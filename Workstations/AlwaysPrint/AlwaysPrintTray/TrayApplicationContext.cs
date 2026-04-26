using System;
using System.Drawing;
using System.ServiceProcess;
using System.Threading;
using System.Windows.Forms;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Messages;
using AlwaysPrintTray.Bootstrap;
using AlwaysPrintTray.Forms;
using AlwaysPrintTray.Pipe;

namespace AlwaysPrintTray
{
    /// <summary>
    /// Main application context. Owns the tray icon, menu, pipe connection, and bootstrap sequence.
    /// </summary>
    public sealed class TrayApplicationContext : ApplicationContext
    {
        private const string ServiceName = "AlwaysPrintService";

        private readonly NotifyIcon  _trayIcon;
        private readonly PipeClient  _pipe;
        private readonly RegistryConfigManager _registry = new RegistryConfigManager();
        private readonly CancellationTokenSource _cts = new CancellationTokenSource();

        // Capturado en el constructor (hilo UI) para hacer marshal seguro desde hilos de fondo.
        private readonly SynchronizationContext _uiContext;

        public TrayApplicationContext()
        {
            // SynchronizationContext.Current es el WindowsFormsSynchronizationContext del hilo UI
            // en este punto, ya que Application.Run aún no ha arrancado pero el hilo es STA.
            // Si fuera null (improbable en WinForms), usamos un fallback que invoca directamente.
            _uiContext = SynchronizationContext.Current ?? new SynchronizationContext();

            _pipe     = new PipeClient();
            _trayIcon = BuildTrayIcon();

            // Run bootstrap off the UI thread so the tray appears immediately.
            var t = new Thread(BootstrapSequence)
            {
                IsBackground = true,
                Name = "AlwaysPrint-TrayBootstrap"
            };
            t.Start();
            
            // Run monitoring loop to keep the tray alive and responsive.
            var monitorThread = new Thread(MonitoringLoop)
            {
                IsBackground = true,
                Name = "AlwaysPrint-TrayMonitor"
            };
            monitorThread.Start();
        }

        private NotifyIcon BuildTrayIcon()
        {
            var icon = new NotifyIcon
            {
                Icon    = SystemIcons.Application,   // replace with embedded resource icon
                Visible = true,
                Text    = "AlwaysPrint"
            };

            var menu = new ContextMenuStrip();
            menu.Items.Add("Acerca de",            null, (_, __) => ShowAbout());
            menu.Items.Add("Configuración de Valores", null, (_, __) => ShowConfiguration());
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add("Salir",                null, (_, __) => ExitApplication());

            icon.ContextMenuStrip = menu;
            icon.DoubleClick      += (_, __) => ShowAbout();
            return icon;
        }

        private void BootstrapSequence()
        {
            string logFile = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "AlwaysPrintTray.log");
            try
            {
                AppendLog(logFile, $"Bootstrap iniciado");

                // 1. Verify the service is running.
                bool serviceRunning = IsServiceRunning();
                AppendLog(logFile, $"Servicio corriendo: {serviceRunning}");
                
                if (!serviceRunning)
                {
                    ShowBalloon("AlwaysPrint",
                        "El servicio AlwaysPrintService no está en ejecución.", ToolTipIcon.Error);
                    EventLogWriter.WriteTrayError("Tray: AlwaysPrintService is not running. Exiting.",
                        EventLogWriter.EvtGenericError);
                    AppendLog(logFile, $"Servicio no corriendo, saliendo");
                    ExitApplication();
                    return;
                }

                // 2. Connect to the Named Pipe within 60 s, with retries.
                AppendLog(logFile, $"Intentando conectar al pipe");
                bool connected = false;
                int maxRetries = 5;
                int retryCount = 0;
                
                while (!connected && retryCount < maxRetries && !_cts.Token.IsCancellationRequested)
                {
                    connected = _pipe.Connect();
                    AppendLog(logFile, $"Intento {retryCount + 1}/{maxRetries}: {(connected ? "éxito" : "fallo")}");
                    
                    if (!connected && retryCount < maxRetries - 1)
                    {
                        AppendLog(logFile, $"Esperando 1 segundo antes de reintentar...");
                        Thread.Sleep(1000);
                    }
                    retryCount++;
                }
                
                if (!connected)
                {
                    ShowBalloon("AlwaysPrint",
                        "No se pudo conectar al servicio. Verifique que esté en ejecución.", ToolTipIcon.Error);
                    EventLogWriter.WriteTrayError("Tray: cannot connect to pipe after retries. Exiting.", EventLogWriter.EvtGenericError);
                    AppendLog(logFile, $"No se pudo conectar después de {maxRetries} intentos, saliendo");
                    ExitApplication();
                    return;
                }

                // 3. Read configuration.
                var cfg = _registry.Load();

                // 4. Perform domain health check.
                AppendLog(logFile, $"Iniciando health check");
                var (success, domain, details) = DomainHealthChecker.CheckAll(cfg.BootstrapDomains, _cts.Token);
                AppendLog(logFile, $"Health check: {success}, domain={domain}, details={details}");

                // 5. Notify service of initialization result.
                var initPayload = new TrayInitializedPayload
                {
                    Success = success,
                    Details = success ? $"OK via {domain}" : details
                };
                AppendLog(logFile, $"Enviando TrayInitialized");
                _pipe.Send(PipeMessage.Create(MessageType.TrayInitialized, initPayload));
                AppendLog(logFile, $"TrayInitialized enviado");

                if (success)
                {
                    ShowBalloon("AlwaysPrint", $"Inicializado correctamente ({domain}).", ToolTipIcon.Info);
                    EventLogWriter.WriteTrayInfo($"Tray initialized successfully. Domain={domain}",
                        EventLogWriter.EvtTrayStarted);
                }
                else
                {
                    ShowBalloon("AlwaysPrint",
                        "No se pudo contactar el servidor de licencias. Operando en modo local.",
                        ToolTipIcon.Warning);
                    EventLogWriter.WriteTrayWarning($"Tray: bootstrap failed. {details}", EventLogWriter.EvtGenericWarning);
                }
            }
            catch (OperationCanceledException) { /* normal shutdown */ }
            catch (Exception ex)
            {
                AppendLog(logFile, $"Error: {ex}");
                EventLogWriter.WriteTrayError("Tray bootstrap sequence failed.", ex, EventLogWriter.EvtGenericError);
            }
        }

