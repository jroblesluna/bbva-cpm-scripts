using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Management;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.ServiceProcess;
using System.Threading;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintService.Actions
{
    /// <summary>
    /// Funciones administrativas que se ejecutan con permisos de LocalSystem.
    /// Estas funciones son invocadas por el motor de acciones (ActionEngine).
    /// </summary>
    public static class AdminActions
    {
        // ═══════════════════════════════════════════════════════════════════════
        // GESTIÓN DE PERMISOS
        // ═══════════════════════════════════════════════════════════════════════
        
        /// <summary>
        /// Propaga los permisos de una carpeta a todas sus subcarpetas y archivos.
        /// Equivalente a: Habilitar herencia + Reemplazar permisos de objetos secundarios.
        /// </summary>
        public static bool PropagatePermissions(string path, bool recursive = true)
        {
            try
            {
                AlwaysPrintLogger.WriteInfo($"PropagatePermissions: iniciando para {path}, recursive={recursive}");
                
                if (!Directory.Exists(path))
                {
                    AlwaysPrintLogger.WriteWarning($"PropagatePermissions: carpeta no existe: {path}");
                    return false;
                }
                
                // Obtener permisos de la carpeta raíz
                var rootDirInfo = new DirectoryInfo(path);
                var rootSecurity = rootDirInfo.GetAccessControl();
                
                // Habilitar herencia en la carpeta raíz
                rootSecurity.SetAccessRuleProtection(false, true);
                rootDirInfo.SetAccessControl(rootSecurity);
                
                if (recursive)
                {
                    // Propagar a todas las subcarpetas
                    PropagatePermissionsRecursive(path, rootSecurity);
                }
                
                AlwaysPrintLogger.WriteInfo($"PropagatePermissions: completado para {path}");
                return true;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"PropagatePermissions: error en {path}: {ex.Message}", ex);
                return false;
            }
        }
        
        private static void PropagatePermissionsRecursive(string path, DirectorySecurity parentSecurity)
        {
            try
            {
                // Procesar subcarpetas
                foreach (var dir in Directory.GetDirectories(path))
                {
                    try
                    {
                        var dirInfo = new DirectoryInfo(dir);
                        var dirSecurity = dirInfo.GetAccessControl();
                        
                        // Habilitar herencia
                        dirSecurity.SetAccessRuleProtection(false, true);
                        dirInfo.SetAccessControl(dirSecurity);
                        
                        // Recursión
                        PropagatePermissionsRecursive(dir, dirSecurity);
                    }
                    catch (Exception ex)
                    {
                        AlwaysPrintLogger.WriteWarning($"PropagatePermissions: error en subcarpeta {dir}: {ex.Message}");
                    }
                }
                
                // Procesar archivos
                foreach (var file in Directory.GetFiles(path))
                {
                    try
                    {
                        var fileInfo = new FileInfo(file);
                        var fileSecurity = fileInfo.GetAccessControl();
                        
                        // Habilitar herencia
                        fileSecurity.SetAccessRuleProtection(false, true);
                        fileInfo.SetAccessControl(fileSecurity);
                    }
                    catch (Exception ex)
                    {
                        AlwaysPrintLogger.WriteWarning($"PropagatePermissions: error en archivo {file}: {ex.Message}");
                    }
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteWarning($"PropagatePermissions: error procesando {path}: {ex.Message}");
            }
        }
        
        // ═══════════════════════════════════════════════════════════════════════
        // GESTIÓN DE USUARIOS
        // ═══════════════════════════════════════════════════════════════════════
        
        /// <summary>
        /// Obtiene la lista de usuarios con sesión activa usando WTS API.
        /// Más confiable que WMI en todas las versiones de Windows.
        /// </summary>
        public static List<string> GetLoggedInUsers(bool excludeActiveConsoleUser = false)
        {
            var users = new List<string>();
            
            try
            {
                AlwaysPrintLogger.WriteInfo($"GetLoggedInUsers: iniciando, excludeActiveConsoleUser={excludeActiveConsoleUser}");
                
                string? activeConsoleUser = null;
                
                if (excludeActiveConsoleUser)
                {
                    activeConsoleUser = GetActiveConsoleUser();
                    AlwaysPrintLogger.WriteInfo($"GetLoggedInUsers: usuario de consola activa: {activeConsoleUser ?? "ninguno"}");
                }
                
                // Usar WTS API para enumerar sesiones (más confiable que WMI)
                IntPtr serverHandle = IntPtr.Zero; // Local server
                IntPtr pSessionInfo = IntPtr.Zero;
                int sessionCount = 0;
                
                if (!WTSEnumerateSessions(serverHandle, 0, 1, ref pSessionInfo, ref sessionCount))
                {
                    AlwaysPrintLogger.WriteWarning("GetLoggedInUsers: WTSEnumerateSessions falló");
                    return users;
                }
                
                try
                {
                    int structSize = Marshal.SizeOf(typeof(WTS_SESSION_INFO));
                    
                    for (int i = 0; i < sessionCount; i++)
                    {
                        IntPtr currentPtr = new IntPtr(pSessionInfo.ToInt64() + (i * structSize));
                        var sessionInfo = (WTS_SESSION_INFO)Marshal.PtrToStructure(currentPtr, typeof(WTS_SESSION_INFO))!;
                        
                        // Solo sesiones activas o desconectadas (no listener, idle, etc.)
                        if (sessionInfo.State != WTS_CONNECTSTATE_CLASS.WTSActive &&
                            sessionInfo.State != WTS_CONNECTSTATE_CLASS.WTSDisconnected)
                        {
                            continue;
                        }
                        
                        // Obtener nombre de usuario de la sesión
                        IntPtr buffer = IntPtr.Zero;
                        uint bytesReturned = 0;
                        
                        if (WTSQuerySessionInformation(serverHandle, (uint)sessionInfo.SessionId,
                            WTS_INFO_CLASS.WTSUserName, out buffer, out bytesReturned))
                        {
                            string username = Marshal.PtrToStringAnsi(buffer) ?? "";
                            WTSFreeMemory(buffer);
                            
                            if (string.IsNullOrEmpty(username))
                                continue;
                            
                            // Evitar duplicados
                            if (users.Contains(username, StringComparer.OrdinalIgnoreCase))
                                continue;
                            
                            // Excluir usuario de consola activa si se solicita
                            if (excludeActiveConsoleUser &&
                                !string.IsNullOrEmpty(activeConsoleUser) &&
                                username.Equals(activeConsoleUser, StringComparison.OrdinalIgnoreCase))
                            {
                                AlwaysPrintLogger.WriteInfo($"GetLoggedInUsers: excluyendo usuario de consola activa: {username}");
                                continue;
                            }
                            
                            users.Add(username);
                            AlwaysPrintLogger.WriteInfo(
                                $"GetLoggedInUsers: sesión encontrada - usuario={username}, " +
                                $"sessionId={sessionInfo.SessionId}, estado={sessionInfo.State}");
                        }
                    }
                }
                finally
                {
                    WTSFreeMemory(pSessionInfo);
                }
                
                AlwaysPrintLogger.WriteInfo($"GetLoggedInUsers: encontrados {users.Count} usuarios: {string.Join(", ", users)}");
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"GetLoggedInUsers: error: {ex.Message}", ex);
            }
            
            return users;
        }
        
        private static string? GetActiveConsoleUser()
        {
            try
            {
                uint sessionId = WTSGetActiveConsoleSessionId();
                
                if (sessionId == 0xFFFFFFFF) // NO_ACTIVE_SESSION
                    return null;
                
                IntPtr buffer = IntPtr.Zero;
                uint bytesReturned = 0;
                
                if (WTSQuerySessionInformation(IntPtr.Zero, sessionId, WTS_INFO_CLASS.WTSUserName, 
                    out buffer, out bytesReturned))
                {
                    string username = Marshal.PtrToStringAnsi(buffer) ?? "";
                    WTSFreeMemory(buffer);
                    return string.IsNullOrEmpty(username) ? null : username;
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteWarning($"GetActiveConsoleUser: error: {ex.Message}");
            }
            
            return null;
        }
        
        // ═══════════════════════════════════════════════════════════════════════
        // GESTIÓN DE ARCHIVOS
        // ═══════════════════════════════════════════════════════════════════════
        
        /// <summary>
        /// Elimina el contenido de una carpeta (archivos y subcarpetas).
        /// </summary>
        public static bool DeleteFolderContents(string path, bool recursive = true, bool ignoreErrors = true)
        {
            try
            {
                AlwaysPrintLogger.WriteInfo($"DeleteFolderContents: iniciando para {path}, recursive={recursive}");
                
                if (!Directory.Exists(path))
                {
                    AlwaysPrintLogger.WriteWarning($"DeleteFolderContents: carpeta no existe: {path}");
                    return ignoreErrors;
                }
                
                int deletedFiles = 0;
                int deletedDirs = 0;
                int errors = 0;
                
                // Eliminar archivos
                foreach (var file in Directory.GetFiles(path))
                {
                    try
                    {
                        File.Delete(file);
                        deletedFiles++;
                    }
                    catch (Exception ex)
                    {
                        errors++;
                        AlwaysPrintLogger.WriteWarning($"DeleteFolderContents: error eliminando archivo {file}: {ex.Message}");
                        
                        if (!ignoreErrors)
                            throw;
                    }
                }
                
                // Eliminar subcarpetas si recursive=true
                if (recursive)
                {
                    foreach (var dir in Directory.GetDirectories(path))
                    {
                        try
                        {
                            Directory.Delete(dir, true);
                            deletedDirs++;
                        }
                        catch (Exception ex)
                        {
                            errors++;
                            AlwaysPrintLogger.WriteWarning($"DeleteFolderContents: error eliminando carpeta {dir}: {ex.Message}");
                            
                            if (!ignoreErrors)
                                throw;
                        }
                    }
                }
                
                AlwaysPrintLogger.WriteInfo(
                    $"DeleteFolderContents: completado para {path}. " +
                    $"Archivos eliminados: {deletedFiles}, Carpetas eliminadas: {deletedDirs}, Errores: {errors}");
                
                return errors == 0 || ignoreErrors;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"DeleteFolderContents: error en {path}: {ex.Message}", ex);
                return false;
            }
        }
        
        // ═══════════════════════════════════════════════════════════════════════
        // ELIMINACIÓN DE CARPETAS HUÉRFANAS
        // ═══════════════════════════════════════════════════════════════════════
        
        /// <summary>
        /// Elimina carpetas de usuarios que no tienen sesión abierta (ni activa ni desconectada).
        /// Enumera subdirectorios de basePath y elimina los que no están en la lista de exclusión.
        /// </summary>
        /// <param name="basePath">Directorio base que contiene carpetas por usuario.</param>
        /// <param name="excludeUsers">Lista de usuarios cuyas carpetas se deben preservar.</param>
        /// <param name="excludeActiveConsoleUser">Si true, también preserva la carpeta del usuario de consola activa.</param>
        /// <returns>Cantidad de carpetas eliminadas.</returns>
        public static int DeleteOrphanedFolders(string basePath, List<string> excludeUsers, bool excludeActiveConsoleUser = true)
        {
            int deleted = 0;
            
            try
            {
                AlwaysPrintLogger.WriteInfo(
                    $"DeleteOrphanedFolders: iniciando en {basePath}, " +
                    $"excludeUsers=[{string.Join(", ", excludeUsers)}], excludeActiveConsole={excludeActiveConsoleUser}");
                
                if (!Directory.Exists(basePath))
                {
                    AlwaysPrintLogger.WriteWarning($"DeleteOrphanedFolders: directorio base no existe: {basePath}");
                    return 0;
                }
                
                // Construir lista completa de usuarios a preservar
                var preserveUsers = new HashSet<string>(excludeUsers, StringComparer.OrdinalIgnoreCase);
                
                if (excludeActiveConsoleUser)
                {
                    string? activeUser = GetActiveConsoleUser();
                    if (!string.IsNullOrEmpty(activeUser))
                    {
                        preserveUsers.Add(activeUser!);
                        AlwaysPrintLogger.WriteInfo($"DeleteOrphanedFolders: preservando usuario de consola activa: {activeUser}");
                    }
                }
                
                AlwaysPrintLogger.WriteInfo($"DeleteOrphanedFolders: usuarios a preservar: [{string.Join(", ", preserveUsers)}]");
                
                // Enumerar subdirectorios y eliminar los huérfanos
                foreach (var dir in Directory.GetDirectories(basePath))
                {
                    string folderName = Path.GetFileName(dir);
                    
                    if (preserveUsers.Contains(folderName))
                    {
                        AlwaysPrintLogger.WriteInfo($"DeleteOrphanedFolders: preservando carpeta: {folderName}");
                        continue;
                    }
                    
                    try
                    {
                        Directory.Delete(dir, recursive: true);
                        deleted++;
                        AlwaysPrintLogger.WriteInfo($"DeleteOrphanedFolders: carpeta eliminada: {dir}");
                    }
                    catch (Exception ex)
                    {
                        AlwaysPrintLogger.WriteWarning($"DeleteOrphanedFolders: error eliminando {dir}: {ex.Message}");
                    }
                }
                
                AlwaysPrintLogger.WriteInfo($"DeleteOrphanedFolders: completado. Carpetas eliminadas: {deleted}");
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"DeleteOrphanedFolders: error: {ex.Message}", ex);
            }
            
            return deleted;
        }
        
        // ═══════════════════════════════════════════════════════════════════════
        // MODO CONTINGENCIA (SHIELD MODE)
        // ═══════════════════════════════════════════════════════════════════════
        
        /// <summary>
        /// Entra en modo contingencia (Shield Mode):
        /// 1. Detiene el servicio Spooler
        /// 2. Crea y asigna un puerto TCP/IP directo a la impresora de contingencia
        /// 3. Reinicia el servicio Spooler
        /// 
        /// Parámetros:
        /// - queue_name: nombre de la cola corporativa (ej: "LexmarkBBVA")
        /// - printer_ip: IP de la impresora de contingencia
        /// - printer_port: puerto de la impresora (default: 9100)
        /// </summary>
        public static bool EnterShieldMode(string queueName, string printerIp, int printerPort = 9100)
        {
            try
            {
                AlwaysPrintLogger.WriteInfo(
                    $"EnterShieldMode: iniciando contingencia. Cola={queueName}, IP={printerIp}:{printerPort}");

                // 1. Detener Spooler
                AlwaysPrintLogger.WriteInfo("EnterShieldMode: deteniendo servicio Spooler...");
                if (!StopService("Spooler", 30, false))
                {
                    AlwaysPrintLogger.WriteError(
                        "EnterShieldMode: no se pudo detener el Spooler. Abortando.",
                        AlwaysPrintLogger.EvtGenericError);
                    return false;
                }

                // 2. Crear o actualizar puerto TCP/IP directo
                string portName = $"AP_SHIELD_{printerIp}_{printerPort}";
                AlwaysPrintLogger.WriteInfo($"EnterShieldMode: configurando puerto {portName}...");
                if (!CreateOrUpdateTcpPort(portName, printerIp, printerPort))
                {
                    AlwaysPrintLogger.WriteError(
                        "EnterShieldMode: no se pudo crear/actualizar puerto TCP/IP. Reiniciando Spooler.",
                        AlwaysPrintLogger.EvtGenericError);
                    StartService("Spooler");
                    return false;
                }

                // 3. Asignar el puerto a la cola corporativa
                AlwaysPrintLogger.WriteInfo($"EnterShieldMode: asignando puerto {portName} a cola {queueName}...");
                if (!AssignPortToQueue(queueName, portName))
                {
                    AlwaysPrintLogger.WriteError(
                        "EnterShieldMode: no se pudo asignar puerto a la cola. Reiniciando Spooler.",
                        AlwaysPrintLogger.EvtGenericError);
                    StartService("Spooler");
                    return false;
                }

                // 4. Reiniciar Spooler
                AlwaysPrintLogger.WriteInfo("EnterShieldMode: reiniciando servicio Spooler...");
                if (!StartService("Spooler"))
                {
                    AlwaysPrintLogger.WriteError(
                        "EnterShieldMode: no se pudo reiniciar el Spooler.",
                        AlwaysPrintLogger.EvtGenericError);
                    return false;
                }

                AlwaysPrintLogger.WriteInfo(
                    $"EnterShieldMode: contingencia activada exitosamente. " +
                    $"Cola '{queueName}' → {printerIp}:{printerPort}");
                return true;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"EnterShieldMode: error crítico: {ex.Message}", ex);
                try { StartService("Spooler"); } catch { /* mejor esfuerzo */ }
                return false;
            }
        }

        /// <summary>
        /// Sale del modo contingencia (Shield Mode):
        /// 1. Detiene el servicio Spooler
        /// 2. Asigna el puerto del monitor LPMC (Lexmark CPM) a la cola corporativa
        /// 3. Reinicia el servicio Spooler
        /// 
        /// Parámetros:
        /// - queue_name: nombre de la cola corporativa (ej: "LexmarkBBVA")
        /// - lpmc_port_name: nombre del puerto LPMC (default: "LPMC:")
        /// </summary>
        public static bool ExitShieldMode(string queueName, string lpmcPortName = "LPMC:")
        {
            try
            {
                AlwaysPrintLogger.WriteInfo(
                    $"ExitShieldMode: saliendo de contingencia. Cola={queueName}, Puerto LPMC={lpmcPortName}");

                // 1. Detener Spooler
                AlwaysPrintLogger.WriteInfo("ExitShieldMode: deteniendo servicio Spooler...");
                if (!StopService("Spooler", 30, false))
                {
                    AlwaysPrintLogger.WriteError(
                        "ExitShieldMode: no se pudo detener el Spooler. Abortando.",
                        AlwaysPrintLogger.EvtGenericError);
                    return false;
                }

                // 2. Asignar el puerto LPMC a la cola corporativa
                AlwaysPrintLogger.WriteInfo($"ExitShieldMode: asignando puerto {lpmcPortName} a cola {queueName}...");
                if (!AssignPortToQueue(queueName, lpmcPortName))
                {
                    AlwaysPrintLogger.WriteError(
                        "ExitShieldMode: no se pudo asignar puerto LPMC a la cola. Reiniciando Spooler.",
                        AlwaysPrintLogger.EvtGenericError);
                    StartService("Spooler");
                    return false;
                }

                // 3. Reiniciar Spooler
                AlwaysPrintLogger.WriteInfo("ExitShieldMode: reiniciando servicio Spooler...");
                if (!StartService("Spooler"))
                {
                    AlwaysPrintLogger.WriteError(
                        "ExitShieldMode: no se pudo reiniciar el Spooler.",
                        AlwaysPrintLogger.EvtGenericError);
                    return false;
                }

                AlwaysPrintLogger.WriteInfo(
                    $"ExitShieldMode: contingencia desactivada. Cola '{queueName}' → {lpmcPortName} (CPM)");
                return true;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"ExitShieldMode: error crítico: {ex.Message}", ex);
                try { StartService("Spooler"); } catch { /* mejor esfuerzo */ }
                return false;
            }
        }

        /// <summary>
        /// Crea o actualiza un puerto TCP/IP de impresora via WMI.
        /// </summary>
        private static bool CreateOrUpdateTcpPort(string portName, string hostAddress, int portNumber)
        {
            try
            {
                string safePort = portName.Replace("'", "''");
                using var portSearch = new ManagementObjectSearcher(
                    @"\\.\root\cimv2",
                    $"SELECT * FROM Win32_TCPIPPrinterPort WHERE Name = '{safePort}'");

                ManagementObject? existingPort = null;
                foreach (ManagementObject obj in portSearch.Get())
                {
                    existingPort = obj;
                    break;
                }

                if (existingPort != null)
                {
                    existingPort["HostAddress"] = hostAddress;
                    existingPort["PortNumber"] = portNumber;
                    existingPort.Put();
                    AlwaysPrintLogger.WriteInfo($"CreateOrUpdateTcpPort: puerto '{portName}' actualizado a {hostAddress}:{portNumber}");
                    return true;
                }

                var portClass = new ManagementClass("Win32_TCPIPPrinterPort");
                var newPort = portClass.CreateInstance();
                if (newPort == null) return false;

                newPort["Name"] = portName;
                newPort["HostAddress"] = hostAddress;
                newPort["PortNumber"] = portNumber;
                newPort["Protocol"] = 1; // RAW
                newPort["SNMPEnabled"] = false;
                newPort.Put();

                AlwaysPrintLogger.WriteInfo($"CreateOrUpdateTcpPort: puerto '{portName}' creado → {hostAddress}:{portNumber}");
                return true;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"CreateOrUpdateTcpPort: error: {ex.Message}", ex);
                return false;
            }
        }

        /// <summary>
        /// Asigna un puerto (por nombre) a una cola de impresión Windows via WMI.
        /// </summary>
        private static bool AssignPortToQueue(string queueName, string portName)
        {
            try
            {
                string safeQueue = queueName.Replace("'", "''");
                using var printerSearch = new ManagementObjectSearcher(
                    @"\\.\root\cimv2",
                    $"SELECT * FROM Win32_Printer WHERE Name = '{safeQueue}'");

                ManagementObject? printer = null;
                foreach (ManagementObject obj in printerSearch.Get())
                {
                    printer = obj;
                    break;
                }

                if (printer == null)
                {
                    AlwaysPrintLogger.WriteError($"AssignPortToQueue: cola '{queueName}' no encontrada en WMI");
                    return false;
                }

                printer["PortName"] = portName;
                printer.Put();

                AlwaysPrintLogger.WriteInfo($"AssignPortToQueue: cola '{queueName}' asignada a puerto '{portName}'");
                return true;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"AssignPortToQueue: error: {ex.Message}", ex);
                return false;
            }
        }

        // ═══════════════════════════════════════════════════════════════════════
        // GESTIÓN DE COLAS DE IMPRESIÓN
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Pausa una cola de impresión Windows via WMI.
        /// Parámetros: queue_name (nombre de la cola)
        /// </summary>
        public static bool PausePrintQueue(string queueName)
        {
            try
            {
                AlwaysPrintLogger.WriteInfo($"PausePrintQueue: pausando cola '{queueName}'...");

                string safeQueue = queueName.Replace("'", "''");
                using var searcher = new ManagementObjectSearcher(
                    @"\\.\root\cimv2",
                    $"SELECT * FROM Win32_Printer WHERE Name = '{safeQueue}'");

                ManagementObject? printer = null;
                foreach (ManagementObject obj in searcher.Get())
                {
                    printer = obj;
                    break;
                }

                if (printer == null)
                {
                    AlwaysPrintLogger.WriteWarning($"PausePrintQueue: cola '{queueName}' no encontrada en WMI");
                    return false;
                }

                printer.InvokeMethod("Pause", null);
                AlwaysPrintLogger.WriteInfo($"PausePrintQueue: cola '{queueName}' pausada exitosamente");
                return true;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"PausePrintQueue: error pausando cola '{queueName}': {ex.Message}", ex);
                return false;
            }
        }

        /// <summary>
        /// Reanuda una cola de impresión Windows via WMI.
        /// Parámetros: queue_name (nombre de la cola)
        /// </summary>
        public static bool UnpausePrintQueue(string queueName)
        {
            try
            {
                AlwaysPrintLogger.WriteInfo($"UnpausePrintQueue: reanudando cola '{queueName}'...");

                string safeQueue = queueName.Replace("'", "''");
                using var searcher = new ManagementObjectSearcher(
                    @"\\.\root\cimv2",
                    $"SELECT * FROM Win32_Printer WHERE Name = '{safeQueue}'");

                ManagementObject? printer = null;
                foreach (ManagementObject obj in searcher.Get())
                {
                    printer = obj;
                    break;
                }

                if (printer == null)
                {
                    AlwaysPrintLogger.WriteWarning($"UnpausePrintQueue: cola '{queueName}' no encontrada en WMI");
                    return false;
                }

                printer.InvokeMethod("Resume", null);
                AlwaysPrintLogger.WriteInfo($"UnpausePrintQueue: cola '{queueName}' reanudada exitosamente");
                return true;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"UnpausePrintQueue: error reanudando cola '{queueName}': {ex.Message}", ex);
                return false;
            }
        }

        /// <summary>
        /// Establece una impresora como predeterminada para el usuario logueado.
        /// Como el Service corre como SYSTEM, esta acción se delega al Tray via Named Pipe.
        /// El Tray detecta el cambio de contingencia y establece la impresora predeterminada
        /// en el contexto del usuario interactivo.
        /// Parámetros: queue_name (nombre de la cola/impresora)
        /// </summary>
        public static bool SetDefaultPrinter(string queueName)
        {
            // TODO: El Service corre como SYSTEM, por lo que SetDefaultPrinterW no afecta
            // al usuario interactivo. Esta acción se delega al Tray, que ya recibe la
            // notificación de contingencia y puede ejecutar SetDefaultPrinter en contexto de usuario.
            AlwaysPrintLogger.WriteInfo(
                $"SetDefaultPrinter: acción delegada al Tray. " +
                $"La impresora '{queueName}' será establecida como predeterminada " +
                $"por el Tray al detectar el cambio de contingencia.");
            return true;
        }

        // ═══════════════════════════════════════════════════════════════════════
        // GESTIÓN DE SERVICIOS
        // ═══════════════════════════════════════════════════════════════════════
        
        /// <summary>
        /// Detiene un servicio de Windows.
        /// </summary>
        public static bool StopService(string serviceName, int gracefulTimeoutSeconds = 30, bool forceKillOnTimeout = false)
        {
            try
            {
                AlwaysPrintLogger.WriteInfo($"StopService: deteniendo {serviceName}, timeout={gracefulTimeoutSeconds}s, force={forceKillOnTimeout}");
                
                using (var sc = new ServiceController(serviceName))
                {
                    if (sc.Status == ServiceControllerStatus.Stopped)
                    {
                        AlwaysPrintLogger.WriteInfo($"StopService: {serviceName} ya está detenido");
                        return true;
                    }
                    
                    if (sc.Status != ServiceControllerStatus.StopPending)
                    {
                        sc.Stop();
                    }
                    
                    sc.WaitForStatus(ServiceControllerStatus.Stopped, TimeSpan.FromSeconds(gracefulTimeoutSeconds));
                    
                    AlwaysPrintLogger.WriteInfo($"StopService: {serviceName} detenido correctamente");
                    return true;
                }
            }
            catch (System.TimeoutException)
            {
                AlwaysPrintLogger.WriteWarning($"StopService: timeout deteniendo {serviceName}");
                
                if (forceKillOnTimeout)
                {
                    AlwaysPrintLogger.WriteWarning($"StopService: intentando kill forzado de {serviceName}");
                    // TODO: Implementar kill forzado del proceso del servicio
                }
                
                return false;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"StopService: error deteniendo {serviceName}: {ex.Message}", ex);
                return false;
            }
        }
        
        /// <summary>
        /// Inicia un servicio de Windows.
        /// </summary>
        public static bool StartService(string serviceName, bool waitForRunning = true, int timeoutSeconds = 30)
        {
            try
            {
                AlwaysPrintLogger.WriteInfo($"StartService: iniciando {serviceName}, wait={waitForRunning}, timeout={timeoutSeconds}s");
                
                using (var sc = new ServiceController(serviceName))
                {
                    if (sc.Status == ServiceControllerStatus.Running)
                    {
                        AlwaysPrintLogger.WriteInfo($"StartService: {serviceName} ya está corriendo");
                        return true;
                    }
                    
                    if (sc.Status != ServiceControllerStatus.StartPending)
                    {
                        sc.Start();
                    }
                    
                    if (waitForRunning)
                    {
                        sc.WaitForStatus(ServiceControllerStatus.Running, TimeSpan.FromSeconds(timeoutSeconds));
                    }
                    
                    AlwaysPrintLogger.WriteInfo($"StartService: {serviceName} iniciado correctamente");
                    return true;
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"StartService: error iniciando {serviceName}: {ex.Message}", ex);
                return false;
            }
        }
        
        // ═══════════════════════════════════════════════════════════════════════
        // GESTIÓN DE PROCESOS
        // ═══════════════════════════════════════════════════════════════════════
        
        /// <summary>
        /// Mata procesos por nombre, opcionalmente filtrando por usuarios.
        /// </summary>
        public static int KillProcessesByName(string processName, List<string>? filterByUsers = null, bool force = true)
        {
            int killed = 0;
            
            try
            {
                AlwaysPrintLogger.WriteInfo($"KillProcessesByName: matando {processName}, users={filterByUsers?.Count ?? 0}, force={force}");
                
                // Remover extensión .exe si está presente
                if (processName.EndsWith(".exe", StringComparison.OrdinalIgnoreCase))
                {
                    processName = processName.Substring(0, processName.Length - 4);
                }
                
                foreach (var process in Process.GetProcessesByName(processName))
                {
                    try
                    {
                        // Filtrar por usuario si se especifica
                        if (filterByUsers != null && filterByUsers.Count > 0)
                        {
                            string? processUser = GetProcessOwner(process);
                            
                            if (string.IsNullOrEmpty(processUser) || 
                                !filterByUsers.Contains(processUser, StringComparer.OrdinalIgnoreCase))
                            {
                                continue;
                            }
                        }
                        
                        AlwaysPrintLogger.WriteInfo($"KillProcessesByName: matando proceso {process.ProcessName} (PID: {process.Id})");
                        
                        if (force)
                        {
                            process.Kill();
                        }
                        else
                        {
                            process.CloseMainWindow();
                            
                            if (!process.WaitForExit(5000))
                            {
                                process.Kill();
                            }
                        }
                        
                        killed++;
                    }
                    catch (Exception ex)
                    {
                        AlwaysPrintLogger.WriteWarning($"KillProcessesByName: error matando proceso {process.Id}: {ex.Message}");
                    }
                }
                
                AlwaysPrintLogger.WriteInfo($"KillProcessesByName: {killed} procesos eliminados");
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"KillProcessesByName: error: {ex.Message}", ex);
            }
            
            return killed;
        }
        
        private static string? GetProcessOwner(Process process)
        {
            try
            {
                string query = $"SELECT * FROM Win32_Process WHERE ProcessId = {process.Id}";
                
                using (var searcher = new ManagementObjectSearcher(query))
                {
                    foreach (ManagementObject obj in searcher.Get())
                    {
                        string[] owner = new string[2];
                        obj.InvokeMethod("GetOwner", (object[])owner);
                        return owner[0]; // Username
                    }
                }
            }
            catch
            {
                // Ignorar errores
            }
            
            return null;
        }
        
        // ═══════════════════════════════════════════════════════════════════════
        // P/INVOKE para WTS APIs
        // ═══════════════════════════════════════════════════════════════════════
        
        [DllImport("kernel32.dll")]
        private static extern uint WTSGetActiveConsoleSessionId();
        
        [DllImport("wtsapi32.dll", SetLastError = true)]
        private static extern bool WTSEnumerateSessions(
            IntPtr hServer,
            int reserved,
            int version,
            ref IntPtr ppSessionInfo,
            ref int pCount);
        
        [DllImport("wtsapi32.dll", SetLastError = true)]
        private static extern bool WTSQuerySessionInformation(
            IntPtr hServer,
            uint sessionId,
            WTS_INFO_CLASS wtsInfoClass,
            out IntPtr ppBuffer,
            out uint pBytesReturned);
        
        [DllImport("wtsapi32.dll")]
        private static extern void WTSFreeMemory(IntPtr pMemory);
        
        private enum WTS_INFO_CLASS
        {
            WTSUserName = 5,
        }
        
        private enum WTS_CONNECTSTATE_CLASS
        {
            WTSActive,
            WTSConnected,
            WTSConnectQuery,
            WTSShadow,
            WTSDisconnected,
            WTSIdle,
            WTSListen,
            WTSReset,
            WTSDown,
            WTSInit
        }
        
        [StructLayout(LayoutKind.Sequential)]
        private struct WTS_SESSION_INFO
        {
            public int SessionId;
            [MarshalAs(UnmanagedType.LPStr)]
            public string pWinStationName;
            public WTS_CONNECTSTATE_CLASS State;
        }
    }
}
