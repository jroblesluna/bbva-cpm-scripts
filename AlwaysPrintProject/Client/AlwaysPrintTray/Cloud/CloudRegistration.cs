using System;
using System.Net.Http;
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
    /// Gestiona el ciclo de registro automático de la workstation con el Cloud Manager.
    /// 
    /// Flujo:
    /// 1. Verifica si CloudEnabled=0 (modo local)
    /// 2. Hace health check de dominios bootstrap
    /// 3. Intenta registrarse cada X minutos
    /// 4. Si registro exitoso: activa CloudEnabled y guarda CloudApiUrl
    /// 5. Si registro rechazado (IP pendiente): espera y reintenta
    /// </summary>
    public sealed class CloudRegistration : IDisposable
    {
        private const int RetryIntervalSeconds = 300; // 5 minutos
        private const string RegisterPath = "/api/v1/workstations/register";
        
        private readonly AppConfiguration _config;
        private readonly Timer _registrationTimer;
        private readonly HttpClient _http;
        private bool _disposed;
        private bool _registrationInProgress;
        
        /// <summary>
        /// Evento que se dispara cuando el registro es exitoso.
        /// Parámetros: (workstationId, accountId, accountName, cloudApiUrl)
        /// </summary>
        public event Action<string, string, string, string>? RegistrationSuccessful;
        
        public CloudRegistration(AppConfiguration config)
        {
            _config = config ?? throw new ArgumentNullException(nameof(config));
            _http = DomainHealthChecker.Http; // Reutilizar HttpClient estático
            
            // Timer que se ejecuta cada 5 minutos
            _registrationTimer = new Timer(
                OnRegistrationTimerTick,
                null,
                TimeSpan.Zero, // Ejecutar inmediatamente
                TimeSpan.FromSeconds(RetryIntervalSeconds)
            );
            
            AlwaysPrintLogger.WriteTrayInfo(
                $"CloudRegistration: iniciado. Intervalo de reintento: {RetryIntervalSeconds}s");
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
            
            // 1. Health check de bootstrap para encontrar servidor cloud
            var (success, respondingDomain, details) = DomainHealthChecker.CheckAll(
                _config.BootstrapDomains,
                CancellationToken.None
            );
            
            if (!success || string.IsNullOrEmpty(respondingDomain))
            {
                AlwaysPrintLogger.WriteTrayInfo(
                    $"CloudRegistration: no se encontró servidor cloud. {details}");
                return;
            }
            
            AlwaysPrintLogger.WriteTrayInfo(
                $"CloudRegistration: servidor cloud encontrado: {respondingDomain}");
            
            // 2. Construir URL de registro
            string cloudApiUrl = $"https://{respondingDomain}";
            string registerUrl = $"{cloudApiUrl}{RegisterPath}";
            
            AlwaysPrintLogger.WriteTrayInfo(
                $"CloudRegistration: intentando registro en: {registerUrl}");
            
            // 3. Preparar datos de registro
            string localIP = NetworkHelper.GetOutboundLocalIP();
            
            var registerData = new
            {
                ip_private = localIP,
                hostname = Environment.MachineName,
                os_serial = GetOsSerial(),
                current_user = Environment.UserName
            };
            
            AlwaysPrintLogger.WriteTrayInfo(
                $"CloudRegistration: datos de registro: " +
                $"ip_private={localIP}, " +
                $"hostname={Environment.MachineName}, " +
                $"current_user={Environment.UserName}");
            
            // 4. Enviar solicitud de registro
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
                    string accountId = result["account_id"]?.ToString() ?? "";
                    string accountName = result["account_name"]?.ToString() ?? "";
                    string message = result["message"]?.ToString() ?? "";
                    
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"CloudRegistration: ¡Registro exitoso! " +
                        $"workstation_id={workstationId}, " +
                        $"account_id={accountId}, " +
                        $"account_name={accountName}, " +
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
