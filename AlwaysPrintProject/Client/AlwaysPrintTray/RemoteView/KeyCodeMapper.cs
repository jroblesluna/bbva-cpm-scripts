using System.Collections.Generic;

namespace AlwaysPrintTray.RemoteView
{
    /// <summary>
    /// Mapea strings de JavaScript KeyboardEvent.code a virtual key codes de Windows (VK_*).
    /// Usado por InputInjector para traducir eventos del frontend a inyecciones de teclado nativas.
    /// Los códigos JavaScript son layout-independent (representan la posición física de la tecla).
    /// </summary>
    public static class KeyCodeMapper
    {
        /// <summary>
        /// Diccionario de mapeo: KeyboardEvent.code → VK_* (ushort).
        /// Cubre letras, dígitos, F-keys, navegación, modificadores y teclas especiales.
        /// </summary>
        private static readonly Dictionary<string, ushort> CodeToVk = new Dictionary<string, ushort>
        {
            // === Letras (A-Z) → VK_A (0x41) a VK_Z (0x5A) ===
            { "KeyA", 0x41 }, { "KeyB", 0x42 }, { "KeyC", 0x43 }, { "KeyD", 0x44 },
            { "KeyE", 0x45 }, { "KeyF", 0x46 }, { "KeyG", 0x47 }, { "KeyH", 0x48 },
            { "KeyI", 0x49 }, { "KeyJ", 0x4A }, { "KeyK", 0x4B }, { "KeyL", 0x4C },
            { "KeyM", 0x4D }, { "KeyN", 0x4E }, { "KeyO", 0x4F }, { "KeyP", 0x50 },
            { "KeyQ", 0x51 }, { "KeyR", 0x52 }, { "KeyS", 0x53 }, { "KeyT", 0x54 },
            { "KeyU", 0x55 }, { "KeyV", 0x56 }, { "KeyW", 0x57 }, { "KeyX", 0x58 },
            { "KeyY", 0x59 }, { "KeyZ", 0x5A },

            // === Dígitos (0-9) → 0x30 a 0x39 ===
            { "Digit0", 0x30 }, { "Digit1", 0x31 }, { "Digit2", 0x32 }, { "Digit3", 0x33 },
            { "Digit4", 0x34 }, { "Digit5", 0x35 }, { "Digit6", 0x36 }, { "Digit7", 0x37 },
            { "Digit8", 0x38 }, { "Digit9", 0x39 },

            // === Teclas de función (F1-F12) → VK_F1 (0x70) a VK_F12 (0x7B) ===
            { "F1", 0x70 }, { "F2", 0x71 }, { "F3", 0x72 }, { "F4", 0x73 },
            { "F5", 0x74 }, { "F6", 0x75 }, { "F7", 0x76 }, { "F8", 0x77 },
            { "F9", 0x78 }, { "F10", 0x79 }, { "F11", 0x7A }, { "F12", 0x7B },

            // === Modificadores ===
            { "ShiftLeft", 0xA0 },     // VK_LSHIFT
            { "ShiftRight", 0xA1 },    // VK_RSHIFT
            { "ControlLeft", 0xA2 },   // VK_LCONTROL
            { "ControlRight", 0xA3 },  // VK_RCONTROL
            { "AltLeft", 0xA4 },       // VK_LMENU
            { "AltRight", 0xA5 },      // VK_RMENU
            { "MetaLeft", 0x5B },      // VK_LWIN
            { "MetaRight", 0x5C },     // VK_RWIN

            // === Teclas de navegación ===
            { "ArrowUp", 0x26 },       // VK_UP
            { "ArrowDown", 0x28 },     // VK_DOWN
            { "ArrowLeft", 0x25 },     // VK_LEFT
            { "ArrowRight", 0x27 },    // VK_RIGHT
            { "Home", 0x24 },          // VK_HOME
            { "End", 0x23 },           // VK_END
            { "PageUp", 0x21 },        // VK_PRIOR
            { "PageDown", 0x22 },      // VK_NEXT
            { "Insert", 0x2D },        // VK_INSERT
            { "Delete", 0x2E },        // VK_DELETE

            // === Teclas especiales ===
            { "Enter", 0x0D },         // VK_RETURN
            { "NumpadEnter", 0x0D },   // VK_RETURN (mismo VK, pero extended)
            { "Escape", 0x1B },        // VK_ESCAPE
            { "Tab", 0x09 },           // VK_TAB
            { "Space", 0x20 },         // VK_SPACE
            { "Backspace", 0x08 },     // VK_BACK
            { "CapsLock", 0x14 },      // VK_CAPITAL
            { "NumLock", 0x90 },       // VK_NUMLOCK
            { "ScrollLock", 0x91 },    // VK_SCROLL
            { "Pause", 0x13 },         // VK_PAUSE
            { "PrintScreen", 0x2C },   // VK_SNAPSHOT
            { "ContextMenu", 0x5D },   // VK_APPS

            // === Teclado numérico ===
            { "Numpad0", 0x60 },       // VK_NUMPAD0
            { "Numpad1", 0x61 },       // VK_NUMPAD1
            { "Numpad2", 0x62 },       // VK_NUMPAD2
            { "Numpad3", 0x63 },       // VK_NUMPAD3
            { "Numpad4", 0x64 },       // VK_NUMPAD4
            { "Numpad5", 0x65 },       // VK_NUMPAD5
            { "Numpad6", 0x66 },       // VK_NUMPAD6
            { "Numpad7", 0x67 },       // VK_NUMPAD7
            { "Numpad8", 0x68 },       // VK_NUMPAD8
            { "Numpad9", 0x69 },       // VK_NUMPAD9
            { "NumpadMultiply", 0x6A },  // VK_MULTIPLY
            { "NumpadAdd", 0x6B },       // VK_ADD
            { "NumpadSubtract", 0x6D },  // VK_SUBTRACT
            { "NumpadDecimal", 0x6E },   // VK_DECIMAL
            { "NumpadDivide", 0x6F },    // VK_DIVIDE

            // === Símbolos y puntuación ===
            { "Minus", 0xBD },           // VK_OEM_MINUS (-)
            { "Equal", 0xBB },           // VK_OEM_PLUS (=)
            { "BracketLeft", 0xDB },     // VK_OEM_4 ([)
            { "BracketRight", 0xDD },    // VK_OEM_6 (])
            { "Backslash", 0xDC },       // VK_OEM_5 (\)
            { "Semicolon", 0xBA },       // VK_OEM_1 (;)
            { "Quote", 0xDE },           // VK_OEM_7 (')
            { "Comma", 0xBC },           // VK_OEM_COMMA (,)
            { "Period", 0xBE },          // VK_OEM_PERIOD (.)
            { "Slash", 0xBF },           // VK_OEM_2 (/)
            { "Backquote", 0xC0 },       // VK_OEM_3 (`)
            { "IntlBackslash", 0xE2 },   // VK_OEM_102 (tecla extra en teclados ISO)
        };

