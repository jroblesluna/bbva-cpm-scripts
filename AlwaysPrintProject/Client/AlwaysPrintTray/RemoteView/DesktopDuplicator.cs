using System;
using System.Drawing;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintTray.RemoteView
{
    /// <summary>
    /// Capturador de pantalla con soporte para Desktop Duplication API (DDA) de DXGI.
    /// Implementa fallback automático a GDI+ (Graphics.CopyFromScreen) cuando DDA no está disponible:
    /// - Windows 7 o anterior (DDA requiere Windows 8+)
    /// - Máquinas virtuales sin GPU passthrough
    /// - Escritorio bloqueado o sesión 0
    /// - Cualquier fallo en la inicialización de DDA
    ///
    /// El Bitmap retornado es responsabilidad del caller para dispose.
    /// Thread safety: usar desde un solo hilo (el hilo del loop de captura).
    /// </summary>
    public class DesktopDuplicator : IDisposable
    {
        private readonly ScreenCapturer _gdiCapturer;
        private readonly bool _ddaAvailable;
        private bool _disposed;

        // Versión mínima de Windows para DDA: Windows 8 = 6.2
        private const int DDA_MIN_MAJOR = 6;
        private const int DDA_MIN_MINOR = 2;

        /// <summary>
        /// Indica si Desktop Duplication API está disponible y activa.
        /// Si es false, se utiliza el fallback GDI+ (ScreenCapturer).
        /// </summary>
        public bool IsDdaActive => _ddaAvailable && !_disposed;

        /// <summary>
        /// Indica el método de captura actual en uso.
        /// </summary>
        public string CaptureMethod => _ddaAvailable ? "DDA (DXGI)" : "GDI+ (CopyFromScreen)";

        /// <summary>
        /// Inicializa el DesktopDuplicator.
        /// Intenta detectar si DDA está disponible (Windows 8+).
        /// Si no está disponible, configura el fallback GDI automáticamente.
        /// </summary>
        public DesktopDuplicator()
        {
            _gdiCapturer = new ScreenCapturer();
            _ddaAvailable = false;

            try
            {
                if (IsDdaSupported())
                {
                    // TODO: Implementar inicialización real de DDA cuando SharpDX u otro
                    // wrapper DirectX esté disponible en el proyecto.
                    // Pasos necesarios:
                    //   1. D3D11CreateDevice → obtener ID3D11Device
                    //   2. QueryInterface IDXGIDevice → GetAdapter → EnumOutputs
                    //   3. output.DuplicateOutput(device) → IDXGIOutputDuplication
                    //
                    // Por ahora, DDA detectado como disponible pero no implementado.
                    // Usamos fallback GDI hasta que se agregue la dependencia DirectX.
                    _ddaAvailable = false;

                    AlwaysPrintLogger.WriteTrayInfo(
                        "DesktopDuplicator: SO compatible con DDA (Windows 8+), " +
                        "pero implementación DDA pendiente — usando fallback GDI.");
                }
                else
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        "DesktopDuplicator: SO no compatible con DDA (requiere Windows 8+). " +
                        "Usando fallback GDI (CopyFromScreen).");
                }
            }
            catch (Exception ex)
            {
                // Si falla la detección, usar GDI sin problemas
                _ddaAvailable = false;

                AlwaysPrintLogger.WriteTrayWarning(
                    $"DesktopDuplicator: error detectando soporte DDA, usando fallback GDI. {ex.Message}");
            }
        }

        /// <summary>
        /// Captura un frame del monitor especificado.
        /// Si DDA está activo, usa Desktop Duplication API (hardware-accelerated).
        /// Si no, usa el fallback GDI+ (ScreenCapturer.Capture).
        /// </summary>
        /// <param name="monitorIndex">Índice del monitor a capturar (0-based).</param>
        /// <param name="targetWidth">Ancho objetivo en píxeles (0 = resolución nativa).</param>
        /// <param name="targetHeight">Alto objetivo en píxeles (0 = resolución nativa).</param>
        /// <returns>Bitmap con la captura. El caller debe hacer Dispose().</returns>
        /// <exception cref="ObjectDisposedException">Si el objeto ya fue disposed.</exception>
        /// <exception cref="InvalidOperationException">Si la captura falla.</exception>
        public Bitmap CaptureFrame(int monitorIndex, int targetWidth = 0, int targetHeight = 0)
        {
            if (_disposed)
                throw new ObjectDisposedException(nameof(DesktopDuplicator));

            if (_ddaAvailable)
            {
                return CaptureWithDda(monitorIndex, targetWidth, targetHeight);
            }

            return CaptureWithGdi(monitorIndex, targetWidth, targetHeight);
        }

        /// <summary>
        /// Captura usando Desktop Duplication API (DXGI).
        /// TODO: Implementar cuando se agregue SharpDX o P/Invoke directo a DXGI/D3D11.
        /// Actualmente este método no se invoca (DDA siempre desactivado).
        /// </summary>
        private Bitmap CaptureWithDda(int monitorIndex, int targetWidth, int targetHeight)
        {
            // TODO: Implementar captura real con DDA:
            //   1. AcquireNextFrame(timeout: 100ms) → IDXGISurface
            //   2. Copiar textura a staging texture (CPU-readable)
            //   3. MapSubresource → leer píxeles → crear Bitmap desde los datos
            //   4. ReleaseFrame()
            //
            // Si AcquireNextFrame falla (ej: desktop bloqueado, cambio de resolución),
            // hacer fallback temporal a GDI para ese frame específico.

            AlwaysPrintLogger.WriteTrayWarning(
                $"DesktopDuplicator: CaptureWithDda invocado pero no implementado, " +
                $"delegando a GDI. monitor={monitorIndex}");

            return CaptureWithGdi(monitorIndex, targetWidth, targetHeight);
        }

        /// <summary>
        /// Captura usando el fallback GDI+ (Graphics.CopyFromScreen via ScreenCapturer).
        /// </summary>
        private Bitmap CaptureWithGdi(int monitorIndex, int targetWidth, int targetHeight)
        {
            return _gdiCapturer.Capture(monitorIndex, targetWidth, targetHeight);
        }

        /// <summary>
        /// Verifica si el sistema operativo soporta Desktop Duplication API.
        /// DDA requiere Windows 8 (versión 6.2) o superior.
        /// </summary>
        /// <returns>True si el SO es compatible con DDA.</returns>
        private bool IsDdaSupported()
        {
            var osVersion = Environment.OSVersion.Version;

            // Windows 8 = 6.2, Windows 8.1 = 6.3, Windows 10/11 = 10.0
            bool supported = osVersion.Major > DDA_MIN_MAJOR ||
                            (osVersion.Major == DDA_MIN_MAJOR && osVersion.Minor >= DDA_MIN_MINOR);

            AlwaysPrintLogger.WriteTrayInfo(
                $"DesktopDuplicator: versión OS={osVersion.Major}.{osVersion.Minor}, " +
                $"DDA soportado={supported} (requiere >= {DDA_MIN_MAJOR}.{DDA_MIN_MINOR})");

            return supported;
        }

        /// <summary>
        /// Libera recursos DXGI/D3D11 si fueron inicializados.
        /// Actualmente solo limpia la referencia al ScreenCapturer (no hay recursos DDA).
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
                // TODO: Cuando DDA esté implementado, liberar aquí:
                //   - IDXGIOutputDuplication.ReleaseFrame()
                //   - IDXGIOutputDuplication → Release()
                //   - ID3D11Device → Release()
                //   - Staging textures → Release()

                AlwaysPrintLogger.WriteTrayInfo("DesktopDuplicator: recursos liberados.");
            }

            _disposed = true;
        }

        /// <summary>
        /// Finalizer de seguridad (por si no se llama Dispose explícitamente).
        /// </summary>
        ~DesktopDuplicator()
        {
            Dispose(false);
        }
    }
}
