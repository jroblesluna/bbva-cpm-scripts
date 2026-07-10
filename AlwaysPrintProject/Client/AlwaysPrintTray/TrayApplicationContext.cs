using System;
using System.Drawing;
using System.IO;
using System.ServiceProcess;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Messages;
using AlwaysPrint.Shared.Security;
using AlwaysPrintTray.Bootstrap;
using AlwaysPrintTray.Cloud;
using AlwaysPrintTray.Connectivity;
using AlwaysPrintTray.Forms;
using AlwaysPrintTray.Localization;
using AlwaysPrintTray.OnDemand;
using AlwaysPrintTray.Pipe;

namespace AlwaysPrintTray
{
    /// <summary>
    /// Contexto principal del Tray. Gestiona el ícono, menú, conexión al pipe y secuencia de bootstrap.
    /// </summary>
    public sealed class TrayApplicationContext : ApplicationContext
    {
        private const string ServiceName = "AlwaysPrintService";

        // Título base para notificaciones
        private const string AppTitle = "APCM";

        private readonly NotifyIcon  _trayIcon;
        private readonly PipeClient  _pipe;
        private readonly RegistryConfigManager _registry = new RegistryConfigManager();
        private readonly CancellationTokenSource _cts = new CancellationTokenSource();

        // Capturado en el constructor (hilo UI) para hacer marshal seguro desde hilos de fondo.
        private readonly SynchronizationContext _uiContext;

        // Integración Cloud (null si CloudEnabled=0 o CloudApiUrl vacía)
        private CloudManager? _cloudManager;
        private CloudRegistration? _cloudRegistration;
        private DateTime? _cloudConnectedAt;

        // Integración de auto-actualización
        private UpdateChecker? _updateChecker;

        // Flag para detectar si una búsqueda manual encontró actualización
        private volatile bool _manualCheckFoundUpdate;

        // Control de instancia única de formularios (evita duplicados)
        private Form? _activeForm;

        // Instancia singleton del StatusForm WPF (null si no está abierto)
        private StatusForm? _statusForm;

        // ID del mensaje Win32 registrado para recibir broadcast ShowStatus desde segunda instancia
        private readonly uint _showStatusMsgId;

        // Ventana oculta que escucha el broadcast Win32 para mostrar StatusForm
        private NativeWindow? _messageWindow;

        // Submenú dinámico de acciones OnDemand y su separador visual
        private ToolStripMenuItem? _onDemandSubmenu;
        private ToolStripSeparator? _onDemandSeparator;

        // Flag para distinguir la primera carga de config (no notificar) de actualizaciones reales
        private bool _firstConfigUpdateReceived;

        // Handler de checks de conectividad (ejecuta verificaciones HTTP por comando del Service)
        private ConnectivityCheckHandler? _connectivityHandler;

        public TrayApplicationContext(uint showStatusMsgId)
        {
            _showStatusMsgId = showStatusMsgId;
            _uiContext = SynchronizationContext.Current ?? new SynchronizationContext();
            _connectivityHandler = new ConnectivityCheckHandler(_uiContext);
            _pipe      = new PipeClient();
            _trayIcon  = BuildTrayIcon();

            // Suscribir a mensajes push del Service (ej: ActionConfigChanged)
            _pipe.MessageReceived += OnPipeMessageReceived;

            // Crear ventana oculta para recibir mensajes broadcast de segunda instancia
            _messageWindow = new BroadcastListener(this, _showStatusMsgId);

            // Bootstrap en hilo de fondo para que el ícono aparezca de inmediato.
            new Thread(BootstrapSequence) { IsBackground = true, Name = "AlwaysPrint-TrayBootstrap" }.Start();

            // Loop de monitoreo para mantener el Tray activo.
            new Thread(MonitoringLoop) { IsBackground = true, Name = "AlwaysPrint-TrayMonitor" }.Start();

            // Mostrar el About automáticamente al iniciar (se cierra solo después de 5 segundos)
            _uiContext.Post(_ => ShowAboutStartup(), null);
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
            menu.Items.Add(LocalizationManager.Get("MenuSystemStatus"),  null, (_, __) => ShowStatusForm());
            menu.Items.Add(LocalizationManager.Get("MenuConfiguration"), null, (_, __) => ShowConfiguration());
            menu.Items.Add(LocalizationManager.Get("MenuMyPrinters"),    null, (_, __) => ShowMyPrinters());
            menu.Items.Add(LocalizationManager.Get("MenuCheckUpdates"),  null, (_, __) => CheckForUpdatesManual());

            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add(LocalizationManager.Get("MenuExit"),          null, (_, __) => ExitApplication());

            icon.ContextMenuStrip = menu;
            icon.DoubleClick     += (_, __) => ShowStatusForm();
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

                // 3.5 Construir submenú OnDemand desde la configuración activa
                _uiContext.Post(_ => RebuildOnDemandSubmenu(), null);

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

                // 5.5. Aplicar jitter de arranque si corresponde (post-update o post-restart reciente)
                try
                {
                    int jitterWindow = _registry.LoadJitterWindowSeconds();
                    DateTime? lastUpdate = _registry.LoadLastUpdateTimestamp();
                    DateTime? lastRestart = _registry.LoadLastRestartTimestamp();

                    var (delayMs, reason) = JitterCalculator.ComputeStartupDelay(
                        DateTime.UtcNow, lastUpdate, lastRestart, jitterWindow);

                    if (delayMs > 0 && reason != null)
                    {
                        double delaySec = delayMs / 1000.0;
                        AlwaysPrintLogger.WriteTrayInfo(
                            $"Aplicando jitter de {delaySec:F1}s por {reason}");
                        Thread.Sleep(delayMs);
                    }
                }
                catch (Exception exJitter)
                {
                    // Fail-open: si hay error en el cálculo de jitter, conectar sin delay
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"Error calculando jitter de arranque, conectando sin delay: {exJitter.Message}",
                        AlwaysPrintLogger.EvtGenericWarning);
                }

