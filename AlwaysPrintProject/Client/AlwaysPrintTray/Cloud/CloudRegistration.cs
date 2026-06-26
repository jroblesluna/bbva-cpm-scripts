using System;
using System.Net.Http;
using System.Reflection;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Network;
using AlwaysPrintTray.Bootstrap;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace AlwaysPrintTray.Cloud
{
    /// <summary>
    /// Estado de conectividad del registro Cloud, expuesto para consumo del StatusForm.
    /// </summary>
    public sealed class CloudConnectivityState
    {
        /// <summary>Estado actual: Connecting, Connected, Disconnected.</summary>
        public string Status { get; set; } = "Connecting";

        /// <summary>Cantidad de intentos fallidos consecutivos desde la última conexión exitosa.</summary>
        public int FailedAttempts { get; set; }

        /// <summary>Timestamp UTC del primer fallo consecutivo (null si conectado).</summary>
        public DateTime? DisconnectedSince { get; set; }

        /// <summary>Timestamp UTC desde que está conectado (null si no conectado).</summary>
        public DateTime? ConnectedSince { get; set; }

        /// <summary>Último error reportado (timeout, error de red, etc.).</summary>
        public string? LastError { get; set; }

        /// <summary>Intervalo actual de reintento en segundos.</summary>
        public int CurrentRetryIntervalSeconds { get; set; }

        /// <summary>Timestamp UTC del último intento realizado.</summary>
        public DateTime? LastAttemptAt { get; set; }

        /// <summary>Duración de la desconexión actual, o null si está conectado.</summary>
        public TimeSpan? DisconnectedDuration =>
            DisconnectedSince.HasValue ? DateTime.UtcNow - DisconnectedSince.Value : null;

        /// <summary>Duración de la conexión actual, o null si no está conectado.</summary>
        public TimeSpan? ConnectedDuration =>
            ConnectedSince.HasValue ? DateTime.UtcNow - ConnectedSince.Value : null;
    }

    /// <summary>
    /// Gestiona el ciclo de registro automático de la workstation con el Cloud Manager.
    /// 
    /// Flujo:
    /// 1. Verifica si CloudEnabled=0 (modo local)
    /// 2. Detecta CIDR de la interfaz de red (si no disponible, reintenta periódicamente)
    /// 3. Hace health check de dominios bootstrap
    /// 4. Intenta registrarse cada X minutos
    /// 5. Si registro exitoso: activa CloudEnabled y guarda CloudApiUrl
    /// 6. Si registro rechazado (IP pendiente): espera y reintenta
    /// 
    /// Retry agresivo: los primeros intentos fallidos usan intervalo corto (30s)
    /// para recuperarse rápidamente cuando el proxy corporativo aún no está listo
    /// tras un logon. Después de N intentos rápidos, escala al intervalo normal (300s).
    /// </summary>
    public sealed class CloudRegistration : IDisposable
    {
        private const int RetryIntervalSeconds = 300; // 5 minutos (intervalo normal)
        private const int AggressiveRetryIntervalSeconds = 30; // 30 segundos (retry agresivo post-logon)
        private const int MaxAggressiveRetries = 6; // Máximo de reintentos rápidos antes de escalar
        private const int CidrRetryIntervalSeconds = 30; // 30 segundos para reintentar detección de CIDR
        private const string RegisterPath = "/api/v1/workstations/register";
        
        private readonly AppConfiguration _config;
        private readonly Timer _registrationTimer;
        private readonly HttpClient _http;
        private bool _disposed;
        private bool _registrationInProgress;
        
        // Estado de detección de CIDR
        private string? _detectedCidr;
        private bool _cidrErrorNotified;

        // === Estado de conectividad y retry agresivo ===
        private int _consecutiveHealthCheckFailures;
        private DateTime? _firstFailureAt;
        private DateTime? _connectedSince;
        private string? _lastHealthCheckError;
        private readonly object _stateLock = new object();
        
        /// <summary>
        /// Evento que se dispara cuando el registro es exitoso.
        /// Parámetros: (workstationId, accountId, accountName, cloudApiUrl)
        /// </summary>
        public event Action<string, string, string, string>? RegistrationSuccessful;

        /// <summary>
        /// Evento que se dispara cuando la IP pública está pendiente de aprobación.
        /// Se dispara solo la primera vez que se detecta (no en cada reintento).
        /// </summary>
        public event Action? RegistrationPending;

        /// <summary>
        /// Evento que se dispara cuando no se puede detectar el CIDR de la red.
        /// Se dispara solo la primera vez que se detecta (no en cada reintento).
        /// </summary>
        public event Action? CidrDetectionFailed;

        /// <summary>
        /// Evento que se dispara cuando el CIDR se detecta exitosamente después de un fallo previo.
        /// </summary>
        public event Action? CidrDetectionRecovered;

        /// <summary>
        /// Evento que se dispara cuando cambia el estado de conectividad Cloud.
        /// Permite al StatusForm actualizar la sección de conectividad en tiempo real.
        /// </summary>
        public event Action<CloudConnectivityState>? ConnectivityStateChanged;

        private bool _pendingNotified;
        
        public CloudRegistration(AppConfiguration config)
        {
            _config = config ?? throw new ArgumentNullException(nameof(config));
            _http = DomainHealthChecker.Http; // Reutilizar HttpClient estático
            
            // Timer que se ejecuta cada 5 minutos (o más frecuente si CIDR no disponible)
            _registrationTimer = new Timer(
                OnRegistrationTimerTick,
                null,
                TimeSpan.Zero, // Ejecutar inmediatamente
                TimeSpan.FromSeconds(RetryIntervalSeconds)
            );
            
            AlwaysPrintLogger.WriteTrayInfo(
                $"CloudRegistration: iniciado. Intervalo de reintento: {RetryIntervalSeconds}s");

            // Notificar estado inicial: conectando
            NotifyConnectivityState("Connecting", null);
        }

        /// <summary>
        /// Obtiene una copia del estado actual de conectividad (thread-safe).
        /// Útil para que el StatusForm lea el estado al abrirse.
        /// </summary>
        public CloudConnectivityState GetConnectivityState()
        {
            lock (_stateLock)
            {
                string status = _connectedSince.HasValue ? "Connected"
                    : _firstFailureAt.HasValue ? "Disconnected"
                    : "Connecting";

                return new CloudConnectivityState
                {
                    Status = status,
                    FailedAttempts = _consecutiveHealthCheckFailures,
                    DisconnectedSince = _firstFailureAt,
                    ConnectedSince = _connectedSince,
                    LastError = _lastHealthCheckError,
                    CurrentRetryIntervalSeconds = GetCurrentRetryInterval(),
                    LastAttemptAt = DateTime.UtcNow
                };
            }
        }

        /// <summary>
        /// Determina el intervalo de retry actual basado en la cantidad de fallos consecutivos.
        /// Los primeros MaxAggressiveRetries intentos usan intervalo corto (30s),
        /// luego escala al intervalo normal (300s).
        /// </summary>
        private int GetCurrentRetryInterval()
        {
            if (_consecutiveHealthCheckFailures < MaxAggressiveRetries)
                return AggressiveRetryIntervalSeconds;
            return RetryIntervalSeconds;
        }
        
        private void OnRegistrationTimerTick(object? state)
        {
            if (_disposed || _registrationInProgress)
                return;
            
            // Solo intentar registro si CloudEnabled=0 (modo local)
            if (_config.CloudEnabled)
            {
                AlwaysPrintLogger.WriteTrayInfo(
                    "CloudRegistration: CloudEnabled=1, deteniendo ciclo de registro");
                _registrationTimer.Change(Timeout.Infinite, Timeout.Infinite);
                return;
            }
            
            _registrationInProgress = true;
            
            try
            {
                // Intentar detectar CIDR antes de registrar
                _detectedCidr = NetworkHelper.GetOutboundCIDR();
                
                if (string.IsNullOrEmpty(_detectedCidr))
                {
                    // CIDR no disponible: no intentar registro
                    AlwaysPrintLogger.WriteError(
                        "CloudRegistration: no se pudo detectar el CIDR de la red. " +
                        "No se intentará registro sin CIDR. Verificar conexión de red.",
                        AlwaysPrintLogger.EvtGenericError);
                    
                    // Notificar al usuario solo la primera vez
                    if (!_cidrErrorNotified)
                    {
                        _cidrErrorNotified = true;
                        CidrDetectionFailed?.Invoke();
                    }
                    
                    // Cambiar intervalo a más frecuente para reintentar detección de CIDR
                    _registrationTimer.Change(
                        TimeSpan.FromSeconds(CidrRetryIntervalSeconds),
                        TimeSpan.FromSeconds(CidrRetryIntervalSeconds));
                    
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"CloudRegistration: reintentando detección de CIDR en {CidrRetryIntervalSeconds}s");
                    return;
                }
                
                // CIDR detectado exitosamente
                if (_cidrErrorNotified)
                {
                    // Se recuperó después de un fallo previo
                    _cidrErrorNotified = false;
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"CloudRegistration: CIDR detectado exitosamente después de fallo previo: {_detectedCidr}");
                    CidrDetectionRecovered?.Invoke();
                    
                    // Restaurar intervalo normal de registro
                    _registrationTimer.Change(
                        TimeSpan.Zero,
                        TimeSpan.FromSeconds(RetryIntervalSeconds));
                    return; // Se ejecutará inmediatamente con el nuevo intervalo
                }
                
                TryRegisterAsync().GetAwaiter().GetResult();
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"CloudRegistration: error en ciclo de registro: {ex.Message}",
                    AlwaysPrintLogger.EvtGenericError);
            }
            finally
            {
                _registrationInProgress = false;
            }
        }
        
        private async Task TryRegisterAsync()
        {
            AlwaysPrintLogger.WriteTrayInfo(
                "CloudRegistration: iniciando intento de registro...");
            
            // Verificar que CIDR esté disponible (no intentar registro sin CIDR)
            if (string.IsNullOrEmpty(_detectedCidr))
            {
                AlwaysPrintLogger.WriteError(
                    "CloudRegistration: CIDR no disponible. No se puede registrar sin CIDR.",
                    AlwaysPrintLogger.EvtGenericError);
                return;
            }
            
            AlwaysPrintLogger.WriteTrayInfo(
                $"CloudRegistration: CIDR detectado: {_detectedCidr}");
            
            // Obtener versión del Tray desde el Assembly
            string trayVersion = GetTrayVersion();
            
            // 1. Health check de bootstrap para encontrar servidor cloud
            var (success, respondingDomain, details) = DomainHealthChecker.CheckAll(
                _config.BootstrapDomains,
                CancellationToken.None
            );
            
            if (!success || string.IsNullOrEmpty(respondingDomain))
            {
                // Health check falló: registrar fallo y aplicar retry agresivo si corresponde
                OnHealthCheckFailed(details ?? "Sin detalles");
                return;
            }
            
            // Health check exitoso: resetear contador de fallos
            OnHealthCheckSucceeded();
            
            AlwaysPrintLogger.WriteTrayInfo(
                $"CloudRegistration: servidor cloud encontrado: {respondingDomain}");
            
            // 2. Construir URL de registro
            string cloudApiUrl = $"https://{respondingDomain}";
            string registerUrl = $"{cloudApiUrl}{RegisterPath}";
            
            AlwaysPrintLogger.WriteTrayInfo(
                $"CloudRegistration: intentando registro en: {registerUrl}");
            
            // 3. Preparar datos de registro (incluye cidr y tray_version)
            string localIP = NetworkHelper.GetOutboundLocalIP();
            
            var registerData = new
            {
                ip_private = localIP,
                hostname = Environment.MachineName,
                os_serial = GetOsSerial(),
                current_user = Environment.UserName,
                cidr = _detectedCidr,
                tray_version = trayVersion
            };
            
            AlwaysPrintLogger.WriteTrayInfo(
                $"CloudRegistration: datos de registro: " +
                $"ip_private={localIP}, " +
                $"hostname={Environment.MachineName}, " +
                $"current_user={Environment.UserName}, " +
                $"cidr={_detectedCidr}, " +
                $"tray_version={trayVersion}");
            
            // 6. Enviar solicitud de registro
            try
            {
                string jsonPayload = JsonConvert.SerializeObject(registerData);
                var content = new StringContent(jsonPayload, Encoding.UTF8, "application/json");
                
                var response = await _http.PostAsync(registerUrl, content);
                string responseBody = await response.Content.ReadAsStringAsync();
                
                AlwaysPrintLogger.WriteTrayInfo(
                    $"CloudRegistration: respuesta HTTP {(int)response.StatusCode}: {responseBody}");
                
                if (response.IsSuccessStatusCode)
                {
                    // Registro exitoso
                    var result = JObject.Parse(responseBody);
                    string workstationId = result["workstation_id"]?.ToString() ?? "";
                    string accountId = result["organization_id"]?.ToString() ?? "";
                    string accountName = result["organization_name"]?.ToString() ?? "";
                    string message = result["message"]?.ToString() ?? "";
                    
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"CloudRegistration: ¡Registro exitoso! " +
                        $"workstation_id={workstationId}, " +
                        $"organization_id={accountId}, " +
                        $"organization_name={accountName}, " +
                        $"message={message}",
                        AlwaysPrintLogger.EvtServiceStarted);
                    
                    // Disparar evento de registro exitoso
                    RegistrationSuccessful?.Invoke(workstationId, accountId, accountName, cloudApiUrl);
                }
                else if (response.StatusCode == System.Net.HttpStatusCode.Forbidden)
                {
                    // IP pública pendiente de autorización
                    var result = JObject.Parse(responseBody);
                    
                    // El backend puede devolver el error en "detail" (FastAPI)
                    var detail = result["detail"];
                    string status = "";
                    string publicIp = "";
                    string message = "";
                    int retryAfter = RetryIntervalSeconds;
                    
                    if (detail != null && detail.Type == JTokenType.Object)
                    {
                        // Formato estructurado
                        status = detail["status"]?.ToString() ?? "";
                        publicIp = detail["public_ip"]?.ToString() ?? "";
                        message = detail["message"]?.ToString() ?? "";
                        retryAfter = detail["retry_after_seconds"]?.Value<int>() ?? RetryIntervalSeconds;
                    }
                    else if (detail != null && detail.Type == JTokenType.String)
                    {
                        // Formato string simple
                        message = detail.ToString();
                    }
                    
                    AlwaysPrintLogger.WriteWarning(
                        $"CloudRegistration: IP pública pendiente de autorización. " +
                        $"public_ip={publicIp}, " +
                        $"message={message}, " +
                        $"retry_after={retryAfter}s",
                        AlwaysPrintLogger.EvtGenericWarning);
                    
                    // Notificar solo la primera vez
                    if (!_pendingNotified)
                    {
                        _pendingNotified = true;
                        RegistrationPending?.Invoke();
                    }
                    
                    // Continuar reintentando según el intervalo configurado
                }
                else
                {
                    // Otro error
                    AlwaysPrintLogger.WriteWarning(
                        $"CloudRegistration: error en registro. " +
                        $"HTTP {(int)response.StatusCode}: {responseBody}",
                        AlwaysPrintLogger.EvtGenericWarning);
                }
            }
            catch (HttpRequestException ex)
            {
                AlwaysPrintLogger.WriteWarning(
                    $"CloudRegistration: error de red al intentar registro: {ex.Message}",
                    AlwaysPrintLogger.EvtGenericWarning);
            }
            catch (TaskCanceledException ex)
            {
                AlwaysPrintLogger.WriteWarning(
                    $"CloudRegistration: timeout al intentar registro: {ex.Message}",
                    AlwaysPrintLogger.EvtGenericWarning);
            }
            catch (JsonException ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"CloudRegistration: error al parsear respuesta JSON: {ex.Message}",
                    AlwaysPrintLogger.EvtGenericError);
            }
        }
        
        /// <summary>
        /// Maneja un fallo en el health check: incrementa contador, registra timestamp,
        /// ajusta el intervalo de retry (agresivo si estamos en los primeros intentos),
        /// y notifica el cambio de estado.
        /// </summary>
        private void OnHealthCheckFailed(string errorDetails)
        {
            lock (_stateLock)
            {
                _consecutiveHealthCheckFailures++;
                _lastHealthCheckError = errorDetails;
                _connectedSince = null;

                if (!_firstFailureAt.HasValue)
                    _firstFailureAt = DateTime.UtcNow;
            }

            int currentInterval = GetCurrentRetryInterval();
            bool isAggressive = _consecutiveHealthCheckFailures <= MaxAggressiveRetries;

            AlwaysPrintLogger.WriteTrayInfo(
                $"CloudRegistration: no se encontró servidor cloud (intento #{_consecutiveHealthCheckFailures}). " +
                $"Próximo reintento en {currentInterval}s{(isAggressive ? " (modo agresivo)" : "")}. {errorDetails}");

            // Ajustar timer al intervalo correspondiente
            _registrationTimer.Change(
                TimeSpan.FromSeconds(currentInterval),
                TimeSpan.FromSeconds(currentInterval));

            // Notificar cambio de estado al UI
            NotifyConnectivityState("Disconnected", errorDetails);
        }

        /// <summary>
        /// Maneja un health check exitoso: resetea contadores de fallo,
        /// restaura el intervalo normal y notifica estado conectado.
        /// </summary>
        private void OnHealthCheckSucceeded()
        {
            bool wasDisconnected;
            int previousFailures;

            lock (_stateLock)
            {
                wasDisconnected = _firstFailureAt.HasValue;
                previousFailures = _consecutiveHealthCheckFailures;
                _consecutiveHealthCheckFailures = 0;
                _firstFailureAt = null;
                _lastHealthCheckError = null;
                if (!_connectedSince.HasValue)
                    _connectedSince = DateTime.UtcNow;
            }

            if (wasDisconnected)
            {
                AlwaysPrintLogger.WriteTrayInfo(
                    $"CloudRegistration: conectividad restaurada después de {previousFailures} intentos fallidos.");

                // Restaurar intervalo normal
                _registrationTimer.Change(
                    Timeout.Infinite,
                    Timeout.Infinite);
            }

            // Notificar estado conectado al UI
            NotifyConnectivityState("Connected", null);
        }

        /// <summary>
        /// Construye y emite el evento de cambio de estado de conectividad.
        /// </summary>
        private void NotifyConnectivityState(string status, string? lastError)
        {
            var state = new CloudConnectivityState
            {
                Status = status,
                FailedAttempts = _consecutiveHealthCheckFailures,
                DisconnectedSince = _firstFailureAt,
                ConnectedSince = _connectedSince,
                LastError = lastError,
                CurrentRetryIntervalSeconds = GetCurrentRetryInterval(),
                LastAttemptAt = DateTime.UtcNow
            };

            ConnectivityStateChanged?.Invoke(state);
        }

        /// <summary>
        /// Obtiene la versión del Tray desde el Assembly ejecutable.
        /// Retorna la versión en formato "Major.Minor.Build.Revision" (ej: "2.1.0.0").
        /// </summary>
        private static string GetTrayVersion()
        {
            try
            {
                var assembly = Assembly.GetExecutingAssembly();
                var version = assembly.GetName().Version;
                return version?.ToString() ?? "0.0.0.0";
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteWarning(
                    $"CloudRegistration: error al obtener versión del Tray: {ex.Message}",
                    AlwaysPrintLogger.EvtGenericWarning);
                return "0.0.0.0";
            }
        }

        private static string GetOsSerial()
        {
            try
            {
                using (var searcher = new System.Management.ManagementObjectSearcher(
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
        
        public void Dispose()
        {
            if (_disposed)
                return;
            
            _disposed = true;
            _registrationTimer?.Dispose();
            
            AlwaysPrintLogger.WriteTrayInfo("CloudRegistration: disposed");
        }
    }
}
