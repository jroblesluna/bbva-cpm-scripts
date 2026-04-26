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
}
