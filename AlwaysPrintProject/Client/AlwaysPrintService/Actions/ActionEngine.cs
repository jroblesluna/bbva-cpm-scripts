using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Messages;
using AlwaysPrint.Shared.Security;
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
        private Func<bool>? _gracefulStopTrayCallback;
        private Func<PipeMessage, bool>? _sendPipeMessageCallback;
        private string? _loadedConfigHash;
        private string? _currentOnDemandLabel;

        /// <summary>
        /// Evento emitido por cada paso de una ejecución OnDemand.
        /// Parámetros: (triggerLabel, actionType, description, status: "running"|"ok"|"error")
        /// </summary>
        public event Action<string, string, string, string>? OnActionProgress;

        /// <summary>
        /// Hash de la configuración actualmente cargada en memoria.
        /// Se usa para detectar si un reload trae la misma config (evita triggers innecesarios).
        /// </summary>
        public string? LoadedConfigHash => _loadedConfigHash;

        /// <summary>
        /// Establece un callback para cierre suave del Tray (envía señal vía pipe para
        /// que el Tray oculte su NotifyIcon antes del kill, evitando iconos fantasma).
        /// </summary>
        public void SetGracefulStopTrayCallback(Func<bool> callback)
        {
            _gracefulStopTrayCallback = callback;
        }

        /// <summary>
        /// Establece un callback para enviar mensajes al Tray vía Named Pipe.
        /// Retorna true si el mensaje se envió, false si el pipe está desconectado.
        /// </summary>
        public void SetSendPipeMessageCallback(Func<PipeMessage, bool> callback)
        {
            _sendPipeMessageCallback = callback;
        }
        
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
        /// Si el archivo contiene un envelope firmado (config + hash + signature + cert_version),
        /// verifica la firma ECDSA ANTES de cargar en memoria.
        /// Si la verificación falla por cualquier motivo, ELIMINA el archivo y retorna false.
        /// </summary>
        public bool LoadConfiguration(string configFilePath)
        {
            try
            {
                // Reset hash al inicio (se establecerá si la carga es exitosa)
                _loadedConfigHash = null;
                
                AlwaysPrintLogger.WriteInfo($"ActionEngine: cargando configuración desde {configFilePath}");
                
                if (!File.Exists(configFilePath))
                {
                    AlwaysPrintLogger.WriteWarning($"ActionEngine: archivo de configuración no existe: {configFilePath}");
                    return false;
                }
                
                string fileContent = File.ReadAllText(configFilePath);
                
                // Intentar parsear como JSON
                JObject? parsed;
                try
                {
                    parsed = JObject.Parse(fileContent);
                }
                catch (JsonException ex)
                {
                    // JSON corrupto — invalidar y eliminar
                    AlwaysPrintLogger.WriteError(
                        $"ActionEngine: archivo de configuración corrupto (JSON inválido): {ex.Message}. Eliminando.",
                        AlwaysPrintLogger.EvtGenericError);
                    DeleteConfigFile(configFilePath);
                    return false;
                }
                
                // Verificar si es envelope firmado (tiene los 4 campos requeridos)
                bool isSignedEnvelope = parsed["config"] != null 
                    && parsed["hash"] != null 
                    && parsed["signature"] != null 
                    && parsed["cert_version"] != null;
                
                if (!isSignedEnvelope)
                {
                    // Formato legacy sin firma — invalidar y eliminar
                    AlwaysPrintLogger.WriteError(
                        "ActionEngine: configuración sin firma digital (formato legacy). " +
                        "Solo se aceptan configuraciones firmadas. Eliminando archivo.",
                        AlwaysPrintLogger.EvtGenericError);
                    DeleteConfigFile(configFilePath);
                    return false;
                }
                
                // Verificar firma ECDSA
                string certPath = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
                    "AlwaysPrint", "config", "org.cer");
                
                if (!File.Exists(certPath))
                {
                    // No hay certificado local — no se puede verificar
                    AlwaysPrintLogger.WriteError(
                        $"ActionEngine: no se encontró certificado local en {certPath}. " +
                        "No se puede verificar la firma. Eliminando configuración.",
                        AlwaysPrintLogger.EvtGenericError);
                    DeleteConfigFile(configFilePath);
                    return false;
                }
                
                if (!SignatureVerifier.VerifyConfig(fileContent, certPath, out string verifiedConfigJson))
                {
                    // Firma inválida (hash mismatch o signature no corresponde)
                    AlwaysPrintLogger.WriteError(
                        "ActionEngine: firma digital inválida — la configuración fue modificada o es inauténtica. " +
                        "Eliminando archivo.",
                        AlwaysPrintLogger.EvtGenericError);
                    DeleteConfigFile(configFilePath);
                    return false;
                }
                
                // Actualizar CertVersion en registro (el Service tiene permisos HKLM)
                int certVersion = parsed["cert_version"]!.Value<int>();
                SignatureVerifier.SetLocalCertVersion(certVersion);
                
                // Firma válida — deserializar solo el config interno
                _config = JsonConvert.DeserializeObject<ActionConfiguration>(verifiedConfigJson);
                
                if (_config == null)
                {
                    AlwaysPrintLogger.WriteError(
                        "ActionEngine: error deserializando el config interno del envelope (resultado null). Eliminando.",
                        AlwaysPrintLogger.EvtGenericError);
                    DeleteConfigFile(configFilePath);
                    return false;
                }
                
                // Almacenar hash del config cargado (para detectar recargas sin cambio)
                _loadedConfigHash = parsed["hash"]?.ToString();
                
                AlwaysPrintLogger.WriteInfo(
                    $"ActionEngine: configuración firmada verificada y cargada. " +
                    $"Nombre: {_config.Name}, Versión: {_config.Version}, " +
                    $"Triggers: {_config.Triggers.Count}, CertVersion: {parsed["cert_version"]}");
                
                return true;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"ActionEngine: error cargando configuración: {ex.Message}", ex);
                return false;
            }
        }
        
        /// <summary>
        /// Elimina el archivo de configuración inválido/corrupto del disco.
        /// </summary>
        private void DeleteConfigFile(string configFilePath)
        {
            try
            {
                File.Delete(configFilePath);
                AlwaysPrintLogger.WriteInfo($"ActionEngine: archivo eliminado: {configFilePath}");
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"ActionEngine: no se pudo eliminar el archivo: {ex.Message}", ex,
                    AlwaysPrintLogger.EvtGenericError);
            }
        }

        /// <summary>
        /// Descarga la configuración de memoria sin eliminar archivo de disco.
        /// Se usa cuando el archivo fue eliminado externamente (ej: cert invalidado por cambio de entorno)
        /// para que el engine quede en estado limpio hasta que llegue una nueva configuración.
        /// </summary>
        public void UnloadConfiguration()
        {
            if (_config == null && _loadedConfigHash == null)
                return; // Ya estaba descargada

            _config = null;
            _loadedConfigHash = null;
            _variables.Clear();
            AlwaysPrintLogger.WriteInfo(
                "ActionEngine: configuración descargada de memoria (archivo no existe en disco).");
        }
        
        /// <summary>
        /// Carga la configuración desde un string JSON.
        /// </summary>
        public bool LoadConfigurationFromString(string json)
        {
            try
            {
                AlwaysPrintLogger.WriteInfo("ActionEngine: cargando configuración desde string JSON");
                
                // No hay envelope firmado → no hay hash disponible
                _loadedConfigHash = null;
                
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
        
        /// <summary>
        /// Ejecuta un trigger OnDemand buscándolo por label exacto.
        /// Retorna (success, message) para comunicar resultado al Tray.
        /// </summary>
        public (bool success, string message) ExecuteOnDemandTrigger(string label)
        {
            if (_config == null)
                return (false, "No hay configuración cargada");
            
            var trigger = _config.Triggers
                .Where(t => t.Event.Equals("OnDemand", StringComparison.OrdinalIgnoreCase)
                         && !string.IsNullOrWhiteSpace(t.Label))
                .FirstOrDefault(t => t.Label!.Equals(label, StringComparison.Ordinal));
            
            if (trigger == null)
                return (false, $"Trigger OnDemand con label '{label}' no encontrado");
            
            // Verificar duplicados y advertir
            var duplicates = _config.Triggers
                .Where(t => t.Event.Equals("OnDemand", StringComparison.OrdinalIgnoreCase)
                         && t.Label == label)
                .Count();
            if (duplicates > 1)
                AlwaysPrintLogger.WriteWarning(
                    $"ActionEngine: existen {duplicates} triggers OnDemand con label '{label}'. " +
                    "Ejecutando el primero encontrado.");
            
            var sw = Stopwatch.StartNew();
            AlwaysPrintLogger.WriteInfo(
                $"ActionEngine: iniciando ejecución OnDemand '{label}'");
            
            _variables.Clear();
            _currentOnDemandLabel = label;
            bool success = ExecuteActions(trigger.Actions);
            _currentOnDemandLabel = null;
            
            sw.Stop();
            AlwaysPrintLogger.WriteInfo(
                $"ActionEngine: OnDemand '{label}' completado. " +
                $"Success={success}, Duración={sw.ElapsedMilliseconds}ms");

            // Emitir progreso final: completado
            OnActionProgress?.Invoke(label, "COMPLETE", 
                success ? "Ejecución completada" : "Ejecución completada con errores",
                success ? "completed_ok" : "completed_error");
            
            return (success, success 
                ? $"Trigger '{label}' ejecutado correctamente ({sw.ElapsedMilliseconds}ms)"
                : $"Trigger '{label}' falló durante ejecución");
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
                    
                    // Emitir progreso: paso iniciando
                    if (_currentOnDemandLabel != null)
                        OnActionProgress?.Invoke(_currentOnDemandLabel, action.Type, action.Description ?? action.Type, "running");
                    
                    bool success = ExecuteAction(action);
                    
                    if (!success)
                    {
                        AlwaysPrintLogger.WriteWarning($"ActionEngine: acción '{action.Type}' falló");
                        if (_currentOnDemandLabel != null)
                            OnActionProgress?.Invoke(_currentOnDemandLabel, action.Type, action.Description ?? action.Type, "error");
                        allSuccess = false;
                    }
                    else
                    {
                        if (_currentOnDemandLabel != null)
                            OnActionProgress?.Invoke(_currentOnDemandLabel, action.Type, action.Description ?? action.Type, "ok");
                    }
                }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteError($"ActionEngine: error ejecutando acción '{action.Type}': {ex.Message}", ex);
                    if (_currentOnDemandLabel != null)
                        OnActionProgress?.Invoke(_currentOnDemandLabel, action.Type, action.Description ?? action.Type, "error");
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

                case ActionTypes.ClassifyOrphanedUsers:
                    return ExecuteClassifyOrphanedUsers(action);
                
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

                case ActionTypes.ReadAppSetting:
                    return ExecuteReadAppSetting(action);

                case ActionTypes.WriteAppSetting:
                    return ExecuteWriteAppSetting(action);

                case ActionTypes.ReadPrintDriverVersion:
                    return ExecuteReadPrintDriverVersion(action);

                case ActionTypes.EnableWindowsFeature:
                    return ExecuteEnableWindowsFeature(action);
                
                case ActionTypes.ConnectivityCheck:
                    return ExecuteConnectivityCheck(action);
                
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
            else if (!conditionMet && action.ElseActions != null && action.ElseActions.Count > 0)
            {
                AlwaysPrintLogger.WriteInfo("ActionEngine: ejecutando else_actions");
                return ExecuteActions(action.ElseActions);
            }
            
            return true;
        }
        
        private bool ExecuteStopTray(ActionConfig action)
        {
            // Escribir LastRestartTimestamp antes de matar el Tray para que
            // aplique jitter al reconectar (prevención de thundering herd).
            try
            {
                var registry = new RegistryConfigManager();
                registry.SaveLastRestartTimestamp(DateTime.UtcNow);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"ActionEngine: no se pudo escribir LastRestartTimestamp en registro: {ex.Message}");
            }

            // Intentar cierre suave primero (envía señal al Tray para que oculte NotifyIcon)
            if (_gracefulStopTrayCallback != null)
            {
                AlwaysPrintLogger.WriteInfo("ActionEngine: StopTray - intentando cierre suave vía pipe");
                try
                {
                    _gracefulStopTrayCallback();
                }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteWarning(
                        $"ActionEngine: StopTray - cierre suave falló, procediendo con kill: {ex.Message}");
                }
            }

            // Force kill de cualquier proceso que quede (graceful puede no haber cerrado todo)
            AlwaysPrintLogger.WriteInfo("ActionEngine: StopTray - matando procesos AlwaysPrintTray restantes");
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

            // Modo directo: si se pasa users_variable, borrar esos usuarios específicos
            string? usersVariable = action.Parameters?["users_variable"]?.ToString();
            if (!string.IsNullOrEmpty(usersVariable))
            {
                // Remover {{}} si están presentes
                string cleanVar = usersVariable!.Trim('{', '}').Trim();

                if (_variables.TryGetValue(cleanVar, out var varValue) && varValue is List<string> userList && userList.Count > 0)
                {
                    AlwaysPrintLogger.WriteInfo(
                        $"ActionEngine: DeleteOrphanedFolders (modo directo): eliminando {userList.Count} carpetas: [{string.Join(", ", userList)}]");

                    int deleted = 0;
                    foreach (string username in userList)
                    {
                        string fullPath = Path.Combine(basePath!, username);
                        try
                        {
                            if (Directory.Exists(fullPath))
                            {
                                Directory.Delete(fullPath, recursive: true);
                                deleted++;
                                AlwaysPrintLogger.WriteInfo($"ActionEngine: DeleteOrphanedFolders: carpeta eliminada: {fullPath}");
                            }
                            else
                            {
                                AlwaysPrintLogger.WriteInfo($"ActionEngine: DeleteOrphanedFolders: carpeta no existe (omitida): {fullPath}");
                            }
                        }
                        catch (Exception ex)
                        {
                            AlwaysPrintLogger.WriteWarning($"ActionEngine: DeleteOrphanedFolders: error eliminando {fullPath}: {ex.Message}");
                        }
                    }

                    AlwaysPrintLogger.WriteInfo($"ActionEngine: DeleteOrphanedFolders (modo directo): {deleted} carpetas eliminadas");
                }
                else
                {
                    AlwaysPrintLogger.WriteInfo(
                        $"ActionEngine: DeleteOrphanedFolders - variable '{cleanVar}' no encontrada o vacía. Nada que eliminar.");
                }

                return true;
            }

            // Modo discovery: descubrir y eliminar carpetas huérfanas (comportamiento original)
            bool excludeActiveConsole = action.Parameters?["exclude_active_console_user"]?.Value<bool>() ?? true;

            var excludeUsers = new List<string>();
            string? excludeVariable = action.Parameters?["exclude_users_variable"]?.ToString();

            if (!string.IsNullOrEmpty(excludeVariable))
            {
                if (_variables.TryGetValue(excludeVariable!, out var varValue2) && varValue2 is List<string> userList2)
                {
                    excludeUsers.AddRange(userList2);
                }
                else
                {
                    AlwaysPrintLogger.WriteInfo(
                        $"ActionEngine: DeleteOrphanedFolders - variable '{excludeVariable}' no encontrada o vacía");
                }
            }

            int deletedCount = AdminActions.DeleteOrphanedFolders(basePath!, excludeUsers, excludeActiveConsole);
            return true; // Siempre retorna éxito (los errores individuales se loguean internamente)
        }

        private bool ExecuteClassifyOrphanedUsers(ActionConfig action)
        {
            string? basePath = action.Parameters?["base_path"]?.ToString();
            if (string.IsNullOrWhiteSpace(basePath))
            {
                AlwaysPrintLogger.WriteWarning("ActionEngine: ClassifyOrphanedUsers requiere 'base_path'");
                return false;
            }

            bool excludeActiveConsole = action.Parameters?["exclude_active_console_user"]?.Value<bool>() ?? true;

            // Obtener lista de usuarios a excluir desde la variable especificada
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
                        $"ActionEngine: ClassifyOrphanedUsers - variable '{excludeVariable}' no encontrada o vacía");
                }
            }

            var classification = AdminActions.ClassifyOrphanedUsers(basePath!, excludeUsers, excludeActiveConsole);

            // Almacenar resultado en dos variables separadas: {store_result_in}_recent y {store_result_in}_stale
            if (!string.IsNullOrEmpty(action.StoreResultIn))
            {
                string baseVarName = action.StoreResultIn!;
                _variables[$"{baseVarName}_recent"] = classification.Recent;
                _variables[$"{baseVarName}_stale"] = classification.Stale;

                AlwaysPrintLogger.WriteInfo(
                    $"ActionEngine: ClassifyOrphanedUsers resultado almacenado: " +
                    $"'{baseVarName}_recent'={classification.Recent.Count} usuarios, " +
                    $"'{baseVarName}_stale'={classification.Stale.Count} usuarios");
            }

            return true;
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

            // Códigos de salida considerados exitosos (default: solo 0)
            int[]? successExitCodes = GetParameterArray<int>(action, "success_exit_codes");

            if (string.IsNullOrWhiteSpace(filePath))
            {
                AlwaysPrintLogger.WriteWarning("ActionEngine: RunProcess requiere 'file_path'");
                return false;
            }

            filePath = ReplaceTemplates(filePath);
            arguments = ReplaceTemplates(arguments);

            bool result = AdminActions.RunProcess(filePath, arguments, timeoutSeconds, windowStyle, runAsLoggedInUser, successExitCodes);

            // Si se especificó store_result_in, guardar en ambos diccionarios:
            // _variables (para EvaluateCondition/GetVariable) y _configVariables (para ReplaceTemplates)
            if (!string.IsNullOrEmpty(action.StoreResultIn))
            {
                string resultValue = result ? "success" : "failed";
                _variables[action.StoreResultIn!] = resultValue;
                _configVariables[action.StoreResultIn!] = resultValue;
                AlwaysPrintLogger.WriteInfo(
                    $"ActionEngine: resultado de RunProcess almacenado en variable '{action.StoreResultIn}': {resultValue}");
            }

            return result;
        }
        
        /// <summary>
        /// Habilita un Windows Optional Feature si no está ya habilitado.
        /// Encapsula la verificación + habilitación en una sola acción.
        /// Parámetros: feature_name (string, nombre del feature de Windows).
        /// </summary>
        private bool ExecuteEnableWindowsFeature(ActionConfig action)
        {
            string featureName = GetParameter<string>(action, "feature_name") ?? "";
            
            if (string.IsNullOrWhiteSpace(featureName))
            {
                AlwaysPrintLogger.WriteWarning("ActionEngine: EnableWindowsFeature requiere 'feature_name'");
                return false;
            }
            
            return AdminActions.EnableWindowsFeature(featureName);
        }

        /// <summary>
        /// Ejecuta un ConnectivityCheck enviando el comando al Tray vía Named Pipe.
        /// El Tray es responsable de ejecutar los HTTP checks, mostrar notificación y loguear.
        /// Fire-and-forget: retorna true siempre (no bloquea el trigger).
        /// </summary>
        private bool ExecuteConnectivityCheck(ActionConfig action)
        {
            try
            {
                // Extraer parámetros del JSON
                var urlsToken = action.Parameters?["urls"];
                var urls = urlsToken?.ToObject<List<string>>() ?? new List<string>();
                int timeoutSeconds = GetParameter<int>(action, "timeout_seconds", 5);
                int notificationGreenTimeout = GetParameter<int>(action, "notification_green_timeout_seconds", 5);
                int notificationYellowTimeout = GetParameter<int>(action, "notification_yellow_timeout_seconds", 10);

                if (urls.Count == 0)
                {
                    AlwaysPrintLogger.WriteWarning("ActionEngine: ConnectivityCheck sin URLs configuradas");
                    return true;
                }

                // Construir payload
                var payload = new ConnectivityCheckPayload
                {
                    Urls = urls,
                    TimeoutSeconds = timeoutSeconds,
                    NotificationGreenTimeoutSeconds = notificationGreenTimeout,
                    NotificationYellowTimeoutSeconds = notificationYellowTimeout
                };

                // Verificar si hay callback de envío de mensajes configurado
                if (_sendPipeMessageCallback == null)
                {
                    AlwaysPrintLogger.WriteWarning(
                        "ActionEngine: ConnectivityCheck - no hay callback de pipe configurado. No se puede enviar al Tray.",
                        AlwaysPrintLogger.EvtGenericWarning);
                    return true;
                }

                // Enviar vía pipe al Tray
                var message = PipeMessage.Create(MessageType.ConnectivityCheck, payload);
                bool sent = _sendPipeMessageCallback(message);

                if (!sent)
                {
                    AlwaysPrintLogger.WriteWarning(
                        $"ActionEngine: ConnectivityCheck - pipe no conectado, comando no enviado al Tray. " +
                        $"Se reintentará en el próximo ciclo.",
                        AlwaysPrintLogger.EvtGenericWarning);
                    return true;
                }

                AlwaysPrintLogger.WriteInfo(
                    $"ActionEngine: ConnectivityCheck: comando enviado al Tray ({urls.Count} URLs, timeout={timeoutSeconds}s)");

                return true;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"ActionEngine: ConnectivityCheck - error: {ex.Message}", ex);
                return true; // Fire-and-forget: no bloquear el trigger por errores
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
                    
                    case "not_empty":
                        // Evalúa si la variable no está vacía (listas con elementos o strings no vacíos)
                        if (variableValue is List<string> notEmptyList)
                            return notEmptyList.Count > 0;
                        if (variableValue is string notEmptyStr)
                            return !string.IsNullOrEmpty(notEmptyStr);
                        return variableValue != null;
                    
                    case "empty":
                        // Evalúa si la variable está vacía (lista sin elementos o string vacío)
                        if (variableValue is List<string> emptyList)
                            return emptyList.Count == 0;
                        if (variableValue is string emptyStr)
                            return string.IsNullOrEmpty(emptyStr);
                        return variableValue == null;
                    
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

        /// <summary>
        /// Lee la versión del driver de una cola de impresión.
        /// Parámetros: queue_name (nombre de la cola).
        /// Si se especifica store_result_in, almacena la versión en la variable indicada.
        /// </summary>
        private bool ExecuteReadPrintDriverVersion(ActionConfig action)
        {
            try
            {
                string queueName = GetParameter<string>(action, "queue_name") ?? "";
                queueName = ReplaceTemplates(queueName);

                if (string.IsNullOrEmpty(queueName))
                {
                    AlwaysPrintLogger.WriteWarning("ReadPrintDriverVersion: queue_name vacío");
                    return false;
                }

                string? version = AdminActions.ReadPrintDriverVersion(queueName);

                if (!string.IsNullOrEmpty(action.StoreResultIn) && version != null)
                {
                    _variables[action.StoreResultIn] = version;
                    _configVariables[action.StoreResultIn] = version;
                }

                return version != null;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"ReadPrintDriverVersion: error: {ex.Message}", ex);
                return false;
            }
        }

        /// <summary>
        /// Lee un valor del registro de la aplicación (ruta según build: AlwaysPrint o AlwaysPrint-DEV).
        /// Parámetros: value_name (string), default_value (string, opcional).
        /// Almacena el resultado en la variable indicada por store_result_in.
        /// No requiere especificar key_path — usa RegistryConfigManager.RegistryPath automáticamente.
        /// </summary>
        private bool ExecuteReadAppSetting(ActionConfig action)
        {
            try
            {
                string valueName = GetParameter<string>(action, "value_name") ?? "";
                string defaultValue = GetParameter<string>(action, "default_value") ?? "";

                valueName = ReplaceTemplates(valueName);

                if (string.IsNullOrEmpty(valueName))
                {
                    AlwaysPrintLogger.WriteWarning("ReadAppSetting: value_name vacío");
                    return false;
                }

                string keyPath = RegistryConfigManager.RegistryPath;
                AlwaysPrintLogger.WriteInfo($"ReadAppSetting: leyendo {valueName} de HKLM\\{keyPath}");

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

                AlwaysPrintLogger.WriteInfo($"ReadAppSetting: {valueName} = '{result}'");

                if (!string.IsNullOrEmpty(action.StoreResultIn))
                {
                    _variables[action.StoreResultIn] = result;
                    _configVariables[action.StoreResultIn] = result;
                }

                return true;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"ReadAppSetting: error: {ex.Message}", ex);
                return false;
            }
        }

        /// <summary>
        /// Escribe un valor en el registro de la aplicación (ruta según build: AlwaysPrint o AlwaysPrint-DEV).
        /// Parámetros: value_name (string), value (string), value_type (string: "dword" o "string", default "string").
        /// No requiere especificar key_path — usa RegistryConfigManager.RegistryPath automáticamente.
        /// </summary>
        private bool ExecuteWriteAppSetting(ActionConfig action)
        {
            try
            {
                string valueName = GetParameter<string>(action, "value_name") ?? "";
                string value = GetParameter<string>(action, "value") ?? "";
                string valueType = GetParameter<string>(action, "value_type") ?? "string";

                valueName = ReplaceTemplates(valueName);
                value = ReplaceTemplates(value);

                if (string.IsNullOrEmpty(valueName))
                {
                    AlwaysPrintLogger.WriteWarning("WriteAppSetting: value_name vacío");
                    return false;
                }

                string keyPath = RegistryConfigManager.RegistryPath;
                AlwaysPrintLogger.WriteInfo($"WriteAppSetting: escribiendo {valueName} = '{value}' ({valueType}) en HKLM\\{keyPath}");

                using (var key = Microsoft.Win32.Registry.LocalMachine.CreateSubKey(keyPath, writable: true))
                {
                    if (key == null)
                    {
                        AlwaysPrintLogger.WriteError("WriteAppSetting: no se pudo abrir/crear la clave de registro");
                        return false;
                    }

                    if (valueType.Equals("dword", StringComparison.OrdinalIgnoreCase))
                    {
                        int intValue = int.TryParse(value, out int parsed) ? parsed : 0;
                        key.SetValue(valueName, intValue, Microsoft.Win32.RegistryValueKind.DWord);
                    }
                    else
                    {
                        key.SetValue(valueName, value, Microsoft.Win32.RegistryValueKind.String);
                    }
                }

                AlwaysPrintLogger.WriteInfo($"WriteAppSetting: {valueName} escrito exitosamente");
                return true;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"WriteAppSetting: error: {ex.Message}", ex);
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
        /// Lee un parámetro de tipo array desde la configuración de acción.
        /// Retorna null si el parámetro no existe o no es un array válido.
        /// </summary>
        private T[]? GetParameterArray<T>(ActionConfig action, string paramName)
        {
            try
            {
                if (action.Parameters == null)
                    return null;

                if (!action.Parameters.TryGetValue(paramName, out JToken? token))
                    return null;

                if (token == null || token.Type != JTokenType.Array)
                    return null;

                return ((JArray)token).ToObject<T[]>();
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteWarning($"ActionEngine: error obteniendo parámetro array '{paramName}': {ex.Message}");
                return null;
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
        /// Obtiene la configuración del watchdog de servicios (si existe).
        /// </summary>
        public ServiceWatchdogConfig? GetServiceWatchdogConfig()
        {
            return _config?.ServiceWatchdog;
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

        /// <summary>
        /// Obtiene el interval_seconds configurado para un trigger específico.
        /// Retorna el valor configurado o 300 (5 min) como default si no está definido.
        /// </summary>
        public int GetTriggerIntervalSeconds(string eventName)
        {
            if (_config == null)
                return 300;

            var trigger = _config.Triggers.FirstOrDefault(t =>
                t.Event.Equals(eventName, StringComparison.OrdinalIgnoreCase));

            return trigger?.IntervalSeconds ?? 300;
        }
    }
}
