using System;
using System.Collections.Generic;
using Newtonsoft.Json;

namespace AlwaysPrint.Shared.Configuration
{
    public class AppConfiguration
    {
        // === PROPIEDADES EXISTENTES (sin modificación) ===
        public string CorporateQueueName { get; set; } = "LexmarkBBVA";
        public SearchTargetsConfig SearchTargets { get; set; } = new SearchTargetsConfig();
        public int PendingTaskPollingMinutes { get; set; } = 3;
        public string BootstrapDomains { get; set; } = "apps.iol.pe,sistemas.com.pe";
        public string RoblesAiLicenseSerial { get; set; } = string.Empty;

        // === INTEGRACIÓN CLOUD ===
        public bool   CloudEnabled             { get; set; } = false;
        public string CloudApiUrl              { get; set; } = string.Empty;
        public string CloudLocale              { get; set; } = string.Empty;
        public List<ConnectivityCheck> ConnectivityChecks { get; set; } = new List<ConnectivityCheck>();
        public bool   TelemetryEnabled         { get; set; } = true;
        public int    TelemetryIntervalSeconds { get; set; } = 300;

        /// <summary>
        /// Valida la configuración Cloud. Lanza excepción si algún valor es inválido.
        /// </summary>
        public void Validate()
        {
            // Validar intervalo de telemetría mínimo
            if (TelemetryIntervalSeconds < 60)
                throw new ArgumentOutOfRangeException(nameof(TelemetryIntervalSeconds),
                    "TelemetryIntervalSeconds debe ser >= 60.");

            // Validar URL del servidor Cloud si está definida
            if (!string.IsNullOrEmpty(CloudApiUrl) && !Uri.IsWellFormedUriString(CloudApiUrl, UriKind.Absolute))
                throw new ArgumentException("CloudApiUrl debe ser una URI absoluta válida.", nameof(CloudApiUrl));

            // Validar cada check de conectividad
            foreach (var check in ConnectivityChecks ?? new List<ConnectivityCheck>())
            {
                // Validar rango de puerto
                if (check.Port.HasValue && (check.Port.Value < 0 || check.Port.Value > 65535))
                    throw new ArgumentOutOfRangeException(nameof(check.Port),
                        $"Port {check.Port.Value} fuera del rango 0-65535.");

                // Validar tipo de check
                var tiposValidos = new[] { "http", "tcp", "ping", "dns" };
                if (!Array.Exists(tiposValidos, t => t == check.Type))
                    throw new ArgumentException($"Tipo de check inválido: '{check.Type}'.", nameof(check.Type));
            }
        }
    }

    public class SearchTargetsConfig
    {
        [JsonProperty("ips")]
        public string Ips { get; set; } = string.Empty;

        [JsonProperty("ranges")]
        public string Ranges { get; set; } = string.Empty;
    }

    /// <summary>
    /// Representa un check de conectividad configurable.
    /// Tipos válidos: "http", "tcp", "ping", "dns".
    /// </summary>
    public class ConnectivityCheck
    {
        [JsonProperty("id")]         public string  Id        { get; set; } = string.Empty;
        [JsonProperty("type")]       public string  Type      { get; set; } = "http";
        [JsonProperty("url")]        public string? Url       { get; set; }
        [JsonProperty("host")]       public string? Host      { get; set; }
        [JsonProperty("hostname")]   public string? Hostname  { get; set; }
        [JsonProperty("port")]       public int?    Port      { get; set; }
        [JsonProperty("timeout_ms")] public int     TimeoutMs { get; set; } = 5000;
    }
}
