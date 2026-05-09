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
    Write-Host "[INFO] El entorno ya existe. Eliminando para recrear..." -ForegroundColor Yellow
    conda env remove -n alwaysprint -y
    Write-Host ""
}

Write-Host "Creando entorno nuevo..." -ForegroundColor Gray
conda env create -f environment.yml

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] Falló la creación del entorno con environment.yml" -ForegroundColor Red
    Write-Host ""
    Write-Host "Intentando método alternativo con pip..." -ForegroundColor Yellow
    Write-Host ""
    
    # Método alternativo: crear entorno básico y usar pip
    conda create -n alwaysprint python=3.12 pip -y
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] No se pudo crear el entorno básico" -ForegroundColor Red
        Read-Host "Presiona Enter para salir"
        exit 1
    }
    
    Write-Host "Instalando dependencias con pip..." -ForegroundColor Gray
    conda run -n alwaysprint pip install -r requirements.txt
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Falló la instalación de dependencias" -ForegroundColor Red
        Read-Host "Presiona Enter para salir"
        exit 1
    }
}
Write-Host ""

Write-Host "[3/5] Configurando variables de entorno..." -ForegroundColor Green
if (-not (Test-Path .env)) {
    if (Test-Path .env.example) {
        Copy-Item .env.example .env
        Write-Host "Archivo .env creado desde .env.example" -ForegroundColor Yellow
        Write-Host "Por favor revisa y actualiza la configuración en .env" -ForegroundColor Yellow
    } else {
        Write-Host "[WARNING] No se encontró .env.example" -ForegroundColor Yellow
    }
} else {
    Write-Host "Archivo .env ya existe." -ForegroundColor Gray
}
Write-Host ""

Write-Host "[4/5] Aplicando migraciones de base de datos..." -ForegroundColor Green
Write-Host "Ejecutando: conda run -n alwaysprint alembic upgrade head" -ForegroundColor Gray

# Ejecutar alembic en el entorno conda
conda run -n alwaysprint alembic upgrade head

if ($LASTEXITCODE -ne 0) {
    Write-Host "[WARNING] Error al aplicar migraciones." -ForegroundColor Yellow
    Write-Host "Esto es normal si es la primera vez o si la base de datos no está configurada." -ForegroundColor Yellow
    Write-Host "Puedes ejecutar 'alembic upgrade head' manualmente después de configurar la DB." -ForegroundColor Yellow
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
Write-Host "   Edita el archivo .env con tu configuración" -ForegroundColor Yellow
Write-Host ""
Write-Host "3. Aplicar migraciones (si no se aplicaron):" -ForegroundColor White
Write-Host "   alembic upgrade head" -ForegroundColor Yellow
Write-Host ""
Write-Host "4. Ejecutar el servidor:" -ForegroundColor White
Write-Host "   uvicorn app.main:app --reload" -ForegroundColor Yellow
Write-Host ""
Write-Host "5. Acceder a la documentación:" -ForegroundColor White
Write-Host "   http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host ""

Read-Host "Presiona Enter para salir"
