using System.Collections.Generic;
using AlwaysPrint.Shared.Configuration;
using Newtonsoft.Json;

namespace AlwaysPrint.Shared.Messages
{
    // ── Requests ────────────────────────────────────────────────────────────────

    public class TrayInitializedPayload
    {
        [JsonProperty("success")]
        public bool Success { get; set; }

        [JsonProperty("details")]
        public string? Details { get; set; }
    }

    public class UpdateConfigurationPayload
    {
        [JsonProperty("configuration")]
        public AppConfiguration Configuration { get; set; } = new AppConfiguration();
    }

    public class CheckCorporateQueuePayload
    {
        [JsonProperty("queueName")]
        public string QueueName { get; set; } = string.Empty;
    }

    public class CheckServiceStatusPayload
    {
        [JsonProperty("serviceName")]
        public string ServiceName { get; set; } = string.Empty;
    }

    // ── Responses ───────────────────────────────────────────────────────────────

    public class AckPayload
    {
        [JsonProperty("success")]
        public bool Success { get; set; }

        [JsonProperty("message")]
        public string? Message { get; set; }
    }

    public class GetConfigurationResponsePayload
    {
        [JsonProperty("configuration")]
        public AppConfiguration Configuration { get; set; } = new AppConfiguration();
    }

    public class CheckCorporateQueueResponsePayload
    {
        [JsonProperty("exists")]
        public bool Exists { get; set; }

        /// <summary>true = routed through loopback CPM agent (cloud mode).</summary>
        [JsonProperty("cloud")]
        public bool Cloud { get; set; }

        [JsonProperty("portType")]
        public string? PortType { get; set; }

        [JsonProperty("details")]
        public string? Details { get; set; }
    }

    public class CheckServiceStatusResponsePayload
    {
        [JsonProperty("serviceName")]
        public string ServiceName { get; set; } = string.Empty;

        [JsonProperty("state")]
        public string State { get; set; } = string.Empty;

        [JsonProperty("binaryPath")]
        public string? BinaryPath { get; set; }

        [JsonProperty("startTime")]
        public string? StartTime { get; set; }
    }

    public class ErrorPayload
    {
        [JsonProperty("code")]
        public string Code { get; set; } = "UNKNOWN";

        [JsonProperty("message")]
        public string Message { get; set; } = string.Empty;
    }

    // ── Cloud ────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Payload enviado del Tray al Service para aplicar una configuración
    /// descargada de APCM.
    /// </summary>
    public class CloudConfigurationReceivedPayload
    {
        [JsonProperty("configuration")]
        public AppConfiguration Configuration { get; set; } = new AppConfiguration();

        [JsonProperty("configHash")]
        public string ConfigHash { get; set; } = string.Empty;

        /// <summary>Origen de la configuración: "cloud" o "cache".</summary>
        [JsonProperty("source")]
        public string Source { get; set; } = "cloud";
    }

    /// <summary>
    /// Representa un evento de desconexión registrado en el log de telemetría.
    /// </summary>
    public class DisconnectionEvent
    {
        [JsonProperty("startedAt")]
        public string StartedAt { get; set; } = string.Empty;

        [JsonProperty("reconnectedAt")]
        public string? ReconnectedAt { get; set; }

        [JsonProperty("durationSeconds")]
        public long? DurationSeconds { get; set; }
    }

    /// <summary>
    /// Payload enviado del Service al Tray con datos de telemetría para
    /// reenviar a APCM.
    /// </summary>
    public class TelemetryPayload
    {
        /// <summary>Estado de la cola corporativa: "ok", "missing" o "error".</summary>
        [JsonProperty("queueStatus")]
        public string QueueStatus { get; set; } = string.Empty;

        [JsonProperty("contingencyActive")]
        public bool ContingencyActive { get; set; }

        [JsonProperty("jobsIdentified")]
        public int JobsIdentified { get; set; }

        [JsonProperty("avgReleaseTimeMs")]
        public long? AvgReleaseTimeMs { get; set; }

        [JsonProperty("disconnectionLog")]
        public List<DisconnectionEvent> DisconnectionLog { get; set; } = new List<DisconnectionEvent>();
    }

    /// <summary>
    /// Payload enviado del Service al Tray con datos de un trabajo completado
    /// para acumular en el TelemetryReporter (IPC ReportTelemetry).
    /// </summary>
    public class ReportTelemetryPayload
    {
        [JsonProperty("jobCount")]
        public int JobCount { get; set; }

        [JsonProperty("releaseTimeMs")]
        public long ReleaseTimeMs { get; set; }
    }

    /// <summary>
    /// Payload enviado del Service al Tray con el estado actual de la
    /// conexión Cloud.
    /// </summary>
    public class CloudStatusResponsePayload
    {
        [JsonProperty("isConnected")]
        public bool IsConnected { get; set; }

        [JsonProperty("lastConnectedAt")]
        public string? LastConnectedAt { get; set; }

        [JsonProperty("configHash")]
        public string? ConfigHash { get; set; }

        [JsonProperty("usingCachedConfig")]
        public bool UsingCachedConfig { get; set; }
    }
}