                // 6. Iniciar integración Cloud si está habilitada
                if (cfg.CloudEnabled && !string.IsNullOrWhiteSpace(cfg.CloudApiUrl))
                {
                    try
                    {
                        var credentials = new CloudCredentialsManager();
                        _cloudManager = new CloudManager(cfg, credentials, _registry, _pipe, _uiContext, _trayIcon);
                        // Capturar cfg para el callback
                        var cfgForCallback = cfg;
                        _cloudManager.Registered += () => OnCloudManagerRegistered(cfgForCallback);
                        _cloudManager.CheckUpdateRequested += OnCheckUpdateRequested;
                        _cloudManager.ActionConfigUpdated += OnActionConfigUpdated;
                        _cloudManager.Start();
                        SubscribeOfflineStateManager(_cloudManager);
                        _cloudConnectedAt = DateTime.UtcNow;
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
                        _cloudRegistration.ConnectivityStateChanged += OnCloudConnectivityStateChanged;
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
        /// Callback que se ejecuta cuando CloudManager descarga/actualiza la configuración de acciones.
        /// Reconstruye el submenú OnDemand para reflejar los nuevos triggers disponibles.
        /// Muestra notificación balloon en actualizaciones posteriores a la primera carga.
        /// </summary>
        private void OnActionConfigUpdated(string configName, string configHash)
        {
            AlwaysPrintLogger.WriteTrayInfo(
                "OnActionConfigUpdated: configuración de acciones actualizada desde Cloud. Reconstruyendo submenú OnDemand.");

            _uiContext.Post(_ =>
            {
                try
                {
                    OnDemandConfigReader.Reload();
                    RebuildOnDemandSubmenu();

                    // Refrescar StatusForm si está abierto
                    if (_statusForm != null && !_statusForm.IsDisposed)
                    {
                        _statusForm.RefreshActionConfigInfo();
                    }

                    if (_firstConfigUpdateReceived)
                    {
                        // Solo notificar en actualizaciones posteriores (no en primera carga)
                        ShowBalloon(AppTitle,
                            $"Configuración actualizada: {configName}",
                            ToolTipIcon.Info);
                    }
                    _firstConfigUpdateReceived = true;
                }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteTrayError(
                        $"OnActionConfigUpdated: error reconstruyendo submenú OnDemand. {ex.Message}",
                        AlwaysPrintLogger.EvtGenericError);
                }
            }, null);
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
        /// Callback de cambio de estado de conectividad Cloud.
        /// Actualiza el StatusForm si está abierto (push en tiempo real).
        /// </summary>
        private void OnCloudConnectivityStateChanged(CloudConnectivityState state)
        {
            // Si el StatusForm está abierto, enviar la actualización en tiempo real
            var form = _statusForm;
            if (form != null && !form.IsDisposed)
            {
                form.UpdateCloudConnectivity(state);
            }
        }

        /// <summary>
        /// Suscribe al evento StateChanged del OfflineStateManager de un CloudManager
        /// para push de estado al StatusForm cuando el WebSocket se desconecta/reconecta.
        /// </summary>
        private void SubscribeOfflineStateManager(CloudManager manager)
        {
            var offlineMgr = manager.GetOfflineStateManager();
            if (offlineMgr == null) return;

            offlineMgr.StateChanged += OnOfflineStateChanged;
        }

        /// <summary>
        /// Callback de cambio de estado online/offline del WebSocket (post-registro).
        /// Traduce el estado del OfflineStateManager a CloudConnectivityState y
        /// actualiza el StatusForm si está abierto.
        /// </summary>
        private void OnOfflineStateChanged(bool isOffline, DateTime? disconnectedSince)
        {
            // Al reconectar, actualizar timestamp de conexión
            if (!isOffline)
                _cloudConnectedAt = DateTime.UtcNow;

            var state = new CloudConnectivityState
            {
                Status = isOffline ? "Disconnected" : "Connected",
                FailedAttempts = 0,
                DisconnectedSince = disconnectedSince,
                ConnectedSince = isOffline ? null : _cloudConnectedAt,
                LastError = isOffline ? "WebSocket desconectado" : null,
                CurrentRetryIntervalSeconds = 0
            };

            var form = _statusForm;
            if (form != null && !form.IsDisposed)
            {
                form.UpdateCloudConnectivity(state);
            }
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

                // Obtener CloudApiUrl: preferir la del CloudManager (ya en memoria y validada)
                // porque el registro puede no estar actualizado aún (race condition con el Service).
                string cloudApiUrl = _cloudManager?.CloudApiUrl ?? _registry.Load().CloudApiUrl;
                if (string.IsNullOrWhiteSpace(cloudApiUrl))
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "AutoUpdate: CloudApiUrl no disponible al intentar descargar. " +
                        "Se reintentará en el próximo ciclo de verificación.");
                    return;
                }
                var downloader = new UpdateDownloader(cloudApiUrl);

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
        /// Usa GetCachedState() como fuente primaria de estado del servidor.
        /// Si no hay estado cacheado (primer inicio o reconexión pendiente),
        /// hace un solo request HTTP fallback al backend.
        /// Compara estado local vs cacheado/recibido y descarga desde S3 lo que difiera.
        /// </summary>
        private async void CheckForUpdatesManual()
        {
            try
            {
                // Si no hay CloudManager inicializado, no hay conexión Cloud
                if (_cloudManager == null)
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

                // 1. Obtener estado de distribución fresco del backend (no usar caché).
                // El usuario explícitamente quiere verificar si hay algo nuevo — el caché
                // puede tener datos obsoletos si el push no llegó (ej: MSI subido después de connect).
                DistributionState? state = await FetchDistributionStateFromBackend();

                // Si el backend no responde, usar caché como fallback
                if (state == null)
                {
                    state = _cloudManager.GetCachedState();
                    if (state != null)
                    {
                        AlwaysPrintLogger.WriteTrayInfo(
                            "Buscar Actualizaciones: backend no respondió, usando estado cacheado como fallback.");
                    }
                }

                if (state == null)
                {
                    // Ni backend ni caché disponible — notificar al usuario
                    AlwaysPrintLogger.WriteTrayWarning(
                        "Buscar Actualizaciones: no se pudo obtener estado del servidor (backend y caché no disponibles).");
                    ShowBalloon(AppTitle,
                        "No se pudo obtener estado del servidor. Verifique la conexión.",
                        ToolTipIcon.Warning);
                    return;
                }

                // 2. Comparar estado local vs remoto y descargar desde S3 lo que difiera
                AlwaysPrintLogger.WriteTrayInfo(
                    $"Buscar Actualizaciones: comparando estado local vs remoto. " +
                    $"ConfigHash={state.ConfigHash ?? "null"}, CertVersion={state.CertVersion}, " +
                    $"MsiVersion={state.MsiVersion ?? "null"}");

                int updatedCount = await _cloudManager.SyncFromCachedStateAsync(state);

                if (updatedCount > 0)
                {
                    ShowBalloon(AppTitle,
                        $"Se actualizaron {updatedCount} componente(s).",
                        ToolTipIcon.Info);
                }
                else
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

        /// <summary>
        /// Fallback HTTP: obtiene el estado de distribución completo desde el backend
        /// cuando no hay estado cacheado (primer inicio o reconexión pendiente).
        /// Realiza UN solo request HTTP al endpoint /api/v1/workstations/{id}/distribution-state.
        /// </summary>
        /// <returns>DistributionState con los datos del servidor, o null si falla.</returns>
        private async Task<DistributionState> FetchDistributionStateFromBackend()
        {
            try
            {
                var httpClient = _cloudManager?.HttpClient;
                var workstationId = _cloudManager?.WorkstationId;

                if (httpClient == null || string.IsNullOrEmpty(workstationId))
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "FetchDistributionState: HttpClient o WorkstationId no disponible. " +
                        "No se puede hacer fallback HTTP.");
                    return null;
                }

                string url = $"{_cloudManager.CloudApiUrl.TrimEnd('/')}/api/v1/workstations/{workstationId}/distribution-state";

                AlwaysPrintLogger.WriteTrayInfo(
                    $"FetchDistributionState: solicitando estado al backend. URL={url}");

                var response = await httpClient.GetAsync(url);

                if (!response.IsSuccessStatusCode)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"FetchDistributionState: backend retornó HTTP {(int)response.StatusCode}. " +
                        "No se pudo obtener estado de distribución.");
                    return null;
                }

                string json = await response.Content.ReadAsStringAsync();
                var data = Newtonsoft.Json.Linq.JObject.Parse(json);

                var distributionState = new DistributionState
                {
                    ConfigHash = data["config_hash"]?.ToString(),
                    ConfigS3Url = data["config_s3_url"]?.ToString(),
                    CertVersion = data["cert_version"]?.ToObject<int>() ?? 0,
                    CertUrl = data["cert_url"]?.ToString(),
                    MsiVersion = data["msi_version"]?.ToString(),
                    MsiUrl = data["msi_url"]?.ToString(),
                    LastUpdated = DateTime.UtcNow
                };

                AlwaysPrintLogger.WriteTrayInfo(
                    $"FetchDistributionState: estado obtenido exitosamente desde backend. " +
                    $"ConfigHash={distributionState.ConfigHash ?? "null"}, " +
                    $"CertVersion={distributionState.CertVersion}, " +
                    $"MsiVersion={distributionState.MsiVersion ?? "null"}");

                return distributionState;
            }
            catch (System.Net.Http.HttpRequestException ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"FetchDistributionState: error de red al contactar backend: {ex.Message}");
                return null;
            }
            catch (TaskCanceledException)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    "FetchDistributionState: timeout al contactar backend.");
                return null;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"FetchDistributionState: error inesperado: {ex.Message}",
                    AlwaysPrintLogger.EvtGenericError);
                return null;
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

                    if (!_pipe.IsConnected)
                    {
                        // Pipe desconectado — intentar reconexión
                        AlwaysPrintLogger.WriteTrayInfo("MonitoringLoop: pipe desconectado, intentando reconexión...");
                        if (_pipe.Connect())
                        {
                            AlwaysPrintLogger.WriteTrayInfo("MonitoringLoop: reconexión exitosa.");
                        }
                        else
                        {
                            AlwaysPrintLogger.WriteTrayWarning(
                                "MonitoringLoop: reconexión fallida. Se reintentará en 30s.",
                                AlwaysPrintLogger.EvtGenericWarning);
                        }
                    }
                    else if (!_pipe.Ping())
                    {
                        AlwaysPrintLogger.WriteTrayWarning("Servicio no responde al ping.");
                    }
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
            // Si ya hay un formulario abierto, traerlo al frente y no abrir otro
            if (_activeForm != null && !_activeForm.IsDisposed)
            {
                _activeForm.Activate();
                return;
            }

            var form = new AboutForm();
            _activeForm = form;
            form.FormClosed += (_, __) => _activeForm = null;
            form.ShowDialog();
        }

        /// <summary>
        /// Muestra el About al startup con auto-cierre rápido (5s).
        /// No bloquea interacción ni se asigna a _activeForm.
        /// </summary>
        private void ShowAboutStartup()
        {
            var form = new AboutForm(isStartup: true);
            form.TopMost = true;  // Asegurar que aparezca visible
            form.Show();
            // No asignar a _activeForm para no bloquear interacción
        }

        private void ShowMyPrinters()
        {
            // Si ya hay un formulario abierto, traerlo al frente y no abrir otro
            if (_activeForm != null && !_activeForm.IsDisposed)
            {
                _activeForm.Activate();
                return;
            }

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

            var form = new MyPrintersForm(
                _cloudManager.CloudApiUrl,
                _cloudManager.WorkstationId,
                _cloudManager.HttpClient);
            _activeForm = form;
            form.FormClosed += (_, __) => _activeForm = null;
            form.ShowDialog();
        }

        private void ShowConfiguration()
        {
            // Si ya hay un formulario abierto, traerlo al frente y no abrir otro
            if (_activeForm != null && !_activeForm.IsDisposed)
            {
                _activeForm.Activate();
                return;
            }

            if (!_pipe.IsConnected && !_pipe.Connect())
            {
                MessageBox.Show("No hay conexión con el servicio. Intente de nuevo.",
                    "AlwaysPrint", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            var form = new ConfigurationForm(_pipe);
            _activeForm = form;
            form.FormClosed += (_, __) => _activeForm = null;
            form.ShowDialog();
        }

        private void ExecuteOnDemandTrigger(OnDemandTriggerInfo trigger)
        {
            // Confirmación del usuario
            var result = MessageBox.Show(
                trigger.Description,
                trigger.Label,
                MessageBoxButtons.OKCancel,
                MessageBoxIcon.Question);

            if (result != DialogResult.OK) return;

            if (!_pipe.IsConnected && !_pipe.Connect())
            {
                MessageBox.Show("No hay conexión con el servicio. Intente de nuevo.",
                    "AlwaysPrint", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            var payload = new ExecuteOnDemandTriggerPayload { Label = trigger.Label };
            var request = PipeMessage.Create(MessageType.ExecuteOnDemandTrigger, payload);
            var response = _pipe.Send(request);

            if (response?.Type == MessageType.Ack)
            {
                var ack = response.GetPayload<AckPayload>();
                if (ack?.Success == true)
                {
                    MessageBox.Show($"✓ {trigger.Label} ejecutado correctamente.",
                        "OK", MessageBoxButtons.OK, MessageBoxIcon.Information);
                }
                else
                {
                    MessageBox.Show($"Error: {ack?.Message ?? "desconocido"}",
                        "Error", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                }
            }
            else
            {
                var error = response?.GetPayload<ErrorPayload>();
                MessageBox.Show($"Error: {error?.Message ?? "respuesta inesperada"}",
                    "Error", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
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
        /// Si la respuesta de registro incluye cert_url/cert_version, descarga el certificado ECDSA.
        /// </summary>
        private async void OnCloudRegistrationSuccessful(string workstationId, string accountId, string accountName, string cloudApiUrl, string? certUrl, int? certVersion)
        {
            AlwaysPrintLogger.WriteTrayInfo(
                $"OnCloudRegistrationSuccessful: " +
                $"workstation_id={workstationId}, " +
                $"organization_id={accountId}, " +
                $"organization_name={accountName}, " +
                $"cloud_api_url={cloudApiUrl}" +
                (certUrl != null ? $", cert_url={certUrl}, cert_version={certVersion}" : ""));
            
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
                        
                        // 4. Descargar certificado ECDSA si está disponible en la respuesta de registro
                        if (!string.IsNullOrEmpty(certUrl) && certVersion.HasValue && certVersion.Value > 0)
                        {
                            string certPath = Path.Combine(
                                Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
                                "AlwaysPrint", "config", "org.cer");
                            
                            bool downloaded = await SignatureVerifier.DownloadCertAsync(certUrl!, certPath, traySource: true);
                            if (downloaded)
                            {
                                // No escribir CertVersion en registro desde el Tray (requiere HKLM/admin).
                                // El Service lo actualizará al cargar y verificar la configuración firmada.
                                AlwaysPrintLogger.WriteTrayInfo(
                                    $"OnCloudRegistrationSuccessful: certificado ECDSA descargado (versión {certVersion.Value})");
                            }
                            else
                            {
                                AlwaysPrintLogger.WriteWarning(
                                    $"OnCloudRegistrationSuccessful: no se pudo descargar certificado ECDSA desde {certUrl}. " +
                                    "Se descargará en la próxima verificación de configuración.",
                                    AlwaysPrintLogger.EvtGenericWarning);
                            }
                        }
                        
                        // 5. Detener CloudRegistration
                        if (_cloudRegistration != null)
                        {
                            _cloudRegistration.RegistrationSuccessful -= OnCloudRegistrationSuccessful;
                            _cloudRegistration.Dispose();
                            _cloudRegistration = null;
                            AlwaysPrintLogger.WriteTrayInfo(
                                "OnCloudRegistrationSuccessful: CloudRegistration detenido");
                        }
                        
                        // 6. Iniciar CloudManager con la configuración actualizada
                        var credentials = new CloudCredentialsManager();
                        _cloudManager = new CloudManager(cfg, credentials, _registry, _pipe, _uiContext, _trayIcon);
                        _cloudManager.Registered += () => OnCloudManagerRegistered(cfg);
                        _cloudManager.CheckUpdateRequested += OnCheckUpdateRequested;
                        _cloudManager.Start();
                        SubscribeOfflineStateManager(_cloudManager);
                        _cloudConnectedAt = DateTime.UtcNow;
                        
                        AlwaysPrintLogger.WriteTrayInfo(
                            "OnCloudRegistrationSuccessful: CloudManager iniciado correctamente");
                        
                        // 7. Mostrar notificación al usuario
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

        /// <summary>
        /// Construye o reconstruye el submenú de acciones OnDemand en el menú contextual.
        /// Se llama en bootstrap y ante ActionConfigChanged.
        /// Posiciona el submenú después de "Buscar Actualizaciones", antes del separador de "Salir".
        /// Si no hay triggers OnDemand, no muestra el submenú.
        /// </summary>
        private void RebuildOnDemandSubmenu()
        {
            var triggers = OnDemandConfigReader.GetOnDemandTriggers();

            // Eliminar submenú anterior si existe
            if (_onDemandSubmenu != null)
                _trayIcon.ContextMenuStrip.Items.Remove(_onDemandSubmenu);
            if (_onDemandSeparator != null)
                _trayIcon.ContextMenuStrip.Items.Remove(_onDemandSeparator);

            if (triggers.Count == 0)
            {
                _onDemandSubmenu = null;
                _onDemandSeparator = null;
                return;
            }

            _onDemandSubmenu = new ToolStripMenuItem(LocalizationManager.Get("MenuOnDemandActions"));
            foreach (var trigger in triggers)
            {
                var item = new ToolStripMenuItem(trigger.Label);
                item.Tag = trigger;
                item.Click += OnDemandMenuItem_Click;
                _onDemandSubmenu.DropDownItems.Add(item);
            }

            // Insertar antes del separador final (antes de "Salir")
            // Estructura del menú: About, Config, MyPrinters, CheckUpdates, [separator], Exit
            // Queremos insertar: ..., CheckUpdates, [_onDemandSeparator], [_onDemandSubmenu], [separator], Exit
            int insertIndex = _trayIcon.ContextMenuStrip.Items.Count - 2;
            _onDemandSeparator = new ToolStripSeparator();
            _trayIcon.ContextMenuStrip.Items.Insert(insertIndex, _onDemandSeparator);
            _trayIcon.ContextMenuStrip.Items.Insert(insertIndex + 1, _onDemandSubmenu);
        }

        /// <summary>
        /// Handler para clic en un ítem del submenú OnDemand.
        /// Envía la solicitud de ejecución al Service vía Named Pipe.
        /// Deshabilita el ítem durante la ejecución y muestra balloon con resultado.
        /// </summary>
        private async void OnDemandMenuItem_Click(object sender, EventArgs e)
        {
            var item = (ToolStripMenuItem)sender;
            var trigger = (OnDemandTriggerInfo)item.Tag;

            AlwaysPrintLogger.WriteTrayInfo(
                $"OnDemandMenuItem_Click: usuario solicitó ejecución de trigger '{trigger.Label}'.");

            // Deshabilitar ítem durante ejecución para prevenir clics duplicados
            item.Enabled = false;

            try
            {
                // Verificar disponibilidad del pipe
                if (!_pipe.IsConnected)
                {
                    AlwaysPrintLogger.WriteTrayError(
                        $"OnDemandMenuItem_Click: pipe no disponible al intentar ejecutar '{trigger.Label}'.",
                        AlwaysPrintLogger.EvtGenericError);
                    ShowBalloon(AppTitle,
                        "El servicio no está accesible",
                        ToolTipIcon.Error);
                    return;
                }

                // Construir y enviar mensaje al Service
                var payload = new ExecuteOnDemandTriggerPayload { Label = trigger.Label };
                var request = PipeMessage.Create(MessageType.ExecuteOnDemandTrigger, payload);

                var response = await Task.Run(() => _pipe.Send(request));

                if (response == null)
                {
                    // Pipe se desconectó durante la comunicación
                    AlwaysPrintLogger.WriteTrayError(
                        $"OnDemandMenuItem_Click: no se recibió respuesta del Service para '{trigger.Label}'.",
                        AlwaysPrintLogger.EvtGenericError);
                    ShowBalloon(AppTitle,
                        "El servicio no está accesible",
                        ToolTipIcon.Error);
                    return;
                }

                if (response.Type == MessageType.Ack)
                {
                    var ack = response.GetPayload<AckPayload>();
                    if (ack?.Success == true)
                    {
                        AlwaysPrintLogger.WriteTrayInfo(
                            $"OnDemandMenuItem_Click: trigger '{trigger.Label}' ejecutado exitosamente.");
                        ShowBalloon(AppTitle,
                            $"✓ {trigger.Label} ejecutado correctamente",
                            ToolTipIcon.Info);
                    }
                    else
                    {
                        // Ack con success=false
                        var errorMsg = ack?.Message ?? "Error desconocido";
                        AlwaysPrintLogger.WriteTrayError(
                            $"OnDemandMenuItem_Click: trigger '{trigger.Label}' falló. Mensaje: {errorMsg}",
                            AlwaysPrintLogger.EvtGenericError);
                        ShowBalloon(AppTitle,
                            $"Error ejecutando '{trigger.Label}': {errorMsg}",
                            ToolTipIcon.Error);
                    }
                }
                else if (response.Type == MessageType.Error)
                {
                    var error = response.GetPayload<ErrorPayload>();
                    var errorMsg = error?.Message ?? "Error desconocido";
                    AlwaysPrintLogger.WriteTrayError(
                        $"OnDemandMenuItem_Click: Service retornó error para '{trigger.Label}'. " +
                        $"Código: {error?.Code}, Mensaje: {errorMsg}",
                        AlwaysPrintLogger.EvtGenericError);
                    ShowBalloon(AppTitle,
                        $"Error ejecutando '{trigger.Label}': {errorMsg}",
                        ToolTipIcon.Error);
                }
                else
                {
                    // Tipo de respuesta inesperado
                    AlwaysPrintLogger.WriteTrayError(
                        $"OnDemandMenuItem_Click: respuesta inesperada tipo '{response.Type}' para '{trigger.Label}'.",
                        AlwaysPrintLogger.EvtGenericError);
                    ShowBalloon(AppTitle,
                        $"Error ejecutando '{trigger.Label}': respuesta inesperada del servicio",
                        ToolTipIcon.Error);
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"OnDemandMenuItem_Click: excepción al ejecutar '{trigger.Label}': {ex.Message}",
                    AlwaysPrintLogger.EvtGenericError);
                ShowBalloon(AppTitle,
                    $"Error ejecutando '{trigger.Label}': {ex.Message}",
                    ToolTipIcon.Error);
            }
            finally
            {
                // Rehabilitar ítem tras respuesta (éxito o error)
                item.Enabled = true;
            }
        }

        /// <summary>
        /// Maneja mensajes push (no solicitados) recibidos del Service vía Named Pipe.
        /// Actualmente procesa ActionConfigChanged para actualizar dinámicamente el menú y StatusForm.
        /// Se invoca desde el hilo del PipeClient (no es hilo UI).
        /// </summary>
        private void OnPipeMessageReceived(PipeMessage message)
        {
            try
            {
                switch (message.Type)
                {
                    case MessageType.ActionConfigChanged:
                        HandleActionConfigChanged();
                        break;
                    case MessageType.OnDemandActionProgress:
                        // El progreso OnDemand se maneja directamente en StatusForm via
                        // suscripción temporal a MessageReceived. No se necesita acción aquí.
                        break;
                    case MessageType.ServiceStopping:
                        // Servicio se está deteniendo: ocultar icono inmediatamente para evitar fantasmas
                        AlwaysPrintLogger.WriteTrayInfo("Tray: mensaje ServiceStopping recibido. Ocultando icono.");
                        _uiContext.Post(_ =>
                        {
                            _trayIcon.Visible = false;
                        }, null);
                        break;
                    case MessageType.ConnectivityCheck:
                        var connectivityPayload = message.GetPayload<ConnectivityCheckPayload>();
                        _ = Task.Run(() => _connectivityHandler?.ExecuteCheckAsync(connectivityPayload));
                        break;
                    default:
                        // Otros mensajes push se ignoran aquí (CloudManager los maneja por separado)
                        break;
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"OnPipeMessageReceived: error procesando mensaje push tipo='{message.Type}'. {ex.Message}",
                    AlwaysPrintLogger.EvtGenericError);
            }
        }

        /// <summary>
        /// Maneja el evento ActionConfigChanged recibido del Service.
        /// Recarga la configuración OnDemand, reconstruye el submenú y actualiza el StatusForm si está abierto.
        /// Si hay un trigger en ejecución que fue eliminado de la nueva configuración,
        /// no se elimina de la UI hasta que su ejecución finalice (el control individual en item.Enabled
        /// y OnDemandTriggerItem.IsExecuting maneja esto — RefreshOnDemandTriggers preserva ítems en ejecución).
        /// </summary>
        private void HandleActionConfigChanged()
        {
            AlwaysPrintLogger.WriteTrayInfo(
                "HandleActionConfigChanged: notificación de cambio de configuración recibida del Service.");

            // Recargar configuración OnDemand desde disco
            var triggers = OnDemandConfigReader.Reload();

            AlwaysPrintLogger.WriteTrayInfo(
                $"HandleActionConfigChanged: configuración recargada. {triggers.Count} triggers OnDemand encontrados.");

            // Actualizar UI en hilo principal (el callback del pipe viene de un hilo de fondo)
            _uiContext.Post(_ =>
            {
                try
                {
                    // Reconstruir submenú OnDemand del menú contextual
                    RebuildOnDemandSubmenu();

                    // Refrescar StatusForm si está abierto
                    if (_statusForm != null && !_statusForm.IsDisposed)
                    {
                        _statusForm.RefreshActionConfigInfo();
                    }

                    AlwaysPrintLogger.WriteTrayInfo(
                        "HandleActionConfigChanged: submenú OnDemand reconstruido.");
                }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteTrayError(
                        $"HandleActionConfigChanged: error actualizando UI. {ex.Message}",
                        AlwaysPrintLogger.EvtGenericError);
                }
            }, null);
        }

        /// <summary>
        /// Muestra el Status Form o lo trae al frente si ya está abierto.
        /// Se invoca al recibir el broadcast ShowStatus desde una segunda instancia.
        /// Implementa patrón singleton: una sola instancia del formulario a la vez.
        /// </summary>
        internal void ShowStatusForm()
        {
            ShowStatusFormInternal();
        }

        private void ShowStatusFormInternal()
        {
            // Si ya hay un formulario abierto, traerlo al frente y no abrir otro
            if (_activeForm != null && !_activeForm.IsDisposed)
            {
                AlwaysPrintLogger.WriteTrayInfo("StatusForm: ya existe una instancia abierta, activando.");
                _activeForm.Activate();
                return;
            }

            // Proveer estado de conectividad Cloud al StatusForm
            Func<CloudConnectivityState?> connectivityProvider = () =>
            {
                // Si CloudRegistration está activo, obtener su estado
                if (_cloudRegistration != null)
                    return _cloudRegistration.GetConnectivityState();

                // Si CloudManager está activo, verificar estado del WebSocket vía OfflineStateManager
                if (_cloudManager != null)
                {
                    var offlineMgr = _cloudManager.GetOfflineStateManager();
                    if (offlineMgr != null && offlineMgr.IsOffline)
                    {
                        return new CloudConnectivityState
                        {
                            Status = "Disconnected",
                            FailedAttempts = 0,
                            DisconnectedSince = offlineMgr.OfflineDuration.HasValue
                                ? DateTime.UtcNow - offlineMgr.OfflineDuration.Value
                                : null,
                            ConnectedSince = null,
                            LastError = "WebSocket desconectado",
                            CurrentRetryIntervalSeconds = 0
                        };
                    }

                    // CloudManager activo y online
                    return new CloudConnectivityState
                    {
                        Status = "Connected",
                        FailedAttempts = 0,
                        DisconnectedSince = null,
                        ConnectedSince = _cloudConnectedAt,
                        LastError = null,
                        CurrentRetryIntervalSeconds = 0
                    };
                }

                // Ni CloudRegistration ni CloudManager activos
                return null;
            };

            var form = new StatusForm(_pipe, connectivityProvider);
            _activeForm = form;
            _statusForm = form;
            form.FormClosed += (_, __) => 
            { 
                _activeForm = null; 
                _statusForm = null;
                AlwaysPrintLogger.WriteTrayInfo("StatusForm cerrado.");
            };
            AlwaysPrintLogger.WriteTrayInfo("StatusForm abierto (ShowDialog).");
            form.ShowDialog();
            AlwaysPrintLogger.WriteTrayInfo("StatusForm.ShowDialog() retornó.");
        }

        /// <summary>
        /// Ventana oculta que intercepta el mensaje broadcast para mostrar StatusForm.
        /// Se registra como message-only window para recibir el Win32 broadcast
        /// enviado por la segunda instancia del Tray.
        /// </summary>
        private sealed class BroadcastListener : NativeWindow
        {
            private readonly TrayApplicationContext _owner;
            private readonly uint _targetMsg;

            public BroadcastListener(TrayApplicationContext owner, uint targetMsg)
            {
                _owner = owner;
                _targetMsg = targetMsg;
                // Crear ventana message-only para recibir broadcasts
                CreateHandle(new CreateParams { Parent = IntPtr.Zero });
            }

            protected override void WndProc(ref Message m)
            {
                if ((uint)m.Msg == _targetMsg)
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        "Broadcast ShowStatus recibido. Mostrando StatusForm.");
                    _owner.ShowStatusForm();
                    return;
                }
                base.WndProc(ref m);
            }
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                _cts.Cancel();
                _pipe.MessageReceived -= OnPipeMessageReceived;
                _messageWindow?.DestroyHandle();
                _messageWindow = null;
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
