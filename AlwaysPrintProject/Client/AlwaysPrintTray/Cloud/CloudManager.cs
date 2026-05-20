using System;
using System.Collections.Generic;
using System.Linq;
using System.Management;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Messages;
using AlwaysPrint.Shared.Network;
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
        /// Se dispara cuando se recibe un comando remoto "check_update" desde la Cloud.
        /// El suscriptor (TrayApplicationContext) debe invocar UpdateChecker.CheckNowAsync().
        /// </summary>
        public event Action? CheckUpdateRequested;

        private readonly AppConfiguration _config;
        private readonly CloudCredentialsManager _credentials;
        private readonly PipeClient _pipe;
        private readonly SynchronizationContext _uiContext;
        private readonly NotifyIcon _trayIcon;

        private CloudWebSocketClient? _wsClient;
        private ConfigurationSync? _configSync;
        private ConfigManager? _configManager;
        private TelemetryReporter? _telemetryReporter;
        private ConnectivityMonitor? _connectivityMonitor;
        private OfflineStateManager? _offlineState;
        private bool _noConfigWarningShown;
        private bool _disposed;

        /// <summary>
        /// Crea una nueva instancia de CloudManager.
        /// </summary>
        /// <param name="config">Configuración de la aplicación con CloudApiUrl.</param>
        /// <param name="credentials">Gestor de credenciales Cloud en HKCU.</param>
        /// <param name="pipe">Cliente Named Pipe para notificar al Service.</param>
        /// <param name="uiContext">Contexto de sincronización del hilo UI.</param>
        /// <param name="trayIcon">Referencia al NotifyIcon del system tray.</param>
        public CloudManager(
            AppConfiguration config,
            CloudCredentialsManager credentials,
            PipeClient pipe,
            SynchronizationContext uiContext,
            NotifyIcon trayIcon)
        {
            _config = config;
            _credentials = credentials;
            _pipe = pipe;
            _uiContext = uiContext;
            _trayIcon = trayIcon;
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
            
            // Nota: CheckActionConfiguration() y el evento Registered se disparan
            // en HandleRegistered() después de recibir confirmación del servidor.
            // Si la workstation ya estaba registrada y el servidor no envía "registered"
            // explícitamente, HandleRegistered no se ejecutará — pero eso es correcto:
            // el UpdateChecker solo debe iniciar cuando el servidor confirma el registro.
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
                default:
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"CloudManager: mensaje recibido tipo='{type}' (sin handler).");
                    break;
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
                    
                    // Verificar configuración de acciones ahora que tenemos WorkstationId
                    CheckActionConfiguration();
                }

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

                        if (enabled)
                        {
                            message = $"Se está entrando en modo contingencia (origen: {sourceName}).";
                        }
                        else
                        {
                            message = $"Se ha desactivado el modo contingencia (origen: {sourceName}).";
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
                        HandleCheckUpdateCommand(commandId);
                        break;

                    case "get_latest_log":
                        HandleGetLatestLogCommand(commandId);
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
        /// Ejecuta el comando check_update: dispara el evento para que TrayApplicationContext
        /// invoque UpdateChecker.CheckNowAsync().
        /// </summary>
        private void HandleCheckUpdateCommand(string commandId)
        {
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
                "CloudManager: comando check_update ejecutado. Verificación de actualización disparada.");
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
        /// Envía el resultado de un comando remoto al servidor vía WebSocket.
        /// </summary>
        private void SendCommandResult(string commandId, bool success, string output)
        {
            try
            {
                var payload = new JObject
                {
                    ["command_id"] = commandId,
                    ["success"] = success,
                    ["output"] = output
                };

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
        /// Verifica y descarga la configuración de acciones desde la Cloud si es necesaria.
        /// Se ejecuta automáticamente al conectarse a la Cloud.
        /// </summary>
        private async void CheckActionConfiguration()
        {
            try
            {
                if (_configManager == null || !_credentials.IsRegistered)
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        "CloudManager: no se puede verificar configuración de acciones (ConfigManager no inicializado o workstation no registrada)");
                    return;
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
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudManager: error en CheckActionConfiguration: {ex.Message}");
            }
        }
    }
}
