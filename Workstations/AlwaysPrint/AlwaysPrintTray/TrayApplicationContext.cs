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
    /// Contexto principal del Tray. Gestiona el ícono, menú, conexión al pipe y secuencia de bootstrap.
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
            _uiContext = SynchronizationContext.Current ?? new SynchronizationContext();
            _pipe      = new PipeClient();
            _trayIcon  = BuildTrayIcon();

            // Bootstrap en hilo de fondo para que el ícono aparezca de inmediato.
            new Thread(BootstrapSequence) { IsBackground = true, Name = "AlwaysPrint-TrayBootstrap" }.Start();

            // Loop de monitoreo para mantener el Tray activo.
            new Thread(MonitoringLoop) { IsBackground = true, Name = "AlwaysPrint-TrayMonitor" }.Start();
        }

        private NotifyIcon BuildTrayIcon()
        {
            var icon = new NotifyIcon
            {
                Icon    = SystemIcons.Application,
                Visible = true,
                Text    = "AlwaysPrint"
            };

            var menu = new ContextMenuStrip();
            menu.Items.Add("Acerca de",                null, (_, __) => ShowAbout());
            menu.Items.Add("Configuración de Valores", null, (_, __) => ShowConfiguration());
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add("Salir",                    null, (_, __) => ExitApplication());

            icon.ContextMenuStrip = menu;
            icon.DoubleClick     += (_, __) => ShowAbout();
            return icon;
        }

        private void BootstrapSequence()
        {
            try
            {
                AlwaysPrintLogger.WriteTrayInfo("Bootstrap iniciado.");

                // 1. Verificar que el servicio esté corriendo.
                bool serviceRunning = IsServiceRunning();
                AlwaysPrintLogger.WriteTrayInfo($"Servicio corriendo: {serviceRunning}");

                if (!serviceRunning)
                {
                    ShowBalloon("AlwaysPrint", "El servicio AlwaysPrintService no está en ejecución.", ToolTipIcon.Error);
                    AlwaysPrintLogger.WriteTrayError("Tray: AlwaysPrintService no está en ejecución. Saliendo.",
                        AlwaysPrintLogger.EvtGenericError);
                    ExitApplication();
                    return;
                }

                // 2. Conectar al Named Pipe con reintentos.
                AlwaysPrintLogger.WriteTrayInfo("Intentando conectar al pipe...");
                bool connected = false;
                int maxRetries = 5;

                for (int i = 0; i < maxRetries && !_cts.Token.IsCancellationRequested; i++)
                {
                    connected = _pipe.Connect();
                    AlwaysPrintLogger.WriteTrayInfo($"Intento {i + 1}/{maxRetries}: {(connected ? "éxito" : "fallo")}");
                    if (connected) break;
                    if (i < maxRetries - 1) Thread.Sleep(1000);
                }

                if (!connected)
                {
                    ShowBalloon("AlwaysPrint", "No se pudo conectar al servicio. Verifique que esté en ejecución.", ToolTipIcon.Error);
                    AlwaysPrintLogger.WriteTrayError($"Tray: no se pudo conectar al pipe después de {maxRetries} intentos. Saliendo.",
                        AlwaysPrintLogger.EvtGenericError);
                    ExitApplication();
                    return;
                }

                // 3. Leer configuración.
                var cfg = _registry.Load();

                // 4. Health check de dominio.
                AlwaysPrintLogger.WriteTrayInfo("Iniciando health check...");
                var (success, domain, details) = DomainHealthChecker.CheckAll(cfg.BootstrapDomains, _cts.Token);
                AlwaysPrintLogger.WriteTrayInfo($"Health check: success={success}, domain={domain}, details={details}");

                // 5. Notificar al servicio el resultado de la inicialización.
                var initPayload = new TrayInitializedPayload
                {
                    Success = success,
                    Details = success ? $"OK via {domain}" : details
                };
                AlwaysPrintLogger.WriteTrayInfo("Enviando TrayInitialized...");
                _pipe.Send(PipeMessage.Create(MessageType.TrayInitialized, initPayload));
                AlwaysPrintLogger.WriteTrayInfo("TrayInitialized enviado.");

                if (success)
                {
                    ShowBalloon("AlwaysPrint", $"Inicializado correctamente ({domain}).", ToolTipIcon.Info);
                    AlwaysPrintLogger.WriteTrayInfo($"Tray inicializado correctamente. Domain={domain}",
                        AlwaysPrintLogger.EvtTrayStarted);
                }
                else
                {
                    ShowBalloon("AlwaysPrint",
                        "No se pudo contactar el servidor de licencias. Operando en modo local.", ToolTipIcon.Warning);
                    AlwaysPrintLogger.WriteTrayWarning($"Tray: bootstrap fallido. {details}", AlwaysPrintLogger.EvtGenericWarning);
                }
            }
            catch (OperationCanceledException) { /* shutdown normal */ }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError("Tray bootstrap sequence falló.", ex, AlwaysPrintLogger.EvtGenericError);
            }
        }

        private void MonitoringLoop()
        {
            AlwaysPrintLogger.WriteTrayInfo("MonitoringLoop iniciado.");

            while (!_cts.Token.IsCancellationRequested)
            {
                try
                {
                    _cts.Token.WaitHandle.WaitOne(TimeSpan.FromSeconds(30));
                    if (_cts.Token.IsCancellationRequested) break;

                    // Heartbeat: verificar que el servicio sigue activo.
                    if (_pipe.IsConnected && !_pipe.Ping())
                        AlwaysPrintLogger.WriteTrayWarning("Servicio no responde al ping.");
                }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteTrayError("MonitoringLoop error.", ex, AlwaysPrintLogger.EvtGenericError);
                }
            }

            AlwaysPrintLogger.WriteTrayInfo("MonitoringLoop finalizado.");
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
            _uiContext.Post(_ => _trayIcon.ShowBalloonTip(5000, title, message, icon), null);
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
