@echo off
REM ============================================================================
REM AlwaysPrint - Script de Instalacion/Desinstalacion Universal
REM ============================================================================
REM Este script permite instalar o desinstalar AlwaysPrint usando el mismo MSI,
REM sin importar que version este instalada.
REM
REM Uso:
REM   install.bat           - Instala o actualiza AlwaysPrint
REM   install.bat /uninstall - Desinstala AlwaysPrint
REM ============================================================================

setlocal enabledelayedexpansion

REM Verificar permisos de administrador
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ERROR: Este script requiere permisos de administrador.
    echo Por favor, ejecutelo como Administrador.
    pause
    exit /b 1
)

REM Detectar la ruta del MSI (mismo directorio que el script)
set "MSI_PATH=%~dp0AlwaysPrint.msi"
if not exist "%MSI_PATH%" (
    echo ERROR: No se encontro AlwaysPrint.msi en %~dp0
    pause
    exit /b 1
)

REM Verificar si es desinstalacion
if /i "%~1"=="/uninstall" goto :uninstall
if /i "%~1"=="-uninstall" goto :uninstall
if /i "%~1"=="/u" goto :uninstall
if /i "%~1"=="-u" goto :uninstall

REM ============================================================================
REM INSTALACION / ACTUALIZACION
REM ============================================================================
:install
echo.
echo ========================================
echo  Instalando AlwaysPrint
echo ========================================
echo.
echo Ejecutando: msiexec /i "%MSI_PATH%" /qn
echo.

msiexec /i "%MSI_PATH%" /qn /L*v "%~dp0install.log"

if %errorLevel% equ 0 (
    echo.
    echo [OK] Instalacion completada correctamente.
    echo Log: %~dp0install.log
) else (
    echo.
    echo [ERROR] La instalacion fallo con codigo: %errorLevel%
    echo Revise el log: %~dp0install.log
    pause
    exit /b %errorLevel%
)

goto :end

REM ============================================================================
REM DESINSTALACION
REM ============================================================================
:uninstall
echo.
echo ========================================
echo  Desinstalando AlwaysPrint
echo ========================================
echo.

REM Buscar el ProductCode en el registro
echo Buscando AlwaysPrint instalado...

set "PRODUCT_CODE="
for /f "tokens=8 delims=\" %%a in ('reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" /s /f "AlwaysPrint" ^| findstr "HKEY"') do (
    set "PRODUCT_CODE=%%a"
)

if "%PRODUCT_CODE%"=="" (
    REM Intentar en WOW6432Node (32-bit en 64-bit)
    for /f "tokens=8 delims=\" %%a in ('reg query "HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall" /s /f "AlwaysPrint" ^| findstr "HKEY"') do (
        set "PRODUCT_CODE=%%a"
    )
)

if "%PRODUCT_CODE%"=="" (
    echo.
    echo [INFO] AlwaysPrint no esta instalado.
    goto :end
)

echo Encontrado: ProductCode = %PRODUCT_CODE%
echo.
echo Ejecutando: msiexec /x {%PRODUCT_CODE%} /qn
echo.

msiexec /x {%PRODUCT_CODE%} /qn /L*v "%~dp0uninstall.log"

if %errorLevel% equ 0 (
    echo.
    echo [OK] Desinstalacion completada correctamente.
    echo Log: %~dp0uninstall.log
) else (
    echo.
    echo [ERROR] La desinstalacion fallo con codigo: %errorLevel%
    echo Revise el log: %~dp0uninstall.log
    pause
    exit /b %errorLevel%
)

goto :end

REM ============================================================================
REM FIN
REM ============================================================================
:end
echo.
endlocal
exit /b 0
