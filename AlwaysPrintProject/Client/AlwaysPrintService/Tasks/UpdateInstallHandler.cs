using System;
using System.Diagnostics;
using System.IO;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Messages;
using AlwaysPrintService.UserSession;

namespace AlwaysPrintService.Tasks
{
    /// <summary>
    /// Maneja la instalación silenciosa del MSI de actualización.
    /// Ejecuta en contexto de LocalSystem (permisos de administrador).
    /// </summary>
    public sealed class UpdateInstallHandler
    {
        // Timeout de 10 minutos para la ejecución de msiexec
        private const int InstallTimeoutMs = 10 * 60 * 1000;

        /// <summary>
        /// Ejecuta la instalación silenciosa del MSI especificado.
        /// </summary>
        /// <param name="msiFilePath">Ruta completa al archivo MSI a instalar.</param>
        /// <returns>Resultado de la instalación con éxito/fallo, mensaje y código de salida.</returns>
        public InstallUpdateResponsePayload Execute(string msiFilePath)
        {
            AlwaysPrintLogger.WriteInfo(
                $"InstallUpdate: iniciando instalación de actualización. Archivo: {msiFilePath}",
                AlwaysPrintLogger.EvtTaskDispatched);

            try
            {
                // 1. Verificar que el archivo MSI existe
                if (!File.Exists(msiFilePath))
                {
                    string errorMsg = $"InstallUpdate: archivo no encontrado en {msiFilePath}.";
                    AlwaysPrintLogger.WriteError(errorMsg, AlwaysPrintLogger.EvtTaskFailed);
                    return new InstallUpdateResponsePayload
                    {
                        Success = false,
                        Message = errorMsg,
                        ExitCode = -1
                    };
                }

                // 2. Ejecutar msiexec con instalación silenciosa
                var startInfo = new ProcessStartInfo
                {
                    FileName = "msiexec",
                    Arguments = $"/i \"{msiFilePath}\" /quiet /norestart",
                    UseShellExecute = false,
                    CreateNoWindow = true
                };

                AlwaysPrintLogger.WriteInfo(
                    $"InstallUpdate: ejecutando msiexec /i \"{msiFilePath}\" /quiet /norestart",
                    AlwaysPrintLogger.EvtTaskDispatched);

                using (var process = Process.Start(startInfo))
                {
                    if (process == null)
                    {
                        string errorMsg = "InstallUpdate: no se pudo iniciar el proceso msiexec.";
                        AlwaysPrintLogger.WriteError(errorMsg, AlwaysPrintLogger.EvtTaskFailed);
                        return new InstallUpdateResponsePayload
                        {
                            Success = false,
                            Message = errorMsg,
                            ExitCode = -1
                        };
                    }

                    // 3. Esperar finalización con timeout de 10 minutos
                    bool exited = process.WaitForExit(InstallTimeoutMs);

                    if (!exited)
                    {
                        // Timeout excedido: matar proceso y retornar error
                        try { process.Kill(); } catch { /* proceso ya terminó */ }

                        string errorMsg = "InstallUpdate: instalación excedió timeout de 10 minutos. Proceso terminado.";
                        AlwaysPrintLogger.WriteError(errorMsg, AlwaysPrintLogger.EvtTaskFailed);
                        return new InstallUpdateResponsePayload
                        {
                            Success = false,
                            Message = errorMsg,
                            ExitCode = -1
                        };
                    }

                    int exitCode = process.ExitCode;

                    // 4. Evaluar resultado según código de salida
                    if (exitCode == 0)
                    {
                        AlwaysPrintLogger.WriteInfo(
                            "InstallUpdate: instalación completada exitosamente (ExitCode=0).",
                            AlwaysPrintLogger.EvtTaskCompleted);

                        // Eliminar archivo MSI temporal
                        TryDeleteMsi(msiFilePath);

                        // Reiniciar proceso Tray
                        RestartTray();

                        return new InstallUpdateResponsePayload
                        {
                            Success = true,
                            Message = "Actualización instalada exitosamente.",
                            ExitCode = 0
                        };
                    }
                    else
                    {
                        // Instalación fallida con código de error
                        string errorMsg = $"InstallUpdate: instalación fallida. msiexec exit code={exitCode}.";
                        AlwaysPrintLogger.WriteError(errorMsg, AlwaysPrintLogger.EvtTaskFailed);
                        return new InstallUpdateResponsePayload
                        {
                            Success = false,
                            Message = errorMsg,
                            ExitCode = exitCode
                        };
                    }
                }
            }
            catch (Exception ex)
            {
                string errorMsg = $"InstallUpdate: no se pudo iniciar msiexec: {ex.Message}";
                AlwaysPrintLogger.WriteError(errorMsg, ex, AlwaysPrintLogger.EvtTaskFailed);
                return new InstallUpdateResponsePayload
                {
                    Success = false,
                    Message = errorMsg,
                    ExitCode = -1
                };
            }
        }

        /// <summary>
        /// Intenta eliminar el archivo MSI temporal. No es crítico si falla.
        /// </summary>
        private static void TryDeleteMsi(string msiFilePath)
        {
            try
            {
                File.Delete(msiFilePath);
                AlwaysPrintLogger.WriteInfo(
                    $"InstallUpdate: archivo MSI temporal eliminado: {msiFilePath}",
                    AlwaysPrintLogger.EvtTaskCompleted);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteWarning(
                    $"InstallUpdate: no se pudo eliminar MSI temporal: {ex.Message}",
                    AlwaysPrintLogger.EvtGenericWarning);
            }
        }

        /// <summary>
        /// Reinicia el proceso Tray: mata instancias existentes y lanza una nueva
        /// en la sesión interactiva del usuario.
        /// </summary>
        private static void RestartTray()
        {
            try
            {
                // Matar instancias existentes del Tray
                int killed = KillExistingTray();
                if (killed > 0)
                    AlwaysPrintLogger.WriteInfo(
                        $"InstallUpdate: se eliminaron {killed} instancia(s) del Tray para reinicio post-actualización.",
                        AlwaysPrintLogger.EvtTrayKilled);

                // Lanzar nueva instancia del Tray en la sesión del usuario
                string trayExe = Path.Combine(
                    Path.GetDirectoryName(Process.GetCurrentProcess().MainModule!.FileName)!,
                    "AlwaysPrintTray.exe");

                bool launched = InteractiveProcessLauncher.Launch(trayExe);
                if (launched)
                    AlwaysPrintLogger.WriteInfo(
                        "InstallUpdate: Tray reiniciado exitosamente post-actualización.",
                        AlwaysPrintLogger.EvtTrayStarted);
                else
                    AlwaysPrintLogger.WriteError(
                        "InstallUpdate: error al reiniciar Tray post-actualización.",
                        AlwaysPrintLogger.EvtTrayError);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"InstallUpdate: error al reiniciar Tray post-actualización: {ex.Message}",
                    ex, AlwaysPrintLogger.EvtTrayError);
            }
        }

        /// <summary>
        /// Mata todas las instancias del proceso AlwaysPrintTray.
        /// </summary>
        private static int KillExistingTray()
        {
            int count = 0;
            foreach (var p in Process.GetProcessesByName("AlwaysPrintTray"))
            {
                try { p.Kill(); count++; } catch { /* proceso ya terminó */ }
            }
            return count;
        }
    }
}
