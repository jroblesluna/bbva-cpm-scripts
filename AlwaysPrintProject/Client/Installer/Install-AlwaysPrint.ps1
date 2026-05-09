#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Installs AlwaysPrint service and tray application.
.DESCRIPTION
    Copies binaries to Program Files, registers the Windows Service,
    configures Event Log source, sets SCM recovery actions, and starts the service.
.PARAMETER BinDir
    Path to the compiled output directory (e.g., .\Release\net48\).
#>

param(
    [Parameter(Mandatory=$false)]
    [string]$BinDir = "$PSScriptRoot\..\publish"
)

$ErrorActionPreference = 'Stop'

$InstallDir  = "$env:ProgramFiles\Robles.AI\AlwaysPrint"
$ServiceName = "AlwaysPrintService"
$ServiceExe  = "$InstallDir\AlwaysPrintService.exe"
$EventSource = "AlwaysPrint"

Write-Host "=== AlwaysPrint Installer ===" -ForegroundColor Cyan

# ── 1. Stop existing service ─────────────────────────────────────────────────
if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
    Write-Host "Stopping existing service..."
    Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Write-Host "Removing existing service..."
    sc.exe delete $ServiceName | Out-Null
    Start-Sleep -Seconds 1
}

# ── 2. Kill orphaned Tray instances ──────────────────────────────────────────
Get-Process -Name "AlwaysPrintTray" -ErrorAction SilentlyContinue | Stop-Process -Force

# ── 3. Copy binaries ─────────────────────────────────────────────────────────
Write-Host "Installing to $InstallDir..."
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null

$required = @("AlwaysPrintService.exe","AlwaysPrintTray.exe","AlwaysPrint.Shared.dll","Newtonsoft.Json.dll")
foreach ($f in $required) {
    $src = Join-Path $BinDir $f
    if (-not (Test-Path $src)) {
        Write-Error "Required file not found: $src"
        exit 1
    }
}

Copy-Item -Path "$BinDir\*" -Destination $InstallDir -Recurse -Force
Write-Host "Files copied." -ForegroundColor Green

# ── 4. Register Event Log source ─────────────────────────────────────────────
if (-not [System.Diagnostics.EventLog]::SourceExists($EventSource)) {
    [System.Diagnostics.EventLog]::CreateEventSource($EventSource, "Application")
    Write-Host "Event Log source '$EventSource' registered."
}

# ── 5. Register the service ───────────────────────────────────────────────────
Write-Host "Registering service '$ServiceName'..."
sc.exe create $ServiceName `
    binPath= "`"$ServiceExe`"" `
    start= auto `
    obj= LocalSystem `
    DisplayName= "AlwaysPrint Service" | Out-Null

sc.exe description $ServiceName "Manages corporate print queues for AlwaysPrint (Robles.AI)." | Out-Null

# ── 6. Set SCM failure/recovery actions ──────────────────────────────────────
# On first failure: restart after 60 s.
# On second failure: restart after 120 s.
# On subsequent failures: restart after 300 s.
sc.exe failure $ServiceName reset= 86400 actions= restart/60000/restart/120000/restart/300000 | Out-Null
Write-Host "Recovery actions configured." -ForegroundColor Green

# ── 7. Start the service ──────────────────────────────────────────────────────
Write-Host "Starting service..."
Start-Service -Name $ServiceName
Start-Sleep -Seconds 3

$svc = Get-Service -Name $ServiceName
if ($svc.Status -eq 'Running') {
    Write-Host "Service is running." -ForegroundColor Green
} else {
    Write-Warning "Service status: $($svc.Status). Check Event Log for details."
}

Write-Host ""
Write-Host "Installation complete." -ForegroundColor Cyan
Write-Host "Event Log source : $EventSource"
Write-Host "Install directory: $InstallDir"
Write-Host "Service name     : $ServiceName"
