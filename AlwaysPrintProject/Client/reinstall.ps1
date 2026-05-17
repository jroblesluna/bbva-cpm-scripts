#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Script de reinstalacion completa de AlwaysPrint
.DESCRIPTION
    Desinstala completamente AlwaysPrint, actualiza el codigo desde Git,
    recompila si hay cambios y reinstala la nueva version.
.NOTES
    Debe ejecutarse como Administrador
    Autor: Robles.AI
    Fecha: Mayo 2026
#>

# Configuracion
$ErrorActionPreference = 'Stop'
$OriginalLocation = Get-Location

# Funcion para logging con colores
function Write-Step {
    param(
        [string]$Message,
        [string]$Type = 'Info'
    )
    
    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    
    switch ($Type) {
        'Success' { Write-Host "[$timestamp] OK $Message" -ForegroundColor Green }
        'Error'   { Write-Host "[$timestamp] ERROR $Message" -ForegroundColor Red }
        'Warning' { Write-Host "[$timestamp] WARN $Message" -ForegroundColor Yellow }
        'Info'    { Write-Host "[$timestamp] INFO $Message" -ForegroundColor Cyan }
        default   { Write-Host "[$timestamp] $Message" }
    }
}

# Funcion para verificar si un proceso esta en ejecucion
function Test-ProcessRunning {
    param([string]$ProcessName)
    return (Get-Process -Name $ProcessName -ErrorAction SilentlyContinue) -ne $null
}

# Funcion para verificar si un servicio existe
function Test-ServiceExists {
    param([string]$ServiceName)
    return (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) -ne $null
}

