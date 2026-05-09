@echo off
REM Script de instalación con Conda para Windows
REM AlwaysPrint Cloud Manager - Backend

echo ========================================
echo AlwaysPrint Cloud Manager - Setup
echo ========================================
echo.

REM Verificar si conda está instalado
where conda >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Conda no está instalado o no está en el PATH
    echo.
    echo Por favor instala Miniconda o Anaconda desde:
    echo https://docs.conda.io/en/latest/miniconda.html
    echo.
    pause
    exit /b 1
)

echo [1/5] Verificando Conda...
conda --version
echo.

echo [2/5] Creando entorno conda 'alwaysprint' con Python 3.12...
conda env create -f environment.yml
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [INFO] El entorno ya existe. Actualizando...
    conda env update -f environment.yml --prune
)
echo.

echo [3/5] Activando entorno...
call conda activate alwaysprint
echo.

echo [4/5] Configurando variables de entorno...
if not exist .env (
    copy .env.example .env
    echo Archivo .env creado. Por favor revisa la configuración.
) else (
    echo Archivo .env ya existe.
)
echo.

echo [5/5] Inicializando base de datos...
alembic upgrade head
if %ERRORLEVEL% NEQ 0 (
    echo [WARNING] Error al aplicar migraciones. Verifica la configuración de la base de datos.
)
echo.

echo ========================================
echo Instalación completada!
echo ========================================
echo.
echo Para activar el entorno:
echo   conda activate alwaysprint
echo.
echo Para ejecutar el servidor:
echo   uvicorn app.main:app --reload
echo.
echo Documentación API:
echo   http://localhost:8000/docs
echo.
pause
