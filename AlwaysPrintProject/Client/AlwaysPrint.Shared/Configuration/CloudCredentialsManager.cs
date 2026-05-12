using System;
using System.Globalization;
using Microsoft.Win32;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrint.Shared.Configuration
{
    /// <summary>
    /// Gestiona las credenciales Cloud de la workstation en HKCU\SOFTWARE\Robles.AI\AlwaysPrint\Cloud.
    /// No requiere privilegios de administrador — usa exclusivamente Registry.CurrentUser.
    /// Solo el AlwaysPrintTray debe instanciar esta clase.
    /// </summary>
    public class CloudCredentialsManager
    {
        /// <summary>
        /// Ruta de la clave de registro en HKCU donde se almacenan las credenciales Cloud.
        /// </summary>
        public const string RegistryPath = @"SOFTWARE\Robles.AI\AlwaysPrint\Cloud";

        // === PROPIEDADES DE SOLO LECTURA ===

        /// <summary>
        /// Identificador único de la workstation asignado por APCM.
        /// Null si la workstation no ha sido registrada.
        /// </summary>
        public string? WorkstationId { get; private set; }

        /// <summary>
        /// Hash SHA-256 de la última configuración descargada de APCM.
        /// Null si no se ha descargado ninguna configuración.
        /// </summary>
        public string? ConfigHash { get; private set; }

        /// <summary>
        /// Fecha y hora en que se almacenó en caché la última configuración.
        /// Null si no hay configuración en caché.
        /// </summary>
        public DateTime? ConfigCachedAt { get; private set; }

        /// <summary>
        /// Fecha y hora de la última conexión exitosa con APCM.
        /// Null si nunca se ha conectado.
        /// </summary>
        public DateTime? LastConnectedAt { get; private set; }

        /// <summary>
        /// Indica si la workstation está registrada en APCM.
        /// Retorna true si y solo si WorkstationId no es null ni vacío.
        /// </summary>
        public bool IsRegistered => !string.IsNullOrEmpty(WorkstationId);

        // === MÉTODOS PÚBLICOS ===

        /// <summary>
        /// Lee los cuatro valores de credenciales desde HKCU\SOFTWARE\Robles.AI\AlwaysPrint\Cloud.
        /// Si la clave no existe, está inaccesible, o cualquier valor no puede parsearse,
        /// las propiedades correspondientes quedan en null sin lanzar excepción.
        /// </summary>
        public void Load()
        {
            try
            {
                using (var key = Registry.CurrentUser.OpenSubKey(RegistryPath, writable: false))
                {
                    // Si la clave no existe, dejar todas las propiedades en null.
                    if (key == null)
                    {
                        WorkstationId   = null;
                        ConfigHash      = null;
                        ConfigCachedAt  = null;
                        LastConnectedAt = null;
                        return;
                    }

                    // Leer WorkstationId como string.
                    WorkstationId = key.GetValue("WorkstationId", null) as string;

                    // Leer ConfigHash como string.
                    ConfigHash = key.GetValue("ConfigHash", null) as string;

                    // Leer y parsear ConfigCachedAt desde ISO-8601.
                    var rawCachedAt = key.GetValue("ConfigCachedAt", null) as string;
                    ConfigCachedAt = ParseIso8601(rawCachedAt);

                    // Leer y parsear LastConnectedAt desde ISO-8601.
                    var rawLastConnected = key.GetValue("LastConnectedAt", null) as string;
                    LastConnectedAt = ParseIso8601(rawLastConnected);
                }
            }
            catch (Exception ex)
            {
                // Error al acceder al registro: loggear en español y no propagar.
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudCredentialsManager.Load: error leyendo credenciales Cloud desde HKCU. {ex.Message}",
                    AlwaysPrintLogger.EvtGenericError);
            }
        }

        /// <summary>
        /// Escribe el WorkstationId en HKCU y actualiza la propiedad en memoria.
        /// Si ocurre un error de registro, se loggea en español y no se propaga la excepción.
        /// </summary>
        /// <param name="id">Identificador de workstation asignado por APCM.</param>
        public void SaveWorkstationId(string id)
        {
            try
            {
                using (var key = Registry.CurrentUser.CreateSubKey(RegistryPath, writable: true))
                {
                    if (key == null)
                        throw new InvalidOperationException("No se puede crear/abrir la clave HKCU para credenciales Cloud.");

                    key.SetValue("WorkstationId", id ?? string.Empty, RegistryValueKind.String);
                }

                // Actualizar propiedad en memoria solo si la escritura fue exitosa.
                WorkstationId = id;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudCredentialsManager.SaveWorkstationId: error guardando WorkstationId en HKCU. {ex.Message}",
                    AlwaysPrintLogger.EvtGenericError);
            }
        }

        /// <summary>
        /// Escribe el hash de configuración y su fecha de caché en HKCU, y actualiza las propiedades en memoria.
        /// La fecha se serializa en formato ISO-8601 (round-trip, especificador "O").
        /// Si ocurre un error de registro, se loggea en español y no se propaga la excepción.
        /// </summary>
        /// <param name="hash">Hash SHA-256 de la configuración descargada.</param>
        /// <param name="cachedAt">Fecha y hora en que se almacenó la configuración en caché.</param>
        public void SaveConfigHash(string hash, DateTime cachedAt)
        {
            try
            {
                using (var key = Registry.CurrentUser.CreateSubKey(RegistryPath, writable: true))
                {
                    if (key == null)
                        throw new InvalidOperationException("No se puede crear/abrir la clave HKCU para credenciales Cloud.");

                    key.SetValue("ConfigHash",     hash ?? string.Empty,       RegistryValueKind.String);
                    key.SetValue("ConfigCachedAt", cachedAt.ToString("O"),     RegistryValueKind.String);
                }

                // Actualizar propiedades en memoria solo si la escritura fue exitosa.
                ConfigHash     = hash;
                ConfigCachedAt = cachedAt;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudCredentialsManager.SaveConfigHash: error guardando ConfigHash en HKCU. {ex.Message}",
                    AlwaysPrintLogger.EvtGenericError);
            }
        }

        /// <summary>
        /// Escribe la fecha de última conexión en HKCU y actualiza la propiedad en memoria.
        /// La fecha se serializa en formato ISO-8601 (round-trip, especificador "O").
        /// Si ocurre un error de registro, se loggea en español y no se propaga la excepción.
        /// </summary>
        /// <param name="connectedAt">Fecha y hora de la última conexión exitosa con APCM.</param>
        public void SaveLastConnected(DateTime connectedAt)
        {
            try
            {
                using (var key = Registry.CurrentUser.CreateSubKey(RegistryPath, writable: true))
                {
                    if (key == null)
                        throw new InvalidOperationException("No se puede crear/abrir la clave HKCU para credenciales Cloud.");

                    key.SetValue("LastConnectedAt", connectedAt.ToString("O"), RegistryValueKind.String);
                }

                // Actualizar propiedad en memoria solo si la escritura fue exitosa.
                LastConnectedAt = connectedAt;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudCredentialsManager.SaveLastConnected: error guardando LastConnectedAt en HKCU. {ex.Message}",
                    AlwaysPrintLogger.EvtGenericError);
            }
        }

        // === MÉTODOS PRIVADOS ===

        /// <summary>
        /// Parsea una cadena ISO-8601 (formato round-trip "O") a DateTime?.
        /// Retorna null si la cadena es nula, vacía, o no puede parsearse.
        /// </summary>
        /// <param name="value">Cadena ISO-8601 a parsear.</param>
        /// <returns>DateTime parseado, o null si el valor es inválido.</returns>
        private static DateTime? ParseIso8601(string? value)
        {
            if (string.IsNullOrWhiteSpace(value))
                return null;

            // Intentar parseo exacto con formato round-trip "O" (ISO-8601 completo).
            if (DateTime.TryParseExact(
                    value,
                    "O",
                    CultureInfo.InvariantCulture,
                    DateTimeStyles.RoundtripKind,
                    out var dtExact))
            {
                return dtExact;
            }

            // Fallback: parseo flexible con RoundtripKind para variantes ISO-8601.
            if (DateTime.TryParse(
                    value,
                    CultureInfo.InvariantCulture,
                    DateTimeStyles.RoundtripKind,
                    out var dtFlex))
            {
                return dtFlex;
            }

            // Valor no parseable: retornar null sin lanzar excepción (req. 3.6).
            return null;
        }
    }
}
