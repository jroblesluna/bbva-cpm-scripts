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

        // Título base para notificaciones — incluye entorno y versión
#if ENV_DEV
        private const string EnvLabel = "dev";
#else
        private const string EnvLabel = "apps";
#endif
        private static readonly string AppTitle = $"alwaysprint.{EnvLabel}.{System.Reflection.Assembly.GetExecutingAssembly().GetName().Version}";

        private readonly NotifyIcon  _trayIcon;
        private readonly PipeClient  _pipe;
        private readonly RegistryConfigManager _registry = new RegistryConfigManager();
        private readonly CancellationTokenSource _cts = new CancellationTokenSource();

        // Capturado en el constructor (hilo UI) para hacer marshal seguro desde hilos de fondo.
        private readonly SynchronizationContext _uiContext;

        // Integración Cloud (null si CloudEnabled=0 o CloudApiUrl vacía)
        private CloudManager? _cloudManager;
        private CloudRegistration? _cloudRegistration;

        // Integración de auto-actualización
        private UpdateChecker? _updateChecker;

        // Flag para detectar si una búsqueda manual encontró actualización
        private volatile bool _manualCheckFoundUpdate;

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
            menu.Items.Add(LocalizationManager.Get("MenuMyPrinters"),    null, (_, __) => ShowMyPrinters());
            menu.Items.Add(LocalizationManager.Get("MenuCheckUpdates"),  null, (_, __) => CheckForUpdatesManual());
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
                    ShowBalloon(AppTitle, LocalizationManager.Get("BalloonServiceNotRunning"), ToolTipIcon.Error);
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
                    ShowBalloon(AppTitle, "No se pudo conectar al servicio. Verifique que esté en ejecución.", ToolTipIcon.Error);
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
                    ShowBalloon(AppTitle, string.Format(LocalizationManager.Get("BalloonInitOk"), domain), ToolTipIcon.Info);
                    AlwaysPrintLogger.WriteTrayInfo($"Tray inicializado correctamente. Domain={domain}",
                        AlwaysPrintLogger.EvtTrayStarted);
                }
                else
                {
                    // Si Cloud está habilitada, no mostrar balloon de "modo local" aquí
                    // porque CloudManager mostrará su propio estado al conectar/fallar
                    if (!cfg.CloudEnabled || string.IsNullOrWhiteSpace(cfg.CloudApiUrl))
                    {
                        ShowBalloon(AppTitle,
                            LocalizationManager.Get("BalloonInitFail"), ToolTipIcon.Warning);
                    }
                    AlwaysPrintLogger.WriteTrayWarning($"Tray: bootstrap fallido. {details}", AlwaysPrintLogger.EvtGenericWarning);
                }

                // 6. Iniciar integración Cloud si está habilitada
                if (cfg.CloudEnabled && !string.IsNullOrWhiteSpace(cfg.CloudApiUrl))
                {
                    try
                    {
                        var credentials = new CloudCredentialsManager();
                        _cloudManager = new CloudManager(cfg, credentials, _pipe, _uiContext, _trayIcon);
                        // Capturar cfg para el callback
                        var cfgForCallback = cfg;
                        _cloudManager.Registered += () => OnCloudManagerRegistered(cfgForCallback);
                        _cloudManager.CheckUpdateRequested += OnCheckUpdateRequested;
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
                        _cloudRegistration.RegistrationPending += OnCloudRegistrationPending;
                        _cloudRegistration.CidrDetectionFailed += OnCidrDetectionFailed;
                        _cloudRegistration.CidrDetectionRecovered += OnCidrDetectionRecovered;
                        AlwaysPrintLogger.WriteTrayInfo("CloudRegistration iniciado correctamente.");
                    }
                    catch (Exception exReg)
                    {
                        AlwaysPrintLogger.WriteTrayError(
                            $"Error iniciando CloudRegistration. {exReg.Message}");
                        _cloudRegistration = null;
                    }
                }

                // 7. Auto-actualización se inicia cuando CloudManager confirme registro exitoso
                // (ver OnCloudManagerRegistered). Si Cloud no está habilitada, no se verifica.
            }
            catch (OperationCanceledException) { /* shutdown normal */ }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError("Tray bootstrap sequence falló.", ex, AlwaysPrintLogger.EvtGenericError);
            }
        }

        /// <summary>
        /// Callback que se ejecuta cuando CloudManager confirma registro exitoso en la Cloud.
        /// Inicia el UpdateChecker solo después de tener conexión autenticada.
        /// Se protege contra invocaciones duplicadas con el guard _updateChecker != null.
        /// </summary>
        private void OnCloudManagerRegistered(AppConfiguration cfg)
        {
            // Evitar inicialización duplicada (el evento puede dispararse en reconexiones)
            if (_updateChecker != null) return;

            AlwaysPrintLogger.WriteTrayInfo(
                "AutoUpdate: conexión Cloud confirmada. Iniciando verificación de actualizaciones.");
            InitializeAutoUpdate(cfg);
        }

        /// <summary>
        /// Callback que se ejecuta cuando se recibe un comando remoto "check_update" desde la Cloud.
        /// Invoca UpdateChecker.CheckNowAsync() si está disponible.
        /// </summary>
        private async void OnCheckUpdateRequested()
        {
            try
            {
                if (_updateChecker == null)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "OnCheckUpdateRequested: UpdateChecker no inicializado. Ignorando comando.");
                    return;
                }

                AlwaysPrintLogger.WriteTrayInfo(
                    "OnCheckUpdateRequested: ejecutando verificación de actualización por comando remoto.");
                await _updateChecker.CheckNowAsync();
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"OnCheckUpdateRequested: error al verificar actualización: {ex.Message}");
            }
        }

        /// <summary>
        /// Callback que se ejecuta cuando CloudRegistration detecta que la IP está pendiente de aprobación.
        /// Muestra un balloon tip informativo y cambia el tooltip del tray.
        /// </summary>
        private void OnCloudRegistrationPending()
        {
            AlwaysPrintLogger.WriteTrayInfo(
                "OnCloudRegistrationPending: IP pública pendiente de aprobación en la Cloud.");

            _uiContext.Post(_ =>
            {
                _trayIcon.Text = "AlwaysPrint (pendiente de aprobación)";
                _trayIcon.ShowBalloonTip(
                    4000,
                    "AlwaysPrint",
                    LocalizationManager.Get("BalloonPendingApproval"),
                    ToolTipIcon.Info);
            }, null);
        }

        /// <summary>
        /// Callback que se ejecuta cuando no se puede detectar el CIDR de la red.
        /// Muestra un balloon tip de error indicando problemas de configuración de red.
        /// </summary>
        private void OnCidrDetectionFailed()
        {
            AlwaysPrintLogger.WriteTrayError(
                "OnCidrDetectionFailed: no se pudo detectar el CIDR de la red. " +
                "Verificar conexión de red (interfaz con gateway).",
                AlwaysPrintLogger.EvtGenericError);

            _uiContext.Post(_ =>
            {
                _trayIcon.Text = "AlwaysPrint (sin red detectada)";
                _trayIcon.ShowBalloonTip(
                    5000,
                    "AlwaysPrint",
                    LocalizationManager.Get("BalloonCidrNotDetected"),
                    ToolTipIcon.Error);
            }, null);
        }

        /// <summary>
        /// Callback que se ejecuta cuando el CIDR se detecta exitosamente después de un fallo previo.
        /// Muestra un balloon tip informativo indicando que la red fue detectada.
        /// </summary>
        private void OnCidrDetectionRecovered()
        {
            AlwaysPrintLogger.WriteTrayInfo(
                "OnCidrDetectionRecovered: CIDR detectado exitosamente después de fallo previo.");

            _uiContext.Post(_ =>
            {
                _trayIcon.Text = LocalizationManager.Get("TrayTooltip");
                _trayIcon.ShowBalloonTip(
                    3000,
                    "AlwaysPrint",
                    LocalizationManager.Get("BalloonCidrDetected"),
                    ToolTipIcon.Info);
            }, null);
        }

        /// <summary>
        /// Inicializa el flujo de auto-actualización. Crea el UpdateChecker, se suscribe
        /// al evento UpdateAvailable y arranca la verificación periódica.
        /// Este método es fire-and-forget: los errores se loggean sin interrumpir el Tray.
        /// </summary>
        private void InitializeAutoUpdate(AppConfiguration cfg)
        {
            try
            {
                // Se requiere CloudApiUrl para verificar actualizaciones
                if (string.IsNullOrWhiteSpace(cfg.CloudApiUrl))
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        "AutoUpdate: no se inicia verificación de actualizaciones (CloudApiUrl no configurada).");
                    return;
                }

                string currentVersion = System.Reflection.Assembly.GetExecutingAssembly()
                    .GetName().Version?.ToString() ?? "0.0.0.0";

                _updateChecker = new UpdateChecker(_registry, cfg.CloudApiUrl, currentVersion);
                _updateChecker.UpdateAvailable += OnUpdateAvailable;
                _updateChecker.Start();

                AlwaysPrintLogger.WriteTrayInfo(
                    $"AutoUpdate: flujo de auto-actualización inicializado. Versión actual: {currentVersion}.");
            }
            catch (Exception ex)
            {
                // Los errores de auto-actualización no deben crashear el Tray
                AlwaysPrintLogger.WriteTrayError(
                    $"AutoUpdate: error al inicializar flujo de auto-actualización: {ex.Message}",
                    AlwaysPrintLogger.EvtGenericError);
                _updateChecker = null;
            }
        }

        /// <summary>
        /// Callback del evento UpdateAvailable. Inicia la descarga del MSI y, al completar,
        /// envía el mensaje InstallUpdate al Service via Named Pipe.
        /// Se ejecuta de forma asíncrona (fire-and-forget) para no bloquear el Tray.
        /// </summary>
        private async void OnUpdateAvailable(UpdateInfo updateInfo)
        {
            try
            {
                // Marcar que se encontró actualización (para búsqueda manual)
                _manualCheckFoundUpdate = true;

                AlwaysPrintLogger.WriteTrayInfo(
                    $"AutoUpdate: actualización disponible detectada. Versión: {updateInfo.Version}, " +
                    $"tamaño: {updateInfo.FileSize} bytes. Iniciando descarga...");

                // Notificar al usuario que se está actualizando
                ShowBalloon(AppTitle,
                    string.Format(LocalizationManager.Get("BalloonUpdating"), updateInfo.Version),
                    ToolTipIcon.Info);

                var stopwatch = System.Diagnostics.Stopwatch.StartNew();

                // Obtener CloudApiUrl de la configuración actual
                var cfg = _registry.Load();
                var downloader = new UpdateDownloader(cfg.CloudApiUrl);

                // Descargar MSI (asíncrono, no bloqueante)
                string? msiPath = await downloader.DownloadAsync(updateInfo.FileSize);

                stopwatch.Stop();

                if (string.IsNullOrEmpty(msiPath))
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"AutoUpdate: descarga fallida para versión {updateInfo.Version}. " +
                        $"Se reintentará en el próximo ciclo de verificación.");
                    return;
                }

                AlwaysPrintLogger.WriteTrayInfo(
                    $"AutoUpdate: descarga completada. Archivo: '{msiPath}', " +
                    $"tamaño: {updateInfo.FileSize} bytes, duración: {stopwatch.Elapsed.TotalSeconds:F1}s.");

                // Enviar mensaje InstallUpdate al Service via Named Pipe
                var installPayload = new InstallUpdatePayload { MsiFilePath = msiPath };
                var request = PipeMessage.Create(MessageType.InstallUpdate, installPayload);

                AlwaysPrintLogger.WriteTrayInfo(
                    $"AutoUpdate: enviando solicitud InstallUpdate al Service. Ruta MSI: '{msiPath}'.");

                var response = _pipe.Send(request);

                if (response == null)
                {
                    AlwaysPrintLogger.WriteTrayError(
                        "AutoUpdate: no se recibió respuesta del Service al enviar InstallUpdate.",
                        AlwaysPrintLogger.EvtGenericError);
                    return;
                }

                if (response.Type == MessageType.InstallUpdateResponse)
                {
                    var result = response.GetPayload<InstallUpdateResponsePayload>();
                    if (result?.Success == true)
                    {
                        AlwaysPrintLogger.WriteTrayInfo(
                            $"AutoUpdate: instalación iniciada exitosamente por el Service. " +
                            $"Versión: {updateInfo.Version}.");
                    }
                    else
                    {
                        AlwaysPrintLogger.WriteTrayError(
                            $"AutoUpdate: el Service reportó error en la instalación. " +
                            $"ExitCode: {result?.ExitCode}, Mensaje: {result?.Message}",
                            AlwaysPrintLogger.EvtGenericError);
                    }
                }
                else if (response.Type == MessageType.Error)
                {
                    var error = response.GetPayload<ErrorPayload>();
                    AlwaysPrintLogger.WriteTrayError(
                        $"AutoUpdate: el Service retornó error. Código: {error?.Code}, Mensaje: {error?.Message}",
                        AlwaysPrintLogger.EvtGenericError);
                }
            }
            catch (Exception ex)
            {
                // Los errores de auto-actualización nunca deben crashear el Tray
                AlwaysPrintLogger.WriteTrayError(
                    $"AutoUpdate: error inesperado durante el flujo de descarga/instalación: {ex.Message}",
                    AlwaysPrintLogger.EvtGenericError);
            }
        }

        /// <summary>
        /// Acción manual del usuario: buscar actualizaciones desde el menú del tray.
        /// Si no hay conexión Cloud, muestra notificación informativa.
        /// Si hay conexión, ejecuta verificación inmediata y notifica resultado.
        /// </summary>
        private async void CheckForUpdatesManual()
        {
            try
            {
                // Si no hay UpdateChecker inicializado, no hay conexión Cloud
                if (_updateChecker == null)
                {
                    ShowBalloon(AppTitle,
                        LocalizationManager.Get("BalloonUpdateNoCloud"),
                        ToolTipIcon.Warning);
                    return;
                }

                AlwaysPrintLogger.WriteTrayInfo("Búsqueda manual de actualizaciones iniciada por el usuario.");

                // Mostrar notificación de que se está buscando
                ShowBalloon(AppTitle,
                    LocalizationManager.Get("BalloonCheckingUpdates"),
                    ToolTipIcon.Info);

                // Resetear flag antes de la verificación
                _manualCheckFoundUpdate = false;

                // Ejecutar verificación inmediata
                await _updateChecker.CheckNowAsync();

                // Si no se disparó el evento UpdateAvailable, no hay actualización disponible
                if (!_manualCheckFoundUpdate)
                {
                    ShowBalloon(AppTitle,
                        LocalizationManager.Get("BalloonNoUpdates"),
                        ToolTipIcon.Info);
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"Error en búsqueda manual de actualizaciones: {ex.Message}",
                    AlwaysPrintLogger.EvtGenericError);
                ShowBalloon(AppTitle,
                    LocalizationManager.Get("BalloonUpdateError"),
                    ToolTipIcon.Error);
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

        private void ShowMyPrinters()
        {
            if (_cloudManager == null || !_cloudManager.IsConnected)
            {
                MessageBox.Show(
                    "No hay conexión con la nube. Verifique su conexión e intente de nuevo.",
                    "Mis Impresoras", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            if (string.IsNullOrEmpty(_cloudManager.WorkstationId))
            {
                MessageBox.Show(
                    "La workstation no está registrada en la nube. Espere a que se complete el registro.",
                    "Mis Impresoras", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }

            if (_cloudManager.HttpClient == null)
            {
                MessageBox.Show(
                    "Error interno: cliente HTTP no disponible.",
                    "Mis Impresoras", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return;
            }

            using var form = new MyPrintersForm(
                _cloudManager.CloudApiUrl,
                _cloudManager.WorkstationId,
                _cloudManager.HttpClient);
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
                $"organization_id={accountId}, " +
                $"organization_name={accountName}, " +
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
                        _cloudManager.CheckUpdateRequested += OnCheckUpdateRequested;
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
                _updateChecker?.Dispose();
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
