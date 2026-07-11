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
    /// 4. Reinicia el servicio (el Service lanza el Tray via CreateProcessAsUser)
    /// 5. Se auto-elimina
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
        /// 5. Inicia el servicio (el Service lanza el Tray via CreateProcessAsUser)
        /// 6. Elimina el MSI temporal
        /// 7. Se auto-elimina
        /// </summary>
        private static string GenerateInstallScript(string msiFilePath, string trayExePath, string scriptPath, string logFilePath)
        {
            return $@"@echo off
setlocal EnableDelayedExpansion
REM ============================================================
REM Script de actualización automática de AlwaysPrint
REM Generado: {DateTime.Now:yyyy-MM-dd HH:mm:ss}
REM MSI: {msiFilePath}
REM Script: {scriptPath}
REM Log: {logFilePath}
REM ============================================================

set LOG=""{logFilePath}""
set SCRIPT_PID=%~0

call :ts
echo %TS% [UPD] Event 1020: Iniciando script de actualizacion. MSI={msiFilePath}, ScriptPID=%%SCRIPT_PID%% >> %LOG%

REM Verificar que el MSI existe antes de continuar
if not exist ""{msiFilePath}"" (
    call :ts
    echo !TS! [UPD] Event 1091: ERROR - MSI no encontrado en {msiFilePath}. Abortando. >> %LOG%
    goto :script_end
)

REM Loggear tamaño del MSI
for %%A in (""{msiFilePath}"") do set MSI_SIZE=%%~zA
call :ts
echo %TS% [UPD] Event 1020: MSI verificado. Tamanio=%MSI_SIZE% bytes. >> %LOG%

REM Esperar 3 segundos para que el Service termine de responder al Tray
call :ts
echo %TS% [UPD] Event 1020: Esperando 3s para que el Service responda al Tray... >> %LOG%
timeout /t 3 /nobreak > nul

REM ============================================================
REM PASO 1: Matar procesos del Tray
REM ============================================================
call :ts
echo %TS% [UPD] Event 1020: [PASO 1] Matando procesos {TrayProcessName}.exe... >> %LOG%
taskkill /f /im {TrayProcessName}.exe 2>&1 | findstr /v ""^$"" >> %LOG%
set TK_EXIT=!errorlevel!
call :ts
echo %TS% [UPD] Event 1020: [PASO 1] taskkill {TrayProcessName}.exe resultado: exitcode=!TK_EXIT! >> %LOG%

REM Verificar que el Tray realmente murió
timeout /t 1 /nobreak > nul
tasklist /fi ""imagename eq {TrayProcessName}.exe"" 2>nul | findstr /i ""{TrayProcessName}"" > nul 2>&1
if !errorlevel! equ 0 (
    call :ts
    echo !TS! [UPD] Event 1091: WARN - {TrayProcessName}.exe aun activo despues de taskkill. Reintentando... >> %LOG%
    taskkill /f /im {TrayProcessName}.exe > nul 2>&1
    timeout /t 2 /nobreak > nul
)

REM ============================================================
REM PASO 2: Deshabilitar Service Recovery temporalmente
REM ============================================================
call :ts
echo %TS% [UPD] Event 1020: [PASO 2] Deshabilitando Service Recovery temporalmente. >> %LOG%
sc failure {ServiceName} reset= 0 actions= """"/""""/"""" 2>&1 | findstr /v ""^$"" >> %LOG%
call :ts
echo %TS% [UPD] Event 1020: [PASO 2] sc failure (deshabilitar) exitcode=!errorlevel! >> %LOG%

REM ============================================================
REM PASO 3: Detener el servicio
REM ============================================================
call :ts
echo %TS% [UPD] Event 1020: [PASO 3] Deteniendo servicio {ServiceName}... >> %LOG%
net stop {ServiceName} 2>&1 | findstr /v ""^$"" >> %LOG%
set STOP_EXIT=!errorlevel!
call :ts
echo %TS% [UPD] Event 1020: [PASO 3] net stop {ServiceName} exitcode=!STOP_EXIT! >> %LOG%

REM Esperar a que el servicio se detenga completamente
timeout /t 2 /nobreak > nul
sc query {ServiceName} 2>&1 | findstr /i ""STATE"" >> %LOG%

REM ============================================================
REM PASO 4: Verificar que no hay otro msiexec corriendo
REM ============================================================
call :ts
echo %TS% [UPD] Event 1020: [PASO 4] Verificando procesos msiexec existentes... >> %LOG%
tasklist /fi ""imagename eq msiexec.exe"" 2>nul | findstr /i ""msiexec"" > nul 2>&1
if !errorlevel! equ 0 (
    call :ts
    echo !TS! [UPD] Event 1091: WARN - msiexec.exe ya en ejecucion. Esperando 10s antes de continuar... >> %LOG%
    tasklist /fi ""imagename eq msiexec.exe"" 2>nul >> %LOG%
    timeout /t 10 /nobreak > nul
    REM Verificar de nuevo
    tasklist /fi ""imagename eq msiexec.exe"" 2>nul | findstr /i ""msiexec"" > nul 2>&1
    if !errorlevel! equ 0 (
        call :ts
        echo !TS! [UPD] Event 1091: WARN - msiexec.exe sigue activo despues de 10s. Continuando de todas formas. >> %LOG%
    ) else (
        call :ts
        echo !TS! [UPD] Event 1020: [PASO 4] msiexec.exe ya no esta activo. Continuando. >> %LOG%
    )
) else (
    call :ts
    echo %TS% [UPD] Event 1020: [PASO 4] No hay msiexec.exe activo. OK. >> %LOG%
)

REM ============================================================
REM PASO 5: Ejecutar instalación silenciosa
REM ============================================================
call :ts
echo %TS% [UPD] Event 1020: [PASO 5] Ejecutando msiexec /i (silencioso). MSI={msiFilePath} >> %LOG%
echo %TS% [UPD] Event 1020: [PASO 5] Comando: msiexec /i ""{msiFilePath}"" /quiet /norestart REINSTALLMODE=amus /l*v ""{msiFilePath}.msiexec.log"" >> %LOG%
msiexec /i ""{msiFilePath}"" /quiet /norestart REINSTALLMODE=amus /l*v ""{msiFilePath}.msiexec.log""
set INSTALL_EXIT=!errorlevel!
call :ts
echo %TS% [UPD] Event 1020: [PASO 5] msiexec finalizado. ExitCode=!INSTALL_EXIT! >> %LOG%

REM Interpretar exit code de msiexec para diagnóstico
if !INSTALL_EXIT! equ 0 (
    echo %TS% [UPD] Event 1020: [PASO 5] msiexec: EXITO (0) - Instalacion completada correctamente. >> %LOG%
) else if !INSTALL_EXIT! equ 1603 (
    echo %TS% [UPD] Event 1091: [PASO 5] msiexec: ERROR FATAL (1603) - Error durante instalacion. Ver msiexec.log. >> %LOG%
) else if !INSTALL_EXIT! equ 1618 (
    echo %TS% [UPD] Event 1091: [PASO 5] msiexec: ERROR (1618) - Otra instalacion ya en progreso. >> %LOG%
) else if !INSTALL_EXIT! equ 1602 (
    echo %TS% [UPD] Event 1091: [PASO 5] msiexec: ERROR (1602) - Cancelado por usuario. >> %LOG%
) else if !INSTALL_EXIT! equ 1619 (
    echo %TS% [UPD] Event 1091: [PASO 5] msiexec: ERROR (1619) - No se pudo abrir paquete MSI. >> %LOG%
) else if !INSTALL_EXIT! equ 1620 (
    echo %TS% [UPD] Event 1091: [PASO 5] msiexec: ERROR (1620) - Paquete MSI invalido. >> %LOG%
) else if !INSTALL_EXIT! equ 1638 (
    echo %TS% [UPD] Event 1020: [PASO 5] msiexec: INFO (1638) - Otra version del producto ya instalada. >> %LOG%
) else (
    echo %TS% [UPD] Event 1091: [PASO 5] msiexec: CODIGO NO ESPERADO (!INSTALL_EXIT!). Ver msiexec.log. >> %LOG%
)

REM ============================================================
REM PASO 6: Restaurar Service Recovery
REM ============================================================
call :ts
echo %TS% [UPD] Event 1020: [PASO 6] Restaurando Service Recovery. >> %LOG%
sc failure {ServiceName} reset= 86400 actions= restart/5000/restart/5000/restart/5000 2>&1 | findstr /v ""^$"" >> %LOG%
call :ts
echo %TS% [UPD] Event 1020: [PASO 6] sc failure (restaurar) exitcode=!errorlevel! >> %LOG%

REM Verificar resultado de la instalación
if !INSTALL_EXIT! neq 0 (
    call :ts
    echo !TS! [UPD] Event 1091: ERROR - Instalacion fallida con codigo !INSTALL_EXIT!. Saltando a verificacion. >> %LOG%
    goto :cleanup
)

REM ============================================================
REM PASO 7: Iniciar el servicio actualizado
REM ============================================================
call :ts
echo %TS% [UPD] Event 1020: [PASO 7] Instalacion exitosa. Iniciando servicio {ServiceName}... >> %LOG%
net start {ServiceName} 2>&1 | findstr /v ""^$"" >> %LOG%
set START_EXIT=!errorlevel!
call :ts
echo %TS% [UPD] Event 1020: [PASO 7] net start {ServiceName} exitcode=!START_EXIT! >> %LOG%
timeout /t 3 /nobreak > nul

REM Verificar que el servicio arrancó
sc query {ServiceName} 2>&1 | findstr /i ""STATE"" >> %LOG%

REM El Tray será lanzado automáticamente por el Service (CreateProcessAsUser en sesión del usuario)

:cleanup
REM ============================================================
REM PASO 8: Verificación post-instalación
REM ============================================================
call :ts
echo %TS% [UPD] Event 1020: [PASO 8] Esperando 30 segundos antes de verificacion post-instalacion... >> %LOG%
timeout /t 30 /nobreak > nul

REM Verificar si msiexec sigue colgado
tasklist /fi ""imagename eq msiexec.exe"" 2>nul | findstr /i ""msiexec"" > nul 2>&1
if !errorlevel! equ 0 (
    call :ts
    echo !TS! [UPD] Event 1091: WARN - msiexec.exe sigue activo post-instalacion. Matando... >> %LOG%
    taskkill /f /im msiexec.exe 2>&1 | findstr /v ""^$"" >> %LOG%
)

REM ============================================================
REM PASO 9: Verificación final del servicio
REM Intenta hasta 5 veces con 30s entre intentos (total max ~2.5 min)
REM ============================================================
call :ts
echo %TS% [UPD] Event 1020: [PASO 9] Verificacion final - asegurando que el servicio esta activo... >> %LOG%

set VERIFY_ATTEMPT=0
set VERIFY_OK=0

:verify_loop
set /a VERIFY_ATTEMPT+=1
if !VERIFY_ATTEMPT! gtr 5 goto :verify_done

sc query {ServiceName} | findstr /i ""RUNNING"" > nul 2>&1
if !errorlevel! equ 0 (
    call :ts
    echo !TS! [UPD] Event 1020: [PASO 9] Verificacion !VERIFY_ATTEMPT!/5: servicio ACTIVO. >> %LOG%
    set VERIFY_OK=1
    goto :verify_done
)

call :ts
echo %TS% [UPD] Event 1020: [PASO 9] Verificacion !VERIFY_ATTEMPT!/5: servicio NO activo. >> %LOG%
sc query {ServiceName} 2>&1 | findstr /i ""STATE"" >> %LOG%

REM Verificar si el servicio existe (puede estar marcado para eliminación por msiexec)
sc query {ServiceName} > nul 2>&1
if !errorlevel! equ 1060 (
    call :ts
    echo !TS! [UPD] Event 1091: [PASO 9] Servicio no existe o marcado para eliminacion (sc error 1060). Reintentando msiexec... >> %LOG%
    taskkill /f /im msiexec.exe > nul 2>&1
    timeout /t 5 /nobreak > nul
    msiexec /i ""{msiFilePath}"" /quiet /norestart REINSTALLMODE=amus
    set RETRY_EXIT=!errorlevel!
    call :ts
    echo !TS! [UPD] Event 1020: [PASO 9] msiexec reintento exitcode=!RETRY_EXIT! >> %LOG%
    timeout /t 10 /nobreak > nul
)

REM Intentar iniciar el servicio
call :ts
echo %TS% [UPD] Event 1020: [PASO 9] Verificacion !VERIFY_ATTEMPT!/5: intentando iniciar servicio... >> %LOG%
net start {ServiceName} 2>&1 | findstr /v ""^$"" >> %LOG%
call :ts
echo %TS% [UPD] Event 1020: [PASO 9] net start exitcode=!errorlevel! >> %LOG%
timeout /t 30 /nobreak > nul
goto :verify_loop

:verify_done
if !VERIFY_OK! equ 0 (
    call :ts
    echo !TS! [UPD] Event 1091: CRITICO - Servicio no pudo iniciarse despues de 5 intentos. Requiere intervencion manual. >> %LOG%
) else (
    call :ts
    echo !TS! [UPD] Event 1020: Servicio verificado activo. Actualizacion completada. >> %LOG%
    REM El Tray será lanzado automáticamente por el Service al iniciar (CreateProcessAsUser)
)

:script_end
REM Eliminar MSI temporal (después de verificación para permitir reinstalación si fue necesaria)
call :ts
echo %TS% [UPD] Event 1020: Eliminando MSI temporal... >> %LOG%
del /f /q ""{msiFilePath}"" > nul 2>&1
if exist ""{msiFilePath}"" (
    echo %TS% [UPD] Event 1091: WARN - No se pudo eliminar MSI (puede estar en uso). >> %LOG%
) else (
    echo %TS% [UPD] Event 1020: MSI temporal eliminado correctamente. >> %LOG%
)

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
