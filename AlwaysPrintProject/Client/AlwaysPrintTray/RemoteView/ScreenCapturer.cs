using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintTray.RemoteView
{
    /// <summary>
    /// Captura la pantalla de un monitor específico usando GDI+ (Graphics.CopyFromScreen).
    /// La captura se escala al tamaño target ANTES de retornar (Req 4.2: scaling reduces at source).
    /// El Bitmap retornado es responsabilidad del caller para dispose.
    /// </summary>
    public class ScreenCapturer
    {
        /// <summary>
        /// Captura la pantalla del monitor indicado y escala al tamaño target.
        /// Usa interpolación bicúbica de alta calidad para el escalado.
        /// Nunca hace upscale: si el target es mayor que la resolución nativa, retorna a resolución nativa.
        /// Si targetWidth=0 o targetHeight=0, captura a resolución nativa sin escalar.
        /// </summary>
        /// <param name="monitorIndex">Índice del monitor a capturar (0-based).</param>
        /// <param name="targetWidth">Ancho objetivo en píxeles (0 = resolución nativa).</param>
        /// <param name="targetHeight">Alto objetivo en píxeles (0 = resolución nativa).</param>
        /// <returns>Bitmap escalado con la captura. El caller debe hacer Dispose().</returns>
        /// <exception cref="InvalidOperationException">Si la captura falla por error de sistema.</exception>
        public Bitmap Capture(int monitorIndex, int targetWidth, int targetHeight)
        {
            // Obtener bounds del monitor seleccionado
            var bounds = MonitorEnumerator.GetMonitorBounds(monitorIndex);

            // Capturar a resolución nativa del monitor
            var nativeBitmap = CaptureNative(bounds);

            // Si no se solicita escalado, retornar captura nativa
            if (targetWidth <= 0 || targetHeight <= 0)
            {
                AlwaysPrintLogger.WriteTrayInfo(
                    $"ScreenCapturer: captura nativa monitor={monitorIndex}, " +
                    $"resolución={bounds.Width}x{bounds.Height}");
                return nativeBitmap;
            }

            // Nunca hacer upscale: si target > nativo, usar nativo
            if (targetWidth >= bounds.Width && targetHeight >= bounds.Height)
            {
                AlwaysPrintLogger.WriteTrayInfo(
                    $"ScreenCapturer: target ({targetWidth}x{targetHeight}) >= nativo " +
                    $"({bounds.Width}x{bounds.Height}), retornando sin escalar.");
                return nativeBitmap;
            }

            // Calcular dimensiones finales respetando aspect ratio
            int finalWidth = Math.Min(targetWidth, bounds.Width);
            int finalHeight = Math.Min(targetHeight, bounds.Height);

            // Escalar con interpolación bicúbica de alta calidad
            Bitmap scaledBitmap = null;
            try
            {
                scaledBitmap = ScaleBitmap(nativeBitmap, finalWidth, finalHeight);

                AlwaysPrintLogger.WriteTrayInfo(
                    $"ScreenCapturer: captura escalada monitor={monitorIndex}, " +
                    $"nativo={bounds.Width}x{bounds.Height}, target={finalWidth}x{finalHeight}");

                return scaledBitmap;
            }
            catch
            {
                // Si falla el escalado, liberar el bitmap escalado parcial y retornar nativo
                scaledBitmap?.Dispose();
                throw;
            }
            finally
            {
                // Siempre liberar el bitmap nativo si se escaló exitosamente
                if (scaledBitmap != null)
                {
                    nativeBitmap.Dispose();
                }
            }
        }

        /// <summary>
        /// Captura la pantalla completa del área indicada usando GDI+ CopyFromScreen.
        /// </summary>
        /// <param name="bounds">Área del escritorio a capturar (bounds del monitor).</param>
        /// <returns>Bitmap con la captura a resolución nativa.</returns>
        private Bitmap CaptureNative(Rectangle bounds)
        {
            var bitmap = new Bitmap(bounds.Width, bounds.Height);

            try
            {
                using (var graphics = Graphics.FromImage(bitmap))
                {
                    graphics.CopyFromScreen(
                        bounds.X,
                        bounds.Y,
                        0,
                        0,
                        bounds.Size,
                        CopyPixelOperation.SourceCopy);
                }

                return bitmap;
            }
            catch (Exception ex)
            {
                bitmap.Dispose();

                AlwaysPrintLogger.WriteTrayError(
                    $"ScreenCapturer: error en CopyFromScreen. bounds={bounds}. {ex.Message}");

                throw new InvalidOperationException(
                    $"Error capturando pantalla del monitor (bounds={bounds}): {ex.Message}", ex);
            }
        }

        /// <summary>
        /// Escala un Bitmap al tamaño indicado usando interpolación bicúbica de alta calidad.
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
                    // Configuración de alta calidad para el escalado
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
                    $"ScreenCapturer: error escalando bitmap de {source.Width}x{source.Height} " +
                    $"a {width}x{height}. {ex.Message}");

                throw;
            }
        }
    }
}
