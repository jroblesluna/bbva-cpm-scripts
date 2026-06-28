using System;
using System.IO;
using System.Net.Http;
using System.Threading.Tasks;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;
using AlwaysPrintService.Debugging;
using Newtonsoft.Json.Linq;

namespace AlwaysPrintTray.Cloud
{
    /// <summary>
    /// Maneja los comandos de debugging recibidos vía WebSocket.
    /// Integra el DebuggingEngine con la comunicación al backend.
    /// 
    /// Comandos soportados:
    /// - start_debugging: Inicia captura según perfil
    /// - stop_debugging: Detiene captura activa
    /// - request_debug_upload: Comprime y sube ZIP al backend
    /// - delete_debug_data: Elimina datos de debugging del cliente
    /// </summary>
    public class DebuggingCommandHandler
    {
        private readonly DebuggingEngine _engine;
        private readonly CloudWebSocketClient _wsClient;
        private readonly HttpClient _httpClient;
        private readonly string _workstationId;
        private readonly string _cloudApiUrl;

        public DebuggingCommandHandler(
            CloudWebSocketClient wsClient,
            HttpClient httpClient,
            string workstationId,
            string cloudApiUrl)
        {
            _wsClient = wsClient ?? throw new ArgumentNullException(nameof(wsClient));
            _httpClient = httpClient ?? throw new ArgumentNullException(nameof(httpClient));
            _workstationId = workstationId ?? throw new ArgumentNullException(nameof(workstationId));
            _cloudApiUrl = cloudApiUrl?.TrimEnd('/') ?? throw new ArgumentNullException(nameof(cloudApiUrl));

            _engine = new DebuggingEngine();

            // Suscribirse a eventos del engine
            _engine.OnCaptureComplete += HandleCaptureComplete;
            _engine.OnCaptureError += HandleCaptureError;
        }

        /// <summary>
        /// Procesa un comando de debugging recibido del backend vía WebSocket.
        /// </summary>
        /// <param name="commandType">Tipo de comando: start_debugging, stop_debugging, etc.</param>
        /// <param name="commandId">ID del comando para tracking.</param>
        /// <param name="paramsObj">Parámetros del comando.</param>
        public void HandleCommand(string commandType, string commandId, JObject? paramsObj)
        {
            switch (commandType)
            {
                case "start_debugging":
                    HandleStartDebugging(commandId, paramsObj);
                    break;

                case "stop_debugging":
                    HandleStopDebugging(commandId, paramsObj);
                    break;

                case "request_debug_upload":
                    HandleRequestUpload(commandId, paramsObj);
                    break;

                case "delete_debug_data":
                    HandleDeleteData(commandId, paramsObj);
                    break;

                default:
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"DebuggingCommandHandler: comando desconocido '{commandType}'");
                    break;
            }
        }

        // ═══════════════════════════════════════════════════════════════════════
        // HANDLERS DE COMANDOS
        // ═══════════════════════════════════════════════════════════════════════

        private void HandleStartDebugging(string commandId, JObject? paramsObj)
        {
            if (paramsObj == null)
            {
                AlwaysPrintLogger.WriteTrayError(
                    "DebuggingCommandHandler: start_debugging sin params.");
                return;
            }

            string debuggingId = paramsObj["debugging_id"]?.ToString() ?? "";
            var profile = paramsObj["profile"] as JObject;
            int durationSeconds = paramsObj["duration_seconds"]?.Value<int>() ?? 60;

            if (string.IsNullOrEmpty(debuggingId) || profile == null)
            {
                AlwaysPrintLogger.WriteTrayError(
                    "DebuggingCommandHandler: start_debugging con params incompletos.");
                SendDebuggingError(debuggingId, "Parámetros de debugging incompletos");
                return;
            }

            bool started = _engine.StartSession(debuggingId, profile, durationSeconds);

            if (started)
            {
                // Enviar acknowledgment al backend
                SendDebuggingStarted(debuggingId);
                AlwaysPrintLogger.WriteTrayInfo(
                    $"DebuggingCommandHandler: Sesión iniciada. ID={debuggingId}, duración={durationSeconds}s");
            }
            else
            {
                SendDebuggingError(debuggingId, "No se pudo iniciar la sesión (ya hay una activa)");
            }
        }

        private void HandleStopDebugging(string commandId, JObject? paramsObj)
        {
            string debuggingId = paramsObj?["debugging_id"]?.ToString() ?? "";

            if (string.IsNullOrEmpty(debuggingId))
            {
                AlwaysPrintLogger.WriteTrayError(
                    "DebuggingCommandHandler: stop_debugging sin debugging_id.");
                return;
            }

            _engine.StopSession(debuggingId);
            AlwaysPrintLogger.WriteTrayInfo(
                $"DebuggingCommandHandler: StopSession invocado para {debuggingId}");
        }

