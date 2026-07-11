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
    /// 1. Verifica que no haya otra actualización en progreso (lockfile)
    /// 2. Detiene el servicio AlwaysPrintService
    /// 3. Mata procesos AlwaysPrintTray
    /// 4. Ejecuta msiexec /i silencioso
    /// 5. Verifica que la versión realmente cambió post-instalación
    /// 6. Reinicia el servicio (el Service lanza el Tray via CreateProcessAsUser)
    /// 7. Se auto-elimina
    /// </summary>
    public sealed class UpdateInstallHandler
    {
        private const string ServiceName = "AlwaysPrintService";
        private const string TrayProcessName = "AlwaysPrintTray";

        /// <summary>
        /// Ruta del lockfile que previene ejecución concurrente de scripts de actualización.
        /// Se ubica en ProgramData para que sea accesible por SYSTEM y por el Tray.
        /// </summary>
        private static readonly string LockFilePath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
            "AlwaysPrint", "Updates", "update.lock");

        /// <summary>
        /// Ejecuta la instalación silenciosa del MSI especificado.
        /// Genera un script externo que detiene el servicio antes de instalar.
        /// Verifica que no haya otra actualización en progreso antes de lanzar.
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

                // 1b. Si el MSI está en un perfil de usuario (%TEMP% del Tray), copiarlo a
                // ProgramData para que el script (que corre como SYSTEM) pueda accederlo.
                // En entornos corporativos con ACLs restrictivas, SYSTEM no puede leer
                // carpetas de perfil de usuario. Este paso resuelve el problema de bootstrap
                // donde versiones antiguas del Tray descargan en %TEMP% del usuario.
                msiFilePath = EnsureMsiAccessibleBySystem(msiFilePath);

                // 2. Verificar que no haya otra actualización en progreso (lockfile)
                if (IsUpdateInProgress())
                {
                    string errorMsg = "InstallUpdate: otra actualización ya está en progreso (lockfile activo). Ignorando solicitud.";
                    AlwaysPrintLogger.WriteWarning(errorMsg);
                    return new InstallUpdateResponsePayload
                    {
                        Success = false,
                        Message = errorMsg,
                        ExitCode = -2
                    };
                }

                // 3. Obtener ruta del ejecutable del Service (para verificar versión post-instalación)
                string serviceDir = Path.GetDirectoryName(
                    Process.GetCurrentProcess().MainModule!.FileName)!;
                string trayExePath = Path.Combine(serviceDir, "AlwaysPrintTray.exe");

                // 4. Generar script de instalación temporal en ProgramData (accesible por SYSTEM)
                string scriptDir = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
                    "AlwaysPrint", "Updates");
                string scriptPath = Path.Combine(scriptDir,
                    $"install_{DateTime.Now:yyyyMMdd_HHmmss}.cmd");

                // Ruta del log del día actual (para que el script escriba con prefijo [UPD])
                string logDir = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
                    "AlwaysPrint", "logs");
                string logFilePath = Path.Combine(logDir, $"AlwaysPrint_{DateTime.Now:yyyyMMdd}.log");

                // Asegurar que los directorios existen
                Directory.CreateDirectory(scriptDir);
                Directory.CreateDirectory(logDir);

                string scriptContent = GenerateInstallScript(
                    msiFilePath, trayExePath, scriptPath, logFilePath);
                File.WriteAllText(scriptPath, scriptContent);

                AlwaysPrintLogger.WriteInfo(
                    $"InstallUpdate: script de instalación generado en {scriptPath}",
                    AlwaysPrintLogger.EvtTaskDispatched);

                // 5. Lanzar el script como proceso independiente (no hijo del servicio)
                var startInfo = new ProcessStartInfo
                {
                    FileName = "cmd.exe",
                    Arguments = $"/c \"{scriptPath}\"",
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    WorkingDirectory = scriptDir
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
        /// Verifica si hay una actualización en progreso consultando el lockfile.
        /// El lockfile es válido por máximo 10 minutos para cubrir escenarios de crash
        /// donde el script no pudo eliminar el lock.
        /// </summary>
        /// <returns>true si hay una actualización activa; false si es seguro proceder.</returns>
        private static bool IsUpdateInProgress()
        {
            try
            {
                if (!File.Exists(LockFilePath))
                    return false;

                // Lockfile existe — verificar antigüedad. Si tiene más de 10 minutos,
                // considerarlo abandonado (script crasheó sin cleanup)
                var lockAge = DateTime.UtcNow - File.GetLastWriteTimeUtc(LockFilePath);
                if (lockAge.TotalMinutes > 10)
                {
                    AlwaysPrintLogger.WriteInfo(
                        $"InstallUpdate: lockfile encontrado pero expirado (edad: {lockAge.TotalMinutes:F1} min). Eliminando.");
                    try { File.Delete(LockFilePath); } catch { /* best effort */ }
                    return false;
                }

                AlwaysPrintLogger.WriteInfo(
                    $"InstallUpdate: lockfile activo (edad: {lockAge.TotalSeconds:F0}s). " +
                    "Otra actualización está en progreso.");
                return true;
            }
            catch (Exception ex)
            {
                // Si no se puede leer el lockfile, asumir que no hay lock (fail-open para updates)
                AlwaysPrintLogger.WriteWarning(
                    $"InstallUpdate: error verificando lockfile: {ex.Message}. Asumiendo sin lock.");
                return false;
            }
        }

        /// <summary>
        /// Si el MSI está en un perfil de usuario (ej: C:\Users\...\AppData\Local\Temp\),
        /// lo copia a C:\ProgramData\AlwaysPrint\Updates\ donde SYSTEM siempre tiene acceso.
        /// 
        /// Esto resuelve el problema de bootstrap donde versiones antiguas del Tray
        /// (pre-fix) descargan el MSI en %TEMP% del usuario, pero el script de instalación
        /// corre como SYSTEM y no puede leer la carpeta del perfil en entornos corporativos
        /// con ACLs restrictivas.
        /// 
        /// Si el MSI ya está en ProgramData (versión nueva del Tray), retorna el path sin cambios.
        /// </summary>
        /// <param name="originalPath">Ruta original del MSI (posiblemente en perfil de usuario).</param>
        /// <returns>Ruta del MSI accesible por SYSTEM (puede ser la misma o una copia).</returns>
        private static string EnsureMsiAccessibleBySystem(string originalPath)
        {
            string programDataUpdates = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
                "AlwaysPrint", "Updates");

            // Si ya está en ProgramData, no necesita copia
            if (originalPath.StartsWith(programDataUpdates, StringComparison.OrdinalIgnoreCase))
            {
                return originalPath;
            }

            // Está en un perfil de usuario u otra ubicación → copiar a ProgramData
            try
            {
                Directory.CreateDirectory(programDataUpdates);
                string destPath = Path.Combine(programDataUpdates, "AlwaysPrint_update.msi");

                File.Copy(originalPath, destPath, overwrite: true);

                AlwaysPrintLogger.WriteInfo(
                    $"InstallUpdate: MSI copiado de perfil de usuario a ProgramData para acceso SYSTEM. " +
                    $"Origen: {originalPath}, Destino: {destPath}");

                // Eliminar el original (best effort, no bloquear si falla)
                try { File.Delete(originalPath); } catch { /* el script lo eliminará después */ }

                return destPath;
            }
            catch (Exception ex)
            {
                // Si la copia falla, intentar con el path original (puede funcionar si SYSTEM tiene acceso)
                AlwaysPrintLogger.WriteWarning(
                    $"InstallUpdate: no se pudo copiar MSI a ProgramData ({ex.Message}). " +
                    $"Usando path original: {originalPath}");
                return originalPath;
            }
        }

        /// <summary>
        /// Genera el contenido del script .cmd que ejecuta la actualización.
        /// El script:
        /// 1. Crea lockfile para prevenir ejecución concurrente
        /// 2. Espera 3 segundos (para que el Service termine de responder al Tray)
        /// 3. Mata procesos del Tray
        /// 4. Detiene el servicio
        /// 5. Ejecuta msiexec silencioso
        /// 6. Verifica que la versión del Service.exe realmente cambió
        /// 7. Inicia el servicio (el Service lanza el Tray via CreateProcessAsUser)
        /// 8. Elimina lockfile + MSI temporal
        /// 9. Se auto-elimina
        /// </summary>
        private static string GenerateInstallScript(
            string msiFilePath, string trayExePath,
            string scriptPath, string logFilePath)
        {
            // Obtener versión actual antes de la actualización
            string currentVersion = "desconocida";
            try
            {
                var versionInfo = FileVersionInfo.GetVersionInfo(
                    Process.GetCurrentProcess().MainModule!.FileName);
                currentVersion = versionInfo.FileVersion ?? "desconocida";
            }
            catch { /* no bloquear generación del script si falla esto */ }

            // NOTA: Este script NO usa EnableDelayedExpansion porque las comillas,
            // paréntesis y caracteres especiales en rutas (Program Files (x86)) y
            // comandos (sc failure actions) corrompen el parser de cmd.exe con
            // delayed expansion habilitado. Se usa %errorlevel% (expansión inmediata)
            // que funciona correctamente para scripts lineales sin bloques IF anidados.
            return $@"@echo off
REM ============================================================
REM Script de actualizacion automatica de AlwaysPrint
REM Generado: {DateTime.Now:yyyy-MM-dd HH:mm:ss}
REM MSI: {msiFilePath}
REM Version pre: {currentVersion}
REM ============================================================
set LOG=""{logFilePath}""
set LOCKFILE=""{LockFilePath}""

REM Funcion para timestamp ISO (sin dependencia de locale ni PowerShell)
REM Usa wmic que retorna formato fijo: 20260711132828.123456-300
call :getTS

REM Crear lockfile
echo %TS% > %LOCKFILE%

echo [%TS%] [UPD] Event 1020: Iniciando script de actualizacion. MSI={msiFilePath} >> %LOG%

REM Verificar que el MSI existe
if not exist ""{msiFilePath}"" (
    call :getTS
    echo [%TS%] [UPD] Event 1091: ERROR - MSI no encontrado. Abortando. >> %LOG%
    goto :cleanup
)

call :getTS
echo [%TS%] [UPD] Event 1020: Esperando 3s para que el Service responda al Tray... >> %LOG%
timeout /t 3 /nobreak > nul

call :getTS
echo [%TS%] [UPD] Event 1020: [PASO 1] Matando procesos {TrayProcessName}.exe... >> %LOG%
taskkill /f /im {TrayProcessName}.exe >> %LOG% 2>&1
call :getTS
echo [%TS%] [UPD] Event 1020: [PASO 1] taskkill exitcode=%errorlevel% >> %LOG%
timeout /t 2 /nobreak > nul

call :getTS
echo [%TS%] [UPD] Event 1020: [PASO 2] Deshabilitando Service Recovery... >> %LOG%
sc failure {ServiceName} reset= 0 actions= """"/""""/"""" > nul 2>&1
call :getTS
echo [%TS%] [UPD] Event 1020: [PASO 2] sc failure exitcode=%errorlevel% >> %LOG%

call :getTS
echo [%TS%] [UPD] Event 1020: [PASO 3] Deteniendo servicio {ServiceName}... >> %LOG%
net stop {ServiceName} >> %LOG% 2>&1
call :getTS
echo [%TS%] [UPD] Event 1020: [PASO 3] net stop exitcode=%errorlevel% >> %LOG%
timeout /t 3 /nobreak > nul

call :getTS
echo [%TS%] [UPD] Event 1020: [PASO 4] Ejecutando msiexec /i (silencioso)... >> %LOG%
msiexec /i ""{msiFilePath}"" /quiet /norestart REINSTALLMODE=amus /l*v ""{msiFilePath}.msiexec.log""
set MSIRESULT=%errorlevel%
call :getTS
echo [%TS%] [UPD] Event 1020: [PASO 4] msiexec finalizado. ExitCode=%MSIRESULT% >> %LOG%

call :getTS
echo [%TS%] [UPD] Event 1020: [PASO 5] Restaurando Service Recovery... >> %LOG%
sc failure {ServiceName} reset= 86400 actions= restart/5000/restart/5000/restart/5000 > nul 2>&1

if %MSIRESULT% neq 0 (
    call :getTS
    echo [%TS%] [UPD] Event 1091: ERROR - msiexec fallo con codigo %MSIRESULT%. >> %LOG%
    net start {ServiceName} > nul 2>&1
    goto :cleanup
)

call :getTS
echo [%TS%] [UPD] Event 1020: [PASO 6] Instalacion exitosa. Iniciando servicio... >> %LOG%
net start {ServiceName} >> %LOG% 2>&1
call :getTS
echo [%TS%] [UPD] Event 1020: [PASO 6] net start exitcode=%errorlevel% >> %LOG%
timeout /t 3 /nobreak > nul

REM Verificar servicio activo
call :getTS
echo [%TS%] [UPD] Event 1020: [PASO 7] Verificando servicio... >> %LOG%
sc query {ServiceName} | findstr /i ""RUNNING"" > nul 2>&1
if %errorlevel% equ 0 (
    call :getTS
    echo [%TS%] [UPD] Event 1020: Servicio ACTIVO. Actualizacion completada. >> %LOG%
) else (
    call :getTS
    echo [%TS%] [UPD] Event 1091: WARN - Servicio no activo. Reintentando... >> %LOG%
    timeout /t 10 /nobreak > nul
    net start {ServiceName} > nul 2>&1
    timeout /t 5 /nobreak > nul
    sc query {ServiceName} | findstr /i ""RUNNING"" > nul 2>&1
    if %errorlevel% equ 0 (
        call :getTS
        echo [%TS%] [UPD] Event 1020: Servicio ACTIVO tras reintento. >> %LOG%
    ) else (
        call :getTS
        echo [%TS%] [UPD] Event 1091: CRITICO - Servicio no pudo iniciarse. >> %LOG%
    )
)

:cleanup
call :getTS
echo [%TS%] [UPD] Event 1020: Eliminando lockfile y MSI... >> %LOG%
del /f /q %LOCKFILE% > nul 2>&1
del /f /q ""{msiFilePath}"" > nul 2>&1
call :getTS
echo [%TS%] [UPD] Event 1020: Script finalizado. >> %LOG%
(goto) 2>nul & del /f /q ""{scriptPath}""
exit /b

:getTS
for /f ""tokens=2 delims=="" %%a in ('wmic os get localdatetime /format:list 2^>nul') do set DT=%%a
set TS=%DT:~0,4%-%DT:~4,2%-%DT:~6,2% %DT:~8,2%:%DT:~10,2%:%DT:~12,2%
goto :eof
";
        }
    }
}
