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

                // Ruta del log del día actual (para que el script escriba con prefijo [UPD])
                string logDir = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
                    "AlwaysPrint", "logs");
                string logFilePath = Path.Combine(logDir, $"AlwaysPrint_{DateTime.Now:yyyyMMdd}.log");

                // Asegurar que el directorio existe
                Directory.CreateDirectory(Path.GetDirectoryName(scriptPath)!);

                string scriptContent = GenerateInstallScript(msiFilePath, trayExePath, scriptPath, logFilePath);
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
        private static string GenerateInstallScript(string msiFilePath, string trayExePath, string scriptPath, string logFilePath)
        {
            return $@"@echo off
REM ============================================================
REM Script de actualización automática de AlwaysPrint
REM Generado: {DateTime.Now:yyyy-MM-dd HH:mm:ss}
REM MSI: {msiFilePath}
REM Log: {logFilePath}
REM ============================================================

set LOG=""{logFilePath}""

call :ts
echo %TS% [UPD] Event 1020: Iniciando script de actualizacion. MSI={msiFilePath} >> %LOG%

REM Esperar 3 segundos para que el Service termine de responder
timeout /t 3 /nobreak > nul

REM Matar procesos del Tray
call :ts
echo %TS% [UPD] Event 1020: Deteniendo procesos AlwaysPrintTray... >> %LOG%
taskkill /f /im {TrayProcessName}.exe > nul 2>&1

REM Deshabilitar Service Recovery temporalmente para evitar que SCM reinicie
REM el servicio antes de que msiexec complete la instalación
call :ts
echo %TS% [UPD] Event 1020: Deshabilitando Service Recovery temporalmente. >> %LOG%
sc failure {ServiceName} reset= 0 actions= """"/""""/"""" > nul 2>&1

REM Detener el servicio
call :ts
echo %TS% [UPD] Event 1020: Deteniendo servicio {ServiceName}... >> %LOG%
net stop {ServiceName} > nul 2>&1
timeout /t 2 /nobreak > nul

REM Ejecutar instalación silenciosa
call :ts
echo %TS% [UPD] Event 1020: Ejecutando msiexec /i (silencioso)... >> %LOG%
msiexec /i ""{msiFilePath}"" /quiet /norestart REINSTALLMODE=amus /l*v ""{msiFilePath}.msiexec.log""
set INSTALL_EXIT=%errorlevel%
call :ts
echo %TS% [UPD] Event 1020: msiexec finalizado con codigo de salida: %INSTALL_EXIT% >> %LOG%

REM Restaurar Service Recovery (reiniciar en 5s ante fallo, reset counter cada 86400s)
call :ts
echo %TS% [UPD] Event 1020: Restaurando Service Recovery. >> %LOG%
sc failure {ServiceName} reset= 86400 actions= restart/5000/restart/5000/restart/5000 > nul 2>&1

REM Verificar resultado
if %INSTALL_EXIT% neq 0 (
    call :ts
    echo %TS% [UPD] Event 1091: ERROR - Instalacion fallida con codigo %INSTALL_EXIT%. >> %LOG%
    goto :cleanup
)

call :ts
echo %TS% [UPD] Event 1020: Instalacion exitosa. Iniciando servicio actualizado... >> %LOG%

REM Iniciar el servicio actualizado
net start {ServiceName} > nul 2>&1
timeout /t 3 /nobreak > nul

REM Lanzar el Tray actualizado
call :ts
echo %TS% [UPD] Event 1020: Lanzando AlwaysPrintTray.exe... >> %LOG%
start """" ""{trayExePath}""

:cleanup
REM ============================================================
REM Esperar 30 segundos antes de verificar (dar tiempo al servicio para estabilizarse)
REM ============================================================
call :ts
echo %TS% [UPD] Event 1020: Esperando 30 segundos antes de verificacion post-instalacion... >> %LOG%
timeout /t 30 /nobreak > nul

REM Matar procesos msiexec que puedan estar colgados (libera lock del servicio)
taskkill /f /im msiexec.exe > nul 2>&1

REM ============================================================
REM Verificación final: asegurar que el servicio está corriendo
REM Intenta hasta 5 veces con 30s entre intentos (total max ~2.5 min)
REM ============================================================
call :ts
echo %TS% [UPD] Event 1020: Verificacion final - asegurando que el servicio esta activo... >> %LOG%

set VERIFY_ATTEMPT=0
set VERIFY_OK=0

:verify_loop
set /a VERIFY_ATTEMPT+=1
if %VERIFY_ATTEMPT% gtr 5 goto :verify_done

sc query {ServiceName} | findstr /i ""RUNNING"" > nul 2>&1
if %errorlevel% equ 0 (
    call :ts
    echo %TS% [UPD] Event 1020: Verificacion %VERIFY_ATTEMPT%/5: servicio ACTIVO. >> %LOG%
    set VERIFY_OK=1
    goto :verify_done
)

call :ts
echo %TS% [UPD] Event 1020: Verificacion %VERIFY_ATTEMPT%/5: servicio NO activo. >> %LOG%

REM Verificar si el servicio existe (puede estar marcado para eliminación)
sc query {ServiceName} > nul 2>&1
if %errorlevel% equ 1060 (
    call :ts
    echo %TS% [UPD] Event 1091: Servicio no existe o marcado para eliminacion. Reintentando msiexec... >> %LOG%
    taskkill /f /im msiexec.exe > nul 2>&1
    timeout /t 5 /nobreak > nul
    msiexec /i ""{msiFilePath}"" /quiet /norestart REINSTALLMODE=amus
    timeout /t 10 /nobreak > nul
)

REM Intentar iniciar el servicio
call :ts
echo %TS% [UPD] Event 1020: Verificacion %VERIFY_ATTEMPT%/5: intentando iniciar servicio... >> %LOG%
net start {ServiceName} > nul 2>&1
timeout /t 30 /nobreak > nul
goto :verify_loop

:verify_done
if %VERIFY_OK% equ 0 (
    call :ts
    echo %TS% [UPD] Event 1091: CRITICO - Servicio no pudo iniciarse despues de 5 intentos. Requiere intervencion manual. >> %LOG%
) else (
    call :ts
    echo %TS% [UPD] Event 1020: Servicio verificado activo. Actualizacion completada. >> %LOG%
    REM Lanzar Tray si no está corriendo (caso de error donde no se lanzó antes)
    tasklist /fi ""IMAGENAME eq {TrayProcessName}.exe"" | findstr /i ""{TrayProcessName}"" > nul 2>&1
    if %errorlevel% neq 0 (
        call :ts
        echo %TS% [UPD] Event 1020: Lanzando AlwaysPrintTray.exe (post-verificacion)... >> %LOG%
        start """" ""{trayExePath}""
    )
)

REM Eliminar MSI temporal (después de verificación para permitir reinstalación si fue necesaria)
del /f /q ""{msiFilePath}"" > nul 2>&1

call :ts
echo %TS% [UPD] Event 1020: Script de actualizacion finalizado. >> %LOG%

REM Auto-eliminar este script (con delay para que cmd lo suelte)
(goto) 2>nul & del /f /q ""{scriptPath}""
exit /b

:ts
for /f ""delims="" %%a in ('powershell -NoProfile -Command ""Get-Date -Format '[yyyy-MM-dd HH:mm:ss]'""') do set ""TS=%%a""
goto :eof
";
        }
    }
}
