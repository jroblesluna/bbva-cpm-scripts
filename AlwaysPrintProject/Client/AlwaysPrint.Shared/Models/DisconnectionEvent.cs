using System;

namespace AlwaysPrint.Shared.Models
{
    /// <summary>
    /// Representa un evento de desconexión WebSocket registrado internamente
    /// por el TelemetryReporter para seguimiento de conectividad.
    /// </summary>
    public class DisconnectionEvent
    {
        /// <summary>Momento UTC en que se detectó la desconexión.</summary>
        public DateTime StartedAt { get; set; }

        /// <summary>Momento UTC en que se restableció la conexión (null si aún desconectado).</summary>
        public DateTime? ReconnectedAt { get; set; }

        /// <summary>Duración de la desconexión en segundos enteros (null si aún desconectado).</summary>
        public int? DurationSeconds { get; set; }
    }
}
