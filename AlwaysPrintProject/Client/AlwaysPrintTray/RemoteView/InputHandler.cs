using System;
using AlwaysPrint.Shared.Logging;
using Newtonsoft.Json.Linq;

namespace AlwaysPrintTray.RemoteView
{
    /// <summary>
    /// Maneja mensajes rv_input recibidos por WebSocket.
    /// Parsea el tipo de evento (mousemove, mousedown, mouseup, wheel, keydown, keyup, sas)
    /// y delega a InputInjector con conversión de coordenadas.
    /// Solo procesa eventos si la sesión actual está en mode=interactive.
    /// </summary>
    public class InputHandler
    {
        private readonly RemoteViewSession _session;

        /// <summary>
        /// Crea una nueva instancia del handler de input remoto.
        /// </summary>
        /// <param name="session">Sesión activa de vista remota (estado y parámetros).</param>
        public InputHandler(RemoteViewSession session)
        {
            _session = session ?? throw new ArgumentNullException(nameof(session));
        }

        /// <summary>
        /// Procesa un mensaje rv_input recibido por WebSocket.
        /// Valida que la sesión esté activa y en modo interactivo,
        /// parsea el evento y delega a InputInjector.
        /// </summary>
        /// <param name="json">JSON completo del mensaje rv_input.</param>
        public void HandleRvInput(string json)
        {
            try
            {
                // Guard clause: solo procesar si el modo es interactive
                if (_session.Mode != "interactive")
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"InputHandler: rv_input recibido pero el modo actual es '{_session.Mode}'. " +
                        "Solo se procesa input en mode=interactive. Ignorando.");
                    return;
                }

