#Requires -Version 5
<#
.SYNOPSIS
    Script de prueba para verificar que el sistema de versionado genera versiones únicas.
#>

$ErrorActionPreference = 'Stop'

Write-Host "=== Prueba de Sistema de Versionado ===" -ForegroundColor Cyan
Write-Host ""

# Función para generar versión (copiada de build.ps1)
function Get-AlwaysPrintVersion {
    $now      = [DateTime]::Now
    $major    = 1
    $minor    = [int]$now.ToString("yy")        # 26 (año 2026)
    $build    = [int]$now.ToString("MMdd")      # 426 (abril 26)
    $revision = [int]$now.ToString("HHmm")      # 1211 (12:11)
    $version  = "$major.$minor.$build.$revision"
    
    return @{
        Version = $version
        DateTime = $now.ToString('yyyy-MM-dd HH:mm')
    }
}

# Generar 3 versiones con intervalos de 1 minuto
Write-Host "Nota: Este test toma ~2 minutos porque la version tiene resolucion de 1 minuto"
Write-Host ""
$versions = @()
for ($i = 1; $i -le 3; $i++) {
    $result = Get-AlwaysPrintVersion
    $versions += $result
    Write-Host "Build $i : $($result.Version) ($($result.DateTime))"
    
    if ($i -lt 3) {
        Write-Host "  Esperando 61 segundos para cambio de minuto..."
        Start-Sleep -Seconds 61
    }
}

Write-Host ""
Write-Host "=== Verificacion ===" -ForegroundColor Cyan

# Verificar que todas las versiones son diferentes
$uniqueVersions = ($versions | ForEach-Object { $_.Version } | Select-Object -Unique)
if ($uniqueVersions.Count -eq $versions.Count) {
    Write-Host "[OK] EXITO: Todas las versiones son unicas ($($versions.Count) builds)" -ForegroundColor Green
} else {
    Write-Host "[ERROR] Se encontraron versiones duplicadas" -ForegroundColor Red
    Write-Host "  Versiones unicas: $($uniqueVersions.Count) de $($versions.Count)" -ForegroundColor Red
    Write-Host "  Nota: La version tiene resolucion de 1 minuto. Builds en el mismo minuto tendran la misma version." -ForegroundColor Yellow
}

# Verificar que las versiones son crecientes
$sorted = $true
for ($i = 1; $i -lt $versions.Count; $i++) {
    $prev = [Version]$versions[$i-1].Version
    $curr = [Version]$versions[$i].Version
    if ($curr -le $prev) {
        $sorted = $false
        Write-Host "[ERROR] Version $curr no es mayor que $prev" -ForegroundColor Red
    }
}

if ($sorted) {
    Write-Host "[OK] EXITO: Las versiones son estrictamente crecientes" -ForegroundColor Green
} else {
    Write-Host "[ERROR] Las versiones no son estrictamente crecientes" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== Informacion Adicional ===" -ForegroundColor Cyan
$now = Get-AlwaysPrintVersion
Write-Host "Version actual: $($now.Version)"
Write-Host "Fecha/Hora: $($now.DateTime)"
