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
│   ├── Messages/                   ← PipeMessage, MessageType, Payloads
│   └── Models/                     ← ServiceState enum
├── AlwaysPrintService/             ← Windows Service (.NET 4.8)
│   ├── Pipe/                       ← PipeServer + MessageDispatcher
│   ├── Queue/                      ← TaskQueueManager (BlockingCollection)
│   ├── Tasks/                      ← UpdateConfiguration, CheckCorporateQueue, CheckServiceStatus
│   └── UserSession/                ← NativeMethods P/Invoke, InteractiveProcessLauncher
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
- [WiX Toolset v4](https://wixtoolset.org/releases/) instalado como dotnet tool global (`build.ps1` lo instala automáticamente)
- `%USERPROFILE%\.dotnet\tools` en el PATH

---

## Build y empaquetado

Desde la carpeta `Workstations/AlwaysPrint/`, en PowerShell:

```powershell
.\build.ps1
```

Qué hace el script:

1. Limpia artefactos anteriores (`bin`, `obj`, `dist`, `.wix`).
2. Instala/actualiza `wix` CLI y registra la extensión `WixToolset.Util.wixext`.
3. Publica `AlwaysPrintService` a `.\dist\` (`net48`, framework-dependent, x64).
4. Publica `AlwaysPrintTray` a `.\dist\` (misma carpeta, agrega el segundo EXE).
5. Compila `Product.wxs` con WiX → `.\AlwaysPrint.msi`.

Salida esperada:

```
dist\
  AlwaysPrintService.exe
  AlwaysPrintTray.exe
  AlwaysPrint.Shared.dll
  Newtonsoft.Json.dll
AlwaysPrint.msi
```

> **Nota:** al ser net48 framework-dependent, la máquina destino debe tener instalado .NET Framework 4.8, que viene incluido en Windows 10 1903+ y Windows 11.

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

---

## Configuración

Ubicación en Registro: `HKEY_LOCAL_MACHINE\SOFTWARE\Robles.AI\AlwaysPrint`

| Valor | Tipo | Default | Descripción |
|---|---|---|---|
| `CorporateQueueName` | String | `""` | Nombre de la cola de impresión corporativa (ej. `LexmarkBBVA`) |
| `SearchTargets` | String (JSON) | `{"ips":"","ranges":""}` | IPs y rangos CIDR de impresoras conocidas |
| `PendingTaskPollingMinutes` | DWORD | `3` | Frecuencia del ciclo de monitoreo |
| `BootstrapDomains` | String | `"robles.ai,iol.pe,sistemas.com.pe"` | Dominios para health check de licencia |
| `RoblesAiLicenseSerial` | String | `""` | Número de serie de licencia |

La configuración se edita desde el menú **Configuración de Valores** del Tray. El Tray envía los cambios al servicio por Named Pipe; el servicio es el único que escribe en HKLM.

---

## Protocolo Named Pipe

- Pipe: `\\.\pipe\AlwaysPrintService`
- Formato: JSON por líneas (`\n`-delimited), un request → una response
- DACL: LocalSystem = FullControl, AuthenticatedUsers = ReadWrite

| Tipo de mensaje | Dirección | Descripción |
|---|---|---|
| `Ping` / `Pong` | Tray → Servicio | Comprobación de liveness |
| `TrayInitialized` | Tray → Servicio | Handshake post-bootstrap |
| `UpdateConfiguration` | Tray → Servicio | Actualizar configuración en Registro |
| `GetCurrentConfiguration` | Tray → Servicio | Leer configuración actual |
| `CheckCorporateQueue` | Tray → Servicio | Inspeccionar cola de impresión por WMI |
| `CheckServiceStatus` | Tray → Servicio | Estado + path + start time de un servicio Windows |
| `Ack` / `Error` | Servicio → Tray | Respuesta genérica |

---

## Ciclo de vida del servicio

```
Starting
  → WaitingUser       (si no hay sesión interactiva; polling cada 60 s)
  → TrayStarting      (lanza AlwaysPrintTray.exe en la sesión del usuario)
  → TrayStarted       (Tray confirmó handshake exitoso en < 5 min)
  → Running           (ciclo de monitoreo activo)
  → TrayError         (timeout de handshake → SCM reinicia el servicio)
  → Stopping / Stopped
```

El servicio lanza el Tray usando `WTSQueryUserToken` + `CreateProcessAsUser` para cruzar desde Session 0 a la sesión interactiva del usuario, sin mostrar UI directamente.

---

## Bootstrap del Tray

Al arrancar, el Tray realiza HTTP GET a `https://alwaysprint.{dominio}/health` para cada dominio en `BootstrapDomains`, en orden. El primero que devuelva HTTP 200 se considera válido y el Tray envía `TrayInitialized { success: true }` al servicio.

Si ningún dominio responde, el Tray envía `TrayInitialized { success: false }` y continúa operando en modo local (las funciones de registro e impresión locales siguen activas).

---

## Logs y diagnóstico

```powershell
# Ver eventos recientes (Event Viewer → Application → Source: AlwaysPrint)
Get-EventLog -LogName Application -Source AlwaysPrint -Newest 30

# Estado del servicio
Get-Service AlwaysPrintService

# Verificar registro
Get-Item 'HKLM:\SOFTWARE\Robles.AI\AlwaysPrint'

# Debug del servicio en consola (sin SCM)
.\dist\AlwaysPrintService.exe /console
```

---

## Solución de problemas

| Síntoma | Causa probable | Acción |
|---|---|---|
| El Tray no aparece tras iniciar el servicio | No hay sesión interactiva o `CreateProcessAsUser` falló | Revisar Event Log (EvtId 1010). Verificar que el servicio corre como LocalSystem. |
| El servicio se detiene a los 5 minutos | Tray no completó handshake (TrayError) | El SCM lo reiniciará. Revisar que `AlwaysPrintTray.exe` existe junto al servicio. |
| `CheckCorporateQueue` devuelve `exists: false` | La cola no existe o WMI falló | Verificar con `Get-Printer`. Revisar permisos WMI del servicio. |
| MSI falla con error 1603 | DLL faltante en `dist\` | Ejecutar `build.ps1` completo. Verificar que todos los archivos de `dist\` existen antes de llamar a WiX. |
| Event Log source no registrado | Primera instalación sin MSI | El servicio intenta crearlo en runtime. Si falla, ejecutar como admin: `[System.Diagnostics.EventLog]::CreateEventSource('AlwaysPrint','Application')` |

---

## Licencia / Contacto

© 2025 **Robles.AI** — antonio@robles.ai  
Uso interno corporativo BBVA. No distribuir externamente.
