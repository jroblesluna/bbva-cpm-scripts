using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;
using System.Threading;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintTray.RemoteView
{
    /// <summary>
    /// Motor de streaming basado en tiles con detección de regiones sucias.
    /// Captura continuamente a N FPS, compara tiles con el frame anterior,
    /// y solo envía las regiones que cambiaron (delta encoding).
    /// Keyframe completo cada 5 segundos para sincronización.
    ///
    /// Protocolo:
    /// - Keyframe: rv_frame con frame_type="keyframe" (JPEG completo)
    /// - Delta: rv_frame con frame_type="delta" y array de tiles cambiados
    /// - Sin cambios: no envía nada (ahorro de bandwidth)
    ///
    /// Si más del 60% de tiles cambiaron, envía keyframe en vez de muchos tiles.
    /// Calidad: keyframe=70%, tiles=60% (tiles son temporales).
    /// </summary>
    public sealed class TileStreamEngine : IDisposable
    {
        // === Configuración ===
        private const int TILE_SIZE = 128;
        private const int KEYFRAME_INTERVAL_MS = 5000;
        private const int DEFAULT_FPS = 5;
        private const int DEFAULT_KEYFRAME_QUALITY = 70;
        private const int DEFAULT_TILE_QUALITY = 60;
        private const double KEYFRAME_THRESHOLD_RATIO = 0.60;

        // === Dependencias ===
        private readonly RemoteViewSession _session;
        private readonly ScreenCapturer _capturer;
        private readonly JpegEncoder _encoder;
        private readonly Action<string, object> _sendMessage;

        // === Hilo de captura ===
        private Thread? _captureThread;
        private CancellationTokenSource? _cts;
        private readonly ManualResetEventSlim _pauseGate;
        private readonly object _stateLock = new object();

        // === Estado ===
        private volatile bool _isRunning;
        private volatile bool _isPaused;
        private bool _disposed;

        // === FPS ===
        private int _targetFps;
        private long _targetIntervalTicks;

        // === Delta detection ===
        private uint[]? _previousTileHashes;
        private int _tileColumns;
        private int _tileRows;
        private int _totalTiles;
        private Stopwatch? _keyframeTimer;
        private bool _forceNextKeyframe;

        // === CRC32 lookup table ===
        private static readonly uint[] Crc32Table = GenerateCrc32Table();

        // === Estadísticas ===
        private long _totalKeyframesSent;
        private long _totalDeltaFramesSent;
        private long _totalSkippedFrames;

        // === Viewer alive tracking ===
        private DateTime _lastViewerAliveAt = DateTime.UtcNow;
        private const int VIEWER_PAUSE_TIMEOUT_SECONDS = 10;
        private const int VIEWER_END_TIMEOUT_SECONDS = 60;
        private bool _viewerPaused; // true = streaming pausado porque viewer no envió heartbeat

        /// <summary>Indica si el engine está corriendo.</summary>
        public bool IsRunning => _isRunning;

        /// <summary>Indica si está pausado.</summary>
        public bool IsPaused => _isPaused;

        /// <summary>FPS actual configurado.</summary>
        public int CurrentFps => _targetFps;

        /// <summary>Total de keyframes enviados.</summary>
        public long TotalKeyframesSent => Interlocked.Read(ref _totalKeyframesSent);

        /// <summary>Total de delta frames enviados.</summary>
        public long TotalDeltaFramesSent => Interlocked.Read(ref _totalDeltaFramesSent);

        /// <summary>Total de frames sin cambios (no enviados).</summary>
        public long TotalSkippedFrames => Interlocked.Read(ref _totalSkippedFrames);

        /// <summary>
        /// Crea una instancia del TileStreamEngine.
        /// </summary>
        /// <param name="session">Estado de la sesión (mode, params).</param>
        /// <param name="capturer">Capturador de pantalla GDI+.</param>
        /// <param name="encoder">Codificador JPEG.</param>
        /// <param name="sendMessage">Callback para enviar mensajes JSON: (type, payload).</param>
        public TileStreamEngine(
            RemoteViewSession session,
            ScreenCapturer capturer,
            JpegEncoder encoder,
            Action<string, object> sendMessage)
        {
            _session = session ?? throw new ArgumentNullException(nameof(session));
            _capturer = capturer ?? throw new ArgumentNullException(nameof(capturer));
            _encoder = encoder ?? throw new ArgumentNullException(nameof(encoder));
            _sendMessage = sendMessage ?? throw new ArgumentNullException(nameof(sendMessage));

            _pauseGate = new ManualResetEventSlim(true);
            _isRunning = false;
            _isPaused = false;
            _forceNextKeyframe = true; // Primer frame siempre es keyframe

            AlwaysPrintLogger.WriteTrayInfo("TileStreamEngine: instancia creada.");
        }

        /// <summary>
        /// Inicia el loop de captura continua con tile-based delta encoding.
        /// </summary>
        public void Start()
        {
            ThrowIfDisposed();

            lock (_stateLock)
            {
                if (_isRunning)
                    throw new InvalidOperationException(
                        "TileStreamEngine ya está corriendo. Llame Stop() primero.");

                _targetFps = _session.Fps > 0 ? _session.Fps : DEFAULT_FPS;
                _targetIntervalTicks = Stopwatch.Frequency / _targetFps;

                _isPaused = false;
                _forceNextKeyframe = true;
                _previousTileHashes = null; // Se inicializa en primer frame
                _totalKeyframesSent = 0;
                _totalDeltaFramesSent = 0;
                _totalSkippedFrames = 0;
                _lastViewerAliveAt = DateTime.UtcNow;
                _viewerPaused = false;
                _keyframeTimer = Stopwatch.StartNew();
                _pauseGate.Set();

                _cts = new CancellationTokenSource();

                _captureThread = new Thread(CaptureLoop)
                {
                    Name = "TileStreamEngine_CaptureLoop",
                    IsBackground = true,
                    Priority = ThreadPriority.AboveNormal
                };

                _isRunning = true;
                _captureThread.Start();
            }

            AlwaysPrintLogger.WriteTrayInfo(
                $"TileStreamEngine: iniciado. fps={_targetFps}, tile_size={TILE_SIZE}px, " +
                $"keyframe_interval={KEYFRAME_INTERVAL_MS}ms");
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
                _cts?.Cancel();
                _pauseGate.Set();
                threadToJoin = _captureThread;
            }

            if (threadToJoin != null && threadToJoin.IsAlive)
            {
                bool joined = threadToJoin.Join(TimeSpan.FromSeconds(5));
                if (!joined)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "TileStreamEngine: el hilo no terminó en 5s.");
                }
            }

            lock (_stateLock)
            {
                _cts?.Dispose();
                _cts = null;
                _captureThread = null;
                _isPaused = false;
                _keyframeTimer?.Stop();
            }

            AlwaysPrintLogger.WriteTrayInfo(
                $"TileStreamEngine: detenido. keyframes={Interlocked.Read(ref _totalKeyframesSent)}, " +
                $"deltas={Interlocked.Read(ref _totalDeltaFramesSent)}, " +
                $"skipped={Interlocked.Read(ref _totalSkippedFrames)}");
        }

        /// <summary>
        /// Pausa la captura (admin cambió de tab).
        /// </summary>
        public void Pause()
        {
            ThrowIfDisposed();

            lock (_stateLock)
            {
                if (!_isRunning || _isPaused)
                    return;

                _isPaused = true;
                _pauseGate.Reset();
            }

            AlwaysPrintLogger.WriteTrayInfo("TileStreamEngine: pausado.");
        }

        /// <summary>
        /// Reanuda la captura tras pausa. Envía keyframe inmediatamente.
        /// </summary>
        public void Resume()
        {
            ThrowIfDisposed();

            lock (_stateLock)
            {
                if (!_isRunning || !_isPaused)
                    return;

                _isPaused = false;
                _forceNextKeyframe = true;
                _pauseGate.Set();
            }

            AlwaysPrintLogger.WriteTrayInfo("TileStreamEngine: reanudado (keyframe forzado).");
        }

        /// <summary>
        /// Fuerza un keyframe en el próximo ciclo (cambio de monitor/resolución).
        /// </summary>
        public void ForceKeyframe()
        {
            _forceNextKeyframe = true;
            AlwaysPrintLogger.WriteTrayInfo("TileStreamEngine: keyframe forzado para próximo ciclo.");
        }

        /// <summary>
        /// Actualiza el FPS objetivo en runtime.
        /// </summary>
        public void UpdateFps(int fps)
        {
            ThrowIfDisposed();

            if (fps < 1) fps = 1;
            if (fps > 30) fps = 30;

            _targetFps = fps;
            _targetIntervalTicks = Stopwatch.Frequency / fps;

            AlwaysPrintLogger.WriteTrayInfo(
                $"TileStreamEngine: FPS actualizado a {fps}.");
        }

        /// <summary>
        /// Registra que el frontend viewer está activo (recibió rv_viewer_alive).
        /// Si el streaming estaba pausado por falta de heartbeat, lo reanuda.
        /// </summary>
        public void RecordViewerAlive()
        {
            _lastViewerAliveAt = DateTime.UtcNow;

            if (_viewerPaused)
            {
                _viewerPaused = false;
                _pauseGate.Set(); // Reanudar si estaba pausado por viewer timeout
                _forceNextKeyframe = true; // Enviar keyframe al reanudar
                AlwaysPrintLogger.WriteTrayInfo(
                    "TileStreamEngine: viewer reconectado, reanudando streaming.");
            }
        }

        /// <summary>
        /// Loop principal de captura con tile-based delta encoding.
        /// </summary>
        private void CaptureLoop()
        {
            var frameStopwatch = new Stopwatch();
            var token = _cts!.Token;

            AlwaysPrintLogger.WriteTrayInfo("TileStreamEngine: hilo de captura iniciado.");

            try
            {
                while (!token.IsCancellationRequested)
                {
                    if (!_pauseGate.Wait(1000, token))
                        continue;

                    if (token.IsCancellationRequested)
                        break;

                    // Verificar si el viewer sigue activo (heartbeat)
                    var secondsSinceViewerAlive = (DateTime.UtcNow - _lastViewerAliveAt).TotalSeconds;

                    if (secondsSinceViewerAlive > VIEWER_END_TIMEOUT_SECONDS)
                    {
                        // 60s sin heartbeat — cerrar sesión
                        AlwaysPrintLogger.WriteTrayInfo(
                            "TileStreamEngine: 60s sin heartbeat del viewer. Cerrando sesión.");
                        _session.End();
                        break; // Salir del loop
                    }

                    if (secondsSinceViewerAlive > VIEWER_PAUSE_TIMEOUT_SECONDS && !_viewerPaused)
                    {
                        // 10s sin heartbeat — pausar streaming
                        _viewerPaused = true;
                        AlwaysPrintLogger.WriteTrayInfo(
                            "TileStreamEngine: 10s sin heartbeat del viewer. Pausando streaming.");
                        _pauseGate.Reset(); // Bloquear el hilo hasta que llegue viewer_alive
                        continue; // Volver al inicio del loop (se bloqueará en el pauseGate.Wait)
                    }

                    frameStopwatch.Restart();

                    try
                    {
                        ProcessFrame();
                    }
                    catch (Exception ex)
                    {
                        AlwaysPrintLogger.WriteTrayWarning(
                            $"TileStreamEngine: error en frame. {ex.Message}");
                    }

                    WaitForNextFrame(frameStopwatch);
                }
            }
            catch (OperationCanceledException)
            {
                // Shutdown limpio
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"TileStreamEngine: error fatal en loop. {ex.Message}");
            }

            AlwaysPrintLogger.WriteTrayInfo("TileStreamEngine: hilo de captura finalizado.");
        }

        /// <summary>
        /// Procesa un frame: captura, decide keyframe o delta, envía.
        /// </summary>
        private void ProcessFrame()
        {
            // Resolver dimensiones de captura
            int targetWidth, targetHeight;
            ParseResolution(_session.Resolution, out targetWidth, out targetHeight);

            // Viewport-adaptive downscale
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
                frame = _capturer.Capture(_session.MonitorIndex, targetWidth, targetHeight);
                if (frame == null)
                    return;

                bool shouldKeyframe = _forceNextKeyframe
                    || _previousTileHashes == null
                    || (_keyframeTimer != null && _keyframeTimer.ElapsedMilliseconds >= KEYFRAME_INTERVAL_MS);

                if (shouldKeyframe)
                {
                    SendKeyframe(frame);
                    UpdateAllTileHashes(frame);
                    _forceNextKeyframe = false;
                    _keyframeTimer?.Restart();
                    Interlocked.Increment(ref _totalKeyframesSent);
                }
                else
                {
                    var dirtyTiles = DetectDirtyTiles(frame);

                    if (dirtyTiles.Count == 0)
                    {
                        // Pantalla sin cambios — no enviar nada
                        Interlocked.Increment(ref _totalSkippedFrames);
                    }
                    else if ((double)dirtyTiles.Count / _totalTiles > KEYFRAME_THRESHOLD_RATIO)
                    {
                        // Más del 60% de tiles cambiaron — keyframe es más eficiente
                        SendKeyframe(frame);
                        UpdateAllTileHashes(frame);
                        _keyframeTimer?.Restart();
                        Interlocked.Increment(ref _totalKeyframesSent);
                    }
                    else
                    {
                        SendDeltaFrame(dirtyTiles, frame.Width, frame.Height);
                        Interlocked.Increment(ref _totalDeltaFramesSent);
                    }
                }
            }
            finally
            {
                frame?.Dispose();
            }
        }

        /// <summary>
        /// Detecta tiles que cambiaron comparando CRC32 con el frame anterior.
        /// Actualiza los hashes de los tiles que cambiaron.
        /// </summary>
        private List<DirtyTile> DetectDirtyTiles(Bitmap frame)
        {
            var dirtyTiles = new List<DirtyTile>();

            // Asegurar que la grilla de tiles está dimensionada
            EnsureTileGrid(frame.Width, frame.Height);

            BitmapData? bitmapData = null;
            try
            {
                bitmapData = frame.LockBits(
                    new Rectangle(0, 0, frame.Width, frame.Height),
                    ImageLockMode.ReadOnly,
                    PixelFormat.Format32bppArgb);

                int stride = bitmapData.Stride;
                int bytesPerPixel = 4; // Format32bppArgb

                for (int row = 0; row < _tileRows; row++)
                {
                    for (int col = 0; col < _tileColumns; col++)
                    {
                        int tileIndex = row * _tileColumns + col;

                        int tileX = col * TILE_SIZE;
                        int tileY = row * TILE_SIZE;
                        int tileW = Math.Min(TILE_SIZE, frame.Width - tileX);
                        int tileH = Math.Min(TILE_SIZE, frame.Height - tileY);

                        // Calcular CRC32 de los píxeles de este tile
                        uint hash = ComputeTileCrc32(
                            bitmapData.Scan0, stride, bytesPerPixel,
                            tileX, tileY, tileW, tileH);

                        if (hash != _previousTileHashes![tileIndex])
                        {
                            _previousTileHashes[tileIndex] = hash;

                            // Extraer tile como JPEG
                            var tileRect = new Rectangle(tileX, tileY, tileW, tileH);
                            using (var tileBitmap = frame.Clone(tileRect, frame.PixelFormat))
                            {
                                byte[] tileJpeg = _encoder.Encode(tileBitmap, DEFAULT_TILE_QUALITY);
                                dirtyTiles.Add(new DirtyTile
                                {
                                    X = tileX,
                                    Y = tileY,
                                    Width = tileW,
                                    Height = tileH,
                                    Data = Convert.ToBase64String(tileJpeg)
                                });
                            }
                        }
                    }
                }
            }
            finally
            {
                if (bitmapData != null)
                    frame.UnlockBits(bitmapData);
            }

            return dirtyTiles;
        }

        /// <summary>
        /// Actualiza todos los hashes de tiles (después de enviar keyframe).
        /// </summary>
        private void UpdateAllTileHashes(Bitmap frame)
        {
            EnsureTileGrid(frame.Width, frame.Height);

            BitmapData? bitmapData = null;
            try
            {
                bitmapData = frame.LockBits(
                    new Rectangle(0, 0, frame.Width, frame.Height),
                    ImageLockMode.ReadOnly,
                    PixelFormat.Format32bppArgb);

                int stride = bitmapData.Stride;
                int bytesPerPixel = 4;

                for (int row = 0; row < _tileRows; row++)
                {
                    for (int col = 0; col < _tileColumns; col++)
                    {
                        int tileIndex = row * _tileColumns + col;
                        int tileX = col * TILE_SIZE;
                        int tileY = row * TILE_SIZE;
                        int tileW = Math.Min(TILE_SIZE, frame.Width - tileX);
                        int tileH = Math.Min(TILE_SIZE, frame.Height - tileY);

                        _previousTileHashes![tileIndex] = ComputeTileCrc32(
                            bitmapData.Scan0, stride, bytesPerPixel,
                            tileX, tileY, tileW, tileH);
                    }
                }
            }
            finally
            {
                if (bitmapData != null)
                    frame.UnlockBits(bitmapData);
            }
        }

        /// <summary>
        /// Asegura que la grilla de tiles está dimensionada para el frame actual.
        /// Si las dimensiones cambiaron, reinicializa la grilla y fuerza keyframe.
        /// </summary>
        private void EnsureTileGrid(int frameWidth, int frameHeight)
        {
            int cols = (frameWidth + TILE_SIZE - 1) / TILE_SIZE;
            int rows = (frameHeight + TILE_SIZE - 1) / TILE_SIZE;
            int total = cols * rows;

            if (_previousTileHashes == null || _tileColumns != cols || _tileRows != rows)
            {
                _tileColumns = cols;
                _tileRows = rows;
                _totalTiles = total;
                _previousTileHashes = new uint[total];
                // Inicializar con valor que garantice que el primer compare siempre detecta cambio
                for (int i = 0; i < total; i++)
                    _previousTileHashes[i] = uint.MaxValue;
            }
        }

        /// <summary>
        /// Calcula CRC32 de los píxeles de un tile específico dentro del bitmap.
        /// Accede directamente a la memoria del bitmap (unsafe-free via Marshal).
        /// </summary>
        private static uint ComputeTileCrc32(
            IntPtr scan0, int stride, int bytesPerPixel,
            int tileX, int tileY, int tileW, int tileH)
        {
            uint crc = 0xFFFFFFFF;
            int rowBytes = tileW * bytesPerPixel;

            for (int y = 0; y < tileH; y++)
            {
                int rowOffset = (tileY + y) * stride + tileX * bytesPerPixel;

                for (int x = 0; x < rowBytes; x++)
                {
                    byte b = Marshal.ReadByte(scan0, rowOffset + x);
                    crc = (crc >> 8) ^ Crc32Table[(crc ^ b) & 0xFF];
                }
            }

            return crc ^ 0xFFFFFFFF;
        }

        /// <summary>
        /// Genera la tabla de lookup CRC32 (estándar IEEE 802.3).
        /// </summary>
        private static uint[] GenerateCrc32Table()
        {
            uint[] table = new uint[256];
            for (uint i = 0; i < 256; i++)
            {
                uint crc = i;
                for (int j = 0; j < 8; j++)
                {
                    crc = (crc & 1) != 0 ? (crc >> 1) ^ 0xEDB88320u : crc >> 1;
                }
                table[i] = crc;
            }
            return table;
        }

        /// <summary>
        /// Envía un keyframe completo (JPEG del frame entero).
        /// </summary>
        private void SendKeyframe(Bitmap frame)
        {
            byte[] jpeg = _encoder.Encode(frame, DEFAULT_KEYFRAME_QUALITY);
            string base64 = Convert.ToBase64String(jpeg);

            var payload = new
            {
                session_id = _session.SessionId,
                frame_type = "keyframe",
                format = "jpeg",
                width = frame.Width,
                height = frame.Height,
                data = base64
            };

            _sendMessage("rv_frame", payload);
        }

        /// <summary>
        /// Envía un delta frame con solo los tiles que cambiaron.
        /// </summary>
        private void SendDeltaFrame(List<DirtyTile> dirtyTiles, int frameWidth, int frameHeight)
        {
            var tiles = new object[dirtyTiles.Count];
            for (int i = 0; i < dirtyTiles.Count; i++)
            {
                var t = dirtyTiles[i];
                tiles[i] = new
                {
                    x = t.X,
                    y = t.Y,
                    w = t.Width,
                    h = t.Height,
                    data = t.Data
                };
            }

            var payload = new
            {
                session_id = _session.SessionId,
                frame_type = "delta",
                format = "jpeg",
                width = frameWidth,
                height = frameHeight,
                tiles = tiles,
                changed_tiles = dirtyTiles.Count,
                total_tiles = _totalTiles
            };

            _sendMessage("rv_frame", payload);
        }

        /// <summary>
        /// Espera el tiempo restante del intervalo para mantener FPS objetivo.
        /// </summary>
        private void WaitForNextFrame(Stopwatch frameStopwatch)
        {
            long elapsed = frameStopwatch.ElapsedTicks;
            long remaining = _targetIntervalTicks - elapsed;

            if (remaining <= 0)
                return;

            double remainingMs = (double)remaining / Stopwatch.Frequency * 1000.0;

            if (remainingMs > 2.0)
            {
                Thread.Sleep((int)(remainingMs - 2.0));
            }

            while (frameStopwatch.ElapsedTicks < _targetIntervalTicks)
            {
                Thread.SpinWait(10);
            }
        }

        /// <summary>
        /// Parsea una resolución string a dimensiones.
        /// </summary>
        private static void ParseResolution(string? resolution, out int width, out int height)
        {
            switch (resolution?.ToLowerInvariant())
            {
                case "1080p":
                    width = 1920; height = 1080; break;
                case "720p":
                    width = 1280; height = 720; break;
                case "480p":
                    width = 854; height = 480; break;
                case "360p":
                    width = 640; height = 360; break;
                default:
                    if (resolution != null && resolution.Contains("x"))
                    {
                        var parts = resolution.Split('x');
                        if (parts.Length == 2 &&
                            int.TryParse(parts[0], out int w) &&
                            int.TryParse(parts[1], out int h))
                        {
                            width = w; height = h; return;
                        }
                    }
                    width = 1280; height = 720; break;
            }
        }

        private void ThrowIfDisposed()
        {
            if (_disposed)
                throw new ObjectDisposedException(nameof(TileStreamEngine));
        }

        public void Dispose()
        {
            Dispose(true);
            GC.SuppressFinalize(this);
        }

        private void Dispose(bool disposing)
        {
            if (_disposed)
                return;

            if (disposing)
            {
                if (_isRunning)
                {
                    try { Stop(); }
                    catch { /* Ignorar errores en dispose */ }
                }

                _pauseGate.Dispose();
                _cts?.Dispose();

                AlwaysPrintLogger.WriteTrayInfo("TileStreamEngine: recursos liberados.");
            }

            _disposed = true;
        }

        ~TileStreamEngine()
        {
            Dispose(false);
        }

        /// <summary>
        /// Estructura interna para un tile que cambió.
        /// </summary>
        private struct DirtyTile
        {
            public int X;
            public int Y;
            public int Width;
            public int Height;
            public string Data; // base64 JPEG
        }
    }
}
