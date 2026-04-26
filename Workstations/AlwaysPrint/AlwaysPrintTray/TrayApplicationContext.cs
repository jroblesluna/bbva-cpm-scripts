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
            try
            {
                // 1. Verify the service is running.
                if (!IsServiceRunning())
                {
                    ShowBalloon("AlwaysPrint",
                        "El servicio AlwaysPrintService no está en ejecución.", ToolTipIcon.Error);
                    EventLogWriter.WriteError("Tray: AlwaysPrintService is not running. Exiting.",
                        EventLogWriter.EvtGenericError);
                    ExitApplication();
                    return;
                }

                // 2. Connect to the Named Pipe within 60 s.
                bool connected = _pipe.Connect();
                if (!connected)
                {
                    ShowBalloon("AlwaysPrint",
                        "No se pudo conectar al servicio. Verifique que esté en ejecución.", ToolTipIcon.Error);
                    EventLogWriter.WriteError("Tray: cannot connect to pipe. Exiting.", EventLogWriter.EvtGenericError);
                    ExitApplication();
                    return;
                }

                // 3. Read configuration.
                var cfg = _registry.Load();

                // 4. Perform domain health check.
                var (success, domain, details) = DomainHealthChecker.CheckAll(cfg.BootstrapDomains, _cts.Token);

                // 5. Notify service of initialization result.
                var initPayload = new TrayInitializedPayload
                {
                    Success = success,
                    Details = success ? $"OK via {domain}" : details
                };
                _pipe.Send(PipeMessage.Create(MessageType.TrayInitialized, initPayload));

                if (success)
                {
                    ShowBalloon("AlwaysPrint", $"Inicializado correctamente ({domain}).", ToolTipIcon.Info);
                    EventLogWriter.WriteInfo($"Tray initialized successfully. Domain={domain}",
                        EventLogWriter.EvtTrayStarted);
                }
                else
                {
                    ShowBalloon("AlwaysPrint",
                        "No se pudo contactar el servidor de licencias. Operando en modo local.",
                        ToolTipIcon.Warning);
                    EventLogWriter.WriteWarning($"Tray: bootstrap failed. {details}", EventLogWriter.EvtGenericWarning);
                }
            }
            catch (OperationCanceledException) { /* normal shutdown */ }
            catch (Exception ex)
            {
                EventLogWriter.WriteError("Tray bootstrap sequence failed.", ex, EventLogWriter.EvtGenericError);
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
