using System;
using System.Diagnostics;
using System.IO;

namespace AlwaysPrint.Shared.Logging
{
    /// <summary>
    /// Thin wrapper around file-based logging.
    /// Logs are written to C:\ProgramData\AlwaysPrint\logs\ with date-based rotation.
    /// Format: [timestamp] [Origen] Logging message
    /// </summary>
    public static class EventLogWriter
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

        private static void Write(string message, EventLogEntryType type, int eventId, string source)
        {
            try
            {
                // Truncate to reasonable size
                if (message != null && message.Length > 30000)
                    message = message.Substring(0, 30000) + "... [truncated]";

                string logFile = GetLogFileName();
                string logMessage = $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] [{source}] Event {eventId}: {message}";

                lock (LogLock)
                {
                    Directory.CreateDirectory(LogDirectory);
                    File.AppendAllText(logFile, logMessage + "\n");
                }
            }
            catch
            {
                // Ignore all logging errors - this is a last resort
            }
        }

        private static string GetLogFileName()
        {
            string datePart = DateTime.Now.ToString("yyyyMMdd");
            return Path.Combine(LogDirectory, $"AlwaysPrint_{datePart}.log");
        }
    }
}
