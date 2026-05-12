namespace AlwaysPrint.Shared.Messages
{
    public enum MessageType
    {
        // Handshake / liveness
        Ping,
        Pong,

        // Tray lifecycle
        TrayInitialized,

        // Configuration
        UpdateConfiguration,
        GetCurrentConfiguration,

        // Task commands
        CheckCorporateQueue,
        CheckServiceStatus,

        // Responses
        Ack,
        Error,

        // Integración Cloud
        CloudConfigurationReceived,  // Tray → Service: aplicar config descargada de APCM
        ReportTelemetry,             // Service → Tray: evento de telemetría para enviar
        GetCloudStatus,              // Tray → Service: consultar estado Cloud
        CloudStatusResponse          // Service → Tray: respuesta con estado Cloud
    }
}
