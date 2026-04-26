function Remove-IfExists {
    param([Parameter(Mandatory)][string]$Path, [switch]$Recurse)
    if (Test-Path -LiteralPath $Path) {
        Write-Host "Eliminando $Path ..."
        if ($Recurse) { Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue }
        else          { Remove-Item -LiteralPath $Path -Force         -ErrorAction SilentlyContinue }
    }
}

# 1) Limpieza
Remove-IfExists "dist"  -Recurse
Remove-IfExists ".wix"  -Recurse
Remove-IfExists "AlwaysPrint.wixpdb"
foreach ($proj in @("AlwaysPrint.Shared","AlwaysPrintService","AlwaysPrintTray")) {
    Remove-IfExists "$proj\bin" -Recurse
    Remove-IfExists "$proj\obj" -Recurse
}

# 2) wix CLI
Write-Host "Instalando/actualizando wix CLI..."
dotnet tool install --global wix | Out-Host
dotnet tool update  --global wix | Out-Host
wix extension add WixToolset.Util.wixext | Out-Host

# 3) Publicar Service (net48, framework-dependent, x64)
Write-Host "Publicando AlwaysPrintService..."
dotnet publish .\AlwaysPrintService\AlwaysPrintService.csproj `
    -c Release -f net48 -o .\dist --no-self-contained
if ($LASTEXITCODE -ne 0) { Write-Error "Fallo en publish de Service"; exit 1 }

# 4) Publicar Tray (misma carpeta — agrega AlwaysPrintTray.exe)
Write-Host "Publicando AlwaysPrintTray..."
dotnet publish .\AlwaysPrintTray\AlwaysPrintTray.csproj `
    -c Release -f net48 -o .\dist --no-self-contained
if ($LASTEXITCODE -ne 0) { Write-Error "Fallo en publish de Tray"; exit 1 }

# 5) Construir MSI
Write-Host "Compilando MSI..."
wix build .\Product.wxs -o .\AlwaysPrint.msi -ext WixToolset.Util.wixext
if ($LASTEXITCODE -ne 0) { Write-Error "Fallo en build WiX"; exit 1 }

Write-Host ""
Write-Host "Listo. Salida: .\AlwaysPrint.msi" -ForegroundColor Green
