#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$ServiceName = "AlwaysPrintService"
$InstallDir  = "$env:ProgramFiles\Robles.AI\AlwaysPrint"

Write-Host "=== AlwaysPrint Uninstaller ===" -ForegroundColor Yellow

Get-Process -Name "AlwaysPrintTray" -ErrorAction SilentlyContinue | Stop-Process -Force

if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
    Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
    sc.exe delete $ServiceName | Out-Null
    Write-Host "Service removed."
}

if (Test-Path $InstallDir) {
    Remove-Item -Path $InstallDir -Recurse -Force
    Write-Host "Files removed from $InstallDir."
}

Write-Host "Uninstallation complete." -ForegroundColor Yellow
