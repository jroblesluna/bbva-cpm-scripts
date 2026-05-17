using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using AlwaysPrint.Shared.Logging;
using Newtonsoft.Json;

namespace AlwaysPrintTray.Localization
{
    /// <summary>
    /// Gestiona la internacionalización (i18n) de la interfaz del Tray.
    /// Soporta inglés (default) y español, detectando el locale del SO o usando un override explícito.
    /// Los strings se cargan desde archivos JSON embebidos (Localization/en.json, Localization/es.json).
    /// </summary>
    public static class LocalizationManager
    {
        /// <summary>Locales soportados por la aplicación.</summary>
        public static readonly string[] SupportedLocales = { "es", "en" };

        private static string _currentLocale = "en";
        private static Dictionary<string, string>? _strings;
        private static Dictionary<string, string>? _fallbackStrings;

        /// <summary>Código ISO de dos letras del locale activo ("es" o "en").</summary>
        public static string CurrentLocale => _currentLocale;

        // ── API pública ─────────────────────────────────────────────────────────

        /// <summary>
        /// Inicializa el sistema i18n.
        /// Sin override: detecta el locale de <see cref="CultureInfo.CurrentUICulture"/>.
        /// Con override: usa el valor proporcionado ignorando el locale del SO.
        /// Los strings se cargan desde los archivos JSON embebidos en el ensamblado.
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

            // Cargar strings desde JSON embebido
            _fallbackStrings = LoadStringsFromResource("en");
            _strings = _currentLocale == "es" ? LoadStringsFromResource("es") : _fallbackStrings;

            AlwaysPrintLogger.WriteTrayInfo(
                $"Localizacion inicializada: locale={_currentLocale} (detectado={target})",
                AlwaysPrintLogger.EvtServiceStarted);
        }

        /// <summary>
        /// Obtiene el string localizado para la clave indicada.
        /// Si la clave no existe en el idioma activo, busca en inglés como fallback.
        /// Si tampoco existe en inglés, devuelve el nombre de la clave sin lanzar excepción.
        /// </summary>
        /// <param name="key">Clave del recurso (ej. "MenuAbout", "TrayTooltip").</param>
        /// <returns>String localizado, o el nombre de la clave si no se encuentra.</returns>
        public static string Get(string key)
        {
            // Buscar en el idioma activo
            if (_strings != null && _strings.TryGetValue(key, out string? value))
                return value;

            // Fallback: buscar en inglés
            if (_fallbackStrings != null && _fallbackStrings.TryGetValue(key, out string? fallback))
                return fallback;

            return key;
        }

        // ── Carga de recursos ───────────────────────────────────────────────────

        /// <summary>
        /// Carga el diccionario de strings desde un archivo JSON embebido en el ensamblado.
        /// El recurso se busca como "AlwaysPrintTray.Localization.{locale}.json".
        /// </summary>
        /// <param name="locale">Código de idioma ("en" o "es").</param>
        /// <returns>Diccionario clave-valor con los strings, o diccionario vacío si falla la carga.</returns>
        private static Dictionary<string, string> LoadStringsFromResource(string locale)
        {
            try
            {
                var assembly = Assembly.GetExecutingAssembly();
                string resourceName = $"AlwaysPrintTray.Localization.{locale}.json";

                using var stream = assembly.GetManifestResourceStream(resourceName);
                if (stream == null)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"Recurso de localización no encontrado: {resourceName}. Usando claves como fallback.");
                    return new Dictionary<string, string>();
                }

                using var reader = new StreamReader(stream);
                string json = reader.ReadToEnd();

                var result = JsonConvert.DeserializeObject<Dictionary<string, string>>(json);
                return result ?? new Dictionary<string, string>();
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"Error cargando localización '{locale}': {ex.Message}. Usando claves como fallback.");
                return new Dictionary<string, string>();
            }
        }
    }
}
