using System;
using System.Runtime.InteropServices;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintTray.RemoteView
{
    /// <summary>
    /// Inyecta eventos de mouse y teclado en la workstation usando la API SendInput de Windows.
    /// Convierte coordenadas normalizadas (0.0-1.0) a coordenadas absolutas del monitor real.
    /// Soporta: movimiento de mouse, clicks, scroll, teclas y Secure Attention Sequence (SAS).
    /// </summary>
    public static class InputInjector
    {
        #region P/Invoke Declarations

        [DllImport("user32.dll", SetLastError = true)]
        private static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);

        [DllImport("user32.dll")]
        private static extern int GetSystemMetrics(int nIndex);

        [DllImport("sas.dll", SetLastError = true)]
        private static extern void SendSAS(bool asUser);

        // GetSystemMetrics constants
        private const int SM_CXSCREEN = 0;  // Ancho total del escritorio virtual
        private const int SM_CYSCREEN = 1;  // Alto total del escritorio virtual
        private const int SM_XVIRTUALSCREEN = 76;
        private const int SM_YVIRTUALSCREEN = 77;
        private const int SM_CXVIRTUALSCREEN = 78;
        private const int SM_CYVIRTUALSCREEN = 79;

        // Constante para coordenadas absolutas de SendInput (0..65535)
        private const int ABSOLUTE_COORDINATE_MAX = 65535;

        #endregion

        #region Input Structures

        [StructLayout(LayoutKind.Sequential)]
        private struct INPUT
        {
            public uint type;
            public INPUTUNION union;
        }

        [StructLayout(LayoutKind.Explicit)]
        private struct INPUTUNION
        {
            [FieldOffset(0)] public MOUSEINPUT mi;
            [FieldOffset(0)] public KEYBDINPUT ki;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct MOUSEINPUT
        {
            public int dx;
            public int dy;
            public int mouseData;
            public uint dwFlags;
            public uint time;
            public IntPtr dwExtraInfo;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct KEYBDINPUT
        {
            public ushort wVk;
            public ushort wScan;
            public uint dwFlags;
            public uint time;
            public IntPtr dwExtraInfo;
        }

        // Tipos de INPUT
        private const uint INPUT_MOUSE = 0;
        private const uint INPUT_KEYBOARD = 1;

        // Flags de mouse
        private const uint MOUSEEVENTF_MOVE = 0x0001;
        private const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
        private const uint MOUSEEVENTF_LEFTUP = 0x0004;
        private const uint MOUSEEVENTF_RIGHTDOWN = 0x0008;
        private const uint MOUSEEVENTF_RIGHTUP = 0x0010;
        private const uint MOUSEEVENTF_MIDDLEDOWN = 0x0020;
        private const uint MOUSEEVENTF_MIDDLEUP = 0x0040;
        private const uint MOUSEEVENTF_WHEEL = 0x0800;
        private const uint MOUSEEVENTF_ABSOLUTE = 0x8000;
        private const uint MOUSEEVENTF_VIRTUALDESK = 0x4000;

        // Flags de teclado
        private const uint KEYEVENTF_KEYDOWN = 0x0000;
        private const uint KEYEVENTF_KEYUP = 0x0002;
        private const uint KEYEVENTF_EXTENDEDKEY = 0x0001;

        #endregion

        #region Mouse Injection

        /// <summary>
        /// Inyecta un movimiento de mouse a la posición normalizada en el monitor indicado.
        /// Las coordenadas normalizadas (0.0-1.0) se convierten a coordenadas absolutas del monitor real.
        /// </summary>
        /// <param name="normalizedX">Coordenada X normalizada (0.0 = izquierda, 1.0 = derecha del monitor).</param>
        /// <param name="normalizedY">Coordenada Y normalizada (0.0 = arriba, 1.0 = abajo del monitor).</param>
        /// <param name="monitorIndex">Índice del monitor destino (0-based).</param>
        public static void InjectMouseMove(double normalizedX, double normalizedY, int monitorIndex)
        {
            try
            {
                // Clamp coordenadas al rango válido
                normalizedX = Math.Max(0.0, Math.Min(1.0, normalizedX));
                normalizedY = Math.Max(0.0, Math.Min(1.0, normalizedY));

                // Obtener bounds del monitor destino
                var monitorBounds = MonitorEnumerator.GetMonitorBounds(monitorIndex);

                // Convertir normalizado → pixel absoluto en el escritorio virtual
                int pixelX = monitorBounds.X + (int)(normalizedX * monitorBounds.Width);
                int pixelY = monitorBounds.Y + (int)(normalizedY * monitorBounds.Height);

                // Convertir pixel absoluto → coordenadas virtuales para SendInput (0..65535)
                int virtualScreenX = GetSystemMetrics(SM_XVIRTUALSCREEN);
                int virtualScreenY = GetSystemMetrics(SM_YVIRTUALSCREEN);
                int virtualScreenWidth = GetSystemMetrics(SM_CXVIRTUALSCREEN);
                int virtualScreenHeight = GetSystemMetrics(SM_CYVIRTUALSCREEN);

                int virtualX = (int)(((double)(pixelX - virtualScreenX) / virtualScreenWidth) * ABSOLUTE_COORDINATE_MAX);
                int virtualY = (int)(((double)(pixelY - virtualScreenY) / virtualScreenHeight) * ABSOLUTE_COORDINATE_MAX);

                var input = new INPUT
                {
                    type = INPUT_MOUSE,
                    union = new INPUTUNION
                    {
                        mi = new MOUSEINPUT
                        {
                            dx = virtualX,
                            dy = virtualY,
                            mouseData = 0,
                            dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
                            time = 0,
                            dwExtraInfo = IntPtr.Zero
                        }
                    }
                };

                SendInputSafe(new[] { input });
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"InputInjector: error inyectando movimiento de mouse. " +
                    $"normalizedX={normalizedX}, normalizedY={normalizedY}, monitor={monitorIndex}. {ex.Message}");
            }
        }

        /// <summary>
        /// Inyecta un evento de botón de mouse presionado en la posición indicada.
        /// Mueve el cursor a la posición antes de presionar el botón.
        /// </summary>
        /// <param name="button">Botón: "left", "right" o "middle".</param>
        /// <param name="normalizedX">Coordenada X normalizada (0.0-1.0).</param>
        /// <param name="normalizedY">Coordenada Y normalizada (0.0-1.0).</param>
        /// <param name="monitorIndex">Índice del monitor destino.</param>
        public static void InjectMouseDown(string button, double normalizedX, double normalizedY, int monitorIndex)
        {
            try
            {
                // Primero mover al punto
                InjectMouseMove(normalizedX, normalizedY, monitorIndex);

                uint flags = GetMouseDownFlag(button);
                if (flags == 0)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"InputInjector: botón de mouse no reconocido '{button}'. Ignorando mousedown.");
                    return;
                }

                var input = new INPUT
                {
                    type = INPUT_MOUSE,
                    union = new INPUTUNION
                    {
                        mi = new MOUSEINPUT
                        {
                            dx = 0,
                            dy = 0,
                            mouseData = 0,
                            dwFlags = flags,
                            time = 0,
                            dwExtraInfo = IntPtr.Zero
                        }
                    }
                };

                SendInputSafe(new[] { input });
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"InputInjector: error inyectando mousedown. button={button}. {ex.Message}");
            }
        }

        /// <summary>
        /// Inyecta un evento de botón de mouse soltado en la posición indicada.
        /// Mueve el cursor a la posición antes de soltar el botón.
        /// </summary>
        /// <param name="button">Botón: "left", "right" o "middle".</param>
        /// <param name="normalizedX">Coordenada X normalizada (0.0-1.0).</param>
        /// <param name="normalizedY">Coordenada Y normalizada (0.0-1.0).</param>
        /// <param name="monitorIndex">Índice del monitor destino.</param>
        public static void InjectMouseUp(string button, double normalizedX, double normalizedY, int monitorIndex)
        {
            try
            {
                // Primero mover al punto
                InjectMouseMove(normalizedX, normalizedY, monitorIndex);

                uint flags = GetMouseUpFlag(button);
                if (flags == 0)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"InputInjector: botón de mouse no reconocido '{button}'. Ignorando mouseup.");
                    return;
                }

                var input = new INPUT
                {
                    type = INPUT_MOUSE,
                    union = new INPUTUNION
                    {
                        mi = new MOUSEINPUT
                        {
                            dx = 0,
                            dy = 0,
                            mouseData = 0,
                            dwFlags = flags,
                            time = 0,
                            dwExtraInfo = IntPtr.Zero
                        }
                    }
                };

                SendInputSafe(new[] { input });
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"InputInjector: error inyectando mouseup. button={button}. {ex.Message}");
            }
        }

        /// <summary>
        /// Inyecta un evento de scroll de rueda del mouse.
        /// Valores positivos = scroll hacia arriba, negativos = scroll hacia abajo.
        /// </summary>
        /// <param name="delta">Delta de scroll (positivo=arriba, negativo=abajo). Típicamente ±120.</param>
        public static void InjectWheel(int delta)
        {
            try
            {
                var input = new INPUT
                {
                    type = INPUT_MOUSE,
                    union = new INPUTUNION
                    {
                        mi = new MOUSEINPUT
                        {
                            dx = 0,
                            dy = 0,
                            mouseData = delta,
                            dwFlags = MOUSEEVENTF_WHEEL,
                            time = 0,
                            dwExtraInfo = IntPtr.Zero
                        }
                    }
                };

                SendInputSafe(new[] { input });
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"InputInjector: error inyectando wheel. delta={delta}. {ex.Message}");
            }
        }

        #endregion

        #region Keyboard Injection

        /// <summary>
        /// Inyecta un evento de tecla presionada (keydown).
        /// Presiona primero los modificadores activos y luego la tecla principal.
        /// </summary>
        /// <param name="virtualKey">Virtual key code de Windows (VK_*).</param>
        /// <param name="modifiers">Array de modificadores activos: "ctrl", "alt", "shift", "meta".</param>
        public static void InjectKeyDown(ushort virtualKey, string[]? modifiers)
        {
            try
            {
                var inputs = new System.Collections.Generic.List<INPUT>();

                // Presionar modificadores primero
                if (modifiers != null)
                {
                    foreach (var mod in modifiers)
                    {
                        ushort modVk = GetModifierVk(mod);
                        if (modVk != 0)
                        {
                            inputs.Add(CreateKeyInput(modVk, KEYEVENTF_KEYDOWN, IsExtendedKey(modVk)));
                        }
                    }
                }

                // Presionar la tecla principal
                inputs.Add(CreateKeyInput(virtualKey, KEYEVENTF_KEYDOWN, IsExtendedKey(virtualKey)));

                SendInputSafe(inputs.ToArray());
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"InputInjector: error inyectando keydown. vk=0x{virtualKey:X2}. {ex.Message}");
            }
        }

        /// <summary>
        /// Inyecta un evento de tecla soltada (keyup).
        /// Suelta primero la tecla principal y luego los modificadores.
        /// </summary>
        /// <param name="virtualKey">Virtual key code de Windows (VK_*).</param>
        /// <param name="modifiers">Array de modificadores activos: "ctrl", "alt", "shift", "meta".</param>
        public static void InjectKeyUp(ushort virtualKey, string[]? modifiers)
        {
            try
            {
                var inputs = new System.Collections.Generic.List<INPUT>();

                // Soltar la tecla principal primero
                inputs.Add(CreateKeyInput(virtualKey, KEYEVENTF_KEYUP, IsExtendedKey(virtualKey)));

                // Soltar modificadores después (orden inverso)
                if (modifiers != null)
                {
                    for (int i = modifiers.Length - 1; i >= 0; i--)
                    {
                        ushort modVk = GetModifierVk(modifiers[i]);
                        if (modVk != 0)
                        {
                            inputs.Add(CreateKeyInput(modVk, KEYEVENTF_KEYUP, IsExtendedKey(modVk)));
                        }
                    }
                }

                SendInputSafe(inputs.ToArray());
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"InputInjector: error inyectando keyup. vk=0x{virtualKey:X2}. {ex.Message}");
            }
        }

        #endregion

        #region Secure Attention Sequence (SAS)

        /// <summary>
        /// Inyecta la Secure Attention Sequence (Ctrl+Alt+Del).
        /// Usa SendSAS() de sas.dll si está disponible (requiere privilegios LocalSystem o UIAccess).
        /// </summary>
        public static void InjectSAS()
        {
            try
            {
                SendSAS(false);
                AlwaysPrintLogger.WriteTrayInfo("InputInjector: SAS (Ctrl+Alt+Del) inyectado exitosamente.");
            }
            catch (DllNotFoundException)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    "InputInjector: sas.dll no disponible. " +
                    "SendSAS requiere ejecutar como LocalSystem o tener privilegios UIAccess. " +
                    "Ctrl+Alt+Del no pudo ser inyectado.");
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"InputInjector: error inyectando SAS. {ex.Message}");
            }
        }

        #endregion

        #region Helpers

        /// <summary>
        /// Envía un array de INPUT a SendInput con manejo de errores.
        /// </summary>
        private static void SendInputSafe(INPUT[] inputs)
        {
            uint sent = SendInput((uint)inputs.Length, inputs, Marshal.SizeOf(typeof(INPUT)));
            if (sent != inputs.Length)
            {
                int error = Marshal.GetLastWin32Error();
                AlwaysPrintLogger.WriteTrayWarning(
                    $"InputInjector: SendInput envió {sent}/{inputs.Length} eventos. " +
                    $"Win32 error={error}. Posible UIPI (proceso destino con mayor integridad).");
            }
        }

        /// <summary>
        /// Crea un INPUT de teclado con los flags indicados.
        /// </summary>
        private static INPUT CreateKeyInput(ushort vk, uint flags, bool extended)
        {
            uint finalFlags = flags;
            if (extended)
                finalFlags |= KEYEVENTF_EXTENDEDKEY;

            return new INPUT
            {
                type = INPUT_KEYBOARD,
                union = new INPUTUNION
                {
                    ki = new KEYBDINPUT
                    {
                        wVk = vk,
                        wScan = 0,
                        dwFlags = finalFlags,
                        time = 0,
                        dwExtraInfo = IntPtr.Zero
                    }
                }
            };
        }

        /// <summary>
        /// Obtiene el flag MOUSEEVENTF para un botón presionado.
        /// </summary>
        private static uint GetMouseDownFlag(string button)
        {
            switch (button?.ToLowerInvariant())
            {
                case "left": return MOUSEEVENTF_LEFTDOWN;
                case "right": return MOUSEEVENTF_RIGHTDOWN;
                case "middle": return MOUSEEVENTF_MIDDLEDOWN;
                default: return 0;
            }
        }

        /// <summary>
        /// Obtiene el flag MOUSEEVENTF para un botón soltado.
        /// </summary>
        private static uint GetMouseUpFlag(string button)
        {
            switch (button?.ToLowerInvariant())
            {
                case "left": return MOUSEEVENTF_LEFTUP;
                case "right": return MOUSEEVENTF_RIGHTUP;
                case "middle": return MOUSEEVENTF_MIDDLEUP;
                default: return 0;
            }
        }

        /// <summary>
        /// Convierte un nombre de modificador del frontend a su virtual key code.
        /// </summary>
        private static ushort GetModifierVk(string modifier)
        {
            switch (modifier?.ToLowerInvariant())
            {
                case "ctrl":
                case "control": return 0x11; // VK_CONTROL
                case "alt": return 0x12;     // VK_MENU
                case "shift": return 0x10;   // VK_SHIFT
                case "meta":
                case "win": return 0x5B;     // VK_LWIN
                default: return 0;
            }
        }

        /// <summary>
        /// Determina si un virtual key code es una tecla extendida (requiere KEYEVENTF_EXTENDEDKEY).
        /// Teclas extendidas: flechas, Insert, Delete, Home, End, Page Up/Down, Num Lock,
        /// tecla Win, tecla App, y las variantes Right de Ctrl/Alt.
        /// </summary>
        private static bool IsExtendedKey(ushort vk)
        {
            switch (vk)
            {
                // Teclas de navegación
                case 0x21: // VK_PRIOR (Page Up)
                case 0x22: // VK_NEXT (Page Down)
                case 0x23: // VK_END
                case 0x24: // VK_HOME
                case 0x25: // VK_LEFT
                case 0x26: // VK_UP
                case 0x27: // VK_RIGHT
                case 0x28: // VK_DOWN
                case 0x2D: // VK_INSERT
                case 0x2E: // VK_DELETE
                // Teclas Windows y contexto
                case 0x5B: // VK_LWIN
                case 0x5C: // VK_RWIN
                case 0x5D: // VK_APPS
                // Teclas de control derechas
                case 0xA3: // VK_RCONTROL
                case 0xA5: // VK_RMENU (Right Alt)
                // Num Lock (es tecla extendida en el protocolo SendInput)
                case 0x90: // VK_NUMLOCK
                    return true;
                default:
                    return false;
            }
        }

        #endregion
    }
}
