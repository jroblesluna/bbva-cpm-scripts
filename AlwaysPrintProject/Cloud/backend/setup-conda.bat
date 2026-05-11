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
    (
        echo DATABASE_URL=sqlite:///./alwaysprint.db
        echo SECRET_KEY=dev-secret-key-change-in-production
        echo ALGORITHM=HS256
        echo ACCESS_TOKEN_EXPIRE_MINUTES=1440
        echo CORS_ORIGINS=http://localhost:3000
        echo API_V1_STR=/api/v1
        echo REDIS_URL=redis://localhost:6379/0
        echo SES_ENABLED=false
        echo SES_FROM_EMAIL=noreply@alwaysprint.apps.iol.pe
        echo AWS_REGION=us-west-2
        echo FRONTEND_URL=http://localhost:3000
        echo LOG_LEVEL=DEBUG
        echo WS_PING_INTERVAL=30
        echo WS_PING_TIMEOUT=60
        echo RATE_LIMIT_LOGIN=5
        echo RATE_LIMIT_API=100
    ) > .env
    echo Archivo .env creado con valores de desarrollo.
    echo Actualiza SECRET_KEY y DATABASE_URL segun tu entorno.
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
