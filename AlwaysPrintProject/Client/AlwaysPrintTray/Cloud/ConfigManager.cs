using System;
using System.IO;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Messages;
using AlwaysPrint.Shared.Security;
using AlwaysPrintTray.Pipe;
using Newtonsoft.Json.Linq;

namespace AlwaysPrintTray.Cloud
{
    /// <summary>
    /// Gestiona la descarga y verificación de archivos de configuración de acciones
    /// desde el servidor Cloud.
    /// La escritura del archivo se delega al Service vía Named Pipe (el Tray no tiene
    /// permisos de escritura en ProgramData).
    /// </summary>
    public class ConfigManager
    {
        private readonly HttpClient _httpClient;
        private readonly PipeClient _pipeClient;
        private readonly string _configFilePath;

        /// <summary>
        /// Hash SHA256 del certificado esperado (recibido del servidor via enrichment TLS).
        /// Se usa para validar que el org.cer en disco no fue manipulado antes de verificar firma.
        /// Se actualiza cada vez que llega un enrichment con cert_hash.
        /// </summary>
        private static volatile string? _expectedCertHash;

        /// <summary>
        /// Actualiza el cert_hash esperado del servidor.
        /// Llamado desde CloudManager al recibir el enrichment.
        /// Si el cert local no coincide con el hash del servidor, lo invalida inmediatamente
        /// y fuerza re-descarga en el siguiente sync (CertVersion=0).
        /// </summary>
        public static void SetExpectedCertHash(string? certHash)
        {
            _expectedCertHash = certHash;

            // Validación inmediata: si tenemos hash del servidor, verificar cert local ahora
            if (!string.IsNullOrEmpty(certHash))
            {
                string certPath = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
                    "AlwaysPrint", "config", "org.cer");

                if (!ValidateCertIntegrity(certPath))
                {
                    // Cert en disco no matchea con lo que el servidor dice — invalidar
                    AlwaysPrintLogger.WriteTrayWarning(
                        "ConfigManager: cert_hash del servidor no coincide con cert local. " +
                        "Invalidando cert para forzar re-descarga.");
                    InvalidateLocalCert();
                }
            }
        }
        
        /// <summary>Timeout en milisegundos para esperar respuesta del Service al guardar config.</summary>
        private const int SaveConfigTimeoutMs = 10_000;
        
        public ConfigManager(HttpClient httpClient, PipeClient pipeClient)
        {
            _httpClient = httpClient;
            _pipeClient = pipeClient;
            
            // Ruta donde el Service guarda la configuración activa.
            // El Tray solo lee desde aquí; la escritura la hace el Service (LocalSystem).
            _configFilePath = PipeConstants.ActionConfigFilePath;
        }
        
