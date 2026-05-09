@echo off
REM Script para agregar Conda al PATH de Windows
REM Ejecutar como Administrador

echo ========================================
echo Configurar Conda en PATH
echo ========================================
echo.

REM Detectar instalación de Miniconda/Anaconda
set CONDA_PATH=
set CONDA_SCRIPTS=

REM Buscar en ubicaciones comunes
if exist "%USERPROFILE%\miniconda3" (
    set CONDA_PATH=%USERPROFILE%\miniconda3
    set CONDA_SCRIPTS=%USERPROFILE%\miniconda3\Scripts
    set CONDA_LIBRARY=%USERPROFILE%\miniconda3\Library\bin
    echo [OK] Encontrado Miniconda en: %CONDA_PATH%
) else if exist "%USERPROFILE%\anaconda3" (
    set CONDA_PATH=%USERPROFILE%\anaconda3
    set CONDA_SCRIPTS=%USERPROFILE%\anaconda3\Scripts
    set CONDA_LIBRARY=%USERPROFILE%\anaconda3\Library\bin
    echo [OK] Encontrado Anaconda en: %CONDA_PATH%
) else if exist "C:\ProgramData\miniconda3" (
    set CONDA_PATH=C:\ProgramData\miniconda3
    set CONDA_SCRIPTS=C:\ProgramData\miniconda3\Scripts
    set CONDA_LIBRARY=C:\ProgramData\miniconda3\Library\bin
    echo [OK] Encontrado Miniconda en: %CONDA_PATH%
) else if exist "C:\ProgramData\anaconda3" (
    set CONDA_PATH=C:\ProgramData\anaconda3
    set CONDA_SCRIPTS=C:\ProgramData\anaconda3\Scripts
    set CONDA_LIBRARY=C:\ProgramData\anaconda3\Library\bin
    echo [OK] Encontrado Anaconda en: %CONDA_PATH%
) else (
    echo [ERROR] No se encontró instalación de Conda
    echo.
    echo Busca manualmente la carpeta de instalación y ejecuta:
    echo   conda init cmd.exe
    echo   conda init powershell
    echo.
    pause
    exit /b 1
)

echo.
echo Rutas detectadas:
echo   Base: %CONDA_PATH%
echo   Scripts: %CONDA_SCRIPTS%
echo   Library: %CONDA_LIBRARY%
echo.

REM Inicializar conda para cmd y powershell
echo [1/2] Inicializando Conda para CMD y PowerShell...
call "%CONDA_PATH%\Scripts\conda.exe" init cmd.exe
call "%CONDA_PATH%\Scripts\conda.exe" init powershell
echo.

echo [2/2] Agregando Conda al PATH del sistema...
echo.
echo IMPORTANTE: Necesitas permisos de Administrador para esto.
echo Si no tienes permisos, salta este paso y usa la opción manual.
echo.
choice /C SN /M "¿Agregar al PATH del sistema (requiere Admin)?"

if errorlevel 2 goto MANUAL
if errorlevel 1 goto SYSTEM_PATH

:SYSTEM_PATH
REM Agregar al PATH del sistema (requiere admin)
setx PATH "%PATH%;%CONDA_PATH%;%CONDA_SCRIPTS%;%CONDA_LIBRARY%" /M
if %ERRORLEVEL% EQU 0 (
    echo [OK] Conda agregado al PATH del sistema
    goto END
) else (
    echo [ERROR] No se pudo agregar al PATH del sistema
    echo Ejecuta este script como Administrador o usa la opción manual
    goto MANUAL
)

:MANUAL
echo.
echo ========================================
echo Configuración Manual
echo ========================================
echo.
echo Opción 1: Agregar al PATH manualmente
echo   1. Presiona Win + R
echo   2. Escribe: sysdm.cpl
echo   3. Ve a "Opciones avanzadas" ^> "Variables de entorno"
echo   4. En "Variables del sistema", selecciona "Path" y haz clic en "Editar"
echo   5. Agrega estas rutas (una por línea):
echo      %CONDA_PATH%
echo      %CONDA_SCRIPTS%
echo      %CONDA_LIBRARY%
echo   6. Haz clic en "Aceptar" en todas las ventanas
echo   7. Reinicia CMD/PowerShell
echo.
echo Opción 2: Usar siempre "Anaconda Prompt" o "Miniconda Prompt"
echo   - Busca en el menú inicio: "Anaconda Prompt"
echo   - Conda ya estará disponible en esa terminal
echo.
goto END

:END
echo.
echo ========================================
echo Configuración completada
echo ========================================
echo.
echo IMPORTANTE: Cierra y abre una nueva ventana de CMD/PowerShell
echo para que los cambios surtan efecto.
echo.
echo Para verificar, ejecuta en una nueva terminal:
echo   conda --version
echo.
pause
