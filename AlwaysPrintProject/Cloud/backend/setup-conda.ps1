# Script de instalación con Conda para Windows PowerShell
# AlwaysPrint Cloud Manager - Backend

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "AlwaysPrint Cloud Manager - Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Verificar si conda está instalado
$condaCommand = Get-Command conda -ErrorAction SilentlyContinue
if (-not $condaCommand) {
    Write-Host "[ERROR] Conda no está instalado o no está en el PATH" -ForegroundColor Red
    Write-Host ""
    Write-Host "Por favor instala Miniconda o Anaconda desde:"
    Write-Host "https://docs.conda.io/en/latest/miniconda.html"
    Write-Host ""
    Read-Host "Presiona Enter para salir"
    exit 1
}

Write-Host "[1/5] Verificando Conda..." -ForegroundColor Green
conda --version
Write-Host ""

Write-Host "[2/5] Creando entorno conda 'alwaysprint' con Python 3.12..." -ForegroundColor Green
$envExists = conda env list | Select-String "alwaysprint"
if ($envExists) {
    Write-Host "[INFO] El entorno ya existe. Actualizando..." -ForegroundColor Yellow
    conda env update -f environment.yml --prune
} else {
    conda env create -f environment.yml
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Falló la creación del entorno" -ForegroundColor Red
    Read-Host "Presiona Enter para salir"
    exit 1
}
Write-Host ""

Write-Host "[3/5] Configurando variables de entorno..." -ForegroundColor Green
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host "Archivo .env creado. Por favor revisa la configuración." -ForegroundColor Yellow
} else {
    Write-Host "Archivo .env ya existe." -ForegroundColor Gray
}
Write-Host ""

Write-Host "[4/5] Activando entorno y aplicando migraciones..." -ForegroundColor Green
Write-Host "Ejecutando: conda run -n alwaysprint alembic upgrade head" -ForegroundColor Gray

# Ejecutar alembic en el entorno conda
conda run -n alwaysprint alembic upgrade head

if ($LASTEXITCODE -ne 0) {
    Write-Host "[WARNING] Error al aplicar migraciones. Verifica la configuración de la base de datos." -ForegroundColor Yellow
}
Write-Host ""

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Instalación completada!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Para activar el entorno:" -ForegroundColor White
Write-Host "  conda activate alwaysprint" -ForegroundColor Yellow
Write-Host ""
Write-Host "Para ejecutar el servidor:" -ForegroundColor White
Write-Host "  uvicorn app.main:app --reload" -ForegroundColor Yellow
Write-Host ""
Write-Host "Documentación API:" -ForegroundColor White
Write-Host "  http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host ""

Read-Host "Presiona Enter para salir"
