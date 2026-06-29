using System;
using System.IO;
using System.Net.Http;
using System.Threading.Tasks;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Messages;
using AlwaysPrintTray.Pipe;
using Newtonsoft.Json.Linq;

namespace AlwaysPrintTray.Cloud
{
    /// <summary>
    /// Maneja los comandos de debugging recibidos vía WebSocket.
    /// Delega la captura de datos al Service (LocalSystem) vía Named Pipe
    /// y gestiona la comunicación con el backend (WebSocket + HTTP upload).
    /// 
    /// Flujo:
    /// 1. WebSocket recibe comando → Tray delega al Service vía Pipe
    /// 2. Service ejecuta captura con privilegios LocalSystem
    /// 3. Service notifica resultado al Tray vía push message
    /// 4. Tray reporta al backend vía WebSocket / HTTP upload
    /// 
    /// Comandos soportados:
    /// - start_debugging: Delega inicio de captura al Service
    /// - stop_debugging: Delega detención al Service
    /// - request_debug_upload: Solicita ZIP al Service y lo sube al backend
    /// - delete_debug_data: Delega eliminación de datos al Service
    /// </summary>
    public class DebuggingCommandHandler
    {
        private readonly CloudWebSocketClient _wsClient;
        private readonly PipeClient _pipeClient;
        private readonly HttpClient _httpClient;
        private readonly string _workstationId;
        private readonly string _cloudApiUrl;

        public DebuggingCommandHandler(
            CloudWebSocketClient wsClient,
            PipeClient pipeClient,
            HttpClient httpClient,
            string workstationId,
            string cloudApiUrl)
        {
            _wsClient = wsClient ?? throw new ArgumentNullException(nameof(wsClient));
            _pipeClient = pipeClient ?? throw new ArgumentNullException(nameof(pipeClient));
            _httpClient = httpClient ?? throw new ArgumentNullException(nameof(httpClient));
            _workstationId = workstationId ?? throw new ArgumentNullException(nameof(workstationId));
            _cloudApiUrl = cloudApiUrl?.TrimEnd('/') ?? throw new ArgumentNullException(nameof(cloudApiUrl));
        }

        /// <summary>
        /// Procesa un comando de debugging recibido del backend vía WebSocket.
        /// </summary>
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

        /// <summary>
        /// Procesa mensajes push del Service relacionados con debugging.
        /// Llamado desde CloudManager.OnPipeMessageReceived.
        /// </summary>
        public void HandleServicePush(PipeMessage message)
        {
            switch (message.Type)
            {
                case MessageType.DebuggingCaptureReady:
                    var readyPayload = message.GetPayload<DebuggingCaptureReadyPayload>();
                    if (readyPayload != null)
                    {
                        SendDebuggingReady(readyPayload.DebuggingId, readyPayload.TotalSizeBytes);
                        AlwaysPrintLogger.WriteTrayInfo(
                            $"DebuggingCommandHandler: Captura completada (Service). ID={readyPayload.DebuggingId}, size={readyPayload.TotalSizeBytes} bytes");
                    }
                    break;

                case MessageType.DebuggingCaptureError:
                    var errorPayload = message.GetPayload<DebuggingCaptureErrorPayload>();
                    if (errorPayload != null)
                    {
                        SendDebuggingError(errorPayload.DebuggingId, errorPayload.ErrorMessage);
                        AlwaysPrintLogger.WriteTrayError(
                            $"DebuggingCommandHandler: Error en captura (Service). ID={errorPayload.DebuggingId}, error={errorPayload.ErrorMessage}");
                    }
                    break;
            }
        }

        // ═══════════════════════════════════════════════════════════════════════
        // HANDLERS DE COMANDOS (delegan al Service vía Named Pipe)
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

            // Delegar al Service vía Named Pipe
            var pipeMsg = PipeMessage.Create(MessageType.StartDebuggingCapture,
                new StartDebuggingCapturePayload
                {
                    DebuggingId = debuggingId,
                    DurationSeconds = durationSeconds,
                    ProfileJson = profile.ToString()
                });

            var response = _pipeClient.Send(pipeMsg);

            if (response != null)
            {
                var ack = response.GetPayload<AckPayload>();
                if (ack?.Success == true)
                {
                    SendDebuggingStarted(debuggingId);
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"DebuggingCommandHandler: Captura delegada al Service. ID={debuggingId}, duración={durationSeconds}s");
                }
                else
                {
                    string errorMsg = ack?.Message ?? "Error desconocido al iniciar captura en Service";
                    SendDebuggingError(debuggingId, errorMsg);
                    AlwaysPrintLogger.WriteTrayError(
                        $"DebuggingCommandHandler: Service rechazó inicio: {errorMsg}");
                }
            }
            else
            {
                SendDebuggingError(debuggingId, "No se pudo comunicar con el Service (pipe desconectado)");
                AlwaysPrintLogger.WriteTrayError(
                    "DebuggingCommandHandler: Pipe desconectado al intentar start_debugging");
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

            var pipeMsg = PipeMessage.Create(MessageType.StopDebuggingCapture,
                new StopDebuggingCapturePayload { DebuggingId = debuggingId });

            _pipeClient.Send(pipeMsg);

            AlwaysPrintLogger.WriteTrayInfo(
                $"DebuggingCommandHandler: Stop delegado al Service para {debuggingId}");
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

            // Solicitar ZIP al Service y subir en background
            Task.Run(async () =>
            {
                try
                {
                    // Pedir al Service que empaquete el ZIP
                    var pipeMsg = PipeMessage.Create(MessageType.PackageDebuggingZip,
                        new PackageDebuggingZipPayload { DebuggingId = debuggingId });

                    var response = _pipeClient.Send(pipeMsg);

                    if (response == null)
                    {
                        SendDebuggingError(debuggingId, "No se pudo comunicar con el Service para empaquetar ZIP");
                        return;
                    }

                    var zipReady = response.GetPayload<DebuggingZipReadyPayload>();
                    string zipPath = zipReady?.ZipPath ?? "";

                    if (string.IsNullOrEmpty(zipPath))
                    {
                        SendDebuggingError(debuggingId, "Error creando ZIP para upload (Service retornó ruta vacía)");
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

            var pipeMsg = PipeMessage.Create(MessageType.DeleteDebuggingData,
                new DeleteDebuggingDataPayload { DebuggingId = debuggingId });

            _pipeClient.Send(pipeMsg);
            SendDebuggingDeleted(debuggingId);

            AlwaysPrintLogger.WriteTrayInfo(
                $"DebuggingCommandHandler: Datos eliminados para {debuggingId}");
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
            using (var fileStream = new FileStream(zipPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
            using (var streamContent = new StreamContent(fileStream))
            {
                streamContent.Headers.ContentType =
                    new System.Net.Http.Headers.MediaTypeHeaderValue("application/zip");

                content.Add(streamContent, "file", Path.GetFileName(zipPath));

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