        // ═══════════════════════════════════════════════════════════════════════
        // VALIDACIÓN DE INTEGRIDAD DEL CERTIFICADO
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Valida que el certificado en disco no fue manipulado comparando su SHA256
        /// contra el hash recibido del servidor (via enrichment TLS, confiable).
        /// Retorna true si el cert es válido o si no hay hash de referencia disponible.
        /// Retorna false si el hash no coincide (cert fue manipulado).
        /// </summary>
        private static bool ValidateCertIntegrity(string certPath)
        {
            // Si no tenemos hash de referencia del servidor, no podemos validar
            // (backward-compatible con orgs que no tienen cert_hash calculado)
            if (string.IsNullOrEmpty(_expectedCertHash))
                return true;

            if (!File.Exists(certPath))
                return true; // Archivo no existe, se descargará después

            try
            {
                byte[] certBytes = File.ReadAllBytes(certPath);
                string localHash;
                using (var sha256 = System.Security.Cryptography.SHA256.Create())
                {
                    byte[] hashBytes = sha256.ComputeHash(certBytes);
                    localHash = BitConverter.ToString(hashBytes).Replace("-", "").ToLowerInvariant();
                }

                if (localHash.Equals(_expectedCertHash, StringComparison.OrdinalIgnoreCase))
                {
                    return true;
                }

                AlwaysPrintLogger.WriteTrayError(
                    $"ConfigManager: ALERTA DE SEGURIDAD — certificado local manipulado. " +
                    $"Hash local: {localHash.Substring(0, 16)}..., " +
                    $"Hash esperado (servidor): {_expectedCertHash.Substring(0, 16)}...");

                return false;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"ConfigManager: error validando integridad del certificado: {ex.Message}");
                return true; // En caso de error de I/O, no bloquear (fail-open para validación)
            }
        }

        // ═══════════════════════════════════════════════════════════════════════
        // INVALIDACIÓN DE CERTIFICADO
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Invalida el certificado local cuando la verificación de firma falla.
        /// Elimina el archivo .cer de disco y resetea CertVersion a 0 en registro.
        /// En el siguiente ciclo de sync, se forzará la re-descarga del cert correcto.
        /// 
        /// Escenarios donde esto aplica:
        /// - Workstation movida de un entorno a otro (DEV→PROD) con cert viejo
        /// - Atacante reemplazó el .cer local con un certificado falso
        /// - Rotación de clave de firma sin actualización del cert
        /// </summary>
        private static void InvalidateLocalCert()
        {
            try
            {
                string certPath = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
                    "AlwaysPrint", "config", "org.cer");

                if (File.Exists(certPath))
                {
                    File.Delete(certPath);
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"ConfigManager: certificado local eliminado ({certPath}) por fallo de verificación de firma.");
                }

                // Eliminar también active.alwaysconfig: fue firmada con el cert que acabamos
                // de invalidar, por lo tanto no es confiable. El Service la recargará vacía
                // y descargará fresh del entorno correcto.
                string configPath = PipeConstants.ActionConfigFilePath;
                if (File.Exists(configPath))
                {
                    File.Delete(configPath);
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"ConfigManager: configuración activa eliminada ({configPath}) porque fue firmada con cert invalidado.");
                }

                // Resetear CertVersion a 0 para forzar re-descarga en el próximo sync
                SignatureVerifier.SetLocalCertVersion(0);

                AlwaysPrintLogger.WriteTrayWarning(
                    "ConfigManager: CertVersion reseteado a 0. Se forzará re-descarga del certificado en el próximo ciclo.");
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"ConfigManager: error invalidando certificado local: {ex.Message}");
            }
        }

        // ═══════════════════════════════════════════════════════════════════════
        // VERIFICACIÓN Y DESCARGA (LEGACY — DEPRECADO)
        // ═══════════════════════════════════════════════════════════════════════
        
        /// <summary>
        /// [DEPRECADO] Verifica si hay una configuración activa en la Cloud y la descarga si es necesaria.
        /// Retorna true si la configuración local está actualizada.
        /// 
        /// Este método usaba polling HTTP a /workstations/{id}/config/info y /config/download.
        /// Ahora la distribución es 100% push-based: los cambios llegan vía WebSocket
        /// (Config_Push_Message) y se descargan directamente desde S3 a través de
        /// DownloadAndApplyFromUrlAsync o ApplyDownloadedConfigAsync.
        /// 
        /// Se mantiene como fallback para el período de transición.
        /// </summary>
        [Obsolete("Usar flujo push-based: DownloadAndApplyFromUrlAsync o ApplyDownloadedConfigAsync. " +
                   "Este método será eliminado cuando se complete la migración a push-based distribution.")]
        public async Task<bool> CheckAndDownloadConfigAsync(string cloudApiUrl, string workstationId, string apiKey)
        {
            try
            {
                AlwaysPrintLogger.WriteTrayInfo("ConfigManager: verificando configuración en Cloud");
                
                // 1. Consultar si hay configuración activa en la Cloud
                var cloudConfigInfo = await GetCloudConfigInfoAsync(cloudApiUrl, workstationId, apiKey);
                
                if (cloudConfigInfo == null)
                {
                    AlwaysPrintLogger.WriteTrayInfo("ConfigManager: no hay configuración activa en Cloud");
                    
                    // Si no hay config en Cloud pero existe local, eliminarla vía Service
                    if (File.Exists(_configFilePath))
                    {
                        AlwaysPrintLogger.WriteTrayInfo("ConfigManager: eliminando configuración local obsoleta vía Service");
                        SendSaveActionConfigToService("", "");
                    }
                    
                    return true;
                }
                
                // 2. Verificar si la configuración local está actualizada
                string? localHash = GetLocalConfigHash();
                
                if (localHash != null && localHash.Equals(cloudConfigInfo.Hash, StringComparison.OrdinalIgnoreCase))
                {
                    AlwaysPrintLogger.WriteTrayInfo($"ConfigManager: configuración local actualizada (hash: {localHash})");
                    return true;
                }
                
                // 3. Descargar nueva configuración
                AlwaysPrintLogger.WriteTrayInfo($"ConfigManager: descargando nueva configuración (hash: {cloudConfigInfo.Hash})");
                
                bool downloaded = await DownloadConfigAsync(cloudApiUrl, workstationId, apiKey, cloudConfigInfo.DownloadUrl, cloudConfigInfo.Hash, cloudConfigInfo.CertVersion, cloudConfigInfo.CertUrl);
                
                if (downloaded)
                {
                    AlwaysPrintLogger.WriteTrayInfo("ConfigManager: configuración descargada y guardada exitosamente");
                    return true;
                }
                else
                {
                    AlwaysPrintLogger.WriteTrayError("ConfigManager: error descargando/guardando configuración");
                    return false;
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError($"ConfigManager: error verificando configuración: {ex.Message}", ex);
                return false;
            }
        }
        
        // ═══════════════════════════════════════════════════════════════════════
        // CONSULTA DE INFORMACIÓN (LEGACY — DEPRECADO)
        // ═══════════════════════════════════════════════════════════════════════
        
        /// <summary>
        /// [DEPRECADO] Consulta /workstations/{id}/config/info vía HTTP.
        /// Reemplazado por estado recibido vía Registration_Enrichment y push messages.
        /// Se mantiene como fallback para el período de transición.
        /// </summary>
        [Obsolete("Usar estado del Registration_Enrichment o push messages vía PushMessageHandler.")]
        private async Task<CloudConfigInfo?> GetCloudConfigInfoAsync(string cloudApiUrl, string workstationId, string apiKey)
        {
            try
            {
                string url = $"{cloudApiUrl.TrimEnd('/')}/api/v1/workstations/{workstationId}/config/info";
                
                var request = new HttpRequestMessage(HttpMethod.Get, url);
                request.Headers.Add("X-API-Key", apiKey);
                
                var response = await _httpClient.SendAsync(request);
                
                if (response.StatusCode == System.Net.HttpStatusCode.NotFound)
                {
                    // Leer detalle del 404 para diagnóstico
                    string detail = "";
                    try { detail = await response.Content.ReadAsStringAsync(); } catch { }
                    AlwaysPrintLogger.WriteTrayInfo($"ConfigManager: endpoint retornó 404. Detalle: {detail}");
                    return null;
                }
                
                response.EnsureSuccessStatusCode();
                
                string json = await response.Content.ReadAsStringAsync();
                var data = JObject.Parse(json);
                
                return new CloudConfigInfo
                {
                    Hash = data["hash"]?.ToString() ?? "",
                    DownloadUrl = data["download_url"]?.ToString() ?? "",
                    Name = data["name"]?.ToString() ?? "",
                    Version = data["version"]?.ToString() ?? "",
                    CertVersion = data["cert_version"]?.ToObject<int?>(),
                    CertUrl = data["cert_url"]?.ToString()
                };
            }
            catch (HttpRequestException ex)
            {
                AlwaysPrintLogger.WriteTrayWarning($"ConfigManager: error consultando info de configuración: {ex.Message}");
                return null;
            }
        }
        
        // ═══════════════════════════════════════════════════════════════════════
        // DESCARGA VÍA HTTP (LEGACY — DEPRECADO)
        // ═══════════════════════════════════════════════════════════════════════
        
        /// <summary>
        /// [DEPRECADO] Descarga configuración vía HTTP desde /workstations/{id}/config/download.
        /// Reemplazado por DownloadAndApplyFromUrlAsync que descarga directamente desde S3.
        /// Se mantiene como fallback para el período de transición.
        /// </summary>
        [Obsolete("Usar DownloadAndApplyFromUrlAsync para descarga directa desde S3.")]
        private async Task<bool> DownloadConfigAsync(string cloudApiUrl, string workstationId, string apiKey, string downloadUrl, string expectedHash, int? remoteCertVersion, string? certUrl)
        {
            try
            {
                string url = $"{cloudApiUrl.TrimEnd('/')}{downloadUrl}";
                
                var request = new HttpRequestMessage(HttpMethod.Get, url);
                request.Headers.Add("X-API-Key", apiKey);
                
                var response = await _httpClient.SendAsync(request);
                response.EnsureSuccessStatusCode();
                
                string downloadedContent = await response.Content.ReadAsStringAsync();
                
                // Determinar si es un JSON firmado (signed envelope) o config raw (legacy)
                
                try
                {
                    var parsed = JObject.Parse(downloadedContent);
                    if (parsed["config"] != null && parsed["hash"] != null && 
                        parsed["signature"] != null && parsed["cert_version"] != null)
                    {
                        
                        // Es un JSON firmado — verificar firma ECDSA
                        int envelopeCertVersion = parsed["cert_version"]!.Value<int>();
                        int localCertVersion = SignatureVerifier.GetLocalCertVersion(traySource: true);
                        
                        string certPath = Path.Combine(
                            Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
                            "AlwaysPrint", "config", "org.cer");
                        
                        // Descargar certificado si: versión remota > local, O si el archivo no existe en disco
                        bool certFileExists = File.Exists(certPath);
                        if (envelopeCertVersion > localCertVersion || !certFileExists)
                        {
                            if (!certFileExists)
                            {
                                AlwaysPrintLogger.WriteTrayWarning(
                                    $"ConfigManager: certificado no encontrado en disco ({certPath}). Descargando...");
                            }
                            else
                            {
                                AlwaysPrintLogger.WriteTrayWarning(
                                    $"ConfigManager: cert_version remoto ({envelopeCertVersion}) > local ({localCertVersion}). " +
                                    "Intentando actualizar certificado.");
                            }
                            
                            if (!string.IsNullOrEmpty(certUrl))
                            {
                                bool certDownloaded = await SignatureVerifier.DownloadCertAsync(certUrl, certPath, traySource: true);
                                if (certDownloaded)
                                {
                                    AlwaysPrintLogger.WriteTrayInfo(
                                        $"ConfigManager: certificado actualizado a versión {envelopeCertVersion}");
                                }
                                else
                                {
                                    AlwaysPrintLogger.WriteTrayWarning(
                                        "ConfigManager: no se pudo descargar el nuevo certificado. " +
                                        "Se intentará verificar con el certificado actual.");
                                }
                            }
                            else
                            {
                                AlwaysPrintLogger.WriteTrayWarning(
                                    "ConfigManager: cert_url no disponible para actualizar certificado. " +
                                    "Se intentará verificar con el certificado actual (puede fallar). " +
                                    "Se actualizará con el próximo cert_rotated.");
                            }
                        }
                        
                        // Verificar integridad del cert antes de usarlo para verificar firma
                        if (!ValidateCertIntegrity(certPath))
                        {
                            AlwaysPrintLogger.WriteTrayError(
                                "ConfigManager: certificado local no pasó validación de integridad. Invalidando y rechazando config.");
                            InvalidateLocalCert();
                            return false;
                        }

                        // Verificar firma usando SignatureVerifier (fail-fast antes de persistir)
                        if (!SignatureVerifier.VerifyConfig(downloadedContent, certPath, out string verifiedConfig, traySource: true))
                        {
                            AlwaysPrintLogger.WriteTrayError(
                                "ConfigManager: verificación de firma ECDSA fallida — rechazando configuración.");
                            InvalidateLocalCert();
                            return false;
                        }
                        
                        AlwaysPrintLogger.WriteTrayInfo("ConfigManager: firma ECDSA verificada exitosamente");
                        
                        // La firma ECDSA ya garantiza autenticidad e integridad del config.
                        // Loguear hash del envelope como referencia (no se usa para bloquear).
                        AlwaysPrintLogger.WriteTrayInfo(
                            $"ConfigManager: config autenticada por firma ECDSA. Hash del envelope: {parsed["hash"]!.ToString().Substring(0, 8)}");
                        
                        // Enviar envelope COMPLETO al Service para persistencia
                        // El Service verificará la firma al cargar desde disco
                        bool saved = SendSaveActionConfigToService(downloadedContent, expectedHash);
                        
                        if (!saved)
                        {
                            AlwaysPrintLogger.WriteTrayError("ConfigManager: el Service no pudo guardar la configuración");
                            return false;
                        }
                        
                        AlwaysPrintLogger.WriteTrayInfo($"ConfigManager: configuración firmada guardada por el Service en {_configFilePath}");
                        return true;
                    }
                    else
                    {
                        // Formato legacy sin firma — NO guardar, rechazar
                        AlwaysPrintLogger.WriteTrayError(
                            "ConfigManager: configuración recibida sin firma digital. Rechazando (formato legacy no aceptado).");
                        return false;
                    }
                }
                catch (Newtonsoft.Json.JsonException)
                {
                    // No es JSON válido — rechazar
                    AlwaysPrintLogger.WriteTrayError(
                        "ConfigManager: contenido descargado no es JSON válido. Rechazando.");
                    return false;
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError($"ConfigManager: error descargando configuración: {ex.Message}", ex);
                return false;
            }
        }
        
        // ═══════════════════════════════════════════════════════════════════════
        // COMUNICACIÓN CON EL SERVICE VÍA NAMED PIPE
        // ═══════════════════════════════════════════════════════════════════════
        
        /// <summary>
        /// Envía el contenido de la configuración al Service para que lo persista en disco.
        /// El Service escribe atómicamente (tmp + rename) y luego recarga la configuración.
        /// </summary>
        /// <param name="configJson">Contenido JSON de la configuración. Vacío para eliminar.</param>
        /// <param name="hash">Hash SHA256 (8 chars) para verificación de integridad.</param>
        /// <returns>true si el Service confirmó la escritura exitosa.</returns>
        private bool SendSaveActionConfigToService(string configJson, string hash)
        {
            try
            {
                if (!_pipeClient.IsConnected)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "ConfigManager: pipe no conectado, no se puede enviar configuración al Service");
                    return false;
                }
                
                var payload = new SaveActionConfigPayload
                {
                    ConfigJson = configJson,
                    Hash = hash
                };
                
                var message = PipeMessage.Create(MessageType.SaveActionConfig, payload);
                var response = _pipeClient.Send(message);
                
                if (response == null)
                {
                    AlwaysPrintLogger.WriteTrayError("ConfigManager: no se recibió respuesta del Service (timeout o desconexión)");
                    return false;
                }
                
                if (response.Type == MessageType.Error)
                {
                    var error = response.GetPayload<ErrorPayload>();
                    AlwaysPrintLogger.WriteTrayError(
                        $"ConfigManager: Service retornó error al guardar config: [{error?.Code}] {error?.Message}");
                    return false;
                }
                
                var ack = response.GetPayload<AckPayload>();
                if (ack?.Success == true)
                {
                    AlwaysPrintLogger.WriteTrayInfo($"ConfigManager: Service confirmó escritura exitosa. {ack.Message}");
                    return true;
                }
                else
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"ConfigManager: Service reportó fallo al guardar: {ack?.Message}");
                    return false;
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError($"ConfigManager: error enviando config al Service: {ex.Message}", ex);
                return false;
            }
        }
        
        // ═══════════════════════════════════════════════════════════════════════
        // DESCARGA DIRECTA DESDE S3 (PUSH-BASED)
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Descarga contenido directamente desde una URL de S3 provista por push message
        /// o Registration_Enrichment. Este método es la interfaz de bajo nivel para
        /// obtener archivos desde S3 sin pasar por el backend.
        /// 
        /// Nota: Este método solo descarga el contenido. Para configuraciones firmadas,
        /// usar DownloadAndApplyFromUrlAsync que incluye verificación ECDSA y persistencia.
        /// </summary>
        /// <param name="s3Url">URL pública o presigned de S3 del recurso a descargar.</param>
        /// <returns>Contenido descargado como string, o null si la descarga falla.</returns>
        public async Task<string> DownloadFromS3(string s3Url)
        {
            try
            {
                if (string.IsNullOrEmpty(s3Url))
                {
                    AlwaysPrintLogger.WriteTrayError(
                        "ConfigManager: URL de S3 vacía o nula. No se puede descargar.");
                    return null;
                }

                AlwaysPrintLogger.WriteTrayInfo(
                    $"ConfigManager: descargando recurso desde S3. URL={s3Url.Substring(0, Math.Min(80, s3Url.Length))}...");

                var response = await _httpClient.GetAsync(s3Url);
                response.EnsureSuccessStatusCode();

                string content = await response.Content.ReadAsStringAsync();

                if (string.IsNullOrEmpty(content))
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "ConfigManager: contenido descargado desde S3 está vacío.");
                    return null;
                }

                AlwaysPrintLogger.WriteTrayInfo(
                    $"ConfigManager: recurso descargado exitosamente desde S3. " +
                    $"Tamaño={content.Length} bytes");
                return content;
            }
            catch (HttpRequestException ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"ConfigManager: error HTTP descargando desde S3: {ex.Message}", ex);
                return null;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"ConfigManager: error inesperado descargando desde S3: {ex.Message}", ex);
                return null;
            }
        }

        /// <summary>
        /// Descarga un archivo de configuración firmado directamente desde una URL de S3,
        /// verifica la firma ECDSA y lo persiste vía el Service.
        /// Este método es invocado por PushMessageHandler al recibir un Config_Push_Message
        /// con hash diferente al local.
        /// </summary>
        /// <param name="downloadUrl">URL pública de S3 del archivo firmado (.signed).</param>
        /// <param name="expectedHash">Hash SHA256 corto (8 chars) esperado de la configuración.</param>
        /// <returns>true si descarga, verificación y persistencia fueron exitosas.</returns>
        public async Task<bool> DownloadAndApplyFromUrlAsync(string downloadUrl, string expectedHash)
        {
            try
            {
                AlwaysPrintLogger.WriteTrayInfo(
                    $"ConfigManager: descargando configuración desde S3. hash_esperado={expectedHash}");

                // 1. Descargar contenido directamente desde la URL de S3
                var response = await _httpClient.GetAsync(downloadUrl);
                response.EnsureSuccessStatusCode();

                string downloadedContent = await response.Content.ReadAsStringAsync();

                if (string.IsNullOrEmpty(downloadedContent))
                {
                    AlwaysPrintLogger.WriteTrayError(
                        "ConfigManager: contenido descargado desde S3 está vacío. Rechazando.");
                    return false;
                }

                // 2. Validar que es un envelope firmado con estructura correcta
                JObject parsed;
                try
                {
                    parsed = JObject.Parse(downloadedContent);
                }
                catch (Newtonsoft.Json.JsonException)
                {
                    AlwaysPrintLogger.WriteTrayError(
                        "ConfigManager: contenido descargado desde S3 no es JSON válido. Rechazando.");
                    return false;
                }

                if (parsed["config"] == null || parsed["hash"] == null ||
                    parsed["signature"] == null || parsed["cert_version"] == null)
                {
                    AlwaysPrintLogger.WriteTrayError(
                        "ConfigManager: configuración descargada no tiene firma digital. " +
                        "Rechazando (formato legacy no aceptado).");
                    return false;
                }

                // 3. Verificar y actualizar certificado si es necesario
                int envelopeCertVersion = parsed["cert_version"]!.Value<int>();
                int localCertVersion = SignatureVerifier.GetLocalCertVersion(traySource: true);

                string certPath = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
                    "AlwaysPrint", "config", "org.cer");

                bool certFileExists = File.Exists(certPath);
                if (envelopeCertVersion > localCertVersion || !certFileExists)
                {
                    if (!certFileExists)
                    {
                        AlwaysPrintLogger.WriteTrayWarning(
                            $"ConfigManager: certificado no encontrado en disco ({certPath}). " +
                            "No se puede verificar firma sin certificado.");
                    }
                    else
                    {
                        AlwaysPrintLogger.WriteTrayWarning(
                            $"ConfigManager: cert_version del envelope ({envelopeCertVersion}) > local ({localCertVersion}). " +
                            "Se intentará verificar con el certificado actual.");
                    }

                    // Nota: la descarga del certificado actualizado se gestiona por Cert_Push_Message
                    // separado. Aquí intentamos verificar con lo que tenemos disponible.
                }

                // 4. Validar integridad del cert y verificar firma ECDSA — FAIL-CLOSED
                if (!ValidateCertIntegrity(certPath))
                {
                    AlwaysPrintLogger.WriteTrayError(
                        "ConfigManager: certificado local no pasó validación de integridad (S3 download). Invalidando.");
                    InvalidateLocalCert();
                    return false;
                }

                if (!SignatureVerifier.VerifyConfig(downloadedContent, certPath, out string verifiedConfig, traySource: true))
                {
                    AlwaysPrintLogger.WriteTrayError(
                        "ConfigManager: verificación de firma ECDSA fallida para config descargada desde S3. " +
                        "Rechazando configuración (fail-closed).");
                    InvalidateLocalCert();
                    return false;
                }

                AlwaysPrintLogger.WriteTrayInfo(
                    "ConfigManager: firma ECDSA verificada exitosamente para config de S3");

                // 5. Persistir vía Service (Named Pipe)
                bool saved = SendSaveActionConfigToService(downloadedContent, expectedHash);

                if (!saved)
                {
                    AlwaysPrintLogger.WriteTrayError(
                        "ConfigManager: el Service no pudo guardar la configuración descargada desde S3");
                    return false;
                }

                AlwaysPrintLogger.WriteTrayInfo(
                    $"ConfigManager: configuración de S3 aplicada exitosamente. hash={expectedHash}");
                return true;
            }
            catch (HttpRequestException ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"ConfigManager: error HTTP descargando config desde S3: {ex.Message}", ex);
                return false;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"ConfigManager: error inesperado en DownloadAndApplyFromUrlAsync: {ex.Message}", ex);
                return false;
            }
        }

        /// <summary>
        /// Verifica la firma ECDSA y persiste contenido de configuración ya descargado.
        /// Este método es invocado por PushMessageHandler después de descargar exitosamente
        /// con retry. Separa la lógica de verificación/persistencia de la descarga HTTP
        /// para permitir que el retry se aplique solo a la parte de red.
        /// </summary>
        /// <param name="downloadedContent">Contenido JSON del envelope firmado descargado desde S3.</param>
        /// <param name="expectedHash">Hash SHA256 corto (8 chars) esperado de la configuración.</param>
        /// <returns>true si verificación y persistencia fueron exitosas.</returns>
        public Task<bool> ApplyDownloadedConfigAsync(string downloadedContent, string expectedHash)
        {
            try
            {
                if (string.IsNullOrEmpty(downloadedContent))
                {
                    AlwaysPrintLogger.WriteTrayError(
                        "ConfigManager: contenido de configuración vacío. Rechazando.");
                    return Task.FromResult(false);
                }

                // 1. Validar que es un envelope firmado con estructura correcta
                JObject parsed;
                try
                {
                    parsed = JObject.Parse(downloadedContent);
                }
                catch (Newtonsoft.Json.JsonException)
                {
                    AlwaysPrintLogger.WriteTrayError(
                        "ConfigManager: contenido descargado no es JSON válido. Rechazando.");
                    return Task.FromResult(false);
                }

                if (parsed["config"] == null || parsed["hash"] == null ||
                    parsed["signature"] == null || parsed["cert_version"] == null)
                {
                    AlwaysPrintLogger.WriteTrayError(
                        "ConfigManager: configuración sin firma digital. " +
                        "Rechazando (formato legacy no aceptado).");
                    return Task.FromResult(false);
                }

                // 2. Verificar y actualizar certificado si es necesario
                int envelopeCertVersion = parsed["cert_version"]!.Value<int>();
                int localCertVersion = SignatureVerifier.GetLocalCertVersion(traySource: true);

                string certPath = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
                    "AlwaysPrint", "config", "org.cer");

                bool certFileExists = File.Exists(certPath);
                if (envelopeCertVersion > localCertVersion || !certFileExists)
                {
                    if (!certFileExists)
                    {
                        AlwaysPrintLogger.WriteTrayWarning(
                            $"ConfigManager: certificado no encontrado en disco ({certPath}). " +
                            "No se puede verificar firma sin certificado.");
                    }
                    else
                    {
                        AlwaysPrintLogger.WriteTrayWarning(
                            $"ConfigManager: cert_version del envelope ({envelopeCertVersion}) > local ({localCertVersion}). " +
                            "Se intentará verificar con el certificado actual.");
                    }

                    // Nota: la descarga del certificado actualizado se gestiona por Cert_Push_Message
                    // separado. Aquí intentamos verificar con lo que tenemos disponible.
                }

                // 3. Validar integridad del cert y verificar firma ECDSA — FAIL-CLOSED
                if (!ValidateCertIntegrity(certPath))
                {
                    AlwaysPrintLogger.WriteTrayError(
                        "ConfigManager: certificado local no pasó validación de integridad (apply). Invalidando.");
                    InvalidateLocalCert();
                    return Task.FromResult(false);
                }

                if (!SignatureVerifier.VerifyConfig(downloadedContent, certPath, out string verifiedConfig, traySource: true))
                {
                    AlwaysPrintLogger.WriteTrayError(
                        "ConfigManager: verificación de firma ECDSA fallida. " +
                        "Rechazando configuración (fail-closed).");
                    InvalidateLocalCert();
                    return Task.FromResult(false);
                }

                AlwaysPrintLogger.WriteTrayInfo(
                    "ConfigManager: firma ECDSA verificada exitosamente");

                // 4. Persistir vía Service (Named Pipe)
                bool saved = SendSaveActionConfigToService(downloadedContent, expectedHash);

                if (!saved)
                {
                    AlwaysPrintLogger.WriteTrayError(
                        "ConfigManager: el Service no pudo guardar la configuración");
                    return Task.FromResult(false);
                }

                AlwaysPrintLogger.WriteTrayInfo(
                    $"ConfigManager: configuración aplicada exitosamente. hash={expectedHash}");
                return Task.FromResult(true);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"ConfigManager: error en ApplyDownloadedConfigAsync: {ex.Message}", ex);
                return Task.FromResult(false);
            }
        }

        // ═══════════════════════════════════════════════════════════════════════
        // HASH Y VERIFICACIÓN
        // ═══════════════════════════════════════════════════════════════════════
        
        /// <summary>
        /// Obtiene el hash de la configuración local activa.
        /// Si el archivo es un envelope firmado, extrae el campo "hash" (primeros 8 chars).
        /// Retorna null si no hay archivo de configuración local.
        /// </summary>
        public string GetLocalConfigHash()
        {
            try
            {
                if (!File.Exists(_configFilePath))
                    return null;
                
                string content = File.ReadAllText(_configFilePath, Encoding.UTF8);
                
                // Si es un envelope firmado, extraer hash del campo "hash"
                try
                {
                    var parsed = JObject.Parse(content);
                    if (parsed["config"] != null && parsed["hash"] != null)
                    {
                        // Es envelope — el hash está en el campo "hash" (64 chars), tomar primeros 8
                        string fullHash = parsed["hash"]!.ToString();
                        return fullHash.Substring(0, Math.Min(8, fullHash.Length));
                    }
                }
                catch (Newtonsoft.Json.JsonException) { }
                
                // Fallback: hashear contenido completo (no debería llegar aquí con el nuevo formato)
                return CalculateHash(content);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning($"ConfigManager: error calculando hash local: {ex.Message}");
                return null;
            }
        }
        
        /// <summary>
        /// Calcula el hash SHA256 de un string y retorna los primeros 8 caracteres.
        /// </summary>
        private static string CalculateHash(string content)
        {
            using (var sha256 = SHA256.Create())
            {
                byte[] bytes = Encoding.UTF8.GetBytes(content);
                byte[] hash = sha256.ComputeHash(bytes);
                
                // Convertir a hexadecimal y tomar primeros 8 caracteres
                string fullHash = BitConverter.ToString(hash).Replace("-", "").ToLowerInvariant();
                return fullHash.Substring(0, 8);
            }
        }
        
        // ═══════════════════════════════════════════════════════════════════════
        // INFORMACIÓN
        // ═══════════════════════════════════════════════════════════════════════
        
        /// <summary>
        /// Obtiene información sobre la configuración local activa.
        /// Si el archivo es un envelope firmado, lee name/version del config interno.
        /// </summary>
        public LocalConfigInfo? GetLocalConfigInfo()
        {
            try
            {
                if (!File.Exists(_configFilePath))
                    return null;
                
                string json = File.ReadAllText(_configFilePath, Encoding.UTF8);
                var obj = JObject.Parse(json);
                
                // Si es envelope firmado, leer del config interno
                JToken configToken = obj["config"] ?? obj;
                
                return new LocalConfigInfo
                {
                    Hash = GetLocalConfigHash() ?? "",
                    Name = configToken["name"]?.ToString() ?? "",
                    Version = configToken["version"]?.ToString() ?? "",
                    FilePath = _configFilePath
                };
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning($"ConfigManager: error obteniendo info local: {ex.Message}");
                return null;
            }
        }

        // ═══════════════════════════════════════════════════════════════════════
        // DESCARGA DE RECURSOS DE VLAN
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Descarga los recursos de la VLAN (metadata, impresoras de contingencia)
        /// desde el endpoint /workstations/{id}/resources y los guarda en resources.json
        /// vía el Service. Los valores de metadata se inyectan como variables del ActionEngine.
        /// </summary>
        public async Task<bool> DownloadResourcesAsync(string cloudApiUrl, string workstationId, string apiKey)
        {
            try
            {
                AlwaysPrintLogger.WriteTrayInfo("ConfigManager: descargando recursos de VLAN");

                string url = $"{cloudApiUrl.TrimEnd('/')}/api/v1/workstations/{workstationId}/resources";

                var request = new HttpRequestMessage(HttpMethod.Get, url);
                request.Headers.Add("X-API-Key", apiKey);

                var response = await _httpClient.SendAsync(request);

                if (response.StatusCode == System.Net.HttpStatusCode.NotFound)
                {
                    AlwaysPrintLogger.WriteTrayInfo("ConfigManager: endpoint /resources retornó 404 (workstation sin VLAN)");
                    return true;
                }

                if (response.StatusCode == System.Net.HttpStatusCode.Forbidden)
                {
                    AlwaysPrintLogger.WriteTrayWarning("ConfigManager: sin permisos para obtener recursos");
                    return false;
                }

                response.EnsureSuccessStatusCode();

                string resourcesJson = await response.Content.ReadAsStringAsync();

                // Enviar al Service para que lo persista en disco
                bool saved = SendSaveResourcesToService(resourcesJson);

                if (saved)
                    AlwaysPrintLogger.WriteTrayInfo("ConfigManager: recursos guardados exitosamente en resources.json");
                else
                    AlwaysPrintLogger.WriteTrayWarning("ConfigManager: no se pudieron guardar los recursos");

                return saved;
            }
            catch (HttpRequestException ex)
            {
                AlwaysPrintLogger.WriteTrayWarning($"ConfigManager: error descargando recursos: {ex.Message}");
                return false;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError($"ConfigManager: error inesperado descargando recursos: {ex.Message}", ex);
                return false;
            }
        }

        /// <summary>
        /// Envía los recursos descargados al Service para que los persista en disco.
        /// </summary>
        private bool SendSaveResourcesToService(string resourcesJson)
        {
            try
            {
                if (!_pipeClient.IsConnected)
                {
                    AlwaysPrintLogger.WriteTrayWarning("ConfigManager: pipe no conectado, no se pueden guardar recursos");
                    return false;
                }

                var payload = new SaveResourcesPayload { ResourcesJson = resourcesJson };
                var message = PipeMessage.Create(MessageType.SaveResources, payload);
                var pipeResponse = _pipeClient.Send(message);

                if (pipeResponse == null)
                    return false;

                if (pipeResponse.Type == MessageType.Error)
                    return false;

                var ack = pipeResponse.GetPayload<AckPayload>();
                return ack?.Success == true;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError($"ConfigManager: error enviando recursos al Service: {ex.Message}", ex);
                return false;
            }
        }
    }
    
    // ═══════════════════════════════════════════════════════════════════════
    // CLASES DE DATOS
    // ═══════════════════════════════════════════════════════════════════════
    
    public class CloudConfigInfo
    {
        public string Hash { get; set; } = "";
        public string DownloadUrl { get; set; } = "";
        public string Name { get; set; } = "";
        public string Version { get; set; } = "";
        public int? CertVersion { get; set; }
        public string? CertUrl { get; set; }
    }
    
    public class LocalConfigInfo
    {
        public string Hash { get; set; } = "";
        public string Name { get; set; } = "";
        public string Version { get; set; } = "";
        public string FilePath { get; set; } = "";
    }
}
