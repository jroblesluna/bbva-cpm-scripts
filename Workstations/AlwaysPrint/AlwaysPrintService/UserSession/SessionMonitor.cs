using System;
using System.ServiceProcess;
using AlwaysPrint.Shared.Logging;
using static AlwaysPrintService.UserSession.NativeMethods;

namespace AlwaysPrintService.UserSession
{
    /// <summary>
    /// Tracks the interactive console session state.
    /// The Windows Service overrides OnSessionChange for event-driven detection;
    /// this class provides the helper that is also used for the initial poll loop.
    /// </summary>
    public static class SessionMonitor
    {
        /// <summary>Returns true when a real user is logged into the physical console.</summary>
        public static bool IsUserLoggedIn()
        {
            uint sessionId = WTSGetActiveConsoleSessionId();
            string logFile = @"C:\ProgramData\AlwaysPrint\service.log";
            System.IO.Directory.CreateDirectory(@"C:\ProgramData\AlwaysPrint");
            System.IO.File.AppendAllText(logFile, $"[{System.DateTime.Now:yyyy-MM-dd HH:mm:ss}] IsUserLoggedIn: sessionId={sessionId}, NO_ACTIVE_SESSION={NO_ACTIVE_SESSION}\n");
            
            if (sessionId == NO_ACTIVE_SESSION) return false;

            // WTSQueryUserToken succeeds only for sessions that have a user.
            // We open and immediately close the token – we just need the boolean.
            if (!WTSQueryUserToken(sessionId, out var token))
            {
                System.IO.File.AppendAllText(logFile, $"[{System.DateTime.Now:yyyy-MM-dd HH:mm:ss}] WTSQueryUserToken falló para sessionId={sessionId}\n");
                return false;
            }
            CloseHandle(token);
            System.IO.File.AppendAllText(logFile, $"[{System.DateTime.Now:yyyy-MM-dd HH:mm:ss}] Usuario detectado en sessionId={sessionId}\n");
            return true;
        }

        /// <summary>Maps a SCM SessionChangeReason to a human-readable string for logging.</summary>
        public static string DescribeReason(SessionChangeReason reason) => reason switch
        {
            SessionChangeReason.SessionLogon       => "User logon",
            SessionChangeReason.SessionLogoff      => "User logoff",
            SessionChangeReason.RemoteConnect      => "Remote connect",
            SessionChangeReason.RemoteDisconnect   => "Remote disconnect",
            SessionChangeReason.ConsoleConnect     => "Console connect",
            SessionChangeReason.ConsoleDisconnect  => "Console disconnect",
            SessionChangeReason.SessionLock         => "Session locked",
            SessionChangeReason.SessionUnlock       => "Session unlocked",
            _ => reason.ToString()
        };
    }
}
