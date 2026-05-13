using System;
using System.Collections.Generic;
using System.Globalization;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintTray.Localization
{
    /// <summary>
    /// Gestiona la internacionalización (i18n) de la interfaz del Tray.
    /// Soporta inglés (default) y español, detectando el locale del SO o usando un override explícito.
    /// Los strings se definen directamente en código para evitar problemas con ensamblados satélite
    /// en .NET Framework 4.8 SDK-style projects.
    /// </summary>
    public static class LocalizationManager
    {
        /// <summary>Locales soportados por la aplicación.</summary>
        public static readonly string[] SupportedLocales = { "es", "en" };

        private static string _currentLocale = "en";
        private static Dictionary<string, string>? _strings;

        /// <summary>Código ISO de dos letras del locale activo ("es" o "en").</summary>
        public static string CurrentLocale => _currentLocale;

        // ── Diccionarios de strings por idioma ──────────────────────────────────

        private static readonly Dictionary<string, string> StringsEn = new Dictionary<string, string>
        {
            { "TrayTooltip",              "AlwaysPrint" },
            { "MenuAbout",               "About" },
            { "MenuConfiguration",       "Configuration" },
            { "MenuExit",                "Exit" },
            { "BalloonInitOk",           "Initialized successfully ({0})." },
            { "BalloonInitFail",         "Operating in local mode." },
            { "BalloonServiceNotRunning","Service is not running." },
            { "BalloonOfflineWarning",   "Using cached config. No cloud connection." },
            { "BalloonOfflineTitle",     "AlwaysPrint" },
            { "BalloonOfflineText",      "Using cached config. No cloud connection." },
            { "BalloonOfflineNoConfig",  "No cloud connection and no cached config. Using defaults." },
            { "BalloonReconnected",      "Cloud connection restored." },
            { "TooltipOffline",          "AlwaysPrint (offline)" }
        };

        private static readonly Dictionary<string, string> StringsEs = new Dictionary<string, string>
        {
            { "TrayTooltip",              "AlwaysPrint" },
            { "MenuAbout",               "Acerca de" },
            { "MenuConfiguration",       "Configuraci\u00f3n de Valores" },
            { "MenuExit",                "Salir" },
            { "BalloonInitOk",           "Inicializado correctamente ({0})." },
            { "BalloonInitFail",         "Operando en modo local." },
            { "BalloonServiceNotRunning","El servicio no est\u00e1 en ejecuci\u00f3n." },
            { "BalloonOfflineWarning",   "Usando configuraci\u00f3n guardada. Sin conexi\u00f3n a la nube." },
            { "BalloonOfflineTitle",     "AlwaysPrint" },
            { "BalloonOfflineText",      "Usando configuraci\u00f3n guardada. Sin conexi\u00f3n a la nube." },
            { "BalloonOfflineNoConfig",  "Sin conexi\u00f3n a la nube y sin configuraci\u00f3n guardada. Usando valores por defecto." },
            { "BalloonReconnected",      "Conexi\u00f3n con la nube restaurada." },
            { "TooltipOffline",          "AlwaysPrint (sin conexi\u00f3n)" }
        };

        // ── API pública ─────────────────────────────────────────────────────────

        /// <summary>
        /// Inicializa el sistema i18n.
        /// Sin override: detecta el locale de <see cref="CultureInfo.CurrentUICulture"/>.
        /// Con override: usa el valor proporcionado ignorando el locale del SO.
        /// </summary>
        /// <param name="localeOverride">Override explícito del locale (ej. "es", "en"). Null o vacío = auto-detectar.</param>
        public static void Initialize(string? localeOverride = null)
        {
            // Determinar el locale objetivo: override explícito o detección automática del SO
            string target = string.IsNullOrEmpty(localeOverride)
                ? CultureInfo.CurrentUICulture.TwoLetterISOLanguageName ?? "en"
                : localeOverride!;

            // Normalizar: cualquier variante de español ("es-PE", "es-MX", etc.) → "es"; resto → "en"
            _currentLocale = target.StartsWith("es", StringComparison.OrdinalIgnoreCase) ? "es" : "en";
            _strings = _currentLocale == "es" ? StringsEs : StringsEn;

            AlwaysPrintLogger.WriteTrayInfo(
                $"Localizacion inicializada: locale={_currentLocale} (detectado={target})",
                AlwaysPrintLogger.EvtServiceStarted);
        }

        /// <summary>
        /// Obtiene el string localizado para la clave indicada.
        /// Si la clave no existe, devuelve el nombre de la clave como fallback sin lanzar excepción.
        /// </summary>
        /// <param name="key">Clave del recurso (ej. "MenuAbout", "TrayTooltip").</param>
        /// <returns>String localizado, o el nombre de la clave si no se encuentra.</returns>
        public static string Get(string key)
        {
            if (_strings != null && _strings.TryGetValue(key, out string? value))
                return value;

            // Fallback: buscar en inglés si el diccionario activo no tiene la clave
            if (StringsEn.TryGetValue(key, out string? fallback))
                return fallback;

            return key;
        }
    }
}
