using System;
using System.Drawing;
using AlwaysPrint.Shared.Logging;
using Newtonsoft.Json.Linq;

namespace AlwaysPrintTray.RemoteView
{
    /// <summary>
    /// Maneja solicitudes rv_request_frame recibidas por WebSocket.
    /// Captura la pantalla, codifica a JPEG y envía el frame como rv_frame (base64 JSON).
    /// Desacoplado del WebSocket: usa un delegado para enviar la respuesta.
    /// </summary>
    public class FrameRequestHandler
    {
        private readonly RemoteViewSession _session;
        private readonly ScreenCapturer _capturer;
        private readonly JpegEncoder _encoder;
        private readonly Action<string, object> _sendMessage;

        /// <summary>
        /// Crea una nueva instancia del handler de solicitudes de frame.
        /// </summary>
        /// <param name="session">Sesión activa de vista remota (estado y parámetros).</param>
        /// <param name="capturer">Capturador de pantalla.</param>
        /// <param name="encoder">Codificador JPEG.</param>
        /// <param name="sendMessage">Delegado para enviar mensajes vía WebSocket. Recibe (type, payload).</param>
        public FrameRequestHandler(
            RemoteViewSession session,
            ScreenCapturer capturer,
            JpegEncoder encoder,
            Action<string, object> sendMessage)
        {
            _session = session ?? throw new ArgumentNullException(nameof(session));
            _capturer = capturer ?? throw new ArgumentNullException(nameof(capturer));
            _encoder = encoder ?? throw new ArgumentNullException(nameof(encoder));
            _sendMessage = sendMessage ?? throw new ArgumentNullException(nameof(sendMessage));
        }

        /// <summary>
        /// Procesa una solicitud rv_request_frame.
        /// Valida que la sesión esté activa y no pausada, captura la pantalla,
        /// codifica a JPEG y envía rv_frame con los datos en base64.
        /// </summary>
        /// <param name="json">JSON completo del mensaje rv_request_frame.</param>
        public void HandleRequestFrame(string json)
        {
            try
            {
                var data = JObject.Parse(json);
                var requestSessionId = data["session_id"]?.ToString();

                // Validar que la solicitud corresponde a la sesión activa
                if (requestSessionId != null && requestSessionId != _session.SessionId)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"FrameRequestHandler: rv_request_frame para session_id={requestSessionId} " +
                        $"pero la sesión activa es {_session.SessionId}. Ignorando.");
                    return;
                }

                // Validar que la sesión esté activa
                if (!_session.IsActive)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "FrameRequestHandler: rv_request_frame recibido pero no hay sesión activa. Ignorando.");
                    return;
                }

                // Validar que la sesión no esté pausada
                if (_session.IsPaused)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "FrameRequestHandler: rv_request_frame recibido pero la sesión está pausada. Ignorando.");
                    return;
                }

                // Resolver dimensiones de captura según la resolución configurada
                int targetWidth;
                int targetHeight;
                ResolveResolution(_session.Resolution, out targetWidth, out targetHeight);

                // Capturar pantalla del monitor configurado
                Bitmap bitmap = null;
                try
                {
                    bitmap = _capturer.Capture(_session.MonitorIndex, targetWidth, targetHeight);
                }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteTrayError(
                        $"FrameRequestHandler: error capturando pantalla. monitor={_session.MonitorIndex}, " +
                        $"target={targetWidth}x{targetHeight}. {ex.Message}");
                    return;
                }

                // Codificar a JPEG (con viewport-adaptive si aplica)
                byte[] jpegData;
                int frameWidth;
                int frameHeight;

                try
                {
                    // Guardar dimensiones del bitmap capturado (puede diferir del target si no se escaló)
                    frameWidth = bitmap.Width;
                    frameHeight = bitmap.Height;

                    // Aplicar viewport-adaptive downscale si el viewport es menor que la captura
                    if (_session.ViewportWidth > 0 && _session.ViewportHeight > 0)
                    {
                        jpegData = _encoder.EncodeWithViewportAdaptive(
                            bitmap,
                            _session.Quality,
                            _session.ViewportWidth,
                            _session.ViewportHeight);

                        // Si se aplicó viewport-adaptive, las dimensiones del frame enviado
                        // son las del viewport (o menores si el bitmap era más pequeño)
                        if (_session.ViewportWidth < frameWidth || _session.ViewportHeight < frameHeight)
                        {
                            frameWidth = Math.Min(_session.ViewportWidth, frameWidth);
                            frameHeight = Math.Min(_session.ViewportHeight, frameHeight);
                        }
                    }
                    else
                    {
                        jpegData = _encoder.Encode(bitmap, _session.Quality);
                    }
                }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteTrayError(
                        $"FrameRequestHandler: error codificando JPEG. " +
                        $"bitmap={bitmap.Width}x{bitmap.Height}, quality={_session.Quality}. {ex.Message}");
                    return;
                }
                finally
                {
                    bitmap.Dispose();
                }

                // Convertir a base64 y enviar rv_frame
                var base64Data = Convert.ToBase64String(jpegData);

                var payload = new
                {
                    session_id = _session.SessionId,
                    format = "jpeg",
                    width = frameWidth,
                    height = frameHeight,
                    data = base64Data
                };

                _sendMessage("rv_frame", payload);

                // VERBOSE: AlwaysPrintLogger.WriteTrayInfo(
                //     $"FrameRequestHandler: frame enviado. session_id={_session.SessionId}, " +
                //     $"dimensions={frameWidth}x{frameHeight}, size={jpegData.Length} bytes, " +
                //     $"base64={base64Data.Length} chars");
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"FrameRequestHandler: error inesperado procesando rv_request_frame. {ex.Message}");
            }
        }

        /// <summary>
        /// Resuelve la resolución configurada a dimensiones en píxeles.
        /// Mapeo: "1080p" → 1920x1080, "720p" → 1280x720, "480p" → 854x480, "360p" → 640x360.
        /// Si la resolución no es reconocida o es "auto", usa 1280x720 por defecto.
        /// </summary>
        /// <param name="resolution">String de resolución (ej: "720p", "1080p").</param>
        /// <param name="width">Ancho resultante en píxeles.</param>
        /// <param name="height">Alto resultante en píxeles.</param>
        private static void ResolveResolution(string? resolution, out int width, out int height)
        {
            if (resolution == "1080p")
            {
                width = 1920;
                height = 1080;
            }
            else if (resolution == "720p")
            {
                width = 1280;
                height = 720;
            }
            else if (resolution == "480p")
            {
                width = 854;
                height = 480;
            }
            else if (resolution == "360p")
            {
                width = 640;
                height = 360;
            }
            else
            {
                // Default (incluyendo "auto"): empezar en 720p
                width = 1280;
                height = 720;
            }
        }
    }
}
