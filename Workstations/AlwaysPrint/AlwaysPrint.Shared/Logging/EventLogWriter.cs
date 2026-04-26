using System;
using System.Diagnostics;

namespace AlwaysPrint.Shared.Logging
{
    /// <summary>
    /// Thin wrapper around Windows Event Log.
    /// Source must be registered before first use (done by the service installer or EnsureSourceExists).
    /// </summary>
    public static class EventLogWriter
    {
        public const string Source = "AlwaysPrint";
        public const string LogName = "Application";

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

        public static void EnsureSourceExists()
        {
            try
            {
                if (!EventLog.SourceExists(Source))
                    EventLog.CreateEventSource(Source, LogName);
            }
            catch { /* May fail if not admin; service installer handles registration. */ }
        }

        public static void WriteInfo(string message, int eventId = EvtGenericWarning)
        {
            Write(message, EventLogEntryType.Information, eventId);
        }

        public static void WriteWarning(string message, int eventId = EvtGenericWarning)
        {
            Write(message, EventLogEntryType.Warning, eventId);
        }

        public static void WriteError(string message, int eventId = EvtGenericError)
        {
            Write(message, EventLogEntryType.Error, eventId);
        }

        public static void WriteError(string message, Exception ex, int eventId = EvtGenericError)
        {
            Write($"{message}\r\n{ex}", EventLogEntryType.Error, eventId);
        }

        private static void Write(string message, EventLogEntryType type, int eventId)
        {
            try
            {
                // Truncate to Event Log limit (32,766 bytes).
                if (message != null && message.Length > 30000)
                    message = message.Substring(0, 30000) + "... [truncated]";

                EventLog.WriteEntry(Source, message ?? "(null)", type, eventId);
            }
            catch (Exception ex)
            {
                // Last resort: write to Debug output – avoids infinite recursion.
                Debug.WriteLine($"[AlwaysPrint EventLogWriter] Failed to write event: {ex.Message}");
            }
        }
    }
}
