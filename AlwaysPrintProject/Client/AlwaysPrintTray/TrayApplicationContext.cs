using System;
using System.Drawing;
using System.ServiceProcess;
using System.Threading;
using System.Windows.Forms;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Messages;
using AlwaysPrintTray.Bootstrap;
using AlwaysPrintTray.Cloud;
using AlwaysPrintTray.Forms;
using AlwaysPrintTray.Localization;
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

        // Integración Cloud (null si CloudEnabled=0 o CloudApiUrl vacía)
        private CloudManager? _cloudManager;
        private CloudRegistration? _cloudRegistration;

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
                Icon    = LoadIconFromResource(),
                Visible = true,
                Text    = LocalizationManager.Get("TrayTooltip")
            };

            var menu = new ContextMenuStrip();
            menu.Items.Add(LocalizationManager.Get("MenuAbout"),         null, (_, __) => ShowAbout());
            menu.Items.Add(LocalizationManager.Get("MenuConfiguration"), null, (_, __) => ShowConfiguration());
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add(LocalizationManager.Get("MenuExit"),          null, (_, __) => ExitApplication());

            icon.ContextMenuStrip = menu;
            icon.DoubleClick     += (_, __) => ShowAbout();
            return icon;
        }

        private static Icon LoadIconFromResource()
        {
            try
            {
                // Intentar cargar el icono desde el recurso embebido
                var assembly = typeof(TrayApplicationContext).Assembly;
                using var stream = assembly.GetManifestResourceStream("AlwaysPrintTray.Resources.logo.ico");
                if (stream != null)
                {
                    return new Icon(stream);
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning($"No se pudo cargar logo.ico: {ex.Message}");
            }

            // Fallback al icono del sistema
            return SystemIcons.Application;
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
                    ShowBalloon("AlwaysPrint", LocalizationManager.Get("BalloonServiceNotRunning"), ToolTipIcon.Error);
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
                    ShowBalloon("AlwaysPrint", string.Format(LocalizationManager.Get("BalloonInitOk"), domain), ToolTipIcon.Info);
                    AlwaysPrintLogger.WriteTrayInfo($"Tray inicializado correctamente. Domain={domain}",
                        AlwaysPrintLogger.EvtTrayStarted);
                }
                else
                {
                    ShowBalloon("AlwaysPrint",
                        LocalizationManager.Get("BalloonInitFail"), ToolTipIcon.Warning);
                    AlwaysPrintLogger.WriteTrayWarning($"Tray: bootstrap fallido. {details}", AlwaysPrintLogger.EvtGenericWarning);
                }

                // 6. Iniciar integración Cloud si está habilitada
                if (cfg.CloudEnabled && !string.IsNullOrWhiteSpace(cfg.CloudApiUrl))
                {
                    try
                    {
                        var credentials = new CloudCredentialsManager();
                        _cloudManager = new CloudManager(cfg, credentials, _pipe, _uiContext, _trayIcon);
                        _cloudManager.Start();
                        AlwaysPrintLogger.WriteTrayInfo("CloudManager iniciado correctamente.");
                    }
                    catch (Exception exCloud)
                    {
                        AlwaysPrintLogger.WriteTrayError(
                            $"Error iniciando CloudManager. Operando en modo local. {exCloud.Message}");
                        _cloudManager = null;
                    }
                }
                else
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        "Integración Cloud deshabilitada (CloudEnabled=0 o CloudApiUrl vacía). " +
                        "Iniciando ciclo de registro automático...");
                    
                    // Iniciar ciclo de registro automático
                    try
                    {
                        _cloudRegistration = new CloudRegistration(cfg);
                        _cloudRegistration.RegistrationSuccessful += OnCloudRegistrationSuccessful;
                        AlwaysPrintLogger.WriteTrayInfo("CloudRegistration iniciado correctamente.");
                    }
                    catch (Exception exReg)
                    {
                        AlwaysPrintLogger.WriteTrayError(
                            $"Error iniciando CloudRegistration. {exReg.Message}");
                        _cloudRegistration = null;
                    }
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
            _uiContext.Post(_ =>
            {
                // Configurar el icono del balloon tip para que use el icono del tray
                _trayIcon.BalloonTipIcon = icon;
                _trayIcon.BalloonTipTitle = title;
                _trayIcon.BalloonTipText = message;
                _trayIcon.ShowBalloonTip(5000);
            }, null);
        }
        
        /// <summary>
        /// Callback que se ejecuta cuando el registro en la cloud es exitoso.
        /// Envía actualización de configuración al Service vía Named Pipe para activar CloudEnabled y CloudApiUrl.
        /// El Service es quien escribe en HKLM (tiene permisos administrativos).
        /// </summary>
        private void OnCloudRegistrationSuccessful(string workstationId, string accountId, string accountName, string cloudApiUrl)
        {
            AlwaysPrintLogger.WriteTrayInfo(
                $"OnCloudRegistrationSuccessful: " +
                $"workstation_id={workstationId}, " +
                $"account_id={accountId}, " +
                $"account_name={accountName}, " +
                $"cloud_api_url={cloudApiUrl}");
            
            try
            {
                // 1. Leer configuración actual
                var cfg = _registry.Load();
                
                // 2. Actualizar campos de Cloud
                cfg.CloudEnabled = true;
                cfg.CloudApiUrl = cloudApiUrl;
                
                AlwaysPrintLogger.WriteTrayInfo(
                    $"OnCloudRegistrationSuccessful: enviando actualización al Service: " +
                    $"CloudEnabled=1, CloudApiUrl={cloudApiUrl}");
                
                // 3. Enviar actualización al Service vía Named Pipe
                // El Service es quien escribe en HKLM (tiene permisos administrativos)
                var updatePayload = new UpdateConfigurationPayload { Configuration = cfg };
                var request = PipeMessage.Create(MessageType.UpdateConfiguration, updatePayload);
                var response = _pipe.Send(request);
                
                if (response?.Type == MessageType.Ack)
                {
                    var ack = response.GetPayload<AckPayload>();
                    if (ack?.Success == true)
                    {
                        AlwaysPrintLogger.WriteTrayInfo(
                            "OnCloudRegistrationSuccessful: configuración actualizada por el Service en HKLM");
                        
                        // 4. Detener CloudRegistration
                        if (_cloudRegistration != null)
                        {
                            _cloudRegistration.RegistrationSuccessful -= OnCloudRegistrationSuccessful;
                            _cloudRegistration.Dispose();
                            _cloudRegistration = null;
                            AlwaysPrintLogger.WriteTrayInfo(
                                "OnCloudRegistrationSuccessful: CloudRegistration detenido");
                        }
                        
                        // 5. Iniciar CloudManager con la configuración actualizada
                        var credentials = new CloudCredentialsManager();
                        _cloudManager = new CloudManager(cfg, credentials, _pipe, _uiContext, _trayIcon);
                        _cloudManager.Start();
                        
                        AlwaysPrintLogger.WriteTrayInfo(
                            "OnCloudRegistrationSuccessful: CloudManager iniciado correctamente");
                        
                        // 6. Mostrar notificación al usuario
                        ShowBalloon(
                            "AlwaysPrint",
                            $"¡Registro exitoso! Conectado a {accountName}",
                            ToolTipIcon.Info);
                    }
                    else
                    {
                        AlwaysPrintLogger.WriteError(
                            $"OnCloudRegistrationSuccessful: error al actualizar configuración en Service: {ack?.Message}",
                            AlwaysPrintLogger.EvtGenericError);
                        
                        ShowBalloon(
                            "AlwaysPrint",
                            "Error al activar integración Cloud. Revise los logs.",
                            ToolTipIcon.Error);
                    }
                }
                else
                {
                    AlwaysPrintLogger.WriteError(
                        "OnCloudRegistrationSuccessful: no se recibió confirmación del Service",
                        AlwaysPrintLogger.EvtGenericError);
                    
                    ShowBalloon(
                        "AlwaysPrint",
                        "Error al comunicarse con el servicio. Revise los logs.",
                        ToolTipIcon.Error);
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"OnCloudRegistrationSuccessful: error al activar integración cloud: {ex.Message}",
                    AlwaysPrintLogger.EvtGenericError);
                
                ShowBalloon(
                    "AlwaysPrint",
                    "Error inesperado al activar integración Cloud. Revise los logs.",
                    ToolTipIcon.Error);
            }
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                _cts.Cancel();
                _cloudManager?.Dispose();
                _cloudRegistration?.Dispose();
                _trayIcon?.Dispose();
                _pipe?.Dispose();
                _cts.Dispose();
            }
            base.Dispose(disposing);
        }
    }
}
