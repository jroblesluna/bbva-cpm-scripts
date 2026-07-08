using System;
using System.Diagnostics;
using System.IO;
using System.Security.AccessControl;
using System.Security.Principal;

namespace AlwaysPrint.Shared.Logging
{
    /// <summary>
    /// Logger de archivo con rotación diaria.
    /// Escribe en C:\ProgramData\AlwaysPrint\logs\AlwaysPrint_yyyyMMdd.log
    /// Formato: [timestamp] [SVC|APP] mensaje
    /// </summary>
    public static class AlwaysPrintLogger
    {
        public const string SourceService = "SVC";
        public const string SourceTray = "APP";

        // Event IDs – stable identifiers for monitoring/alerting tools.
        public const int EvtServiceStarted       = 1000;
        public const int EvtServiceStopped       = 1001;
        public const int EvtDuplicateInstance    = 1002;
        public const int EvtTrayKilled           = 1003;
        public const int EvtQueueCleared         = 1004;
        public const int EvtPipeServerStarted    = 1005;
        public const int EvtWaitingUser          = 1006;
        public const int EvtUserDetected         = 1007;
        public const int EvtTrayStarting         = 1008;
        public const int EvtTrayStarted          = 1009;
        public const int EvtTrayError            = 1010;
        public const int EvtTaskDispatched       = 1020;
        public const int EvtTaskCompleted        = 1021;
        public const int EvtTaskFailed           = 1022;
        public const int EvtConfigSaved          = 1030;
        public const int EvtGenericWarning       = 1090;
        public const int EvtGenericError         = 1091;

        // Connectivity Check
        public const int EvtConnectivitySummary  = 1090;
        public const int EvtConnectivityFail     = 1091;

        private static readonly string LogDirectory = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
            "AlwaysPrint", "logs");

        private static readonly object LogLock = new object();

        public static void EnsureSourceExists()
        {
            // No longer needed - we don't use EventLog anymore
        }

        public static void WriteInfo(string message, int eventId = EvtGenericWarning)
        {
            Write(message, EventLogEntryType.Information, eventId, SourceService);
        }

        public static void WriteWarning(string message, int eventId = EvtGenericWarning)
        {
            Write(message, EventLogEntryType.Warning, eventId, SourceService);
        }

        public static void WriteError(string message, int eventId = EvtGenericError)
        {
            Write(message, EventLogEntryType.Error, eventId, SourceService);
        }

        public static void WriteError(string message, Exception ex, int eventId = EvtGenericError)
        {
            Write($"{message}\r\n{ex}", EventLogEntryType.Error, eventId, SourceService);
        }

        public static void WriteTrayInfo(string message, int eventId = EvtGenericWarning)
        {
            Write(message, EventLogEntryType.Information, eventId, SourceTray);
        }

        public static void WriteTrayWarning(string message, int eventId = EvtGenericWarning)
        {
            Write(message, EventLogEntryType.Warning, eventId, SourceTray);
        }

        public static void WriteTrayError(string message, int eventId = EvtGenericError)
        {
            Write(message, EventLogEntryType.Error, eventId, SourceTray);
        }

        public static void WriteTrayError(string message, Exception ex, int eventId = EvtGenericError)
        {
            Write($"{message}\r\n{ex}", EventLogEntryType.Error, eventId, SourceTray);
        }

