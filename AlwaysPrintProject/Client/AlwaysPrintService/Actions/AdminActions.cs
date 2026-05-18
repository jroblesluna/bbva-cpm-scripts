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
        /// Obtiene la lista de usuarios con sesión activa.
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
                
                // Usar WMI para obtener sesiones activas
                using (var searcher = new ManagementObjectSearcher("SELECT * FROM Win32_LogonSession WHERE LogonType = 2 OR LogonType = 10"))
                {
                    foreach (ManagementObject session in searcher.Get())
                    {
                        try
                        {
                            string logonId = session["LogonId"]?.ToString() ?? "";
                            
                            if (string.IsNullOrEmpty(logonId))
                                continue;
                            
                            // Obtener usuario asociado a la sesión
                            using (var userSearcher = new ManagementObjectSearcher($"SELECT * FROM Win32_LoggedOnUser WHERE Dependent LIKE '%LogonId=\"{logonId}\"%'"))
                            {
                                foreach (ManagementObject user in userSearcher.Get())
                                {
                                    try
                                    {
                                        string antecedent = user["Antecedent"]?.ToString() ?? "";
                                        
                                        // Extraer nombre de usuario del path WMI
                                        // Formato: \\MACHINE\root\cimv2:Win32_Account.Domain="DOMAIN",Name="USERNAME"
                                        int nameStart = antecedent.IndexOf("Name=\"") + 6;
                                        int nameEnd = antecedent.IndexOf("\"", nameStart);
                                        
                                        if (nameStart > 5 && nameEnd > nameStart)
                                        {
                                            string username = antecedent.Substring(nameStart, nameEnd - nameStart);
                                            
                                            if (!string.IsNullOrEmpty(username) && 
                                                !users.Contains(username, StringComparer.OrdinalIgnoreCase))
                                            {
                                                // Excluir usuario de consola activa si se solicita
                                                if (excludeActiveConsoleUser && 
                                                    !string.IsNullOrEmpty(activeConsoleUser) &&
                                                    username.Equals(activeConsoleUser, StringComparison.OrdinalIgnoreCase))
                                                {
                                                    AlwaysPrintLogger.WriteInfo($"GetLoggedInUsers: excluyendo usuario de consola activa: {username}");
                                                    continue;
                                                }
                                                
                                                users.Add(username);
                                            }
                                        }
                                    }
                                    catch (Exception ex)
                                    {
                                        AlwaysPrintLogger.WriteWarning($"GetLoggedInUsers: error procesando usuario: {ex.Message}");
                                    }
                                }
                            }
                        }
                        catch (Exception ex)
                        {
                            AlwaysPrintLogger.WriteWarning($"GetLoggedInUsers: error procesando sesión: {ex.Message}");
                        }
                    }
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
    }
}
