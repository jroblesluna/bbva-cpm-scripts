using System;
using System.Collections.Generic;
using Microsoft.Win32;
using Newtonsoft.Json;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrint.Shared.Configuration
{
    /// <summary>
    /// Lee y escribe la configuración de AlwaysPrint en HKLM\SOFTWARE\Robles.AI\AlwaysPrint.
    /// La escritura requiere que el caller tenga privilegios de administrador (el servicio).
    /// </summary>
    public class RegistryConfigManager
    {
        public const string RegistryPath = @"SOFTWARE\Robles.AI\AlwaysPrint";

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
                    cfg.BootstrapDomains    = key.GetValue("BootstrapDomains",    "alwaysprint.apps.iol.pe") as string
                                             ?? "alwaysprint.apps.iol.pe";

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
                key.SetValue("BootstrapDomains",             cfg.BootstrapDomains    ?? "alwaysprint.apps.iol.pe", RegistryValueKind.String);
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
                SetIfMissing(key, "BootstrapDomains",          "alwaysprint.apps.iol.pe",                      RegistryValueKind.String);
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
