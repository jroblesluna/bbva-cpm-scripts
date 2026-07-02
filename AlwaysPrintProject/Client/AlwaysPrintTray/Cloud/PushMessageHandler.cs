using System;
using System.IO;
using System.Net.Http;
using System.Threading.Tasks;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Messages;
using AlwaysPrint.Shared.Security;
using AlwaysPrintTray.Pipe;
using Newtonsoft.Json.Linq;

namespace AlwaysPrintTray.Cloud
{
    /// <summary>
    /// Procesa mensajes push recibidos vía WebSocket y mantiene
    /// un caché del último estado de distribución conocido.
    /// Thread-safe: múltiples mensajes WebSocket pueden llegar concurrentemente.
    /// </summary>
    public class PushMessageHandler
    {
        /// <summary>Último estado de distribución conocido (push o registration enrichment).</summary>
        private DistributionState _lastKnownState;

        /// <summary>Lock para acceso thread-safe al estado cacheado.</summary>
        private readonly object _stateLock = new object();

        /// <summary>ConfigManager para descarga y verificación de configuraciones desde S3.</summary>
        private readonly ConfigManager _configManager;

        /// <summary>UpdateDownloader para descarga de MSI desde presigned URL o fallback.</summary>
        private readonly UpdateDownloader _updateDownloader;

        /// <summary>PipeClient para enviar solicitud de instalación de MSI al Service.</summary>
        private readonly PipeClient _pipeClient;

        /// <summary>URL base de la API Cloud para fallback HTTP del MSI.</summary>
        private readonly string _cloudApiUrl;

        /// <summary>HttpClient compartido para descargas directas desde S3 con retry.</summary>
        private readonly HttpClient _httpClient;

        /// <summary>
        /// Delays de backoff exponencial en milisegundos entre reintentos.
        /// Tras fallo 1: esperar 1s, tras fallo 2: esperar 2s, tras fallo 3: esperar 4s.
        /// </summary>
        private static readonly int[] RetryDelaysMs = { 1000, 2000, 4000 };

        /// <summary>Número máximo de intentos para descargas S3 (config y cert).</summary>
        private const int MaxDownloadAttempts = 3;

        /// <summary>
        /// Crea una nueva instancia de PushMessageHandler.
        /// </summary>
        /// <param name="configManager">ConfigManager para descarga directa desde S3 y verificación ECDSA.</param>
        /// <param name="updateDownloader">UpdateDownloader para descarga de MSI.</param>
        /// <param name="pipeClient">PipeClient para comunicación con el Service.</param>
        /// <param name="cloudApiUrl">URL base de la API Cloud para fallback HTTP.</param>
        /// <param name="httpClient">HttpClient compartido para descargas S3 con retry.</param>
        public PushMessageHandler(ConfigManager configManager, UpdateDownloader updateDownloader, PipeClient pipeClient, string cloudApiUrl, HttpClient httpClient)
        {
            _configManager = configManager ?? throw new ArgumentNullException(nameof(configManager));
            _updateDownloader = updateDownloader ?? throw new ArgumentNullException(nameof(updateDownloader));
            _pipeClient = pipeClient ?? throw new ArgumentNullException(nameof(pipeClient));
            _cloudApiUrl = cloudApiUrl ?? throw new ArgumentNullException(nameof(cloudApiUrl));
            _httpClient = httpClient ?? throw new ArgumentNullException(nameof(httpClient));
        }

        /// <summary>
        /// Retorna el último estado de distribución conocido.
        /// Puede ser null si no se ha recibido aún ningún estado del servidor.
        /// </summary>
        public DistributionState GetCachedState()
        {
            lock (_stateLock)
            {
                return _lastKnownState;
            }
        }

        /// <summary>
        /// Actualiza el estado cacheado con datos del registro enriquecido o un push message.
        /// Se usa tanto al procesar Registration_Enrichment como al recibir push messages individuales.
        /// </summary>
        /// <param name="newState">Nuevo estado de distribución a cachear.</param>
        public void UpdateState(DistributionState newState)
        {
            if (newState == null)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    "PushMessageHandler: intento de actualizar estado con valor nulo. Ignorando.");
                return;
            }

