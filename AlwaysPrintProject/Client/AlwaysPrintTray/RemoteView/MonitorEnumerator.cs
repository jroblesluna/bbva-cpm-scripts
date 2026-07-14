using System;
using System.Collections.Generic;
using System.Windows.Forms;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintTray.RemoteView
{
    /// <summary>
    /// Fuente canónica para enumerar monitores de la workstation.
    /// Provee información de todos los monitores conectados: nombre, resolución, posición y primario.
    /// Utilizado por ConsentPopup, RemoteViewSession y ScreenCapturer.
    /// </summary>
    public static class MonitorEnumerator
    {
        /// <summary>
        /// Obtiene la lista de monitores conectados a la workstation.
        /// Lee Screen.AllScreens y retorna metadata en el formato esperado por el protocolo WebSocket.
        /// </summary>
        /// <returns>Lista de MonitorInfo con los monitores disponibles (siempre al menos uno).</returns>
        public static List<MonitorInfo> GetMonitors()
        {
            var monitors = new List<MonitorInfo>();

            try
            {
                var screens = Screen.AllScreens;

                for (int i = 0; i < screens.Length; i++)
                {
                    var screen = screens[i];
                    string name = screen.Primary ? "Principal" : $"Monitor {i + 1}";

                    monitors.Add(new MonitorInfo
                    {
                        Index = i,
                        Name = name,
                        Width = screen.Bounds.Width,
                        Height = screen.Bounds.Height,
                        Primary = screen.Primary,
                        X = screen.Bounds.X,
                        Y = screen.Bounds.Y
                    });
                }

                AlwaysPrintLogger.WriteTrayInfo(
                    $"MonitorEnumerator: {monitors.Count} monitores detectados.");
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"MonitorEnumerator: error enumerando monitores. {ex.Message}");

                // Fallback: reportar al menos un monitor genérico (primario)
                monitors.Add(new MonitorInfo
                {
                    Index = 0,
                    Name = "Principal",
                    Width = Screen.PrimaryScreen?.Bounds.Width ?? 1920,
                    Height = Screen.PrimaryScreen?.Bounds.Height ?? 1080,
                    Primary = true,
                    X = Screen.PrimaryScreen?.Bounds.X ?? 0,
                    Y = Screen.PrimaryScreen?.Bounds.Y ?? 0
                });
            }

            return monitors;
        }

        /// <summary>
        /// Obtiene el índice del monitor primario.
        /// Útil para determinar el monitor por defecto al iniciar una sesión (Req 8.4).
        /// </summary>
        /// <returns>Índice del monitor primario, o 0 si no se puede determinar.</returns>
        public static int GetPrimaryMonitorIndex()
        {
            try
            {
                var screens = Screen.AllScreens;
                for (int i = 0; i < screens.Length; i++)
                {
                    if (screens[i].Primary)
                        return i;
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"MonitorEnumerator: error obteniendo monitor primario. {ex.Message}");
            }

            return 0;
        }

        /// <summary>
        /// Obtiene los bounds (posición y tamaño) de un monitor específico.
        /// </summary>
        /// <param name="monitorIndex">Índice del monitor (0-based).</param>
        /// <returns>Rectangle con los bounds del monitor, o bounds del primario si el índice es inválido.</returns>
        public static System.Drawing.Rectangle GetMonitorBounds(int monitorIndex)
        {
            try
            {
                var screens = Screen.AllScreens;

                if (monitorIndex >= 0 && monitorIndex < screens.Length)
                {
                    return screens[monitorIndex].Bounds;
                }

                AlwaysPrintLogger.WriteTrayWarning(
                    $"MonitorEnumerator: índice de monitor {monitorIndex} fuera de rango " +
                    $"(hay {screens.Length} monitores). Usando monitor primario.");
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"MonitorEnumerator: error obteniendo bounds del monitor {monitorIndex}. {ex.Message}");
            }

            // Fallback: bounds del monitor primario
            return Screen.PrimaryScreen?.Bounds
                ?? new System.Drawing.Rectangle(0, 0, 1920, 1080);
        }
    }
}
