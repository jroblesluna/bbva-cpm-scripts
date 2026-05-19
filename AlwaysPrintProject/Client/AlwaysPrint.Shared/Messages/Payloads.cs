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

        /// <summary>
        /// Flag independiente de auto-actualización. Se persiste por separado
        /// de AppConfiguration para evitar sobreescritura por sincronización Cloud.
        /// Nullable: si es null, el Service no modifica el valor actual en registro.
        /// </summary>
        [JsonProperty("autoUpdateEnabled")]
        public bool? AutoUpdateEnabled { get; set; }
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

    // ── Configuración de Acciones ───────────────────────────────────────────────

    /// <summary>
    /// Payload enviado del Tray al Service para que persista la configuración
    /// de acciones en disco (C:\ProgramData\AlwaysPrint\config\active.alwaysconfig).
    /// El Tray descarga el JSON de la Cloud y lo envía al Service porque solo
    /// LocalSystem tiene permisos de escritura en ProgramData.
    /// </summary>
    public class SaveActionConfigPayload
    {
        [JsonProperty("configJson")]
        public string ConfigJson { get; set; } = string.Empty;

        /// <summary>Hash SHA256 (8 chars) para verificación de integridad.</summary>
        [JsonProperty("hash")]
        public string Hash { get; set; } = string.Empty;
    }

    // ── Actualizaciones automáticas ─────────────────────────────────────────────

    /// <summary>
    /// Payload enviado del Tray al Service para solicitar la instalación
    /// de un MSI de actualización.
    /// </summary>
    public class InstallUpdatePayload
    {
        [JsonProperty("msiFilePath")]
        public string MsiFilePath { get; set; } = string.Empty;
    }

    /// <summary>
    /// Payload enviado del Service al Tray con el resultado de la
    /// instalación del MSI.
    /// </summary>
    public class InstallUpdateResponsePayload
    {
        [JsonProperty("success")]
        public bool Success { get; set; }

        [JsonProperty("message")]
        public string? Message { get; set; }

        [JsonProperty("exitCode")]
        public int ExitCode { get; set; }
    }

    // ── Contingencia Forzada ────────────────────────────────────────────────────

    /// <summary>
    /// Payload enviado del Tray al Service cuando se recibe un mensaje
    /// de contingencia forzada desde la Cloud.
    /// </summary>
    public class ForcedContingencyPayload
    {
        /// <summary>true = contingencia forzada activada, false = desactivada.</summary>
        [JsonProperty("enabled")]
        public bool Enabled { get; set; }

        /// <summary>Origen del cambio: "organization", "vlan" o "workstation".</summary>
        [JsonProperty("source")]
        public string Source { get; set; } = string.Empty;

        /// <summary>Nombre del origen (nombre de la organización, VLAN o workstation).</summary>
        [JsonProperty("sourceName")]
        public string SourceName { get; set; } = string.Empty;
    }

    /// <summary>
    /// Payload push del Service al Tray con el resultado de la ejecución de contingencia.
    /// El Tray muestra un balloon tip al usuario con esta información.
    /// </summary>
    public class ContingencyResultPayload
    {
        /// <summary>true = contingencia ejecutada exitosamente.</summary>
        [JsonProperty("success")]
        public bool Success { get; set; }

        /// <summary>true = entró en contingencia, false = salió de contingencia.</summary>
        [JsonProperty("entered")]
        public bool Entered { get; set; }

        /// <summary>Nombre de la impresora a la que se conectó (solo si entered=true y success=true).</summary>
        [JsonProperty("printerName")]
        public string? PrinterName { get; set; }

        /// <summary>IP:puerto de la impresora (solo si entered=true y success=true).</summary>
        [JsonProperty("printerAddress")]
        public string? PrinterAddress { get; set; }

        /// <summary>Mensaje descriptivo del resultado.</summary>
        [JsonProperty("message")]
        public string Message { get; set; } = string.Empty;
    }
}
