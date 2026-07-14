using System;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintTray.RemoteView
{
    /// <summary>
    /// Orquestador que conecta los eventos de RemoteViewSession con la reconfiguración
    /// de los componentes de captura/encoding/streaming.
    ///
    /// Responsabilidades:
    /// - Suscribirse a OnConfigChanged → reconfigura H264Encoder y FrameStreamer según lo que cambió
    /// - Suscribirse a OnPauseChanged → pausa/reanuda el FrameStreamer
    /// - Suscribirse a OnSessionStarted/OnSessionEnded → gestiona ciclo de vida del streamer
    ///
    /// Nota: DesktopDuplicator NO requiere reinicialización al cambiar de monitor,
    /// ya que recibe monitorIndex por frame desde la sesión (leído en FrameStreamer).
    ///
    /// Thread safety: los eventos pueden dispararse desde el hilo del WebSocket.
    /// Las operaciones delegadas (Reconfigure, UpdateFps, etc.) son thread-safe en sus respectivas clases.
    ///
    /// Requirements: 5.8, 5.9, 5.10, 8.3
    /// </summary>
    public class StreamController : IDisposable
    {
        private readonly RemoteViewSession _session;
        private readonly DesktopDuplicator _capturer;
        private readonly H264Encoder _encoder;
        private readonly FrameStreamer _streamer;
        private bool _disposed;

        // Estado previo para detectar qué cambió
        private string? _previousResolution;
        private int _previousMonitorIndex;
        private int _previousFps;
        private int _previousQuality;

        /// <summary>
        /// Crea una instancia del StreamController y suscribe a los eventos de la sesión.
        /// </summary>
        /// <param name="session">Estado de la sesión remota.</param>
        /// <param name="capturer">Capturador de pantalla (DDA/GDI).</param>
        /// <param name="encoder">Codificador H.264.</param>
        /// <param name="streamer">Loop de captura y envío de frames.</param>
        public StreamController(
            RemoteViewSession session,
            DesktopDuplicator capturer,
            H264Encoder encoder,
            FrameStreamer streamer)
        {
            _session = session ?? throw new ArgumentNullException(nameof(session));
            _capturer = capturer ?? throw new ArgumentNullException(nameof(capturer));
            _encoder = encoder ?? throw new ArgumentNullException(nameof(encoder));
            _streamer = streamer ?? throw new ArgumentNullException(nameof(streamer));

            // Suscribir a eventos de la sesión
            _session.OnConfigChanged += HandleConfigChanged;
            _session.OnPauseChanged += HandlePauseChanged;
            _session.OnSessionStarted += HandleSessionStarted;
            _session.OnSessionEnded += HandleSessionEnded;

            AlwaysPrintLogger.WriteTrayInfo("StreamController: instancia creada y eventos suscritos.");
        }

        /// <summary>
        /// Handler de cambio de configuración en vivo (monitor, resolución, fps, quality).
        /// Compara con estado previo para aplicar solo los cambios necesarios.
        /// </summary>
        private void HandleConfigChanged()
        {
            try
            {
                bool monitorChanged = _session.MonitorIndex != _previousMonitorIndex;
                bool resolutionChanged = _session.Resolution != _previousResolution;
                bool fpsChanged = _session.Fps != _previousFps && _session.Fps > 0;
                bool qualityChanged = _session.Quality != _previousQuality;

                // === Cambio de monitor ===
                // DesktopDuplicator no necesita reinicialización: recibe monitorIndex por frame
                // desde RemoteViewSession (leído por FrameStreamer.CaptureEncodeAndSend).
                // Solo forzamos keyframe para que el frontend sincronice inmediatamente.
                if (monitorChanged)
                {
                    _encoder.ForceKeyframe();
                    _previousMonitorIndex = _session.MonitorIndex;

                    AlwaysPrintLogger.WriteTrayInfo(
                        $"StreamController: monitor cambiado a {_session.MonitorIndex}. " +
                        "Keyframe forzado para sincronización.");
                }

                // === Cambio de resolución o calidad → reconfigurar encoder ===
                if (resolutionChanged || qualityChanged)
                {
                    int width, height;
                    ParseResolution(_session.Resolution, out width, out height);

                    if (width > 0 && height > 0)
                    {
                        // Calcular bitrate basado en calidad (mapeo simple)
                        int bitrate = CalculateBitrate(width, height, _session.Quality);

                        _encoder.Reconfigure(width, height, bitrate);

                        AlwaysPrintLogger.WriteTrayInfo(
                            $"StreamController: encoder reconfigurado. " +
                            $"resolución={width}x{height}, quality={_session.Quality}, " +
                            $"bitrate={bitrate}bps. Keyframe forzado automáticamente por Reconfigure.");
                    }

                    _previousResolution = _session.Resolution;
                    _previousQuality = _session.Quality;
                }

                // === Cambio de FPS → actualizar FrameStreamer ===
                if (fpsChanged)
                {
                    _streamer.UpdateFps(_session.Fps);
                    _previousFps = _session.Fps;

                    AlwaysPrintLogger.WriteTrayInfo(
                        $"StreamController: FPS actualizado a {_session.Fps}.");
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"StreamController: error procesando cambio de configuración. {ex.Message}");
            }
        }

        /// <summary>
        /// Handler de cambio de pausa (admin cambió de tab o volvió).
        /// Pausa o reanuda el FrameStreamer según el estado actual de la sesión.
        /// </summary>
        private void HandlePauseChanged()
        {
            try
            {
                if (_session.IsPaused)
                {
                    _streamer.Pause();
                    AlwaysPrintLogger.WriteTrayInfo(
                        "StreamController: streamer pausado (admin cambió de tab).");
                }
                else
                {
                    _streamer.Resume();
                    AlwaysPrintLogger.WriteTrayInfo(
                        "StreamController: streamer reanudado (admin volvió al tab).");
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"StreamController: error en cambio de pausa. {ex.Message}");
            }
        }

        /// <summary>
        /// Handler de inicio de sesión. Captura el estado inicial para comparación.
        /// </summary>
        private void HandleSessionStarted()
        {
            try
            {
                _previousResolution = _session.Resolution;
                _previousMonitorIndex = _session.MonitorIndex;
                _previousFps = _session.Fps;
                _previousQuality = _session.Quality;

                AlwaysPrintLogger.WriteTrayInfo(
                    $"StreamController: sesión iniciada. Estado inicial capturado: " +
                    $"resolution={_previousResolution}, monitor={_previousMonitorIndex}, " +
                    $"fps={_previousFps}, quality={_previousQuality}.");
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"StreamController: error en inicio de sesión. {ex.Message}");
            }
        }

        /// <summary>
        /// Handler de fin de sesión. Limpia estado previo.
        /// </summary>
        private void HandleSessionEnded()
        {
            try
            {
                _previousResolution = null;
                _previousMonitorIndex = 0;
                _previousFps = 0;
                _previousQuality = 0;

                AlwaysPrintLogger.WriteTrayInfo(
                    "StreamController: sesión finalizada. Estado previo limpiado.");
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"StreamController: error en fin de sesión. {ex.Message}");
            }
        }

        /// <summary>
        /// Parsea una resolución string a dimensiones (misma lógica que FrameStreamer).
        /// </summary>
        private void ParseResolution(string? resolution, out int width, out int height)
        {
            switch (resolution?.ToLowerInvariant())
            {
                case "1080p":
                    width = 1920;
                    height = 1080;
                    break;
                case "720p":
                    width = 1280;
                    height = 720;
                    break;
                case "480p":
                    width = 854;
                    height = 480;
                    break;
                case "360p":
                    width = 640;
                    height = 360;
                    break;
                default:
                    // Intentar parsear formato "WxH" (ej: "1280x720")
                    if (resolution != null && resolution.Contains("x"))
                    {
                        var parts = resolution.Split('x');
                        if (parts.Length == 2 &&
                            int.TryParse(parts[0], out int w) &&
                            int.TryParse(parts[1], out int h))
                        {
                            width = w;
                            height = h;
                            return;
                        }
                    }
                    // Default: no reconfigurar (0 = resolución nativa)
                    width = 0;
                    height = 0;
                    break;
            }
        }

        /// <summary>
        /// Calcula el bitrate apropiado basándose en resolución y calidad.
        /// Fórmula: (width × height × fps_base × factor_calidad) / 100
        /// Donde fps_base=5 y factor_calidad mapea quality (1-100) a un multiplicador.
        /// </summary>
        private int CalculateBitrate(int width, int height, int quality)
        {
            // Bitrate base por resolución (a calidad 70%)
            //   1080p → ~2 Mbps
            //   720p  → ~1 Mbps
            //   480p  → ~500 Kbps
            //   360p  → ~300 Kbps
            long pixels = (long)width * height;

            // Base: 1 bit por píxel por frame a 5fps ≈ referencia razonable
            // Ajustar por factor de calidad (50-100% → 0.5-1.5x)
            double qualityFactor = 0.5 + (quality / 100.0);
            int bitrate = (int)(pixels * qualityFactor);

            // Clamping a rangos razonables
            if (bitrate < 200_000) bitrate = 200_000;       // Mínimo 200 Kbps
            if (bitrate > 8_000_000) bitrate = 8_000_000;   // Máximo 8 Mbps

            return bitrate;
        }

        /// <summary>
        /// Libera recursos y desuscribe de los eventos de la sesión.
        /// </summary>
        public void Dispose()
        {
            Dispose(true);
            GC.SuppressFinalize(this);
        }

        /// <summary>
        /// Patrón Dispose protegido.
        /// </summary>
        protected virtual void Dispose(bool disposing)
        {
            if (_disposed)
                return;

            if (disposing)
            {
                // Desuscribir de todos los eventos
                _session.OnConfigChanged -= HandleConfigChanged;
                _session.OnPauseChanged -= HandlePauseChanged;
                _session.OnSessionStarted -= HandleSessionStarted;
                _session.OnSessionEnded -= HandleSessionEnded;

                AlwaysPrintLogger.WriteTrayInfo("StreamController: recursos liberados y eventos desuscritos.");
            }

            _disposed = true;
        }

        /// <summary>
        /// Finalizer de seguridad.
        /// </summary>
        ~StreamController()
        {
            Dispose(false);
        }
    }
}
