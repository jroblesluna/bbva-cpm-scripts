using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintTray.RemoteView
{
    /// <summary>
    /// Indicador visual persistente de monitoreo remoto en el System Tray.
    /// Modifica el icono del NotifyIcon existente agregando un overlay de punto rojo
    /// y cambia el tooltip según el modo activo (view-only o interactivo).
    /// 
    /// Requisitos implementados:
    /// - Req 3.9: Indicador visual persistente NO ocultable durante sesión activa.
    /// - Req 6.8: Indicador distinto cuando modo interactivo está activo.
    /// - Req 12.5: No suprimible via configuración, API, o cualquier mecanismo.
    /// </summary>
    public sealed class MonitoringIndicator : IDisposable
    {
        // === Constantes de tooltip ===
        private const string TooltipViewOnly = "\U0001F534 Pantalla monitoreada por {0}";
        private const string TooltipInteractive = "\U0001F534 Control remoto activo - {0}";

        // === Estado interno ===
        private readonly NotifyIcon _notifyIcon;
        private Icon? _originalIcon;
        private string? _originalTooltip;
        private bool _isActive;
        private string? _currentMode;
        private string? _currentUserName;
        private readonly object _lock = new object();
        private bool _disposed;

        /// <summary>
        /// Indica si el indicador de monitoreo está actualmente visible.
        /// </summary>
        public bool IsActive
        {
            get { lock (_lock) { return _isActive; } }
        }

        /// <summary>
        /// Constructor. Recibe la referencia al NotifyIcon existente del Tray.
        /// </summary>
        /// <param name="notifyIcon">NotifyIcon del sistema tray que será modificado.</param>
        public MonitoringIndicator(NotifyIcon notifyIcon)
        {
            _notifyIcon = notifyIcon ?? throw new ArgumentNullException(nameof(notifyIcon));
        }

        /// <summary>
        /// Activa el indicador de monitoreo. Cambia el icono del tray agregando un
        /// overlay rojo y actualiza el tooltip según el modo de sesión.
        /// </summary>
        /// <param name="mode">Modo de la sesión: "screenshot", "stream", o "interactive".</param>
        /// <param name="userName">Nombre del administrador que está monitoreando.</param>
        public void Activate(string mode, string userName)
        {
            if (_disposed) return;

            lock (_lock)
            {
                if (!_isActive)
                {
                    // Guardar estado original para restaurar al desactivar
                    _originalIcon = _notifyIcon.Icon;
                    _originalTooltip = _notifyIcon.Text;
                }

                _currentMode = mode;
                _currentUserName = userName ?? "Admin";
                _isActive = true;
            }

            ApplyOverlayIcon();
            ApplyTooltip();

            AlwaysPrintLogger.WriteTrayInfo(
                $"MonitoringIndicator: activado. mode={mode}, user={userName}");
        }

        /// <summary>
        /// Actualiza el modo de la sesión (cambia tooltip sin recrear el overlay del icono).
        /// </summary>
        /// <param name="mode">Nuevo modo: "screenshot", "stream", o "interactive".</param>
        public void UpdateMode(string mode)
        {
            if (_disposed) return;

            lock (_lock)
            {
                if (!_isActive) return;
                _currentMode = mode;
            }

            ApplyTooltip();

            AlwaysPrintLogger.WriteTrayInfo(
                $"MonitoringIndicator: modo actualizado a '{mode}'.");
        }

        /// <summary>
        /// Desactiva el indicador de monitoreo. Restaura el icono y tooltip originales del Tray.
        /// Llamado al recibir remote_view_stop o al perder conexión WebSocket.
        /// </summary>
        public void Deactivate()
        {
            if (_disposed) return;

            Icon? overlayToDispose = null;

            lock (_lock)
            {
                if (!_isActive) return;

                _isActive = false;
                _currentMode = null;
                _currentUserName = null;

                // Capturar el icono overlay actual para dispose posterior
                if (_notifyIcon.Icon != null && _notifyIcon.Icon != _originalIcon)
                {
                    overlayToDispose = _notifyIcon.Icon;
                }
            }

            // Restaurar icono y tooltip originales
            RestoreOriginal();

            // Liberar el icono overlay generado
            overlayToDispose?.Dispose();

            AlwaysPrintLogger.WriteTrayInfo(
                "MonitoringIndicator: desactivado. Icono y tooltip restaurados.");
        }

        /// <summary>
        /// Aplica el icono con overlay de punto rojo al NotifyIcon.
        /// Genera el overlay programáticamente dibujando un círculo rojo
        /// sobre el icono existente.
        /// </summary>
        private void ApplyOverlayIcon()
        {
            try
            {
                Icon? baseIcon;
                lock (_lock)
                {
                    baseIcon = _originalIcon;
                }

                if (baseIcon == null)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "MonitoringIndicator: no hay icono base para aplicar overlay.");
                    return;
                }

                // Crear bitmap a partir del icono original
                int size = 32; // Tamaño estándar de icono de tray
                using (var baseBitmap = new Bitmap(baseIcon.ToBitmap(), size, size))
                using (var graphics = Graphics.FromImage(baseBitmap))
                {
                    graphics.SmoothingMode = SmoothingMode.AntiAlias;

                    // Dibujar círculo rojo en esquina inferior derecha (indicador de estado)
                    int dotSize = 12;
                    int dotX = size - dotSize - 1;
                    int dotY = size - dotSize - 1;

                    // Borde blanco para contraste
                    using (var whiteBrush = new SolidBrush(Color.White))
                    {
                        graphics.FillEllipse(whiteBrush, dotX - 1, dotY - 1, dotSize + 2, dotSize + 2);
                    }

                    // Punto rojo principal
                    using (var redBrush = new SolidBrush(Color.FromArgb(220, 30, 30)))
                    {
                        graphics.FillEllipse(redBrush, dotX, dotY, dotSize, dotSize);
                    }

                    // Convertir bitmap con overlay a Icon y asignar
                    var overlayIcon = Icon.FromHandle(baseBitmap.GetHicon());

                    // Dispose del icono overlay anterior si existe
                    Icon? previousOverlay = null;
                    lock (_lock)
                    {
                        if (_notifyIcon.Icon != null && _notifyIcon.Icon != _originalIcon)
                        {
                            previousOverlay = _notifyIcon.Icon;
                        }
                    }

                    _notifyIcon.Icon = overlayIcon;
                    previousOverlay?.Dispose();
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"MonitoringIndicator: error generando icono overlay. {ex.Message}");
            }
        }

        /// <summary>
        /// Aplica el tooltip correspondiente al modo activo.
        /// - screenshot/stream: "Pantalla monitoreada por [UserName]"
        /// - interactive: "Control remoto activo - [UserName]"
        /// </summary>
        private void ApplyTooltip()
        {
            try
            {
                string? mode;
                string? userName;

                lock (_lock)
                {
                    if (!_isActive) return;
                    mode = _currentMode;
                    userName = _currentUserName;
                }

                string tooltip;
                if (string.Equals(mode, "interactive", StringComparison.OrdinalIgnoreCase))
                {
                    tooltip = string.Format(TooltipInteractive, userName);
                }
                else
                {
                    // screenshot y stream son view-only
                    tooltip = string.Format(TooltipViewOnly, userName);
                }

                // NotifyIcon.Text tiene límite de 63 caracteres
                if (tooltip.Length > 63)
                {
                    tooltip = tooltip.Substring(0, 60) + "...";
                }

                _notifyIcon.Text = tooltip;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"MonitoringIndicator: error aplicando tooltip. {ex.Message}");
            }
        }

        /// <summary>
        /// Restaura el icono y tooltip originales del NotifyIcon.
        /// </summary>
        private void RestoreOriginal()
        {
            try
            {
                lock (_lock)
                {
                    if (_originalIcon != null)
                    {
                        _notifyIcon.Icon = _originalIcon;
                        _originalIcon = null;
                    }

                    if (_originalTooltip != null)
                    {
                        _notifyIcon.Text = _originalTooltip;
                        _originalTooltip = null;
                    }
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"MonitoringIndicator: error restaurando icono/tooltip original. {ex.Message}");
            }
        }

        /// <summary>
        /// Libera recursos. No restaura el icono (debe llamarse Deactivate antes si se desea).
        /// </summary>
        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;

            // Si aún está activo al disponer, desactivar primero
            if (_isActive)
            {
                Deactivate();
            }
        }
    }
}
