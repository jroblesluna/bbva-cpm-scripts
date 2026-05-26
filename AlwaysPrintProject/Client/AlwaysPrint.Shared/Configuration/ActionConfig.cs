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
        
        [JsonProperty("triggers")]
        public List<TriggerConfig> Triggers { get; set; } = new List<TriggerConfig>();
    }
    
    /// <summary>
    /// Trigger que ejecuta acciones cuando ocurre un evento específico.
    /// </summary>
    public class TriggerConfig
    {
        [JsonProperty("event")]
        public string Event { get; set; } = string.Empty;
        
        [JsonProperty("description")]
        public string Description { get; set; } = string.Empty;
        
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
    }
}
