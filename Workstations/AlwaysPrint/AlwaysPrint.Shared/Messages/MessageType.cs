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
        Error
    }
}
