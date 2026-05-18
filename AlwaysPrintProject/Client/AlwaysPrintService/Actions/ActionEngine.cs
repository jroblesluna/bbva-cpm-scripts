using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace AlwaysPrintService.Actions
{
    /// <summary>
    /// Motor de ejecución de acciones administrativas basado en configuración JSON.
    /// Parsea ActionConfiguration y ejecuta acciones en secuencia con soporte para:
    /// - Variables y almacenamiento de resultados
    /// - Templates ({{variable}})
    /// - Condicionales
    /// - Iteración sobre listas de usuarios
    /// </summary>
    public class ActionEngine
    {
        private readonly Dictionary<string, object> _variables = new Dictionary<string, object>();
        private ActionConfiguration? _config;
        
        // ═══════════════════════════════════════════════════════════════════════
        // CARGA DE CONFIGURACIÓN
        // ═══════════════════════════════════════════════════════════════════════
        
        /// <summary>
        /// Carga la configuración desde un archivo JSON.
        /// </summary>
        public bool LoadConfiguration(string configFilePath)
        {
            try
            {
                AlwaysPrintLogger.WriteInfo($"ActionEngine: cargando configuración desde {configFilePath}");
                
                if (!File.Exists(configFilePath))
                {
                    AlwaysPrintLogger.WriteWarning($"ActionEngine: archivo de configuración no existe: {configFilePath}");
                    return false;
                }
                
                string json = File.ReadAllText(configFilePath);
                _config = JsonConvert.DeserializeObject<ActionConfiguration>(json);
                
                if (_config == null)
                {
                    AlwaysPrintLogger.WriteError("ActionEngine: error deserializando configuración (resultado null)");
                    return false;
                }
                
                AlwaysPrintLogger.WriteInfo(
                    $"ActionEngine: configuración cargada. " +
                    $"Nombre: {_config.Name}, Versión: {_config.Version}, Triggers: {_config.Triggers.Count}");
                
                return true;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"ActionEngine: error cargando configuración: {ex.Message}", ex);
                return false;
            }
        }
        
        /// <summary>
        /// Carga la configuración desde un string JSON.
        /// </summary>
        public bool LoadConfigurationFromString(string json)
        {
            try
            {
                AlwaysPrintLogger.WriteInfo("ActionEngine: cargando configuración desde string JSON");
                
                _config = JsonConvert.DeserializeObject<ActionConfiguration>(json);
                
                if (_config == null)
                {
                    AlwaysPrintLogger.WriteError("ActionEngine: error deserializando configuración (resultado null)");
                    return false;
                }
                
                AlwaysPrintLogger.WriteInfo(
                    $"ActionEngine: configuración cargada. " +
                    $"Nombre: {_config.Name}, Versión: {_config.Version}, Triggers: {_config.Triggers.Count}");
                
                return true;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"ActionEngine: error cargando configuración: {ex.Message}", ex);
                return false;
            }
        }
        
        // ═══════════════════════════════════════════════════════════════════════
        // EJECUCIÓN DE TRIGGERS
        // ═══════════════════════════════════════════════════════════════════════
        
        /// <summary>
        /// Ejecuta todas las acciones asociadas a un evento específico.
        /// </summary>
        public bool ExecuteTrigger(string eventName)
        {
            try
            {
                if (_config == null)
                {
                    AlwaysPrintLogger.WriteWarning("ActionEngine: no hay configuración cargada");
                    return false;
                }
                
                AlwaysPrintLogger.WriteInfo($"ActionEngine: ejecutando trigger para evento '{eventName}'");
                
                // Buscar triggers que coincidan con el evento
                var triggers = _config.Triggers.Where(t => 
                    t.Event.Equals(eventName, StringComparison.OrdinalIgnoreCase)).ToList();
                
                if (triggers.Count == 0)
                {
                    AlwaysPrintLogger.WriteInfo($"ActionEngine: no hay triggers configurados para evento '{eventName}'");
                    return true;
                }
                
                // Limpiar variables antes de ejecutar
                _variables.Clear();
                
                // Ejecutar cada trigger
                bool allSuccess = true;
                foreach (var trigger in triggers)
                {
                    AlwaysPrintLogger.WriteInfo($"ActionEngine: ejecutando trigger '{trigger.Description}'");
                    
                    bool success = ExecuteActions(trigger.Actions);
                    if (!success)
                    {
                        AlwaysPrintLogger.WriteWarning($"ActionEngine: trigger '{trigger.Description}' falló");
                        allSuccess = false;
                    }
                }
                
                AlwaysPrintLogger.WriteInfo($"ActionEngine: ejecución de trigger '{eventName}' completada. Success={allSuccess}");
                return allSuccess;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"ActionEngine: error ejecutando trigger '{eventName}': {ex.Message}", ex);
                return false;
            }
        }
        
        // ═══════════════════════════════════════════════════════════════════════
        // EJECUCIÓN DE ACCIONES
        // ═══════════════════════════════════════════════════════════════════════
        
        private bool ExecuteActions(List<ActionConfig> actions)
        {
            bool allSuccess = true;
            
            foreach (var action in actions)
            {
                try
                {
                    AlwaysPrintLogger.WriteInfo($"ActionEngine: ejecutando acción '{action.Type}': {action.Description}");
                    
                    bool success = ExecuteAction(action);
                    
                    if (!success)
                    {
                        AlwaysPrintLogger.WriteWarning($"ActionEngine: acción '{action.Type}' falló");
                        allSuccess = false;
                    }
                }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteError($"ActionEngine: error ejecutando acción '{action.Type}': {ex.Message}", ex);
                    allSuccess = false;
                }
            }
            
            return allSuccess;
        }
        
        private bool ExecuteAction(ActionConfig action)
        {
            switch (action.Type)
            {
                case ActionTypes.PropagatePermissions:
                    return ExecutePropagatePermissions(action);
                
                case ActionTypes.GetLoggedInUsers:
                    return ExecuteGetLoggedInUsers(action);
                
                case ActionTypes.DeleteFolderContents:
                    return ExecuteDeleteFolderContents(action);
                
                case ActionTypes.StopService:
                    return ExecuteStopService(action);
                
                case ActionTypes.StartService:
                    return ExecuteStartService(action);
                
                case ActionTypes.KillProcessesByName:
                    return ExecuteKillProcessesByName(action);
                
                case ActionTypes.Conditional:
                    return ExecuteConditional(action);
                
                case ActionTypes.StopTray:
                    return ExecuteStopTray(action);
                
                case ActionTypes.StartTray:
                    return ExecuteStartTray(action);
                
                default:
                    AlwaysPrintLogger.WriteWarning($"ActionEngine: tipo de acción desconocido: {action.Type}");
                    return false;
            }
        }
        
        // ═══════════════════════════════════════════════════════════════════════
        // IMPLEMENTACIÓN DE ACCIONES INDIVIDUALES
        // ═══════════════════════════════════════════════════════════════════════
        
        private bool ExecutePropagatePermissions(ActionConfig action)
        {
            string path = GetParameter<string>(action, "path") ?? "";
            bool recursive = GetParameter<bool>(action, "recursive", true);
            
            path = ReplaceTemplates(path);
            
            return AdminActions.PropagatePermissions(path, recursive);
        }
        
        private bool ExecuteGetLoggedInUsers(ActionConfig action)
        {
            bool excludeActiveConsoleUser = GetParameter<bool>(action, "exclude_active_console_user", false);
            
            var users = AdminActions.GetLoggedInUsers(excludeActiveConsoleUser);
            
            // Almacenar resultado si se especifica
            if (!string.IsNullOrEmpty(action.StoreResultIn))
            {
                _variables[action.StoreResultIn] = users;
                AlwaysPrintLogger.WriteInfo(
                    $"ActionEngine: resultado almacenado en variable '{action.StoreResultIn}': {users.Count} usuarios");
            }
            
            return true;
        }
        
        private bool ExecuteDeleteFolderContents(ActionConfig action)
        {
            string? pathTemplate = GetParameter<string>(action, "path_template");
            string? path = GetParameter<string>(action, "path");
            bool recursive = GetParameter<bool>(action, "recursive", true);
            bool ignoreErrors = GetParameter<bool>(action, "ignore_errors", true);
            
            // iterate_users es un nombre de variable, no un template.
            // Se lee como raw (sin ReplaceTemplates) para poder resolver la lista.
            string? iterateUsers = GetRawParameter(action, "iterate_users");
            
            // Si hay iteración sobre usuarios
            if (!string.IsNullOrEmpty(iterateUsers) && !string.IsNullOrEmpty(pathTemplate))
            {
                var users = GetVariableAsList(iterateUsers);
                
                if (users == null || users.Count == 0)
                {
                    AlwaysPrintLogger.WriteInfo($"ActionEngine: no hay usuarios para iterar (variable: {iterateUsers})");
                    return true;
                }
                
                bool allSuccess = true;
                foreach (var username in users)
                {
                    // Crear contexto temporal con el username
                    var tempVars = new Dictionary<string, object>(_variables)
                    {
                        ["username"] = username
                    };
                    
                    string resolvedPath = ReplaceTemplates(pathTemplate, tempVars);
                    AlwaysPrintLogger.WriteInfo($"ActionEngine: DeleteFolderContents iterando usuario '{username}', path={resolvedPath}");
                    
                    bool success = AdminActions.DeleteFolderContents(resolvedPath, recursive, ignoreErrors);
                    if (!success && !ignoreErrors)
                        allSuccess = false;
                }
                
                return allSuccess;
            }
            else if (!string.IsNullOrEmpty(path))
            {
                path = ReplaceTemplates(path);
                return AdminActions.DeleteFolderContents(path, recursive, ignoreErrors);
            }
            else
            {
                AlwaysPrintLogger.WriteWarning("ActionEngine: DeleteFolderContents requiere 'path' o 'path_template'");
                return false;
            }
        }
        
        private bool ExecuteStopService(ActionConfig action)
        {
            string serviceName = GetParameter<string>(action, "service_name") ?? "";
            int gracefulTimeout = GetParameter<int>(action, "graceful_timeout_seconds", 30);
            bool forceKill = GetParameter<bool>(action, "force_kill_on_timeout", false);
            
            return AdminActions.StopService(serviceName, gracefulTimeout, forceKill);
        }
        
        private bool ExecuteStartService(ActionConfig action)
        {
            string serviceName = GetParameter<string>(action, "service_name") ?? "";
            bool waitForRunning = GetParameter<bool>(action, "wait_for_running", true);
            int timeout = GetParameter<int>(action, "timeout_seconds", 30);
            
            return AdminActions.StartService(serviceName, waitForRunning, timeout);
        }
        
        private bool ExecuteKillProcessesByName(ActionConfig action)
        {
            string processName = GetParameter<string>(action, "process_name") ?? "";
            // filter_by_users es un nombre de variable, no un template.
            string? filterByUsers = GetRawParameter(action, "filter_by_users");
            bool force = GetParameter<bool>(action, "force", true);
            
            List<string>? users = null;
            if (!string.IsNullOrEmpty(filterByUsers))
            {
                users = GetVariableAsList(filterByUsers);
            }
            
            int killed = AdminActions.KillProcessesByName(processName, users, force);
            return killed >= 0;
        }
        
        private bool ExecuteConditional(ActionConfig action)
        {
            if (action.Condition == null)
            {
                AlwaysPrintLogger.WriteWarning("ActionEngine: Conditional sin condición definida");
                return false;
            }
            
            bool conditionMet = EvaluateCondition(action.Condition);
            
            AlwaysPrintLogger.WriteInfo($"ActionEngine: condición evaluada: {conditionMet}");
            
            if (conditionMet && action.Actions != null && action.Actions.Count > 0)
            {
                return ExecuteActions(action.Actions);
            }
            
            return true;
        }
        
        private bool ExecuteStopTray(ActionConfig action)
        {
            AlwaysPrintLogger.WriteInfo("ActionEngine: StopTray - matando procesos AlwaysPrintTray");
            int killed = AdminActions.KillProcessesByName("AlwaysPrintTray", null, true);
            return killed >= 0;
        }
        
        private bool ExecuteStartTray(ActionConfig action)
        {
            try
            {
                string trayExe = Path.Combine(
                    Path.GetDirectoryName(System.Diagnostics.Process.GetCurrentProcess().MainModule!.FileName)!,
                    "AlwaysPrintTray.exe");
                
                AlwaysPrintLogger.WriteInfo($"ActionEngine: StartTray - lanzando {trayExe} en sesión interactiva");
                
                bool ok = UserSession.InteractiveProcessLauncher.Launch(trayExe);
                
                if (ok)
                {
                    AlwaysPrintLogger.WriteInfo("ActionEngine: StartTray - Tray lanzado exitosamente");
                }
                else
                {
                    AlwaysPrintLogger.WriteWarning("ActionEngine: StartTray - no se pudo lanzar el Tray");
                }
                
                return ok;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"ActionEngine: StartTray - error: {ex.Message}", ex);
                return false;
            }
        }
        
        // ═══════════════════════════════════════════════════════════════════════
        // EVALUACIÓN DE CONDICIONES
        // ═══════════════════════════════════════════════════════════════════════
        
        private bool EvaluateCondition(ConditionConfig condition)
        {
            try
            {
                object? variableValue = GetVariable(condition.Variable);
                
                if (variableValue == null)
                {
                    AlwaysPrintLogger.WriteWarning($"ActionEngine: variable '{condition.Variable}' no existe");
                    return false;
                }
                
                switch (condition.Operator.ToLowerInvariant())
                {
                    case "count_greater_than":
                        if (variableValue is List<string> list)
                        {
                            int threshold = Convert.ToInt32(condition.Value);
                            return list.Count > threshold;
                        }
                        break;
                    
                    case "count_equals":
                        if (variableValue is List<string> list2)
                        {
                            int expected = Convert.ToInt32(condition.Value);
                            return list2.Count == expected;
                        }
                        break;
                    
                    case "equals":
                        return variableValue.Equals(condition.Value);
                    
                    case "not_equals":
                        return !variableValue.Equals(condition.Value);
                    
                    case "contains":
                        if (variableValue is string str && condition.Value is string searchStr)
                        {
                            return str.Contains(searchStr);
                        }
                        break;
                    
                    default:
                        AlwaysPrintLogger.WriteWarning($"ActionEngine: operador desconocido: {condition.Operator}");
                        return false;
                }
                
                return false;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"ActionEngine: error evaluando condición: {ex.Message}", ex);
                return false;
            }
        }
        
        // ═══════════════════════════════════════════════════════════════════════
        // GESTIÓN DE VARIABLES Y TEMPLATES
        // ═══════════════════════════════════════════════════════════════════════
        
        private object? GetVariable(string variableName)
        {
            // Remover {{}} si están presentes
            variableName = variableName.Trim('{', '}').Trim();
            
            if (_variables.TryGetValue(variableName, out object? value))
                return value;
            
            return null;
        }
        
        private List<string>? GetVariableAsList(string variableName)
        {
            object? value = GetVariable(variableName);
            
            if (value is List<string> list)
                return list;
            
            return null;
        }
        
        private string ReplaceTemplates(string template)
        {
            return ReplaceTemplates(template, _variables);
        }
        
        private string ReplaceTemplates(string template, Dictionary<string, object> variables)
        {
            if (string.IsNullOrEmpty(template))
                return template;
            
            // Buscar patrones {{variable}}
            var regex = new Regex(@"\{\{(\w+)\}\}");
            
            return regex.Replace(template, match =>
            {
                string varName = match.Groups[1].Value;
                
                if (variables.TryGetValue(varName, out object? value))
                {
                    if (value is string str)
                        return str;
                    
                    if (value is List<string> list)
                        return string.Join(",", list);
                    
                    return value?.ToString() ?? "";
                }
                
                AlwaysPrintLogger.WriteWarning($"ActionEngine: variable '{varName}' no encontrada en template");
                return match.Value; // Dejar sin reemplazar
            });
        }
        
        // ═══════════════════════════════════════════════════════════════════════
        // HELPERS PARA PARÁMETROS
        // ═══════════════════════════════════════════════════════════════════════
        
        private T? GetParameter<T>(ActionConfig action, string paramName, T? defaultValue = default)
        {
            try
            {
                if (action.Parameters == null)
                    return defaultValue;
                
                if (!action.Parameters.TryGetValue(paramName, out JToken? token))
                    return defaultValue;
                
                if (token == null)
                    return defaultValue;
                
                // Manejar templates en strings
                if (typeof(T) == typeof(string))
                {
                    string? strValue = token.ToString();
                    if (!string.IsNullOrEmpty(strValue))
                    {
                        strValue = ReplaceTemplates(strValue);
                        return (T)(object)strValue;
                    }
                }
                
                return token.ToObject<T>();
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteWarning($"ActionEngine: error obteniendo parámetro '{paramName}': {ex.Message}");
                return defaultValue;
            }
        }
        
        /// <summary>
        /// Lee un parámetro string sin aplicar ReplaceTemplates.
        /// Útil para parámetros que son nombres de variables (iterate_users, filter_by_users)
        /// y no deben ser resueltos como templates.
        /// </summary>
        private string? GetRawParameter(ActionConfig action, string paramName)
        {
            try
            {
                if (action.Parameters == null)
                    return null;
                
                if (!action.Parameters.TryGetValue(paramName, out JToken? token))
                    return null;
                
                if (token == null)
                    return null;
                
                string? value = token.ToString();
                
                // Remover {{}} si están presentes — el usuario puede escribir
                // "iterate_users": "{{inactive_users}}" o "iterate_users": "inactive_users"
                if (!string.IsNullOrEmpty(value))
                {
                    value = value.Trim('{', '}').Trim();
                }
                
                return value;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteWarning($"ActionEngine: error obteniendo parámetro raw '{paramName}': {ex.Message}");
                return null;
            }
        }
        
        // ═══════════════════════════════════════════════════════════════════════
        // INFORMACIÓN DE CONFIGURACIÓN
        // ═══════════════════════════════════════════════════════════════════════
        
        /// <summary>
        /// Obtiene información sobre la configuración cargada.
        /// </summary>
        public string GetConfigurationInfo()
        {
            if (_config == null)
                return "No hay configuración cargada";
            
            return $"Configuración: {_config.Name} v{_config.Version} - {_config.Triggers.Count} triggers";
        }
        
        /// <summary>
        /// Verifica si hay un trigger configurado para un evento específico.
        /// </summary>
        public bool HasTrigger(string eventName)
        {
            if (_config == null)
                return false;
            
            return _config.Triggers.Any(t => 
                t.Event.Equals(eventName, StringComparison.OrdinalIgnoreCase));
        }
    }
}
