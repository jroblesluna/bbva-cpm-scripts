using System;
using AlwaysPrint.Shared.Logging;
using Newtonsoft.Json.Linq;

namespace AlwaysPrintTray.RemoteView
{
    /// <summary>
    /// Estados posibles de una sesión de vista remota.
    /// </summary>
    public enum RemoteViewSessionState
    {
        /// <summary>Esperando consentimiento del usuario.</summary>
        PendingConsent,
        /// <summary>Sesión activa transmitiendo frames.</summary>
        Active,
        /// <summary>Sesión pausada (admin cambió de tab).</summary>
        Paused,
        /// <summary>Sesión finalizada.</summary>
        Ended
    }

    /// <summary>
    /// Gestiona el estado de una sesión de vista remota activa en el Tray.
    /// Procesa mensajes WebSocket de inicio, parada, configuración y pausa/resume.
    /// Thread-safe: los handlers pueden ser invocados desde el hilo del WebSocket.
    /// </summary>
    public sealed class RemoteViewSession
    {
        // === Eventos públicos para que otros componentes reaccionen ===

        /// <summary>Se dispara cuando la sesión inicia (tras aceptar o auto-aceptar).</summary>
        public event Action? OnSessionStarted;

        /// <summary>Se dispara cuando se requiere consentimiento del usuario.</summary>
        public event Action? OnConsentRequired;

        /// <summary>Se dispara cuando la sesión termina por cualquier razón.</summary>
        public event Action? OnSessionEnded;

        /// <summary>Se dispara cuando se recibe una actualización de configuración en vivo.</summary>
        public event Action? OnConfigChanged;

        /// <summary>Se dispara cuando cambia el estado de pausa (pause/resume).</summary>
        public event Action? OnPauseChanged;

        // === Propiedades de estado de la sesión ===

        /// <summary>ID único de la sesión (UUID del backend).</summary>
        public string? SessionId { get; private set; }

        /// <summary>Modo actual: screenshot, stream, interactive.</summary>
        public string? Mode { get; private set; }

        /// <summary>Indica si la sesión está activa (Active o Paused).</summary>
        public bool IsActive => _state == RemoteViewSessionState.Active || _state == RemoteViewSessionState.Paused;

        /// <summary>Indica si la sesión está pausada (admin cambió de tab).</summary>
        public bool IsPaused => _state == RemoteViewSessionState.Paused;

        /// <summary>Resolución de captura configurada (ej: "720p", "480p", "1080p").</summary>
        public string? Resolution { get; private set; }

        /// <summary>Calidad de compresión JPEG (1-100).</summary>
        public int Quality { get; private set; }

        /// <summary>Índice del monitor a capturar.</summary>
        public int MonitorIndex { get; private set; }

        /// <summary>Ancho del viewport del admin (para viewport-adaptive downscale).</summary>
        public int ViewportWidth { get; private set; }

        /// <summary>Alto del viewport del admin.</summary>
        public int ViewportHeight { get; private set; }

        /// <summary>Nombre del admin/operador que inició la sesión.</summary>
        public string? UserName { get; private set; }

        /// <summary>FPS máximo para Stream/Interactive mode.</summary>
        public int Fps { get; private set; }

        /// <summary>Estado actual de la sesión.</summary>
        public RemoteViewSessionState State => _state;

        // === Estado interno ===
        private volatile RemoteViewSessionState _state = RemoteViewSessionState.Ended;
        private readonly object _lock = new object();

