using System;
using System.Diagnostics;
using System.IO;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Messages;

namespace AlwaysPrintService.Tasks
{
    /// <summary>
    /// Maneja la instalación silenciosa del MSI de actualización.
    /// Genera un script .cmd temporal que:
    /// 1. Detiene el servicio AlwaysPrintService
    /// 2. Mata procesos AlwaysPrintTray
    /// 3. Ejecuta msiexec /i silencioso
    /// 4. Reinicia el servicio
    /// 5. Lanza el Tray
    /// 6. Se auto-elimina
    /// </summary>
    public sealed class UpdateInstallHandler
    {
        private const string ServiceName = "AlwaysPrintService";
        private const string TrayProcessName = "AlwaysPrintTray";

        /// <summary>
        /// Ejecuta la instalación silenciosa del MSI especificado.
        /// Genera un script externo que detiene el servicio antes de instalar.
        /// </summary>
        /// <param name="msiFilePath">Ruta completa al archivo MSI a instalar.</param>
        /// <returns>Resultado de la instalación (éxito indica que el script fue lanzado).</returns>
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

                // 2. Obtener ruta del ejecutable del Tray (mismo directorio que el Service)
                string serviceDir = Path.GetDirectoryName(
                    Process.GetCurrentProcess().MainModule!.FileName)!;
                string trayExePath = Path.Combine(serviceDir, "AlwaysPrintTray.exe");

                // 3. Generar script de instalación temporal
                string scriptPath = Path.Combine(
                    Path.GetTempPath(), "AlwaysPrint", "Updates",
                    $"install_{DateTime.Now:yyyyMMdd_HHmmss}.cmd");

                // Asegurar que el directorio existe
                Directory.CreateDirectory(Path.GetDirectoryName(scriptPath)!);

                string scriptContent = GenerateInstallScript(msiFilePath, trayExePath, scriptPath);
                File.WriteAllText(scriptPath, scriptContent);

                AlwaysPrintLogger.WriteInfo(
                    $"InstallUpdate: script de instalación generado en {scriptPath}",
                    AlwaysPrintLogger.EvtTaskDispatched);

                // 4. Lanzar el script como proceso independiente (no hijo del servicio)
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
                    string errorMsg = "InstallUpdate: no se pudo lanzar el script de instalación.";
                    AlwaysPrintLogger.WriteError(errorMsg, AlwaysPrintLogger.EvtTaskFailed);
                    return new InstallUpdateResponsePayload
                    {
                        Success = false,
                        Message = errorMsg,
                        ExitCode = -1
                    };
                }

                AlwaysPrintLogger.WriteInfo(
                    $"InstallUpdate: script de instalación lanzado (PID={process.Id}). " +
                    "El servicio se detendrá en breve para permitir la actualización.",
                    AlwaysPrintLogger.EvtTaskCompleted);

                // Retornar éxito — el script se encargará del resto
                // (detener servicio, instalar, reiniciar)
                return new InstallUpdateResponsePayload
                {
                    Success = true,
                    Message = "Script de actualización lanzado. El servicio se reiniciará automáticamente.",
                    ExitCode = 0
                };
            }
            catch (Exception ex)
            {
                string errorMsg = $"InstallUpdate: error al preparar la instalación: {ex.Message}";
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
        /// Genera el contenido del script .cmd que ejecuta la actualización.
        /// El script:
        /// 1. Espera 3 segundos (para que el Service termine de responder al Tray)
        /// 2. Mata procesos del Tray
        /// 3. Detiene el servicio
        /// 4. Ejecuta msiexec silencioso
        /// 5. Inicia el servicio
        /// 6. Lanza el Tray
        /// 7. Elimina el MSI temporal
        /// 8. Se auto-elimina
        /// </summary>
        private static string GenerateInstallScript(string msiFilePath, string trayExePath, string scriptPath)
        {
            // Usar log en el mismo directorio del MSI para diagnóstico
            string logPath = Path.Combine(
                Path.GetDirectoryName(msiFilePath)!,
                $"install_{DateTime.Now:yyyyMMdd_HHmmss}.log");

            return $@"@echo off
REM ============================================================
REM Script de actualización automática de AlwaysPrint
REM Generado: {DateTime.Now:yyyy-MM-dd HH:mm:ss}
REM MSI: {msiFilePath}
REM ============================================================

echo [%date% %time%] Iniciando actualización de AlwaysPrint... >> ""{logPath}""

REM Esperar 3 segundos para que el Service termine de responder
timeout /t 3 /nobreak > nul

REM Matar procesos del Tray
echo [%date% %time%] Deteniendo AlwaysPrintTray... >> ""{logPath}""
taskkill /f /im {TrayProcessName}.exe > nul 2>&1

REM Detener el servicio
echo [%date% %time%] Deteniendo servicio {ServiceName}... >> ""{logPath}""
net stop {ServiceName} > nul 2>&1
timeout /t 2 /nobreak > nul

REM Ejecutar instalación silenciosa (REINSTALLMODE=amus fuerza copia de archivos incluso en downgrade)
echo [%date% %time%] Ejecutando msiexec... >> ""{logPath}""
msiexec /i ""{msiFilePath}"" /quiet /norestart REINSTALLMODE=amus /l*v ""{logPath}.msiexec.log""
set INSTALL_EXIT=%errorlevel%
echo [%date% %time%] msiexec finalizado con código: %INSTALL_EXIT% >> ""{logPath}""

REM Verificar resultado
if %INSTALL_EXIT% neq 0 (
    echo [%date% %time%] ERROR: Instalación fallida. Reiniciando servicio anterior... >> ""{logPath}""
    net start {ServiceName} > nul 2>&1
    timeout /t 2 /nobreak > nul
    start """" ""{trayExePath}""
    goto :cleanup
)

echo [%date% %time%] Instalación exitosa. Reiniciando servicio... >> ""{logPath}""

REM Iniciar el servicio actualizado
net start {ServiceName} > nul 2>&1
timeout /t 3 /nobreak > nul

REM Lanzar el Tray actualizado
echo [%date% %time%] Lanzando AlwaysPrintTray... >> ""{logPath}""
start """" ""{trayExePath}""

REM Eliminar MSI temporal
echo [%date% %time%] Eliminando MSI temporal... >> ""{logPath}""
del /f /q ""{msiFilePath}"" > nul 2>&1

:cleanup
echo [%date% %time%] Actualización finalizada. >> ""{logPath}""

REM Auto-eliminar este script (con delay para que cmd lo suelte)
(goto) 2>nul & del /f /q ""{scriptPath}""
";
        }
    }
}