        private static void AppendLog(string logFile, string message)
        {
            try
            {
                System.IO.File.AppendAllText(logFile, $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] {message}\n");
            }
            catch
            {
                // Ignorar errores de escritura de log
            }
        }

        private static bool IsServiceRunning()
        {
            try
            {
                using var sc = new ServiceController(ServiceName);
                return sc.Status == ServiceControllerStatus.Running;
            }
            catch { return false; }
        }

        private void ShowAbout()
        {
            using var form = new AboutForm();
            form.ShowDialog();
        }

        private void ShowConfiguration()
        {
            if (!_pipe.IsConnected && !_pipe.Connect())
            {
                MessageBox.Show("No hay conexión con el servicio. Intente de nuevo.",
                    "AlwaysPrint", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            using var form = new ConfigurationForm(_pipe);
            form.ShowDialog();
        }

        private void ExitApplication()
        {
            // Puede llamarse desde el hilo de bootstrap; Application.Exit debe ejecutarse en el UI thread.
            _cts.Cancel();
            _uiContext.Post(_ =>
            {
                _trayIcon.Visible = false;
                _trayIcon.Dispose();
                _pipe.Dispose();
                Application.Exit();
            }, null);
        }

        private void ShowBalloon(string title, string message, ToolTipIcon icon)
        {
            // Siempre hacer marshal al hilo UI mediante el SynchronizationContext capturado
            // en el constructor. Post es fire-and-forget; no bloquea el hilo de fondo.
            _uiContext.Post(_ => _trayIcon.ShowBalloonTip(5000, title, message, icon), null);
        }

        private void MonitoringLoop()
        {
            string logFile = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "AlwaysPrintTray.log");
            System.IO.File.AppendAllText(logFile, $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] MonitoringLoop iniciado\n");
            
            while (!_cts.Token.IsCancellationRequested)
            {
                try
                {
                    // Esperar 30 segundos o hasta que se cancele
                    _cts.Token.WaitHandle.WaitOne(TimeSpan.FromSeconds(30));
                    
                    if (_cts.Token.IsCancellationRequested) break;
                    
                    // Heartbeat: verificar que el servicio sigue activo
                    if (_pipe.IsConnected)
                    {
                        bool alive = _pipe.Ping();
                        if (!alive)
                        {
                            System.IO.File.AppendAllText(logFile, $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] Servicio no responde al ping\n");
                        }
                    }
                }
                catch (Exception ex)
                {
                    System.IO.File.AppendAllText(logFile, $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] MonitoringLoop error: {ex.Message}\n");
                }
            }
            System.IO.File.AppendAllText(logFile, $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] MonitoringLoop finalizado\n");
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                _cts.Cancel();
                _trayIcon?.Dispose();
                _pipe?.Dispose();
                _cts.Dispose();
            }
            base.Dispose(disposing);
        }
    }
}
