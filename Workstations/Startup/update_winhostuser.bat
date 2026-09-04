@echo off
setlocal EnableDelayedExpansion
setlocal EnableExtensions

REM Comprobar si el cliente LPR está instalado
where lpr >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Comando LPR no encontrado. Por favor, habilite la característica "LPR Port Monitor".
    exit /b 1
)

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
        goto DERIVAR_VMHOST
    )
)

REM ───────── INTENTO 2: VMX (si no se definio SERVER) ─────────
REM Primero probar C:\imagenes_12\Nacar_Suse12.vmx; si no, C:\VMware\Nacar_Suse12.vmx; si no, error.

:DERIVAR_VMHOST
set "VMXFILE=C:\imagenes_12\Nacar_Suse12.vmx"
if not exist "%VMXFILE%" (
    set "VMXFILE=C:\VMware\Nacar_Suse12.vmx"
    if not exist "!VMXFILE!" (
        set "VMXFILE=C:\VMware\imagenes_12\Nacar_Suse12.vmx"
        if not exist "!VMXFILE!" (
            REM Si SERVER ya se resolvió por virtconf, la ausencia del VMX no es fatal:
            REM solo significa que no podremos derivar VMHOST (usuarios de agencia usan COMPUTERNAME).
            if defined SERVER (
                echo [ADVERTENCIA] No se encontro VMX; VMHOST no derivado ^(SERVER via virtconf^)
                goto CONTINUAR
            )
            echo [ERROR] No se encuentra ruta disponible a Servidor Nacar.
            exit /b 1
        )
    )
)

for /f "tokens=2 delims==" %%A in ('findstr /b "ethernet0.address" "%VMXFILE%"') do (
    for /f "tokens=* delims= " %%B in ("%%~A") do set MAC=%%B
)
set MAC=%MAC:"=%

echo MAC: %MAC%

if not defined MAC (
    if defined SERVER (
        echo [ADVERTENCIA] No se pudo extraer MAC del VMX; VMHOST no derivado
        goto CONTINUAR
    )
    echo [ERROR] No se pudo extraer la direccion MAC del archivo VMX.
    exit /b 1
)

set "CHAR10=%MAC:~9,1%"
set "CHAR11=%MAC:~10,1%"
set "CHAR13=%MAC:~12,1%"
set "CHAR14=%MAC:~13,1%"
set "CHAR16=%MAC:~15,1%"
set "CHAR17=%MAC:~16,1%"

REM Si SERVER no vino de virtconf, derivarlo de la MAC (flujo VMware puro)
if not defined SERVER set SERVER=s0%CHAR11%%CHAR13%%CHAR14%00%CHAR10%.nacarpe.igrupobbva

REM Derivar hostname de la VM Linux desde la MAC del VMX
REM MAC "00:50:56:YX:XX:ZZ" -> w10<XXX>0<Y>p<ZZ>
REM   XXX (agencia)  = CHAR11 + CHAR13 + CHAR14  (ej. 9,1,0 -> "910")
REM   Y   (servidor) = CHAR10                    (ej. 1)
REM   ZZ  (puesto)   = CHAR16 + CHAR17           (ej. 2,2 -> "22")
set "VMHOST=w10%CHAR11%%CHAR13%%CHAR14%0%CHAR10%p%CHAR16%%CHAR17%"
echo VM Host derivado: %VMHOST%

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

REM ───────── DETERMINAR HOSTNAME A ENVIAR ─────────
REM La decisión se basa en el HOSTNAME de Windows (%COMPUTERNAME%):
REM   - Si cumple la estructura de agencia W1######P## (W1 + 6 dígitos + P +
REM     2 dígitos = 11 chars), con o sin sufijo alfabético opcional
REM     (w1012301p15, w1012301p15a, w1012301p15b) -> flujo de agencias.
REM     Se TRUNCA a los primeros 11 chars (w1012301p15a -> w1012301p15).
REM   - Cualquier otro caso (P017241, P017241A, XP12345, DESKTOP-ABCD,
REM     W11PRUEBAOF3, etc.) -> flujo Sede Central, se envía el hostname de la
REM     VM Linux (VMHOST) derivado de la MAC del VMX.
set "SENDHOST=%COMPUTERNAME%"

REM ¿El hostname cumple la estructura de agencia W1######P## + sufijo opcional?
REM Se valida contra los primeros 11 chars; si coinciden, es agencia y se trunca.
set "HOST11=%COMPUTERNAME:~0,11%"
set "IS_AGENCIA=0"
echo(%HOST11%| findstr /I /X /R "W1[0-9][0-9][0-9][0-9][0-9][0-9]P[0-9][0-9]" >nul && set "IS_AGENCIA=1"

if "!IS_AGENCIA!"=="1" (
    set "SENDHOST=!HOST11!"
    echo [Agencia] Hostname %COMPUTERNAME% es de agencia, se envia truncado a 11: !HOST11!
) else (
    if defined VMHOST (
        set "SENDHOST=!VMHOST!"
        echo [Sede Central] Hostname %COMPUTERNAME% no es de agencia, usando VM Host: !VMHOST!
    ) else (
        echo [ADVERTENCIA] Hostname %COMPUTERNAME% no es de agencia pero VMHOST no derivado; se usa %COMPUTERNAME%
    )
)

set "DATA=!SENDHOST!^|%USERNAME%^|%IP%"
echo DATA: "!DATA!"
set "TEMPFILE=%TEMP%\hostuser_%RANDOM%.txt"
echo TEMPFILE: %TEMPFILE%
echo !DATA! > "%TEMPFILE%"
echo Temp File: %TEMPFILE%
type "%TEMPFILE%"
echo Exec: lpr -S %SERVER% -P %QUEUE% "%TEMPFILE%"
lpr -S %SERVER% -P %QUEUE% "%TEMPFILE%"
echo del "%TEMPFILE%"
del "%TEMPFILE%"