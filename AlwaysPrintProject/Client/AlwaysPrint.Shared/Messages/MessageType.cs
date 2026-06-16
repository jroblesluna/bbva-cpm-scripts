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
        CloudStatusResponse,         // Service → Tray: respuesta con estado Cloud
        
        // Configuración de Acciones
        ActionConfigChanged,         // Tray → Service: nueva configuración de acciones descargada
        SaveActionConfig,            // Tray → Service: guardar contenido de config en disco

        // Actualizaciones automáticas
        InstallUpdate,               // Tray → Service: solicitar instalación de MSI
        InstallUpdateResponse,       // Service → Tray: resultado de la instalación

        // Contingencia forzada
        ForcedContingencyChanged,    // Tray → Service: contingencia forzada activada/desactivada desde Cloud
        ContingencyResult,           // Service → Tray (push): resultado de la ejecución de contingencia

        // Recursos de VLAN
        SaveResources,               // Tray → Service: guardar resources.json en disco

        // On-Demand Triggers y acciones de servicio
        ExecuteOnDemandTrigger,      // Tray → Service: ejecutar trigger OnDemand por label
        ServiceAction,               // Tray → Service: iniciar o reiniciar un servicio
        ServiceActionResponse,       // Service → Tray: resultado de la acción sobre servicio

        // Lifecycle del servicio
        ServiceStopping,             // Service → Tray (push): servicio se está deteniendo, ocultar icono
    }
}
