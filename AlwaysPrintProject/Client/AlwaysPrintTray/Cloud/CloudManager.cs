using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Management;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Messages;
using AlwaysPrint.Shared.Network;
using AlwaysPrint.Shared.Security;
using AlwaysPrintTray.Localization;
using AlwaysPrintTray.Pipe;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace AlwaysPrintTray.Cloud
{
    /// <summary>
    /// Orquestador principal de la integración Cloud.
    /// Gestiona el ciclo de vida completo de la conexión WebSocket hacia APCM:
    /// inicio, registro de workstation, heartbeat (pong), y notificación al Service.
    /// </summary>
    public sealed class CloudManager : IDisposable
    {
        /// <summary>Estado actual de conexión Cloud.</summary>
        public bool IsConnected { get; private set; }

        /// <summary>URL base de la API Cloud.</summary>
        public string CloudApiUrl => _config.CloudApiUrl;

        /// <summary>ID de la workstation registrada en la Cloud (null si no registrada).</summary>
        public string? WorkstationId => _credentials.WorkstationId;

        /// <summary>HttpClient compartido para requests HTTP a la Cloud.</summary>
        public HttpClient? HttpClient => _wsClient?.HttpClient;

        /// <summary>
        /// Se dispara cuando la workstation ha sido registrada exitosamente en la Cloud
        /// (después de recibir el mensaje "registered" con WorkstationId).
        /// </summary>
        public event Action? Registered;

        /// <summary>
        /// [LEGACY FALLBACK] Se dispara cuando se recibe un comando remoto "check_update" sin download_url.
        /// El suscriptor (TrayApplicationContext) invoca UpdateChecker.CheckNowAsync() para hacer
        /// un único request HTTP al backend como fallback. En operación normal, las actualizaciones
        /// de MSI llegan vía push message con presigned URL y se descargan directamente desde S3.
        /// </summary>
        [Obsolete("Evento legacy para comandos check_update sin download_url. " +
                   "En operación normal, MSI_Push_Message incluye download_url para descarga directa S3.")]
        public event Action? CheckUpdateRequested;

        /// <summary>
        /// Se dispara cuando la configuración de acciones ha sido descargada/actualizada exitosamente.
        /// El suscriptor (TrayApplicationContext) debe reconstruir el submenú OnDemand.
        /// Parámetros: (configName, configHash).
        /// </summary>
        public event Action<string, string>? ActionConfigUpdated;

        /// <summary>
        /// Expone el OfflineStateManager interno para que el StatusForm pueda consultar
        /// el estado de conectividad del WebSocket post-registro.
        /// </summary>
        public OfflineStateManager? GetOfflineStateManager() => _offlineState;

        /// <summary>
        /// Retorna el último estado de distribución conocido (del registro enriquecido o push messages).
        /// Delega al PushMessageHandler para verificación manual desde el Tray.
        /// Puede ser null si no se ha recibido aún ningún estado del servidor.
        /// </summary>
        public DistributionState? GetCachedState() => _pushMessageHandler?.GetCachedState();

        /// <summary>
        /// Compara un estado de distribución contra el estado local y descarga desde S3
        /// los recursos que difieran. Usado por la verificación manual desde el Tray.
        /// Delega al PushMessageHandler para la lógica de comparación y descarga.
        /// Retorna el número de componentes actualizados (0 = todo al día).
        /// </summary>
        /// <param name="state">Estado de distribución a comparar.</param>
        public async Task<int> SyncFromCachedStateAsync(DistributionState state)
        {
            if (_pushMessageHandler == null)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    "CloudManager: SyncFromCachedStateAsync invocado pero PushMessageHandler no inicializado.");
                return 0;
            }

            return await _pushMessageHandler.SyncFromStateAsync(state);
        }

        private readonly AppConfiguration _config;
        private readonly CloudCredentialsManager _credentials;
        private readonly RegistryConfigManager _registry;
        private readonly PipeClient _pipe;
        private readonly SynchronizationContext _uiContext;
        private readonly NotifyIcon _trayIcon;
        private readonly UpdateDownloader _updateDownloader;

        private CloudWebSocketClient? _wsClient;
        private ConfigurationSync? _configSync;
        private ConfigManager? _configManager;
        private PushMessageHandler? _pushMessageHandler;
        private TelemetryReporter? _telemetryReporter;
        private ConnectivityMonitor? _connectivityMonitor;
        private OfflineStateManager? _offlineState;
        private DebuggingCommandHandler? _debuggingHandler;
        private bool _noConfigWarningShown;
        private bool _disposed;

        /// <summary>
        /// Crea una nueva instancia de CloudManager.
        /// </summary>
        /// <param name="config">Configuración de la aplicación con CloudApiUrl.</param>
        /// <param name="credentials">Gestor de credenciales Cloud en HKCU.</param>
        /// <param name="registry">Gestor de configuración del registro (flag local auto-update).</param>
        /// <param name="pipe">Cliente Named Pipe para notificar al Service.</param>
        /// <param name="uiContext">Contexto de sincronización del hilo UI.</param>
        /// <param name="trayIcon">Referencia al NotifyIcon del system tray.</param>
        public CloudManager(
            AppConfiguration config,
            CloudCredentialsManager credentials,
            RegistryConfigManager registry,
            PipeClient pipe,
            SynchronizationContext uiContext,
            NotifyIcon trayIcon)
        {
            _config = config;
            _credentials = credentials;
            _registry = registry;
            _pipe = pipe;
            _uiContext = uiContext;
            _trayIcon = trayIcon;
            _updateDownloader = new UpdateDownloader(config.CloudApiUrl);
        }

        /// <summary>
        /// Inicia la integración Cloud: carga credenciales, crea el cliente WebSocket,
        /// suscribe eventos y conecta. Instancia TelemetryReporter y ConnectivityMonitor
        /// según la configuración actual.
        /// </summary>
        public void Start()
        {
            _credentials.Load();

            _wsClient = new CloudWebSocketClient(_config.CloudApiUrl);
            _wsClient.Connected += OnConnected;
            _wsClient.Disconnected += OnDisconnected;
            _wsClient.MessageReceived += OnMessageReceived;
            _wsClient.Error += OnError;

            _configSync = new ConfigurationSync(
                _config.CloudApiUrl,
                _credentials.WorkstationId!,
                _credentials,
                _pipe,
                _wsClient);

            // Inicializar ConfigManager para gestión de archivos de configuración de acciones
            _configManager = new ConfigManager(_wsClient.HttpClient, _pipe);
            AlwaysPrintLogger.WriteTrayInfo("CloudManager: ConfigManager inicializado.");

            // Inicializar PushMessageHandler para procesar mensajes push de distribución
            _pushMessageHandler = new PushMessageHandler(
                _configManager, _updateDownloader, _pipe, _config.CloudApiUrl, _wsClient.HttpClient);
            AlwaysPrintLogger.WriteTrayInfo("CloudManager: PushMessageHandler inicializado.");

            // Detectar condición sin configuración cacheada + offline al inicio
            var cachedConfig = _configSync.LoadFromCache();
            if (cachedConfig == null && !IsConnected && !_noConfigWarningShown)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    "CloudManager: sin conexión a la nube y sin configuración cacheada. Operando con valores por defecto.");
                _uiContext.Post(_ =>
                {
                    try
                    {
                        _trayIcon.ShowBalloonTip(
                            4000,
                            LocalizationManager.Get("BalloonOfflineTitle"),
                            LocalizationManager.Get("BalloonOfflineNoConfig"),
                            ToolTipIcon.Info);
                    }
                    catch (Exception ex)
                    {
                        AlwaysPrintLogger.WriteTrayWarning(
                            $"CloudManager: error mostrando balloon tip sin-config-offline. {ex.Message}");
                    }
                }, null);
                _noConfigWarningShown = true;
            }

            // Instanciar y arrancar TelemetryReporter si la telemetría está habilitada
            if (_config.TelemetryEnabled)
            {
                _telemetryReporter = new TelemetryReporter(
                    _wsClient, _pipe, _config.TelemetryIntervalSeconds, contingencyActive: false);
                _telemetryReporter.Start();
                AlwaysPrintLogger.WriteTrayInfo(
                    "CloudManager: TelemetryReporter iniciado (TelemetryEnabled=true).");
            }
            else
            {
                AlwaysPrintLogger.WriteTrayInfo(
                    "CloudManager: TelemetryReporter no iniciado (TelemetryEnabled=false).");
            }

            // Instanciar y arrancar ConnectivityMonitor si hay checks configurados
            if (_config.ConnectivityChecks != null && _config.ConnectivityChecks.Count > 0)
            {
                _connectivityMonitor = new ConnectivityMonitor(
                    _wsClient, _config.ConnectivityChecks);
                _connectivityMonitor.Start();
                AlwaysPrintLogger.WriteTrayInfo(
                    $"CloudManager: ConnectivityMonitor iniciado con {_config.ConnectivityChecks.Count} checks.");
            }
            else
            {
                AlwaysPrintLogger.WriteTrayInfo(
                    "CloudManager: ConnectivityMonitor no iniciado (ConnectivityChecks vacío).");
            }

            // Instanciar OfflineStateManager (CloudEnabled=true está garantizado por el caller)
            _offlineState = new OfflineStateManager(_uiContext, _trayIcon);
            AlwaysPrintLogger.WriteTrayInfo(
                "CloudManager: OfflineStateManager instanciado.");

            // Suscribir a mensajes push del Service vía Named Pipe (ej: ReportTelemetry)
            _pipe.MessageReceived += OnPipeMessageReceived;

            _wsClient.Connect();
            AlwaysPrintLogger.WriteTrayInfo("CloudManager: conexión WebSocket iniciada.");
        }

        /// <summary>
        /// Detiene la integración Cloud: detiene y libera TelemetryReporter y ConnectivityMonitor,
        /// desconecta el WebSocket y actualiza el estado.
        /// </summary>
        public void Stop()
        {
            // Desuscribir de mensajes push del pipe
            _pipe.MessageReceived -= OnPipeMessageReceived;

            // Detener y liberar TelemetryReporter
            _telemetryReporter?.Stop();
            _telemetryReporter?.Dispose();
            _telemetryReporter = null;

            // Detener y liberar ConnectivityMonitor
            _connectivityMonitor?.Stop();
            _connectivityMonitor?.Dispose();
            _connectivityMonitor = null;

            // Liberar OfflineStateManager (detiene timer de verificación)
            _offlineState?.Dispose();
            _offlineState = null;
            
            // Detener timer de reintento de CIDR si está activo
            StopCidrRetryTimer();

            _wsClient?.Disconnect();
            IsConnected = false;

            AlwaysPrintLogger.WriteTrayInfo(
                "CloudManager: detenido. TelemetryReporter, ConnectivityMonitor y OfflineStateManager liberados.");
        }

        /// <summary>
        /// Libera todos los recursos: detiene la conexión y dispone el cliente WebSocket.
        /// </summary>
        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;
            Stop();
            _wsClient?.Dispose();
        }

        // === Handlers de eventos ===

        private void OnConnected()
        {
            IsConnected = true;
            AlwaysPrintLogger.WriteTrayInfo("CloudManager: conectado a APCM.");

            // Notificar reconexión al OfflineStateManager (restaura icono y muestra balloon tip)
            _offlineState?.OnReconnected();

            // Registrar reconexión en TelemetryReporter (si existe un evento de desconexión abierto)
            _telemetryReporter?.RecordReconnection(DateTime.UtcNow);

            // Enviar telemetría pendiente acumulada durante la desconexión
            _telemetryReporter?.FlushPending();

            SendRegistration();
            NotifyServiceCloudStatus(connected: true);
            
            // Nota: El evento Registered se dispara en HandleRegistered() después de
            // recibir confirmación del servidor. La distribución de configs, certificados
            // y MSI es ahora 100% push-based:
            // - ProcessRegistrationState() recibe el estado enriquecido completo
            // - PushMessageHandler gestiona las descargas directas desde S3
            // - UpdateChecker polling periódico DESHABILITADO (MSI llega vía push)
            // - HandleCertRotated ya no descarga (delegado a PushMessageHandler)
            // Ya no se hace polling HTTP a /config/info, /config/download,
            // /updates/check (periódico) ni descarga directa de certificados.
        }

        private void OnDisconnected()
        {
            IsConnected = false;
            AlwaysPrintLogger.WriteTrayWarning("CloudManager: desconectado de APCM.");

            // Notificar desconexión al OfflineStateManager (inicia timer de verificación)
            _offlineState?.OnDisconnected();

            // Registrar evento de desconexión en TelemetryReporter
            _telemetryReporter?.RecordDisconnection(DateTime.UtcNow);

            NotifyServiceCloudStatus(connected: false);
        }

        private void OnMessageReceived(string type, string json)
        {
            switch (type)
            {
                case "ping":
                    HandlePing();
                    break;
                case "registered":
                    HandleRegistered(json);
                    break;
                case "config_update":
                    HandleConfigUpdate(json);
                    break;
                case "command":
                    HandleCommand(json);
                    break;
                case "forced_contingency":
                    HandleForcedContingency(json);
                    break;
                case "default_printer_changed":
                    HandleDefaultPrinterChanged(json);
                    break;
                case "message":
                    HandleCloudMessage(json);
                    break;
                case "cert_rotated":
                    HandleCertRotated(json);
                    // Enrutar al PushMessageHandler para actualizar estado cacheado
                    RouteToPushHandler("cert_rotated", json);
                    break;
                case "action_config_changed":
                    HandleActionConfigChanged(json);
                    // Enrutar al PushMessageHandler para actualizar estado cacheado y descarga directa S3
                    RouteToPushHandler("action_config_changed", json);
                    break;
                case "check_update":
                    // Mensaje push directo de actualización de MSI — enrutar al PushMessageHandler
                    RouteToPushHandler("check_update", json);
                    break;
                default:
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"CloudManager: mensaje recibido tipo='{type}' (sin handler).");
                    break;
            }
        }

        /// <summary>
        /// Maneja mensajes push enviados por un administrador desde la Cloud.
        /// Muestra un balloon tip con el contenido del mensaje.
        /// Formato esperado: {"type": "message", "message_id": "...", "content": "...", "sent_at": "...", "sender_name": "..."}
        /// </summary>
        private void HandleCloudMessage(string json)
        {
            try
            {
                var data = JObject.Parse(json);
                var content = data["content"]?.ToString();
                var messageId = data["message_id"]?.ToString();
                var senderName = data["sender_name"]?.ToString();

                if (string.IsNullOrWhiteSpace(content))
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "CloudManager: mensaje recibido sin contenido.");
                    return;
                }

                AlwaysPrintLogger.WriteTrayInfo(
                    $"CloudManager: mensaje Cloud recibido. id={messageId}, longitud={content.Length}");

                string title = string.IsNullOrWhiteSpace(senderName)
                    ? "AlwaysPrint - Mensaje"
                    : $"AlwaysPrint - Mensaje de {senderName}";

                // Mostrar notificación al usuario vía balloon tip
                _uiContext.Post(_ =>
                {
                    _trayIcon.BalloonTipIcon = ToolTipIcon.Info;
                    _trayIcon.BalloonTipTitle = title;
                    _trayIcon.BalloonTipText = content.Length > 255
                        ? content.Substring(0, 252) + "..."
                        : content;
                    _trayIcon.ShowBalloonTip(8000);
                }, null);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudManager: error procesando mensaje Cloud. {ex.Message}");
            }
        }

        /// <summary>
        /// [DEPRECADO] Anteriormente descargaba el certificado directamente al recibir cert_rotated.
        /// 
        /// Con push-based distribution, la descarga de certificados se gestiona
        /// exclusivamente por PushMessageHandler.HandleCertPush() que incluye:
        /// - Comparación de cert_version vs local
        /// - Retry con backoff exponencial [1s, 2s, 4s]
        /// - Actualización del estado cacheado (DistributionState)
        /// 
        /// El routing al PushMessageHandler se realiza en OnMessageReceived vía RouteToPushHandler.
        /// Este método se mantiene solo para loguear la recepción del mensaje con fines de diagnóstico.
        /// </summary>
        [Obsolete("La descarga de certificados se gestiona por PushMessageHandler.HandleCertPush() con retry. " +
                   "Este handler solo loguea. Será eliminado cuando se complete la migración.")]
        private void HandleCertRotated(string json)
        {
            try
            {
                var data = JObject.Parse(json);
                string? certUrl = data["cert_url"]?.ToString();
                int? certVersion = data["cert_version"]?.ToObject<int?>();

                AlwaysPrintLogger.WriteTrayInfo(
                    $"CloudManager: cert_rotated recibido (versión={certVersion?.ToString() ?? "?"}, url={(certUrl != null ? "presente" : "null")}). " +
                    "Descarga delegada a PushMessageHandler con retry S3.");
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"CloudManager: error parseando mensaje cert_rotated para diagnóstico: {ex.Message}");
            }
        }

        private void OnError(Exception ex)
        {
            AlwaysPrintLogger.WriteTrayError(
                $"CloudManager: error en WebSocket. {ex.Message}");
        }

        // === Handler de mensajes push del Service vía Named Pipe ===

        /// <summary>
        /// Maneja mensajes push (no solicitados) recibidos del Service vía Named Pipe.
        /// Actualmente procesa ReportTelemetry para acumular datos de trabajos de impresión.
        /// </summary>
        private void OnPipeMessageReceived(PipeMessage message)
        {
            try
            {
                switch (message.Type)
                {
                    case MessageType.ReportTelemetry:
                        HandleReportTelemetry(message);
                        break;
                    case MessageType.ContingencyResult:
                        HandleContingencyResult(message);
                        break;
                    case MessageType.DebuggingCaptureReady:
                    case MessageType.DebuggingCaptureError:
                        _debuggingHandler?.HandleServicePush(message);
                        break;
                    case MessageType.OnDemandActionProgress:
                        // Se maneja en TrayApplicationContext.OnPipeMessageReceived (ventana de progreso)
                        break;
                    default:
                        AlwaysPrintLogger.WriteTrayInfo(
                            $"CloudManager: mensaje push del Service tipo='{message.Type}' no manejado.");
                        break;
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudManager: error procesando mensaje push del Service tipo='{message.Type}'. {ex.Message}");
            }
        }

        /// <summary>
        /// Procesa un mensaje ContingencyResult del Service: muestra un balloon tip
        /// al usuario informando si la contingencia se activó/desactivó correctamente
        /// y a qué impresora se conectó.
        /// </summary>
        private void HandleContingencyResult(PipeMessage message)
        {
            var payload = message.GetPayload<ContingencyResultPayload>();
            if (payload == null)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    "CloudManager: mensaje ContingencyResult recibido con payload inválido. Descartando.");
                return;
            }

            AlwaysPrintLogger.WriteTrayInfo(
                $"CloudManager: ContingencyResult recibido. success={payload.Success}, entered={payload.Entered}, " +
                $"printer={payload.PrinterName}, message={payload.Message}");

            // Enviar status_update al servidor Cloud con el estado de contingencia y la IP
            if (payload.Success && _wsClient != null && _wsClient.IsConnected)
            {
                try
                {
                    // Extraer solo la IP del PrinterAddress (formato "IP:puerto")
                    string? printerIp = null;
                    if (!string.IsNullOrEmpty(payload.PrinterAddress))
                    {
                        int colonIdx = payload.PrinterAddress.LastIndexOf(':');
                        printerIp = colonIdx > 0
                            ? payload.PrinterAddress.Substring(0, colonIdx)
                            : payload.PrinterAddress;
                    }

                    _wsClient.Send("status_update", new
                    {
                        contingency_active = payload.Entered,
                        contingency_printer_ip = printerIp,
                        current_user = Environment.UserName
                    });

                    AlwaysPrintLogger.WriteTrayInfo(
                        $"CloudManager: status_update enviado al servidor. " +
                        $"contingency_active={payload.Entered}, contingency_printer_ip={printerIp}");
                }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"CloudManager: error enviando status_update de contingencia al servidor. {ex.Message}");
                }
            }

            // Actualizar estado en TelemetryReporter
            _telemetryReporter?.UpdateContingencyState(payload.Entered);

            _uiContext.Post(_ =>
            {
                try
                {
                    string title = "AlwaysPrint - Contingencia";
                    string text;
                    ToolTipIcon icon;

                    if (payload.Success)
                    {
                        if (payload.Entered)
                        {
                            text = $"Contingencia activada. Impresora: {payload.PrinterName} ({payload.PrinterAddress})";
                            icon = ToolTipIcon.Warning;
                        }
                        else
                        {
                            text = "Contingencia desactivada. Impresión restaurada a modo normal (CPM).";
                            icon = ToolTipIcon.Info;
                        }
                    }
                    else
                    {
                        text = $"Error en contingencia: {payload.Message}";
                        icon = ToolTipIcon.Error;
                    }

                    _trayIcon.ShowBalloonTip(5000, title, text, icon);
                }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"CloudManager: error mostrando balloon tip de contingencia. {ex.Message}");
                }
            }, null);
        }

        /// <summary>
        /// Procesa un mensaje ReportTelemetry del Service: deserializa el payload
        /// y acumula los datos del trabajo en el TelemetryReporter.
        /// </summary>
        private void HandleReportTelemetry(PipeMessage message)
        {
            var payload = message.GetPayload<ReportTelemetryPayload>();
            if (payload == null)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    "CloudManager: mensaje ReportTelemetry recibido con payload inválido o ausente. Descartando.");
                return;
            }

            if (_telemetryReporter == null)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    "CloudManager: mensaje ReportTelemetry recibido pero TelemetryReporter no está activo. Descartando.");
                return;
            }

            _telemetryReporter.AccumulateJobData(payload.JobCount, payload.ReleaseTimeMs);
            AlwaysPrintLogger.WriteTrayInfo(
                $"CloudManager: ReportTelemetry procesado. jobCount={payload.JobCount}, releaseTimeMs={payload.ReleaseTimeMs}.");
        }

        // === Registro ===

        /// <summary>
        /// Intervalo de reintento para detección de CIDR (30 segundos).
        /// </summary>
        private const int CidrRetryIntervalMs = 30_000;
        
        /// <summary>
        /// Timer para reintentar detección de CIDR cuando no está disponible.
        /// </summary>
        private System.Threading.Timer? _cidrRetryTimer;
        
        /// <summary>
        /// Flag para evitar notificaciones duplicadas de error de CIDR.
        /// </summary>
        private bool _cidrErrorShown;

        private void SendRegistration()
        {
            try
            {
                // Detectar CIDR antes de enviar registro
                string? cidr = NetworkHelper.GetOutboundCIDR();
                
                if (string.IsNullOrEmpty(cidr))
                {
                    // CIDR no disponible: no intentar registro
                    AlwaysPrintLogger.WriteError(
                        "CloudManager: no se pudo detectar el CIDR de la red. " +
                        "No se enviará registro sin CIDR. Verificar conexión de red.",
                        AlwaysPrintLogger.EvtGenericError);
                    
                    // Mostrar notificación al usuario solo la primera vez
                    if (!_cidrErrorShown)
                    {
                        _cidrErrorShown = true;
                        _uiContext.Post(_ =>
                        {
                            try
                            {
                                _trayIcon.ShowBalloonTip(
                                    5000,
                                    "AlwaysPrint",
                                    LocalizationManager.Get("BalloonCidrNotDetected"),
                                    ToolTipIcon.Error);
                            }
                            catch (Exception ex)
                            {
                                AlwaysPrintLogger.WriteTrayWarning(
                                    $"CloudManager: error mostrando balloon tip de CIDR no detectado. {ex.Message}");
                            }
                        }, null);
                    }
                    
                    // Iniciar retry periódico de detección de CIDR
                    StartCidrRetryTimer();
                    return;
                }
                
                // CIDR detectado exitosamente
                if (_cidrErrorShown)
                {
                    // Se recuperó después de un fallo previo
                    _cidrErrorShown = false;
                    StopCidrRetryTimer();
                    
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"CloudManager: CIDR detectado exitosamente después de fallo previo: {cidr}");
                    
                    _uiContext.Post(_ =>
                    {
                        try
                        {
                            _trayIcon.ShowBalloonTip(
                                3000,
                                "AlwaysPrint",
                                LocalizationManager.Get("BalloonCidrDetected"),
                                ToolTipIcon.Info);
                        }
                        catch (Exception ex)
                        {
                            AlwaysPrintLogger.WriteTrayWarning(
                                $"CloudManager: error mostrando balloon tip de CIDR recuperado. {ex.Message}");
                        }
                    }, null);
                }
                
                // Obtener versión del Tray desde el Assembly
                string trayVersion = Assembly.GetExecutingAssembly()
                                        .GetName().Version?.ToString() ?? "0.0.0.0";

                var payload = new JObject
                {
                    ["ip_private"] = GetPrivateIp(),
                    ["hostname"] = Environment.MachineName,
                    ["os_serial"] = GetOsSerial(),
                    ["current_user"] = Environment.UserName,
                    ["locale"] = LocalizationManager.CurrentLocale,
                    ["client_version"] = trayVersion,
                    ["cidr"] = cidr,
                    ["tray_version"] = trayVersion,
                    ["workstation_id"] = _credentials.IsRegistered
                                            ? _credentials.WorkstationId
                                            : null
                };

                _wsClient!.Send("register", payload);
                AlwaysPrintLogger.WriteTrayInfo(
                    $"CloudManager: mensaje de registro enviado. cidr={cidr}, tray_version={trayVersion}");
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudManager: error enviando registro. {ex.Message}");
            }
        }
        
        /// <summary>
        /// Inicia el timer de reintento periódico de detección de CIDR.
        /// Se ejecuta cada 30 segundos hasta que el CIDR sea detectado.
        /// </summary>
        private void StartCidrRetryTimer()
        {
            if (_cidrRetryTimer != null)
                return; // Ya está activo
            
            AlwaysPrintLogger.WriteTrayInfo(
                $"CloudManager: iniciando reintento periódico de detección de CIDR cada {CidrRetryIntervalMs / 1000}s");
            
            _cidrRetryTimer = new System.Threading.Timer(OnCidrRetryTick, null,
                TimeSpan.FromMilliseconds(CidrRetryIntervalMs),
                TimeSpan.FromMilliseconds(CidrRetryIntervalMs));
        }
        
        /// <summary>
        /// Detiene el timer de reintento de detección de CIDR.
        /// </summary>
        private void StopCidrRetryTimer()
        {
            if (_cidrRetryTimer != null)
            {
                _cidrRetryTimer.Dispose();
                _cidrRetryTimer = null;
                AlwaysPrintLogger.WriteTrayInfo(
                    "CloudManager: timer de reintento de CIDR detenido.");
            }
        }
        
        /// <summary>
        /// Callback del timer de reintento de CIDR.
        /// Intenta detectar el CIDR y, si tiene éxito, envía el registro.
        /// </summary>
        private void OnCidrRetryTick(object? state)
        {
            if (_disposed) return;
            
            AlwaysPrintLogger.WriteTrayInfo(
                "CloudManager: reintentando detección de CIDR...");
            
            // Intentar enviar registro (SendRegistration verifica CIDR internamente)
            SendRegistration();
        }

        private void HandleRegistered(string json)
        {
            try
            {
                var obj = JObject.Parse(json);
                var workstationId = obj["workstation_id"]?.ToString();

                if (!string.IsNullOrEmpty(workstationId))
                {
                    _credentials.SaveWorkstationId(workstationId!);
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"CloudManager: WorkstationId registrado = {workstationId}");
                    
                    // Inicializar handler de debugging con el workstation_id
                    if (_debuggingHandler == null && _wsClient != null)
                    {
                        _debuggingHandler = new DebuggingCommandHandler(
                            _wsClient,
                            _pipe,
                            new System.Net.Http.HttpClient(),
                            workstationId!,
                            _config.CloudApiUrl);
                    }

                    // NOTA: La verificación de configuración de acciones ahora se gestiona
                    // vía Registration_Enrichment (ProcessRegistrationState) que recibe el estado
                    // completo desde el In_Memory_State_Map del servidor. Ya no se hace polling
                    // HTTP a /workstations/{id}/config/info ni /config/download.
                    // Si el estado incluye config_hash + config_s3_url, PushMessageHandler
                    // descarga directamente desde S3.

                    // Descargar recursos de VLAN (metadata, impresoras de contingencia)
                    DownloadResources();
                }

                // Procesar estado de distribución enriquecido (Registration_Enrichment)
                ProcessRegistrationState(obj);

                _credentials.SaveLastConnected(DateTime.UtcNow);

                // Mostrar notificación de conexión exitosa al usuario
                _uiContext.Post(_ =>
                {
                    try
                    {
                        _trayIcon.ShowBalloonTip(
                            3000,
                            "AlwaysPrint",
                            LocalizationManager.Get("BalloonConnectedOk"),
                            ToolTipIcon.Info);
                    }
                    catch (Exception ex)
                    {
                        AlwaysPrintLogger.WriteTrayWarning(
                            $"CloudManager: error mostrando balloon tip de conexión exitosa. {ex.Message}");
                    }
                }, null);
                _noConfigWarningShown = false;

                // Notificar que el registro fue exitoso (para que UpdateChecker pueda iniciar)
                Registered?.Invoke();
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudManager: error procesando respuesta de registro. {ex.Message}");
            }
        }

        // === Registration Enrichment y routing de push messages ===

        /// <summary>
        /// Procesa el campo "state" del mensaje "registered" (Registration_Enrichment).
        /// Si el servidor incluye datos de distribución, crea un DistributionState
        /// y lo pasa al PushMessageHandler para que mantenga el caché actualizado.
        /// </summary>
        /// <param name="registeredObj">JObject del mensaje "registered" completo.</param>
        private void ProcessRegistrationState(JObject registeredObj)
        {
            try
            {
                var stateObj = registeredObj["state"] as JObject;
                if (stateObj == null)
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        "CloudManager: mensaje registered sin campo 'state'. " +
                        "El servidor no incluyó estado de distribución enriquecido.");
                    return;
                }

                // Construir DistributionState desde el JSON del registro enriquecido
                var distributionState = new DistributionState
                {
                    ConfigHash = stateObj["config_hash"]?.ToString(),
                    ConfigS3Url = stateObj["config_s3_url"]?.ToString(),
                    CertVersion = stateObj["cert_version"]?.ToObject<int>() ?? 0,
                    CertUrl = stateObj["cert_url"]?.ToString(),
                    CertHash = stateObj["cert_hash"]?.ToString(),
                    MsiVersion = stateObj["msi_version"]?.ToString(),
                    MsiUrl = stateObj["msi_url"]?.ToString(),
                    MsiFileSize = stateObj["msi_file_size"]?.ToObject<long>() ?? 0,
                    LastUpdated = DateTime.UtcNow
                };

                // Pasar al PushMessageHandler para cacheo y posible sincronización
                _pushMessageHandler?.UpdateState(distributionState);

                // Actualizar cert_hash esperado para validación de integridad
                bool configExistedBefore = File.Exists(PipeConstants.ActionConfigFilePath);
                ConfigManager.SetExpectedCertHash(distributionState.CertHash);

                // Si el cert fue invalidado (mismatch detectado), InvalidateLocalCert eliminó
                // el archivo de config. Notificar al Service para que descargue su configuración de memoria.
                if (configExistedBefore && !File.Exists(PipeConstants.ActionConfigFilePath))
                {
                    NotifyServiceActionConfigChanged();
                }

                AlwaysPrintLogger.WriteTrayInfo(
                    $"CloudManager: estado de distribución recibido en registro enriquecido. " +
                    $"ConfigHash={distributionState.ConfigHash ?? "null"}, " +
                    $"CertVersion={distributionState.CertVersion}, " +
                    $"MsiVersion={distributionState.MsiVersion ?? "null"}");

                // Si hay config asignada pero el archivo local no existe, forzar descarga
                if (!string.IsNullOrEmpty(distributionState.ConfigHash) &&
                    !string.IsNullOrEmpty(distributionState.ConfigS3Url) &&
                    !File.Exists(PipeConstants.ActionConfigFilePath))
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"CloudManager: config asignada (hash={distributionState.ConfigHash}) pero " +
                        "archivo local no existe. Forzando descarga...");

                    _ = Task.Run(async () =>
                    {
                        try
                        {
                            int updated = await _pushMessageHandler.SyncFromStateAsync(distributionState);
                            // Reportar estado actualizado al backend
                            if (updated > 0)
                            {
                                var localConfig = _configManager?.GetLocalConfigInfo();
                                if (localConfig != null)
                                {
                                    SendActionConfigStatus(localConfig.Name, localConfig.Hash, localConfig.Version);
                                    AlwaysPrintLogger.WriteTrayInfo(
                                        $"CloudManager: status_update enviado tras descarga de config. " +
                                        $"Name={localConfig.Name}, Hash={localConfig.Hash}, Version={localConfig.Version}");
                                }
                            }
                        }
                        catch (Exception syncEx)
                        {
                            AlwaysPrintLogger.WriteTrayError(
                                $"CloudManager: error en descarga forzada de config: {syncEx.Message}");
                        }
                    });
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"CloudManager: error procesando estado de distribución del registro enriquecido. {ex.Message}");
            }
        }

        /// <summary>
        /// Enruta un mensaje push recibido vía WebSocket al PushMessageHandler.
        /// Fire-and-forget: no bloquea el hilo de procesamiento de mensajes WebSocket.
        /// </summary>
        /// <param name="messageType">Tipo del mensaje (action_config_changed, check_update, cert_rotated).</param>
        /// <param name="json">JSON completo del mensaje.</param>
        private async void RouteToPushHandler(string messageType, string json)
        {
            try
            {
                if (_pushMessageHandler == null)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"CloudManager: PushMessageHandler no inicializado. " +
                        $"No se puede procesar mensaje push tipo='{messageType}'.");
                    return;
                }

                await _pushMessageHandler.HandlePushMessage(messageType, json);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudManager: error enrutando mensaje push tipo='{messageType}' al PushMessageHandler. {ex.Message}");
            }
        }

        // === Config Update ===

        private void HandleConfigUpdate(string json)
        {
            try
            {
                AlwaysPrintLogger.WriteTrayInfo(
                    "CloudManager: procesando mensaje config_update recibido del servidor.");

                var obj = JObject.Parse(json);
                
                // El config_hash está dentro del objeto "config" del mensaje
                var configObj = obj["config"] as JObject;
                var configHash = configObj?["config_hash"]?.ToString();

                // Persistir jitter_window_seconds en Registry si viene en el payload
                PersistJitterWindowFromConfig(configObj);

                if (string.IsNullOrEmpty(configHash))
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "CloudManager: mensaje config_update recibido con config_hash ausente, nulo o vacío. Se ignora.");
                    return;
                }

                AlwaysPrintLogger.WriteTrayInfo(
                    $"CloudManager: config_update con hash={configHash}. Iniciando sincronización...");

                bool result = _configSync!.SyncIfNeeded(configHash!);
                if (!result)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "CloudManager: la sincronización de configuración no pudo completarse.");
                    return;
                }

                // Sincronización exitosa — aplicar cambios de telemetría y conectividad
                ApplyTelemetryAndConnectivityChanges();
            }
            catch (JsonReaderException ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"CloudManager: error al parsear JSON del mensaje config_update — {ex.Message}");
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudManager: error procesando config_update — {ex.GetType().Name}: {ex.Message}");
            }
        }

        /// <summary>
        /// Extrae jitter_window_seconds del payload de config_update.
        /// La persistencia en Registry la hace el Service al recibir CloudConfigurationReceived
        /// (el Tray no tiene permisos de escritura en HKLM).
        /// Este método solo loguea el valor recibido para diagnóstico.
        /// </summary>
        /// <param name="configObj">Objeto JSON "config" del mensaje config_update.</param>
        private void PersistJitterWindowFromConfig(JObject? configObj)
        {
            if (configObj == null)
                return;

            var jitterToken = configObj["jitter_window_seconds"];
            if (jitterToken == null)
                return;

            try
            {
                int jitterValue = jitterToken.Value<int>();
                AlwaysPrintLogger.WriteTrayInfo(
                    $"CloudManager: jitter_window_seconds={jitterValue} recibido de Cloud (persistencia delegada al Service).");
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"CloudManager: error al leer jitter_window_seconds del payload. {ex.Message}");
            }
        }

        /// <summary>
        /// Aplica cambios de configuración relacionados con telemetría y conectividad
        /// después de una sincronización exitosa. Lee la configuración actualizada del cache
        /// y ajusta el estado de TelemetryReporter y ConnectivityMonitor según corresponda.
        /// </summary>
        private void ApplyTelemetryAndConnectivityChanges()
        {
            try
            {
                // Leer la configuración actualizada desde el cache
                var updatedConfig = _configSync!.LoadFromCache();
                if (updatedConfig == null)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "CloudManager: no se pudo leer la configuración actualizada del cache para aplicar cambios de telemetría/conectividad.");
                    return;
                }

                // === Gestión de TelemetryReporter ===
                HandleTelemetryToggle(updatedConfig);

                // === Gestión de ConnectivityMonitor ===
                HandleConnectivityUpdate(updatedConfig);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudManager: error al aplicar cambios de telemetría/conectividad — {ex.GetType().Name}: {ex.Message}");
            }
        }

        /// <summary>
        /// Gestiona el toggle de TelemetryEnabled: inicia o detiene el TelemetryReporter
        /// según el nuevo valor de configuración.
        /// </summary>
        private void HandleTelemetryToggle(AppConfiguration updatedConfig)
        {
            if (updatedConfig.TelemetryEnabled && _telemetryReporter == null)
            {
                // TelemetryEnabled cambió de false a true: iniciar TelemetryReporter
                _telemetryReporter = new TelemetryReporter(
                    _wsClient!, _pipe, updatedConfig.TelemetryIntervalSeconds, contingencyActive: false);
                _telemetryReporter.Start();
                AlwaysPrintLogger.WriteTrayInfo(
                    "CloudManager: TelemetryReporter iniciado tras config_update (TelemetryEnabled=true).");
            }
            else if (!updatedConfig.TelemetryEnabled && _telemetryReporter != null)
            {
                // TelemetryEnabled cambió de true a false: detener y liberar TelemetryReporter
                _telemetryReporter.Stop();
                _telemetryReporter.Dispose();
                _telemetryReporter = null;
                AlwaysPrintLogger.WriteTrayInfo(
                    "CloudManager: TelemetryReporter detenido y liberado tras config_update (TelemetryEnabled=false).");
            }
        }

        /// <summary>
        /// Gestiona actualizaciones de ConnectivityChecks: actualiza la lista de checks,
        /// inicia el monitor si no estaba activo, o lo detiene si la lista queda vacía.
        /// </summary>
        private void HandleConnectivityUpdate(AppConfiguration updatedConfig)
        {
            var newChecks = updatedConfig.ConnectivityChecks ?? new List<ConnectivityCheck>();

            if (newChecks.Count > 0)
            {
                if (_connectivityMonitor == null)
                {
                    // No había monitor activo: crear e iniciar
                    _connectivityMonitor = new ConnectivityMonitor(_wsClient!, newChecks);
                    _connectivityMonitor.Start();
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"CloudManager: ConnectivityMonitor iniciado tras config_update con {newChecks.Count} checks.");
                }
                else
                {
                    // Monitor ya activo: actualizar lista de checks
                    _connectivityMonitor.UpdateChecks(newChecks);
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"CloudManager: ConnectivityMonitor actualizado con {newChecks.Count} checks tras config_update.");
                }
            }
            else
            {
                // Lista vacía: detener y liberar ConnectivityMonitor si estaba activo
                if (_connectivityMonitor != null)
                {
                    _connectivityMonitor.Stop();
                    _connectivityMonitor.Dispose();
                    _connectivityMonitor = null;
                    AlwaysPrintLogger.WriteTrayInfo(
                        "CloudManager: ConnectivityMonitor detenido y liberado tras config_update (ConnectivityChecks vacío).");
                }
            }
        }

        // === Contingencia Forzada ===

        /// <summary>
        /// Procesa un mensaje de contingencia forzada recibido desde la Cloud.
        /// Muestra una notificación al usuario indicando que se está entrando o saliendo
        /// del modo contingencia forzada.
        /// </summary>
        private void HandleForcedContingency(string json)
        {
            try
            {
                var obj = JObject.Parse(json);
                bool enabled = obj["enabled"]?.Value<bool>() ?? false;
                string source = obj["source"]?.ToString() ?? "cloud";
                string sourceName = obj["source_name"]?.ToString() ?? "";
                string? printerIp = obj["printer_ip"]?.ToString();

                AlwaysPrintLogger.WriteTrayInfo(
                    $"CloudManager: contingencia forzada recibida. enabled={enabled}, source={source}, source_name={sourceName}, printer_ip={printerIp ?? "null"}");

                // Validación: si se activa contingencia pero no hay printer_ip, no enviar payload al Service
                if (enabled && string.IsNullOrEmpty(printerIp))
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "CloudManager: contingencia forzada recibida sin printer_ip. No se enviará payload al servicio.");

                    // Mostrar balloon tip informativo al usuario indicando que falló la activación
                    _uiContext.Post(_ =>
                    {
                        try
                        {
                            _trayIcon.ShowBalloonTip(
                                5000,
                                "AlwaysPrint",
                                "No se pudo activar contingencia: no hay impresora configurada",
                                ToolTipIcon.Warning);
                        }
                        catch (Exception ex)
                        {
                            AlwaysPrintLogger.WriteTrayWarning(
                                $"CloudManager: error mostrando balloon tip de contingencia sin IP. {ex.Message}");
                        }
                    }, null);

                    return;
                }

                // Notificar al Service vía Named Pipe
                try
                {
                    if (_pipe.IsConnected)
                    {
                        var payload = new ForcedContingencyPayload
                        {
                            Enabled = enabled,
                            Source = source,
                            SourceName = sourceName,
                            PrinterIp = printerIp
                        };
                        _pipe.Send(PipeMessage.Create(MessageType.ForcedContingencyChanged, payload));
                        AlwaysPrintLogger.WriteTrayInfo(
                            "CloudManager: notificación de contingencia forzada enviada al Service.");
                    }
                }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"CloudManager: error notificando contingencia forzada al Service. {ex.Message}");
                }

                // Mostrar notificación al usuario en el system tray
                _uiContext.Post(_ =>
                {
                    try
                    {
                        string title = "AlwaysPrint";
                        string message;

                        string sourceLabel = source switch
                        {
                            "workstation"  => "Workstation",
                            "vlan"         => "VLAN",
                            "organization" => "Organización",
                            _              => source
                        };

                        if (enabled)
                        {
                            message = $"Contingencia activada a nivel {sourceLabel}: {sourceName}";
                        }
                        else
                        {
                            message = $"Contingencia desactivada a nivel {sourceLabel}: {sourceName}";
                        }

                        _trayIcon.ShowBalloonTip(
                            5000,
                            title,
                            message,
                            enabled ? ToolTipIcon.Warning : ToolTipIcon.Info);
                    }
                    catch (Exception ex)
                    {
                        AlwaysPrintLogger.WriteTrayWarning(
                            $"CloudManager: error mostrando balloon tip de contingencia forzada. {ex.Message}");
                    }
                }, null);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudManager: error procesando mensaje forced_contingency. {ex.Message}");
            }
        }

        // === Cambio de impresora predeterminada de VLAN ===

        /// <summary>
        /// Procesa la notificación de cambio de impresora predeterminada de la VLAN.
        /// Muestra un balloon tip informativo al usuario.
        /// </summary>
        private void HandleDefaultPrinterChanged(string json)
        {
            try
            {
                var obj = JObject.Parse(json);
                string? printerName = obj["printer_name"]?.ToString();
                string? printerIp = obj["printer_ip"]?.ToString();
                string? vlanName = obj["vlan_name"]?.ToString();

                AlwaysPrintLogger.WriteTrayInfo(
                    $"CloudManager: impresora predeterminada de VLAN cambiada. printer={printerName ?? "ninguna"}, ip={printerIp ?? "null"}, vlan={vlanName}");

                // Mostrar notificación al usuario
                _uiContext.Post(_ =>
                {
                    try
                    {
                        string title = "APCM";
                        string message;

                        if (!string.IsNullOrEmpty(printerName))
                        {
                            message = $"Impresora predeterminada actualizada: {printerName} ({printerIp})";
                        }
                        else
                        {
                            message = "Se ha removido la impresora predeterminada de la VLAN.";
                        }

                        _trayIcon.ShowBalloonTip(5000, title, message, ToolTipIcon.Info);
                    }
                    catch (Exception ex)
                    {
                        AlwaysPrintLogger.WriteTrayWarning(
                            $"CloudManager: error mostrando balloon tip de cambio de impresora. {ex.Message}");
                    }
                }, null);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudManager: error procesando mensaje default_printer_changed. {ex.Message}");
            }
        }

        // === Heartbeat ===

        private void HandlePing()
        {
            try
            {
                _wsClient!.Send("pong", null);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"CloudManager: error enviando pong. {ex.Message}");
            }
        }

        // === Comandos Remotos ===

        /// <summary>
        /// Procesa un comando remoto recibido desde la Cloud.
        /// Soporta: restart_service, restart_tray, check_update.
        /// Envía el resultado de vuelta al servidor vía WebSocket.
        /// </summary>
        private void HandleCommand(string json)
        {
            string commandId = "unknown";
            string commandType = "unknown";

            try
            {
                var obj = JObject.Parse(json);
                commandId = obj["command_id"]?.ToString() ?? "unknown";
                commandType = obj["command_type"]?.ToString() ?? "unknown";

                AlwaysPrintLogger.WriteTrayInfo(
                    $"CloudManager: comando remoto recibido. command_id={commandId}, command_type={commandType}");

                switch (commandType)
                {
                    case "restart_service":
                        HandleRestartServiceCommand(commandId);
                        break;

                    case "restart_tray":
                        HandleRestartTrayCommand(commandId);
                        break;

                    case "check_update":
                        var paramsObj = obj["params"] as JObject;
                        HandleCheckUpdateCommand(commandId, paramsObj);
                        break;

                    case "get_latest_log":
                        HandleGetLatestLogCommand(commandId);
                        break;

                    case "analyze_log":
                        HandleAnalyzeLogCommand(commandId);
                        break;

                    case "execute_on_demand":
                        var execParams = obj["params"] as JObject;
                        HandleExecuteOnDemandCommand(commandId, execParams);
                        break;

                    // Comandos de debugging: delegados al DebuggingCommandHandler
                    case "start_debugging":
                    case "stop_debugging":
                    case "request_debug_upload":
                    case "delete_debug_data":
                        var debugParams = obj["params"] as JObject;
                        _debuggingHandler?.HandleCommand(commandType, commandId, debugParams);
                        break;

                    default:
                        // Comando desconocido
                        AlwaysPrintLogger.WriteTrayWarning(
                            $"CloudManager: comando remoto desconocido: {commandType}");
                        SendCommandResult(commandId, false, $"Comando desconocido: {commandType}");
                        break;
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudManager: error procesando comando remoto command_id={commandId}. {ex.Message}");
                SendCommandResult(commandId, false, $"Error interno: {ex.Message}");
            }
        }

        /// <summary>
        /// Ejecuta el comando restart_service: genera un script .cmd que reinicia el servicio.
        /// </summary>
        private void HandleRestartServiceCommand(string commandId)
        {
            var (success, message) = RestartServiceHandler.Execute();
            SendCommandResult(commandId, success, message);

            if (success)
            {
                AlwaysPrintLogger.WriteTrayInfo(
                    $"CloudManager: comando restart_service ejecutado exitosamente. El servicio se reiniciará en breve.");
            }
        }

        /// <summary>
        /// Ejecuta el comando restart_tray: envía resultado y luego cierra la aplicación.
        /// El Service detectará que el Tray no está corriendo y lo relanzará automáticamente.
        /// </summary>
        private void HandleRestartTrayCommand(string commandId)
        {
            // Enviar resultado ANTES de cerrar (para que el servidor reciba confirmación)
            SendCommandResult(commandId, true, "Tray se cerrará. El Service lo relanzará automáticamente.");

            AlwaysPrintLogger.WriteTrayInfo(
                "CloudManager: comando restart_tray recibido. Cerrando aplicación Tray...");

            // Cerrar la aplicación en el hilo UI
            _uiContext.Post(_ =>
            {
                Application.Exit();
            }, null);
        }

        /// <summary>
        /// Ejecuta el comando check_update: soporta dos flujos:
        /// 1. Push-based (normal): si params contiene download_url válida, descarga directa desde S3
        /// 2. Legacy fallback: si download_url ausente/vacío, dispara CheckUpdateRequested 
        ///    para que UpdateChecker.CheckNowAsync() haga un solo request HTTP al backend
        ///    (NO activa polling periódico, solo una verificación puntual).
        /// </summary>
        /// <param name="commandId">ID del comando para reportar resultado.</param>
        /// <param name="paramsObj">Params del comando WebSocket (puede contener download_url, version, file_size).</param>
        private void HandleCheckUpdateCommand(string commandId, JObject? paramsObj = null)
        {
            // Extraer download_url de los params (si viene del broadcast enriquecido zero-query)
            string? downloadUrl = paramsObj?["download_url"]?.ToString();

            if (!string.IsNullOrEmpty(downloadUrl))
            {
                // Flujo zero-query: descarga directa desde presigned URL de S3
                // Verificar flags de auto-actualización antes de proceder
                bool localFlag = _registry.LoadAutoUpdateEnabled();
                // Flag de organización: viene en los params del broadcast o del estado en _config
                bool orgFlag = paramsObj?["auto_update_enabled"]?.Value<bool>() ?? _config.AutoUpdateEnabled;

                if (!localFlag)
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        "CloudManager: check_update con download_url recibido pero flag local de auto-update deshabilitado. Ignorando.");
                    SendCommandResult(commandId, true, "Flag local de auto-update deshabilitado. Descarga no iniciada.");
                    return;
                }

                if (!orgFlag)
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        "CloudManager: check_update con download_url recibido pero flag de organización deshabilitado. Ignorando.");
                    SendCommandResult(commandId, true, "Flag de organización de auto-update deshabilitado. Descarga no iniciada.");
                    return;
                }

                // Ambos flags habilitados: iniciar descarga directa desde presigned URL
                long fileSize = paramsObj?["file_size"]?.Value<long>() ?? 0;
                string version = paramsObj?["version"]?.ToString() ?? "unknown";

                // Verificar que la versión ofrecida sea diferente a la instalada antes de descargar
                string currentVersion = System.Reflection.Assembly.GetExecutingAssembly()
                    .GetName().Version?.ToString() ?? "0.0.0.0";
                if (version == currentVersion)
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"CloudManager: check_update zero-query ignorado — versión ofrecida ({version}) es igual a la instalada.");
                    SendCommandResult(commandId, true, $"Versión ya instalada ({currentVersion}). Sin descarga.");
                    return;
                }

                HandleDirectDownload(downloadUrl, fileSize, version, commandId);
                return;
            }

            // Flujo legacy: sin download_url, disparar CheckUpdateRequested para verificación HTTP
            if (CheckUpdateRequested == null)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    "CloudManager: comando check_update recibido pero no hay suscriptor (UpdateChecker no inicializado).");
                SendCommandResult(commandId, false, "UpdateChecker no disponible.");
                return;
            }

            CheckUpdateRequested.Invoke();
            SendCommandResult(commandId, true, "Verificación de actualización iniciada.");
            AlwaysPrintLogger.WriteTrayInfo(
                "CloudManager: comando check_update ejecutado. Verificación de actualización disparada (flujo legacy).");
        }

        /// <summary>
        /// Maneja la descarga directa del MSI desde una presigned URL de S3 (flujo zero-query).
        /// Si la descarga falla (URL expirada, error de red), activa fallback al flujo legacy.
        /// </summary>
        /// <param name="downloadUrl">Presigned URL de S3 para descarga directa del MSI.</param>
        /// <param name="fileSize">Tamaño esperado del archivo en bytes para verificación de integridad.</param>
        /// <param name="version">Versión del MSI a descargar.</param>
        /// <param name="commandId">ID del comando para reportar resultado.</param>
        private async void HandleDirectDownload(string downloadUrl, long fileSize, string version, string commandId)
        {
            try
            {
                AlwaysPrintLogger.WriteTrayInfo(
                    $"CloudManager: iniciando descarga directa zero-query. Versión: {version}, tamaño: {fileSize} bytes.");

                string? filePath = await _updateDownloader.DownloadFromUrlAsync(downloadUrl, fileSize, version);

                if (filePath != null)
                {
                    // Enviar solicitud InstallUpdate al Service via Named Pipe
                    // para que ejecute msiexec (mismo flujo que OnUpdateAvailable)
                    if (_pipe.IsConnected)
                    {
                        var installPayload = new InstallUpdatePayload { MsiFilePath = filePath };
                        var installRequest = PipeMessage.Create(MessageType.InstallUpdate, installPayload);
                        _pipe.Send(installRequest);

                        AlwaysPrintLogger.WriteTrayInfo(
                            $"CloudManager: solicitud InstallUpdate enviada al Service. Ruta MSI: '{filePath}'.");
                    }
                    else
                    {
                        AlwaysPrintLogger.WriteTrayWarning(
                            "CloudManager: descarga completada pero pipe desconectado. " +
                            "No se pudo enviar InstallUpdate al Service.");
                    }

                    SendCommandResult(commandId, true, $"Descarga directa completada e instalación solicitada: {version}");
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"CloudManager: descarga directa zero-query completada exitosamente. Versión: {version}.");
                }
                else
                {
                    // DownloadFromUrlAsync retornó null → hubo un error o URL expirada
                    // Fallback al flujo legacy para reintentar vía endpoint del backend
                    AlwaysPrintLogger.WriteTrayWarning(
                        "CloudManager: descarga directa fallida. Activando fallback a flujo legacy.");
                    CheckUpdateRequested?.Invoke();
                    SendCommandResult(commandId, true, "Descarga directa fallida, flujo legacy activado.");
                }
            }
            catch (Exception ex)
            {
                // Error inesperado: fallback al flujo legacy
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudManager: error en descarga directa: {ex.Message}. Activando fallback a flujo legacy.");
                CheckUpdateRequested?.Invoke();
                SendCommandResult(commandId, false, $"Error descarga directa: {ex.Message}");
            }
        }

        /// <summary>
        /// Ejecuta el comando get_latest_log: lee el último archivo de log de la carpeta
        /// C:\ProgramData\AlwaysPrint\logs y envía su contenido codificado en base64.
        /// </summary>
        private void HandleGetLatestLogCommand(string commandId)
        {
            try
            {
                string logsFolder = @"C:\ProgramData\AlwaysPrint\logs";

                if (!System.IO.Directory.Exists(logsFolder))
                {
                    SendCommandResult(commandId, false, "La carpeta de logs no existe.");
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"CloudManager: comando get_latest_log - carpeta no encontrada: {logsFolder}");
                    return;
                }

                // Obtener el archivo más reciente por fecha de última escritura
                var logFiles = new System.IO.DirectoryInfo(logsFolder)
                    .GetFiles("*.*")
                    .OrderByDescending(f => f.LastWriteTimeUtc)
                    .ToArray();

                if (logFiles.Length == 0)
                {
                    SendCommandResult(commandId, false, "No se encontraron archivos de log.");
                    AlwaysPrintLogger.WriteTrayWarning(
                        "CloudManager: comando get_latest_log - no hay archivos en la carpeta de logs.");
                    return;
                }

                var latestFile = logFiles[0];

                // Limitar tamaño a 5 MB para evitar problemas de memoria/WebSocket
                const long maxSize = 5 * 1024 * 1024;
                if (latestFile.Length > maxSize)
                {
                    SendCommandResult(commandId, false,
                        $"El archivo de log es demasiado grande ({latestFile.Length / 1024 / 1024} MB). Máximo: 5 MB.");
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"CloudManager: comando get_latest_log - archivo demasiado grande: {latestFile.Length} bytes.");
                    return;
                }

                // Leer archivo con FileShare.ReadWrite para no bloquear escrituras activas
                byte[] fileContent;
                using (var fs = new System.IO.FileStream(
                    latestFile.FullName,
                    System.IO.FileMode.Open,
                    System.IO.FileAccess.Read,
                    System.IO.FileShare.ReadWrite))
                {
                    fileContent = new byte[fs.Length];
                    fs.Read(fileContent, 0, fileContent.Length);
                }

                // Codificar en base64 y enviar como JSON con nombre de archivo
                string base64Content = Convert.ToBase64String(fileContent);
                var resultJson = new JObject
                {
                    ["filename"] = latestFile.Name,
                    ["content"] = base64Content
                };

                SendCommandResult(commandId, true, resultJson.ToString(Formatting.None));
                AlwaysPrintLogger.WriteTrayInfo(
                    $"CloudManager: comando get_latest_log ejecutado. Archivo: {latestFile.Name}, " +
                    $"tamaño: {latestFile.Length} bytes.");
            }
            catch (Exception ex)
            {
                SendCommandResult(commandId, false, $"Error leyendo archivo de log: {ex.Message}");
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudManager: error ejecutando comando get_latest_log. {ex.Message}");
            }
        }

        /// <summary>
        /// Umbral de compresión configurable (default 50KB).
        /// Si el archivo de log es menor a este umbral, se comprime a ZIP antes de enviar.
        /// </summary>
        private const long DefaultCompressionThresholdBytes = 50 * 1024; // 50KB

        /// <summary>
        /// Ejecuta el comando analyze_log: lee el archivo de log del día actual,
        /// lo comprime a ZIP si es menor al umbral de compresión, codifica en base64
        /// y envía el resultado al servidor.
        /// </summary>
        private void HandleAnalyzeLogCommand(string commandId)
        {
            try
            {
                string logsFolder = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
                    "AlwaysPrint", "logs");

                // Construir nombre del archivo de log del día actual
                string datePart = DateTime.Now.ToString("yyyyMMdd");
                string logFileName = $"AlwaysPrint_{datePart}.log";
                string logFilePath = Path.Combine(logsFolder, logFileName);

                // Verificar si el archivo existe
                if (!File.Exists(logFilePath))
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"CloudManager: comando analyze_log - archivo no encontrado: {logFilePath}");
                    SendCommandResult(commandId, false, "Archivo de log del día actual no encontrado.");
                    return;
                }

                // Leer archivo con FileShare.ReadWrite para no bloquear escrituras activas del logger
                byte[] fileContent;
                using (var fs = new FileStream(
                    logFilePath,
                    FileMode.Open,
                    FileAccess.Read,
                    FileShare.ReadWrite))
                {
                    fileContent = new byte[fs.Length];
                    fs.Read(fileContent, 0, fileContent.Length);
                }

                long originalSize = fileContent.Length;

                // Determinar umbral de compresión (configurable, default 50KB)
                long compressionThreshold = DefaultCompressionThresholdBytes;

                // Decidir si comprimir según el umbral
                bool isCompressed;
                string base64Content;

                if (originalSize < compressionThreshold)
                {
                    // Comprimir a ZIP antes de enviar
                    byte[] zipContent = CompressToZip(logFileName, fileContent);
                    base64Content = Convert.ToBase64String(zipContent);
                    isCompressed = true;

                    AlwaysPrintLogger.WriteTrayInfo(
                        $"CloudManager: comando analyze_log - archivo comprimido. " +
                        $"Original: {originalSize} bytes, ZIP: {zipContent.Length} bytes.");
                }
                else
                {
                    // Enviar sin compresión
                    base64Content = Convert.ToBase64String(fileContent);
                    isCompressed = false;

                    AlwaysPrintLogger.WriteTrayInfo(
                        $"CloudManager: comando analyze_log - archivo enviado sin compresión. " +
                        $"Tamaño: {originalSize} bytes.");
                }

                // Construir resultado JSON con la estructura esperada por el backend
                var resultJson = new JObject
                {
                    ["filename"] = logFileName,
                    ["content"] = base64Content,
                    ["original_size"] = originalSize,
                    ["is_compressed"] = isCompressed
                };

                SendCommandResult(commandId, true, resultJson.ToString(Formatting.None));
                AlwaysPrintLogger.WriteTrayInfo(
                    $"CloudManager: comando analyze_log ejecutado exitosamente. " +
                    $"Archivo: {logFileName}, tamaño original: {originalSize} bytes, comprimido: {isCompressed}.");
            }
            catch (Exception ex)
            {
                SendCommandResult(commandId, false, $"Error procesando log para análisis: {ex.Message}");
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudManager: error ejecutando comando analyze_log. {ex.Message}");
            }
        }

        /// <summary>
        /// Comprime un archivo a formato ZIP en memoria.
        /// </summary>
        /// <param name="fileName">Nombre del archivo dentro del ZIP.</param>
        /// <param name="fileContent">Contenido del archivo a comprimir.</param>
        /// <returns>Bytes del archivo ZIP resultante.</returns>
        private static byte[] CompressToZip(string fileName, byte[] fileContent)
        {
            using (var memoryStream = new MemoryStream())
            {
                using (var archive = new ZipArchive(memoryStream, ZipArchiveMode.Create, leaveOpen: true))
                {
                    var entry = archive.CreateEntry(fileName, CompressionLevel.Optimal);
                    using (var entryStream = entry.Open())
                    {
                        entryStream.Write(fileContent, 0, fileContent.Length);
                    }
                }

                return memoryStream.ToArray();
            }
        }

        /// <summary>
        /// Ejecuta una acción OnDemand desde un comando remoto del servidor.
        /// Envía la solicitud al Service vía Named Pipe y espera el resultado.
        /// Incluye duration_ms en la respuesta para que el frontend muestre el tiempo de ejecución.
        /// </summary>
        private void HandleExecuteOnDemandCommand(string commandId, JObject? paramsObj)
        {
            string? label = paramsObj?["label"]?.ToString();

            if (string.IsNullOrEmpty(label))
            {
                SendCommandResult(commandId, false, "Parámetro 'label' no proporcionado");
                return;
            }

            AlwaysPrintLogger.WriteTrayInfo(
                $"CloudManager: ejecutando acción OnDemand remota. command_id={commandId}, label={label}");

            var stopwatch = System.Diagnostics.Stopwatch.StartNew();

            try
            {
                // Enviar al Service via Pipe
                var payload = new ExecuteOnDemandTriggerPayload { Label = label };
                var pipeMessage = PipeMessage.Create(MessageType.ExecuteOnDemandTrigger, payload);
                var response = _pipe.Send(pipeMessage);

                stopwatch.Stop();
                long durationMs = stopwatch.ElapsedMilliseconds;

                if (response == null)
                {
                    SendCommandResult(commandId, false, "No se recibió respuesta del Service (timeout)", durationMs);
                    return;
                }

                if (response.Type == MessageType.Error)
                {
                    var error = response.GetPayload<ErrorPayload>();
                    SendCommandResult(commandId, false, $"Error del Service: {error?.Message}", durationMs);
                    return;
                }

                var ack = response.GetPayload<AckPayload>();
                bool success = ack?.Success == true;
                string message = ack?.Message ?? (success ? "Acción ejecutada correctamente" : "Error al ejecutar acción");

                SendCommandResult(commandId, success, message, durationMs);

                AlwaysPrintLogger.WriteTrayInfo(
                    $"CloudManager: acción OnDemand completada. label={label}, success={success}, duration_ms={durationMs}");
            }
            catch (Exception ex)
            {
                stopwatch.Stop();
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudManager: error ejecutando acción OnDemand '{label}': {ex.Message}");
                SendCommandResult(commandId, false, $"Error: {ex.Message}", stopwatch.ElapsedMilliseconds);
            }
        }

        /// <summary>
        /// Envía el resultado de un comando remoto al servidor vía WebSocket.
        /// </summary>
        private void SendCommandResult(string commandId, bool success, string output, long? durationMs = null)
        {
            try
            {
                var payload = new JObject
                {
                    ["command_id"] = commandId,
                    ["success"] = success,
                    ["output"] = output
                };

                if (durationMs.HasValue)
                {
                    payload["duration_ms"] = durationMs.Value;
                }

                _wsClient!.Send("command_result", payload);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"CloudManager: error enviando command_result para command_id={commandId}. {ex.Message}");
            }
        }

        // === Notificación al Service ===

        private void NotifyServiceCloudStatus(bool connected)
        {
            try
            {
                if (!_pipe.IsConnected)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "CloudManager: pipe no conectado, no se puede notificar estado Cloud.");
                    return;
                }

                var payload = new CloudStatusResponsePayload
                {
                    IsConnected = connected,
                    LastConnectedAt = connected
                        ? DateTime.UtcNow.ToString("o")
                        : _credentials.LastConnectedAt?.ToString("o"),
                    ConfigHash = _credentials.ConfigHash,
                    UsingCachedConfig = !connected
                };

                _pipe.Send(PipeMessage.Create(MessageType.CloudStatusResponse, payload));
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudManager: error notificando estado Cloud al Service. {ex.Message}");
            }
        }

        /// <summary>
        /// Notifica al Service que la configuración de acciones cambió (o fue eliminada).
        /// El Service ejecutará ReloadActionConfiguration que detectará archivo ausente
        /// y descargará la configuración de memoria.
        /// </summary>
        private void NotifyServiceActionConfigChanged()
        {
            try
            {
                if (!_pipe.IsConnected)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "CloudManager: pipe no conectado, no se puede notificar invalidación de config al Service.");
                    return;
                }

                var msg = PipeMessage.Create(MessageType.ActionConfigChanged);
                _pipe.Send(msg);
                AlwaysPrintLogger.WriteTrayInfo(
                    "CloudManager: notificación ActionConfigChanged enviada al Service (config invalidada por cert mismatch).");
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudManager: error notificando invalidación de config al Service. {ex.Message}");
            }
        }

        // === Utilidades ===

        private static string GetPrivateIp()
        {
            try
            {
                // Usar NetworkHelper para obtener la IP de la interfaz con gateway (más confiable)
                string localIP = NetworkHelper.GetOutboundLocalIP();
                
                AlwaysPrintLogger.WriteTrayInfo(
                    $"CloudManager.GetPrivateIp: IP detectada = {localIP}");
                
                if (!string.IsNullOrEmpty(localIP) && localIP != "unknown")
                {
                    return localIP;
                }
                
                // Fallback al método antiguo si NetworkHelper falla
                AlwaysPrintLogger.WriteWarning(
                    "CloudManager.GetPrivateIp: NetworkHelper falló, usando método fallback",
                    AlwaysPrintLogger.EvtGenericWarning);
                
                var addresses = Dns.GetHostAddresses(Dns.GetHostName());
                var privateIp = addresses.FirstOrDefault(a =>
                    a.AddressFamily == AddressFamily.InterNetwork &&
                    IsPrivateIp(a));
                
                string fallbackIP = privateIp?.ToString() ?? "0.0.0.0";
                AlwaysPrintLogger.WriteTrayInfo(
                    $"CloudManager.GetPrivateIp: IP fallback = {fallbackIP}");
                
                return fallbackIP;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"CloudManager.GetPrivateIp: error detectando IP privada: {ex.Message}",
                    AlwaysPrintLogger.EvtGenericError);
                return "0.0.0.0";
            }
        }

        private static bool IsPrivateIp(IPAddress ip)
        {
            var bytes = ip.GetAddressBytes();
            return bytes[0] == 10 ||
                   (bytes[0] == 172 && bytes[1] >= 16 && bytes[1] <= 31) ||
                   (bytes[0] == 192 && bytes[1] == 168);
        }

        private static string GetOsSerial()
        {
            try
            {
                using (var searcher = new ManagementObjectSearcher(
                    "SELECT SerialNumber FROM Win32_OperatingSystem"))
                {
                    foreach (var obj in searcher.Get())
                    {
                        return obj["SerialNumber"]?.ToString() ?? "";
                    }
                }
                return "";
            }
            catch
            {
                return "";
            }
        }
        
        // === Gestión de Configuración de Acciones ===

        /// <summary>
        /// [DEPRECADO] Manejaba la notificación del servidor de que la configuración cambió
        /// descargando vía HTTP. Ahora la descarga directa desde S3 la gestiona el
        /// PushMessageHandler a través de RouteToPushHandler.
        /// 
        /// Se mantiene solo para actualizar el estado del UI (submenú OnDemand) cuando
        /// PushMessageHandler aplica exitosamente una config.
        /// </summary>
        [Obsolete("La descarga se gestiona vía PushMessageHandler.HandlePushMessage. " +
                   "Este método solo actualiza UI como efecto secundario.")]
        private async void HandleActionConfigChanged(string json)
        {
            try
            {
                // Extraer hash de la nueva config del mensaje (si viene)
                string? remoteHash = null;
                try
                {
                    var data = JObject.Parse(json);
                    remoteHash = data["config_hash"]?.ToString();
                }
                catch { }

                // Si el hash remoto coincide con el local, no hay cambio real → no hacer nada
                if (!string.IsNullOrEmpty(remoteHash))
                {
                    var localInfo = _configManager?.GetLocalConfigInfo();
                    if (localInfo != null && localInfo.Hash.Equals(remoteHash, StringComparison.OrdinalIgnoreCase))
                    {
                        AlwaysPrintLogger.WriteTrayInfo(
                            $"CloudManager: action_config_changed recibido pero hash local ({localInfo.Hash}) " +
                            $"coincide con remoto ({remoteHash}). Sin cambios.");
                        return;
                    }
                }

                // NOTA: La descarga se gestiona vía PushMessageHandler (RouteToPushHandler)
                // que descarga directamente desde S3. NO hacemos polling HTTP al backend.
                AlwaysPrintLogger.WriteTrayInfo(
                    $"CloudManager: action_config_changed recibido (hash={remoteHash ?? "?"}). " +
                    "Descarga delegada a PushMessageHandler vía S3 directo.");

                // Esperar a que PushMessageHandler complete la descarga y el Service
                // confirme la escritura. La actualización de UI se gestiona vía
                // HandleActionConfigChanged (pipe notification) que se ejecuta DESPUÉS
                // de que el archivo esté en disco.
                await Task.Delay(3000);

                // Solo loguear — no invocar ActionConfigUpdated aquí porque el archivo
                // puede no estar escrito aún. HandleActionConfigChanged se encarga de la UI.
                var updatedInfo = _configManager?.GetLocalConfigInfo();
                if (updatedInfo != null)
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"CloudManager: action_config_changed procesado. Config local: {updatedInfo.Name} hash={updatedInfo.Hash}");
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudManager: error procesando action_config_changed: {ex.Message}");
            }
        }

        /// <summary>
        /// [DEPRECADO] Wrapper síncrono para CheckActionConfigurationAsync.
        /// Ya no se invoca automáticamente al conectarse — la distribución es push-based.
        /// Se mantiene para compatibilidad durante la transición.
        /// </summary>
        [Obsolete("La distribución de configs es push-based. Usar GetCachedState() para verificación manual.")]
        private async void CheckActionConfiguration()
        {
            await CheckActionConfigurationAsync();
        }

        /// <summary>
        /// [DEPRECADO] Verifica y descarga la configuración de acciones desde la Cloud vía HTTP.
        /// Anteriormente era el flujo principal. Ahora la distribución es push-based:
        /// - Push messages → PushMessageHandler → descarga directa desde S3
        /// - Registration_Enrichment → ProcessRegistrationState → PushMessageHandler
        /// 
        /// Se mantiene como fallback para "Buscar Actualizaciones" durante el período de transición.
        /// Task 7.3 implementará la verificación manual usando GetCachedState() como fuente primaria.
        /// </summary>
        [Obsolete("Será reemplazado por verificación manual basada en GetCachedState() (Task 7.3).")]
        public async Task<bool> CheckActionConfigurationAsync()
        {
            try
            {
                if (_configManager == null || !_credentials.IsRegistered)
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        "CloudManager: no se puede verificar configuración de acciones (ConfigManager no inicializado o workstation no registrada)");
                    return false;
                }
                
                AlwaysPrintLogger.WriteTrayInfo("CloudManager: verificando configuración de acciones en Cloud");
                
                // Usar WorkstationId como API Key para autenticación
                bool success = await _configManager.CheckAndDownloadConfigAsync(
                    _config.CloudApiUrl,
                    _credentials.WorkstationId!,
                    _credentials.WorkstationId!);
                
                if (success)
                {
                    var localInfo = _configManager.GetLocalConfigInfo();
                    if (localInfo != null)
                    {
                        AlwaysPrintLogger.WriteTrayInfo(
                            $"CloudManager: configuración de acciones actualizada. " +
                            $"Nombre: {localInfo.Name}, Hash: {localInfo.Hash}");

                        // Notificar para reconstruir submenú OnDemand
                        ActionConfigUpdated?.Invoke(localInfo.Name, localInfo.Hash);
                    }
                    else
                    {
                        AlwaysPrintLogger.WriteTrayInfo(
                            "CloudManager: no hay configuración de acciones activa en Cloud");
                    }
                }
                else
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "CloudManager: error verificando configuración de acciones");
                }

                // Siempre reportar el estado de la config local al backend
                // (puede existir localmente aunque la Cloud no tenga config para esta org)
                var currentConfig = _configManager.GetLocalConfigInfo();
                SendActionConfigStatus(
                    currentConfig?.Name,
                    currentConfig?.Hash,
                    currentConfig?.Version);

                return success;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudManager: error en CheckActionConfigurationAsync: {ex.Message}");
                return false;
            }
        }

        /// <summary>
        /// Descarga los recursos de la VLAN (metadata, impresoras de contingencia)
        /// y los guarda en resources.json para uso offline.
        /// </summary>
        private async void DownloadResources()
        {
            try
            {
                if (_configManager == null || !_credentials.IsRegistered)
                    return;

                AlwaysPrintLogger.WriteTrayInfo("CloudManager: descargando recursos de VLAN");

                bool success = await _configManager.DownloadResourcesAsync(
                    _config.CloudApiUrl,
                    _credentials.WorkstationId!,
                    _credentials.WorkstationId!);

                if (success)
                    AlwaysPrintLogger.WriteTrayInfo("CloudManager: recursos de VLAN actualizados");
                else
                    AlwaysPrintLogger.WriteTrayWarning("CloudManager: error descargando recursos de VLAN");
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError($"CloudManager: error en DownloadResources: {ex.Message}");
            }
        }

        private void SendActionConfigStatus(string? configName, string? configHash)
        {
            SendActionConfigStatus(configName, configHash, null);
        }

        /// <summary>
        /// Envía status_update al servidor con la información de la action config activa.
        /// Se invoca después de verificar/actualizar la configuración de acciones.
        /// </summary>
        /// <param name="configName">Nombre de la config activa (null si no hay).</param>
        /// <param name="configHash">Hash de la config activa (null si no hay).</param>
        /// <param name="configVersion">Versión de la config activa (null si no hay).</param>
        private void SendActionConfigStatus(string? configName, string? configHash, string? configVersion)
        {
            try
            {
                if (_wsClient == null || !_wsClient.IsConnected) return;

                _wsClient.Send("status_update", new
                {
                    action_config_name = configName,
                    action_config_hash = configHash,
                    action_config_version = configVersion,
                    current_user = Environment.UserName
                });
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"CloudManager: error enviando status_update de action_config. {ex.Message}");
            }
        }
    }
}
