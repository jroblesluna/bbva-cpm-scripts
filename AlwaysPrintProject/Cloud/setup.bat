@echo off
REM Script de inicialización del proyecto AlwaysPrint Cloud Management
REM Este script configura el entorno de desarrollo local en Windows

echo ==========================================
echo AlwaysPrint Cloud Management - Setup
echo ==========================================
echo.

REM Verificar Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python 3.11+ no encontrado. Por favor instalar Python.
    exit /b 1
)
echo [OK] Python encontrado

REM Verificar Node.js
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Node.js 20+ no encontrado. Por favor instalar Node.js.
    exit /b 1
)
echo [OK] Node.js encontrado

REM Verificar npm
npm --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] npm no encontrado. Por favor instalar npm.
    exit /b 1
)
echo [OK] npm encontrado

echo.
echo ==========================================
echo Configurando Backend...
echo ==========================================

cd backend

REM Crear entorno virtual
if not exist "venv" (
    echo Creando entorno virtual Python...
    python -m venv venv
    echo [OK] Entorno virtual creado
) else (
    echo [WARN] Entorno virtual ya existe
)

REM Activar entorno virtual e instalar dependencias
echo Instalando dependencias Python...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
echo [OK] Dependencias Python instaladas

REM Crear archivo .env si no existe
if not exist ".env" (
    echo Creando archivo .env...
    copy .env.example .env
    echo [OK] Archivo .env creado (revisar y ajustar configuracion)
) else (
    echo [WARN] Archivo .env ya existe
)

cd ..

echo.
echo ==========================================
echo Configurando Frontend...
echo ==========================================

cd frontend

REM Instalar dependencias
echo Instalando dependencias Node.js...
call npm install
echo [OK] Dependencias Node.js instaladas

REM Crear archivo .env.local si no existe
if not exist ".env.local" (
    echo Creando archivo .env.local...
    copy .env.example .env.local
    echo [OK] Archivo .env.local creado
) else (
    echo [WARN] Archivo .env.local ya existe
)

cd ..

echo.
echo ==========================================
echo Setup completado!
echo ==========================================
echo.
echo Para iniciar el proyecto:
echo.
echo Backend:
echo   cd backend
echo   venv\Scripts\activate
echo   uvicorn app.main:app --reload
echo.
echo Frontend:
echo   cd frontend
echo   npm run dev
echo.
echo O usar Docker Compose:
echo   docker-compose up -d
echo.
echo [OK] Listo para desarrollar!
pause
