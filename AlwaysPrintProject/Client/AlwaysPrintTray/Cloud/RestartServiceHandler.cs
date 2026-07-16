using System;
using System.Diagnostics;
using System.IO;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Messages;
using AlwaysPrintTray.Pipe;

namespace AlwaysPrintTray.Cloud
{
    /// <summary>
    /// Ejecuta el reinicio del servicio AlwaysPrintService.
    /// Estrategia: envía mensaje pipe al Service para que él genere y lance
    /// el script de reinicio (corre como SYSTEM, tiene permisos para net stop/start).
    /// Fallback: si el pipe no está conectado, intenta lanzar script directo
    /// (puede fallar si el usuario no es admin).
    /// </summary>
    public static class RestartServiceHandler
    {
        private const string ServiceName = "AlwaysPrintService";
        private const string TrayProcessName = "AlwaysPrintTray";

        /// <summary>
        /// Solicita al Service que se reinicie a sí mismo vía Named Pipe.
        /// El Service corre como SYSTEM y tiene permisos para ejecutar net stop/start.
        /// </summary>
        /// <param name="pipe">Cliente pipe para comunicación con el Service.</param>
        /// <returns>Tupla con resultado: success indica si el reinicio fue iniciado.</returns>
        public static (bool success, string message) Execute(PipeClient? pipe = null)
        {
            // Estrategia 1: delegar al Service vía pipe (preferido — corre como SYSTEM)
            if (pipe != null && pipe.IsConnected)
            {
                try
                {
                    var msg = PipeMessage.Create(MessageType.ServiceAction,
                        new ServiceActionPayload { Action = "restart" });
                    var response = pipe.Send(msg);

                    if (response?.Type == MessageType.Ack)
                    {
                        var ack = response.GetPayload<AckPayload>();
                        if (ack?.Success == true)
                        {
                            AlwaysPrintLogger.WriteTrayInfo(
                                "RestartServiceHandler: Service confirmó reinicio. El servicio se reiniciará en breve.");
                            return (true, "Reinicio de servicio iniciado por el Service (SYSTEM).");
                        }
                        else
                        {
                            AlwaysPrintLogger.WriteTrayWarning(
                                $"RestartServiceHandler: Service reportó error: {ack?.Message}. Intentando fallback directo.");
                        }
                    }
                }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"RestartServiceHandler: error comunicando con Service: {ex.Message}. Intentando fallback directo.");
                }
            }

            // Estrategia 2: fallback — lanzar script directo (requiere admin, puede fallar)
            return ExecuteDirectScript();
        }

        /// <summary>
        /// Fallback: genera y lanza un script .cmd directo que reinicia el servicio.
        /// Solo funciona si el proceso tiene privilegios de administrador.
        /// </summary>
        private static (bool success, string message) ExecuteDirectScript()
        {
            try
            {
                string scriptDir = Path.Combine(Path.GetTempPath(), "AlwaysPrint", "Commands");
                Directory.CreateDirectory(scriptDir);

                string scriptPath = Path.Combine(
                    scriptDir,
                    $"restart_service_{DateTime.Now:yyyyMMdd_HHmmss}.cmd");

                string scriptContent = GenerateRestartScript(scriptPath);
                File.WriteAllText(scriptPath, scriptContent);

                AlwaysPrintLogger.WriteTrayInfo(
                    $"RestartServiceHandler: script de reinicio (fallback) generado en {scriptPath}");

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
                    string errorMsg = "RestartServiceHandler: no se pudo lanzar el script de reinicio (fallback).";
                    AlwaysPrintLogger.WriteTrayError(errorMsg);
                    return (false, errorMsg);
                }

                AlwaysPrintLogger.WriteTrayInfo(
                    $"RestartServiceHandler: script de reinicio (fallback) lanzado (PID={process.Id}).");

                return (true, "Script de reinicio lanzado (fallback directo, puede requerir permisos admin).");
            }
            catch (Exception ex)
            {
                string errorMsg = $"RestartServiceHandler: error en fallback directo: {ex.Message}";
                AlwaysPrintLogger.WriteTrayError(errorMsg);
                return (false, errorMsg);
            }
        }

        private static string GenerateRestartScript(string scriptPath)
        {
            // Ruta del log principal de AlwaysPrint (fecha fija al generar el script)
            string logDate = DateTime.Now.ToString("yyyyMMdd");
            string logFile = $@"C:\ProgramData\AlwaysPrint\logs\AlwaysPrint_{logDate}.log";
            string datePrefix = DateTime.Now.ToString("yyyy-MM-dd");

            return $@"@echo off
REM ============================================================
REM Script de reinicio de servicio AlwaysPrint
REM Generado: {DateTime.Now:yyyy-MM-dd HH:mm:ss}
REM ============================================================

set ""LOGFILE={logFile}""
set ""DATEPREFIX={datePrefix}""

goto :main

:log
set ""MSG=%~1""
echo [%DATEPREFIX% %time:~0,8%] [RST] Event 1090: %MSG% >> ""%LOGFILE%""
goto :eof

:main
call :log ""Inicio de script de reinicio""

call :log ""Esperando 3s antes de taskkill...""
timeout /t 3 /nobreak > nul

taskkill /f /im {TrayProcessName}.exe > nul 2>&1
call :log ""taskkill /f /im {TrayProcessName}.exe - errorlevel=%errorlevel%""

call :log ""Ejecutando net stop {ServiceName}...""
net stop {ServiceName} > nul 2>&1
call :log ""net stop {ServiceName} - errorlevel=%errorlevel%""

call :log ""Esperando 3s antes de net start...""
timeout /t 3 /nobreak > nul

call :log ""Ejecutando net start {ServiceName}...""
net start {ServiceName} > nul 2>&1
call :log ""net start {ServiceName} - errorlevel=%errorlevel%""

call :log ""Script de reinicio completado""
";
        }
    }
}
