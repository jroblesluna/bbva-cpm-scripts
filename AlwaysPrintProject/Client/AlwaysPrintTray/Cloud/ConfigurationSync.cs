using System;
using System.Net;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Messages;
using AlwaysPrintTray.Bootstrap;
using AlwaysPrintTray.Localization;
using AlwaysPrintTray.Pipe;
using Newtonsoft.Json;

namespace AlwaysPrintTray.Cloud
{
    /// <summary>
    /// Gestiona el ciclo completo de sincronización de configuración entre el Tray y APCM.
    /// Compara hash SHA-256, descarga configuración vía HTTP GET, la aplica al Service vía Named Pipe,
    /// persiste cache offline en HKCU, y confirma al servidor mediante config_change_report.
    /// </summary>
    public sealed class ConfigurationSync
    {
        private readonly string _cloudApiUrl;
        private readonly CloudCredentialsManager _credentials;
        private readonly PipeClient _pipe;
        private readonly CloudWebSocketClient _wsClient;

        /// <summary>
        /// Obtiene el workstation_id actual desde CloudCredentialsManager.
        /// Siempre lee el valor más reciente (cubre re-registros donde el ID cambia).
        /// </summary>
        private string WorkstationId => _credentials.WorkstationId!;

        /// <summary>
        /// Crea una nueva instancia de ConfigurationSync.
        /// </summary>
        /// <param name="cloudApiUrl">URL base de la API Cloud (ej: https://alwaysprint.robles.ai).</param>
        /// <param name="workstationId">No utilizado (mantenido por compatibilidad). Se lee de credentials.</param>
        /// <param name="credentials">Gestor de credenciales y cache en HKCU.</param>
        /// <param name="pipe">Cliente Named Pipe para comunicación con el Service.</param>
        /// <param name="wsClient">Cliente WebSocket para enviar reportes a APCM.</param>
        public ConfigurationSync(
            string cloudApiUrl,
            string workstationId,
            CloudCredentialsManager credentials,
            PipeClient pipe,
            CloudWebSocketClient wsClient)
        {
            _cloudApiUrl = cloudApiUrl;
            // workstationId del parámetro ya no se almacena — se lee de _credentials en cada uso
            _credentials = credentials;
            _pipe = pipe;
            _wsClient = wsClient;
        }

        // === Métodos públicos (stubs para tareas posteriores) ===

        /// <summary>
        /// Compara el hash del servidor con el hash local. Si difieren, descarga y aplica la configuración.
        /// Retorna true si la configuración está actualizada (hashes iguales o sincronización exitosa).
        /// </summary>
        /// <param name="serverConfigHash">Hash SHA-256 recibido del servidor en el mensaje config_update.</param>
        /// <returns>true si la configuración está sincronizada; false si falló la sincronización.</returns>
        public bool SyncIfNeeded(string serverConfigHash)
        {
            try
            {
                // Comparar hash del servidor con el hash local almacenado en HKCU
                if (string.Equals(serverConfigHash, _credentials.ConfigHash, StringComparison.OrdinalIgnoreCase))
                {
                    return true;
                }

                // Los hashes difieren — descargar la nueva configuración
                string? rawJson = DownloadConfig();
                if (rawJson == null)
                {
                    return false;
                }

                // Aplicar la configuración descargada
                return ApplyConfig(rawJson, serverConfigHash);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"ConfigurationSync: error durante la sincronización de configuración — {ex.GetType().Name}: {ex.Message}");
                return false;
            }
        }

