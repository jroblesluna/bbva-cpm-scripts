using System;
using System.IO;
using System.Runtime.InteropServices;
using AlwaysPrint.Shared.Logging;
using static AlwaysPrintService.UserSession.NativeMethods;

namespace AlwaysPrintService.UserSession
{
    /// <summary>
    /// Launches a process inside the active interactive user session from Session 0.
    /// Requires SE_TCB_NAME privilege, which LocalSystem possesses by default.
    ///
    /// Why not Process.Start? Processes started from Session 0 (where services run)
    /// are invisible to the interactive desktop. We must acquire the user's token via
    /// WTS APIs and call CreateProcessAsUser to place the process in their session.
    /// </summary>
    public static class InteractiveProcessLauncher
    {
        /// <summary>
        /// Launches <paramref name="exePath"/> in the active console session.
        /// Returns true if the OS accepted the CreateProcessAsUser call.
        /// </summary>
        public static bool Launch(string exePath, string? arguments = null)
        {
            string logFile = @"C:\ProgramData\AlwaysPrint\service.log";
            System.IO.Directory.CreateDirectory(@"C:\ProgramData\AlwaysPrint");
            System.IO.File.AppendAllText(logFile, $"[{System.DateTime.Now:yyyy-MM-dd HH:mm:ss}] InteractiveProcessLauncher.Launch: {exePath}\n");
            
            if (!File.Exists(exePath))
            {
                System.IO.File.AppendAllText(logFile, $"[{System.DateTime.Now:yyyy-MM-dd HH:mm:ss}] Archivo no encontrado: {exePath}\n");
                EventLogWriter.WriteError($"InteractiveProcessLauncher: executable not found: {exePath}",
                    EventLogWriter.EvtTrayError);
                return false;
            }

            uint sessionId = WTSGetActiveConsoleSessionId();
            System.IO.File.AppendAllText(logFile, $"[{System.DateTime.Now:yyyy-MM-dd HH:mm:ss}] sessionId={sessionId}, NO_ACTIVE_SESSION={NO_ACTIVE_SESSION}\n");
            
            if (sessionId == NO_ACTIVE_SESSION)
            {
                System.IO.File.AppendAllText(logFile, $"[{System.DateTime.Now:yyyy-MM-dd HH:mm:ss}] No hay sesión activa\n");
                EventLogWriter.WriteWarning("InteractiveProcessLauncher: no active console session.",
                    EventLogWriter.EvtWaitingUser);
                return false;
            }

            IntPtr userToken   = IntPtr.Zero;
            IntPtr primaryToken = IntPtr.Zero;
            IntPtr environment  = IntPtr.Zero;

            try
            {
                // Step 1: get impersonation token for the logged-on user.
                if (!WTSQueryUserToken(sessionId, out userToken))
                {
                    System.IO.File.AppendAllText(logFile, $"[{System.DateTime.Now:yyyy-MM-dd HH:mm:ss}] WTSQueryUserToken falló: {Marshal.GetLastWin32Error()}\n");
                    throw new InvalidOperationException(
                        $"WTSQueryUserToken failed. Win32 error: {Marshal.GetLastWin32Error()}");
                }

                // Step 2: promote to a primary token (CreateProcessAsUser requires this).
                var sa = new SECURITY_ATTRIBUTES { nLength = Marshal.SizeOf<SECURITY_ATTRIBUTES>() };
                if (!DuplicateTokenEx(userToken, TOKEN_ALL_ACCESS, ref sa,
                        SECURITY_IMPERSONATION_LEVEL.SecurityImpersonation,
                        TOKEN_TYPE.TokenPrimary, out primaryToken))
                {
                    System.IO.File.AppendAllText(logFile, $"[{System.DateTime.Now:yyyy-MM-dd HH:mm:ss}] DuplicateTokenEx falló: {Marshal.GetLastWin32Error()}\n");
                    throw new InvalidOperationException(
                        $"DuplicateTokenEx failed. Win32 error: {Marshal.GetLastWin32Error()}");
                }

                // Step 3: build an environment block from the user profile.
                // bInherit=false means we get the user's own env, not the service's.
                CreateEnvironmentBlock(out environment, primaryToken, false);

                var si = new STARTUPINFO
                {
                    cb        = Marshal.SizeOf<STARTUPINFO>(),
                    lpDesktop = "winsta0\\default"   // interactive desktop
                };

                uint flags = CREATE_UNICODE_ENVIRONMENT | NORMAL_PRIORITY_CLASS;

                // Build safe command line (quote the path).
                string commandLine = string.IsNullOrWhiteSpace(arguments)
                    ? $"\"{exePath}\""
                    : $"\"{exePath}\" {arguments}";

                System.IO.File.AppendAllText(logFile, $"[{System.DateTime.Now:yyyy-MM-dd HH:mm:ss}] Llamando CreateProcessAsUser: {commandLine}\n");
                
                bool ok = CreateProcessAsUser(
                    primaryToken,
                    null,
                    commandLine,
                    ref sa, ref sa,
                    false,
                    flags,
                    environment,
                    Path.GetDirectoryName(exePath),
                    ref si,
                    out var pi);

                if (ok)
                {
                    // Close the handles we own; we don't need to track the child process here.
                    if (pi.hProcess != IntPtr.Zero) CloseHandle(pi.hProcess);
                    if (pi.hThread  != IntPtr.Zero) CloseHandle(pi.hThread);
                    System.IO.File.AppendAllText(logFile, $"[{System.DateTime.Now:yyyy-MM-dd HH:mm:ss}] Tray lanzado exitosamente en sesión {sessionId}\n");
                    EventLogWriter.WriteInfo(
                        $"InteractiveProcessLauncher: launched '{exePath}' in session {sessionId}.",
                        EventLogWriter.EvtTrayStarting);
                }
                else
                {
                    System.IO.File.AppendAllText(logFile, $"[{System.DateTime.Now:yyyy-MM-dd HH:mm:ss}] CreateProcessAsUser falló: {Marshal.GetLastWin32Error()}\n");
                    EventLogWriter.WriteError(
                        $"InteractiveProcessLauncher: CreateProcessAsUser failed. Win32 error: {Marshal.GetLastWin32Error()}",
                        EventLogWriter.EvtTrayError);
                }

                return ok;
            }
            catch (Exception ex)
            {
                System.IO.File.AppendAllText(logFile, $"[{System.DateTime.Now:yyyy-MM-dd HH:mm:ss}] Excepción: {ex}\n");
                EventLogWriter.WriteError("InteractiveProcessLauncher failed.", ex, EventLogWriter.EvtTrayError);
                return false;
            }
            finally
            {
                if (environment  != IntPtr.Zero) DestroyEnvironmentBlock(environment);
                if (primaryToken != IntPtr.Zero) CloseHandle(primaryToken);
                if (userToken    != IntPtr.Zero) CloseHandle(userToken);
            }
        }
    }
}
