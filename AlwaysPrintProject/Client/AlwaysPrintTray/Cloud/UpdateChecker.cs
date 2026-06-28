using System;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Network;
using Newtonsoft.Json;

namespace AlwaysPrintTray.Cloud
{
    /// <summary>
    /// [DEPRECADO] Verificaba periódicamente si hay actualizaciones disponibles consultando
    /// al Cloud Backend vía polling HTTP a /api/v1/updates/check cada 24 horas.
    /// 
    /// Con la implementación de push-based distribution, las actualizaciones de MSI
    /// ahora llegan vía WebSocket (MSI_Push_Message tipo "check_update") con presigned URL
    /// de S3 para descarga directa. El PushMessageHandler gestiona estos mensajes.
    /// 
    /// El polling periódico ha sido DESHABILITADO. Se mantiene únicamente:
    /// - CheckNowAsync() como fallback para comandos remotos "check_update" legacy
    ///   que no incluyen download_url (durante período de transición).
    /// - La clase permanece instanciada pero sin timer activo.
    /// 
    /// Será eliminada completamente cuando se complete la migración a push-based distribution.
    /// </summary>
    [Obsolete("La verificación de actualizaciones MSI es push-based vía WebSocket (PushMessageHandler). " +
               "El polling periódico ha sido deshabilitado. CheckNowAsync() se mantiene como fallback legacy.")]
    public class UpdateChecker : IDisposable
    {
        private readonly Timer _timer;
        private readonly RegistryConfigManager _registry;
        private readonly string _cloudApiUrl;
        private readonly string _currentVersion;
        private readonly HttpClient _httpClient;
        private bool _disposed;

        /// <summary>Intervalo de verificación: 24 horas en milisegundos.</summary>
        private const int CheckIntervalMs = 86_400_000;

        /// <summary>
        /// Se dispara cuando hay una actualización disponible y lista para descargar.
        /// El suscriptor recibe un objeto UpdateInfo con la versión, tamaño y estado del flag de organización.
        /// </summary>
        public event Action<UpdateInfo>? UpdateAvailable;

        /// <summary>
        /// Crea una nueva instancia de UpdateChecker.
        /// </summary>
        /// <param name="registry">Gestor de configuración del registro para leer el flag local.</param>
        /// <param name="cloudApiUrl">URL base de la API Cloud (ej: https://alwaysprint.apps.iol.pe).</param>
        /// <param name="currentVersion">Versión actualmente instalada del cliente.</param>
        public UpdateChecker(RegistryConfigManager registry, string cloudApiUrl, string currentVersion)
        {
            _registry = registry ?? throw new ArgumentNullException(nameof(registry));
            _cloudApiUrl = cloudApiUrl ?? throw new ArgumentNullException(nameof(cloudApiUrl));
            _currentVersion = currentVersion ?? throw new ArgumentNullException(nameof(currentVersion));

            // Crear HttpClient con timeout razonable para evitar bloqueos prolongados
            _httpClient = new HttpClient
            {
                Timeout = TimeSpan.FromSeconds(30)
            };

            // Crear timer sin iniciar (Timeout.Infinite = no dispara)
            _timer = new Timer(OnTimerElapsed, null, Timeout.Infinite, Timeout.Infinite);
        }

        /// <summary>
        /// [DEPRECADO] Anteriormente iniciaba la verificación periódica de actualizaciones cada 24h.
        /// 
        /// Con push-based distribution, las actualizaciones de MSI llegan vía WebSocket
        /// (MSI_Push_Message) y se gestionan por PushMessageHandler. El polling periódico
        /// ha sido deshabilitado para eliminar la dependencia del endpoint /api/v1/updates/check.
        /// 
        /// Se mantiene el método para compatibilidad de interfaz pero NO activa el timer.
        /// CheckNowAsync() sigue disponible como fallback para comandos remotos legacy.
        /// </summary>
        [Obsolete("Polling periódico de MSI deshabilitado. Usar push-based distribution vía PushMessageHandler.")]
        public void Start()
        {
            bool autoUpdateEnabled = _registry.LoadAutoUpdateEnabled();

            if (!autoUpdateEnabled)
            {
                AlwaysPrintLogger.WriteTrayInfo(
                    "UpdateChecker: auto-actualización deshabilitada localmente. No se inicia verificación periódica.");
                return;
            }

            // NOTA: El timer periódico ha sido DESHABILITADO intencionalmente.
            // Las actualizaciones de MSI ahora llegan vía WebSocket push (check_update message).
            // El PushMessageHandler compara la versión y gestiona la descarga directa desde S3.
            // Se mantiene CheckNowAsync() como fallback para comandos remotos legacy sin download_url.
            AlwaysPrintLogger.WriteTrayInfo(
                "UpdateChecker: polling periódico de actualizaciones DESHABILITADO (push-based distribution activa). " +
                "CheckNowAsync() disponible como fallback para comandos remotos legacy.");
        }

