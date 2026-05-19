using System;
using System.Diagnostics;
using System.IO;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintTray.Cloud
{
    /// <summary>
    /// Genera y ejecuta un script .cmd independiente que reinicia el servicio AlwaysPrintService.
    /// El script sobrevive a la muerte del Tray y del Service.
    /// Patrón: mismo que UpdateInstallHandler del proyecto Service.
    /// </summary>
    public static class RestartServiceHandler
    {
        private const string ServiceName = "AlwaysPrintService";
        private const string TrayProcessName = "AlwaysPrintTray";

        /// <summary>
        /// Genera y lanza un script .cmd que reinicia el servicio AlwaysPrintService.
        /// El script se ejecuta como proceso independiente que sobrevive al Tray y al Service.
        /// </summary>
        /// <returns>Tupla con resultado: success indica si el script fue lanzado, message con detalle.</returns>
        public static (bool success, string message) Execute()
        {
            try
            {
                // Generar ruta del script temporal
                string scriptDir = Path.Combine(Path.GetTempPath(), "AlwaysPrint", "Commands");
                Directory.CreateDirectory(scriptDir);

                string scriptPath = Path.Combine(
                    scriptDir,
                    $"restart_service_{DateTime.Now:yyyyMMdd_HHmmss}.cmd");

                // Generar contenido del script de reinicio
                string scriptContent = GenerateRestartScript(scriptPath);
                File.WriteAllText(scriptPath, scriptContent);

                AlwaysPrintLogger.WriteTrayInfo(
                    $"RestartServiceHandler: script de reinicio generado en {scriptPath}");

                // Lanzar como proceso independiente (no hijo del Tray)
                var startInfo = new ProcessStartInfo
                {
                    FileName = "cmd.exe",
                    Arguments = $"/c \"{scriptPath}\"",
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    WorkingDirectory = Path.GetTempPath()
                };

                var process = Process.Start(startInfo);
                if (process == null)
                {
                    string errorMsg = "RestartServiceHandler: no se pudo lanzar el script de reinicio.";
                    AlwaysPrintLogger.WriteTrayError(errorMsg);
                    return (false, errorMsg);
                }

                AlwaysPrintLogger.WriteTrayInfo(
                    $"RestartServiceHandler: script de reinicio lanzado (PID={process.Id}). " +
                    "El servicio se reiniciará en breve.");

                return (true, "Script de reinicio de servicio lanzado exitosamente.");
            }
            catch (Exception ex)
            {
                string errorMsg = $"RestartServiceHandler: error al generar/lanzar script de reinicio: {ex.Message}";
                AlwaysPrintLogger.WriteTrayError(errorMsg);
                return (false, errorMsg);
            }
        }

        /// <summary>
        /// Genera el contenido del script .cmd que reinicia el servicio.
        /// Secuencia:
        /// 1. Espera 3 segundos (para que el Tray termine de enviar command_result)
        /// 2. Mata el proceso AlwaysPrintTray
        /// 3. Detiene el servicio AlwaysPrintService
        /// 4. Espera 3 segundos
        /// 5. Inicia el servicio (que relanzará el Tray automáticamente)
        /// 6. Se auto-elimina
        /// </summary>
        private static string GenerateRestartScript(string scriptPath)
        {
            return $@"@echo off
REM ============================================================
REM Script de reinicio de servicio AlwaysPrint
REM Generado: {DateTime.Now:yyyy-MM-dd HH:mm:ss}
REM Comando remoto desde Cloud Manager
REM ============================================================
timeout /t 3 /nobreak > nul
taskkill /f /im {TrayProcessName}.exe > nul 2>&1
net stop {ServiceName} > nul 2>&1
timeout /t 3 /nobreak > nul
net start {ServiceName} > nul 2>&1
(goto) 2>nul & del /f /q ""{scriptPath}""
";
        }
    }
}
