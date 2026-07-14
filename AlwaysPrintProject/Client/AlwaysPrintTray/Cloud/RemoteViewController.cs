using System;
using AlwaysPrint.Shared.Logging;
using AlwaysPrintTray.RemoteView;

namespace AlwaysPrintTray.Cloud
{
    /// <summary>
    /// Bridge entre el message loop de CloudManager y los componentes de RemoteView.
    /// Instancia y gestiona los componentes de captura y manejo de sesión,
    /// recibiendo mensajes del WebSocket y delegando al handler apropiado.
    /// 
    /// Solo implementa Screenshot mode (rv_request_frame → rv_frame).
    /// Stream (H.264) e Interactive (input injection) se gestionan por StreamController.
    /// </summary>
    public sealed class RemoteViewController
    {
        private readonly CloudWebSocketClient _wsClient;
        private readonly RemoteViewSession _session;
        private readonly ScreenCapturer _capturer;
        private readonly JpegEncoder _encoder;
        private readonly FrameRequestHandler _frameHandler;
        private readonly InputHandler _inputHandler;

        /// <summary>
        /// Crea una nueva instancia del controller de vista remota.
        /// Inicializa todos los componentes necesarios para Screenshot mode.
        /// </summary>
        /// <param name="wsClient">Cliente WebSocket para enviar respuestas (rv_frame).</param>
        public RemoteViewController(CloudWebSocketClient wsClient)
        {
            _wsClient = wsClient ?? throw new ArgumentNullException(nameof(wsClient));
            _session = new RemoteViewSession();
            _capturer = new ScreenCapturer();
            _encoder = new JpegEncoder();

            // FrameRequestHandler usa un delegado para enviar mensajes (desacoplado del WS)
            _frameHandler = new FrameRequestHandler(
                _session,
                _capturer,
                _encoder,
                (type, payload) => _wsClient.Send(type, payload));

            _inputHandler = new InputHandler(_session);

            // Suscribirse a eventos de sesión para logging
            _session.OnSessionStarted += OnSessionStarted;
            _session.OnSessionEnded += OnSessionEnded;

            AlwaysPrintLogger.WriteTrayInfo(
                "RemoteViewController: inicializado. Screenshot mode listo.");
        }

        /// <summary>
        /// Despacha un mensaje de tipo remote view al handler correspondiente.
        /// Llamado desde CloudManager.OnMessageReceived para mensajes de vista remota.
        /// </summary>
        /// <param name="type">Tipo del mensaje WebSocket.</param>
        /// <param name="json">JSON completo del mensaje.</param>
        public void HandleMessage(string type, string json)
        {
            switch (type)
            {
                case "remote_view_start":
                    _session.HandleStart(json);
                    break;

                case "remote_view_stop":
                    _session.HandleStop(json);
                    break;

                case "remote_view_config":
                    _session.HandleConfig(json);
                    break;

                case "remote_view_pause":
                    _session.HandlePause();
                    break;

                case "remote_view_resume":
                    _session.HandleResume();
                    break;

                case "rv_request_frame":
                    _frameHandler.HandleRequestFrame(json);
                    break;

                case "rv_input":
                    _inputHandler.HandleRvInput(json);
                    break;

                default:
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"RemoteViewController: tipo de mensaje no reconocido '{type}'. Ignorando.");
                    break;
            }
        }

        /// <summary>
        /// Determina si un tipo de mensaje pertenece al subsistema de vista remota.
        /// Usado por CloudManager para enrutar mensajes sin agregar cases explícitos por cada tipo.
        /// </summary>
        /// <param name="type">Tipo del mensaje WebSocket.</param>
        /// <returns>true si el mensaje es de vista remota, false en caso contrario.</returns>
        public static bool IsRemoteViewMessage(string type)
        {
            return type == "remote_view_start"
                || type == "remote_view_stop"
                || type == "remote_view_config"
                || type == "remote_view_pause"
                || type == "remote_view_resume"
                || type == "rv_request_frame"
                || type == "rv_input";
        }

        /// <summary>
        /// Finaliza la sesión activa programáticamente (ej: pérdida de conexión WebSocket).
        /// </summary>
        public void EndSession()
        {
            _session.End();
        }

        /// <summary>
        /// Indica si hay una sesión de vista remota activa.
        /// </summary>
        public bool HasActiveSession => _session.IsActive;

        private void OnSessionStarted()
        {
            AlwaysPrintLogger.WriteTrayInfo(
                $"RemoteViewController: sesión iniciada. session_id={_session.SessionId}, mode={_session.Mode}");
        }

        private void OnSessionEnded()
        {
            AlwaysPrintLogger.WriteTrayInfo(
                $"RemoteViewController: sesión finalizada.");
        }
    }
}
