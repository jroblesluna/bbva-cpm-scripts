using System;
using System.Collections.Generic;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace AlwaysPrint.Shared.Configuration
{
    /// <summary>
    /// Configuración de acciones administrativas que se ejecutan en respuesta a eventos.
    /// </summary>
    public class ActionConfiguration
    {
        [JsonProperty("version")]
        public string Version { get; set; } = "1.0";
        
        [JsonProperty("name")]
        public string Name { get; set; } = string.Empty;
        
        [JsonProperty("description")]
        public string Description { get; set; } = string.Empty;
        
        [JsonProperty("created_at")]
        public DateTime CreatedAt { get; set; }

        /// <summary>
        /// Lista de servicios Windows a monitorear en el Status Form.
        /// Si está vacía o ausente, no se muestra la sección de servicios.
        /// </summary>
        [JsonProperty("monitored_services")]
        public List<MonitoredServiceConfig> MonitoredServices { get; set; } = new List<MonitoredServiceConfig>();
        
        [JsonProperty("triggers")]
        public List<TriggerConfig> Triggers { get; set; } = new List<TriggerConfig>();
    }

    /// <summary>
    /// Configuración de un servicio Windows a monitorear en el Status Form.
    /// </summary>
    public class MonitoredServiceConfig
    {
        /// <summary>Nombre visible en la UI (ej: "Cola de Impresión").</summary>
        [JsonProperty("display_name")]
        public string DisplayName { get; set; } = string.Empty;

        /// <summary>Nombre real del servicio Windows (ej: "Spooler").</summary>
        [JsonProperty("service_name")]
        public string ServiceName { get; set; } = string.Empty;
    }
    
    /// <summary>
    /// Trigger que ejecuta acciones cuando ocurre un evento específico.
    /// Para OnScheduledTask, se puede definir un intervalo de ejecución periódica.
    /// </summary>
    public class TriggerConfig
    {
        [JsonProperty("event")]
        public string Event { get; set; } = string.Empty;
        
        /// <summary>
        /// Etiqueta única del trigger OnDemand. Requerida solo para event="OnDemand".
        /// Se usa como identificador en la UI y en el payload de ejecución.
        /// </summary>
        [JsonProperty("label")]
        public string? Label { get; set; }
        
        [JsonProperty("description")]
        public string Description { get; set; } = string.Empty;
        
        /// <summary>
        /// Intervalo en segundos para triggers periódicos (OnScheduledTask).
        /// Mínimo 60 segundos. Ignorado para otros eventos.
        /// </summary>
        [JsonProperty("interval_seconds")]
        public int? IntervalSeconds { get; set; }
        
        [JsonProperty("actions")]
        public List<ActionConfig> Actions { get; set; } = new List<ActionConfig>();
    }
    
    /// <summary>
    /// Acción individual que se ejecuta como parte de un trigger.
    /// </summary>
    public class ActionConfig
    {
        [JsonProperty("type")]
        public string Type { get; set; } = string.Empty;
        
        [JsonProperty("description")]
        public string Description { get; set; } = string.Empty;
        
        [JsonProperty("parameters")]
        public JObject? Parameters { get; set; }
        
        [JsonProperty("store_result_in")]
        public string? StoreResultIn { get; set; }
        
        [JsonProperty("condition")]
        public ConditionConfig? Condition { get; set; }
        
        [JsonProperty("actions")]
        public List<ActionConfig>? Actions { get; set; }

        [JsonProperty("else_actions")]
        public List<ActionConfig>? ElseActions { get; set; }
    }
    
    /// <summary>
    /// Condición que determina si se ejecutan acciones anidadas.
    /// </summary>
    public class ConditionConfig
    {
        [JsonProperty("variable")]
        public string Variable { get; set; } = string.Empty;
        
        [JsonProperty("operator")]
        public string Operator { get; set; } = string.Empty;
        
        [JsonProperty("value")]
        public object? Value { get; set; }
    }
    
    /// <summary>
    /// Eventos soportados para triggers.
    /// </summary>
    public static class TriggerEvents
    {
        public const string OnServiceStart = "OnServiceStart";
        public const string OnTrayLaunched = "OnTrayLaunched";
        public const string OnConfigChange = "OnConfigChange";
        public const string OnUserLogon = "OnUserLogon";
        public const string OnUserLogoff = "OnUserLogoff";
        public const string OnContingencyActivated = "OnContingencyActivated";
        public const string OnContingencyDeactivated = "OnContingencyDeactivated";
        public const string OnScheduledTask = "OnScheduledTask";
        public const string OnDemand = "OnDemand";
    }
    
    /// <summary>
    /// Tipos de acciones soportadas.
    /// </summary>
    public static class ActionTypes
    {
        public const string PropagatePermissions = "PropagatePermissions";
        public const string GetLoggedInUsers = "GetLoggedInUsers";
        public const string DeleteFolderContents = "DeleteFolderContents";
        public const string StopService = "StopService";
        public const string StartService = "StartService";
        public const string KillProcessesByName = "KillProcessesByName";
        public const string StopTray = "StopTray";
        public const string StartTray = "StartTray";
        public const string Conditional = "Conditional";
        public const string DeleteOrphanedFolders = "DeleteOrphanedFolders";
        public const string CreateTcpPort = "CreateTcpPort";
        public const string SetTcpPort = "SetTcpPort";
        public const string AssignPortToQueue = "AssignPortToQueue";
        public const string DeleteTcpPort = "DeleteTcpPort";
        public const string PausePrintQueue = "PausePrintQueue";
        public const string UnpausePrintQueue = "UnpausePrintQueue";
        public const string SetDefaultPrinter = "SetDefaultPrinter";
        public const string RunProcess = "RunProcess";
        public const string CheckPrintQueueExists = "CheckPrintQueueExists";
        public const string ReadRegistryValue = "ReadRegistryValue";
        public const string ReadPrintQueuePort = "ReadPrintQueuePort";
        public const string ReadAppSetting = "ReadAppSetting";
        public const string WriteAppSetting = "WriteAppSetting";
        public const string ReadPrintDriverVersion = "ReadPrintDriverVersion";
        public const string CheckWindowsFeature = "CheckWindowsFeature";
        public const string EnableWindowsFeature = "EnableWindowsFeature";
    }
}
