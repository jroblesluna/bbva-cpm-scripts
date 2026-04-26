#Requires -Version 5
<#
.SYNOPSIS
    Build completo de AlwaysPrint: limpieza, publicación de proyectos y generación del MSI.
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

# ── 2. wix CLI ────────────────────────────────────────────────────────────────
# Intenta actualizar primero; si falla (no instalado), instala desde cero.

Write-Host "=== Configurando wix CLI ===" -ForegroundColor Cyan
$wixUpdateOutput = dotnet tool update --global wix 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "wix no estaba instalado, instalando..."
    dotnet tool install --global wix
    if ($LASTEXITCODE -ne 0) { Write-Error "No se pudo instalar wix CLI."; exit 1 }
} else {
    Write-Host $wixUpdateOutput
}

# Registrar extensión (idempotente — no falla si ya está registrada)
wix extension add WixToolset.Util.wixext --global 2>&1 | Out-Host

# ── 3. Leer versión del assembly del servicio ─────────────────────────────────
# Extrae la versión de AssemblyInfo o del .csproj para inyectarla en el MSI.
# Si no se encuentra, usa 1.0.0 como fallback.

$version = "1.0.0"
$csprojPath = "AlwaysPrintService\AlwaysPrintService.csproj"
if (Test-Path $csprojPath) {
    $xml = [xml](Get-Content $csprojPath -Raw)
    $ver = $xml.Project.PropertyGroup.Version | Where-Object { $_ } | Select-Object -First 1
    if ($ver) { $version = $ver.Trim() }
}
Write-Host "Versión del paquete: $version"

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

Write-Host "=== Compilando MSI (versión $version) ===" -ForegroundColor Cyan
wix build .\Product.wxs `
    -o .\AlwaysPrint.msi `
    -ext WixToolset.Util.wixext `
    -d "ProductVersion=$version"
if ($LASTEXITCODE -ne 0) { Write-Error "Fallo en build WiX."; exit 1 }

# ── Resumen ───────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host " Build completado correctamente" -ForegroundColor Green
Write-Host " Versión : $version" -ForegroundColor Green
Write-Host " MSI     : $((Resolve-Path .\AlwaysPrint.msi).Path)" -ForegroundColor Green
Write-Host " Binarios: $((Resolve-Path .\dist).Path)" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