        /// <summary>
        /// Descarga y aplica la configuración sin comparar hash previo.
        /// Ejecuta la misma secuencia que SyncIfNeeded cuando los hashes difieren,
        /// pero sin verificar el hash local almacenado en HKCU.
        /// </summary>
        /// <returns>true si la configuración fue aplicada exitosamente; false en caso de error.</returns>
        public bool ForceSync()
        {
            try
            {
                // Descargar la configuración sin comparar hash previo
                string? rawJson = DownloadConfig();
                if (rawJson == null)
                {
                    return false;
                }

                // Calcular hash del JSON descargado para usar como serverConfigHash
                string computedHash = ComputeSha256(rawJson);

                // Aplicar la configuración descargada
                return ApplyConfig(rawJson, computedHash);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"ConfigurationSync: error durante la sincronización forzada de configuración — {ex.GetType().Name}: {ex.Message}");
                return false;
            }
        }

        /// <summary>
        /// Lee la configuración desde el cache offline en HKCU y la deserializa.
        /// Retorna null si no hay cache o si la deserialización falla.
        /// </summary>
        /// <returns>AppConfiguration deserializada del cache, o null.</returns>
        public AppConfiguration? LoadFromCache()
        {
            string? cachedJson = _credentials.LoadConfigCache();
            if (string.IsNullOrWhiteSpace(cachedJson))
            {
                return null;
            }

            try
            {
                var settings = new JsonSerializerSettings
                {
                    ContractResolver = new Newtonsoft.Json.Serialization.DefaultContractResolver
                    {
                        NamingStrategy = new Newtonsoft.Json.Serialization.SnakeCaseNamingStrategy()
                    }
                };

                var config = JsonConvert.DeserializeObject<AppConfiguration>(cachedJson!, settings);
                return config;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"ConfigurationSync: error al deserializar configuración desde cache — {ex.GetType().Name}: {ex.Message}");
                return null;
            }
        }

        // === Métodos privados implementados ===

        /// <summary>
        /// Calcula el hash SHA-256 de un string, codificándolo como UTF-8.
        /// Retorna un string hexadecimal en minúsculas de exactamente 64 caracteres.
        /// </summary>
        /// <param name="input">String de entrada a hashear.</param>
        /// <returns>Hash SHA-256 como hex lowercase de 64 caracteres.</returns>
        private static string ComputeSha256(string input)
        {
            byte[] bytes = Encoding.UTF8.GetBytes(input);

            using (var sha256 = SHA256.Create())
            {
                byte[] hash = sha256.ComputeHash(bytes);

                var sb = new StringBuilder(64);
                for (int i = 0; i < hash.Length; i++)
                {
                    sb.Append(hash[i].ToString("x2"));
                }
                return sb.ToString();
            }
        }

        /// <summary>
        /// Envía un reporte config_change_report al servidor vía WebSocket.
        /// Si el WebSocket no está conectado, loggea un warning en español sin reintentar.
        /// </summary>
        /// <param name="applied">true si la configuración fue aplicada exitosamente.</param>
        /// <param name="configHash">Hash de la configuración reportada.</param>
        /// <param name="errorMessage">Mensaje de error descriptivo, o null si fue exitoso.</param>
        private void SendChangeReport(bool applied, string configHash, string? errorMessage = null)
        {
            if (!_wsClient.IsConnected)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    "ConfigurationSync: no se puede enviar config_change_report — WebSocket no está conectado.");
                return;
            }

            var payload = new
            {
                applied = applied,
                config_hash = configHash,
                error_message = errorMessage
            };

            _wsClient.Send("config_change_report", payload);
        }

        // === Stubs privados para tareas posteriores ===

        /// <summary>
        /// Descarga la configuración efectiva desde el endpoint REST de APCM.
        /// Usa el HttpClient estático de DomainHealthChecker con ProxyHelper para soporte de proxy corporativo.
        /// Timeout de 30 segundos. Retorna el body crudo como string, o null si falla.
        /// </summary>
        private string? DownloadConfig()
        {
            string url = $"{_cloudApiUrl}/api/v1/workstations/{WorkstationId}/config";

            try
            {
                using (var cts = new CancellationTokenSource(TimeSpan.FromSeconds(30)))
                {
                    var response = DomainHealthChecker.Http
                        .GetAsync(url, cts.Token)
                        .GetAwaiter()
                        .GetResult();

                    if (response.StatusCode == HttpStatusCode.OK)
                    {
                        string body = response.Content.ReadAsStringAsync().GetAwaiter().GetResult();

                        if (string.IsNullOrWhiteSpace(body))
                        {
                            AlwaysPrintLogger.WriteTrayWarning(
                                "ConfigurationSync: la respuesta del servidor está vacía o es solo espacios en blanco.");
                            return null;
                        }

                        return body;
                    }
                    else
                    {
                        // HTTP 4xx/5xx — loggear código y primeros 2048 chars del body
                        string errorBody = response.Content.ReadAsStringAsync().GetAwaiter().GetResult() ?? string.Empty;
                        if (errorBody.Length > 2048)
                        {
                            errorBody = errorBody.Substring(0, 2048);
                        }

                        AlwaysPrintLogger.WriteTrayError(
                            $"ConfigurationSync: error HTTP {(int)response.StatusCode} al descargar configuración desde {url}. " +
                            $"Respuesta: {errorBody}");
                        return null;
                    }
                }
            }
            catch (OperationCanceledException)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"ConfigurationSync: timeout de 30 segundos al descargar configuración desde {url}.");
                return null;
            }
            catch (HttpRequestException ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"ConfigurationSync: error de red al descargar configuración desde {url} — {ex.Message}");
                return null;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"ConfigurationSync: error inesperado al descargar configuración desde {url} — {ex.GetType().Name}: {ex.Message}");
                return null;
            }
        }

        /// <summary>
        /// Aplica la configuración descargada: valida, envía al Service, persiste cache, aplica locale.
        /// Secuencia: hash → deserializar → validar → pipe → ack → cache → locale → report.
        /// </summary>
        private bool ApplyConfig(string rawJson, string serverConfigHash)
        {
            // 1. Calcular SHA-256 del JSON crudo
            string computedHash = ComputeSha256(rawJson);

            // 2. Verificar integridad: comparar hash computado con el del servidor
            if (!string.Equals(computedHash, serverConfigHash, StringComparison.OrdinalIgnoreCase))
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"ConfigurationSync: hash mismatch — hash computado '{computedHash}' difiere del hash del servidor '{serverConfigHash}'. Se continuará con el hash computado.");
            }

            // 3. Deserializar JSON → AppConfiguration (snake_case → PascalCase)
            AppConfiguration config;
            try
            {
                var settings = new JsonSerializerSettings
                {
                    ContractResolver = new Newtonsoft.Json.Serialization.DefaultContractResolver
                    {
                        NamingStrategy = new Newtonsoft.Json.Serialization.SnakeCaseNamingStrategy()
                    }
                };
                config = JsonConvert.DeserializeObject<AppConfiguration>(rawJson, settings)
                    ?? throw new InvalidOperationException("La deserialización retornó null.");
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"ConfigurationSync: error al deserializar JSON de configuración — {ex.GetType().Name}: {ex.Message}");
                SendChangeReport(false, serverConfigHash, "Error de deserialización JSON");
                return false;
            }

            // 4. Validar la configuración
            try
            {
                config.Validate();
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"ConfigurationSync: la configuración descargada no pasó la validación — {ex.GetType().Name}: {ex.Message}");
                SendChangeReport(false, serverConfigHash, "Validación de configuración fallida");
                return false;
            }

            // 5. Verificar que PipeClient está conectado
            if (!_pipe.IsConnected)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    "ConfigurationSync: no se puede aplicar configuración — el pipe al Service no está conectado.");
                SendChangeReport(false, serverConfigHash, "Pipe no conectado");
                return false;
            }

            // 6. Enviar PipeMessage(CloudConfigurationReceived) con payload
            var pipePayload = new CloudConfigurationReceivedPayload
            {
                Configuration = config,
                ConfigHash = computedHash,
                Source = "cloud"
            };
            var request = PipeMessage.Create(MessageType.CloudConfigurationReceived, pipePayload);

            // 7. Esperar AckPayload del Service con timeout de 10 segundos
            PipeMessage? response = null;
            try
            {
                var sendTask = System.Threading.Tasks.Task.Run(() => _pipe.Send(request));
                if (sendTask.Wait(TimeSpan.FromSeconds(10)))
                {
                    response = sendTask.Result;
                }
                else
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "ConfigurationSync: timeout de 10 segundos esperando respuesta del Service al aplicar configuración.");
                    SendChangeReport(false, serverConfigHash, "Timeout esperando respuesta del Service");
                    return false;
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"ConfigurationSync: error al enviar configuración al Service vía pipe — {ex.GetType().Name}: {ex.Message}");
                SendChangeReport(false, serverConfigHash, "Error de comunicación con el Service");
                return false;
            }

            // 8. Verificar AckPayload
            if (response == null)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    "ConfigurationSync: no se recibió respuesta del Service al aplicar configuración.");
                SendChangeReport(false, serverConfigHash, "Sin respuesta del Service");
                return false;
            }

            var ack = response.GetPayload<AckPayload>();
            if (ack == null || !ack.Success)
            {
                string ackMessage = ack?.Message ?? "sin detalle";
                AlwaysPrintLogger.WriteTrayWarning(
                    $"ConfigurationSync: el Service rechazó la configuración — {ackMessage}");
                SendChangeReport(false, serverConfigHash, $"Service rechazó: {ackMessage}");
                return false;
            }

            // 9. Persistir cache en HKCU — capturar excepciones de CCM
            try
            {
                _credentials.SaveConfigCache(rawJson, computedHash);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"ConfigurationSync: error al guardar cache de configuración en HKCU — {ex.GetType().Name}: {ex.Message}");
                // Continuar — la configuración ya fue aplicada al Service
            }

            // 10. Aplicar locale override si está definido
            if (!string.IsNullOrEmpty(config.CloudLocale))
            {
                try
                {
                    LocalizationManager.Initialize(config.CloudLocale);
                }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"ConfigurationSync: error al aplicar locale '{config.CloudLocale}' — {ex.GetType().Name}: {ex.Message}");
                    // Continuar — la configuración ya fue aplicada
                }
            }

            // 11. Enviar config_change_report(applied: true)
            SendChangeReport(true, serverConfigHash);

            // 12. Retornar éxito
            return true;
        }
    }
}