            lock (_stateLock)
            {
                _lastKnownState = newState;
            }

            AlwaysPrintLogger.WriteTrayInfo(
                $"PushMessageHandler: estado de distribución actualizado. " +
                $"ConfigHash={newState.ConfigHash ?? "null"}, CertVersion={newState.CertVersion}, " +
                $"MsiVersion={newState.MsiVersion ?? "null"}, LastUpdated={newState.LastUpdated:u}");
        }

        /// <summary>
        /// Procesa un mensaje push genérico recibido vía WebSocket.
        /// Determina el tipo de mensaje y delega al handler correspondiente,
        /// actualizando el estado cacheado con los campos relevantes.
        /// </summary>
        /// <param name="messageType">Tipo del mensaje WebSocket (action_config_changed, check_update, cert_rotated).</param>
        /// <param name="messageJson">JSON completo del mensaje recibido.</param>
        public async Task HandlePushMessage(string messageType, string messageJson)
        {
            try
            {
                AlwaysPrintLogger.WriteTrayInfo(
                    $"PushMessageHandler: procesando mensaje push tipo='{messageType}'.");

                switch (messageType)
                {
                    case "action_config_changed":
                        await HandleConfigPush(messageJson);
                        break;

                    case "check_update":
                        HandleMsiPush(messageJson);
                        break;

                    case "cert_rotated":
                        await HandleCertPush(messageJson);
                        break;

                    default:
                        AlwaysPrintLogger.WriteTrayInfo(
                            $"PushMessageHandler: tipo de mensaje '{messageType}' no reconocido como push de distribución.");
                        break;
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"PushMessageHandler: error procesando mensaje push tipo='{messageType}': {ex.Message}");
            }
        }

        // ═══════════════════════════════════════════════════════════════════════
        // RETRY CON BACKOFF EXPONENCIAL PARA DESCARGAS S3
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Descarga contenido desde una URL con retry y backoff exponencial.
        /// Reintentos: hasta maxAttempts intentos con delays [1s, 2s, 4s].
        /// No reintenta en errores 4xx (errores de cliente) excepto 429 (rate limit).
        /// Si todos los intentos fallan, retorna null.
        /// </summary>
        /// <param name="url">URL de descarga (S3 público o presigned).</param>
        /// <param name="maxAttempts">Número máximo de intentos (default: 3).</param>
        /// <returns>Contenido descargado como string, o null si todos los intentos fallaron.</returns>
        public async Task<string> DownloadWithRetryAsync(string url, int maxAttempts = MaxDownloadAttempts)
        {
            if (string.IsNullOrEmpty(url))
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    "PushMessageHandler: DownloadWithRetry invocado con URL vacía.");
                return null;
            }

            // Limitar intentos al máximo configurado
            if (maxAttempts > MaxDownloadAttempts)
                maxAttempts = MaxDownloadAttempts;

            for (int attempt = 1; attempt <= maxAttempts; attempt++)
            {
                try
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"PushMessageHandler: descarga S3, intento {attempt}/{maxAttempts}. URL={TruncateUrl(url)}");

                    var response = await _httpClient.GetAsync(url);

                    // Verificar si es error de cliente (4xx) — no reintentar excepto 429
                    int statusCode = (int)response.StatusCode;
                    if (statusCode >= 400 && statusCode < 500 && statusCode != 429)
                    {
                        AlwaysPrintLogger.WriteTrayError(
                            $"PushMessageHandler: error de cliente HTTP {statusCode} en descarga S3. " +
                            "No se reintentará (error del lado del cliente).");
                        return null;
                    }

                    // Si es error de servidor (5xx) o rate limit (429), reintentar
                    if (!response.IsSuccessStatusCode)
                    {
                        AlwaysPrintLogger.WriteTrayWarning(
                            $"PushMessageHandler: HTTP {statusCode} en intento {attempt}/{maxAttempts}. " +
                            (attempt < maxAttempts ? $"Reintentando en {RetryDelaysMs[attempt - 1]}ms..." : "Sin más reintentos."));

                        if (attempt < maxAttempts)
                        {
                            await Task.Delay(RetryDelaysMs[attempt - 1]);
                        }
                        continue;
                    }

                    // Éxito — retornar contenido
                    string content = await response.Content.ReadAsStringAsync();
                    
                    if (attempt > 1)
                    {
                        AlwaysPrintLogger.WriteTrayInfo(
                            $"PushMessageHandler: descarga exitosa en intento {attempt}/{maxAttempts}.");
                    }

                    return content;
                }
                catch (TaskCanceledException)
                {
                    // Timeout del HttpClient
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"PushMessageHandler: timeout en intento {attempt}/{maxAttempts} descargando desde S3. " +
                        (attempt < maxAttempts ? $"Reintentando en {RetryDelaysMs[attempt - 1]}ms..." : "Sin más reintentos."));

                    if (attempt < maxAttempts)
                    {
                        await Task.Delay(RetryDelaysMs[attempt - 1]);
                    }
                }
                catch (HttpRequestException ex)
                {
                    // Error de red (DNS, conexión rechazada, etc.)
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"PushMessageHandler: error de red en intento {attempt}/{maxAttempts}: {ex.Message}. " +
                        (attempt < maxAttempts ? $"Reintentando en {RetryDelaysMs[attempt - 1]}ms..." : "Sin más reintentos."));

                    if (attempt < maxAttempts)
                    {
                        await Task.Delay(RetryDelaysMs[attempt - 1]);
                    }
                }
                catch (Exception ex)
                {
                    // Error inesperado — loguear y reintentar
                    AlwaysPrintLogger.WriteTrayError(
                        $"PushMessageHandler: error inesperado en intento {attempt}/{maxAttempts}: {ex.Message}. " +
                        (attempt < maxAttempts ? $"Reintentando en {RetryDelaysMs[attempt - 1]}ms..." : "Sin más reintentos."));

                    if (attempt < maxAttempts)
                    {
                        await Task.Delay(RetryDelaysMs[attempt - 1]);
                    }
                }
            }

            // Todos los intentos fallaron
            AlwaysPrintLogger.WriteTrayError(
                $"PushMessageHandler: todos los {maxAttempts} intentos de descarga fallaron. " +
                "Se esperará próximo push o reconexión para reintentar.");
            return null;
        }

        // ═══════════════════════════════════════════════════════════════════════
        // VERIFICACIÓN MANUAL (SYNC DESDE ESTADO CACHEADO O HTTP FALLBACK)
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Compara el estado de distribución proporcionado contra el estado local
        /// y descarga desde S3 los recursos que difieran.
        /// Usado por la verificación manual ("Buscar actualizaciones") del Tray.
        /// Retorna el número de recursos que se actualizaron exitosamente.
        /// </summary>
        /// <param name="state">Estado de distribución a comparar (del caché o del HTTP fallback).</param>
        /// <returns>Número de componentes actualizados (0 = todo al día).</returns>
        public async Task<int> SyncFromStateAsync(DistributionState state)
        {
            if (state == null)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    "PushMessageHandler: SyncFromStateAsync invocado con estado nulo.");
                return 0;
            }

            int updatedCount = 0;

            // 1. Comparar certificado ECDSA (cert_version) — PRIMERO para que la config pueda verificar firma
            if (state.CertVersion > 0 && !string.IsNullOrEmpty(state.CertUrl))
            {
                int localCertVersion = SignatureVerifier.GetLocalCertVersion(traySource: true);
                string certPath = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
                    "AlwaysPrint", "config", "org.cer");
                bool certFileExists = File.Exists(certPath);

                // Descargar si: versión remota > local, O archivo no existe en disco
                if (state.CertVersion > localCertVersion || !certFileExists)
                {
                    string reason = !certFileExists
                        ? "archivo no existe en disco"
                        : $"versión remota ({state.CertVersion}) > local ({localCertVersion})";
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"PushMessageHandler: SyncFromState — cert requiere descarga ({reason}).");

                    bool downloaded = await DownloadCertWithRetryAsync(state.CertUrl, certPath);
                    if (downloaded)
                    {
                        updatedCount++;
                        AlwaysPrintLogger.WriteTrayInfo(
                            $"PushMessageHandler: SyncFromState — certificado actualizado a v{state.CertVersion}.");
                    }
                }
                else
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"PushMessageHandler: SyncFromState — cert_version al día (local={localCertVersion}, remoto={state.CertVersion}).");
                }
            }

            // 2. Comparar configuración de acciones (config_hash) — DESPUÉS del cert para poder verificar firma
            if (!string.IsNullOrEmpty(state.ConfigHash) && !string.IsNullOrEmpty(state.ConfigS3Url))
            {
                string localHash = _configManager.GetLocalConfigHash();
                if (string.IsNullOrEmpty(localHash) ||
                    !localHash.Equals(state.ConfigHash, StringComparison.OrdinalIgnoreCase))
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"PushMessageHandler: SyncFromState — config_hash difiere " +
                        $"(local={localHash ?? "null"}, remoto={state.ConfigHash}). Descargando...");

                    string content = await DownloadWithRetryAsync(state.ConfigS3Url);
                    if (content != null)
                    {
                        bool applied = await _configManager.ApplyDownloadedConfigAsync(content, state.ConfigHash);
                        if (applied)
                        {
                            updatedCount++;
                            AlwaysPrintLogger.WriteTrayInfo(
                                $"PushMessageHandler: SyncFromState — configuración actualizada. hash={state.ConfigHash}");
                        }
                    }
                }
                else
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"PushMessageHandler: SyncFromState — config_hash coincide ({state.ConfigHash}). Sin cambios.");
                }
            }

            // 3. Comparar versión de MSI (msi_version)
            if (!string.IsNullOrEmpty(state.MsiVersion))
            {
                string currentVersion = System.Reflection.Assembly.GetExecutingAssembly()
                    .GetName().Version?.ToString() ?? "0.0.0.0";

                if (!currentVersion.Equals(state.MsiVersion, StringComparison.OrdinalIgnoreCase))
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"PushMessageHandler: SyncFromState — msi_version difiere " +
                        $"(local={currentVersion}, remoto={state.MsiVersion}). Iniciando descarga.");

                    // Disparar descarga si hay URL disponible
                    if (!string.IsNullOrEmpty(state.MsiUrl))
                    {
                        _ = Task.Run(async () =>
                        {
                            try
                            {
                                string? msiPath = await _updateDownloader.DownloadFromUrlAsync(
                                    state.MsiUrl, 0, state.MsiVersion);

                                if (msiPath != null)
                                {
                                    // Solicitar instalación al Service vía Named Pipe
                                    var installMsg = PipeMessage.Create(MessageType.InstallUpdate,
                                        new InstallUpdatePayload { MsiFilePath = msiPath });
                                    _pipeClient.Send(installMsg);

                                    AlwaysPrintLogger.WriteTrayInfo(
                                        $"PushMessageHandler: MSI descargado y enviado a instalar. " +
                                        $"Versión: {state.MsiVersion}, path: {msiPath}");
                                }
                                else
                                {
                                    AlwaysPrintLogger.WriteTrayWarning(
                                        $"PushMessageHandler: descarga de MSI fallida. " +
                                        $"Versión: {state.MsiVersion}");
                                }
                            }
                            catch (Exception ex)
                            {
                                AlwaysPrintLogger.WriteTrayError(
                                    $"PushMessageHandler: error descargando/instalando MSI: {ex.Message}");
                            }
                        });
                    }
                    else
                    {
                        AlwaysPrintLogger.WriteTrayWarning(
                            $"PushMessageHandler: SyncFromState — msi_version difiere pero no hay URL de descarga.");
                    }

                    updatedCount++;
                }
                else
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"PushMessageHandler: SyncFromState — msi_version al día ({currentVersion}).");
                }
            }

            return updatedCount;
        }

        // ═══════════════════════════════════════════════════════════════════════
        // HANDLERS DE MENSAJES PUSH
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Procesa un Config_Push_Message: compara el config_hash recibido contra el hash local.
        /// Si difiere, descarga el archivo firmado desde S3 con retry y lo aplica con verificación ECDSA.
        /// Si coincide, ignora el mensaje sin descargar.
        /// </summary>
        private async Task HandleConfigPush(string json)
        {
            try
            {
                var data = JObject.Parse(json);
                string configHash = data["config_hash"]?.ToString();
                string downloadUrl = data["download_url"]?.ToString();

                if (string.IsNullOrEmpty(configHash))
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "PushMessageHandler: mensaje action_config_changed sin config_hash. Ignorando.");
                    return;
                }

                // Actualizar campos de config en el estado cacheado
                lock (_stateLock)
                {
                    if (_lastKnownState == null)
                    {
                        _lastKnownState = new DistributionState();
                    }

                    _lastKnownState.ConfigHash = configHash;
                    _lastKnownState.ConfigS3Url = downloadUrl;
                    _lastKnownState.LastUpdated = DateTime.UtcNow;
                }

                // Comparar hash recibido vs hash local
                string localHash = _configManager.GetLocalConfigHash();

                if (!string.IsNullOrEmpty(localHash) &&
                    localHash.Equals(configHash, StringComparison.OrdinalIgnoreCase))
                {
                    // Hash coincide — no es necesario descargar
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"PushMessageHandler: config_hash recibido ({configHash}) coincide con el local. " +
                        "No se requiere descarga.");
                    return;
                }

                // Hash difiere — descargar desde S3 con retry
                if (string.IsNullOrEmpty(downloadUrl))
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"PushMessageHandler: config_hash difiere (local={localHash ?? "null"}, " +
                        $"remoto={configHash}) pero download_url es nulo. No se puede descargar.");
                    return;
                }

                AlwaysPrintLogger.WriteTrayInfo(
                    $"PushMessageHandler: config_hash difiere (local={localHash ?? "null"}, " +
                    $"remoto={configHash}). Descargando desde S3 con retry...");

                // Descargar contenido con retry y backoff exponencial
                string downloadedContent = await DownloadWithRetryAsync(downloadUrl);

                if (downloadedContent == null)
                {
                    // Todos los intentos fallaron — esperar próximo push
                    AlwaysPrintLogger.WriteTrayError(
                        $"PushMessageHandler: no se pudo descargar configuración tras {MaxDownloadAttempts} intentos. " +
                        $"hash_esperado={configHash}. Se esperará próximo push o reconexión.");
                    return;
                }

                // Delegar verificación ECDSA y persistencia al ConfigManager
                bool success = await _configManager.ApplyDownloadedConfigAsync(downloadedContent, configHash);

                if (success)
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"PushMessageHandler: configuración actualizada exitosamente vía push. hash={configHash}");
                }
                else
                {
                    AlwaysPrintLogger.WriteTrayError(
                        $"PushMessageHandler: falló la verificación/aplicación de configuración descargada. " +
                        $"hash_esperado={configHash}. Se esperará próximo push o reconexión.");
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"PushMessageHandler: error procesando Config_Push_Message: {ex.Message}");
            }
        }

        /// <summary>
        /// Procesa un MSI_Push_Message: actualiza el estado cacheado con la nueva versión y URL de descarga.
        /// Nota: MSI NO usa retry con backoff — tiene su propio fallback HTTP al backend.
        /// </summary>
        private void HandleMsiPush(string json)
        {
            try
            {
                var data = JObject.Parse(json);
                string version = data["version"]?.ToString();
                string downloadUrl = data["download_url"]?.ToString();

                if (string.IsNullOrEmpty(version))
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "PushMessageHandler: mensaje check_update sin version. Ignorando.");
                    return;
                }

                // Actualizar campos de MSI en el estado cacheado
                lock (_stateLock)
                {
                    if (_lastKnownState == null)
                    {
                        _lastKnownState = new DistributionState();
                    }

                    _lastKnownState.MsiVersion = version;
                    _lastKnownState.MsiUrl = downloadUrl;
                    _lastKnownState.LastUpdated = DateTime.UtcNow;
                }

                AlwaysPrintLogger.WriteTrayInfo(
                    $"PushMessageHandler: estado de MSI actualizado. version={version}, url={(downloadUrl != null ? "presente" : "null")}");
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"PushMessageHandler: error procesando MSI_Push_Message: {ex.Message}");
            }
        }

        /// <summary>
        /// Procesa un Cert_Push_Message: compara cert_version recibido contra el local.
        /// Si la versión remota es mayor, descarga el nuevo certificado desde S3 con retry.
        /// Si es igual o menor, ignora el mensaje.
        /// </summary>
        private async Task HandleCertPush(string json)
        {
            try
            {
                var data = JObject.Parse(json);
                int? certVersion = data["cert_version"]?.ToObject<int?>();
                string certUrl = data["cert_url"]?.ToString();

                if (!certVersion.HasValue)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "PushMessageHandler: mensaje cert_rotated sin cert_version. Ignorando.");
                    return;
                }

                // Actualizar campos de certificado en el estado cacheado
                lock (_stateLock)
                {
                    if (_lastKnownState == null)
                    {
                        _lastKnownState = new DistributionState();
                    }

                    _lastKnownState.CertVersion = certVersion.Value;
                    _lastKnownState.CertUrl = certUrl;
                    _lastKnownState.LastUpdated = DateTime.UtcNow;
                }

                // Comparar cert_version recibido vs local
                int localCertVersion = SignatureVerifier.GetLocalCertVersion(traySource: true);

                if (certVersion.Value <= localCertVersion)
                {
                    // Versión igual o menor — ignorar
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"PushMessageHandler: cert_version recibida ({certVersion.Value}) <= local ({localCertVersion}). " +
                        "No se requiere descarga.");
                    return;
                }

                // Versión mayor — descargar nuevo certificado con retry
                if (string.IsNullOrEmpty(certUrl))
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"PushMessageHandler: cert_version {certVersion.Value} > local ({localCertVersion}) " +
                        "pero cert_url es nulo. No se puede descargar.");
                    return;
                }

                AlwaysPrintLogger.WriteTrayInfo(
                    $"PushMessageHandler: cert_version {certVersion.Value} > local ({localCertVersion}). " +
                    "Descargando nuevo certificado desde S3 con retry...");

                // Descargar certificado con retry y backoff exponencial
                string certPath = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
                    "AlwaysPrint", "config", "org.cer");

                bool downloaded = await DownloadCertWithRetryAsync(certUrl, certPath);

                if (downloaded)
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"PushMessageHandler: certificado ECDSA actualizado exitosamente a versión {certVersion.Value}");
                }
                else
                {
                    AlwaysPrintLogger.WriteTrayError(
                        $"PushMessageHandler: no se pudo descargar certificado v{certVersion.Value} tras {MaxDownloadAttempts} intentos. " +
                        "Se esperará próximo push o reconexión para reintentar.");
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"PushMessageHandler: error procesando Cert_Push_Message: {ex.Message}");
            }
        }

        // ═══════════════════════════════════════════════════════════════════════
        // DESCARGA DE CERTIFICADO CON RETRY
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Descarga un certificado desde una URL de S3 con retry y backoff exponencial.
        /// Guarda el archivo .cer en la ruta local especificada.
        /// </summary>
        /// <param name="certUrl">URL pública del certificado en S3.</param>
        /// <param name="localPath">Ruta local donde guardar el certificado.</param>
        /// <returns>true si la descarga fue exitosa, false si todos los intentos fallaron.</returns>
        private async Task<bool> DownloadCertWithRetryAsync(string certUrl, string localPath)
        {
            for (int attempt = 1; attempt <= MaxDownloadAttempts; attempt++)
            {
                try
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"PushMessageHandler: descarga de certificado, intento {attempt}/{MaxDownloadAttempts}.");

                    var response = await _httpClient.GetAsync(certUrl);

                    // No reintentar en errores de cliente (4xx) excepto 429
                    int statusCode = (int)response.StatusCode;
                    if (statusCode >= 400 && statusCode < 500 && statusCode != 429)
                    {
                        AlwaysPrintLogger.WriteTrayError(
                            $"PushMessageHandler: error HTTP {statusCode} descargando certificado. " +
                            "No se reintentará.");
                        return false;
                    }

                    if (!response.IsSuccessStatusCode)
                    {
                        AlwaysPrintLogger.WriteTrayWarning(
                            $"PushMessageHandler: HTTP {statusCode} en intento {attempt}/{MaxDownloadAttempts} de cert. " +
                            (attempt < MaxDownloadAttempts ? $"Reintentando en {RetryDelaysMs[attempt - 1]}ms..." : "Sin más reintentos."));

                        if (attempt < MaxDownloadAttempts)
                        {
                            await Task.Delay(RetryDelaysMs[attempt - 1]);
                        }
                        continue;
                    }

                    // Éxito — guardar certificado en disco
                    byte[] certBytes = await response.Content.ReadAsByteArrayAsync();

                    if (certBytes == null || certBytes.Length == 0)
                    {
                        AlwaysPrintLogger.WriteTrayError(
                            "PushMessageHandler: certificado descargado está vacío. Rechazando.");
                        return false;
                    }

                    // Crear directorio si no existe
                    string directory = Path.GetDirectoryName(localPath);
                    if (!string.IsNullOrEmpty(directory) && !Directory.Exists(directory))
                    {
                        Directory.CreateDirectory(directory);
                    }

                    // Guardar certificado en disco
                    File.WriteAllBytes(localPath, certBytes);

                    AlwaysPrintLogger.WriteTrayInfo(
                        $"PushMessageHandler: certificado guardado exitosamente en {localPath} ({certBytes.Length} bytes)" +
                        (attempt > 1 ? $" (intento {attempt})" : ""));
                    return true;
                }
                catch (TaskCanceledException)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"PushMessageHandler: timeout en intento {attempt}/{MaxDownloadAttempts} descargando certificado. " +
                        (attempt < MaxDownloadAttempts ? $"Reintentando en {RetryDelaysMs[attempt - 1]}ms..." : "Sin más reintentos."));

                    if (attempt < MaxDownloadAttempts)
                    {
                        await Task.Delay(RetryDelaysMs[attempt - 1]);
                    }
                }
                catch (HttpRequestException ex)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"PushMessageHandler: error de red en intento {attempt}/{MaxDownloadAttempts} de cert: {ex.Message}. " +
                        (attempt < MaxDownloadAttempts ? $"Reintentando en {RetryDelaysMs[attempt - 1]}ms..." : "Sin más reintentos."));

                    if (attempt < MaxDownloadAttempts)
                    {
                        await Task.Delay(RetryDelaysMs[attempt - 1]);
                    }
                }
                catch (IOException ex)
                {
                    // Error de I/O al escribir — no reintentar (problema local, no de red)
                    AlwaysPrintLogger.WriteTrayError(
                        $"PushMessageHandler: error de I/O guardando certificado: {ex.Message}. No se reintentará.");
                    return false;
                }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteTrayError(
                        $"PushMessageHandler: error inesperado en intento {attempt}/{MaxDownloadAttempts} de cert: {ex.Message}. " +
                        (attempt < MaxDownloadAttempts ? $"Reintentando en {RetryDelaysMs[attempt - 1]}ms..." : "Sin más reintentos."));

                    if (attempt < MaxDownloadAttempts)
                    {
                        await Task.Delay(RetryDelaysMs[attempt - 1]);
                    }
                }
            }

            return false;
        }

        // ═══════════════════════════════════════════════════════════════════════
        // UTILIDADES
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Trunca una URL para logging (no exponer tokens de presigned URLs completas).
        /// </summary>
        private static string TruncateUrl(string url)
        {
            if (string.IsNullOrEmpty(url))
                return "(vacía)";

            // Si tiene query string (presigned URL), truncar después del path
            int queryIndex = url.IndexOf('?');
            if (queryIndex > 0 && queryIndex < url.Length - 1)
            {
                return url.Substring(0, queryIndex) + "?...";
            }

            // Si la URL es muy larga, truncar
            return url.Length > 100 ? url.Substring(0, 100) + "..." : url;
        }
    }
}
