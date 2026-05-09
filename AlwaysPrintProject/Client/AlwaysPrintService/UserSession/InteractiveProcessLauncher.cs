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
            AlwaysPrintLogger.WriteInfo($"InteractiveProcessLauncher.Launch: {exePath}");

            if (!File.Exists(exePath))
            {
                AlwaysPrintLogger.WriteError($"Archivo no encontrado: {exePath}", AlwaysPrintLogger.EvtTrayError);
                return false;
            }

            uint sessionId = WTSGetActiveConsoleSessionId();
            AlwaysPrintLogger.WriteInfo($"sessionId={sessionId}, NO_ACTIVE_SESSION={NO_ACTIVE_SESSION}");

            if (sessionId == NO_ACTIVE_SESSION)
            {
                AlwaysPrintLogger.WriteWarning("InteractiveProcessLauncher: no hay sesión activa.", AlwaysPrintLogger.EvtWaitingUser);
                return false;
            }

            IntPtr userToken    = IntPtr.Zero;
            IntPtr primaryToken = IntPtr.Zero;
            IntPtr environment  = IntPtr.Zero;

            try
            {
                // Paso 1: obtener token de impersonación del usuario logueado.
                if (!WTSQueryUserToken(sessionId, out userToken))
                    throw new InvalidOperationException($"WTSQueryUserToken falló. Win32 error: {Marshal.GetLastWin32Error()}");

                // Paso 2: promover a token primario (CreateProcessAsUser lo requiere).
                var sa = new SECURITY_ATTRIBUTES { nLength = Marshal.SizeOf<SECURITY_ATTRIBUTES>() };
                if (!DuplicateTokenEx(userToken, TOKEN_ALL_ACCESS, ref sa,
                        SECURITY_IMPERSONATION_LEVEL.SecurityImpersonation,
                        TOKEN_TYPE.TokenPrimary, out primaryToken))
                    throw new InvalidOperationException($"DuplicateTokenEx falló. Win32 error: {Marshal.GetLastWin32Error()}");

                // Paso 3: construir bloque de entorno del perfil del usuario.
                CreateEnvironmentBlock(out environment, primaryToken, false);

                var si = new STARTUPINFO
                {
                    cb        = Marshal.SizeOf<STARTUPINFO>(),
                    lpDesktop = "winsta0\\default"   // escritorio interactivo
                };

                uint flags = CREATE_UNICODE_ENVIRONMENT | NORMAL_PRIORITY_CLASS;

                string commandLine = string.IsNullOrWhiteSpace(arguments)
                    ? $"\"{exePath}\""
                    : $"\"{exePath}\" {arguments}";

                AlwaysPrintLogger.WriteInfo($"Llamando CreateProcessAsUser: {commandLine}");

                bool ok = CreateProcessAsUser(
                    primaryToken, null, commandLine,
                    ref sa, ref sa, false, flags, environment,
                    Path.GetDirectoryName(exePath), ref si, out var pi);

                if (ok)
                {
                    if (pi.hProcess != IntPtr.Zero) CloseHandle(pi.hProcess);
                    if (pi.hThread  != IntPtr.Zero) CloseHandle(pi.hThread);
                    AlwaysPrintLogger.WriteInfo(
                        $"InteractiveProcessLauncher: launched '{exePath}' in session {sessionId}.",
                        AlwaysPrintLogger.EvtTrayStarting);
                }
                else
                {
                    AlwaysPrintLogger.WriteError(
                        $"CreateProcessAsUser falló. Win32 error: {Marshal.GetLastWin32Error()}",
                        AlwaysPrintLogger.EvtTrayError);
                }

                return ok;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError("InteractiveProcessLauncher falló.", ex, AlwaysPrintLogger.EvtTrayError);
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