        /// <summary>
        /// Detiene la verificación periódica de actualizaciones.
        /// </summary>
        public void Stop()
        {
            _timer.Change(Timeout.Infinite, Timeout.Infinite);
            AlwaysPrintLogger.WriteTrayInfo("UpdateChecker: verificación periódica detenida.");
        }

        /// <summary>
        /// [LEGACY FALLBACK] Ejecuta una verificación inmediata de actualización vía HTTP.
        /// 
        /// Este método se mantiene EXCLUSIVAMENTE como fallback para comandos remotos
        /// "check_update" que no incluyen download_url (clientes/servidores antiguos durante transición).
        /// 
        /// En operación normal, las actualizaciones de MSI llegan vía WebSocket push
        /// (MSI_Push_Message con presigned URL) y se descargan directamente desde S3.
        /// 
        /// Flujo: leer flag local → llamar API /updates/check → comparar versiones → disparar evento.
        /// </summary>
        [Obsolete("Fallback legacy para comandos remotos sin download_url. " +
                   "En operación normal, usar push-based distribution vía PushMessageHandler.")]
        public async Task CheckNowAsync()
        {
            try
            {
                // 1. Leer flag local de auto-actualización
                bool autoUpdateEnabled = _registry.LoadAutoUpdateEnabled();
                if (!autoUpdateEnabled)
                {
                    // Flag local deshabilitado: no hacer nada (silencioso)
                    return;
                }

                AlwaysPrintLogger.WriteTrayInfo(
                    $"UpdateChecker: iniciando verificación de actualización. Versión actual: {_currentVersion}");

                // 2. Llamar al endpoint de verificación del Cloud Backend
                string url = $"{_cloudApiUrl.TrimEnd('/')}/api/v1/updates/check";

                var request = new HttpRequestMessage(HttpMethod.Get, url);
                // Autenticación de workstation (se envía la versión actual como header informativo)
                request.Headers.Add("X-Client-Version", _currentVersion);
                // Headers de identificación para diagnóstico de IPs pendientes
                request.Headers.Add("X-Workstation-Hostname", Environment.MachineName);
                request.Headers.Add("X-Workstation-User", Environment.UserName);
                request.Headers.Add("X-Workstation-IP-Private", NetworkHelper.GetOutboundLocalIP());

                var response = await _httpClient.SendAsync(request);

                if (!response.IsSuccessStatusCode)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"UpdateChecker: backend retornó código {(int)response.StatusCode} en verificación de actualización. " +
                        $"Reintentando en próximo ciclo.");
                    return;
                }

                string json = await response.Content.ReadAsStringAsync();
                var updateResponse = JsonConvert.DeserializeObject<UpdateCheckApiResponse>(json);

