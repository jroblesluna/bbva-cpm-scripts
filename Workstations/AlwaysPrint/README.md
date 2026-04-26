# AlwaysPrint

Solución Windows de gestión corporativa de colas de impresión para BBVA.  
Dos ejecutables cooperan mediante Named Pipe para monitorear y configurar impresoras Lexmark desde la workstation.

---

## Componentes

| Ejecutable | Tipo | Cuenta | Rol |
|---|---|---|---|
| `AlwaysPrintService.exe` | Windows Service | LocalSystem | Componente central. Mantiene la cola de tareas, gestiona la configuración en Registro, lanza el Tray y expone el Named Pipe. |
| `AlwaysPrintTray.exe` | WinForms tray app | Usuario interactivo | Interacción con el usuario. Se conecta al servicio por Named Pipe, realiza el handshake de licencia y expone menú de configuración. |

---

## Estructura de proyectos

```
AlwaysPrint/
├── AlwaysPrint.sln
├── build.ps1                       ← build completo + MSI (un comando)
├── Product.wxs                     ← definición WiX del instalador
├── AlwaysPrint.Shared/             ← biblioteca compartida (DTOs, config, logging)
│   ├── Configuration/              ← AppConfiguration + RegistryConfigManager
│   ├── Logging/                    ← EventLogWriter (event IDs fijos)
│   ├── Messages/                   ← PipeMessage, MessageType, Payloads, PipeConstants
│   └── Models/                     ← ServiceState enum
├── AlwaysPrintService/             ← Windows Service (.NET 4.8)
│   ├── Pipe/                       ← PipeServer + MessageDispatcher
│   ├── Queue/                      ← TaskQueueManager (BlockingCollection)
│   ├── Tasks/                      ← UpdateConfiguration, CheckCorporateQueue, CheckServiceStatus
│   └── UserSession/                ← NativeMethods P/Invoke, InteractiveProcessLauncher, SessionMonitor
├── AlwaysPrintTray/                ← WinForms tray app (.NET 4.8)
│   ├── Bootstrap/                  ← DomainHealthChecker (HTTP health check)
│   ├── Forms/                      ← AboutForm, ConfigurationForm
│   └── Pipe/                       ← PipeClient
└── Installer/                      ← Scripts PowerShell alternativos (sin WiX)
    ├── Install-AlwaysPrint.ps1
    └── Uninstall-AlwaysPrint.ps1
```

---

## Requisitos de build

