# Script de reinstalacion completa de AlwaysPrint
# Autor: Robles.AI - Mayo 2026

# Auto-elevacion si no es administrador
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
$isAdmin = $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "`nEste script requiere permisos de Administrador." -ForegroundColor Yellow
    Write-Host "Solicitando elevacion...`n" -ForegroundColor Yellow
    
    $scriptPath = $MyInvocation.MyCommand.Path
    $arguments = "-NoProfile -ExecutionPolicy Bypass -NoExit -File `"$scriptPath`""
    
    try {
        Start-Process PowerShell.exe -Verb RunAs -ArgumentList $arguments
        exit
    } catch {
        Write-Host "Error al solicitar elevacion: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "Por favor, ejecute PowerShell como Administrador manualmente." -ForegroundColor Red
        Read-Host "Presione Enter para salir"
        exit 1
    }
}

$ErrorActionPreference = "Stop"
$OriginalLocation = Get-Location

function Write-Step {
    param([string]$Message, [string]$Type = "Info")
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    switch ($Type) {
        "Success" { Write-Host "[$ts] OK $Message" -ForegroundColor Green }
        "Error"   { Write-Host "[$ts] ERROR $Message" -ForegroundColor Red }
        "Warning" { Write-Host "[$ts] WARN $Message" -ForegroundColor Yellow }
        "Info"    { Write-Host "[$ts] INFO $Message" -ForegroundColor Cyan }
        default   { Write-Host "[$ts] $Message" }
    }
}

function Test-ProcessRunning {
    param([string]$ProcessName)
    return (Get-Process -Name $ProcessName -ErrorAction SilentlyContinue) -ne $null
}

function Test-ServiceExists {
    param([string]$ServiceName)
    return (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) -ne $null
}

try {
    Write-Host "`n========================================" -ForegroundColor Magenta
    Write-Host "  REINSTALACION DE ALWAYSPRINT" -ForegroundColor Magenta
    Write-Host "========================================`n" -ForegroundColor Magenta

    # PASO 1: Cerrar AlwaysPrintTray
    Write-Step "PASO 1: Cerrando aplicacion AlwaysPrintTray..." "Info"
    if (Test-ProcessRunning -ProcessName "AlwaysPrintTray") {
        Write-Step "Deteniendo proceso AlwaysPrintTray..." "Info"
        Stop-Process -Name "AlwaysPrintTray" -Force
        Start-Sleep -Seconds 2
        if (Test-ProcessRunning -ProcessName "AlwaysPrintTray") {
            throw "No se pudo detener AlwaysPrintTray"
        }
        Write-Step "AlwaysPrintTray cerrado exitosamente" "Success"
    } else {
        Write-Step "AlwaysPrintTray no esta en ejecucion" "Info"
    }

    # PASO 2: Detener servicio
    Write-Step "`nPASO 2: Deteniendo servicio AlwaysPrintService..." "Info"
    if (Test-ServiceExists -ServiceName "AlwaysPrintService") {
        $service = Get-Service -Name "AlwaysPrintService"
        if ($service.Status -eq "Running") {
            Write-Step "Deteniendo servicio..." "Info"
            Stop-Service -Name "AlwaysPrintService" -Force
            $timeout = 30; $elapsed = 0
            while ((Get-Service -Name "AlwaysPrintService").Status -ne "Stopped" -and $elapsed -lt $timeout) {
                Start-Sleep -Seconds 1; $elapsed++
            }
            if ((Get-Service -Name "AlwaysPrintService").Status -ne "Stopped") {
                throw "El servicio no se detuvo en el tiempo esperado"
            }
            Write-Step "Servicio detenido exitosamente" "Success"
        } else {
            Write-Step "El servicio ya esta detenido" "Info"
        }
    } else {
        Write-Step "El servicio AlwaysPrintService no existe" "Info"
    }

    # PASO 3: Eliminar registro
    Write-Step "`nPASO 3: Eliminando llaves del registro..." "Info"
    $registryPath = "HKLM:\Software\Robles.AI\AlwaysPrint"
    if (Test-Path $registryPath) {
        Write-Step "Eliminando $registryPath..." "Info"
        Remove-Item -Path $registryPath -Recurse -Force
        Write-Step "Llaves del registro eliminadas" "Success"
    } else {
        Write-Step "No se encontraron llaves del registro" "Info"
    }
    if (Test-Path $registryPath) {
        throw "Las llaves del registro no se eliminaron"
    }

    # PASO 4: Desinstalar MSI
    Write-Step "`nPASO 4: Desinstalando AlwaysPrint..." "Info"
    $uninstallPaths = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    $alwaysPrintProduct = $null
    foreach ($path in $uninstallPaths) {
        $alwaysPrintProduct = Get-ItemProperty $path -ErrorAction SilentlyContinue | 
            Where-Object { $_.DisplayName -like "*AlwaysPrint*" } | Select-Object -First 1
        if ($alwaysPrintProduct) { break }
    }
    if ($alwaysPrintProduct) {
        $productCode = $alwaysPrintProduct.PSChildName
        Write-Step "Producto: $($alwaysPrintProduct.DisplayName) v$($alwaysPrintProduct.DisplayVersion)" "Info"
        Write-Step "Ejecutando desinstalacion..." "Info"
        $uninstallLog = "$env:TEMP\AlwaysPrint_Uninstall_$(Get-Date -Format yyyyMMdd_HHmmss).log"
        $args = "/x `"$productCode`" /qn /norestart /L*V `"$uninstallLog`""
        $proc = Start-Process -FilePath "msiexec.exe" -ArgumentList $args -Wait -PassThru -NoNewWindow
        if ($proc.ExitCode -eq 0 -or $proc.ExitCode -eq 1605) {
            Write-Step "Desinstalacion completada (Exit: $($proc.ExitCode))" "Success"
        } else {
            Write-Step "Advertencia: Exit Code: $($proc.ExitCode)" "Warning"
            Write-Step "Log: $uninstallLog" "Info"
        }
        Start-Sleep -Seconds 3
    } else {
        Write-Step "AlwaysPrint no esta instalado" "Info"
    }

    # PASO 5: Eliminar logs
    Write-Step "`nPASO 5: Eliminando archivos de log..." "Info"
    $logPath = "C:\ProgramData\AlwaysPrint"
    if (Test-Path $logPath) {
        Write-Step "Eliminando $logPath..." "Info"
        Remove-Item -Path $logPath -Recurse -Force
        Write-Step "Archivos de log eliminados" "Success"
    } else {
        Write-Step "No se encontraron archivos de log" "Info"
    }
    if (Test-Path $logPath) {
        throw "Los archivos de log no se eliminaron"
    }

    # PASO 6: Verificar limpieza
    Write-Step "`nPASO 6: Verificando limpieza completa..." "Info"
    $issues = @()
    if (Test-ProcessRunning -ProcessName "AlwaysPrintTray") {
        $issues += "Proceso AlwaysPrintTray aun en ejecucion"
    }
    if (Test-ServiceExists -ServiceName "AlwaysPrintService") {
        $svc = Get-Service -Name "AlwaysPrintService"
        if ($svc.Status -eq "Running") {
            $issues += "Servicio AlwaysPrintService aun en ejecucion"
        }
    }
    if (Test-Path "HKLM:\Software\Robles.AI\AlwaysPrint") {
        $issues += "Llaves del registro aun presentes"
    }
    if (Test-Path "C:\ProgramData\AlwaysPrint") {
        $issues += "Archivos de log aun presentes"
    }
    $stillInstalled = $null
    foreach ($path in $uninstallPaths) {
        $stillInstalled = Get-ItemProperty $path -ErrorAction SilentlyContinue | 
            Where-Object { $_.DisplayName -like "*AlwaysPrint*" }
        if ($stillInstalled) { break }
    }
    if ($stillInstalled) {
        $issues += "Producto aun en Programas instalados"
    }
    if ($issues.Count -gt 0) {
        Write-Step "Se encontraron problemas:" "Warning"
        foreach ($issue in $issues) { Write-Step "  - $issue" "Warning" }
        throw "La limpieza no fue completa"
    }
    Write-Step "Verificacion completa: sistema limpio" "Success"

    # PASO 7: Git pull
    Write-Step "`nPASO 7: Actualizando codigo desde Git..." "Info"
    $repoPath = "C:\Dev\bbva-cpm-scripts"
    Set-Location $repoPath
    if (-not (Test-Path ".git")) {
        throw "No se encontro repositorio Git en $repoPath"
    }
    $beforeCommit = git rev-parse HEAD
    Write-Step "Commit actual: $beforeCommit" "Info"
    Write-Step "Ejecutando git pull..." "Info"
    $gitOutput = git pull 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Step "Error en git pull:" "Error"
        Write-Host $gitOutput -ForegroundColor Red
        throw "Git pull fallo con codigo $LASTEXITCODE"
    }
    Write-Step "Git pull completado" "Success"
    $afterCommit = git rev-parse HEAD
    $hasChanges = $beforeCommit -ne $afterCommit
    if ($hasChanges) {
        Write-Step "Se detectaron cambios (commit: $afterCommit)" "Info"
        $changedFiles = git diff --name-only $beforeCommit $afterCommit
        Write-Step "Archivos modificados:" "Info"
        $changedFiles | ForEach-Object { Write-Host "  - $_" -ForegroundColor Gray }
    } else {
        Write-Step "No se detectaron cambios" "Info"
    }

    # PASO 8: Compilar si hubo cambios
    Write-Step "`nPASO 8: Compilando proyecto..." "Info"
    $clientPath = Join-Path $repoPath "AlwaysPrintProject\Client"
    Set-Location $clientPath
    if ($hasChanges) {
        Write-Step "Compilando debido a cambios..." "Info"
        $buildScript = Join-Path $clientPath "build.ps1"
        if (-not (Test-Path $buildScript)) {
            throw "No se encontro build.ps1 en $clientPath"
        }
        Write-Step "Ejecutando build.ps1..." "Info"
        & $buildScript
        if ($LASTEXITCODE -ne 0) {
            throw "La compilacion fallo con codigo $LASTEXITCODE"
        }
        Write-Step "Compilacion completada" "Success"
    } else {
        Write-Step "Omitiendo compilacion (sin cambios)" "Info"
    }
    $msiPath = Join-Path $clientPath "AlwaysPrint.msi"
    if (-not (Test-Path $msiPath)) {
        throw "No se encontro el MSI en $msiPath"
    }
    $msiInfo = Get-Item $msiPath
    Write-Step "MSI: $($msiInfo.Name) ($([math]::Round($msiInfo.Length/1MB,2)) MB)" "Info"
    Write-Step "Modificado: $($msiInfo.LastWriteTime)" "Info"

    # PASO 8.5: Subir MSI a S3
    $s3Destination = "s3://alwaysprint-artifacts/latest/AlwaysPrint.msi"
    $s3HttpUrl = "https://alwaysprint-artifacts.s3.us-west-2.amazonaws.com/latest/AlwaysPrint.msi"
    Write-Step "`nPASO 8.5: Subiendo MSI al bucket S3..." "Info"
    Write-Step "Descarga: $s3HttpUrl" "Info"
    if ($hasChanges -and (Test-Path $msiPath)) {
        Write-Step "Preparando subida al bucket S3..." "Info"
        $buildDate = Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ"
        $shortCommit = $afterCommit.Substring(0, 7)
        $metadata = "version=$shortCommit,build-date=$buildDate,commit-hash=$afterCommit"

        try {
            Write-Step "Destino: $s3Destination" "Info"
            Write-Step "Metadata: version=$shortCommit, build-date=$buildDate" "Info"
            $s3Output = aws s3 cp $msiPath $s3Destination --metadata $metadata 2>&1
            if ($LASTEXITCODE -ne 0) {
                throw "aws s3 cp fallo con codigo $LASTEXITCODE`: $s3Output"
            }
            Write-Step "MSI subido exitosamente a S3" "Success"
        } catch {
            Write-Step "Error al subir MSI a S3: $($_.Exception.Message)" "Warning"
            $respuesta = Read-Host "¿Desea continuar con la instalacion? (S/N)"
            if ($respuesta -notin @("S", "s", "Si", "si", "SI")) {
                throw "Instalacion abortada por el usuario tras fallo de subida a S3"
            }
            Write-Step "Continuando sin subida a S3 por decision del usuario..." "Warning"
        }
    } else {
        if (-not $hasChanges) {
            Write-Step "Omitiendo subida a S3 (sin cambios detectados)" "Info"
        } else {
            Write-Step "Omitiendo subida a S3 (MSI no encontrado)" "Warning"
        }
    }

    # PASO 9: Instalar MSI
    Write-Step "`nPASO 9: Instalando AlwaysPrint..." "Info"
    $installLog = "$env:TEMP\AlwaysPrint_Install_$(Get-Date -Format yyyyMMdd_HHmmss).log"
    $args = "/i `"$msiPath`" /qn /norestart /L*V `"$installLog`""
    Write-Step "Ejecutando instalacion..." "Info"
    Write-Step "Log: $installLog" "Info"
    $proc = Start-Process -FilePath "msiexec.exe" -ArgumentList $args -Wait -PassThru -NoNewWindow
    if ($proc.ExitCode -eq 0) {
        Write-Step "Instalacion completada" "Success"
    } elseif ($proc.ExitCode -eq 3010) {
        Write-Step "Instalacion completada (requiere reinicio)" "Warning"
    } else {
        throw "Instalacion fallo con codigo $($proc.ExitCode). Ver: $installLog"
    }
    Start-Sleep -Seconds 3

    # VERIFICACION FINAL
    Write-Step "`nVERIFICACION FINAL..." "Info"
    if (Test-ServiceExists -ServiceName "AlwaysPrintService") {
        $svc = Get-Service -Name "AlwaysPrintService"
        Write-Step "Servicio: $($svc.Status)" "Success"
        if ($svc.Status -ne "Running") {
            Write-Step "Iniciando servicio..." "Info"
            Start-Service -Name "AlwaysPrintService"
            Start-Sleep -Seconds 2
            $svc = Get-Service -Name "AlwaysPrintService"
            Write-Step "Servicio iniciado: $($svc.Status)" "Success"
        }
    } else {
        Write-Step "Advertencia: Servicio no encontrado" "Warning"
    }
    $installedProduct = $null
    foreach ($path in $uninstallPaths) {
        $installedProduct = Get-ItemProperty $path -ErrorAction SilentlyContinue | 
            Where-Object { $_.DisplayName -like "*AlwaysPrint*" } | Select-Object -First 1
        if ($installedProduct) { break }
    }
    if ($installedProduct) {
        Write-Step "Producto: $($installedProduct.DisplayName)" "Success"
        Write-Step "Version: $($installedProduct.DisplayVersion)" "Success"
        Write-Step "Fabricante: $($installedProduct.Publisher)" "Success"
    } else {
        Write-Step "Advertencia: Producto no encontrado en registro" "Warning"
    }
    $programPath = "C:\Program Files\Robles.AI\AlwaysPrint"
    if (Test-Path $programPath) {
        $files = Get-ChildItem $programPath -File
        Write-Step "Archivos instalados: $($files.Count)" "Success"
    }

    Write-Host "`n========================================" -ForegroundColor Green
    Write-Host "  REINSTALACION COMPLETADA" -ForegroundColor Green
    Write-Host "========================================`n" -ForegroundColor Green
    Write-Step "Resumen:" "Info"
    Write-Step "  - Desinstalacion: Completada" "Success"
    Write-Step "  - Git pull: Completado" "Success"
    Write-Step "  - Compilacion: $(if ($hasChanges) {'Ejecutada'} else {'Omitida'})" "Success"
    Write-Step "  - Instalacion: Completada" "Success"
    if ($hasChanges) {
        Write-Host "`nCambios aplicados:" -ForegroundColor Cyan
        Write-Host "  Anterior: $beforeCommit" -ForegroundColor Gray
        Write-Host "  Actual: $afterCommit" -ForegroundColor Gray
    }
    exit 0
} catch {
    Write-Step "`nERROR: $($_.Exception.Message)" "Error"
    Write-Step "Linea: $($_.InvocationInfo.ScriptLineNumber)" "Error"
    Write-Host "`n========================================" -ForegroundColor Red
    Write-Host "  REINSTALACION FALLIDA" -ForegroundColor Red
    Write-Host "========================================`n" -ForegroundColor Red
    exit 1
} finally {
    Set-Location $OriginalLocation
}