        private void HandleRequestUpload(string commandId, JObject? paramsObj)
        {
            string debuggingId = paramsObj?["debugging_id"]?.ToString() ?? "";

            if (string.IsNullOrEmpty(debuggingId))
            {
                AlwaysPrintLogger.WriteTrayError(
                    "DebuggingCommandHandler: request_debug_upload sin debugging_id.");
                return;
            }

            // Empaquetar y subir en background
            Task.Run(async () =>
            {
                try
                {
                    // Comprimir
                    string? zipPath = _engine.PackageForUpload(debuggingId);
                    if (zipPath == null)
                    {
                        AlwaysPrintLogger.WriteTrayError(
                            $"DebuggingCommandHandler: No se pudo crear ZIP para {debuggingId}");
                        SendDebuggingError(debuggingId, "Error creando ZIP para upload");
                        return;
                    }

                    // Upload vía HTTP
                    await UploadZipToBackend(debuggingId, zipPath);

                    AlwaysPrintLogger.WriteTrayInfo(
                        $"DebuggingCommandHandler: ZIP subido exitosamente para {debuggingId}");
                }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteTrayError(
                        $"DebuggingCommandHandler: Error en upload para {debuggingId}: {ex.Message}");
                    SendDebuggingError(debuggingId, $"Error en upload: {ex.Message}");
                }
            });
        }

        private void HandleDeleteData(string commandId, JObject? paramsObj)
        {
            string debuggingId = paramsObj?["debugging_id"]?.ToString() ?? "";

            if (string.IsNullOrEmpty(debuggingId))
            {
                AlwaysPrintLogger.WriteTrayError(
                    "DebuggingCommandHandler: delete_debug_data sin debugging_id.");
                return;
            }

            _engine.DeleteSession(debuggingId);
            SendDebuggingDeleted(debuggingId);

            AlwaysPrintLogger.WriteTrayInfo(
                $"DebuggingCommandHandler: Datos eliminados para {debuggingId}");
        }

        // ═══════════════════════════════════════════════════════════════════════
        // EVENT HANDLERS DEL ENGINE
        // ═══════════════════════════════════════════════════════════════════════

        private void HandleCaptureComplete(string debuggingId, long totalSizeBytes)
        {
            SendDebuggingReady(debuggingId, totalSizeBytes);
            AlwaysPrintLogger.WriteTrayInfo(
                $"DebuggingCommandHandler: Captura completada. ID={debuggingId}, size={totalSizeBytes} bytes");
        }

        private void HandleCaptureError(string debuggingId, string errorMessage)
        {
            SendDebuggingError(debuggingId, errorMessage);
            AlwaysPrintLogger.WriteTrayError(
                $"DebuggingCommandHandler: Error en captura. ID={debuggingId}, error={errorMessage}");
        }

        // ═══════════════════════════════════════════════════════════════════════
        // MENSAJES WEBSOCKET AL BACKEND
        // ═══════════════════════════════════════════════════════════════════════

        private void SendDebuggingStarted(string debuggingId)
        {
            try
            {
                _wsClient.Send("debugging_started", new JObject
                {
                    ["debugging_id"] = debuggingId,
                    ["status"] = "capturing"
                });
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"DebuggingCommandHandler: Error enviando debugging_started: {ex.Message}");
            }
        }

        private void SendDebuggingReady(string debuggingId, long totalSizeBytes)
        {
            try
            {
                _wsClient.Send("debugging_ready", new JObject
                {
                    ["debugging_id"] = debuggingId,
                    ["status"] = "ready_for_collection",
                    ["total_size_bytes"] = totalSizeBytes
                });
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"DebuggingCommandHandler: Error enviando debugging_ready: {ex.Message}");
            }
        }

        private void SendDebuggingDeleted(string debuggingId)
        {
            try
            {
                _wsClient.Send("debugging_deleted", new JObject
                {
                    ["debugging_id"] = debuggingId
                });
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"DebuggingCommandHandler: Error enviando debugging_deleted: {ex.Message}");
            }
        }

        private void SendDebuggingError(string debuggingId, string errorMessage)
        {
            try
            {
                _wsClient.Send("debugging_error", new JObject
                {
                    ["debugging_id"] = debuggingId,
                    ["error_message"] = errorMessage
                });
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"DebuggingCommandHandler: Error enviando debugging_error: {ex.Message}");
            }
        }

        // ═══════════════════════════════════════════════════════════════════════
        // HTTP UPLOAD
        // ═══════════════════════════════════════════════════════════════════════

        private async Task UploadZipToBackend(string debuggingId, string zipPath)
        {
            string uploadUrl = $"{_cloudApiUrl}/api/v1/debugging/{debuggingId}/upload";

            using (var content = new MultipartFormDataContent())
            using (var fileStream = File.OpenRead(zipPath))
            using (var streamContent = new StreamContent(fileStream))
            {
                streamContent.Headers.ContentType =
                    new System.Net.Http.Headers.MediaTypeHeaderValue("application/zip");

                content.Add(streamContent, "file", Path.GetFileName(zipPath));

                // Agregar header de autenticación de workstation
                var request = new HttpRequestMessage(HttpMethod.Post, uploadUrl);
                request.Headers.Add("X-Workstation-ID", _workstationId);
                request.Content = content;

                var response = await _httpClient.SendAsync(request);

                if (!response.IsSuccessStatusCode)
                {
                    string body = await response.Content.ReadAsStringAsync();
                    throw new HttpRequestException(
                        $"Upload fallido: HTTP {(int)response.StatusCode} - {body}");
                }
            }
        }
    }
}
