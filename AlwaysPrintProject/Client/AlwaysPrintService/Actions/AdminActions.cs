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
        // OPERACIONES ATÓMICAS DE PUERTOS E IMPRESORAS
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Crea o actualiza un puerto TCP/IP de impresora via WMI.
        /// Si el puerto ya existe con la misma configuración (host y port), retorna éxito
        /// sin intentar escribir — evita el "Error genérico" de WMI en ciertos entornos
        /// donde el puerto fue creado por GPO u otro mecanismo que bloquea escritura.
        /// </summary>
        public static bool CreateOrUpdateTcpPort(string portName, string hostAddress, int portNumber)
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
                    // Verificar si ya tiene la configuración deseada antes de intentar escribir
                    string currentHost = existingPort["HostAddress"]?.ToString() ?? "";
                    int currentPort = 0;
                    if (existingPort["PortNumber"] != null)
                        int.TryParse(existingPort["PortNumber"].ToString(), out currentPort);

                    if (string.Equals(currentHost, hostAddress, StringComparison.OrdinalIgnoreCase)
                        && currentPort == portNumber)
                    {
                        AlwaysPrintLogger.WriteInfo(
                            $"CreateOrUpdateTcpPort: puerto '{portName}' ya configurado correctamente ({hostAddress}:{portNumber}). Sin cambios.");
                        return true;
                    }

                    // Configuración diferente: intentar actualizar
                    try
                    {
                        existingPort["HostAddress"] = hostAddress;
                        existingPort["PortNumber"] = portNumber;
                        existingPort.Put();
                        AlwaysPrintLogger.WriteInfo($"CreateOrUpdateTcpPort: puerto '{portName}' actualizado a {hostAddress}:{portNumber}");
                        return true;
                    }
                    catch (ManagementException ex)
                    {
                        // Si falla la escritura pero el puerto ya existe, intentar recrear
                        AlwaysPrintLogger.WriteWarning(
                            $"CreateOrUpdateTcpPort: no se pudo actualizar puerto '{portName}' ({ex.Message}). " +
                            "Intentando eliminar y recrear...");

                        try
                        {
                            existingPort.Delete();
                            AlwaysPrintLogger.WriteInfo(
                                $"CreateOrUpdateTcpPort: puerto '{portName}' eliminado para recreación.");
                        }
                        catch (Exception delEx)
                        {
                            // No se pudo eliminar (puede estar en uso por una cola)
                            AlwaysPrintLogger.WriteError(
                                $"CreateOrUpdateTcpPort: no se pudo eliminar puerto '{portName}': {delEx.Message}. " +
                                "Puede estar asignado a una cola de impresión.", delEx);
                            return false;
                        }

                        // Caer al bloque de creación abajo
                    }
                }

                // Crear puerto nuevo
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
        /// Elimina un puerto TCP/IP de impresora via WMI.
        /// Solo se puede eliminar si no está asignado a ninguna cola.
        /// Parámetros: port_name (nombre del puerto a eliminar)
        /// </summary>
        public static bool DeleteTcpPort(string portName)
        {
            try
            {
                AlwaysPrintLogger.WriteInfo($"DeleteTcpPort: eliminando puerto '{portName}'...");

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

                if (existingPort == null)
                {
                    AlwaysPrintLogger.WriteInfo($"DeleteTcpPort: puerto '{portName}' no existe. Nada que eliminar.");
                    return true; // No es error si no existe
                }

                existingPort.Delete();
                AlwaysPrintLogger.WriteInfo($"DeleteTcpPort: puerto '{portName}' eliminado exitosamente.");
                return true;
            }
            catch (Exception ex)
            {
                // Si falla porque está en uso, loggear warning (no es crítico)
                AlwaysPrintLogger.WriteWarning(
                    $"DeleteTcpPort: no se pudo eliminar puerto '{portName}': {ex.Message}. " +
                    "Puede estar en uso por otra cola.");
                return false;
            }
        }

        /// <summary>
        /// Asigna un puerto (por nombre) a una cola de impresión Windows via WMI.
        /// </summary>
        public static bool AssignPortToQueue(string queueName, string portName)
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
        /// Lee la versión del driver de impresora asociado a una cola.
        /// Usa Win32_Printer para obtener el nombre del driver, luego Win32_PrinterDriver
        /// para obtener la versión del archivo .dll del driver.
        /// Parámetros: queue_name (nombre de la cola)
        /// Retorna: string con la versión del driver, o null si no se pudo obtener.
        /// </summary>
        public static string? ReadPrintDriverVersion(string queueName)
        {
            try
            {
                AlwaysPrintLogger.WriteInfo($"ReadPrintDriverVersion: leyendo driver de cola '{queueName}'...");

                // 1. Obtener el nombre del driver desde Win32_Printer
                string safeQueue = queueName.Replace("'", "''");
                using var printerSearch = new ManagementObjectSearcher(
                    @"\\.\root\cimv2",
                    $"SELECT DriverName FROM Win32_Printer WHERE Name = '{safeQueue}'");

                string? driverName = null;
                foreach (ManagementObject obj in printerSearch.Get())
                {
                    driverName = obj["DriverName"]?.ToString();
                    break;
                }

                if (string.IsNullOrEmpty(driverName))
                {
                    AlwaysPrintLogger.WriteWarning(
                        $"ReadPrintDriverVersion: cola '{queueName}' no encontrada o sin driver asignado");
                    return null;
                }

                AlwaysPrintLogger.WriteInfo(
                    $"ReadPrintDriverVersion: cola '{queueName}' usa driver '{driverName}'");

                // 2. Leer DriverVersion directamente del registro de drivers de impresión
                string[] envPaths = new[]
                {
                    $@"SYSTEM\CurrentControlSet\Control\Print\Environments\Windows x64\Drivers\Version-3\{driverName}",
                    $@"SYSTEM\CurrentControlSet\Control\Print\Environments\Windows x64\Drivers\Version-4\{driverName}",
                    $@"SYSTEM\CurrentControlSet\Control\Print\Environments\Windows NT x86\Drivers\Version-3\{driverName}"
                };

                foreach (var regPath in envPaths)
                {
                    using var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(regPath);
                    if (key == null) continue;

                    string? version = key.GetValue("DriverVersion")?.ToString();
                    if (!string.IsNullOrEmpty(version))
                    {
                        AlwaysPrintLogger.WriteInfo(
                            $"ReadPrintDriverVersion: driver '{driverName}' versión = {version}");
                        return version;
                    }
                }

                // Fallback: no se encontró DriverVersion en registro
                AlwaysPrintLogger.WriteWarning(
                    $"ReadPrintDriverVersion: no se encontró DriverVersion en registro para '{driverName}'");
                return driverName;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"ReadPrintDriverVersion: error leyendo driver de cola '{queueName}': {ex.Message}", ex);
                return null;
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
        // VERIFICACIÓN DE WINDOWS FEATURES
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Verifica si un Windows Optional Feature está habilitado.
        /// Usa DISM /online /get-featureinfo para consultar el estado.
        /// </summary>
        /// <param name="featureName">Nombre del feature (ej: Printing-Foundation-LPDPrintService)</param>
        /// <returns>"enabled" si está habilitado, "disabled" si no, "unknown" si no se pudo determinar</returns>
        private static string CheckWindowsFeature(string featureName)
        {
            try
            {
                AlwaysPrintLogger.WriteInfo($"CheckWindowsFeature: verificando estado de '{featureName}'");

                var startInfo = new ProcessStartInfo
                {
                    FileName = "C:\\Windows\\System32\\dism.exe",
                    Arguments = $"/online /get-featureinfo /featurename:{featureName}",
                    UseShellExecute = false,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    CreateNoWindow = true
                };

                using (var process = new Process { StartInfo = startInfo })
                {
                    var stdout = new System.Text.StringBuilder();
                    process.OutputDataReceived += (s, e) => { if (e.Data != null) stdout.AppendLine(e.Data); };

                    process.Start();
                    process.BeginOutputReadLine();
                    process.WaitForExit(30000);

                    string output = stdout.ToString();

                    // DISM output contiene "State : Enabled" (inglés) o "Estado : Habilitada" (español)
                    if (output.Contains("State : Enabled") || output.Contains("Estado : Habilitad"))
                    {
                        AlwaysPrintLogger.WriteInfo($"CheckWindowsFeature: '{featureName}' está habilitado");
                        return "enabled";
                    }
                    else if (output.Contains("State : Disabled") || output.Contains("Estado : Deshabilitad"))
                    {
                        AlwaysPrintLogger.WriteInfo($"CheckWindowsFeature: '{featureName}' está deshabilitado");
                        return "disabled";
                    }
                    else
                    {
                        AlwaysPrintLogger.WriteWarning($"CheckWindowsFeature: no se pudo determinar estado de '{featureName}'");
                        return "unknown";
                    }
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"CheckWindowsFeature: error verificando '{featureName}': {ex.Message}");
                return "unknown";
            }
        }

        /// <summary>
        /// Habilita un Windows Optional Feature si no está ya habilitado.
        /// Verifica primero con dism /get-featureinfo; si ya está habilitado, no hace nada.
        /// Si está deshabilitado, ejecuta dism /enable-feature.
        /// </summary>
        /// <param name="featureName">Nombre del feature (ej: Printing-Foundation-LPDPrintService)</param>
        /// <returns>true si el feature está habilitado (ya estaba o se habilitó), false si falló</returns>
        public static bool EnableWindowsFeature(string featureName)
        {
            try
            {
                // 1. Verificar estado actual
                string state = CheckWindowsFeature(featureName);
                
                if (state == "enabled")
                {
                    AlwaysPrintLogger.WriteInfo($"EnableWindowsFeature: '{featureName}' ya está habilitado. No se requiere acción.");
                    return true;
                }
                
                // 2. Habilitar si está deshabilitado o desconocido
                AlwaysPrintLogger.WriteInfo($"EnableWindowsFeature: habilitando '{featureName}'...");
                
                var startInfo = new ProcessStartInfo
                {
                    FileName = "C:\\Windows\\System32\\dism.exe",
                    Arguments = $"/online /enable-feature /featurename:{featureName} /all /norestart",
                    UseShellExecute = false,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    CreateNoWindow = true
                };
                
                using (var process = new Process { StartInfo = startInfo })
                {
                    var stdout = new System.Text.StringBuilder();
                    process.OutputDataReceived += (s, e) => { if (e.Data != null) stdout.AppendLine(e.Data); };
                    
                    process.Start();
                    process.BeginOutputReadLine();
                    bool exited = process.WaitForExit(120000); // 2 minutos timeout
                    
                    if (!exited)
                    {
                        AlwaysPrintLogger.WriteWarning($"EnableWindowsFeature: timeout habilitando '{featureName}'. Terminando proceso.");
                        process.Kill();
                        return false;
                    }
                    
                    // Exit codes: 0 = éxito, 3010 = éxito + reboot pendiente
                    int exitCode = process.ExitCode;
                    bool success = (exitCode == 0 || exitCode == 3010);
                    
                    if (success)
                    {
                        AlwaysPrintLogger.WriteInfo($"EnableWindowsFeature: '{featureName}' habilitado exitosamente (exit code {exitCode})");
                    }
                    else
                    {
                        AlwaysPrintLogger.WriteError($"EnableWindowsFeature: error habilitando '{featureName}' (exit code {exitCode})");
                    }
                    
                    return success;
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"EnableWindowsFeature: error habilitando '{featureName}': {ex.Message}");
                return false;
            }
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
                
                // Determinar si es un patrón wildcard (contiene * o ?)
                bool isWildcard = processName.Contains("*") || processName.Contains("?");
                
                Process[] processes;
                if (isWildcard)
                {
                    // Búsqueda por patrón: obtener todos los procesos y filtrar con wildcard
                    var pattern = "^" + System.Text.RegularExpressions.Regex.Escape(processName)
                        .Replace("\\*", ".*")
                        .Replace("\\?", ".") + "$";
                    var regex = new System.Text.RegularExpressions.Regex(pattern, System.Text.RegularExpressions.RegexOptions.IgnoreCase);
                    processes = Process.GetProcesses()
                        .Where(p => regex.IsMatch(p.ProcessName))
                        .ToArray();
                }
                else
                {
                    processes = Process.GetProcessesByName(processName);
                }
                
                foreach (var process in processes)
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
        // RunProcess — Ejecutar un archivo/proceso externo
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Ejecuta un proceso externo (bat, exe, cmd) con ventana oculta.
        /// Captura stdout y stderr, los registra en el log.
        /// Si runAsLoggedInUser=true, lanza el proceso como el usuario de consola activo.
        /// </summary>
        /// <param name="filePath">Ruta completa al archivo a ejecutar</param>
        /// <param name="arguments">Argumentos opcionales</param>
        /// <param name="timeoutSeconds">Timeout máximo de ejecución</param>
        /// <param name="windowStyle">Estilo de ventana: Hidden, Minimized, Normal</param>
        /// <param name="runAsLoggedInUser">Si true, ejecuta como el usuario de consola activo</param>
        /// <param name="successExitCodes">Códigos de salida considerados exitosos (default: solo 0). Ej: DISM retorna 3010 (reboot required) como éxito.</param>
        /// <returns>true si el proceso terminó con un exit code considerado exitoso</returns>
        public static bool RunProcess(string filePath, string arguments = "", int timeoutSeconds = 120, string windowStyle = "Hidden", bool runAsLoggedInUser = false, int[]? successExitCodes = null)
        {
            try
            {
                if (!File.Exists(filePath))
                {
                    AlwaysPrintLogger.WriteWarning($"RunProcess: archivo no encontrado: {filePath}");
                    return false;
                }

                if (runAsLoggedInUser)
                {
                    return RunProcessAsLoggedInUser(filePath, arguments, timeoutSeconds, windowStyle, successExitCodes);
                }

                AlwaysPrintLogger.WriteInfo($"RunProcess: ejecutando '{filePath}' con argumentos '{arguments}', ventana={windowStyle}, timeout={timeoutSeconds}s");

                var startInfo = new ProcessStartInfo
                {
                    FileName = filePath,
                    Arguments = arguments,
                    UseShellExecute = false,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    CreateNoWindow = windowStyle.Equals("Hidden", StringComparison.OrdinalIgnoreCase),
                    WindowStyle = windowStyle.Equals("Minimized", StringComparison.OrdinalIgnoreCase)
                        ? ProcessWindowStyle.Minimized
                        : ProcessWindowStyle.Hidden
                };

                using (var process = new Process { StartInfo = startInfo })
                {
                    var stdout = new System.Text.StringBuilder();
                    var stderr = new System.Text.StringBuilder();

                    process.OutputDataReceived += (s, e) => { if (e.Data != null) stdout.AppendLine(e.Data); };
                    process.ErrorDataReceived += (s, e) => { if (e.Data != null) stderr.AppendLine(e.Data); };

                    process.Start();
                    process.BeginOutputReadLine();
                    process.BeginErrorReadLine();

                    bool exited = process.WaitForExit(timeoutSeconds * 1000);

                    if (!exited)
                    {
                        AlwaysPrintLogger.WriteWarning($"RunProcess: timeout ({timeoutSeconds}s) alcanzado para '{filePath}'. Terminando proceso.");
                        process.Kill();
                        return false;
                    }

                    // Registrar output en log
                    if (stdout.Length > 0)
                    {
                        AlwaysPrintLogger.WriteInfo($"RunProcess stdout [{filePath}]: {stdout.ToString().TrimEnd()}");
                    }
                    if (stderr.Length > 0)
                    {
                        AlwaysPrintLogger.WriteWarning($"RunProcess stderr [{filePath}]: {stderr.ToString().TrimEnd()}");
                    }

                    AlwaysPrintLogger.WriteInfo($"RunProcess: '{filePath}' terminó con exit code {process.ExitCode}");
                    int[] validCodes = successExitCodes ?? new[] { 0 };
                    return validCodes.Contains(process.ExitCode);
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"RunProcess: error ejecutando '{filePath}': {ex.Message}", ex);
                return false;
            }
        }

        /// <summary>
        /// Ejecuta un proceso como el usuario de consola activo (desde un servicio LocalSystem).
        /// Usa WTSQueryUserToken + CreateProcessAsUser para impersonar al usuario logueado.
        /// Redirige stdout/stderr a un archivo temporal para capturar el output.
        /// </summary>
        private static bool RunProcessAsLoggedInUser(string filePath, string arguments, int timeoutSeconds, string windowStyle, int[]? successExitCodes = null)
        {
            IntPtr userToken = IntPtr.Zero;
            IntPtr duplicateToken = IntPtr.Zero;
            string outputFile = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
                "AlwaysPrint",
                $"runprocess_{Guid.NewGuid():N}.log");

            try
            {
                uint sessionId = WTSGetActiveConsoleSessionId();
                if (sessionId == 0xFFFFFFFF)
                {
                    AlwaysPrintLogger.WriteWarning("RunProcess: no hay sesión de consola activa. No se puede ejecutar como usuario.");
                    return false;
                }

                if (!WTSQueryUserToken(sessionId, out userToken))
                {
                    int error = Marshal.GetLastWin32Error();
                    AlwaysPrintLogger.WriteWarning($"RunProcess: WTSQueryUserToken falló (error {error}). Sesión={sessionId}");
                    return false;
                }

                // Duplicar token para CreateProcessAsUser
                var sa = new SECURITY_ATTRIBUTES();
                sa.nLength = Marshal.SizeOf(sa);
                if (!DuplicateTokenEx(userToken, 0x10000000, ref sa, 2, 1, out duplicateToken))
                {
                    AlwaysPrintLogger.WriteWarning($"RunProcess: DuplicateTokenEx falló (error {Marshal.GetLastWin32Error()})");
                    return false;
                }

                // Preparar comando: redirigir stdout y stderr a archivo temporal
                string commandLine;
                if (filePath.EndsWith(".bat", StringComparison.OrdinalIgnoreCase) ||
                    filePath.EndsWith(".cmd", StringComparison.OrdinalIgnoreCase))
                {
                    commandLine = $"cmd.exe /c \"\"{filePath}\" {arguments} > \"{outputFile}\" 2>&1\"".Trim();
                }
                else
                {
                    commandLine = $"cmd.exe /c \"\"{filePath}\" {arguments} > \"{outputFile}\" 2>&1\"".Trim();
                }

                AlwaysPrintLogger.WriteInfo($"RunProcess (como usuario, sesión {sessionId}): ejecutando '{filePath}', ventana={windowStyle}, timeout={timeoutSeconds}s");

                // Crear bloque de variables de entorno del usuario
                IntPtr envBlock = IntPtr.Zero;
                if (!CreateEnvironmentBlock(out envBlock, duplicateToken, false))
                {
                    AlwaysPrintLogger.WriteWarning($"RunProcess: CreateEnvironmentBlock falló (error {Marshal.GetLastWin32Error()}). Usando entorno heredado.");
                }

                var si = new STARTUPINFO();
                si.cb = Marshal.SizeOf(si);
                si.lpDesktop = "winsta0\\default";
                // Ventana oculta
                si.dwFlags = 0x00000001; // STARTF_USESHOWWINDOW
                si.wShowWindow = windowStyle.Equals("Minimized", StringComparison.OrdinalIgnoreCase) ? (short)7 : (short)0; // SW_SHOWMINNOACTIVE o SW_HIDE

                var pi = new PROCESS_INFORMATION();

                // CREATE_NEW_CONSOLE | CREATE_UNICODE_ENVIRONMENT | CREATE_SUSPENDED
                // CREATE_SUSPENDED permite asignar al Job Object antes de que el proceso inicie
                uint creationFlags = 0x00000010 | 0x00000400 | 0x00000004;

                bool created = CreateProcessAsUser(
                    duplicateToken,
                    null,
                    commandLine,
                    ref sa,
                    ref sa,
                    false,
                    creationFlags,
                    envBlock != IntPtr.Zero ? envBlock : IntPtr.Zero,
                    null,
                    ref si,
                    out pi);

                // Liberar bloque de entorno
                if (envBlock != IntPtr.Zero) DestroyEnvironmentBlock(envBlock);

                if (!created)
                {
                    int error = Marshal.GetLastWin32Error();
                    AlwaysPrintLogger.WriteWarning($"RunProcess: CreateProcessAsUser falló (error {error})");
                    return false;
                }

                // Crear Job Object con KILL_ON_JOB_CLOSE para matar todo el árbol de procesos al cerrar el handle
                IntPtr hJob = CreateJobObject(IntPtr.Zero, null);
                if (hJob != IntPtr.Zero)
                {
                    var jobInfo = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
                    jobInfo.BasicLimitInformation.LimitFlags = 0x00002000; // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                    int infoSize = Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION));
                    IntPtr infoPtr = Marshal.AllocHGlobal(infoSize);
                    try
                    {
                        Marshal.StructureToPtr(jobInfo, infoPtr, false);
                        SetInformationJobObject(hJob, 9 /* JobObjectExtendedLimitInformation */, infoPtr, (uint)infoSize);
                    }
                    finally
                    {
                        Marshal.FreeHGlobal(infoPtr);
                    }
                    AssignProcessToJobObject(hJob, pi.hProcess);
                }

                // Reanudar el proceso (fue creado suspendido)
                ResumeThread(pi.hThread);

                // Esperar a que termine
                uint waitResult = WaitForSingleObject(pi.hProcess, (uint)(timeoutSeconds * 1000));
                if (waitResult != 0) // WAIT_OBJECT_0
                {
                    AlwaysPrintLogger.WriteWarning($"RunProcess: timeout ({timeoutSeconds}s) alcanzado para '{filePath}' (como usuario). Terminando árbol de procesos.");
                    // Cerrar el Job Object mata todos los procesos del grupo (cmd.exe + rundll32.exe + hijos)
                    if (hJob != IntPtr.Zero)
                    {
                        TerminateJobObject(hJob, 1);
                        CloseHandle(hJob);
                        hJob = IntPtr.Zero;
                    }
                    else
                    {
                        TerminateProcess(pi.hProcess, 1);
                    }
                    CloseHandle(pi.hProcess);
                    CloseHandle(pi.hThread);
                    return false;
                }

                // Limpiar Job Object después de terminación normal
                if (hJob != IntPtr.Zero) CloseHandle(hJob);

                uint exitCode = 0;
                GetExitCodeProcess(pi.hProcess, out exitCode);
                CloseHandle(pi.hProcess);
                CloseHandle(pi.hThread);

                // Leer output del archivo temporal y registrar en log
                if (File.Exists(outputFile))
                {
                    try
                    {
                        string output = File.ReadAllText(outputFile).TrimEnd();
                        if (!string.IsNullOrEmpty(output))
                        {
                            AlwaysPrintLogger.WriteInfo($"RunProcess stdout (como usuario) [{filePath}]: {output}");
                        }
                    }
                    catch (Exception ex)
                    {
                        AlwaysPrintLogger.WriteWarning($"RunProcess: no se pudo leer output temporal: {ex.Message}");
                    }
                    finally
                    {
                        try { File.Delete(outputFile); } catch { }
                    }
                }

                AlwaysPrintLogger.WriteInfo($"RunProcess (como usuario): '{filePath}' terminó con exit code {exitCode}");
                int[] validCodes = successExitCodes ?? new[] { 0 };
                return validCodes.Contains((int)exitCode);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"RunProcess (como usuario): error ejecutando '{filePath}': {ex.Message}", ex);
                return false;
            }
            finally
            {
                if (userToken != IntPtr.Zero) CloseHandle(userToken);
                if (duplicateToken != IntPtr.Zero) CloseHandle(duplicateToken);
                // Limpiar archivo temporal si quedó
                try { if (File.Exists(outputFile)) File.Delete(outputFile); } catch { }
            }
        }

        // ═══════════════════════════════════════════════════════════════════════
        // P/INVOKE para CreateProcessAsUser
        // ═══════════════════════════════════════════════════════════════════════

        [DllImport("wtsapi32.dll", SetLastError = true)]
        private static extern bool WTSQueryUserToken(uint sessionId, out IntPtr phToken);

        [DllImport("advapi32.dll", SetLastError = true)]
        private static extern bool DuplicateTokenEx(
            IntPtr hExistingToken, uint dwDesiredAccess,
            ref SECURITY_ATTRIBUTES lpTokenAttributes,
            int impersonationLevel, int tokenType,
            out IntPtr phNewToken);

        [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        private static extern bool CreateProcessAsUser(
            IntPtr hToken, string? lpApplicationName, string lpCommandLine,
            ref SECURITY_ATTRIBUTES lpProcessAttributes,
            ref SECURITY_ATTRIBUTES lpThreadAttributes,
            bool bInheritHandles, uint dwCreationFlags,
            IntPtr lpEnvironment, string? lpCurrentDirectory,
            ref STARTUPINFO lpStartupInfo,
            out PROCESS_INFORMATION lpProcessInformation);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern uint WaitForSingleObject(IntPtr hHandle, uint dwMilliseconds);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool GetExitCodeProcess(IntPtr hProcess, out uint lpExitCode);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool TerminateProcess(IntPtr hProcess, uint uExitCode);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool CloseHandle(IntPtr hObject);

        [DllImport("userenv.dll", SetLastError = true)]
        private static extern bool CreateEnvironmentBlock(out IntPtr lpEnvironment, IntPtr hToken, bool bInherit);

        [DllImport("userenv.dll", SetLastError = true)]
        private static extern bool DestroyEnvironmentBlock(IntPtr lpEnvironment);

        [StructLayout(LayoutKind.Sequential)]
        private struct SECURITY_ATTRIBUTES
        {
            public int nLength;
            public IntPtr lpSecurityDescriptor;
            public bool bInheritHandle;
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct STARTUPINFO
        {
            public int cb;
            public string lpReserved;
            public string lpDesktop;
            public string lpTitle;
            public int dwX, dwY, dwXSize, dwYSize;
            public int dwXCountChars, dwYCountChars;
            public int dwFillAttribute;
            public int dwFlags;
            public short wShowWindow;
            public short cbReserved2;
            public IntPtr lpReserved2;
            public IntPtr hStdInput, hStdOutput, hStdError;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct PROCESS_INFORMATION
        {
            public IntPtr hProcess;
            public IntPtr hThread;
            public int dwProcessId;
            public int dwThreadId;
        }
        
        // ═══════════════════════════════════════════════════════════════════════
        // P/INVOKE para WTS APIs
        // ═══════════════════════════════════════════════════════════════════════
        
        [DllImport("kernel32.dll")]
        private static extern uint WTSGetActiveConsoleSessionId();
        
        // ═══════════════════════════════════════════════════════════════════════
        // P/INVOKE para Job Objects (matar árbol de procesos en timeout)
        // ═══════════════════════════════════════════════════════════════════════

        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        private static extern IntPtr CreateJobObject(IntPtr lpJobAttributes, string? lpName);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool AssignProcessToJobObject(IntPtr hJob, IntPtr hProcess);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool SetInformationJobObject(IntPtr hJob, int jobObjectInfoClass, IntPtr lpJobObjectInfo, uint cbJobObjectInfoLength);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool TerminateJobObject(IntPtr hJob, uint uExitCode);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern uint ResumeThread(IntPtr hThread);

        [StructLayout(LayoutKind.Sequential)]
        private struct JOBOBJECT_BASIC_LIMIT_INFORMATION
        {
            public long PerProcessUserTimeLimit;
            public long PerJobUserTimeLimit;
            public uint LimitFlags;
            public UIntPtr MinimumWorkingSetSize;
            public UIntPtr MaximumWorkingSetSize;
            public uint ActiveProcessLimit;
            public UIntPtr Affinity;
            public uint PriorityClass;
            public uint SchedulingClass;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct IO_COUNTERS
        {
            public ulong ReadOperationCount;
            public ulong WriteOperationCount;
            public ulong OtherOperationCount;
            public ulong ReadTransferCount;
            public ulong WriteTransferCount;
            public ulong OtherTransferCount;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        {
            public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
            public IO_COUNTERS IoInfo;
            public UIntPtr ProcessMemoryLimit;
            public UIntPtr JobMemoryLimit;
            public UIntPtr PeakProcessMemoryUsed;
            public UIntPtr PeakJobMemoryUsed;
        }
        
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