                // Validar que la sesión esté activa
                if (!_session.IsActive)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "InputHandler: rv_input recibido pero no hay sesión activa. Ignorando.");
                    return;
                }

                var data = JObject.Parse(json);

                // Validar que el session_id coincide con la sesión activa
                var inputSessionId = data["session_id"]?.ToString();
                if (inputSessionId != null && inputSessionId != _session.SessionId)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"InputHandler: rv_input para session_id={inputSessionId} " +
                        $"pero la sesión activa es {_session.SessionId}. Ignorando.");
                    return;
                }

                // Parsear tipo de evento
                var eventType = data["event"]?.ToString();
                if (string.IsNullOrEmpty(eventType))
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "InputHandler: rv_input recibido sin campo 'event'. Ignorando.");
                    return;
                }

                // Despachar según tipo de evento
                switch (eventType)
                {
                    case "mousemove":
                        HandleMouseMove(data);
                        break;

                    case "mousedown":
                        HandleMouseDown(data);
                        break;

                    case "mouseup":
                        HandleMouseUp(data);
                        break;

                    case "wheel":
                        HandleWheel(data);
                        break;

                    case "keydown":
                        HandleKeyDown(data);
                        break;

                    case "keyup":
                        HandleKeyUp(data);
                        break;

                    case "sas":
                        HandleSAS();
                        break;

                    default:
                        AlwaysPrintLogger.WriteTrayWarning(
                            $"InputHandler: tipo de evento desconocido '{eventType}'. Ignorando.");
                        break;
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"InputHandler: error inesperado procesando rv_input. {ex.Message}");
            }
        }

        /// <summary>
        /// Procesa un evento mousemove. Extrae coordenadas normalizadas (0.0-1.0)
        /// y delega a InputInjector para mover el cursor al monitor configurado.
        /// </summary>
        private void HandleMouseMove(JObject data)
        {
            var x = data["x"]?.ToObject<double>() ?? 0.0;
            var y = data["y"]?.ToObject<double>() ?? 0.0;

            InputInjector.InjectMouseMove(x, y, _session.MonitorIndex);
        }

        /// <summary>
        /// Procesa un evento mousedown. Extrae coordenadas y botón,
        /// y delega a InputInjector para inyectar click en el monitor configurado.
        /// </summary>
        private void HandleMouseDown(JObject data)
        {
            var x = data["x"]?.ToObject<double>() ?? 0.0;
            var y = data["y"]?.ToObject<double>() ?? 0.0;
            var button = data["button"]?.ToString() ?? "left";

            InputInjector.InjectMouseDown(button, x, y, _session.MonitorIndex);
        }

        /// <summary>
        /// Procesa un evento mouseup. Extrae coordenadas y botón,
        /// y delega a InputInjector para soltar el botón en el monitor configurado.
        /// </summary>
        private void HandleMouseUp(JObject data)
        {
            var x = data["x"]?.ToObject<double>() ?? 0.0;
            var y = data["y"]?.ToObject<double>() ?? 0.0;
            var button = data["button"]?.ToString() ?? "left";

            InputInjector.InjectMouseUp(button, x, y, _session.MonitorIndex);
        }

        /// <summary>
        /// Procesa un evento wheel (scroll). Extrae el delta y delega a InputInjector.
        /// </summary>
        private void HandleWheel(JObject data)
        {
            var delta = data["delta"]?.ToObject<int>() ?? 0;

            InputInjector.InjectWheel(delta);
        }

        /// <summary>
        /// Procesa un evento keydown. Mapea el código JavaScript a virtual key code
        /// usando KeyCodeMapper y delega a InputInjector con los modificadores activos.
        /// </summary>
        private void HandleKeyDown(JObject data)
        {
            var code = data["code"]?.ToString();
            if (string.IsNullOrEmpty(code))
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    "InputHandler: keydown recibido sin campo 'code'. Ignorando.");
                return;
            }

            // Mapear código JavaScript a virtual key de Windows
            var virtualKey = KeyCodeMapper.GetVirtualKey(code!);
            if (virtualKey == 0)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"InputHandler: keydown con código no reconocido '{code}'. Ignorando.");
                return;
            }

            // Extraer modificadores activos
            var modifiers = ExtractModifiers(data);

            InputInjector.InjectKeyDown(virtualKey, modifiers);
        }

        /// <summary>
        /// Procesa un evento keyup. Mapea el código JavaScript a virtual key code
        /// usando KeyCodeMapper y delega a InputInjector con los modificadores activos.
        /// </summary>
        private void HandleKeyUp(JObject data)
        {
            var code = data["code"]?.ToString();
            if (string.IsNullOrEmpty(code))
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    "InputHandler: keyup recibido sin campo 'code'. Ignorando.");
                return;
            }

            // Mapear código JavaScript a virtual key de Windows
            var virtualKey = KeyCodeMapper.GetVirtualKey(code!);
            if (virtualKey == 0)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"InputHandler: keyup con código no reconocido '{code}'. Ignorando.");
                return;
            }

            // Extraer modificadores activos
            var modifiers = ExtractModifiers(data);

            InputInjector.InjectKeyUp(virtualKey, modifiers);
        }

        /// <summary>
        /// Procesa un evento sas (Secure Attention Sequence — Ctrl+Alt+Del).
        /// Delega directamente a InputInjector.InjectSAS().
        /// </summary>
        private void HandleSAS()
        {
            AlwaysPrintLogger.WriteTrayInfo(
                $"InputHandler: SAS (Ctrl+Alt+Del) solicitado. session_id={_session.SessionId}");

            InputInjector.InjectSAS();
        }

        /// <summary>
        /// Extrae el array de modificadores activos del mensaje JSON.
        /// Convierte el JArray a string[] para InputInjector.
        /// </summary>
        /// <param name="data">Objeto JSON del mensaje rv_input.</param>
        /// <returns>Array de strings con los modificadores activos ("ctrl", "alt", "shift", "meta"), o null si no hay.</returns>
        private static string[]? ExtractModifiers(JObject data)
        {
            var modifiersToken = data["modifiers"];
            if (modifiersToken == null || modifiersToken.Type != JTokenType.Array)
                return null;

            var modifiersArray = modifiersToken.ToObject<string[]>();
            if (modifiersArray == null || modifiersArray.Length == 0)
                return null;

            return modifiersArray;
        }
    }
}
