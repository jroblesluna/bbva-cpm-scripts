# AlwaysPrint

Software Windows de contingencia complementaria para gestión de impresión corporativa.  
Dos ejecutables cooperan mediante Named Pipe para monitorear y gestionar impresoras desde la workstation.

**Versión:** 1.26.426.HHMM (formato: Major.YY.MMDD.HHMM)  
**Última actualización:** 8 de mayo de 2026

---

## Descripción

**AlwaysPrint** es el cliente Windows que se instala en workstations como **mecanismo de contingencia complementario** al sistema de producción estándar (Lexmark CPM + CUPS). 

**Propósito**:
- ✅ **Contingencia**: Actúa cuando el sistema principal (Lexmark CPM) no está disponible
- ✅ **Monitoreo**: Proporciona visibilidad del estado de impresión local
- ✅ **Gestión centralizada**: Opcionalmente se integra con AlwaysPrint Cloud Manager
- ✅ **Coexistencia**: Funciona junto al sistema de producción sin interferir

**Relación con el sistema de producción**:
- Coexiste con Lexmark CPM (sistema principal de producción)
- Se activa como contingencia cuando CPM no está disponible
- No reemplaza ni interfiere con el sistema principal
- Proporciona capa adicional de monitoreo y gestión

### Arquitectura de Comunicación

```
┌─────────────────────────────────────────────────────────────┐
│                    WORKSTATION WINDOWS                       │
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │  AlwaysPrintService.exe                            │    │
│  │  - Cuenta: LocalSystem (sin acceso a Internet)     │    │
│  │  - Gestiona impresión local                        │    │
│  │  - Lanza AlwaysPrintTray                           │    │
│  │  - Expone Named Pipe                               │    │
│  └────────────────┬───────────────────────────────────┘    │
│                   │ Named Pipe (IPC local)                  │
│  ┌────────────────▼───────────────────────────────────┐    │
│  │  AlwaysPrintTray.exe                               │    │
│  │  - Cuenta: Usuario (con acceso a Internet)         │    │
│  │  - Interfaz de usuario (system tray)               │    │
│  │  - Cliente HTTP para Cloud Manager (opcional)      │    │
│  └────────────────┬───────────────────────────────────┘    │
└───────────────────┼─────────────────────────────────────────┘
                    │
                    │ HTTPS (opcional, vía Proxy)
                    │
┌───────────────────▼─────────────────────────────────────────┐
│              ALWAYSPRINT CLOUD MANAGER                       │
│              (Plataforma SaaS - Opcional)                    │
└──────────────────────────────────────────────────────────────┘
```

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
- PowerShell 5.0 o superior

**Nota:** No es necesario tener .NET Framework 4.8 SDK instalado. El .NET SDK 8+ puede compilar proyectos net48 usando los reference assemblies incluidos.

---

## Build y empaquetado

Desde la carpeta `AlwaysPrintProject/Client/`, en PowerShell:

```powershell
.\build.ps1
```

Qué hace el script:

1. Limpia artefactos anteriores (`bin`, `obj`, `dist`, `.wix`, `AlwaysPrint.msi`).
2. Genera `logo.ico` desde `logo.png` si no existe (usando `convert-icon.ps1`).
3. Actualiza `wix` CLI global; si no está instalado, lo instala desde cero.
4. Registra la extensión `WixToolset.Util.wixext` (idempotente).
5. Genera versión automática basada en fecha/hora: `1.YY.MMDD.HHMM` (ej: `1.26.426.1211` = 26 abril 2026, 12:11).
6. Publica `AlwaysPrintService` a `.\dist\` (`net48`, framework-dependent, x64).
7. Publica `AlwaysPrintTray` a `.\dist\` (misma carpeta, agrega el segundo EXE).
8. Verifica que los 4 archivos requeridos existen en `dist\` antes de llamar a WiX.
9. Compila `Product.wxs` → `.\AlwaysPrint.msi` con la versión generada.

Salida esperada:

```
dist\
  AlwaysPrintService.exe
  AlwaysPrintService.exe.config
  AlwaysPrintTray.exe
  AlwaysPrintTray.exe.config
  AlwaysPrint.Shared.dll
  Newtonsoft.Json.dll
  *.pdb (símbolos de debug)