        /// <summary>
        /// Escribe el bloque "Root Log" al inicio de un archivo de log nuevo.
        /// Contiene información diagnóstica general de la workstation para contexto.
        /// Se invoca al crear un nuevo archivo de log (rotación diaria) o al iniciar el servicio.
        /// </summary>
        /// <param name="organizationName">Nombre de la organización (ej: "BBVA").</param>
        /// <param name="organizationId">UUID de la organización en Cloud.</param>
        /// <param name="environment">Nombre del entorno (DEV o PROD).</param>
        /// <param name="serverUrl">URL del servidor Cloud.</param>
        /// <param name="version">Versión del EXE del servicio.</param>
        /// <param name="hostname">Hostname de la workstation.</param>
        /// <param name="workstationId">UUID de la workstation registrada en Cloud.</param>
        /// <param name="localIp">IP local de la workstation.</param>
        /// <param name="actionConfigInfo">Nombre y versión de la configuración de acciones.</param>
        /// <param name="osInfo">Información del sistema operativo.</param>
        /// <param name="timezone">Zona horaria usada para timestamps.</param>
        public static void WriteRootLog(
            string? organizationName,
            string? organizationId,
            string environment,
            string? serverUrl,
            string version,
            string hostname,
            string? workstationId,
            string localIp,
            string? actionConfigInfo,
            string? osInfo,
            string? timezone)
        {
            try
            {
                string ts = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss");
                string src = SourceService;
                int evt = EvtServiceStarted;

                var lines = new System.Text.StringBuilder();
                lines.AppendLine($"[{ts}] [{src}] Event {evt}: ═══ ROOT LOG ═══");
                lines.AppendLine($"[{ts}] [{src}] Event {evt}: Organización: {organizationName ?? "N/A"} ({organizationId ?? "no registrada"})");
                lines.AppendLine($"[{ts}] [{src}] Event {evt}: Entorno: {environment}");
                lines.AppendLine($"[{ts}] [{src}] Event {evt}: Servidor: {serverUrl ?? "N/A"}");
                lines.AppendLine($"[{ts}] [{src}] Event {evt}: Versión: {version}");
                lines.AppendLine($"[{ts}] [{src}] Event {evt}: Workstation: {hostname} ({workstationId ?? "no registrada"})");
                lines.AppendLine($"[{ts}] [{src}] Event {evt}: IP: {localIp}");
                lines.AppendLine($"[{ts}] [{src}] Event {evt}: Configuración: {actionConfigInfo ?? "sin configuración"}");
                lines.AppendLine($"[{ts}] [{src}] Event {evt}: Zona horaria: {timezone ?? "desconocida"}");
                lines.AppendLine($"[{ts}] [{src}] Event {evt}: OS: {osInfo ?? "desconocido"}");
                lines.AppendLine($"[{ts}] [{src}] Event {evt}: ═══════════════");

                string logFile = GetLogFileName();

                lock (LogLock)
                {
                    Directory.CreateDirectory(LogDirectory);
                    EnsureDirectoryPermissions();

                    if (!File.Exists(logFile))
                    {
                        File.WriteAllText(logFile, lines.ToString());
                        EnsureFilePermissions(logFile);
                    }
                    else
                    {
                        // Si el archivo ya existe, agregar el root log en posición cronológica (append)
                        File.AppendAllText(logFile, lines.ToString());
                    }
                }
            }
            catch
            {
                // Ignorar errores de logging - último recurso
            }
        }

        private static void Write(string message, EventLogEntryType type, int eventId, string source)
        {
            try
            {
                // Truncar a tamaño razonable
                if (message != null && message.Length > 30000)
                    message = message.Substring(0, 30000) + "... [truncated]";

                string logFile = GetLogFileName();
                string logMessage = $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] [{source}] Event {eventId}: {message}";

                lock (LogLock)
                {
                    Directory.CreateDirectory(LogDirectory);
                    EnsureDirectoryPermissions();

                    // Si el archivo no existe, crearlo con permisos para todos los usuarios
                    if (!File.Exists(logFile))
                    {
                        File.WriteAllText(logFile, logMessage + "\n");
                        EnsureFilePermissions(logFile);
                    }
                    else
                    {
                        File.AppendAllText(logFile, logMessage + "\n");
                    }
                }
            }
            catch
            {
                // Ignorar errores de logging - último recurso
            }
        }

        /// <summary>
        /// Asegura que el directorio de logs tenga permisos de escritura para BUILTIN\Users.
        /// Esto permite que tanto el servicio (SYSTEM) como el Tray (usuario) escriban.
        /// </summary>
        private static void EnsureDirectoryPermissions()
        {
            try
            {
                var dirInfo = new DirectoryInfo(LogDirectory);
                var security = dirInfo.GetAccessControl();
                var usersIdentity = new SecurityIdentifier(WellKnownSidType.BuiltinUsersSid, null);

                security.AddAccessRule(new FileSystemAccessRule(
                    usersIdentity,
                    FileSystemRights.Modify | FileSystemRights.Synchronize,
                    InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit,
                    PropagationFlags.None,
                    AccessControlType.Allow));

                dirInfo.SetAccessControl(security);
            }
            catch
            {
                // Si no se pueden cambiar permisos (ej: el Tray no es admin), ignorar
            }
        }

        /// <summary>
        /// Asegura que el archivo de log tenga permisos de escritura para BUILTIN\Users.
        /// </summary>
        private static void EnsureFilePermissions(string filePath)
        {
            try
            {
                var fileInfo = new FileInfo(filePath);
                var security = fileInfo.GetAccessControl();
                var usersIdentity = new SecurityIdentifier(WellKnownSidType.BuiltinUsersSid, null);

                security.AddAccessRule(new FileSystemAccessRule(
                    usersIdentity,
                    FileSystemRights.Modify | FileSystemRights.Synchronize,
                    AccessControlType.Allow));

                fileInfo.SetAccessControl(security);
            }
            catch
            {
                // Si no se pueden cambiar permisos, ignorar
            }
        }

        private static string GetLogFileName()
        {
            string datePart = DateTime.Now.ToString("yyyyMMdd");
            return Path.Combine(LogDirectory, $"AlwaysPrint_{datePart}.log");
        }
    }
}
