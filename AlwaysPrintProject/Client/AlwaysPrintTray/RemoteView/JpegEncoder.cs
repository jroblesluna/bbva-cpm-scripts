using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintTray.RemoteView
{
    /// <summary>
    /// Codifica Bitmaps a JPEG con calidad configurable (1-100%).
    /// Soporta viewport-adaptive downscale: si el viewport del admin es menor
    /// que la resolución de captura, escala el bitmap antes de encodear (Req 4.4).
    /// Nunca hace upscale — si el viewport es mayor que el bitmap, encodea al tamaño original.
    /// </summary>
    public class JpegEncoder
    {
        /// <summary>
        /// Codec JPEG cacheado para evitar buscarlo en cada frame.
        /// </summary>
        private readonly ImageCodecInfo _jpegCodec;

        /// <summary>
        /// Inicializa el encoder localizando el codec JPEG del sistema.
        /// </summary>
        /// <exception cref="InvalidOperationException">Si el codec JPEG no está disponible.</exception>
        public JpegEncoder()
        {
            _jpegCodec = GetJpegCodec();

            AlwaysPrintLogger.WriteTrayInfo("JpegEncoder: inicializado correctamente.");
        }

        /// <summary>
        /// Codifica un Bitmap a JPEG con la calidad especificada.
        /// No modifica el bitmap de entrada (no hace dispose).
        /// </summary>
        /// <param name="bitmap">Bitmap fuente a codificar.</param>
        /// <param name="quality">Calidad JPEG (1-100). Se clampea al rango válido.</param>
        /// <returns>Array de bytes con la imagen JPEG codificada.</returns>
        /// <exception cref="ArgumentNullException">Si bitmap es null.</exception>
        public byte[] Encode(Bitmap bitmap, int quality)
        {
            if (bitmap == null)
                throw new ArgumentNullException(nameof(bitmap));

            // Clampear calidad al rango válido (1-100)
            quality = ClampQuality(quality);

            try
            {
                using (var stream = new MemoryStream())
                {
                    var encoderParams = CreateEncoderParams(quality);
                    bitmap.Save(stream, _jpegCodec, encoderParams);

                    var result = stream.ToArray();

                    AlwaysPrintLogger.WriteTrayInfo(
                        $"JpegEncoder: codificado {bitmap.Width}x{bitmap.Height} " +
                        $"quality={quality}%, size={result.Length} bytes");

                    return result;
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"JpegEncoder: error codificando bitmap {bitmap.Width}x{bitmap.Height} " +
                    $"quality={quality}%. {ex.Message}");
                throw;
            }
        }

        /// <summary>
        /// Codifica un Bitmap a JPEG con viewport-adaptive downscale.
        /// Si el viewport es menor que el bitmap, escala primero al tamaño del viewport
        /// respetando el aspect ratio. Nunca hace upscale.
        /// </summary>
        /// <param name="bitmap">Bitmap fuente a codificar.</param>
        /// <param name="quality">Calidad JPEG (1-100). Se clampea al rango válido.</param>
        /// <param name="viewportWidth">Ancho del viewport del admin en píxeles (0 = sin adaptive).</param>
        /// <param name="viewportHeight">Alto del viewport del admin en píxeles (0 = sin adaptive).</param>
        /// <returns>Array de bytes con la imagen JPEG codificada.</returns>
        /// <exception cref="ArgumentNullException">Si bitmap es null.</exception>
        public byte[] EncodeWithViewportAdaptive(Bitmap bitmap, int quality, int viewportWidth, int viewportHeight)
        {
            if (bitmap == null)
                throw new ArgumentNullException(nameof(bitmap));

            // Si viewport no es válido o no requiere downscale, encodear directamente
            if (viewportWidth <= 0 || viewportHeight <= 0)
            {
                return Encode(bitmap, quality);
            }

            // Nunca upscale: si viewport >= bitmap en ambas dimensiones, encodear sin escalar
            if (viewportWidth >= bitmap.Width && viewportHeight >= bitmap.Height)
            {
                AlwaysPrintLogger.WriteTrayInfo(
                    $"JpegEncoder: viewport ({viewportWidth}x{viewportHeight}) >= bitmap " +
                    $"({bitmap.Width}x{bitmap.Height}), sin downscale.");
                return Encode(bitmap, quality);
            }

            // Calcular dimensiones finales respetando aspect ratio
            var (targetWidth, targetHeight) = CalculateScaledDimensions(
                bitmap.Width, bitmap.Height, viewportWidth, viewportHeight);

            // Si las dimensiones calculadas no requieren escalar, encodear directo
            if (targetWidth >= bitmap.Width && targetHeight >= bitmap.Height)
            {
                return Encode(bitmap, quality);
            }

            // Escalar y encodear
            Bitmap scaledBitmap = null;
            try
            {
                scaledBitmap = ScaleBitmap(bitmap, targetWidth, targetHeight);

                AlwaysPrintLogger.WriteTrayInfo(
                    $"JpegEncoder: viewport-adaptive downscale de {bitmap.Width}x{bitmap.Height} " +
                    $"a {targetWidth}x{targetHeight} (viewport={viewportWidth}x{viewportHeight})");

                return Encode(scaledBitmap, quality);
            }
            finally
            {
                scaledBitmap?.Dispose();
            }
        }

        /// <summary>
        /// Calcula las dimensiones de destino respetando aspect ratio del bitmap fuente.
        /// Ajusta al viewport sin exceder ninguna dimensión (fit within).
        /// </summary>
        /// <param name="sourceWidth">Ancho del bitmap fuente.</param>
        /// <param name="sourceHeight">Alto del bitmap fuente.</param>
        /// <param name="maxWidth">Ancho máximo permitido (viewport).</param>
        /// <param name="maxHeight">Alto máximo permitido (viewport).</param>
        /// <returns>Tupla (width, height) con las dimensiones calculadas.</returns>
        private (int width, int height) CalculateScaledDimensions(
            int sourceWidth, int sourceHeight, int maxWidth, int maxHeight)
        {
            double ratioW = (double)maxWidth / sourceWidth;
            double ratioH = (double)maxHeight / sourceHeight;

            // Usar el ratio más pequeño para que quepa en ambas dimensiones
            double ratio = Math.Min(ratioW, ratioH);

            // Nunca upscale
            if (ratio >= 1.0)
                return (sourceWidth, sourceHeight);

            int targetWidth = Math.Max(1, (int)Math.Round(sourceWidth * ratio));
            int targetHeight = Math.Max(1, (int)Math.Round(sourceHeight * ratio));

            return (targetWidth, targetHeight);
        }

        /// <summary>
        /// Escala un Bitmap al tamaño indicado usando interpolación bicúbica de alta calidad.
        /// Misma configuración de calidad que ScreenCapturer para consistencia visual.
        /// </summary>
        /// <param name="source">Bitmap fuente a escalar.</param>
        /// <param name="width">Ancho destino en píxeles.</param>
        /// <param name="height">Alto destino en píxeles.</param>
        /// <returns>Nuevo Bitmap escalado. El caller debe hacer Dispose().</returns>
        private Bitmap ScaleBitmap(Bitmap source, int width, int height)
        {
            var scaled = new Bitmap(width, height);

            try
            {
                using (var graphics = Graphics.FromImage(scaled))
                {
                    // Configuración de alta calidad para el escalado (misma que ScreenCapturer)
                    graphics.InterpolationMode = InterpolationMode.HighQualityBicubic;
                    graphics.SmoothingMode = SmoothingMode.HighQuality;
                    graphics.PixelOffsetMode = PixelOffsetMode.HighQuality;
                    graphics.CompositingQuality = CompositingQuality.HighQuality;

                    graphics.DrawImage(source, 0, 0, width, height);
                }

                return scaled;
            }
            catch (Exception ex)
            {
                scaled.Dispose();

                AlwaysPrintLogger.WriteTrayError(
                    $"JpegEncoder: error escalando bitmap de {source.Width}x{source.Height} " +
                    $"a {width}x{height}. {ex.Message}");

                throw;
            }
        }

        /// <summary>
        /// Crea los parámetros del encoder JPEG con la calidad especificada.
        /// </summary>
        /// <param name="quality">Calidad JPEG (1-100).</param>
        /// <returns>EncoderParameters configurados.</returns>
        private EncoderParameters CreateEncoderParams(int quality)
        {
            var encoderParams = new EncoderParameters(1);
            encoderParams.Param[0] = new EncoderParameter(Encoder.Quality, (long)quality);
            return encoderParams;
        }

        /// <summary>
        /// Clampea el valor de calidad al rango válido (1-100).
        /// </summary>
        /// <param name="quality">Valor de calidad a clampear.</param>
        /// <returns>Valor clampeado entre 1 y 100.</returns>
        private int ClampQuality(int quality)
        {
            if (quality < 1) return 1;
            if (quality > 100) return 100;
            return quality;
        }

        /// <summary>
        /// Obtiene el ImageCodecInfo para JPEG del sistema.
        /// </summary>
        /// <returns>ImageCodecInfo del codec JPEG.</returns>
        /// <exception cref="InvalidOperationException">Si el codec JPEG no está disponible.</exception>
        private ImageCodecInfo GetJpegCodec()
        {
            var codec = ImageCodecInfo.GetImageEncoders()
                .FirstOrDefault(c => c.FormatID == ImageFormat.Jpeg.Guid);

            if (codec == null)
            {
                AlwaysPrintLogger.WriteTrayError(
                    "JpegEncoder: codec JPEG no encontrado en el sistema.");
                throw new InvalidOperationException(
                    "No se encontró el codec JPEG en el sistema. " +
                    "Verifique que GDI+ esté correctamente instalado.");
            }

            return codec;
        }
    }
}
