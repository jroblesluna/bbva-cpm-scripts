@echo off
REM AlwaysPrint - Instalador/Desinstalador Universal
REM Uso: AlwaysPrint.bat [/u para desinstalar]

if /i "%1"=="/u" goto uninstall

:install
msiexec /i "%~dp0AlwaysPrint.msi" /qn
exit /b

:uninstall
for /f "tokens=8 delims=\" %%a in ('reg query HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall /s /f AlwaysPrint ^| findstr HKEY') do msiexec /x {%%a} /qn
exit /b