        /// <summary>
        /// Procesa el mensaje remote_view_start recibido por WebSocket.
        /// Almacena los parámetros de sesión y transiciona al estado Active.
        /// </summary>
        /// <param name="json">JSON completo del mensaje remote_view_start.</param>
        public void HandleStart(string json)
        {
            try
            {
                var data = JObject.Parse(json);

                lock (_lock)
                {
                    SessionId = data["session_id"]?.ToString();
                    Mode = data["mode"]?.ToString() ?? "screenshot";
                    Resolution = data["resolution"]?.ToString() ?? "720p";
                    Quality = data["quality"]?.Value<int?>() ?? 70;
                    MonitorIndex = data["monitor"]?.Value<int?>() ?? 0;
                    UserName = data["user_name"]?.ToString();
                    ViewportWidth = data["viewport_width"]?.Value<int?>() ?? 0;
                    ViewportHeight = data["viewport_height"]?.Value<int?>() ?? 0;
                    Fps = data["fps"]?.Value<int?>() ?? 5;

                    // Si require_consent está ausente, asumir true por seguridad
                    bool requireConsent = data["require_consent"]?.Value<bool?>() ?? true;

                    if (requireConsent)
                    {
                        _state = RemoteViewSessionState.PendingConsent;
                    }
                    else
                    {
                        _state = RemoteViewSessionState.Active;
                    }
                }

                AlwaysPrintLogger.WriteTrayInfo(
                    $"RemoteViewSession: sesión iniciada. session_id={SessionId}, mode={Mode}, " +
                    $"resolution={Resolution}, quality={Quality}, monitor={MonitorIndex}, " +
                    $"viewport={ViewportWidth}x{ViewportHeight}, user={UserName}");

                // Determinar si se requiere consentimiento fuera del lock
                bool consentRequired = _state == RemoteViewSessionState.PendingConsent;

                if (consentRequired)
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"RemoteViewSession: esperando consentimiento del usuario. session_id={SessionId}");
                    OnConsentRequired?.Invoke();
                }
                else
                {
                    OnSessionStarted?.Invoke();
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"RemoteViewSession: error procesando remote_view_start. {ex.Message}");
            }
        }

        /// <summary>
        /// Procesa el mensaje remote_view_stop recibido por WebSocket.
        /// Limpia el estado de la sesión y quita el indicador visual.
        /// </summary>
        /// <param name="json">JSON completo del mensaje remote_view_stop.</param>
        public void HandleStop(string json)
        {
            try
            {
                var data = JObject.Parse(json);
                var reason = data["reason"]?.ToString() ?? "unknown";
                var stoppedSessionId = data["session_id"]?.ToString();

                lock (_lock)
                {
                    // Verificar que el stop corresponde a la sesión activa
                    if (stoppedSessionId != null && stoppedSessionId != SessionId)
                    {
                        AlwaysPrintLogger.WriteTrayWarning(
                            $"RemoteViewSession: remote_view_stop recibido para session_id={stoppedSessionId} " +
                            $"pero la sesión activa es {SessionId}. Ignorando.");
                        return;
                    }

                    _state = RemoteViewSessionState.Ended;
                }

                AlwaysPrintLogger.WriteTrayInfo(
                    $"RemoteViewSession: sesión finalizada. session_id={SessionId}, reason={reason}");

                OnSessionEnded?.Invoke();

                // Limpiar estado después de notificar
                ClearState();
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"RemoteViewSession: error procesando remote_view_stop. {ex.Message}");
            }
        }

        /// <summary>
        /// Procesa el mensaje remote_view_config recibido por WebSocket.
        /// Actualiza parámetros de captura en vivo sin reiniciar la sesión.
        /// </summary>
        /// <param name="json">JSON completo del mensaje remote_view_config.</param>
        public void HandleConfig(string json)
        {
            try
            {
                var data = JObject.Parse(json);
                var configSessionId = data["session_id"]?.ToString();

                lock (_lock)
                {
                    // Verificar que el config corresponde a la sesión activa
                    if (configSessionId != null && configSessionId != SessionId)
                    {
                        AlwaysPrintLogger.WriteTrayWarning(
                            $"RemoteViewSession: remote_view_config recibido para session_id={configSessionId} " +
                            $"pero la sesión activa es {SessionId}. Ignorando.");
                        return;
                    }

                    if (!IsActive)
                    {
                        AlwaysPrintLogger.WriteTrayWarning(
                            "RemoteViewSession: remote_view_config recibido pero no hay sesión activa. Ignorando.");
                        return;
                    }

                    // Actualizar solo los campos presentes en el mensaje (partial update)
                    // Usar Value<T?>() para manejar JTokenType.Null correctamente
                    if (data["resolution"] != null && data["resolution"].Type != JTokenType.Null)
                        Resolution = data["resolution"].ToString();
                    if (data["quality"] != null && data["quality"].Type != JTokenType.Null)
                        Quality = data["quality"].Value<int?>() ?? Quality;
                    if (data["monitor"] != null && data["monitor"].Type != JTokenType.Null)
                        MonitorIndex = data["monitor"].Value<int?>() ?? MonitorIndex;
                    if (data["fps"] != null && data["fps"].Type != JTokenType.Null)
                        Fps = data["fps"].Value<int?>() ?? Fps;
                    if (data["viewport_width"] != null && data["viewport_width"].Type != JTokenType.Null)
                        ViewportWidth = data["viewport_width"].Value<int?>() ?? ViewportWidth;
                    if (data["viewport_height"] != null && data["viewport_height"].Type != JTokenType.Null)
                        ViewportHeight = data["viewport_height"].Value<int?>() ?? ViewportHeight;
                    if (data["mode"] != null && data["mode"].Type != JTokenType.Null)
                        Mode = data["mode"].ToString();
                }

                AlwaysPrintLogger.WriteTrayInfo(
                    $"RemoteViewSession: configuración actualizada en vivo. " +
                    $"resolution={Resolution}, quality={Quality}, monitor={MonitorIndex}, " +
                    $"fps={Fps}, viewport={ViewportWidth}x{ViewportHeight}, mode={Mode}");

                OnConfigChanged?.Invoke();
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"RemoteViewSession: error procesando remote_view_config. {ex.Message}");
            }
        }

        /// <summary>
        /// Procesa el mensaje remote_view_pause (admin cambió de tab).
        /// Pausa la captura para ahorrar CPU y bandwidth.
        /// </summary>
        public void HandlePause()
        {
            lock (_lock)
            {
                if (_state != RemoteViewSessionState.Active)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"RemoteViewSession: pause recibido pero estado actual es {_state}. Ignorando.");
                    return;
                }

                _state = RemoteViewSessionState.Paused;
            }

            AlwaysPrintLogger.WriteTrayInfo(
                $"RemoteViewSession: sesión pausada. session_id={SessionId}");

            OnPauseChanged?.Invoke();
        }

        /// <summary>
        /// Procesa el mensaje remote_view_resume (admin volvió al tab).
        /// Reanuda la captura y envía un keyframe inmediato.
        /// </summary>
        public void HandleResume()
        {
            lock (_lock)
            {
                if (_state != RemoteViewSessionState.Paused)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"RemoteViewSession: resume recibido pero estado actual es {_state}. Ignorando.");
                    return;
                }

                _state = RemoteViewSessionState.Active;
            }

            AlwaysPrintLogger.WriteTrayInfo(
                $"RemoteViewSession: sesión reanudada. session_id={SessionId}");

            OnPauseChanged?.Invoke();
        }

        /// <summary>
        /// Finaliza la sesión programáticamente (ej: pérdida de conexión WebSocket).
        /// Equivale a recibir un remote_view_stop sin mensaje explícito.
        /// </summary>
        public void End()
        {
            lock (_lock)
            {
                if (_state == RemoteViewSessionState.Ended)
                    return;

                _state = RemoteViewSessionState.Ended;
            }

            AlwaysPrintLogger.WriteTrayInfo(
                $"RemoteViewSession: sesión finalizada programáticamente. session_id={SessionId}");

            OnSessionEnded?.Invoke();
            ClearState();
        }

        /// <summary>
        /// Acepta el consentimiento del usuario y transiciona de PendingConsent a Active.
        /// Solo tiene efecto si el estado actual es PendingConsent.
        /// </summary>
        public void AcceptConsent()
        {
            lock (_lock)
            {
                if (_state != RemoteViewSessionState.PendingConsent) return;
                _state = RemoteViewSessionState.Active;
            }
            AlwaysPrintLogger.WriteTrayInfo(
                $"RemoteViewSession: consentimiento aceptado. session_id={SessionId}");
            OnSessionStarted?.Invoke();
        }

        /// <summary>Último timestamp de viewer_alive recibido.</summary>
        public DateTime LastViewerAliveAt { get; private set; } = DateTime.UtcNow;

        /// <summary>
        /// Registra que el frontend viewer está activo.
        /// </summary>
        public void RecordViewerAlive()
        {
            LastViewerAliveAt = DateTime.UtcNow;
        }

        /// <summary>
        /// Limpia todos los campos de estado de la sesión.
        /// </summary>
        private void ClearState()
        {
            lock (_lock)
            {
                SessionId = null;
                Mode = null;
                Resolution = null;
                Quality = 0;
                MonitorIndex = 0;
                ViewportWidth = 0;
                ViewportHeight = 0;
                UserName = null;
                Fps = 0;
            }
        }
    }
}
