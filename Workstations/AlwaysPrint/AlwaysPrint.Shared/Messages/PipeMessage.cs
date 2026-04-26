using System;
using Newtonsoft.Json;

namespace AlwaysPrint.Shared.Messages
{
    /// <summary>
    /// Envelope for all Named Pipe messages. Payload is a JSON-serialized inner DTO.
    /// Messages are transmitted as single-line JSON strings terminated with '\n'.
    /// </summary>
    public class PipeMessage
    {
        [JsonProperty("id")]
        public string Id { get; set; } = Guid.NewGuid().ToString("N");

        [JsonProperty("correlationId")]
        public string? CorrelationId { get; set; }

        [JsonProperty("type")]
        public MessageType Type { get; set; }

        [JsonProperty("timestamp")]
        public DateTime Timestamp { get; set; } = DateTime.UtcNow;

        /// <summary>JSON-encoded inner payload. Use GetPayload/SetPayload helpers.</summary>
        [JsonProperty("payload")]
        public string? Payload { get; set; }

        // --- Convenience factory methods ---

        public static PipeMessage Create(MessageType type, object? payload = null)
        {
            var msg = new PipeMessage { Type = type };
            if (payload != null)
                msg.Payload = JsonConvert.SerializeObject(payload);
            return msg;
        }

        public static PipeMessage Reply(PipeMessage request, MessageType type, object? payload = null)
        {
            var msg = Create(type, payload);
            msg.CorrelationId = request.Id;
            return msg;
        }

        public T? GetPayload<T>() where T : class
        {
            if (string.IsNullOrWhiteSpace(Payload)) return null;
            return JsonConvert.DeserializeObject<T>(Payload!);
        }

        public string Serialize() => JsonConvert.SerializeObject(this);

        public static PipeMessage? Deserialize(string json) =>
            JsonConvert.DeserializeObject<PipeMessage>(json);
    }
}