try {
    Write-Host "`n========================================" -ForegroundColor Magenta
    Write-Host "  REINSTALACION DE ALWAYSPRINT" -ForegroundColor Magenta
    Write-Host "========================================`n" -ForegroundColor Magenta

    # PASO 1: Cerrar AlwaysPrintTray
    Write-Step 'PASO 1: Cerrando aplicacion AlwaysPrintTray...' 'Info'
    
    if (Test-ProcessRunning -ProcessName 'AlwaysPrintTray') {
        Write-Step 'Deteniendo proceso AlwaysPrintTray...' 'Info'
        Stop-Process -Name 'AlwaysPrintTray' -Force -ErrorAction Stop
        Start-Sleep -Seconds 2
        
        if (Test-ProcessRunning -ProcessName 'AlwaysPrintTray') {
            throw 'No se pudo detener AlwaysPrintTray'
        }
        Write-Step 'AlwaysPrintTray cerrado exitosamente' 'Success'
    } else {
        Write-Step 'AlwaysPrintTray no esta en ejecucion' 'Info'
    }

    # PASO 2: Detener servicio AlwaysPrintService
    Write-Step "`nPASO 2: Deteniendo servicio AlwaysPrintService..." 'Info'
    
    if (Test-ServiceExists -ServiceName 'AlwaysPrintService') {
        $service = Get-Service -Name 'AlwaysPrintService'
        
        if ($service.Status -eq 'Running') {
            Write-Step 'Deteniendo servicio...' 'Info'
            Stop-Service -Name 'AlwaysPrintService' -Force -ErrorAction Stop
            
            $timeout = 30
            $elapsed = 0
            while ((Get-Service -Name 'AlwaysPrintService').Status -ne 'Stopped' -and $elapsed -lt $timeout) {
                Start-Sleep -Seconds 1
                $elapsed++
            }
            
            if ((Get-Service -Name 'AlwaysPrintService').Status -ne 'Stopped') {
                throw 'El servicio no se detuvo en el tiempo esperado'
            }
            Write-Step 'Servicio detenido exitosamente' 'Success'
        } else {
            Write-Step 'El servicio ya esta detenido' 'Info'
        }
    } else {
        Write-Step 'El servicio AlwaysPrintService no existe' 'Info'
    }

    # PASO 3: Eliminar llaves del registro
    Write-Step "`nPASO 3: Eliminando llaves del registro..." 'Info'
    
    $registryPath = 'HKLM:\Software\Robles.AI\AlwaysPrint'
    
    if (Test-Path $registryPath) {
        Write-Step "Eliminando $registryPath..." 'Info'
        Remove-Item -Path $registryPath -Recurse -Force -ErrorAction Stop
        Write-Step 'Llaves del registro eliminadas exitosamente' 'Success'
    } else {
        Write-Step 'No se encontraron llaves del registro' 'Info'
    }
    
    if (Test-Path $registryPath) {
        throw 'Las llaves del registro no se eliminaron correctamente'
    }

    # PASO 4: Desinstalar producto via MSI
    Write-Step "`nPASO 4: Desinstalando AlwaysPrint..." 'Info'
    
    $uninstallPaths = @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )
    
    $alwaysPrintProduct = $null
    foreach ($path in $uninstallPaths) {
        $alwaysPrintProduct = Get-ItemProperty $path -ErrorAction SilentlyContinue | 
            Where-Object { $_.DisplayName -like '*AlwaysPrint*' } | 
            Select-Object -First 1
        
        if ($alwaysPrintProduct) { break }
    }
    
    if ($alwaysPrintProduct) {
        $productCode = $alwaysPrintProduct.PSChildName
        Write-Step "Producto encontrado: $($alwaysPrintProduct.DisplayName) (v$($alwaysPrintProduct.DisplayVersion))" 'Info'
        Write-Step "ProductCode: $productCode" 'Info'
        
        Write-Step 'Ejecutando desinstalacion...' 'Info'
        $uninstallLog = "$env:TEMP\AlwaysPrint_Uninstall_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
        $arguments = "/x `"$productCode`" /qn /norestart /L*V `"$uninstallLog`""
        
        $process = Start-Process -FilePath 'msiexec.exe' -ArgumentList $arguments -Wait -PassThru -NoNewWindow
        
        if ($process.ExitCode -eq 0 -or $process.ExitCode -eq 1605) {
            Write-Step "Desinstalacion completada (Exit Code: $($process.ExitCode))" 'Success'
        } else {
            Write-Step "Advertencia: Exit Code de desinstalacion: $($process.ExitCode)" 'Warning'
            Write-Step "Log de desinstalacion: $uninstallLog" 'Info'
        }
        
        Start-Sleep -Seconds 3
    } else {
        Write-Step 'AlwaysPrint no esta instalado en el sistema' 'Info'
    }

    # PASO 5: Eliminar archivos de log
    Write-Step "`nPASO 5: Eliminando archivos de log..." 'Info'
    
    $logPath = 'C:\ProgramData\AlwaysPrint'
    
    if (Test-Path $logPath) {
        Write-Step "Eliminando $logPath..." 'Info'
        Remove-Item -Path $logPath -Recurse -Force -ErrorAction Stop
        Write-Step 'Archivos de log eliminados exitosamente' 'Success'
    } else {
        Write-Step 'No se encontraron archivos de log' 'Info'
    }
    
    if (Test-Path $logPath) {
        throw 'Los archivos de log no se eliminaron correctamente'
    }

    # PASO 6: Verificar que no quedan rastros
    Write-Step "`nPASO 6: Verificando limpieza completa..." 'Info'
    
    $issues = @()
    
    if (Test-ProcessRunning -ProcessName 'AlwaysPrintTray') {
        $issues += 'Proceso AlwaysPrintTray aun en ejecucion'
    }
    
    if (Test-ServiceExists -ServiceName 'AlwaysPrintService') {
        $service = Get-Service -Name 'AlwaysPrintService'
        if ($service.Status -eq 'Running') {
            $issues += 'Servicio AlwaysPrintService aun en ejecucion'
        }
    }
    
    if (Test-Path 'HKLM:\Software\Robles.AI\AlwaysPrint') {
        $issues += 'Llaves del registro aun presentes'
    }
    
    if (Test-Path 'C:\ProgramData\AlwaysPrint') {
        $issues += 'Archivos de log aun presentes'
    }
    
    $stillInstalled = $null
    foreach ($path in $uninstallPaths) {
        $stillInstalled = Get-ItemProperty $path -ErrorAction SilentlyContinue | 
            Where-Object { $_.DisplayName -like '*AlwaysPrint*' }
        if ($stillInstalled) { break }
    }
    
    if ($stillInstalled) {
        $issues += 'Producto aun aparece en Programas instalados'
    }
    
    if ($issues.Count -gt 0) {
        Write-Step 'Se encontraron problemas:' 'Warning'
        foreach ($issue in $issues) {
            Write-Step "  - $issue" 'Warning'
        }
        throw 'La limpieza no fue completa'
    }
    
    Write-Step 'Verificacion completa: sistema limpio OK' 'Success'

    # PASO 7: Git pull
    Write-Step "`nPASO 7: Actualizando codigo desde Git..." 'Info'
    
    $repoPath = 'C:\Dev\bbva-cpm-scripts'
    Set-Location $repoPath
    
    if (-not (Test-Path '.git')) {
        throw "No se encontro repositorio Git en $repoPath"
    }
    
    $beforeCommit = git rev-parse HEAD
    Write-Step "Commit actual: $beforeCommit" 'Info'
    
    Write-Step 'Ejecutando git pull...' 'Info'
    $gitOutput = git pull 2>&1
    
    if ($LASTEXITCODE -ne 0) {
        Write-Step 'Error en git pull:' 'Error'
        Write-Host $gitOutput -ForegroundColor Red
        throw "Git pull fallo con codigo de salida $LASTEXITCODE"
    }
    
    Write-Step 'Git pull completado' 'Success'
    
    $afterCommit = git rev-parse HEAD
    $hasChanges = $beforeCommit -ne $afterCommit
    
    if ($hasChanges) {
        Write-Step "Se detectaron cambios (nuevo commit: $afterCommit)" 'Info'
        
        $changedFiles = git diff --name-only $beforeCommit $afterCommit
        Write-Step 'Archivos modificados:' 'Info'
        $changedFiles | ForEach-Object { Write-Host "  - $_" -ForegroundColor Gray }
    } else {
        Write-Step 'No se detectaron cambios en el repositorio' 'Info'
    }

    # PASO 8: Compilar si hubo cambios
    Write-Step "`nPASO 8: Compilando proyecto..." 'Info'
    
    $clientPath = Join-Path $repoPath 'AlwaysPrintProject\Client'
    Set-Location $clientPath
    
    if ($hasChanges) {
        Write-Step 'Compilando debido a cambios detectados...' 'Info'
        
        $buildScript = Join-Path $clientPath 'build.ps1'
        if (-not (Test-Path $buildScript)) {
            throw "No se encontro el script build.ps1 en $clientPath"
        }
        
        Write-Step 'Ejecutando build.ps1...' 'Info'
        & $buildScript
        
        if ($LASTEXITCODE -ne 0) {
            throw "La compilacion fallo con codigo de salida $LASTEXITCODE"
        }
        
        Write-Step 'Compilacion completada exitosamente' 'Success'
    } else {
        Write-Step 'Omitiendo compilacion (no hubo cambios)' 'Info'
    }
    
    $msiPath = Join-Path $clientPath 'AlwaysPrint.msi'
    if (-not (Test-Path $msiPath)) {
        throw "No se encontro el archivo MSI en $msiPath"
    }
    
    $msiInfo = Get-Item $msiPath
    Write-Step "MSI encontrado: $($msiInfo.Name) ($([math]::Round($msiInfo.Length / 1MB, 2)) MB)" 'Info'
    Write-Step "Ultima modificacion: $($msiInfo.LastWriteTime)" 'Info'

    # PASO 9: Instalar nuevo MSI
    Write-Step "`nPASO 9: Instalando AlwaysPrint..." 'Info'
    
    $installLog = "$env:TEMP\AlwaysPrint_Install_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
    $arguments = "/i `"$msiPath`" /qn /norestart /L*V `"$installLog`""
    
    Write-Step 'Ejecutando instalacion...' 'Info'
    Write-Step "Log de instalacion: $installLog" 'Info'
    
    $process = Start-Process -FilePath 'msiexec.exe' -ArgumentList $arguments -Wait -PassThru -NoNewWindow
    
    if ($process.ExitCode -eq 0) {
        Write-Step 'Instalacion completada exitosamente' 'Success'
    } elseif ($process.ExitCode -eq 3010) {
        Write-Step 'Instalacion completada (requiere reinicio)' 'Warning'
    } else {
        throw "La instalacion fallo con codigo de salida $($process.ExitCode). Ver log: $installLog"
    }
    
    Start-Sleep -Seconds 3

    # VERIFICACION FINAL
    Write-Step "`nVERIFICACION FINAL..." 'Info'
    
    if (Test-ServiceExists -ServiceName 'AlwaysPrintService') {
        $service = Get-Service -Name 'AlwaysPrintService'
        Write-Step "Servicio AlwaysPrintService: $($service.Status)" 'Success'
        
        if ($service.Status -ne 'Running') {
            Write-Step 'Iniciando servicio...' 'Info'
            Start-Service -Name 'AlwaysPrintService'
            Start-Sleep -Seconds 2
            $service = Get-Service -Name 'AlwaysPrintService'
            Write-Step "Servicio iniciado: $($service.Status)" 'Success'
        }
    } else {
        Write-Step 'Advertencia: Servicio no encontrado despues de la instalacion' 'Warning'
    }
    
    $installedProduct = $null
    foreach ($path in $uninstallPaths) {
        $installedProduct = Get-ItemProperty $path -ErrorAction SilentlyContinue | 
            Where-Object { $_.DisplayName -like '*AlwaysPrint*' } | 
            Select-Object -First 1
        if ($installedProduct) { break }
    }
    
    if ($installedProduct) {
        Write-Step "Producto instalado: $($installedProduct.DisplayName)" 'Success'
        Write-Step "Version: $($installedProduct.DisplayVersion)" 'Success'
        Write-Step "Fabricante: $($installedProduct.Publisher)" 'Success'
    } else {
        Write-Step 'Advertencia: Producto no encontrado en el registro' 'Warning'
    }
    
    $programPath = 'C:\Program Files\Robles.AI\AlwaysPrint'
    if (Test-Path $programPath) {
        $files = Get-ChildItem $programPath -File
        Write-Step "Archivos instalados en $programPath`: $($files.Count)" 'Success'
    }

    Write-Host "`n========================================" -ForegroundColor Green
    Write-Host "  OK REINSTALACION COMPLETADA" -ForegroundColor Green
    Write-Host "========================================`n" -ForegroundColor Green
    
    Write-Step 'Resumen:' 'Info'
    Write-Step '  - Desinstalacion: Completada' 'Success'
    Write-Step '  - Git pull: Completado' 'Success'
    Write-Step "  - Compilacion: $(if ($hasChanges) { 'Ejecutada' } else { 'Omitida (sin cambios)' })" 'Success'
    Write-Step '  - Instalacion: Completada' 'Success'
    
    if ($hasChanges) {
        Write-Host "`nCambios aplicados desde commit:" -ForegroundColor Cyan
        Write-Host "  Anterior: $beforeCommit" -ForegroundColor Gray
        Write-Host "  Actual:   $afterCommit" -ForegroundColor Gray
    }

    exit 0

} catch {
    Write-Step "`nERROR: $($_.Exception.Message)" 'Error'
    Write-Step "Linea: $($_.InvocationInfo.ScriptLineNumber)" 'Error'
    
    Write-Host "`n========================================" -ForegroundColor Red
    Write-Host "  ERROR REINSTALACION FALLIDA" -ForegroundColor Red
    Write-Host "========================================`n" -ForegroundColor Red
    
    exit 1
} finally {
    Set-Location $OriginalLocation
}
