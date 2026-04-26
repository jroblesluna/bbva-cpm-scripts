function Remove-IfExists {
    param(
        [Parameter(Mandatory)]
        [string]$Path,
        [switch]$Recurse
    )
    if (Test-Path -LiteralPath $Path) {
        Write-Host "Eliminando $Path ..." 
        if ($Recurse) {
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue
        } else {
            Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
        }
    } else {
        Write-Host "No existe: $Path (ok)"
    }
}

# 1) Limpieza
Remove-IfExists ".wix" -Recurse
Remove-IfExists "bin" -Recurse
Remove-IfExists "obj" -Recurse
Remove-IfExists "dist" -Recurse
Remove-IfExists "test" -Recurse
Remove-IfExists ".\LpdServiceMonitor.wixpdb"

# 2) Asegurar que 'wix' CLI está disponible (dotnet tool global)
#    Nota: requiere que %USERPROFILE%\.dotnet\tools esté en PATH
Write-Host "Instalando/actualizando wix CLI..."
dotnet tool install --global wix | Out-Host
dotnet tool update  --global wix | Out-Host

# 3) Añadir extensión de Util (crea .wix si no existe)
Write-Host "Registrando extensión WixToolset.Util.wixext..."
wix extension add WixToolset.Util.wixext | Out-Host

# 4) Publicar el ejecutable self-contained (win-x64)
Write-Host "Publicando .NET..."
dotnet publish .\LpdServiceMonitor.csproj `
  -c Release -r win-x64 `
  -p:PublishSingleFile=true `
  -p:SelfContained=true `
  -p:IncludeNativeLibrariesForSelfExtract=true `
  -p:EnableCompressionInSingleFile=true `
  -p:PublishTrimmed=false `
  -o .\dist

# 5) Construir el MSI con WiX
Write-Host "Compilando MSI..."
wix build .\Product.wxs -o .\LpdServiceMonitor.msi -ext WixToolset.Util.wixext

Write-Host "Listo. Salida: .\LpdServiceMonitor.msi"