- Windows 10/11 o Windows Server 2019+
- [.NET SDK 8+](https://dotnet.microsoft.com/download) (compila net48 con proyectos SDK-style)
- WiX Toolset v4 como dotnet tool global — `build.ps1` lo instala automáticamente
- `%USERPROFILE%\.dotnet\tools` en el PATH

---

## Build y empaquetado

Desde la carpeta `Workstations/AlwaysPrint/`, en PowerShell:

```powershell
.\build.ps1
```

Qué hace el script:

1. Limpia artefactos anteriores (`bin`, `obj`, `dist`, `.wix`, `AlwaysPrint.msi`).
2. Actualiza `wix` CLI global; si no está instalado, lo instala desde cero.
3. Registra la extensión `WixToolset.Util.wixext` (idempotente).
4. Publica `AlwaysPrintService` a `.\dist\` (`net48`, framework-dependent, x64).
5. Publica `AlwaysPrintTray` a `.\dist\` (misma carpeta, agrega el segundo EXE).
6. Verifica que los 4 archivos requeridos existen en `dist\` antes de llamar a WiX.
7. Compila `Product.wxs` → `.\AlwaysPrint.msi`. La versión del paquete se toma automáticamente del file version de `AlwaysPrintService.exe`.

Salida esperada:

```
dist\
  AlwaysPrintService.exe
  AlwaysPrintTray.exe
  AlwaysPrint.Shared.dll
  Newtonsoft.Json.dll
AlwaysPrint.msi
```

> **Nota:** al ser net48 framework-dependent, la máquina destino debe tener .NET Framework 4.8, incluido en Windows 10 1903+ y Windows 11.

---

## Instalación

### Opción A — MSI (recomendado para producción)

```powershell
# Instalación silenciosa
msiexec /i .\AlwaysPrint.msi /qn /L*v install.log

# Desinstalación
msiexec /x .\AlwaysPrint.msi /qn /L*v uninstall.log
```

El MSI realiza automáticamente:
- Instala los binarios en `C:\Program Files\Robles.AI\AlwaysPrint\`
- Registra el servicio `AlwaysPrintService` (LocalSystem, inicio automático)
- Configura recuperación automática (reinicio en 60 s tras cualquier fallo)
- Crea el source de Event Log `AlwaysPrint` en el Application log
- Escribe los valores por defecto en `HKLM\SOFTWARE\Robles.AI\AlwaysPrint`

### Opción B — Script PowerShell (desarrollo / pruebas)

```powershell
# Compilar primero
dotnet publish .\AlwaysPrintService\AlwaysPrintService.csproj -c Release -f net48 -o publish
dotnet publish .\AlwaysPrintTray\AlwaysPrintTray.csproj       -c Release -f net48 -o publish

# Instalar (requiere admin)
.\Installer\Install-AlwaysPrint.ps1 -BinDir ".\publish"

# Desinstalar
.\Installer\Uninstall-AlwaysPrint.ps1
```

### Opción C — Modo consola (debug sin SCM)

Permite ejecutar el servicio directamente en la terminal sin registrarlo en el SCM:

```powershell
.\dist\AlwaysPrintService.exe /console
# Muestra logs en tiempo real. Enter para detener.
```

---

## Configuración

Ubicación en Registro: `HKEY_LOCAL_MACHINE\SOFTWARE\Robles.AI\AlwaysPrint`

| Valor | Tipo | Default | Descripción |
|---|---|---|---|
| `CorporateQueueName` | String | `""` | Nombre de la cola de impresión corporativa (ej. `LexmarkBBVA`) |
| `SearchTargets` | String (JSON) | `{"ips":"","ranges":""}` | IPs y rangos CIDR de impresoras conocidas |
| `PendingTaskPollingMinutes` | DWORD | `3` | Frecuencia del ciclo de monitoreo (1–1440 min) |
| `BootstrapDomains` | String | `"robles.ai,iol.pe,sistemas.com.pe"` | Dominios para health check de licencia (CSV) |
| `RoblesAiLicenseSerial` | String | `""` | Número de serie de licencia |

La configuración se edita desde el menú **Configuración de Valores** del Tray. El Tray envía los cambios al servicio por Named Pipe; el servicio es el único que escribe en HKLM.

---

## Protocolo Named Pipe

- Pipe: `\\.\pipe\AlwaysPrintService`
- Nombre definido en `AlwaysPrint.Shared/Messages/PipeConstants.cs` (compartido por servicio y Tray)
- Formato: JSON por líneas (`\n`-delimited), un request → una response
- DACL: LocalSystem = FullControl, AuthenticatedUsers = ReadWrite
- Timeout de lectura en el cliente: 30 s (evita bloqueos ante respuestas lentas de WMI)

| Tipo de mensaje | Dirección | Payload de respuesta |
|---|---|---|
| `Ping` / `Pong` | Tray → Servicio | — |
| `TrayInitialized` | Tray → Servicio | `AckPayload` |
| `UpdateConfiguration` | Tray → Servicio | `AckPayload` |
| `GetCurrentConfiguration` | Tray → Servicio | `GetConfigurationResponsePayload` |
| `CheckCorporateQueue` | Tray → Servicio | `CheckCorporateQueueResponsePayload` |
| `CheckServiceStatus` | Tray → Servicio | `CheckServiceStatusResponsePayload` |
| `Ack` / `Error` | Servicio → Tray | `AckPayload` / `ErrorPayload` |

---

## Ciclo de vida del servicio

```
Starting
  → WaitingUser       (espera sesión interactiva; se despierta por evento SCM o polling 60 s)
  → TrayStarting      (lanza AlwaysPrintTray.exe en la sesión del usuario)
  → TrayStarted       (Tray confirmó handshake en < 5 min)
  → Running           (ciclo de monitoreo activo)
       ↓ logoff
  → WaitingUser       (mata el Tray, espera nueva sesión → relanza automáticamente)
  → TrayError         (timeout de handshake → SCM reinicia el servicio)
  → Stopping / Stopped
```

El ciclo WaitingUser → Running se repite en cada logon/logoff sin reiniciar el servicio.  
El servicio lanza el Tray usando `WTSQueryUserToken` + `CreateProcessAsUser` para cruzar desde Session 0 a la sesión interactiva.

---

## Bootstrap del Tray

Al arrancar, el Tray realiza HTTP GET a `https://alwaysprint.{dominio}/health` para cada dominio en `BootstrapDomains`, en orden. El primero que devuelva HTTP 200 se considera válido.

- Si alguno responde: envía `TrayInitialized { success: true }` y muestra notificación de éxito.
- Si ninguno responde: envía `TrayInitialized { success: false }` y continúa en modo local (las funciones de impresión locales siguen activas).

El `HttpClient` es estático y reutilizable (no se instancia por llamada).

---

## Logs y diagnóstico

```powershell
# Ver eventos recientes (Event Viewer → Application → Source: AlwaysPrint)
Get-EventLog -LogName Application -Source AlwaysPrint -Newest 30

# Estado del servicio
Get-Service AlwaysPrintService

# Verificar registro
Get-Item 'HKLM:\SOFTWARE\Robles.AI\AlwaysPrint'

# Debug del servicio en consola (sin SCM, sin admin)
.\dist\AlwaysPrintService.exe /console
```

### Event IDs de referencia

| ID | Significado |
|---|---|
| 1000 | Servicio iniciado |
| 1001 | Servicio detenido |
| 1002 | Instancia duplicada detectada |
| 1003 | Tray eliminado (logoff o arranque) |
| 1004 | Cola de tareas limpiada |
| 1005 | Pipe server iniciado |
| 1006 | Esperando sesión de usuario |
| 1007 | Sesión de usuario detectada |
| 1008–1009 | Tray iniciando / iniciado |
| 1010 | Error en el Tray |
| 1020–1022 | Tarea despachada / completada / fallida |
| 1030 | Configuración guardada |
| 1090–1091 | Warning / Error genérico |

---

## Solución de problemas

| Síntoma | Causa probable | Acción |
|---|---|---|
| El Tray no aparece tras iniciar el servicio | No hay sesión interactiva o `CreateProcessAsUser` falló | Revisar Event Log (EvtId 1010). Verificar que el servicio corre como LocalSystem. |
| El Tray no reaparece tras un logoff/logon | Bug en el ciclo de sesión | Revisar Event Log alrededor de EvtId 1003 y 1006. El ciclo debería reiniciarse automáticamente. |
| El servicio se detiene a los 5 minutos | Tray no completó handshake (TrayError, EvtId 1010) | El SCM lo reiniciará. Verificar que `AlwaysPrintTray.exe` existe en la misma carpeta que el servicio. |
| `CheckCorporateQueue` devuelve `exists: false` | La cola no existe o WMI falló | Verificar con `Get-Printer -Name "LexmarkBBVA"`. Revisar permisos WMI del servicio. |
| Configuración no se guarda | El Tray no tiene respuesta del servicio | Verificar que el pipe está activo con `Get-Service AlwaysPrintService`. Revisar EvtId 1091. |
| MSI falla con error 1603 | Archivo faltante en `dist\` o wix no instalado | Ejecutar `build.ps1` completo. El script verifica los 4 archivos requeridos antes de llamar a WiX. |
| Event Log source no registrado | Primera instalación sin MSI | El servicio intenta crearlo en runtime. Si falla: `[System.Diagnostics.EventLog]::CreateEventSource('AlwaysPrint','Application')` (requiere admin). |

---

## Licencia / Contacto

© 2025 **Robles.AI** — antonio@robles.ai  
Uso interno corporativo BBVA. No distribuir externamente.
