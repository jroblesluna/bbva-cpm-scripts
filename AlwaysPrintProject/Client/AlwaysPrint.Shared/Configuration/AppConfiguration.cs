using System;
using System.Collections.Generic;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace AlwaysPrint.Shared.Configuration
{
    public class AppConfiguration
    {
        // === PROPIEDADES EXISTENTES (sin modificación) ===
        public string CorporateQueueName { get; set; } = "LexmarkBBVA";
        public SearchTargetsConfig SearchTargets { get; set; } = new SearchTargetsConfig();
        public int PendingTaskPollingMinutes { get; set; } = 3;
#if ENV_DEV
        public string BootstrapDomains { get; set; } = "dev.iol.pe";
#else
        public string BootstrapDomains { get; set; } = "apps.iol.pe,sistemas.com.pe";
#endif
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
        [JsonConverter(typeof(StringOrArrayConverter))]
        public string Ips { get; set; } = string.Empty;

        [JsonProperty("ranges")]
        [JsonConverter(typeof(StringOrArrayConverter))]
        public string Ranges { get; set; } = string.Empty;
    }

    /// <summary>
    /// Converter que acepta tanto un string CSV como un array JSON ["a","b"]
    /// y lo convierte a string CSV separado por comas.
    /// Esto permite compatibilidad entre el formato del backend (arrays) y el cliente (CSV).
    /// </summary>
    public class StringOrArrayConverter : JsonConverter<string>
    {
        public override string ReadJson(JsonReader reader, Type objectType, string existingValue, bool hasExistingValue, JsonSerializer serializer)
        {
            var token = JToken.Load(reader);

            if (token.Type == JTokenType.Array)
            {
                // Convertir array ["a", "b"] → "a,b"
                var items = token.ToObject<List<string>>();
                return items != null ? string.Join(",", items) : string.Empty;
            }

            if (token.Type == JTokenType.String)
            {
                return token.ToString();
            }

            if (token.Type == JTokenType.Null)
            {
                return string.Empty;
            }

            return string.Empty;
        }

        public override void WriteJson(JsonWriter writer, string value, JsonSerializer serializer)
        {
            // Escribir siempre como string CSV
            writer.WriteValue(value ?? string.Empty);
        }
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
