#Requires -Version 5
<#
.SYNOPSIS
    Convierte logo.png a logo.ico para usar como icono de aplicación.
    
.DESCRIPTION
    Este script convierte el archivo logo.png a formato .ico con múltiples tamaños
    (16x16, 32x32, 48x48, 256x256) para que se vea bien en diferentes contextos.
#>

$ErrorActionPreference = 'Stop'

Write-Host "=== Convirtiendo logo.png a logo.ico ===" -ForegroundColor Cyan

# Verificar que existe logo.png
if (-not (Test-Path "logo.png")) {
    Write-Error "No se encontró logo.png en el directorio actual"
}

# Cargar System.Drawing
Add-Type -AssemblyName System.Drawing

# Cargar la imagen PNG
$png = [System.Drawing.Image]::FromFile((Resolve-Path "logo.png").Path)
Write-Host "Imagen cargada: $($png.Width)x$($png.Height) pixels"

# Crear iconos en diferentes tamaños
$sizes = @(16, 32, 48, 256)
$bitmaps = @()

foreach ($size in $sizes) {
    Write-Host "  Generando icono ${size}x${size}..."
    $bitmap = New-Object System.Drawing.Bitmap($size, $size)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $graphics.DrawImage($png, 0, 0, $size, $size)
    $graphics.Dispose()
    $bitmaps += $bitmap
}

# Guardar como .ico
$iconPath = Join-Path $PSScriptRoot "logo.ico"
$stream = [System.IO.FileStream]::new($iconPath, [System.IO.FileMode]::Create)

try {
    # Escribir header del ICO
    $writer = [System.IO.BinaryWriter]::new($stream)
    $writer.Write([uint16]0)  # Reserved
    $writer.Write([uint16]1)  # Type (1 = ICO)
    $writer.Write([uint16]$bitmaps.Count)  # Number of images
    
    # Calcular offsets
    $offset = 6 + ($bitmaps.Count * 16)  # Header + directory entries
    
    # Escribir directory entries
    foreach ($bitmap in $bitmaps) {
        $ms = New-Object System.IO.MemoryStream
        $bitmap.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
        $imageData = $ms.ToArray()
        $ms.Dispose()
        
        # En formato ICO, 256 se representa como 0
        $width = if ($bitmap.Width -eq 256) { 0 } else { $bitmap.Width }
        $height = if ($bitmap.Height -eq 256) { 0 } else { $bitmap.Height }
        
        $writer.Write([byte]$width)          # Width (0 = 256)
        $writer.Write([byte]$height)         # Height (0 = 256)
        $writer.Write([byte]0)               # Color palette
        $writer.Write([byte]0)               # Reserved
        $writer.Write([uint16]1)             # Color planes
        $writer.Write([uint16]32)            # Bits per pixel
        $writer.Write([uint32]$imageData.Length)  # Size of image data
        $writer.Write([uint32]$offset)       # Offset to image data
        
        $offset += $imageData.Length
    }
    
    # Escribir image data
    foreach ($bitmap in $bitmaps) {
        $ms = New-Object System.IO.MemoryStream
        $bitmap.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
        $imageData = $ms.ToArray()
        $writer.Write($imageData)
        $ms.Dispose()
    }
    
    $writer.Flush()
    Write-Host ""
    Write-Host "Icono generado: logo.ico" -ForegroundColor Green
    Write-Host "Tamaños incluidos: $($sizes -join ', ') pixels" -ForegroundColor Green
}
finally {
    $stream.Dispose()
    foreach ($bitmap in $bitmaps) {
        $bitmap.Dispose()
    }
    $png.Dispose()
}

Write-Host ""
Write-Host "Siguiente paso: Configurar los proyectos .csproj para usar el icono" -ForegroundColor Yellow