                if (updateResponse == null)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "UpdateChecker: respuesta de actualización con formato inválido. Reintentando en próximo ciclo.");
                    return;
                }

                // 3. Verificar flag de organización
                if (!updateResponse.AutoUpdateEnabled)
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        "UpdateChecker: actualizaciones automáticas deshabilitadas para la organización. " +
                        "No se procede con la descarga.");
                    return;
                }

                // 4. Comparar versiones
                if (string.Equals(_currentVersion, updateResponse.Version, StringComparison.OrdinalIgnoreCase))
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"UpdateChecker: sin actualización disponible. Versión instalada ({_currentVersion}) " +
                        $"es igual a la versión disponible.");
                    return;
                }

                // 5. Versión diferente: disparar evento UpdateAvailable
                AlwaysPrintLogger.WriteTrayInfo(
                    $"UpdateChecker: actualización disponible. Versión actual: {_currentVersion}, " +
                    $"versión disponible: {updateResponse.Version}, tamaño: {updateResponse.FileSize} bytes.");

                var updateInfo = new UpdateInfo
                {
                    Version = updateResponse.Version,
                    FileSize = updateResponse.FileSize,
                    OrganizationAutoUpdateEnabled = updateResponse.AutoUpdateEnabled
                };

                UpdateAvailable?.Invoke(updateInfo);
            }
            catch (HttpRequestException ex)
            {
                // Backend inalcanzable (timeout, DNS, red, etc.)
                AlwaysPrintLogger.WriteTrayWarning(
                    $"UpdateChecker: verificación de actualización fallida: {ex.Message}. Reintentando en 24h.");
            }
            catch (TaskCanceledException ex)
            {
                // Timeout del HttpClient
                AlwaysPrintLogger.WriteTrayWarning(
                    $"UpdateChecker: verificación de actualización excedió timeout: {ex.Message}. Reintentando en 24h.");
            }
            catch (JsonException ex)
            {
                // JSON malformado en la respuesta
                AlwaysPrintLogger.WriteTrayWarning(
                    $"UpdateChecker: respuesta de actualización con formato inválido: {ex.Message}. Reintentando en 24h.");
            }
            catch (Exception ex)
            {
                // Error inesperado: loggear sin interrumpir operación
                AlwaysPrintLogger.WriteTrayError(
                    $"UpdateChecker: error inesperado durante verificación de actualización: {ex.Message}",
                    AlwaysPrintLogger.EvtGenericError);
            }
        }

        /// <summary>
        /// [DEPRECADO] Callback del timer periódico (anteriormente cada 24h).
        /// El timer ya no se activa — este callback no debería ejecutarse nunca.
        /// Se mantiene por si el timer queda activo por un defecto.
        /// </summary>
        [Obsolete("Timer periódico deshabilitado. Este callback no debería ejecutarse.")]
        private async void OnTimerElapsed(object? state)
        {
            try
            {
                await CheckNowAsync();
            }
            catch (Exception ex)
            {
                // Protección adicional: nunca dejar que una excepción escape del callback del timer
                AlwaysPrintLogger.WriteTrayError(
                    $"UpdateChecker: error en callback del timer de verificación. {ex.Message}",
                    AlwaysPrintLogger.EvtGenericError);
            }
        }

        /// <summary>
        /// Libera los recursos del timer y el HttpClient.
        /// </summary>
        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;

            _timer.Change(Timeout.Infinite, Timeout.Infinite);
            _timer.Dispose();
            _httpClient.Dispose();

            AlwaysPrintLogger.WriteTrayInfo("UpdateChecker: recursos liberados (Dispose).");
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    // CLASES DE DATOS
    // ═══════════════════════════════════════════════════════════════════════

    /// <summary>
    /// Información de una actualización disponible. Se pasa a los suscriptores del evento UpdateAvailable.
    /// </summary>
    public class UpdateInfo
    {
        /// <summary>Versión disponible en el servidor.</summary>
        public string Version { get; set; } = string.Empty;

        /// <summary>Tamaño del archivo MSI en bytes.</summary>
        public long FileSize { get; set; }

        /// <summary>Indica si la organización tiene habilitadas las actualizaciones automáticas.</summary>
        public bool OrganizationAutoUpdateEnabled { get; set; }
    }

    /// <summary>
    /// Modelo de deserialización para la respuesta del endpoint /api/v1/updates/check.
    /// </summary>
    internal class UpdateCheckApiResponse
    {
        [JsonProperty("version")]
        public string Version { get; set; } = string.Empty;

        [JsonProperty("auto_update_enabled")]
        public bool AutoUpdateEnabled { get; set; }

        [JsonProperty("file_size")]
        public long FileSize { get; set; }

        [JsonProperty("build_date")]
        public string BuildDate { get; set; } = string.Empty;

        [JsonProperty("commit_hash")]
        public string CommitHash { get; set; } = string.Empty;
    }
}
