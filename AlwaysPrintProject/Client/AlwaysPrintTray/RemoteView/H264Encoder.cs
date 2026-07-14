using System;
using System.Drawing;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintTray.RemoteView
{
    /// <summary>
    /// Codificador H.264 vía Windows Media Foundation para streaming de video remoto.
    /// Configurado con H.264 Baseline Profile para máxima compatibilidad con decodificadores.
    /// Output: raw NAL units (sin MP4 container) — listo para envío directo por WebSocket.
    ///
    /// NOTA: Implementación provisional usando JPEG. La codificación H.264 real vía
    /// Media Foundation se implementará cuando se agregue la dependencia MF.NET
    /// (MediaFoundation.NET o interop P/Invoke a mfplat.dll/mf.dll).
    ///
    /// Características del encoder:
    /// - Intenta hardware MFT primero (GPU), fallback a software MFT (CPU)
    /// - Baseline Profile Level 3.1 para compatibilidad universal
    /// - Fuerza keyframe (IDR) cada 2 segundos automáticamente
    /// - Resolución y bitrate cambiables en runtime sin recrear encoder
    ///
    /// Thread safety: no thread-safe — usar desde un solo hilo (el hilo del FrameStreamer).
    /// </summary>
    public class H264Encoder : IDisposable
    {
        // Parámetros actuales del encoder
        private int _width;
        private int _height;
        private int _fps;
        private int _bitrate;
        private bool _isInitialized;
        private bool _disposed;

        // Control de keyframes
        private int _framesSinceLastKeyframe;
        private bool _forceNextKeyframe;

        // Encoder JPEG provisional (placeholder hasta MF real)
        private readonly JpegEncoder _jpegEncoder;

        // Calidad JPEG del placeholder (simula bitrate variable)
        private const int PLACEHOLDER_QUALITY = 70;

        /// <summary>
        /// Ancho actual de codificación en píxeles.
        /// </summary>
        public int Width => _width;

        /// <summary>
        /// Alto actual de codificación en píxeles.
        /// </summary>
        public int Height => _height;

        /// <summary>
        /// Frames por segundo configurados.
        /// </summary>
        public int Fps => _fps;

        /// <summary>
        /// Bitrate actual en bits por segundo.
        /// </summary>
        public int Bitrate => _bitrate;

        /// <summary>
        /// Indica si el encoder usa aceleración por hardware (GPU).
        /// En la implementación provisional siempre retorna false.
        /// Con MF real: true si se encontró un MFT hardware, false si usa software.
        /// </summary>
        public bool IsHardwareAccelerated { get; private set; }

        /// <summary>
        /// Indica si el encoder fue inicializado correctamente.
        /// </summary>
        public bool IsInitialized => _isInitialized;

        /// <summary>
        /// Crea una instancia del H264Encoder.
        /// Requiere llamar a Initialize() antes de poder codificar frames.
        /// </summary>
        public H264Encoder()
        {
            _jpegEncoder = new JpegEncoder();
            _framesSinceLastKeyframe = 0;
            _forceNextKeyframe = true; // Primer frame siempre es keyframe
            IsHardwareAccelerated = false;

            AlwaysPrintLogger.WriteTrayInfo("H264Encoder: instancia creada (modo placeholder JPEG).");
        }

        /// <summary>
        /// Inicializa el encoder con los parámetros de codificación.
        /// En la implementación real, aquí se ejecutaría:
        ///   1. MFStartup(MF_VERSION)
        ///   2. MFTEnumEx para buscar H.264 encoders (hardware primero, luego software)
        ///   3. Configurar media type de entrada: MFVideoFormat_NV12, width, height, fps
        ///   4. Configurar media type de salida: MFVideoFormat_H264, Baseline Profile,
        ///      bitrate, keyframe interval
        ///   5. SetInputType + SetOutputType en el MFT
        ///   6. ProcessMessage(MFT_MESSAGE_NOTIFY_BEGIN_STREAMING)
        ///
        /// En la versión provisional, solo almacena los parámetros.
        /// </summary>
        /// <param name="width">Ancho de codificación en píxeles (mínimo 160).</param>
        /// <param name="height">Alto de codificación en píxeles (mínimo 120).</param>
        /// <param name="fps">Frames por segundo objetivo (1-30).</param>
        /// <param name="bitrate">Bitrate en bits por segundo (ej: 1_000_000 para 1 Mbps).</param>
        /// <exception cref="ArgumentException">Si los parámetros están fuera de rango.</exception>
        /// <exception cref="ObjectDisposedException">Si el encoder fue disposed.</exception>
        public void Initialize(int width, int height, int fps, int bitrate)
        {
            ThrowIfDisposed();
            ValidateParameters(width, height, fps, bitrate);

            _width = width;
            _height = height;
            _fps = fps;
            _bitrate = bitrate;
            _isInitialized = true;
            _framesSinceLastKeyframe = 0;
            _forceNextKeyframe = true;

            // TODO: Implementación real con Media Foundation:
            //   - MFStartup(MF_VERSION, MFSTARTUP_NOSOCKET)
            //   - Buscar encoder hardware: MFTEnumEx(MFT_CATEGORY_VIDEO_ENCODER,
            //     MFT_ENUM_FLAG_HARDWARE | MFT_ENUM_FLAG_SORTANDFILTER, inputType, outputType)
            //   - Si no hay hardware: MFTEnumEx con MFT_ENUM_FLAG_SYNCMFT | MFT_ENUM_FLAG_ASYNCMFT
            //   - Configurar output media type:
            //     * MF_MT_MAJOR_TYPE = MFMediaType_Video
            //     * MF_MT_SUBTYPE = MFVideoFormat_H264
            //     * MF_MT_AVG_BITRATE = bitrate
            //     * MF_MT_INTERLACE_MODE = MFVideoInterlace_Progressive
            //     * MF_MT_MPEG2_PROFILE = eAVEncH264VProfile_Base (Baseline)
            //     * MF_MT_MPEG2_LEVEL = eAVEncH264VLevel3_1
            //     * MFFrameRateToAverageTimePerFrame(fps, 1) → MF_MT_FRAME_RATE
            //     * MFSetAttributeSize → MF_MT_FRAME_SIZE = width × height
            //   - Configurar input media type:
            //     * MF_MT_SUBTYPE = MFVideoFormat_RGB32 (o NV12 si se usa GPU texture)
            //     * Mismos width, height, fps
            //   - SetOutputType(0, outputType, 0)
            //   - SetInputType(0, inputType, 0)
            //   - IsHardwareAccelerated = true si MFT_ENUM_FLAG_HARDWARE encontró encoder

            AlwaysPrintLogger.WriteTrayInfo(
                $"H264Encoder: inicializado {_width}x{_height} @ {_fps}fps, " +
                $"bitrate={_bitrate}bps, hw={IsHardwareAccelerated}, " +
                $"profile=Baseline (placeholder JPEG activo).");
        }

        /// <summary>
        /// Codifica un frame a H.264 NAL units (o JPEG en modo placeholder).
        ///
        /// En la implementación real con Media Foundation:
        ///   1. Convertir Bitmap a IMFMediaBuffer (copiar píxeles a buffer MF)
        ///   2. Crear IMFSample con el buffer + timestamp + duration
        ///   3. Si forceKeyframe: setear MFSampleExtension_CleanPoint = TRUE en el sample
        ///   4. ProcessInput(0, sample, 0)
        ///   5. ProcessOutput(0, outputDataBuffer, out status)
        ///   6. Extraer NAL units del output buffer (sin start codes Annex B si se desea)
        ///   7. Retornar raw NAL data
        ///
        /// En modo placeholder: codifica como JPEG y retorna esos bytes.
        /// </summary>
        /// <param name="frame">Bitmap del frame a codificar. No se modifica ni dispone.</param>
        /// <param name="forceKeyframe">Si true, este frame será un keyframe IDR.</param>
        /// <returns>Bytes codificados (NAL units H.264 o JPEG en modo placeholder).</returns>
        /// <exception cref="ArgumentNullException">Si frame es null.</exception>
        /// <exception cref="InvalidOperationException">Si el encoder no fue inicializado.</exception>
        /// <exception cref="ObjectDisposedException">Si el encoder fue disposed.</exception>
        public byte[] Encode(Bitmap frame, bool forceKeyframe = false)
        {
            ThrowIfDisposed();

            if (!_isInitialized)
                throw new InvalidOperationException(
                    "H264Encoder no inicializado. Llame a Initialize() primero.");

            if (frame == null)
                throw new ArgumentNullException(nameof(frame));

            // Determinar si este frame debe ser keyframe (IDR)
            bool isKeyframe = forceKeyframe || _forceNextKeyframe || ShouldForcePeriodicKeyframe();

            if (isKeyframe)
            {
                _framesSinceLastKeyframe = 0;
                _forceNextKeyframe = false;
            }
            else
            {
                _framesSinceLastKeyframe++;
            }

            // TODO: Implementación real con MF:
            //   - Crear IMFSample desde los píxeles del Bitmap
            //   - Si isKeyframe: sample.SetUINT32(MFSampleExtension_CleanPoint, 1)
            //   - ProcessInput → ProcessOutput → extraer NAL units
            //   - Retornar bytes del output buffer

            // Placeholder: codificar como JPEG
            var encoded = _jpegEncoder.Encode(frame, CalculatePlaceholderQuality());

            if (isKeyframe)
            {
                AlwaysPrintLogger.WriteTrayInfo(
                    $"H264Encoder: frame IDR (keyframe) codificado, " +
                    $"size={encoded.Length} bytes, {frame.Width}x{frame.Height}");
            }

            return encoded;
        }

        /// <summary>
        /// Reconfigura el encoder con nuevos parámetros sin recrear la instancia.
        /// Permite cambiar resolución y bitrate en runtime (Req 5.10).
        ///
        /// En la implementación real con Media Foundation:
        ///   1. Drain: ProcessMessage(MFT_MESSAGE_COMMAND_DRAIN)
        ///   2. Esperar que salgan los frames pendientes del pipeline
        ///   3. Flush: ProcessMessage(MFT_MESSAGE_COMMAND_FLUSH)
        ///   4. Reconfiguar output type con nuevos width/height/bitrate
        ///   5. Reconfigurar input type con nuevos width/height
        ///   6. ProcessMessage(MFT_MESSAGE_NOTIFY_BEGIN_STREAMING)
        ///   7. Forzar keyframe en el siguiente frame
        ///
        /// Si el MFT no soporta reconfiguración dinámica (raro pero posible):
        ///   - Destruir MFT actual y crear uno nuevo con los nuevos parámetros
        ///   - Siempre intentar reconfigurar primero antes de recrear
        /// </summary>
        /// <param name="width">Nuevo ancho en píxeles (mínimo 160).</param>
        /// <param name="height">Nuevo alto en píxeles (mínimo 120).</param>
        /// <param name="bitrate">Nuevo bitrate en bits por segundo.</param>
        /// <exception cref="ArgumentException">Si los parámetros están fuera de rango.</exception>
        /// <exception cref="InvalidOperationException">Si el encoder no fue inicializado.</exception>
        /// <exception cref="ObjectDisposedException">Si el encoder fue disposed.</exception>
        public void Reconfigure(int width, int height, int bitrate)
        {
            ThrowIfDisposed();

            if (!_isInitialized)
                throw new InvalidOperationException(
                    "H264Encoder no inicializado. Llame a Initialize() primero.");

            ValidateParameters(width, height, _fps, bitrate);

            var oldWidth = _width;
            var oldHeight = _height;
            var oldBitrate = _bitrate;

            _width = width;
            _height = height;
            _bitrate = bitrate;

            // Forzar keyframe tras reconfiguración para que el decoder pueda sincronizar
            _forceNextKeyframe = true;
            _framesSinceLastKeyframe = 0;

            AlwaysPrintLogger.WriteTrayInfo(
                $"H264Encoder: reconfigurado de {oldWidth}x{oldHeight}@{oldBitrate}bps " +
                $"a {_width}x{_height}@{_bitrate}bps. Próximo frame será IDR.");
        }

        /// <summary>
        /// Fuerza que el próximo frame codificado sea un keyframe IDR.
        /// Útil al cambiar de monitor, tras un pause/resume, o cuando el frontend
        /// solicita sincronización después de un error de decodificación.
        /// </summary>
        /// <exception cref="ObjectDisposedException">Si el encoder fue disposed.</exception>
        public void ForceKeyframe()
        {
            ThrowIfDisposed();

            _forceNextKeyframe = true;
            _framesSinceLastKeyframe = 0;

            AlwaysPrintLogger.WriteTrayInfo("H264Encoder: keyframe forzado para el próximo frame.");
        }

        /// <summary>
        /// Determina si se debe forzar un keyframe periódico.
        /// La política es: IDR cada 2 segundos = cada (fps * 2) frames.
        /// Esto garantiza que un cliente que se conecta a mitad de stream
        /// pueda comenzar a decodificar en máximo 2 segundos.
        /// </summary>
        /// <returns>True si se debe forzar keyframe por política periódica.</returns>
        private bool ShouldForcePeriodicKeyframe()
        {
            if (_fps <= 0)
                return true;

            int keyframeInterval = _fps * 2; // IDR cada 2 segundos
            return _framesSinceLastKeyframe >= keyframeInterval;
        }

        /// <summary>
        /// Calcula la calidad JPEG del placeholder basándose en el bitrate configurado.
        /// Simula el comportamiento de un encoder real donde más bitrate = mejor calidad.
        /// </summary>
        /// <returns>Calidad JPEG (30-90) proporcional al bitrate.</returns>
        private int CalculatePlaceholderQuality()
        {
            // Mapear bitrate a calidad JPEG:
            //   500 Kbps → quality 40
            //   1 Mbps   → quality 55
            //   2 Mbps   → quality 70
            //   4 Mbps   → quality 85
            //   8+ Mbps  → quality 90
            if (_bitrate <= 500_000) return 40;
            if (_bitrate <= 1_000_000) return 55;
            if (_bitrate <= 2_000_000) return 70;
            if (_bitrate <= 4_000_000) return 85;
            return 90;
        }

        /// <summary>
        /// Valida los parámetros de codificación.
        /// </summary>
        private void ValidateParameters(int width, int height, int fps, int bitrate)
        {
            if (width < 160)
                throw new ArgumentException(
                    $"Ancho mínimo es 160 píxeles, recibido: {width}", nameof(width));

            if (height < 120)
                throw new ArgumentException(
                    $"Alto mínimo es 120 píxeles, recibido: {height}", nameof(height));

            if (fps < 1 || fps > 30)
                throw new ArgumentException(
                    $"FPS debe estar entre 1 y 30, recibido: {fps}", nameof(fps));

            if (bitrate < 100_000)
                throw new ArgumentException(
                    $"Bitrate mínimo es 100,000 bps, recibido: {bitrate}", nameof(bitrate));
        }

        /// <summary>
        /// Lanza ObjectDisposedException si el encoder fue disposed.
        /// </summary>
        private void ThrowIfDisposed()
        {
            if (_disposed)
                throw new ObjectDisposedException(nameof(H264Encoder));
        }

        /// <summary>
        /// Libera recursos del encoder.
        /// En la implementación real:
        ///   - ProcessMessage(MFT_MESSAGE_NOTIFY_END_OF_STREAM)
        ///   - ProcessMessage(MFT_MESSAGE_COMMAND_DRAIN)
        ///   - Liberar IMFTransform (Release)
        ///   - Liberar media types
        ///   - MFShutdown()
        /// </summary>
        public void Dispose()
        {
            Dispose(true);
            GC.SuppressFinalize(this);
        }

        /// <summary>
        /// Patrón Dispose protegido para herencia futura.
        /// </summary>
        protected virtual void Dispose(bool disposing)
        {
            if (_disposed)
                return;

            if (disposing)
            {
                // TODO: Cuando MF esté implementado, liberar aquí:
                //   - IMFTransform → Release()
                //   - IMFMediaType (input/output) → Release()
                //   - IMFSample / IMFMediaBuffer pools
                //   - MFShutdown()

                _isInitialized = false;

                AlwaysPrintLogger.WriteTrayInfo(
                    "H264Encoder: recursos liberados (placeholder JPEG).");
            }

            _disposed = true;
        }

        /// <summary>
        /// Finalizer de seguridad (por si no se llama Dispose explícitamente).
        /// </summary>
        ~H264Encoder()
        {
            Dispose(false);
        }
    }
}