AlwaysPrint.msi
```

> **Nota:** al ser net48 framework-dependent, la máquina destino debe tener .NET Framework 4.8, incluido en Windows 10 1903+ y Windows 11.

**Verificar compilación sin errores:**

```powershell
dotnet build AlwaysPrint.sln -c Release --nologo
# Debe terminar con: 0 Errores, 0 Advertencias
```

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

**ProductCode Fijo**: `C7A4B5D6-A200-4E00-8F00-0BBA00000001`

Todos los MSIs de AlwaysPrint comparten el mismo ProductCode, por lo que:
- Windows Installer los reconoce como el mismo producto
- Cualquier MSI puede instalar, actualizar o desinstalar
- No importa qué versión esté instalada o qué versión tenga el MSI
- Permite downgrades (instalar versión más antigua)

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

### Instalación con Integración Cloud

Para habilitar la integración con AlwaysPrint Cloud Manager, configurar durante la instalación:

```powershell
# Instalar con configuración cloud
msiexec /i AlwaysPrint.msi /qn ^
  CLOUDENABLEDPROP=1 ^
  CLOUDAPIURLPROP=https://api.alwaysprint.com ^
  CLOUDAPIKEYPROP=org_bbva_xxxxxxxx ^
  /L*v install.log
```

O configurar manualmente después de la instalación en el Registry:
- `HKLM\SOFTWARE\Robles.AI\AlwaysPrint\CloudEnabled` = 1
- `HKLM\SOFTWARE\Robles.AI\AlwaysPrint\CloudApiUrl` = https://api.alwaysprint.com
- `HKLM\SOFTWARE\Robles.AI\AlwaysPrint\CloudApiKey` = org_bbva_xxxxxxxx

---

## Configuración

Ubicación en Registro: `HKEY_LOCAL_MACHINE\SOFTWARE\Robles.AI\AlwaysPrint`

| Valor | Tipo | Default | Descripción |
|---|---|---|---|
| `CorporateQueueName` | String | `""` | Nombre de la cola de impresión corporativa (ej. `LexmarkBBVA`) |
| `SearchTargets` | String (JSON) | `{"ips":"","ranges":""}` | IPs y rangos CIDR de impresoras conocidas |
| `PendingTaskPollingMinutes` | DWORD | `3` | Frecuencia del ciclo de monitoreo (1–1440 min) |
| `BootstrapDomains` | String | `"apps.iol.pe,iol.pe,sistemas.com.pe,robles.ai"` | Dominios para health check de licencia (CSV) |
| `RoblesAiLicenseSerial` | String | `""` | Número de serie de licencia |
| `CloudEnabled` | DWORD | `0` | 1 = habilitar integración con Cloud Manager |
| `CloudApiUrl` | String | `""` | URL del backend (ej: https://api.alwaysprint.com) |
| `CloudApiKey` | String | `""` | Organization API Key para registro inicial |

La configuración se edita desde el menú **Configuración de Valores** del Tray. El Tray envía los cambios al servicio por Named Pipe; el servicio es el único que escribe en HKLM.

---

## Integración con Cloud Manager

AlwaysPrint puede integrarse opcionalmente con **AlwaysPrint Cloud Manager** para monitoreo y gestión centralizada.

### Flujo de Registro

```
1. Admin instala AlwaysPrint.msi con configuración cloud
2. AlwaysPrintTray lee CloudEnabled, CloudApiUrl, CloudApiKey del Registry
3. Si CloudEnabled = 1:
   a. Tray envía POST /api/v1/workstations/register
   b. Backend devuelve workstation_id y workstation_api_key
   c. Tray guarda credenciales en HKCU\SOFTWARE\Robles.AI\AlwaysPrint\Cloud
   d. Tray inicia heartbeat cada 60 segundos
