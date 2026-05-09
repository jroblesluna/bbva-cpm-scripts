# AlwaysPrintService

Servicio Windows que gestiona la impresión corporativa y lanza el Tray en la sesión del usuario.

## Descripción

**AlwaysPrintService** es el componente central de AlwaysPrint. Corre como servicio Windows con cuenta LocalSystem, sin acceso a Internet, y gestiona:

- Monitoreo de colas de impresión
- Gestión de configuración en Registry
- Lanzamiento de AlwaysPrintTray en la sesión del usuario
- Exposición de Named Pipe para comunicación con el Tray
- Cola de tareas asíncronas

## Estructura

```
AlwaysPrintService/
├── Pipe/                       # Comunicación Named Pipe
│   ├── PipeServer.cs          # Servidor Named Pipe
│   └── MessageDispatcher.cs   # Despacho de mensajes
├── Queue/                      # Cola de tareas
│   └── TaskQueueManager.cs    # Gestión de tareas asíncronas
├── Tasks/                      # Tareas ejecutables
│   ├── UpdateConfiguration.cs # Actualizar configuración
│   ├── CheckCorporateQueue.cs # Verificar cola de impresión
│   └── CheckServiceStatus.cs  # Verificar estado del servicio
├── UserSession/                # Gestión de sesión de usuario
│   ├── NativeMethods.cs       # P/Invoke para Win32 API
│   ├── InteractiveProcessLauncher.cs # Lanzar proceso en sesión interactiva
│   └── SessionMonitor.cs      # Monitoreo de sesión de usuario
├── AlwaysPrintService.cs      # Clase principal del servicio
└── Program.cs                  # Punto de entrada
```

## Componentes Principales

### Pipe

**PipeServer**: Servidor Named Pipe que escucha conexiones del Tray.
- Nombre: `\\.\pipe\AlwaysPrintService`
- DACL: LocalSystem = FullControl, AuthenticatedUsers = ReadWrite
- Formato: JSON por líneas (`\n`-delimited)

**MessageDispatcher**: Procesa mensajes recibidos y genera respuestas.

### Queue

**TaskQueueManager**: Cola de tareas asíncronas usando `BlockingCollection<T>`.
- Permite encolar tareas desde cualquier thread
- Procesa tareas en orden FIFO
- Thread dedicado para procesamiento

### Tasks

**UpdateConfiguration**: Actualiza configuración en Registry.

**CheckCorporateQueue**: Verifica existencia y estado de la cola de impresión usando WMI.

**CheckServiceStatus**: Devuelve estado actual del servicio.

### UserSession

**NativeMethods**: P/Invoke para Win32 API:
- `WTSQueryUserToken`: Obtener token de usuario de sesión
- `CreateProcessAsUser`: Crear proceso en sesión del usuario
- `WTSGetActiveConsoleSessionId`: Obtener ID de sesión activa

**InteractiveProcessLauncher**: Lanza AlwaysPrintTray.exe en la sesión del usuario desde Session 0.

**SessionMonitor**: Monitorea cambios de sesión (logon/logoff) usando eventos del SCM.

## Ciclo de Vida

```
Starting
  → WaitingUser       (espera sesión interactiva)
  → TrayStarting      (lanza AlwaysPrintTray.exe)
  → TrayStarted       (Tray confirmó handshake)
  → Running           (ciclo de monitoreo activo)
       ↓ logoff
  → WaitingUser       (mata el Tray, espera nueva sesión)
  → TrayError         (timeout de handshake → SCM reinicia)
  → Stopping / Stopped
```

## Configuración

Lee configuración de `HKLM\SOFTWARE\Robles.AI\AlwaysPrint`:
- `CorporateQueueName`
- `SearchTargets`
- `PendingTaskPollingMinutes`
- `BootstrapDomains`
- `RoblesAiLicenseSerial`
- `CloudEnabled`
- `CloudApiUrl`
- `CloudApiKey`

## Logs

Escribe logs en:
- Event Log de Windows (Application log, source: AlwaysPrint)
- Archivo: `C:\ProgramData\AlwaysPrint\logs\AlwaysPrint_yyyyMMdd.log`

Event IDs: 1000-1099 (ver README principal para lista completa)

## Modo Consola

Para debugging, puede ejecutarse en modo consola sin registrarse en el SCM:

```powershell
.\AlwaysPrintService.exe /console
```

## Target Framework

- .NET Framework 4.8

## Dependencias

- AlwaysPrint.Shared
- Newtonsoft.Json
- System.ServiceProcess

---

**Robles.AI**  
Email: antonio@robles.ai  
Teléfono: +1 408 590 0153  
Web: https://robles.ai

---

© 2026 Inversiones On Line SAC - Todos los derechos reservados  
Producto de la familia de automatización Robles.AI  
Prohibida la utilización sin autorización de Inversiones On Line SAC
