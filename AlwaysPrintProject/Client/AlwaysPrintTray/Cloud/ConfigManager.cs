using System;
using System.IO;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Messages;
using AlwaysPrintTray.Pipe;
using Newtonsoft.Json.Linq;

namespace AlwaysPrintTray.Cloud
{
    /// <summary>
    /// Gestiona la descarga y verificación de archivos de configuración de acciones
    /// desde el servidor Cloud.
    /// </summary>
    public class ConfigManager
    {
        private readonly HttpClient _httpClient;
        private readonly PipeClient _pipeClient;
        private readonly string _configFilePath;
        
        public ConfigManager(HttpClient httpClient, PipeClient pipeClient)
        {
            _httpClient = httpClient;
            _pipeClient = pipeClient;
            
            // Ruta donde se guarda la configuración activa.
            // Se usa ProgramData porque el Tray corre como usuario normal y no puede
            // escribir en Program Files. El Service (LocalSystem) también puede leer desde aquí.
            string configDir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
                "Robles.AI", "AlwaysPrint");
            
            if (!Directory.Exists(configDir))
                Directory.CreateDirectory(configDir);
            
            _configFilePath = Path.Combine(configDir, "active.alwaysconfig");
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
                    
                    // Si no hay config en Cloud pero existe local, eliminarla
                    if (File.Exists(_configFilePath))
                    {
                        AlwaysPrintLogger.WriteInfo("ConfigManager: eliminando configuración local obsoleta");
                        File.Delete(_configFilePath);
                        NotifyServiceConfigChanged();
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
                
                bool downloaded = await DownloadConfigAsync(cloudApiUrl, workstationId, apiKey, cloudConfigInfo.DownloadUrl);
                
                if (downloaded)
                {
                    AlwaysPrintLogger.WriteInfo("ConfigManager: configuración descargada exitosamente");
                    
                    // Verificar hash del archivo descargado
                    string? downloadedHash = GetLocalConfigHash();
                    
                    if (downloadedHash != null && downloadedHash.Equals(cloudConfigInfo.Hash, StringComparison.OrdinalIgnoreCase))
                    {
                        AlwaysPrintLogger.WriteInfo("ConfigManager: hash verificado correctamente");
                        
                        // Notificar al Service que hay nueva configuración
                        NotifyServiceConfigChanged();
                        
                        return true;
                    }
                    else
                    {
                        AlwaysPrintLogger.WriteError($"ConfigManager: hash no coincide. Esperado: {cloudConfigInfo.Hash}, Obtenido: {downloadedHash}");
                        return false;
                    }
                }
                else
                {
                    AlwaysPrintLogger.WriteError("ConfigManager: error descargando configuración");
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
                    // No hay configuración activa
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
                    Version = data["version"]?.ToString() ?? ""
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
        
        private async Task<bool> DownloadConfigAsync(string cloudApiUrl, string workstationId, string apiKey, string downloadUrl)
        {
            try
            {
                string url = $"{cloudApiUrl.TrimEnd('/')}{downloadUrl}";
                
                var request = new HttpRequestMessage(HttpMethod.Get, url);
                request.Headers.Add("X-API-Key", apiKey);
                
                var response = await _httpClient.SendAsync(request);
                response.EnsureSuccessStatusCode();
                
                string configJson = await response.Content.ReadAsStringAsync();
                
                // Guardar en archivo temporal primero
                string tempPath = _configFilePath + ".tmp";
                File.WriteAllText(tempPath, configJson, Encoding.UTF8);
                
                // Reemplazar archivo activo
                if (File.Exists(_configFilePath))
                {
                    File.Delete(_configFilePath);
                }
                
                File.Move(tempPath, _configFilePath);
                
                AlwaysPrintLogger.WriteInfo($"ConfigManager: configuración guardada en {_configFilePath}");
                
                return true;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"ConfigManager: error descargando configuración: {ex.Message}", ex);
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
        // NOTIFICACIÓN AL SERVICE
        // ═══════════════════════════════════════════════════════════════════════
        
        /// <summary>
        /// Notifica al Service que hay una nueva configuración disponible.
        /// El Service debe recargar la configuración y ejecutar el trigger OnConfigChange.
        /// </summary>
        private void NotifyServiceConfigChanged()
        {
            try
            {
                AlwaysPrintLogger.WriteInfo("ConfigManager: notificando al Service sobre cambio de configuración");
                
                if (!_pipeClient.IsConnected)
                {
                    AlwaysPrintLogger.WriteWarning("ConfigManager: pipe no conectado, no se puede notificar al Service");
                    return;
                }
                
                // Enviar mensaje al Service vía Named Pipe
                var message = PipeMessage.Create(MessageType.ActionConfigChanged, null);
                _pipeClient.Send(message);
                
                AlwaysPrintLogger.WriteInfo("ConfigManager: notificación enviada al Service");
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteWarning($"ConfigManager: error notificando al Service: {ex.Message}");
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
    }
    
    public class LocalConfigInfo
    {
        public string Hash { get; set; } = "";
        public string Name { get; set; } = "";
        public string Version { get; set; } = "";
        public string FilePath { get; set; } = "";
    }
}