```

### Operación con Cloud

```
Cada 60 segundos:
  Tray → POST /api/v1/workstations/{id}/heartbeat
  Backend actualiza last_seen y status = "online"

Cuando ocurre evento:
  Service → Tray (Named Pipe): ReportTelemetry
  Tray → POST /api/v1/workstations/{id}/telemetry

Cada 5 minutos:
  Tray → GET /api/v1/workstations/{id}/config
  Si hay cambios:
    Tray → Service (Named Pipe): CloudConfigurationReceived
    Service aplica nueva configuración
```

Ver documentación completa en [AlwaysPrint Cloud Manager](../Cloud/README.md).

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
  → TrayStarted       (Tray confirmó handshake en < 30 min)
  → Running           (ciclo de monitoreo activo)
       ↓ logoff
  → WaitingUser       (mata el Tray, espera nueva sesión → relanza automáticamente)
  → TrayError         (timeout de handshake → SCM reinicia el servicio)
  → Stopping / Stopped
```

**Detalles del ciclo:**
- El ciclo WaitingUser → Running se repite en cada logon/logoff sin reiniciar el servicio
- El servicio lanza el Tray usando `WTSQueryUserToken` + `CreateProcessAsUser` para cruzar desde Session 0 a la sesión interactiva
- Timeout de handshake del Tray: **1800 segundos (30 minutos)**
- Polling de sesión de usuario: **60 segundos**
- El servicio espera 3 segundos después de detectar sesión antes de lanzar el Tray (para asegurar que el Named Pipe esté listo)
- El Tray realiza hasta 5 reintentos de conexión al Named Pipe con 1 segundo entre intentos

---

## Bootstrap del Tray

Al arrancar, el Tray realiza HTTP GET a `https://alwaysprint.{dominio}/api/v1/health` para cada dominio en `BootstrapDomains`, en orden. El primero que devuelva HTTP 200 con JSON válido se considera válido.

**IMPORTANTE**: Los dominios bootstrap deben ser **dominios base** (ej: `apps.iol.pe`, `iol.pe`). El prefijo `alwaysprint.` se añade automáticamente.

**Ejemplo de configuración**:
```
BootstrapDomains = "apps.iol.pe,sistemas.com.pe,iol.pe,robles.ai"
```

**URLs generadas automáticamente**:
- `https://alwaysprint.apps.iol.pe/api/v1/health`
- `https://alwaysprint.sistemas.com.pe/api/v1/health`
- `https://alwaysprint.iol.pe/api/v1/health`
- `https://alwaysprint.robles.ai/api/v1/health`

**Comportamiento**:
- Si alguno responde con HTTP 200 y JSON válido: envía `TrayInitialized { success: true }` y muestra notificación de éxito.
- Si ninguno responde: envía `TrayInitialized { success: false }` y continúa en modo local (las funciones de impresión locales siguen activas).

El `HttpClient` es estático y reutilizable (no se instancia por llamada).

**Detalles de implementación:**
- Timeout HTTP: 10 segundos por dominio
- Dominios por defecto: `apps.iol.pe,iol.pe,sistemas.com.pe,robles.ai`
- El health check se ejecuta en un thread de fondo para no bloquear la UI
- Si el health check falla, el Tray sigue funcionando pero muestra un warning balloon
- La respuesta debe ser JSON válido (se valida parseando el body)

---

## Logs y diagnóstico

```powershell
# Ver logs del día actual
Get-Content "C:\ProgramData\AlwaysPrint\logs\AlwaysPrint_$(Get-Date -Format 'yyyyMMdd').log" -Tail 50

# Ver logs de los últimos 7 días
Get-ChildItem "C:\ProgramData\AlwaysPrint\logs\AlwaysPrint_*.log" | 
    Where-Object { $_.LastWriteTime -gt (Get-Date).AddDays(-7) } | 
    Sort-Object LastWriteTime -Descending

# Estado del servicio
Get-Service AlwaysPrintService

# Verificar registro
Get-Item 'HKLM:\SOFTWARE\Robles.AI\AlwaysPrint'

# Debug del servicio en consola (sin SCM, sin admin)
.\dist\AlwaysPrintService.exe /console
```

