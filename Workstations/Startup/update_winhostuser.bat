@echo off
setlocal EnableDelayedExpansion

REM ───────── INTENTO 1: virtconf.txt (srvhost) ─────────
set "VCONF=D:\VirtAplic\VirtRM\virtconf.txt"
if exist "%VCONF%" (
    for /f "usebackq tokens=2 delims=='" %%A in (`findstr /i /b "srvhost=" "%VCONF%"`) do (
        set "RAWIP=%%A"
    )
    if defined RAWIP (
        for /f "tokens=1-4 delims=." %%a in ("!RAWIP!") do (
            set "SERVER=%%a.%%b.%%c.210"
        )
        echo [virtconf] SERVER cargado desde virtconf.txt: !SERVER!
        goto CONTINUAR
    )
)

REM ───────── INTENTO 2: VMX (si no se definio SERVER) ─────────
set VMXFILE=C:\imagenes_12\Nacar_Suse12.vmx
for /f "tokens=2 delims==" %%A in ('findstr /b "ethernet0.address" "%VMXFILE%"') do (
    for /f "tokens=* delims= " %%B in ("%%~A") do set MAC=%%B
)
set MAC=%MAC:"=%

echo MAC: %MAC%

set CHAR10=%MAC:~9,1%
set CHAR11=%MAC:~10,1%
set CHAR13=%MAC:~12,1%
set CHAR14=%MAC:~13,1%

set SERVER=s0%CHAR11%%CHAR13%%CHAR14%00%CHAR10%.nacarpe.igrupobbva

:CONTINUAR
echo Server: %SERVER%
set QUEUE=CPMWinHostUser
echo Queue: %QUEUE%

set "IP="
for /f "tokens=2 delims=:" %%A in ('ipconfig ^| findstr /i "IPv4"') do (
    set "raw=%%A"
    set "raw=!raw: =!"
    if /i not "!raw:~0,3!"=="169" if /i not "!raw!"=="127.0.0.1" if not defined IP set "IP=!raw!"
)
if not defined IP set "IP=unknown"
echo IP: %IP%
set "DATA=%COMPUTERNAME%^|%USERNAME%^|%IP%"
echo DATA: "%DATA%"
set TEMPFILE=%TEMP%\hostuser_%RANDOM%.txt
echo TEMPFILE: %TEMPFILE%
echo %DATA% > "%TEMPFILE%"
echo Temp File: %TEMPFILE%
type %TEMPFILE%
echo Exec: lpr -S %SERVER% -P %QUEUE% "%TEMPFILE%"
lpr -S %SERVER% -P %QUEUE% "%TEMPFILE%"
echo del "%TEMPFILE%"
del "%TEMPFILE%"