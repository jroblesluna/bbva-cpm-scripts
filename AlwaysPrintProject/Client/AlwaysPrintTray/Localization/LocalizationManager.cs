using System;
using System.Globalization;
using System.Resources;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintTray.Localization
{
    /// <summary>
    /// Gestiona la internacionalización (i18n) de la interfaz del Tray.
    /// Soporta inglés (default) y español, detectando el locale del SO o usando un override explícito.
    /// </summary>
    public static class LocalizationManager
    {
        /// <summary>Locales soportados por la aplicación.</summary>
        public static readonly string[] SupportedLocales = { "es", "en" };

        private static string _currentLocale = "en";
        private static ResourceManager? _rm;

        /// <summary>Código ISO de dos letras del locale activo ("es" o "en").</summary>
        public static string CurrentLocale => _currentLocale;

        /// <summary>
        /// Inicializa el sistema i18n.
        /// Sin override: detecta el locale de <see cref="CultureInfo.CurrentUICulture"/>.
        /// Con override: usa el valor proporcionado ignorando el locale del SO.
        /// Si falla la carga del recurso, hace fallback a inglés y loggea el error.
        /// </summary>
        /// <param name="localeOverride">Override explícito del locale (ej. "es", "en"). Null o vacío = auto-detectar.</param>
        public static void Initialize(string? localeOverride = null)
        {
            // Determinar el locale objetivo: override explícito o detección automática del SO
            string target = string.IsNullOrEmpty(localeOverride)
                ? CultureInfo.CurrentUICulture.TwoLetterISOLanguageName
                : localeOverride;

            // Normalizar: cualquier variante de español ("es-PE", "es-MX", etc.) → "es"; resto → "en"
            _currentLocale = target.StartsWith("es", StringComparison.OrdinalIgnoreCase) ? "es" : "en";

            try
            {
                var culture = new CultureInfo(_currentLocale);
                _rm = new ResourceManager(
                    "AlwaysPrintTray.Resources.Strings",
                    typeof(LocalizationManager).Assembly);

                // Verificar que el recurso carga correctamente antes de continuar
                _rm.GetString("TrayTooltip", culture);
            }
            catch (Exception ex)
            {
                // Fallback a inglés si falla la carga del recurso
                AlwaysPrintLogger.WriteTrayError(
                    $"Error cargando recursos de idioma '{_currentLocale}'. Usando inglés. {ex.Message}");

                _currentLocale = "en";
                _rm = new ResourceManager(
                    "AlwaysPrintTray.Resources.Strings",
                    typeof(LocalizationManager).Assembly);
            }
        }

        /// <summary>
        /// Obtiene el string localizado para la clave indicada.
        /// Si la clave no existe, devuelve el nombre de la clave como fallback sin lanzar excepción.
        /// </summary>
        /// <param name="key">Clave del recurso (ej. "MenuAbout", "TrayTooltip").</param>
        /// <returns>String localizado, o el nombre de la clave si no se encuentra.</returns>
        public static string Get(string key)
        {
            try
            {
                var culture = new CultureInfo(_currentLocale);
                return _rm?.GetString(key, culture) ?? key;
            }
            catch
            {
                // Devolver el nombre del key como fallback sin propagar la excepción
                return key;
            }
        }
    }
}
