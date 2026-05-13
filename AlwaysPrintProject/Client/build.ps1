#Requires -Version 5
<#
.SYNOPSIS
    Build completo de AlwaysPrint: limpieza, publicacion de proyectos y generacion del MSI.
    Ejecutar desde la carpeta Workstations/AlwaysPrint/.
#>

$ErrorActionPreference = 'Stop'

# ── Helpers ──────────────────────────────────────────────────────────────────

function Remove-IfExists {
    param([Parameter(Mandatory)][string]$Path, [switch]$Recurse)
    if (Test-Path -LiteralPath $Path) {
        Write-Host "Eliminando $Path ..."
        if ($Recurse) { Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue }
        else          { Remove-Item -LiteralPath $Path -Force         -ErrorAction SilentlyContinue }
    }
}

# ── 1. Limpieza ───────────────────────────────────────────────────────────────

Write-Host "=== Limpiando artefactos anteriores ===" -ForegroundColor Cyan
Remove-IfExists "dist"           -Recurse
Remove-IfExists ".wix"           -Recurse
Remove-IfExists "AlwaysPrint.wixpdb"
Remove-IfExists "AlwaysPrint.msi"
foreach ($proj in @("AlwaysPrint.Shared","AlwaysPrintService","AlwaysPrintTray")) {
    Remove-IfExists "$proj\bin" -Recurse
    Remove-IfExists "$proj\obj" -Recurse
}

# ── 1.5. Generar icono si no existe ──────────────────────────────────────────

if (-not (Test-Path "logo.ico") -and (Test-Path "logo.png")) {
    Write-Host "=== Generando logo.ico desde logo.png ===" -ForegroundColor Cyan
    .\convert-icon.ps1 | Out-Null
    if (-not (Test-Path "logo.ico")) {
        Write-Warning "No se pudo generar logo.ico. Los EXEs usaran icono por defecto."
    }
}

# ── 2. wix CLI ────────────────────────────────────────────────────────────────
# Se fija WiX 4.x (MIT license). WiX v5+ y v7 requieren aceptar la OSMF EULA
# (licencia de pago). No usar "dotnet tool update wix" sin version explicita
# porque instalaria v7 automaticamente.

Write-Host "=== Configurando wix CLI (v4) ===" -ForegroundColor Cyan

$wixVersion = "4.0.5"

# Desinstalar cualquier version incompatible (v5/v7) si esta presente
$installedWix = dotnet tool list --global 2>&1 | Select-String "^wix\s"
if ($installedWix) {
    $installedVersion = ($installedWix -split '\s+')[1]
    if ($installedVersion -and -not $installedVersion.StartsWith("4.")) {
        Write-Host "Desinstalando wix $installedVersion (incompatible, requiere EULA)..."
        dotnet tool uninstall --global wix | Out-Null
    }
}

# Instalar o actualizar a la version 4.x fijada
$currentWix = dotnet tool list --global 2>&1 | Select-String "^wix\s"
if ($currentWix) {
    Write-Host "wix ya instalado: $($currentWix.ToString().Trim())"
} else {
    Write-Host "Instalando wix $wixVersion..."
    dotnet tool install --global wix --version $wixVersion
    if ($LASTEXITCODE -ne 0) { Write-Error "No se pudo instalar wix CLI v$wixVersion."; exit 1 }
}

# Registrar extension con version explicita (idempotente — no falla si ya esta registrada)
# Se fija la misma version que el CLI para evitar que NuGet resuelva la v7 incompatible.
Write-Host "Registrando extension WixToolset.Util.wixext v$wixVersion..."
wix extension add "WixToolset.Util.wixext/$wixVersion" --global 2>&1 | Out-Host

# ── 3. Generar version basada en fecha/hora ──────────────────────────────────
# Formato ajustado a limites de MSI: Major.Minor.Build.Revision
# Limites de Windows Installer:
#   - Major < 256
#   - Minor < 256
#   - Build < 65536
#   - Revision < 65536 (ignorado por MSI, pero WiX lo valida)
#
# Esquema usado:
#   Major    = 1 (fijo)
#   Minor    = YY (ultimos 2 digitos del anio: 26 para 2026)
#   Build    = MMDD (mes y dia: 0426 para abril 26)
#   Revision = HHMM (hora y minuto: 1211 para 12:11)
#
# Ejemplo: 1.26.426.1211 = 26 de abril de 2026, 12:11
# Nota: Perdemos los segundos, pero ganamos version unica por minuto
#       que es suficiente para builds de desarrollo.

$now      = [DateTime]::Now
$major    = 1
$minor    = [int]$now.ToString("yy")        # 26 (anio 2026)
$build    = [int]$now.ToString("MMdd")      # 426 (abril 26)
$revision = [int]$now.ToString("HHmm")      # 1211 (12:11)
$version  = "$major.$minor.$build.$revision"
Write-Host "Version del paquete: $version ($($now.ToString('yyyy-MM-dd HH:mm')))"

# ── 4. Publicar AlwaysPrintService ────────────────────────────────────────────

Write-Host "=== Publicando AlwaysPrintService ===" -ForegroundColor Cyan
dotnet publish .\AlwaysPrintService\AlwaysPrintService.csproj `
    -c Release -f net48 -o .\dist --no-self-contained
if ($LASTEXITCODE -ne 0) { Write-Error "Fallo en publish de AlwaysPrintService."; exit 1 }

# ── 5. Publicar AlwaysPrintTray ───────────────────────────────────────────────

Write-Host "=== Publicando AlwaysPrintTray ===" -ForegroundColor Cyan
dotnet publish .\AlwaysPrintTray\AlwaysPrintTray.csproj `
    -c Release -f net48 -o .\dist --no-self-contained
if ($LASTEXITCODE -ne 0) { Write-Error "Fallo en publish de AlwaysPrintTray."; exit 1 }

# ── 6. Verificar archivos requeridos en dist\ ─────────────────────────────────

$required = @(
    "dist\AlwaysPrintService.exe",
    "dist\AlwaysPrintTray.exe",
    "dist\AlwaysPrint.Shared.dll",
    "dist\Newtonsoft.Json.dll"
)
foreach ($f in $required) {
    if (-not (Test-Path $f)) {
        Write-Error "Archivo requerido no encontrado en dist\: $f"
        exit 1
    }
}
Write-Host "Todos los archivos requeridos presentes en dist\." -ForegroundColor Green

# ── 7. Construir MSI ──────────────────────────────────────────────────────────

Write-Host "=== Compilando MSI (version $version) ===" -ForegroundColor Cyan
$projectDir = (Get-Location).Path + "\"
wix build .\Product.wxs `
    -o .\AlwaysPrint.msi `
    -ext WixToolset.Util.wixext `
    -d "ProductVersion=$version" `
    -d "ProjectDir=$projectDir"
if ($LASTEXITCODE -ne 0) { Write-Error "Fallo en build WiX."; exit 1 }

# ── Resumen ───────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host " Build completado correctamente" -ForegroundColor Green
Write-Host " Version : $version" -ForegroundColor Green
Write-Host " MSI     : $((Resolve-Path .\AlwaysPrint.msi).Path)" -ForegroundColor Green
Write-Host " Binarios: $((Resolve-Path .\dist).Path)" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
