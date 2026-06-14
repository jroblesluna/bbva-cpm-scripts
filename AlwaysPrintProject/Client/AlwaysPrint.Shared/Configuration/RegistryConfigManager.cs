using System;
using System.Collections.Generic;
using System.Globalization;
using Microsoft.Win32;
using Newtonsoft.Json;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrint.Shared.Configuration
{
    /// <summary>
    /// Lee y escribe la configuración de AlwaysPrint en el registro de Windows.
    /// DEV: HKLM\SOFTWARE\Robles.AI\AlwaysPrint-DEV
    /// PROD: HKLM\SOFTWARE\Robles.AI\AlwaysPrint
    /// La escritura requiere que el caller tenga privilegios de administrador (el servicio).
    /// </summary>
    public class RegistryConfigManager
    {
#if ENV_DEV
        public const string RegistryPath = @"SOFTWARE\Robles.AI\AlwaysPrint-DEV";
        private const string DefaultBootstrapDomains = "dev.iol.pe";
#else
        public const string RegistryPath = @"SOFTWARE\Robles.AI\AlwaysPrint";
        private const string DefaultBootstrapDomains = "apps.iol.pe,sistemas.com.pe";
#endif

        public AppConfiguration Load()
        {
            var cfg = new AppConfiguration();
            try
            {
                using (var key = Registry.LocalMachine.OpenSubKey(RegistryPath, writable: false))
                {
                    if (key == null) return cfg;

                    // === CAMPOS EXISTENTES ===
                    cfg.CorporateQueueName  = key.GetValue("CorporateQueueName",  "LexmarkBBVA") as string ?? "LexmarkBBVA";
                    cfg.RoblesAiLicenseSerial = key.GetValue("RoblesAiLicenseSerial", string.Empty) as string ?? string.Empty;
                    cfg.BootstrapDomains    = key.GetValue("BootstrapDomains",    DefaultBootstrapDomains) as string
                                             ?? DefaultBootstrapDomains;

                    var rawPoll = key.GetValue("PendingTaskPollingMinutes", 3);
                    cfg.PendingTaskPollingMinutes = Math.Max(1, Convert.ToInt32(rawPoll));

                    var rawTargets = key.GetValue("SearchTargets", null) as string;
                    if (!string.IsNullOrWhiteSpace(rawTargets))
                        cfg.SearchTargets = JsonConvert.DeserializeObject<SearchTargetsConfig>(rawTargets!)
                                            ?? new SearchTargetsConfig();

                    // === CAMPOS CLOUD ===
                    cfg.CloudEnabled = Convert.ToInt32(key.GetValue("CloudEnabled", 0)) == 1;
                    cfg.CloudApiUrl  = key.GetValue("CloudApiUrl",  string.Empty) as string ?? string.Empty;
                    cfg.CloudLocale  = key.GetValue("CloudLocale",  string.Empty) as string ?? string.Empty;

                    var rawChecks = key.GetValue("ConnectivityChecks", null) as string;
                    if (string.IsNullOrWhiteSpace(rawChecks))
                    {
                        cfg.ConnectivityChecks = new List<ConnectivityCheck>();
                    }
                    else
                    {
                        try
                        {
                            cfg.ConnectivityChecks =
                                JsonConvert.DeserializeObject<List<ConnectivityCheck>>(rawChecks!)
                                ?? new List<ConnectivityCheck>();
                        }
                        catch (JsonException exJson)
                        {
                            // JSON malformado: asignar lista vacía sin propagar la excepción.
                            cfg.ConnectivityChecks = new List<ConnectivityCheck>();
                            AlwaysPrintLogger.WriteWarning(
                                $"RegistryConfigManager.Load: ConnectivityChecks contiene JSON malformado, se usará lista vacía. {exJson.Message}",
                                AlwaysPrintLogger.EvtGenericWarning);
                        }
                    }

                    cfg.TelemetryEnabled         = Convert.ToInt32(key.GetValue("TelemetryEnabled",         1)) == 1;
                    cfg.TelemetryIntervalSeconds = Math.Max(60, Convert.ToInt32(key.GetValue("TelemetryIntervalSeconds", 300)));
                }
            }
            catch (Exception ex)
            {
                // Loggear el error y devolver defaults para que el servicio pueda arrancar.
                AlwaysPrintLogger.WriteWarning(
                    $"RegistryConfigManager.Load: error leyendo configuración, usando valores por defecto. {ex.Message}",
                    AlwaysPrintLogger.EvtGenericWarning);
            }
            return cfg;
        }

        /// <summary>
        /// Persiste la configuración. El caller debe tener acceso de escritura a HKLM
        /// (servicio ejecutándose como LocalSystem).
        /// Llama a cfg.Validate() antes de abrir la clave de registro; si lanza, no escribe nada.
        /// </summary>
        public void Save(AppConfiguration cfg)
        {
            if (cfg == null) throw new ArgumentNullException(nameof(cfg));

            // Validar campos existentes (sanitización de strings, rangos, etc.)
            ValidateConfiguration(cfg);

            // Validar campos Cloud — si lanza, la excepción se propaga al caller sin escribir nada.
            cfg.Validate();

            using (var key = Registry.LocalMachine.CreateSubKey(RegistryPath, writable: true))
            {
                if (key == null)
                    throw new InvalidOperationException("No se puede crear/abrir la clave de registro — privilegios insuficientes.");

                // === CAMPOS EXISTENTES ===
                key.SetValue("CorporateQueueName",          cfg.CorporateQueueName  ?? "LexmarkBBVA",              RegistryValueKind.String);
                key.SetValue("PendingTaskPollingMinutes",    Math.Max(1, cfg.PendingTaskPollingMinutes),          RegistryValueKind.DWord);
                key.SetValue("BootstrapDomains",             cfg.BootstrapDomains    ?? DefaultBootstrapDomains, RegistryValueKind.String);
                key.SetValue("RoblesAiLicenseSerial",        cfg.RoblesAiLicenseSerial ?? string.Empty,          RegistryValueKind.String);
                key.SetValue("SearchTargets",
                    JsonConvert.SerializeObject(cfg.SearchTargets ?? new SearchTargetsConfig()),
                    RegistryValueKind.String);

                // === CAMPOS CLOUD ===
                key.SetValue("CloudEnabled",             cfg.CloudEnabled  ? 1 : 0,                                                    RegistryValueKind.DWord);
                key.SetValue("CloudApiUrl",              cfg.CloudApiUrl   ?? string.Empty,                                            RegistryValueKind.String);
                key.SetValue("CloudLocale",              cfg.CloudLocale   ?? string.Empty,                                            RegistryValueKind.String);
                key.SetValue("ConnectivityChecks",
                    JsonConvert.SerializeObject(cfg.ConnectivityChecks ?? new List<ConnectivityCheck>()),
                    RegistryValueKind.String);
                key.SetValue("TelemetryEnabled",         cfg.TelemetryEnabled ? 1 : 0,                                                 RegistryValueKind.DWord);
                key.SetValue("TelemetryIntervalSeconds", cfg.TelemetryIntervalSeconds,                                                  RegistryValueKind.DWord);
            }
        }

        /// <summary>
        /// Crea la clave de registro y escribe los valores por defecto para cualquier valor ausente.
        /// Es seguro llamarlo en cada inicio del servicio (idempotente).
        /// </summary>
        public void EnsureDefaults()
        {
            using (var key = Registry.LocalMachine.CreateSubKey(RegistryPath, writable: true))
            {
                if (key == null) return;

                // === CAMPOS EXISTENTES ===
                SetIfMissing(key, "CorporateQueueName",       "LexmarkBBVA",                                    RegistryValueKind.String);
                SetIfMissing(key, "PendingTaskPollingMinutes", 3,                                              RegistryValueKind.DWord);
                SetIfMissing(key, "BootstrapDomains",          DefaultBootstrapDomains,                      RegistryValueKind.String);
                SetIfMissing(key, "RoblesAiLicenseSerial",     string.Empty,                                  RegistryValueKind.String);
                SetIfMissing(key, "SearchTargets",
                    JsonConvert.SerializeObject(new SearchTargetsConfig()),                                     RegistryValueKind.String);

                // === CAMPOS CLOUD ===
                SetIfMissing(key, "CloudEnabled",             0,             RegistryValueKind.DWord);
                SetIfMissing(key, "CloudApiUrl",              string.Empty,  RegistryValueKind.String);
                SetIfMissing(key, "CloudLocale",              string.Empty,  RegistryValueKind.String);
                SetIfMissing(key, "ConnectivityChecks",       "[]",          RegistryValueKind.String);
                SetIfMissing(key, "TelemetryEnabled",         1,             RegistryValueKind.DWord);
                SetIfMissing(key, "TelemetryIntervalSeconds", 300,           RegistryValueKind.DWord);

                // === AUTO-ACTUALIZACIÓN ===
                SetIfMissing(key, "AutoUpdateEnabled", 0, RegistryValueKind.DWord);
            }
        }

        /// <summary>
        /// Lee el flag local de auto-actualización desde el registro.
        /// Este campo es independiente de AppConfiguration para evitar que la
        /// sincronización Cloud lo sobreescriba.
        /// </summary>
        /// <returns>true si auto-actualización está habilitada, false en caso contrario.</returns>
        public bool LoadAutoUpdateEnabled()
        {
            try
            {
                using (var key = Registry.LocalMachine.OpenSubKey(RegistryPath, writable: false))
                {
                    if (key == null) return false;
                    return Convert.ToInt32(key.GetValue("AutoUpdateEnabled", 0)) == 1;
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteWarning(
                    $"RegistryConfigManager.LoadAutoUpdateEnabled: error leyendo flag de auto-actualización, retornando deshabilitado. {ex.Message}",
                    AlwaysPrintLogger.EvtGenericWarning);
                return false;
            }
        }

        /// <summary>
        /// Persiste el flag local de auto-actualización en el registro.
        /// Este campo es independiente de AppConfiguration para evitar que la
        /// sincronización Cloud lo sobreescriba.
        /// Requiere privilegios de administrador (servicio o elevación).
        /// </summary>
        /// <param name="enabled">true para habilitar, false para deshabilitar.</param>
        public void SaveAutoUpdateEnabled(bool enabled)
        {
            try
            {
                using (var key = Registry.LocalMachine.CreateSubKey(RegistryPath, writable: true))
                {
                    key?.SetValue("AutoUpdateEnabled", enabled ? 1 : 0, RegistryValueKind.DWord);
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteWarning(
                    $"RegistryConfigManager.SaveAutoUpdateEnabled: error escribiendo flag de auto-actualización. {ex.Message}",
                    AlwaysPrintLogger.EvtGenericWarning);
                throw;
            }
        }

        // === MÉTODOS DE JITTER (reconexión distribuida) ===

        /// <summary>
        /// Valor por defecto de JitterWindowSeconds cuando el valor del registro es inválido o ausente.
        /// </summary>
        private const int DefaultJitterWindowSeconds = 30;

        /// <summary>
        /// Lee el valor de JitterWindowSeconds (DWORD) desde el registro.
        /// Si el valor es ausente, no es un entero válido, o está fuera del rango [5, 300],
        /// retorna el valor por defecto (30).
        /// </summary>
        /// <returns>Ventana de jitter en segundos (30 si ausente o inválido).</returns>
        public int LoadJitterWindowSeconds()
        {
            try
            {
                using (var key = Registry.LocalMachine.OpenSubKey(RegistryPath, writable: false))
                {
                    if (key == null) return DefaultJitterWindowSeconds;

                    var rawValue = key.GetValue("JitterWindowSeconds");
                    if (rawValue == null) return DefaultJitterWindowSeconds;

                    int value = Convert.ToInt32(rawValue);
                    // Si está fuera del rango válido [5, 300], retornar default
                    if (value < 5 || value > 300) return DefaultJitterWindowSeconds;
                    return value;
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteWarning(
                    $"RegistryConfigManager.LoadJitterWindowSeconds: error leyendo JitterWindowSeconds, usando default {DefaultJitterWindowSeconds}. {ex.Message}",
                    AlwaysPrintLogger.EvtGenericWarning);
                return DefaultJitterWindowSeconds;
            }
        }

        /// <summary>
        /// Escribe el valor de JitterWindowSeconds (DWORD) en el registro.
        /// Requiere privilegios de administrador (servicio o Tray elevado).
        /// </summary>
        /// <param name="value">Ventana de jitter en segundos a persistir.</param>
        /// <returns>true si la escritura fue exitosa, false si falló.</returns>
        public bool SaveJitterWindowSeconds(int value)
        {
            try
            {
                using (var key = Registry.LocalMachine.CreateSubKey(RegistryPath, writable: true))
                {
                    if (key == null)
                    {
                        AlwaysPrintLogger.WriteWarning(
                            "RegistryConfigManager.SaveJitterWindowSeconds: no se pudo abrir/crear la clave de registro.",
                            AlwaysPrintLogger.EvtGenericWarning);
                        return false;
                    }
                    key.SetValue("JitterWindowSeconds", value, RegistryValueKind.DWord);
                    return true;
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteWarning(
                    $"RegistryConfigManager.SaveJitterWindowSeconds: error escribiendo JitterWindowSeconds. {ex.Message}",
                    AlwaysPrintLogger.EvtGenericWarning);
                return false;
            }
        }

        /// <summary>
        /// Lee el valor de LastUpdateTimestamp (String ISO 8601) desde el registro.
        /// Retorna null si el valor es ausente, no es un ISO 8601 válido, o representa un tiempo futuro.
        /// </summary>
        /// <returns>DateTime en UTC del último update, o null si ausente/inválido/futuro.</returns>
        public DateTime? LoadLastUpdateTimestamp()
        {
            return LoadTimestampFromRegistry("LastUpdateTimestamp");
        }

        /// <summary>
        /// Escribe el valor de LastUpdateTimestamp (String ISO 8601) en el registro.
        /// Llamado por el Service después de una actualización MSI exitosa.
        /// </summary>
        /// <param name="utcNow">Momento actual en UTC a persistir.</param>
        public void SaveLastUpdateTimestamp(DateTime utcNow)
        {
            SaveTimestampToRegistry("LastUpdateTimestamp", utcNow);
        }

        /// <summary>
        /// Lee el valor de LastRestartTimestamp (String ISO 8601) desde el registro.
        /// Retorna null si el valor es ausente, no es un ISO 8601 válido, o representa un tiempo futuro.
        /// </summary>
        /// <returns>DateTime en UTC del último reinicio de Tray, o null si ausente/inválido/futuro.</returns>
        public DateTime? LoadLastRestartTimestamp()
        {
            return LoadTimestampFromRegistry("LastRestartTimestamp");
        }

        /// <summary>
        /// Escribe el valor de LastRestartTimestamp (String ISO 8601) en el registro.
        /// Llamado por el Service justo antes de reiniciar el Tray.
        /// </summary>
        /// <param name="utcNow">Momento actual en UTC a persistir.</param>
        public void SaveLastRestartTimestamp(DateTime utcNow)
        {
            SaveTimestampToRegistry("LastRestartTimestamp", utcNow);
        }

        /// <summary>
        /// Lee un timestamp ISO 8601 del registro y lo valida.
        /// Retorna null si: ausente, formato inválido, o tiempo futuro.
        /// </summary>
        /// <param name="valueName">Nombre del valor en el registro.</param>
        /// <returns>DateTime en UTC si válido y no futuro, null en caso contrario.</returns>
        private DateTime? LoadTimestampFromRegistry(string valueName)
        {
            try
            {
                using (var key = Registry.LocalMachine.OpenSubKey(RegistryPath, writable: false))
                {
                    if (key == null) return null;

                    var rawValue = key.GetValue(valueName) as string;
                    if (string.IsNullOrWhiteSpace(rawValue)) return null;

                    // Intentar parsear como ISO 8601 en UTC
                    if (!DateTime.TryParse(rawValue, CultureInfo.InvariantCulture,
                            DateTimeStyles.RoundtripKind | DateTimeStyles.AdjustToUniversal, out DateTime parsed))
                    {
                        AlwaysPrintLogger.WriteWarning(
                            $"RegistryConfigManager.{valueName}: valor '{rawValue}' no es un ISO 8601 válido, tratando como ausente.",
                            AlwaysPrintLogger.EvtGenericWarning);
                        return null;
                    }

                    // Asegurar que el resultado esté en UTC
                    DateTime utcParsed = parsed.Kind == DateTimeKind.Utc ? parsed : parsed.ToUniversalTime();

                    // Si el timestamp es futuro, tratarlo como inválido
                    if (utcParsed > DateTime.UtcNow)
                    {
                        AlwaysPrintLogger.WriteWarning(
                            $"RegistryConfigManager.{valueName}: timestamp '{rawValue}' es futuro, tratando como ausente.",
                            AlwaysPrintLogger.EvtGenericWarning);
                        return null;
                    }

                    return utcParsed;
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteWarning(
                    $"RegistryConfigManager.{valueName}: error leyendo timestamp, tratando como ausente. {ex.Message}",
                    AlwaysPrintLogger.EvtGenericWarning);
                return null;
            }
        }

        /// <summary>
        /// Escribe un timestamp en formato ISO 8601 (con segundos, UTC) en el registro.
        /// Maneja errores sin interrumpir la operación del caller.
        /// </summary>
        /// <param name="valueName">Nombre del valor en el registro.</param>
        /// <param name="utcNow">Momento en UTC a persistir.</param>
        private void SaveTimestampToRegistry(string valueName, DateTime utcNow)
        {
            try
            {
                // Formatear como ISO 8601 con precisión de segundos en UTC (ej: "2026-01-15T10:30:00Z")
                string isoString = utcNow.ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture);

                using (var key = Registry.LocalMachine.CreateSubKey(RegistryPath, writable: true))
                {
                    if (key == null)
                    {
                        AlwaysPrintLogger.WriteWarning(
                            $"RegistryConfigManager.{valueName}: no se pudo abrir/crear la clave de registro.",
                            AlwaysPrintLogger.EvtGenericWarning);
                        return;
                    }
                    key.SetValue(valueName, isoString, RegistryValueKind.String);
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteWarning(
                    $"RegistryConfigManager.{valueName}: error escribiendo timestamp. {ex.Message}",
                    AlwaysPrintLogger.EvtGenericWarning);
            }
        }

        private static void SetIfMissing(RegistryKey key, string name, object value, RegistryValueKind kind)
        {
            if (key.GetValue(name) == null)
                key.SetValue(name, value, kind);
        }

        private static void ValidateConfiguration(AppConfiguration cfg)
        {
            if (cfg.PendingTaskPollingMinutes < 1 || cfg.PendingTaskPollingMinutes > 1440)
                throw new ArgumentOutOfRangeException("PendingTaskPollingMinutes debe estar entre 1 y 1440.");

            // Eliminar caracteres potencialmente peligrosos de los campos de texto.
            cfg.CorporateQueueName    = Sanitize(cfg.CorporateQueueName,    64);
            cfg.RoblesAiLicenseSerial = Sanitize(cfg.RoblesAiLicenseSerial, 128);
            cfg.BootstrapDomains      = Sanitize(cfg.BootstrapDomains,       512);

            if (cfg.SearchTargets != null)
            {
#nullable disable
                // CS8602 es un falso positivo del analizador Roslyn en net48 —
                // el if garantiza no-null pero el analizador no lo infiere en variables locales.
                SearchTargetsConfig st = cfg.SearchTargets;
                st.Ips    = Sanitize(st.Ips,    1024);
                st.Ranges = Sanitize(st.Ranges, 1024);
                cfg.SearchTargets = st;
#nullable restore
            }
        }

        private static string Sanitize(string? value, int maxLength)
        {
            if (string.IsNullOrWhiteSpace(value)) return string.Empty;
            // value no puede ser null aquí — IsNullOrWhiteSpace lo garantiza,
            // pero el analizador de Roslyn en net48 no infiere el flujo de control.
            string trimmed = value!.Trim();
            return trimmed.Length > maxLength ? trimmed.Substring(0, maxLength) : trimmed;
        }
    }
}
