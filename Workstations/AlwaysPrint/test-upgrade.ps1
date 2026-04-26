#Requires -Version 5
#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Script de prueba para verificar el sistema de upgrade automático de AlwaysPrint.
    
.DESCRIPTION
    Este script:
    1. Construye e instala la versión 1
    2. Espera 1 minuto
    3. Construye e instala la versión 2 (debe desinstalar automáticamente la versión 1)
    4. Verifica que solo la versión 2 está instalada
    5. Desinstala todo
#>

$ErrorActionPreference = 'Stop'

function Get-InstalledVersion {
    $product = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*" -ErrorAction SilentlyContinue |
               Where-Object { $_.DisplayName -eq "AlwaysPrint" } |
               Select-Object -First 1
    return $product
}

function Show-InstalledVersion {
    $product = Get-InstalledVersion
    if ($product) {
        Write-Host "  Instalado: AlwaysPrint v$($product.DisplayVersion)" -ForegroundColor Green
        Write-Host "  ProductCode: $($product.PSChildName)" -ForegroundColor Gray
    } else {
        Write-Host "  No hay ninguna version instalada" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Test de Upgrade Automatico" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Paso 1: Verificar estado inicial
Write-Host "[1/6] Verificando estado inicial..." -ForegroundColor Cyan
Show-InstalledVersion
Write-Host ""

# Paso 2: Construir e instalar versión 1
Write-Host "[2/6] Construyendo e instalando version 1..." -ForegroundColor Cyan
.\build.ps1 | Out-Null
$version1 = (Get-Content .\AlwaysPrint.msi | Select-String -Pattern "ProductVersion" -Context 0,0 | Select-Object -First 1).ToString()
Write-Host "  Build completado"
Write-Host "  Instalando..."
$result = Start-Process "msiexec.exe" -ArgumentList "/i `"$PSScriptRoot\AlwaysPrint.msi`" /qn /L*v `"$PSScriptRoot\install1.log`"" -Wait -PassThru
if ($result.ExitCode -ne 0) {
    Write-Error "Instalacion fallo con codigo: $($result.ExitCode)"
}
Start-Sleep -Seconds 2
Show-InstalledVersion
Write-Host ""

# Paso 3: Esperar 1 minuto para cambio de versión
Write-Host "[3/6] Esperando 61 segundos para cambio de version..." -ForegroundColor Cyan
for ($i = 61; $i -gt 0; $i--) {
    Write-Host "`r  Quedan $i segundos..." -NoNewline
    Start-Sleep -Seconds 1
}
Write-Host ""
Write-Host ""

# Paso 4: Construir e instalar versión 2
Write-Host "[4/6] Construyendo e instalando version 2..." -ForegroundColor Cyan
.\build.ps1 | Out-Null
Write-Host "  Build completado"
Write-Host "  Instalando (debe desinstalar automaticamente la version 1)..."
$result = Start-Process "msiexec.exe" -ArgumentList "/i `"$PSScriptRoot\AlwaysPrint.msi`" /qn /L*v `"$PSScriptRoot\install2.log`"" -Wait -PassThru
if ($result.ExitCode -ne 0) {
    Write-Error "Instalacion fallo con codigo: $($result.ExitCode)"
}
Start-Sleep -Seconds 2
Show-InstalledVersion
Write-Host ""

# Paso 5: Verificar que solo hay una versión instalada
Write-Host "[5/6] Verificando que el upgrade funciono correctamente..." -ForegroundColor Cyan
$allProducts = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*" -ErrorAction SilentlyContinue |
               Where-Object { $_.DisplayName -eq "AlwaysPrint" }
$count = ($allProducts | Measure-Object).Count
if ($count -eq 1) {
    Write-Host "  [OK] Solo hay 1 version instalada (correcto)" -ForegroundColor Green
} else {
    Write-Host "  [ERROR] Hay $count versiones instaladas (deberia ser 1)" -ForegroundColor Red
}
Write-Host ""

# Paso 6: Limpiar (desinstalar)
Write-Host "[6/6] Limpiando (desinstalando)..." -ForegroundColor Cyan
.\uninstall.ps1 | Out-Null
Start-Sleep -Seconds 2
Show-InstalledVersion
Write-Host ""

Write-Host "========================================" -ForegroundColor Green
Write-Host " Test completado" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Logs generados:" -ForegroundColor Cyan
Write-Host "  - install1.log (primera instalacion)"
Write-Host "  - install2.log (upgrade)"
Write-Host "  - uninstall.log (desinstalacion)"
Write-Host ""
