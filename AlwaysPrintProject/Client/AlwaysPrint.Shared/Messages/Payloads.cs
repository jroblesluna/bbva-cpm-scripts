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

        /// <summary>
        /// Ventana de jitter en segundos recibida de la Cloud (nivel organización).
        /// El Service lo persiste en HKLM porque tiene privilegios de escritura.
        /// Null si no vino en el payload (no se modifica el valor existente).
        /// </summary>
        [JsonProperty("jitterWindowSeconds")]
        public int? JitterWindowSeconds { get; set; }
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

        /// <summary>IP de la impresora de contingencia (obtenida del default_printer de la workstation).</summary>
        [JsonProperty("printerIp")]
        public string? PrinterIp { get; set; }
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

    // ── Recursos de VLAN ────────────────────────────────────────────────────────

    /// <summary>
    /// Payload enviado del Tray al Service para que persista los recursos
    /// de la VLAN en disco (C:\ProgramData\AlwaysPrint\config\resources.json).
    /// Contiene metadata de VLAN, impresoras de contingencia y remote_queue_path.
    /// </summary>
    public class SaveResourcesPayload
    {
        /// <summary>JSON completo de los recursos descargados del endpoint /resources.</summary>
        [JsonProperty("resourcesJson")]
        public string ResourcesJson { get; set; } = string.Empty;
    }

    // ── On-Demand Triggers y acciones de servicio ────────────────────────────────

    /// <summary>
    /// Payload para solicitar ejecución de un trigger OnDemand.
    /// Tray → Service.
    /// </summary>
    public class ExecuteOnDemandTriggerPayload
    {
        [JsonProperty("label")]
        public string Label { get; set; } = string.Empty;
    }

    /// <summary>
    /// Payload para solicitar acción sobre un servicio Windows.
    /// Tray → Service.
    /// </summary>
    public class ServiceActionPayload
    {
        /// <summary>Nombre del servicio Windows (ej: "lpmc_universal_service").</summary>
        [JsonProperty("serviceName")]
        public string ServiceName { get; set; } = string.Empty;

        /// <summary>Acción a ejecutar: "Start" o "Restart".</summary>
        [JsonProperty("action")]
        public string Action { get; set; } = string.Empty;
    }

    /// <summary>
    /// Respuesta del Service al Tray tras una acción sobre servicio.
    /// </summary>
    public class ServiceActionResponsePayload
    {
        [JsonProperty("serviceName")]
        public string ServiceName { get; set; } = string.Empty;

        [JsonProperty("success")]
        public bool Success { get; set; }

        /// <summary>Estado resultante del servicio tras la acción.</summary>
        [JsonProperty("newState")]
        public string NewState { get; set; } = string.Empty;

        [JsonProperty("message")]
        public string? Message { get; set; }
    }

    // ── Connectivity Check ──────────────────────────────────────────────────────

    /// <summary>
    /// URL individual para el check de conectividad con metadatos.
    /// </summary>
    public class ConnectivityUrl
    {
        [JsonProperty("url")]
        public string Url { get; set; } = string.Empty;

        [JsonProperty("critical")]
        public bool Critical { get; set; } = true;

        [JsonProperty("function")]
        public string Function { get; set; } = string.Empty;
    }

    /// <summary>
    /// Payload enviado del Service al Tray para ejecutar un check de conectividad
    /// contra una lista de URLs. El Tray ejecuta los HTTP checks, muestra
    /// notificación y escribe en log.
    /// </summary>
    public class ConnectivityCheckPayload
    {
        [JsonProperty("urls")]
        public List<ConnectivityUrl> Urls { get; set; } = new();

        [JsonProperty("timeout_seconds")]
        public int TimeoutSeconds { get; set; } = 5;

        [JsonProperty("notification_green_timeout_seconds")]
        public int NotificationGreenTimeoutSeconds { get; set; } = 5;

        [JsonProperty("notification_yellow_timeout_seconds")]
        public int NotificationYellowTimeoutSeconds { get; set; } = 10;
    }
}

    // ── Debugging Remoto (captura con privilegios LocalSystem) ────────────────────

    /// <summary>
    /// Payload enviado del Tray al Service para iniciar una captura de debugging.
    /// El Service ejecuta la captura con privilegios LocalSystem.
    /// </summary>
    public class StartDebuggingCapturePayload
    {
        /// <summary>ID único de la sesión de debugging (asignado por el backend).</summary>
        [JsonProperty("debuggingId")]
        public string DebuggingId { get; set; } = string.Empty;

        /// <summary>Duración máxima de la captura en segundos.</summary>
        [JsonProperty("durationSeconds")]
        public int DurationSeconds { get; set; }

        /// <summary>Perfil de debugging serializado como JSON (targets, nombre, etc.).</summary>
        [JsonProperty("profileJson")]
        public string ProfileJson { get; set; } = string.Empty;
    }

    /// <summary>
    /// Payload enviado del Tray al Service para detener una captura activa.
    /// </summary>
    public class StopDebuggingCapturePayload
    {
        [JsonProperty("debuggingId")]
        public string DebuggingId { get; set; } = string.Empty;
    }

    /// <summary>
    /// Payload push del Service al Tray cuando la captura finaliza correctamente.
    /// El Tray usa esta información para reportar debugging_ready al backend.
    /// </summary>
    public class DebuggingCaptureReadyPayload
    {
        [JsonProperty("debuggingId")]
        public string DebuggingId { get; set; } = string.Empty;

        /// <summary>Tamaño total de los archivos capturados en bytes.</summary>
        [JsonProperty("totalSizeBytes")]
        public long TotalSizeBytes { get; set; }
    }

    /// <summary>
    /// Payload push del Service al Tray cuando ocurre un error durante la captura.
    /// </summary>
    public class DebuggingCaptureErrorPayload
    {
        [JsonProperty("debuggingId")]
        public string DebuggingId { get; set; } = string.Empty;

        [JsonProperty("errorMessage")]
        public string ErrorMessage { get; set; } = string.Empty;
    }

    /// <summary>
    /// Payload enviado del Tray al Service para empaquetar los datos de debugging en ZIP.
    /// Se usa cuando el backend solicita request_debug_upload.
    /// </summary>
    public class PackageDebuggingZipPayload
    {
        [JsonProperty("debuggingId")]
        public string DebuggingId { get; set; } = string.Empty;
    }

    /// <summary>
    /// Respuesta del Service al Tray con la ruta del ZIP generado.
    /// El Tray usa esta ruta para subir el archivo al backend.
    /// </summary>
    public class DebuggingZipReadyPayload
    {
        [JsonProperty("debuggingId")]
        public string DebuggingId { get; set; } = string.Empty;

        /// <summary>Ruta absoluta al archivo ZIP en disco.</summary>
        [JsonProperty("zipPath")]
        public string ZipPath { get; set; } = string.Empty;
    }

    /// <summary>
    /// Payload enviado del Tray al Service para eliminar datos de una sesión de debugging.
    /// </summary>
    public class DeleteDebuggingDataPayload
    {
        [JsonProperty("debuggingId")]
        public string DebuggingId { get; set; } = string.Empty;
    }

    // ── Progreso de Ejecución OnDemand ───────────────────────────────────────────

    /// <summary>
    /// Payload push del Service al Tray con el progreso de un paso de ejecución OnDemand.
    /// El Tray lo muestra en tiempo real en la ventana de progreso.
    /// </summary>
    public class OnDemandActionProgressPayload
    {
        /// <summary>Label del trigger OnDemand que se está ejecutando.</summary>
        [JsonProperty("triggerLabel")]
        public string TriggerLabel { get; set; } = string.Empty;

        /// <summary>Nombre/descripción del paso que se ejecutó.</summary>
        [JsonProperty("stepName")]
        public string StepName { get; set; } = string.Empty;

        /// <summary>Tipo de acción: StopService, StartService, DeleteFolderContents, etc.</summary>
        [JsonProperty("actionType")]
        public string ActionType { get; set; } = string.Empty;

        /// <summary>Estado del paso: "running", "ok", "error", "completed".</summary>
        [JsonProperty("status")]
        public string Status { get; set; } = string.Empty;

        /// <summary>Mensaje adicional (detalle del resultado o error).</summary>
        [JsonProperty("message")]
        public string? Message { get; set; }

        /// <summary>true si este es el último mensaje (ejecución completó).</summary>
        [JsonProperty("isComplete")]
        public bool IsComplete { get; set; }

        /// <summary>Resultado global de la ejecución (solo relevante si isComplete=true).</summary>
        [JsonProperty("overallSuccess")]
        public bool OverallSuccess { get; set; }

        /// <summary>Duración total en ms (solo relevante si isComplete=true).</summary>
        [JsonProperty("durationMs")]
        public long DurationMs { get; set; }
    }
