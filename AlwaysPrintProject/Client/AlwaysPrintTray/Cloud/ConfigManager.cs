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
        // VERIFICACIÓN Y DESCARGA
        // ═══════════════════════════════════════════════════════════════════════
        
        /// <summary>
        /// Verifica si hay una configuración activa en la Cloud y la descarga si es necesaria.
        /// Retorna true si la configuración local está actualizada.
        /// </summary>
        public async Task<bool> CheckAndDownloadConfigAsync(string cloudApiUrl, string workstationId, string apiKey)
        {
            try
            {
                AlwaysPrintLogger.WriteInfo("ConfigManager: verificando configuración en Cloud");
                
                // 1. Consultar si hay configuración activa en la Cloud
                var cloudConfigInfo = await GetCloudConfigInfoAsync(cloudApiUrl, workstationId, apiKey);
                
                if (cloudConfigInfo == null)
                {
                    AlwaysPrintLogger.WriteInfo("ConfigManager: no hay configuración activa en Cloud");
                    
                    // Si no hay config en Cloud pero existe local, eliminarla vía Service
                    if (File.Exists(_configFilePath))
                    {
                        AlwaysPrintLogger.WriteInfo("ConfigManager: eliminando configuración local obsoleta vía Service");
                        SendSaveActionConfigToService("", "");
                    }
                    
                    return true;
                }
                
                // 2. Verificar si la configuración local está actualizada
                string? localHash = GetLocalConfigHash();
                
                if (localHash != null && localHash.Equals(cloudConfigInfo.Hash, StringComparison.OrdinalIgnoreCase))
                {
                    AlwaysPrintLogger.WriteInfo($"ConfigManager: configuración local actualizada (hash: {localHash})");
                    return true;
                }
                
                // 3. Descargar nueva configuración
                AlwaysPrintLogger.WriteInfo($"ConfigManager: descargando nueva configuración (hash: {cloudConfigInfo.Hash})");
                
                bool downloaded = await DownloadConfigAsync(cloudApiUrl, workstationId, apiKey, cloudConfigInfo.DownloadUrl, cloudConfigInfo.Hash, cloudConfigInfo.CertVersion, cloudConfigInfo.CertUrl);
                
                if (downloaded)
                {
                    AlwaysPrintLogger.WriteInfo("ConfigManager: configuración descargada y guardada exitosamente");
                    return true;
                }
                else
                {
                    AlwaysPrintLogger.WriteError("ConfigManager: error descargando/guardando configuración");
                    return false;
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"ConfigManager: error verificando configuración: {ex.Message}", ex);
                return false;
            }
        }
        
        // ═══════════════════════════════════════════════════════════════════════
        // CONSULTA DE INFORMACIÓN
        // ═══════════════════════════════════════════════════════════════════════
        
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
                    AlwaysPrintLogger.WriteInfo($"ConfigManager: endpoint retornó 404. Detalle: {detail}");
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
                AlwaysPrintLogger.WriteWarning($"ConfigManager: error consultando info de configuración: {ex.Message}");
                return null;
            }
        }
        
        // ═══════════════════════════════════════════════════════════════════════
        // DESCARGA
        // ═══════════════════════════════════════════════════════════════════════
        
        private async Task<bool> DownloadConfigAsync(string cloudApiUrl, string workstationId, string apiKey, string downloadUrl, string expectedHash)
        {
            return await DownloadConfigAsync(cloudApiUrl, workstationId, apiKey, downloadUrl, expectedHash, null, null);
        }

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
                string configJson;
                bool isSigned = false;
                
                try
                {
                    var parsed = JObject.Parse(downloadedContent);
                    if (parsed["config"] != null && parsed["hash"] != null && 
                        parsed["signature"] != null && parsed["cert_version"] != null)
                    {
                        isSigned = true;
                        
                        // Es un JSON firmado — verificar firma ECDSA
                        int envelopeCertVersion = parsed["cert_version"]!.Value<int>();
                        int localCertVersion = SignatureVerifier.GetLocalCertVersion();
                        
                        string certPath = Path.Combine(
                            Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
                            "AlwaysPrint", "config", "org.cer");
                        
                        // Si cert_version remoto > local, intentar descargar nuevo certificado
                        if (envelopeCertVersion > localCertVersion)
                        {
                            AlwaysPrintLogger.WriteWarning(
                                $"ConfigManager: cert_version remoto ({envelopeCertVersion}) > local ({localCertVersion}). " +
                                "Intentando actualizar certificado.");
                            
                            if (!string.IsNullOrEmpty(certUrl))
                            {
                                bool certDownloaded = await SignatureVerifier.DownloadCertAsync(certUrl, certPath);
                                if (certDownloaded)
                                {
                                    SignatureVerifier.SetLocalCertVersion(envelopeCertVersion);
                                    AlwaysPrintLogger.WriteInfo(
                                        $"ConfigManager: certificado actualizado a versión {envelopeCertVersion}");
                                }
                                else
                                {
                                    AlwaysPrintLogger.WriteWarning(
                                        "ConfigManager: no se pudo descargar el nuevo certificado. " +
                                        "Se intentará verificar con el certificado actual.");
                                }
                            }
                            else
                            {
                                AlwaysPrintLogger.WriteWarning(
                                    "ConfigManager: cert_url no disponible para actualizar certificado. " +
                                    "Se intentará verificar con el certificado actual (puede fallar). " +
                                    "Se actualizará con el próximo cert_rotated.");
                            }
                        }
                        
                        // Verificar firma usando SignatureVerifier
                        if (!SignatureVerifier.VerifyConfig(downloadedContent, certPath, out string verifiedConfig))
                        {
                            AlwaysPrintLogger.WriteError(
                                "ConfigManager: verificación de firma ECDSA fallida — rechazando configuración.");
                            return false;
                        }
                        
                        // Firma válida — usar el config extraído
                        configJson = verifiedConfig;
                        AlwaysPrintLogger.WriteInfo("ConfigManager: firma ECDSA verificada exitosamente");
                    }
                    else
                    {
                        // No es un envelope firmado — config sin firmar (legacy / org sin certificado)
                        configJson = downloadedContent;
                    }
                }
                catch (Newtonsoft.Json.JsonException)
                {
                    // No es JSON válido como envelope — tratar como config raw
                    configJson = downloadedContent;
                }
                
                // Verificar hash del config extraído (8 primeros chars del SHA256)
                string downloadedHash = CalculateHash(configJson);
                
                if (!downloadedHash.Equals(expectedHash, StringComparison.OrdinalIgnoreCase))
                {
                    AlwaysPrintLogger.WriteError(
                        $"ConfigManager: hash no coincide. Esperado: {expectedHash}, Obtenido: {downloadedHash}");
                    return false;
                }
                
                AlwaysPrintLogger.WriteInfo($"ConfigManager: hash verificado correctamente{(isSigned ? " (firmado)" : "")}");
                
                // Enviar contenido al Service para que lo persista en disco
                bool saved = SendSaveActionConfigToService(configJson, downloadedHash);
                
                if (!saved)
                {
                    AlwaysPrintLogger.WriteError("ConfigManager: el Service no pudo guardar la configuración");
                    return false;
                }
                
                AlwaysPrintLogger.WriteInfo($"ConfigManager: configuración guardada por el Service en {_configFilePath}");
                return true;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"ConfigManager: error descargando configuración: {ex.Message}", ex);
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
                    AlwaysPrintLogger.WriteWarning(
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
                    AlwaysPrintLogger.WriteError("ConfigManager: no se recibió respuesta del Service (timeout o desconexión)");
                    return false;
                }
                
                if (response.Type == MessageType.Error)
                {
                    var error = response.GetPayload<ErrorPayload>();
                    AlwaysPrintLogger.WriteError(
                        $"ConfigManager: Service retornó error al guardar config: [{error?.Code}] {error?.Message}");
                    return false;
                }
                
                var ack = response.GetPayload<AckPayload>();
                if (ack?.Success == true)
                {
                    AlwaysPrintLogger.WriteInfo($"ConfigManager: Service confirmó escritura exitosa. {ack.Message}");
                    return true;
                }
                else
                {
                    AlwaysPrintLogger.WriteWarning(
                        $"ConfigManager: Service reportó fallo al guardar: {ack?.Message}");
                    return false;
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"ConfigManager: error enviando config al Service: {ex.Message}", ex);
                return false;
            }
        }
        
        // ═══════════════════════════════════════════════════════════════════════
        // HASH Y VERIFICACIÓN
        // ═══════════════════════════════════════════════════════════════════════
        
        /// <summary>
        /// Calcula el hash SHA256 del archivo de configuración local.
        /// Retorna los primeros 8 caracteres del hash en hexadecimal.
        /// </summary>
        private string? GetLocalConfigHash()
        {
            try
            {
                if (!File.Exists(_configFilePath))
                    return null;
                
                string content = File.ReadAllText(_configFilePath, Encoding.UTF8);
                return CalculateHash(content);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteWarning($"ConfigManager: error calculando hash local: {ex.Message}");
                return null;
            }
        }
        
        /// <summary>
        /// Calcula el hash SHA256 de un string y retorna los primeros 8 caracteres.
        /// </summary>
        public static string CalculateHash(string content)
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
        /// </summary>
        public LocalConfigInfo? GetLocalConfigInfo()
        {
            try
            {
                if (!File.Exists(_configFilePath))
                    return null;
                
                string json = File.ReadAllText(_configFilePath, Encoding.UTF8);
                var config = JObject.Parse(json);
                
                return new LocalConfigInfo
                {
                    Hash = GetLocalConfigHash() ?? "",
                    Name = config["name"]?.ToString() ?? "",
                    Version = config["version"]?.ToString() ?? "",
                    FilePath = _configFilePath
                };
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteWarning($"ConfigManager: error obteniendo info local: {ex.Message}");
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
                AlwaysPrintLogger.WriteInfo("ConfigManager: descargando recursos de VLAN");

                string url = $"{cloudApiUrl.TrimEnd('/')}/api/v1/workstations/{workstationId}/resources";

                var request = new HttpRequestMessage(HttpMethod.Get, url);
                request.Headers.Add("X-API-Key", apiKey);

                var response = await _httpClient.SendAsync(request);

                if (response.StatusCode == System.Net.HttpStatusCode.NotFound)
                {
                    AlwaysPrintLogger.WriteInfo("ConfigManager: endpoint /resources retornó 404 (workstation sin VLAN)");
                    return true;
                }

                if (response.StatusCode == System.Net.HttpStatusCode.Forbidden)
                {
                    AlwaysPrintLogger.WriteWarning("ConfigManager: sin permisos para obtener recursos");
                    return false;
                }

                response.EnsureSuccessStatusCode();

                string resourcesJson = await response.Content.ReadAsStringAsync();

                // Enviar al Service para que lo persista en disco
                bool saved = SendSaveResourcesToService(resourcesJson);

                if (saved)
                    AlwaysPrintLogger.WriteInfo("ConfigManager: recursos guardados exitosamente en resources.json");
                else
                    AlwaysPrintLogger.WriteWarning("ConfigManager: no se pudieron guardar los recursos");

                return saved;
            }
            catch (HttpRequestException ex)
            {
                AlwaysPrintLogger.WriteWarning($"ConfigManager: error descargando recursos: {ex.Message}");
                return false;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"ConfigManager: error inesperado descargando recursos: {ex.Message}", ex);
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
                    AlwaysPrintLogger.WriteWarning("ConfigManager: pipe no conectado, no se pueden guardar recursos");
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
                AlwaysPrintLogger.WriteError($"ConfigManager: error enviando recursos al Service: {ex.Message}", ex);
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
