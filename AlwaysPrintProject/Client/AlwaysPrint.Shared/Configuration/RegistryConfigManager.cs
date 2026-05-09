using System;
using Microsoft.Win32;
using Newtonsoft.Json;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrint.Shared.Configuration
{
    /// <summary>
    /// Reads and writes AlwaysPrint configuration from/to HKLM\SOFTWARE\Robles.AI\AlwaysPrint.
    /// Writing requires the caller to have administrative privileges (the service).
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

                    cfg.CorporateQueueName  = key.GetValue("CorporateQueueName",  string.Empty) as string ?? string.Empty;
                    cfg.RoblesAiLicenseSerial = key.GetValue("RoblesAiLicenseSerial", string.Empty) as string ?? string.Empty;
                    cfg.BootstrapDomains    = key.GetValue("BootstrapDomains",    "robles.ai,iol.pe,sistemas.com.pe") as string
                                             ?? "robles.ai,iol.pe,sistemas.com.pe";

                    var rawPoll = key.GetValue("PendingTaskPollingMinutes", 3);
                    cfg.PendingTaskPollingMinutes = Math.Max(1, Convert.ToInt32(rawPoll));

                    var rawTargets = key.GetValue("SearchTargets", null) as string;
                    if (!string.IsNullOrWhiteSpace(rawTargets))
                        cfg.SearchTargets = JsonConvert.DeserializeObject<SearchTargetsConfig>(rawTargets!)
                                            ?? new SearchTargetsConfig();
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
        /// Persists configuration. Caller must have HKLM write access (service running as LocalSystem).
        /// </summary>
        public void Save(AppConfiguration cfg)
        {
            if (cfg == null) throw new ArgumentNullException(nameof(cfg));
            ValidateConfiguration(cfg);

            using (var key = Registry.LocalMachine.CreateSubKey(RegistryPath, writable: true))
            {
                if (key == null)
                    throw new InvalidOperationException("Cannot create/open registry key – insufficient privileges.");

                key.SetValue("CorporateQueueName",          cfg.CorporateQueueName  ?? string.Empty,            RegistryValueKind.String);
                key.SetValue("PendingTaskPollingMinutes",    Math.Max(1, cfg.PendingTaskPollingMinutes),          RegistryValueKind.DWord);
                key.SetValue("BootstrapDomains",             cfg.BootstrapDomains    ?? "robles.ai,iol.pe,sistemas.com.pe", RegistryValueKind.String);
                key.SetValue("RoblesAiLicenseSerial",        cfg.RoblesAiLicenseSerial ?? string.Empty,          RegistryValueKind.String);
                key.SetValue("SearchTargets",
                    JsonConvert.SerializeObject(cfg.SearchTargets ?? new SearchTargetsConfig()),
                    RegistryValueKind.String);
            }
        }

        /// <summary>
        /// Creates the registry key and writes defaults for any missing values.
        /// Safe to call on every service start.
        /// </summary>
        public void EnsureDefaults()
        {
            using (var key = Registry.LocalMachine.CreateSubKey(RegistryPath, writable: true))
            {
                if (key == null) return;

                SetIfMissing(key, "CorporateQueueName",       string.Empty,                                   RegistryValueKind.String);
                SetIfMissing(key, "PendingTaskPollingMinutes", 3,                                              RegistryValueKind.DWord);
                SetIfMissing(key, "BootstrapDomains",          "robles.ai,iol.pe,sistemas.com.pe",            RegistryValueKind.String);
                SetIfMissing(key, "RoblesAiLicenseSerial",     string.Empty,                                  RegistryValueKind.String);
                SetIfMissing(key, "SearchTargets",
                    JsonConvert.SerializeObject(new SearchTargetsConfig()),                                     RegistryValueKind.String);
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
                throw new ArgumentOutOfRangeException("PendingTaskPollingMinutes must be between 1 and 1440.");

            // Strip potential registry-injection characters from string fields.
            cfg.CorporateQueueName    = Sanitize(cfg.CorporateQueueName,    64);
            cfg.RoblesAiLicenseSerial = Sanitize(cfg.RoblesAiLicenseSerial, 128);
            cfg.BootstrapDomains      = Sanitize(cfg.BootstrapDomains,       512);

            if (cfg.SearchTargets != null)
            {
                SearchTargetsConfig st = cfg.SearchTargets;
                st.Ips    = Sanitize(st.Ips,    1024);
                st.Ranges = Sanitize(st.Ranges, 1024);
                cfg.SearchTargets = st;
            }
        }

        private static string Sanitize(string? value, int maxLength)
        {
            if (string.IsNullOrWhiteSpace(value)) return string.Empty;
            value = value.Trim();
            return value.Length > maxLength ? value.Substring(0, maxLength) : value;
        }
    }
}
