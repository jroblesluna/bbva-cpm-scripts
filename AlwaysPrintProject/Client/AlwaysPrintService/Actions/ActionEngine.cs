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
    /// - Variables de configuración (corporate_queue_name, contingency_printer_ip)
    /// </summary>
    public class ActionEngine
    {
        private readonly Dictionary<string, object> _variables = new Dictionary<string, object>();
        private readonly Dictionary<string, string> _configVariables = new Dictionary<string, string>();
        private ActionConfiguration? _config;
        
        // ═══════════════════════════════════════════════════════════════════════
        // VARIABLES DE CONFIGURACIÓN
        // ═══════════════════════════════════════════════════════════════════════
        
        /// <summary>
        /// Establece una variable de configuración que se resuelve en templates {{nombre}}.
        /// Estas variables provienen de AppConfiguration y son inmutables durante la ejecución.
        /// </summary>
        public void SetConfigVariable(string name, string value)
        {
            _configVariables[name] = value;
            AlwaysPrintLogger.WriteInfo($"ActionEngine: variable de configuración '{name}' establecida.");
        }
        
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
                
                case ActionTypes.DeleteOrphanedFolders:
                    return ExecuteDeleteOrphanedFolders(action);
                
                case ActionTypes.CreateTcpPort:
                case ActionTypes.SetTcpPort:
                    return ExecuteCreateTcpPort(action);
                
                case ActionTypes.AssignPortToQueue:
                    return ExecuteAssignPortToQueue(action);
                
                case ActionTypes.DeleteTcpPort:
                    return ExecuteDeleteTcpPort(action);
                
                // Compatibilidad hacia atrás: tipos obsoletos
                case "EnterShieldMode":
                    AlwaysPrintLogger.WriteWarning("ActionEngine: 'EnterShieldMode' está obsoleto. Usar 'CreateTcpPort' + 'AssignPortToQueue'.");
                    return ExecuteEnterShieldModeLegacy(action);
                
                case "ExitShieldMode":
                    AlwaysPrintLogger.WriteWarning("ActionEngine: 'ExitShieldMode' está obsoleto. Usar 'AssignPortToQueue'.");
                    return ExecuteExitShieldModeLegacy(action);
                
                case ActionTypes.PausePrintQueue:
                    return ExecutePausePrintQueue(action);
                
                case ActionTypes.UnpausePrintQueue:
                    return ExecuteUnpausePrintQueue(action);
                
                case ActionTypes.SetDefaultPrinter:
                    return ExecuteSetDefaultPrinter(action);
                
                case ActionTypes.RunProcess:
                    return ExecuteRunProcess(action);
                
                case ActionTypes.CheckPrintQueueExists:
                    return ExecuteCheckPrintQueueExists(action);

                case ActionTypes.ReadRegistryValue:
                    return ExecuteReadRegistryValue(action);

                case ActionTypes.ReadPrintQueuePort:
                    return ExecuteReadPrintQueuePort(action);
                
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
                _variables[action.StoreResultIn!] = users;
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
                var users = GetVariableAsList(iterateUsers!);
                
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
                    
                    string resolvedPath = ReplaceTemplates(pathTemplate!, tempVars);
                    AlwaysPrintLogger.WriteInfo($"ActionEngine: DeleteFolderContents iterando usuario '{username}', path={resolvedPath}");
                    
                    bool success = AdminActions.DeleteFolderContents(resolvedPath, recursive, ignoreErrors);
                    if (!success && !ignoreErrors)
                        allSuccess = false;
                }
                
                return allSuccess;
            }
            else if (!string.IsNullOrEmpty(path))
            {
                path = ReplaceTemplates(path!);
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

        private bool ExecuteDeleteOrphanedFolders(ActionConfig action)
        {
            string? basePath = action.Parameters?["base_path"]?.ToString();
            if (string.IsNullOrWhiteSpace(basePath))
            {
                AlwaysPrintLogger.WriteWarning("ActionEngine: DeleteOrphanedFolders requiere 'base_path'");
                return false;
            }

            bool excludeActiveConsole = action.Parameters?["exclude_active_console_user"]?.Value<bool>() ?? true;

            // Obtener lista de usuarios a preservar desde la variable especificada
            var excludeUsers = new List<string>();
            string? excludeVariable = action.Parameters?["exclude_users_variable"]?.ToString();

            if (!string.IsNullOrEmpty(excludeVariable))
            {
                if (_variables.TryGetValue(excludeVariable!, out var varValue) && varValue is List<string> userList)
                {
                    excludeUsers.AddRange(userList);
                }
                else
                {
                    AlwaysPrintLogger.WriteInfo(
                        $"ActionEngine: DeleteOrphanedFolders - variable '{excludeVariable}' no encontrada o vacía");
                }
            }

            int deleted = AdminActions.DeleteOrphanedFolders(basePath!, excludeUsers, excludeActiveConsole);
            return true; // Siempre retorna éxito (los errores individuales se loguean internamente)
        }

        private bool ExecuteCreateTcpPort(ActionConfig action)
        {
            string portName = GetParameter<string>(action, "port_name") ?? "";
            string hostAddress = GetParameter<string>(action, "host_address") ?? "";
            int portNumber = GetParameter<int>(action, "port_number", 9100);

            if (string.IsNullOrWhiteSpace(portName) || string.IsNullOrWhiteSpace(hostAddress))
            {
                AlwaysPrintLogger.WriteWarning("ActionEngine: CreateTcpPort requiere 'port_name' y 'host_address'");
                return false;
            }

            portName = ReplaceTemplates(portName);
            hostAddress = ReplaceTemplates(hostAddress);

            return AdminActions.CreateOrUpdateTcpPort(portName, hostAddress, portNumber);
        }

        private bool ExecuteAssignPortToQueue(ActionConfig action)
        {
            string queueName = GetParameter<string>(action, "queue_name") ?? "";
            string portName = GetParameter<string>(action, "port_name") ?? "";

            if (string.IsNullOrWhiteSpace(queueName) || string.IsNullOrWhiteSpace(portName))
            {
                AlwaysPrintLogger.WriteWarning("ActionEngine: AssignPortToQueue requiere 'queue_name' y 'port_name'");
                return false;
            }

            queueName = ReplaceTemplates(queueName);
            portName = ReplaceTemplates(portName);

            return AdminActions.AssignPortToQueue(queueName, portName);
        }

        private bool ExecuteDeleteTcpPort(ActionConfig action)
        {
            string portName = GetParameter<string>(action, "port_name") ?? "";

            if (string.IsNullOrWhiteSpace(portName))
            {
                AlwaysPrintLogger.WriteWarning("ActionEngine: DeleteTcpPort requiere 'port_name'");
                return false;
            }

            portName = ReplaceTemplates(portName);

            return AdminActions.DeleteTcpPort(portName);
        }

        // ═══════════════════════════════════════════════════════════════════════
        // COMPATIBILIDAD HACIA ATRÁS (OBSOLETO)
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Soporte legacy para configs antiguas que usen EnterShieldMode.
        /// Delega en CreateOrUpdateTcpPort + AssignPortToQueue.
        /// </summary>
        private bool ExecuteEnterShieldModeLegacy(ActionConfig action)
        {
            string queueName = GetParameter<string>(action, "queue_name") ?? "";
            string printerIp = GetParameter<string>(action, "printer_ip") ?? "";
            int printerPort = GetParameter<int>(action, "printer_port", 9100);

            if (string.IsNullOrWhiteSpace(queueName) || string.IsNullOrWhiteSpace(printerIp))
            {
                AlwaysPrintLogger.WriteWarning("ActionEngine: EnterShieldMode (legacy) requiere 'queue_name' y 'printer_ip'");
                return false;
            }

            queueName = ReplaceTemplates(queueName);
            printerIp = ReplaceTemplates(printerIp);

            string portName = $"AP_{printerIp}_{printerPort}";
            bool portOk = AdminActions.CreateOrUpdateTcpPort(portName, printerIp, printerPort);
            if (!portOk) return false;

            return AdminActions.AssignPortToQueue(queueName, portName);
        }

        /// <summary>
        /// Soporte legacy para configs antiguas que usen ExitShieldMode.
        /// Delega en AssignPortToQueue.
        /// </summary>
        private bool ExecuteExitShieldModeLegacy(ActionConfig action)
        {
            string queueName = GetParameter<string>(action, "queue_name") ?? "";
            string lpmcPortName = GetParameter<string>(action, "lpmc_port_name") ?? "LPMC:";

            if (string.IsNullOrWhiteSpace(queueName))
            {
                AlwaysPrintLogger.WriteWarning("ActionEngine: ExitShieldMode (legacy) requiere 'queue_name'");
                return false;
            }

            queueName = ReplaceTemplates(queueName);
            lpmcPortName = ReplaceTemplates(lpmcPortName);

            return AdminActions.AssignPortToQueue(queueName, lpmcPortName);
        }

        private bool ExecutePausePrintQueue(ActionConfig action)
        {
            string queueName = GetParameter<string>(action, "queue_name") ?? "";

            if (string.IsNullOrWhiteSpace(queueName))
            {
                AlwaysPrintLogger.WriteWarning("ActionEngine: PausePrintQueue requiere 'queue_name'");
                return false;
            }

            queueName = ReplaceTemplates(queueName);

            return AdminActions.PausePrintQueue(queueName);
        }

        private bool ExecuteUnpausePrintQueue(ActionConfig action)
        {
            string queueName = GetParameter<string>(action, "queue_name") ?? "";

            if (string.IsNullOrWhiteSpace(queueName))
            {
                AlwaysPrintLogger.WriteWarning("ActionEngine: UnpausePrintQueue requiere 'queue_name'");
                return false;
            }

            queueName = ReplaceTemplates(queueName);

            return AdminActions.UnpausePrintQueue(queueName);
        }

        private bool ExecuteSetDefaultPrinter(ActionConfig action)
        {
            string queueName = GetParameter<string>(action, "queue_name") ?? "";

            if (string.IsNullOrWhiteSpace(queueName))
            {
                AlwaysPrintLogger.WriteWarning("ActionEngine: SetDefaultPrinter requiere 'queue_name'");
                return false;
            }

            queueName = ReplaceTemplates(queueName);

            return AdminActions.SetDefaultPrinter(queueName);
        }

        private bool ExecuteRunProcess(ActionConfig action)
        {
            string filePath = GetParameter<string>(action, "file_path") ?? "";
            string arguments = GetParameter<string>(action, "arguments") ?? "";
            int timeoutSeconds = GetParameter<int>(action, "timeout_seconds", 120);
            string windowStyle = GetParameter<string>(action, "window_style") ?? "Hidden";
            bool runAsLoggedInUser = GetParameter<bool>(action, "run_as_logged_in_user", false);

            if (string.IsNullOrWhiteSpace(filePath))
            {
                AlwaysPrintLogger.WriteWarning("ActionEngine: RunProcess requiere 'file_path'");
                return false;
            }

            filePath = ReplaceTemplates(filePath);
            arguments = ReplaceTemplates(arguments);

            bool result = AdminActions.RunProcess(filePath, arguments, timeoutSeconds, windowStyle, runAsLoggedInUser);

            // Si se especificó store_result_in, guardar el resultado
            if (!string.IsNullOrEmpty(action.StoreResultIn))
            {
                SetConfigVariable(action.StoreResultIn, result ? "success" : "failed");
            }

            return result;
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

        /// <summary>
        /// Verifica si una cola de impresión existe en el sistema.
        /// Almacena "true" o "false" en la variable indicada por store_result_in.
        /// Parámetros: queue_name (string, soporta templates).
        /// </summary>
        private bool ExecuteCheckPrintQueueExists(ActionConfig action)
        {
            try
            {
                string queueName = GetParameter<string>(action, "queue_name") ?? "";
                queueName = ReplaceTemplates(queueName);

                if (string.IsNullOrEmpty(queueName))
                {
                    AlwaysPrintLogger.WriteWarning("CheckPrintQueueExists: queue_name vacío");
                    return false;
                }

                AlwaysPrintLogger.WriteInfo($"CheckPrintQueueExists: verificando si existe cola '{queueName}'");

                // Consultar registro de impresoras del Spooler
                bool exists = false;
                string regPath = $@"SYSTEM\CurrentControlSet\Control\Print\Printers\{queueName}";
                using (var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(regPath, writable: false))
                {
                    exists = key != null;
                }

                AlwaysPrintLogger.WriteInfo($"CheckPrintQueueExists: cola '{queueName}' existe = {exists}");

                // Almacenar resultado en variable si se especificó store_result_in
                if (!string.IsNullOrEmpty(action.StoreResultIn))
                {
                    _variables[action.StoreResultIn] = exists.ToString().ToLower();
                    AlwaysPrintLogger.WriteInfo(
                        $"CheckPrintQueueExists: resultado almacenado en '{action.StoreResultIn}' = {exists.ToString().ToLower()}");
                }

                return true;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"CheckPrintQueueExists: error: {ex.Message}", ex);
                return false;
            }
        }

        /// <summary>
        /// Lee un valor del registro de Windows y lo almacena en una variable.
        /// Parámetros: key_path (string), value_name (string), default_value (string, opcional).
        /// El resultado se almacena como string en la variable indicada por store_result_in.
        /// Para DWORD, se convierte a string (ej: "0", "1").
        /// </summary>
        private bool ExecuteReadRegistryValue(ActionConfig action)
        {
            try
            {
                string keyPath = GetParameter<string>(action, "key_path") ?? "";
                string valueName = GetParameter<string>(action, "value_name") ?? "";
                string defaultValue = GetParameter<string>(action, "default_value") ?? "";

                keyPath = ReplaceTemplates(keyPath);
                valueName = ReplaceTemplates(valueName);

                if (string.IsNullOrEmpty(keyPath) || string.IsNullOrEmpty(valueName))
                {
                    AlwaysPrintLogger.WriteWarning("ReadRegistryValue: key_path o value_name vacío");
                    return false;
                }

                AlwaysPrintLogger.WriteInfo($"ReadRegistryValue: leyendo HKLM\\{keyPath}\\{valueName}");

                string result = defaultValue;
                using (var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(keyPath, writable: false))
                {
                    if (key != null)
                    {
                        var regValue = key.GetValue(valueName);
                        if (regValue != null)
                            result = regValue.ToString() ?? defaultValue;
                    }
                }

                AlwaysPrintLogger.WriteInfo($"ReadRegistryValue: {valueName} = '{result}'");

                // Almacenar resultado en variable
                if (!string.IsNullOrEmpty(action.StoreResultIn))
                {
                    _variables[action.StoreResultIn] = result;
                    // También establecer como variable de configuración para uso en templates
                    _configVariables[action.StoreResultIn] = result;
                }

                return true;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"ReadRegistryValue: error: {ex.Message}", ex);
                return false;
            }
        }

        /// <summary>
        /// Lee el puerto asignado a una cola de impresión desde el registro del Spooler.
        /// Parámetros: queue_name (string, soporta templates).
        /// Almacena el nombre del puerto en la variable indicada por store_result_in.
        /// Si la cola no existe, almacena cadena vacía.
        /// </summary>
        private bool ExecuteReadPrintQueuePort(ActionConfig action)
        {
            try
            {
                string queueName = GetParameter<string>(action, "queue_name") ?? "";
                queueName = ReplaceTemplates(queueName);

                if (string.IsNullOrEmpty(queueName))
                {
                    AlwaysPrintLogger.WriteWarning("ReadPrintQueuePort: queue_name vacío");
                    return false;
                }

                AlwaysPrintLogger.WriteInfo($"ReadPrintQueuePort: leyendo puerto de cola '{queueName}'");

                string portName = "";
                string regPath = $@"SYSTEM\CurrentControlSet\Control\Print\Printers\{queueName}";
                using (var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(regPath, writable: false))
                {
                    if (key != null)
                    {
                        portName = key.GetValue("Port")?.ToString() ?? "";
                    }
                }

                AlwaysPrintLogger.WriteInfo($"ReadPrintQueuePort: cola '{queueName}' → puerto = '{portName}'");

                if (!string.IsNullOrEmpty(action.StoreResultIn))
                {
                    _variables[action.StoreResultIn] = portName;
                    _configVariables[action.StoreResultIn] = portName;
                }

                return true;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"ReadPrintQueuePort: error: {ex.Message}", ex);
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
                
                // Primero buscar en variables de ejecución
                if (variables.TryGetValue(varName, out object? value))
                {
                    if (value is string str)
                        return str;
                    
                    if (value is List<string> list)
                        return string.Join(",", list);
                    
                    return value?.ToString() ?? "";
                }
                
                // Luego buscar en variables de configuración (AppConfiguration)
                if (_configVariables.TryGetValue(varName, out string? configValue))
                {
                    return configValue ?? "";
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
