using Newtonsoft.Json;

namespace AlwaysPrint.Shared.Models
{
    /// <summary>
    /// Resultado de una verificación de conectividad ejecutada por el ConnectivityMonitor.
    /// Se envía a APCM como mensaje "connectivity_result" vía WebSocket.
    /// </summary>
    public class ConnectivityCheckResult
    {
        /// <summary>Identificador único del check configurado.</summary>
        [JsonProperty("check_id")]
        public string CheckId { get; set; } = string.Empty;

        /// <summary>Tipo de check ejecutado: http, tcp, ping, dns.</summary>
        [JsonProperty("check_type")]
        public string CheckType { get; set; } = string.Empty;

        /// <summary>Indica si la verificación fue exitosa.</summary>
        [JsonProperty("success")]
        public bool Success { get; set; }

        /// <summary>Latencia en milisegundos (null si la verificación falló).</summary>
        [JsonProperty("latency_ms")]
        public long? LatencyMs { get; set; }

        /// <summary>Mensaje de error cuando la verificación falla (null si fue exitosa).</summary>
        [JsonProperty("error")]
        public string? Error { get; set; }
    }
}
