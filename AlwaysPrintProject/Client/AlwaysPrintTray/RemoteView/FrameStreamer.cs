using System;
using System.Diagnostics;
using System.Drawing;
using System.Threading;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintTray.RemoteView
{
    /// <summary>
    /// Loop de captura continua de frames para Stream/Interactive mode.
    /// Captura → encode → envía a FPS configurado usando un hilo dedicado
    /// con timing preciso (Stopwatch, no Task.Delay/Thread.Sleep que derivan).
    ///
    /// Características:
    /// - Hilo dedicado (no ThreadPool) para timing preciso y sin starvation
    /// - ManualResetEventSlim para pause/resume sin spin-wait
    /// - CancellationTokenSource para shutdown limpio
    /// - Backpressure: monitorea buffer de WebSocket y reduce FPS/calidad si se acumula
    /// - Fuerza keyframe al reanudar tras pause
    ///
    /// Thread safety: Start/Stop/Pause/Resume son thread-safe.
    /// El loop de captura corre en su propio hilo dedicado.
    /// </summary>
    public class FrameStreamer : IDisposable
    {
        // === Dependencias inyectadas ===
        private readonly RemoteViewSession _session;
        private readonly DesktopDuplicator _capturer;
        private readonly H264Encoder _encoder;
        private readonly Action<byte[], bool> _sendFrame;

        // === Control del hilo de captura ===
        private Thread? _captureThread;
        private CancellationTokenSource? _cts;
        private readonly ManualResetEventSlim _pauseGate;
        private readonly object _stateLock = new object();

        // === Estado ===
        private volatile bool _isRunning;
        private volatile bool _isPaused;
        private volatile bool _forceKeyframeOnResume;
        private bool _disposed;

        // === Configuración de FPS ===
        private int _targetFps;
        private long _targetIntervalTicks; // Intervalo objetivo en ticks de Stopwatch

        // === Backpressure ===
        private Func<long>? _getPendingBytes;
        private int _originalFps;
        private int _consecutiveLowBufferFrames;
        private bool _fpsReduced;
        private bool _capturePausedByBackpressure;
        private DateTime _backpressurePauseUntil;

        // Umbrales de backpressure (bytes)
        private const long BACKPRESSURE_THRESHOLD_REDUCE = 1_048_576;    // 1 MB → reducir FPS
        private const long BACKPRESSURE_THRESHOLD_RESTORE = 262_144;     // 256 KB → restaurar FPS
        private const long BACKPRESSURE_THRESHOLD_CRITICAL = 3_145_728;  // 3 MB → pausar captura
        private const int CONSECUTIVE_LOW_FRAMES_TO_RESTORE = 5;
        private const int BACKPRESSURE_PAUSE_SECONDS = 5;

        // === Estadísticas ===
        private long _totalFramesCaptured;
        private long _totalFramesDropped;

        /// <summary>Indica si el streamer está corriendo (puede estar pausado).</summary>
        public bool IsRunning => _isRunning;

        /// <summary>Indica si el streamer está pausado (admin cambió de tab).</summary>
        public bool IsPaused => _isPaused;

        /// <summary>FPS actual configurado (puede estar reducido por backpressure).</summary>
        public int CurrentFps => _targetFps;

        /// <summary>Total de frames capturados y enviados desde el inicio.</summary>
        public long TotalFramesCaptured => Interlocked.Read(ref _totalFramesCaptured);

        /// <summary>Total de frames descartados por backpressure.</summary>
        public long TotalFramesDropped => Interlocked.Read(ref _totalFramesDropped);

        /// <summary>
        /// Crea una instancia del FrameStreamer.
        /// </summary>
        /// <param name="session">Estado de la sesión (mode, paused, params).</param>
        /// <param name="capturer">Capturador de pantalla (DDA o GDI fallback).</param>
        /// <param name="encoder">Codificador H.264 (o placeholder JPEG).</param>
        /// <param name="sendFrame">Callback para enviar frame: (encodedBytes, isKeyframe).</param>
        public FrameStreamer(
            RemoteViewSession session,
            DesktopDuplicator capturer,
            H264Encoder encoder,
            Action<byte[], bool> sendFrame)
        {
            _session = session ?? throw new ArgumentNullException(nameof(session));
            _capturer = capturer ?? throw new ArgumentNullException(nameof(capturer));
            _encoder = encoder ?? throw new ArgumentNullException(nameof(encoder));
            _sendFrame = sendFrame ?? throw new ArgumentNullException(nameof(sendFrame));

            _pauseGate = new ManualResetEventSlim(true); // Inicia en estado "no pausado"
            _isRunning = false;
            _isPaused = false;
            _forceKeyframeOnResume = false;

            AlwaysPrintLogger.WriteTrayInfo("FrameStreamer: instancia creada.");
        }

        /// <summary>
        /// Configura el delegado para monitoreo de backpressure.
        /// Debe llamarse antes de Start() si se desea backpressure.
        /// </summary>
        /// <param name="getPendingBytes">Función que retorna bytes pendientes en el buffer de WebSocket.</param>
        public void SetBackpressureMonitor(Func<long> getPendingBytes)
        {
            _getPendingBytes = getPendingBytes ?? throw new ArgumentNullException(nameof(getPendingBytes));

            AlwaysPrintLogger.WriteTrayInfo(
                "FrameStreamer: monitor de backpressure configurado.");
        }

        /// <summary>
        /// Inicia el loop de captura continua.
        /// Lanza un hilo dedicado que captura, codifica y envía frames al FPS configurado.
        /// </summary>
        /// <exception cref="InvalidOperationException">Si ya está corriendo.</exception>
        /// <exception cref="ObjectDisposedException">Si fue disposed.</exception>
        public void Start()
        {
            ThrowIfDisposed();

            lock (_stateLock)
            {
                if (_isRunning)
                    throw new InvalidOperationException(
                        "FrameStreamer ya está corriendo. Llame Stop() primero.");

                // Obtener FPS del session (configurado por org)
                _targetFps = _session.Fps > 0 ? _session.Fps : 5;
                _originalFps = _targetFps;
                _targetIntervalTicks = Stopwatch.Frequency / _targetFps;

                // Reset estado
                _isPaused = false;
                _forceKeyframeOnResume = false;
                _consecutiveLowBufferFrames = 0;
                _fpsReduced = false;
                _capturePausedByBackpressure = false;
                _totalFramesCaptured = 0;
                _totalFramesDropped = 0;
                _pauseGate.Set(); // Asegurar que no está pausado

                // Crear CancellationTokenSource para shutdown limpio
                _cts = new CancellationTokenSource();

                // Lanzar hilo dedicado (no ThreadPool para timing preciso)
                _captureThread = new Thread(CaptureLoop)
                {
                    Name = "FrameStreamer_CaptureLoop",
                    IsBackground = true,
                    Priority = ThreadPriority.AboveNormal
                };

                _isRunning = true;
                _captureThread.Start();
            }

            AlwaysPrintLogger.WriteTrayInfo(
                $"FrameStreamer: iniciado. fps={_targetFps}, " +
                $"intervalo={1000.0 / _targetFps:F1}ms, monitor={_session.MonitorIndex}");
        }

        /// <summary>
        /// Detiene el loop de captura y espera a que el hilo termine.
        /// </summary>
        public void Stop()
        {
            ThrowIfDisposed();

            Thread? threadToJoin = null;

            lock (_stateLock)
            {
                if (!_isRunning)
                    return;

                _isRunning = false;

                // Señalar cancelación
                _cts?.Cancel();

                // Desbloquear el gate por si está pausado (para que el hilo pueda salir)
                _pauseGate.Set();

                threadToJoin = _captureThread;
            }

            // Esperar a que el hilo termine (fuera del lock para evitar deadlock)
            if (threadToJoin != null && threadToJoin.IsAlive)
            {
                bool joined = threadToJoin.Join(TimeSpan.FromSeconds(5));
                if (!joined)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "FrameStreamer: el hilo de captura no terminó en 5s, forzando abort.");
                }
            }

            lock (_stateLock)
            {
                _cts?.Dispose();
                _cts = null;
                _captureThread = null;
                _isPaused = false;
            }

            AlwaysPrintLogger.WriteTrayInfo(
                $"FrameStreamer: detenido. frames_capturados={Interlocked.Read(ref _totalFramesCaptured)}, " +
                $"frames_descartados={Interlocked.Read(ref _totalFramesDropped)}");
        }

        /// <summary>
        /// Pausa la captura (admin cambió de tab). Deja de capturar para ahorrar CPU y ancho de banda.
        /// El hilo sigue vivo pero bloqueado en el ManualResetEventSlim.
        /// </summary>
        public void Pause()
        {
            ThrowIfDisposed();

            lock (_stateLock)
            {
                if (!_isRunning || _isPaused)
                    return;

                _isPaused = true;
                _forceKeyframeOnResume = true;
                _pauseGate.Reset(); // Bloquear el hilo de captura
            }

            AlwaysPrintLogger.WriteTrayInfo("FrameStreamer: pausado (admin cambió de tab).");
        }

        /// <summary>
        /// Reanuda la captura tras una pausa. Fuerza keyframe en el primer frame.
        /// </summary>
        public void Resume()
        {
            ThrowIfDisposed();

            lock (_stateLock)
            {
                if (!_isRunning || !_isPaused)
                    return;

                _isPaused = false;
                _pauseGate.Set(); // Desbloquear el hilo de captura
            }

            AlwaysPrintLogger.WriteTrayInfo("FrameStreamer: reanudado (admin volvió al tab).");
        }

        /// <summary>
        /// Actualiza el FPS objetivo en runtime (ej: cambio de config desde admin).
        /// </summary>
        /// <param name="newFps">Nuevo FPS objetivo (1-10).</param>
        public void UpdateFps(int newFps)
        {
            ThrowIfDisposed();

            if (newFps < 1) newFps = 1;
            if (newFps > 10) newFps = 10;

            _targetFps = newFps;
            _originalFps = newFps;
            _targetIntervalTicks = Stopwatch.Frequency / newFps;
            _fpsReduced = false;
            _consecutiveLowBufferFrames = 0;

            AlwaysPrintLogger.WriteTrayInfo(
                $"FrameStreamer: FPS actualizado a {newFps} (intervalo={1000.0 / newFps:F1}ms).");
        }

        /// <summary>
        /// Loop principal de captura. Corre en un hilo dedicado.
        /// Usa Stopwatch para timing preciso y SpinWait para espera activa corta.
        /// </summary>
        private void CaptureLoop()
        {
            var frameStopwatch = new Stopwatch();
            var token = _cts!.Token;

            AlwaysPrintLogger.WriteTrayInfo("FrameStreamer: hilo de captura iniciado.");

            try
            {
                while (!token.IsCancellationRequested)
                {
                    // Verificar pause gate (se bloquea si está pausado)
                    if (!_pauseGate.Wait(1000, token))
                    {
                        // Timeout en espera de resume o cancellation — re-evaluar
                        continue;
                    }

                    if (token.IsCancellationRequested)
                        break;

                    // Verificar pausa por backpressure crítica
                    if (_capturePausedByBackpressure)
                    {
                        if (DateTime.UtcNow < _backpressurePauseUntil)
                        {
                            // Esperar con sleep (no necesitamos precisión aquí)
                            Thread.Sleep(500);
                            continue;
                        }

                        // Tiempo de pausa expirado, reanudar
                        _capturePausedByBackpressure = false;
                        AlwaysPrintLogger.WriteTrayInfo(
                            "FrameStreamer: pausa por backpressure crítica finalizada, reanudando captura.");
                    }

                    // Iniciar medición del frame
                    frameStopwatch.Restart();

                    // Evaluar backpressure antes de capturar
                    if (!EvaluateBackpressure())
                    {
                        // Frame descartado por backpressure
                        Interlocked.Increment(ref _totalFramesDropped);
                        WaitForNextFrame(frameStopwatch);
                        continue;
                    }

                    // === Captura → Encode → Envía ===
                    try
                    {
                        CaptureEncodeAndSend();
                    }
                    catch (Exception ex)
                    {
                        AlwaysPrintLogger.WriteTrayWarning(
                            $"FrameStreamer: error en captura/encode/envío. {ex.Message}");
                    }

                    // Esperar el tiempo restante para mantener FPS objetivo
                    WaitForNextFrame(frameStopwatch);
                }
            }
            catch (OperationCanceledException)
            {
                // Shutdown limpio — esperado
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"FrameStreamer: error fatal en loop de captura. {ex.Message}");
            }

            AlwaysPrintLogger.WriteTrayInfo("FrameStreamer: hilo de captura finalizado.");
        }

        /// <summary>
        /// Captura un frame, lo codifica y lo envía vía el callback.
        /// </summary>
        private void CaptureEncodeAndSend()
        {
            // Determinar si necesitamos keyframe
            bool forceKeyframe = false;
            if (_forceKeyframeOnResume)
            {
                forceKeyframe = true;
                _forceKeyframeOnResume = false;
            }

            // Obtener dimensiones de captura desde la sesión
            int targetWidth = 0;
            int targetHeight = 0;
            ParseResolution(_session.Resolution, out targetWidth, out targetHeight);

            // Viewport-adaptive downscale: usar viewport si es menor que captura
            if (_session.ViewportWidth > 0 && _session.ViewportHeight > 0)
            {
                if (_session.ViewportWidth < targetWidth && targetWidth > 0)
                {
                    targetWidth = _session.ViewportWidth;
                    targetHeight = _session.ViewportHeight;
                }
            }

            // Capturar frame
            Bitmap? frame = null;
            try
            {
                frame = _capturer.CaptureFrame(_session.MonitorIndex, targetWidth, targetHeight);

                if (frame == null)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "FrameStreamer: CaptureFrame retornó null, saltando frame.");
                    return;
                }

                // Codificar frame
                byte[] encoded = _encoder.Encode(frame, forceKeyframe);

                if (encoded == null || encoded.Length == 0)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "FrameStreamer: Encode retornó vacío, saltando frame.");
                    return;
                }

                // Enviar frame vía callback (fire-and-forget desde perspectiva del streamer)
                _sendFrame(encoded, forceKeyframe);

                Interlocked.Increment(ref _totalFramesCaptured);
            }
            finally
            {
                frame?.Dispose();
            }
        }

        /// <summary>
        /// Evalúa el estado del buffer de WebSocket para backpressure.
        /// Retorna true si se puede capturar, false si debe saltarse el frame.
        /// </summary>
        /// <returns>True si se puede proceder con la captura.</returns>
        private bool EvaluateBackpressure()
        {
            if (_getPendingBytes == null)
                return true; // Sin monitor de backpressure → siempre capturar

            long pendingBytes;
            try
            {
                pendingBytes = _getPendingBytes();
            }
            catch
            {
                // Si falla la consulta, continuar normalmente
                return true;
            }

            // === Crítico: buffer > 3 MB → pausar captura 5 segundos ===
            if (pendingBytes > BACKPRESSURE_THRESHOLD_CRITICAL)
            {
                _capturePausedByBackpressure = true;
                _backpressurePauseUntil = DateTime.UtcNow.AddSeconds(BACKPRESSURE_PAUSE_SECONDS);

                AlwaysPrintLogger.WriteTrayWarning(
                    $"FrameStreamer: buffer crítico ({pendingBytes / 1024}KB > 3MB), " +
                    $"pausando captura por {BACKPRESSURE_PAUSE_SECONDS}s.");
                return false;
            }

            // === Alto: buffer > 1 MB → reducir FPS a la mitad ===
            if (pendingBytes > BACKPRESSURE_THRESHOLD_REDUCE)
            {
                if (!_fpsReduced)
                {
                    int reducedFps = Math.Max(1, _targetFps / 2);
                    _targetFps = reducedFps;
                    _targetIntervalTicks = Stopwatch.Frequency / reducedFps;
                    _fpsReduced = true;
                    _consecutiveLowBufferFrames = 0;

                    AlwaysPrintLogger.WriteTrayWarning(
                        $"FrameStreamer: backpressure detectado ({pendingBytes / 1024}KB > 1MB), " +
                        $"reduciendo FPS de {_originalFps} a {reducedFps}.");
                }
                return true; // Sigue capturando pero más lento
            }

            // === Bajo: buffer < 256 KB por 5 frames consecutivos → restaurar FPS ===
            if (pendingBytes < BACKPRESSURE_THRESHOLD_RESTORE)
            {
                _consecutiveLowBufferFrames++;

                if (_fpsReduced && _consecutiveLowBufferFrames >= CONSECUTIVE_LOW_FRAMES_TO_RESTORE)
                {
                    _targetFps = _originalFps;
                    _targetIntervalTicks = Stopwatch.Frequency / _originalFps;
                    _fpsReduced = false;
                    _consecutiveLowBufferFrames = 0;

                    AlwaysPrintLogger.WriteTrayInfo(
                        $"FrameStreamer: buffer drenado ({pendingBytes / 1024}KB < 256KB), " +
                        $"restaurando FPS a {_originalFps}.");
                }
            }
            else
            {
                // Buffer entre 256KB y 1MB — resetear contador de consecutivos
                _consecutiveLowBufferFrames = 0;
            }

            return true;
        }

        /// <summary>
        /// Espera el tiempo restante del intervalo del frame usando timing preciso.
        /// Usa SpinWait para los últimos microsegundos (precisión sub-milisegundo).
        /// Para esperas largas usa Thread.Sleep(1) para no saturar CPU.
        /// </summary>
        /// <param name="frameStopwatch">Stopwatch iniciado al comienzo del frame.</param>
        private void WaitForNextFrame(Stopwatch frameStopwatch)
        {
            long elapsed = frameStopwatch.ElapsedTicks;
            long remaining = _targetIntervalTicks - elapsed;

            if (remaining <= 0)
                return; // Frame tomó más tiempo que el intervalo — no esperar

            // Convertir a milisegundos para la parte gruesa del sleep
            double remainingMs = (double)remaining / Stopwatch.Frequency * 1000.0;

            // Sleep grueso: dormir la mayor parte del tiempo (dejar 2ms para spin-wait)
            if (remainingMs > 2.0)
            {
                Thread.Sleep((int)(remainingMs - 2.0));
            }

            // Spin-wait fino: los últimos ~2ms para precisión
            while (frameStopwatch.ElapsedTicks < _targetIntervalTicks)
            {
                Thread.SpinWait(10);
            }
        }

        /// <summary>
        /// Parsea una resolución string (ej: "720p", "1080p", "480p") a dimensiones.
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
                    // Default: resolución nativa (0 = sin escalar)
                    width = 0;
                    height = 0;
                    break;
            }
        }

        /// <summary>
        /// Lanza ObjectDisposedException si el streamer fue disposed.
        /// </summary>
        private void ThrowIfDisposed()
        {
            if (_disposed)
                throw new ObjectDisposedException(nameof(FrameStreamer));
        }

        /// <summary>
        /// Libera recursos del streamer. Detiene el loop si está corriendo.
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
                // Detener el loop si está corriendo
                if (_isRunning)
                {
                    try { Stop(); }
                    catch { /* Ignorar errores en dispose */ }
                }

                _pauseGate.Dispose();
                _cts?.Dispose();

                AlwaysPrintLogger.WriteTrayInfo("FrameStreamer: recursos liberados.");
            }

            _disposed = true;
        }

        /// <summary>
        /// Finalizer de seguridad.
        /// </summary>
        ~FrameStreamer()
        {
            Dispose(false);
        }
    }
}