**Ubicación de logs:**
- Directorio: `C:\ProgramData\AlwaysPrint\logs\`
- Formato de archivo: `AlwaysPrint_yyyyMMdd.log` (un archivo por día)
- Formato de línea: `[yyyy-MM-dd HH:mm:ss] [SVC|APP] Event XXXX: mensaje`
- Rotación: automática diaria (no hay límite de tamaño, se crea un nuevo archivo cada día)

### Event IDs de referencia

| ID | Significado | Origen |
|---|---|---|
| 1000 | Servicio iniciado | SVC |
| 1001 | Servicio detenido | SVC |
| 1002 | Instancia duplicada detectada | SVC |
| 1003 | Tray eliminado (logoff o arranque) | SVC |
| 1004 | Cola de tareas limpiada | SVC |
| 1005 | Pipe server iniciado | SVC |
| 1006 | Esperando sesión de usuario | SVC |
| 1007 | Sesión de usuario detectada | SVC |
| 1008 | Tray iniciando | SVC |
| 1009 | Tray iniciado | SVC/APP |
| 1010 | Error en el Tray | SVC/APP |
| 1020 | Tarea despachada | SVC |
| 1021 | Tarea completada | SVC |
| 1022 | Tarea fallida | SVC |
| 1030 | Configuración guardada | SVC |
| 1090 | Warning genérico | SVC/APP |
| 1091 | Error genérico | SVC/APP |

**Nota:** Los eventos con origen `SVC` provienen del servicio, `APP` del Tray, y `SVC/APP` pueden venir de ambos.

---

## Solución de problemas

| Síntoma | Causa probable | Acción |
|---|---|---|
| El Tray no aparece tras iniciar el servicio | No hay sesión interactiva o `CreateProcessAsUser` falló | Revisar logs en `C:\ProgramData\AlwaysPrint\logs\` (Event 1010). Verificar que el servicio corre como LocalSystem. |
| El Tray no reaparece tras un logoff/logon | Bug en el ciclo de sesión | Revisar logs alrededor de Event 1003 y 1006. El ciclo debería reiniciarse automáticamente. |
| El servicio se detiene a los 30 minutos | Tray no completó handshake (TrayError, Event 1010) | El SCM lo reiniciará. Verificar que `AlwaysPrintTray.exe` existe en la misma carpeta que el servicio. Revisar logs del Tray (origen APP). |
| `CheckCorporateQueue` devuelve `exists: false` | La cola no existe o WMI falló | Verificar con `Get-Printer -Name "LexmarkBBVA"`. Revisar permisos WMI del servicio. |
| Configuración no se guarda | El Tray no tiene respuesta del servicio | Verificar que el pipe está activo con `Get-Service AlwaysPrintService`. Revisar Event 1091 en logs. |
| MSI falla con error 1603 | Archivo faltante en `dist\` o wix no instalado | Ejecutar `build.ps1` completo. El script verifica los 4 archivos requeridos antes de llamar a WiX. |
| Logs no se generan | Permisos en `C:\ProgramData\AlwaysPrint\logs\` | El servicio crea el directorio automáticamente. Verificar permisos de escritura para LocalSystem. |
| Tray no se conecta al pipe | Servicio no está corriendo o Named Pipe no está listo | El Tray reintenta 5 veces con 1s de espera. Verificar que el servicio está en estado Running. |

---

## Licencia / Contacto

**Robles.AI**  
Email: antonio@robles.ai  
Teléfono: +1 408 590 0153  
Web: https://robles.ai

---

© 2026 Inversiones On Line SAC - Todos los derechos reservados  
Producto de la familia de automatización Robles.AI  
Prohibida la utilización sin autorización de Inversiones On Line SAC

## Documentación Adicional

- [AlwaysPrint Cloud Manager](../../Cloud/README.md) - Plataforma SaaS de gestión centralizada
- [Visión General del Sistema](../../SYSTEM-OVERVIEW.md) - Ecosistema completo
- [Proyecto Principal](../README.md) - AlwaysPrint Project