        /// <summary>
        /// Convierte un KeyboardEvent.code de JavaScript a un virtual key code de Windows.
        /// </summary>
        /// <param name="code">String del KeyboardEvent.code (ej: "KeyA", "ArrowLeft", "Enter").</param>
        /// <param name="virtualKey">Virtual key code de Windows si se encontró mapeo.</param>
        /// <returns>true si se encontró un mapeo válido, false si el código no es reconocido.</returns>
        public static bool TryGetVirtualKey(string code, out ushort virtualKey)
        {
            if (string.IsNullOrEmpty(code))
            {
                virtualKey = 0;
                return false;
            }

            return CodeToVk.TryGetValue(code, out virtualKey);
        }

        /// <summary>
        /// Convierte un KeyboardEvent.code de JavaScript a un virtual key code de Windows.
        /// Retorna 0 si no se encuentra mapeo.
        /// </summary>
        /// <param name="code">String del KeyboardEvent.code.</param>
        /// <returns>Virtual key code o 0 si no reconocido.</returns>
        public static ushort GetVirtualKey(string code)
        {
            if (string.IsNullOrEmpty(code))
                return 0;

            return CodeToVk.TryGetValue(code, out ushort vk) ? vk : (ushort)0;
        }

        /// <summary>
        /// Verifica si un KeyboardEvent.code tiene un mapeo conocido.
        /// </summary>
        /// <param name="code">String del KeyboardEvent.code.</param>
        /// <returns>true si el código es reconocido y puede ser inyectado.</returns>
        public static bool IsKnownCode(string code)
        {
            return !string.IsNullOrEmpty(code) && CodeToVk.ContainsKey(code);
        }
    }
}
