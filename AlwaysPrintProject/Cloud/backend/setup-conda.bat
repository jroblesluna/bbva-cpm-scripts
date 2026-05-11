@echo off
REM Script de instalación con Conda para Windows CMD
REM AlwaysPrint Cloud Manager - Backend

echo ========================================
echo AlwaysPrint Cloud Manager - Setup
echo ========================================
echo.

REM Verificar si conda está instalado
where conda >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Conda no esta instalado o no esta en el PATH
    echo.
    echo Instala Miniconda desde: https://docs.conda.io/en/latest/miniconda.html
    echo.
    pause
    exit /b 1
)

echo [1/4] Verificando Conda...
conda --version
echo.

echo [2/4] Preparando entorno conda 'alwaysprint' con Python 3.12...
conda env list | findstr /B "alwaysprint " >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo [INFO] El entorno ya existe. Eliminando para recrear...
    conda env remove -n alwaysprint -y
    echo.
)

conda create -n alwaysprint python=3.12 pip -y
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] No se pudo crear el entorno conda
    pause
    exit /b 1
)

echo Instalando dependencias...
conda run -n alwaysprint pip install -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Fallo la instalacion de dependencias
    pause
    exit /b 1
)
echo.

echo [3/4] Configurando variables de entorno...
if not exist .env (
    if exist .env.example (
        copy .env.example .env
        echo Archivo .env creado desde .env.example
        echo Revisa y actualiza la configuracion en .env antes de continuar
    ) else (
        echo [WARNING] No se encontro .env.example
    )
) else (
    echo Archivo .env ya existe.
)
echo.

echo [4/4] Aplicando migraciones de base de datos...
conda run -n alwaysprint alembic upgrade head
if %ERRORLEVEL% NEQ 0 (
    echo [WARNING] Error al aplicar migraciones.
    echo Verifica DATABASE_URL en .env y ejecuta 'alembic upgrade head' manualmente.
)
echo.

echo ========================================
echo Instalacion completada!
echo ========================================
echo.
echo Proximos pasos:
echo.
echo 1. Activar el entorno:
echo    conda activate alwaysprint
echo.
echo 2. Revisar configuracion:
echo    Edita .env con tu configuracion local
echo.
echo 3. Ejecutar el servidor:
echo    uvicorn app.main:app --reload
echo.
echo 4. Documentacion API:
echo    http://localhost:8000/docs
echo.
pause
