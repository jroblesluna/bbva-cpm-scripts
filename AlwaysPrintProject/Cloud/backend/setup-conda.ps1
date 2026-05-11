# Script de instalación con Conda para Windows PowerShell
# AlwaysPrint Cloud Manager - Backend

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "AlwaysPrint Cloud Manager - Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Verificar si conda está instalado
if (-not (Get-Command conda -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Conda no está instalado o no está en el PATH" -ForegroundColor Red
    Write-Host ""
    Write-Host "Instala Miniconda desde: https://docs.conda.io/en/latest/miniconda.html"
    Write-Host ""
    Read-Host "Presiona Enter para salir"
    exit 1
}

Write-Host "[1/4] Verificando Conda..." -ForegroundColor Green
conda --version
Write-Host ""

Write-Host "[2/4] Preparando entorno conda 'alwaysprint' con Python 3.12..." -ForegroundColor Green
$envExists = conda env list | Select-String "^alwaysprint "
if ($envExists) {
    Write-Host "[INFO] El entorno ya existe. Eliminando para recrear..." -ForegroundColor Yellow
    conda env remove -n alwaysprint -y
    Write-Host ""
}

conda create -n alwaysprint python=3.12 pip -y

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] No se pudo crear el entorno conda" -ForegroundColor Red
    Read-Host "Presiona Enter para salir"
    exit 1
}

Write-Host "Instalando dependencias..." -ForegroundColor Gray
conda run -n alwaysprint pip install -r requirements.txt

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Falló la instalación de dependencias" -ForegroundColor Red
    Read-Host "Presiona Enter para salir"
    exit 1
}
Write-Host ""

Write-Host "[3/4] Configurando variables de entorno..." -ForegroundColor Green
if (-not (Test-Path .env)) {
    if (Test-Path .env.example) {
        Copy-Item .env.example .env
        Write-Host "Archivo .env creado desde .env.example" -ForegroundColor Yellow
        Write-Host "Revisa y actualiza la configuración en .env antes de continuar" -ForegroundColor Yellow
    } else {
        Write-Host "[WARNING] No se encontró .env.example" -ForegroundColor Yellow
    }
} else {
    Write-Host "Archivo .env ya existe." -ForegroundColor Gray
}
Write-Host ""

Write-Host "[4/4] Aplicando migraciones de base de datos..." -ForegroundColor Green
conda run -n alwaysprint alembic upgrade head

if ($LASTEXITCODE -ne 0) {
    Write-Host "[WARNING] Error al aplicar migraciones." -ForegroundColor Yellow
    Write-Host "Verifica la configuración DATABASE_URL en .env y ejecuta 'alembic upgrade head' manualmente." -ForegroundColor Yellow
}
Write-Host ""

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Instalación completada!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Próximos pasos:" -ForegroundColor White
Write-Host ""
Write-Host "1. Activar el entorno:" -ForegroundColor White
Write-Host "   conda activate alwaysprint" -ForegroundColor Yellow
Write-Host ""
Write-Host "2. Revisar configuración:" -ForegroundColor White
Write-Host "   Edita .env con tu configuración local" -ForegroundColor Yellow
Write-Host ""
Write-Host "3. Ejecutar el servidor:" -ForegroundColor White
Write-Host "   uvicorn app.main:app --reload" -ForegroundColor Yellow
Write-Host ""
Write-Host "4. Documentación API:" -ForegroundColor White
Write-Host "   http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host ""

Read-Host "Presiona Enter para salir"
