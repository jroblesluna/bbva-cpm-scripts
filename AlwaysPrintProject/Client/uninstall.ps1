#Requires -Version 5
#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Desinstala AlwaysPrint buscando el ProductCode registrado en Windows.
    Funciona independientemente de la versión instalada.
#>

$ErrorActionPreference = 'Stop'

Write-Host "=== Desinstalando AlwaysPrint ===" -ForegroundColor Cyan

# Buscar el ProductCode en el registro de Windows Installer
$uninstallPaths = @(
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
)

$product = $null
foreach ($path in $uninstallPaths) {
    $product = Get-ItemProperty $path -ErrorAction SilentlyContinue |
               Where-Object { $_.DisplayName -eq "AlwaysPrint" } |
               Select-Object -First 1
    if ($product) { break }
}

if (-not $product) {
    Write-Host "AlwaysPrint no está instalado." -ForegroundColor Yellow
    exit 0
}

$productCode = $product.PSChildName
Write-Host "Encontrado: $($product.DisplayName) v$($product.DisplayVersion) — ProductCode: $productCode"
Write-Host "Desinstalando..."

$result = Start-Process "msiexec.exe" -ArgumentList "/x `"$productCode`" /qn /L*v `"$PSScriptRoot\uninstall.log`"" -Wait -PassThru
if ($result.ExitCode -eq 0) {
    Write-Host "Desinstalación completada correctamente." -ForegroundColor Green
} else {
    Write-Error "Desinstalación falló con código: $($result.ExitCode). Ver uninstall.log para detalles."
}
