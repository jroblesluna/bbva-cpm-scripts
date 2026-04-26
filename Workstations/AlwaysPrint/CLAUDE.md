# CLAUDE.md — AlwaysPrint

Guía para agentes de IA al trabajar con esta solución.

## Qué es esto

Solución C# .NET Framework 4.8 compuesta por un Windows Service (`AlwaysPrintService`) y una Tray app WinForms (`AlwaysPrintTray`) que se comunican por Named Pipe. El servicio corre como LocalSystem en Session 0; el Tray corre en la sesión interactiva del usuario, lanzado por el servicio con `CreateProcessAsUser`.

## Build

```powershell
# Un solo comando desde Workstations/AlwaysPrint/
.\build.ps1
# Produce: dist\ con los EXEs/DLLs, y AlwaysPrint.msi
```

Requiere .NET SDK 8+ y wix CLI (el script lo instala/actualiza automáticamente).  
Target: `net48`, x64, framework-dependent (no self-contained).

Para verificar que compila sin errores:

```powershell
dotnet build AlwaysPrint.sln -c Release --nologo
# Debe terminar con: 0 Errores, 0 Advertencias
```

## Proyectos y namespaces

| Proyecto | Namespace raíz | Rol |
|---|---|---|
| `AlwaysPrint.Shared` | `AlwaysPrint.Shared` | DTOs, config, logging — referenciado por ambos EXEs |
| `AlwaysPrintService` | `AlwaysPrintService` | Windows Service — toda escritura en Registro ocurre aquí |
| `AlwaysPrintTray` | `AlwaysPrintTray` | WinForms tray — nunca escribe en HKLM directamente |

## Archivos críticos

| Archivo | Función |
|---|---|
| `AlwaysPrintService/AlwaysPrintWindowsService.cs` | Orquestación completa: ciclo de vida, máquina de estados, bucle de sesión |
| `AlwaysPrintService/Pipe/PipeServer.cs` | Named pipe server; un thread por cliente; DACL explícita |
| `AlwaysPrintService/Pipe/MessageDispatcher.cs` | Router de mensajes entrantes hacia handlers/tareas |
| `AlwaysPrintService/Queue/TaskQueueManager.cs` | `BlockingCollection<IServiceTask>` con worker thread dedicado |
| `AlwaysPrintService/UserSession/InteractiveProcessLauncher.cs` | `CreateProcessAsUser` para lanzar el Tray desde Session 0 |
| `AlwaysPrintService/UserSession/NativeMethods.cs` | Todos los P/Invoke de WTS/advapi32/userenv |
| `AlwaysPrint.Shared/Configuration/RegistryConfigManager.cs` | Única clase que lee/escribe `HKLM\SOFTWARE\Robles.AI\AlwaysPrint` |
| `AlwaysPrint.Shared/Messages/PipeConstants.cs` | Nombre del pipe centralizado (`"AlwaysPrintService"`) — usar siempre esta constante |
| `AlwaysPrint.Shared/Messages/PipeMessage.cs` + `Payloads.cs` | Contrato completo del protocolo Named Pipe |
| `AlwaysPrintTray/TrayApplicationContext.cs` | Lógica principal del tray: icono, menú, bootstrap, pipe, marshal UI |
| `AlwaysPrintTray/Bootstrap/DomainHealthChecker.cs` | HTTP GET a `alwaysprint.{dominio}/health` → HTTP 200 = OK |
| `Product.wxs` | Instalador WiX v4: service, event log source, registry defaults |

## Protocolo Named Pipe

- Pipe name: `PipeConstants.PipeName` → `\\.\pipe\AlwaysPrintService`
- Framing: una línea JSON por mensaje (`\n`-terminated)
- Cada `PipeMessage` tiene `id`, `correlationId`, `type` (enum `MessageType`), `payload` (JSON inner DTO)
- El cliente envía un request y lee la siguiente línea como response (sincrónico con lock)
- Timeout de lectura en el cliente: 30 s — si el servidor no responde en ese tiempo, `Send` devuelve `null`
- Nuevos comandos: agregar valor a `MessageType`, nuevo payload en `Payloads.cs`, handler en `MessageDispatcher.Dispatch()`

## Ciclo de vida del servicio (estados)

```
Starting → WaitingUser → TrayStarting → TrayStarted → Running
                ↑               ↓ (logoff)                ↓ (logoff)
                └───────────────┴─────────────────────────┘
                                     ↘ TrayError (timeout 5 min) → SCM reinicia
```

El ciclo WaitingUser → Running se repite en cada logon/logoff sin reiniciar el servicio (`RunSessionLoop`).

### Mecanismo de wake-up entre threads

`_userArrivedGate` (`ManualResetEventSlim`) es el único mecanismo de señalización entre `OnSessionChange` y los bucles de espera:

- `OnSessionChange` (logon/unlock) → `_userArrivedGate.Set()` → despierta `WaitForUser`
- `OnSessionChange` (logoff) → `_userArrivedGate.Set()` → despierta `MonitoringLoop` para que detecte el cambio de estado y salga
- `OnStop` → `_userArrivedGate.Set()` + `_cts.Cancel()` → desbloquea cualquier espera activa

No usar `Monitor.PulseAll` ni `Thread.Interrupt` — ambos son incorrectos en este contexto.

## Agregar una nueva tarea al servicio

1. Crear `AlwaysPrintService/Tasks/MiNuevaTarea.cs` implementando `IServiceTask`
2. Agregar el tipo de mensaje a `MessageType.cs` y los DTOs a `Payloads.cs`
3. Agregar el `case` correspondiente en `MessageDispatcher.Dispatch()`
4. Si la tarea es de larga duración: encolarla con `_taskQueue.Enqueue(...)` y devolver `Ack` inmediato
5. Si necesita resultado síncrono (como `CheckCorporateQueue`): ejecutar inline y devolver `result.Data` como payload

El dispatcher debe devolver el payload tipado específico (no `AckPayload` genérico) para que el Tray pueda deserializarlo correctamente con `GetPayload<T>()`.

## Registro de Windows

Clave: `HKLM\SOFTWARE\Robles.AI\AlwaysPrint`

El servicio llama a `_registry.EnsureDefaults()` en cada arranque (idempotente). Al modificar un valor:
- El Tray envía `UpdateConfiguration` con el nuevo `AppConfiguration` serializado
- `MessageDispatcher` encola un `UpdateConfigurationTask`
- `UpdateConfigurationTask.Execute()` llama a `_registry.Save()` con validación y sanitización

`RegistryConfigManager.Load()` loggea errores con `EventLogWriter.WriteWarning` en lugar de silenciarlos — nunca usar catch vacío en esta clase.

## Logging (Event IDs fijos)

Todos los eventos van a `EventLog Application`, source `AlwaysPrint`.

| Rango | Categoría |
|---|---|
| 1000–1009 | Ciclo de vida del servicio |
| 1010 | TrayError |
| 1020–1022 | Tareas (dispatched / completed / failed) |
| 1030 | Configuración guardada |
| 1090–1091 | Warning/Error genérico |

## Thread safety en el Tray

El Tray es una app WinForms sin formularios visibles (solo tray icon). Reglas:

- `ShowBalloon` y `ExitApplication` usan `_uiContext.Post(...)` — el `SynchronizationContext` se captura en el constructor del hilo UI
- No usar `Application.OpenForms[0]?.BeginInvoke` — en apps tray-only no hay formularios abiertos
- `ConfigurationForm` carga datos en el evento `Shown`, no en el constructor, para no bloquear el hilo UI durante la apertura
- `PipeClient.Send` está protegido con `lock` — es seguro llamarlo desde cualquier hilo

## Añadir nueva forma al Tray

1. Crear `AlwaysPrintTray/Forms/MiForm.cs` como `Form` normal en código (sin designer)
2. Añadir el ítem al menú en `TrayApplicationContext.BuildTrayIcon()`
3. Si necesita datos del servicio: usar `_pipe.Send(PipeMessage.Create(...))` — es sincrónico y thread-safe
4. Cargar datos del servicio en el evento `Shown` del formulario, no en el constructor

## Convenciones de código

- Comentarios técnicos en inglés
- Sin comentarios obvios; solo cuando el `por qué` no es evidente del código
- P/Invoke en `NativeMethods.cs` únicamente — no dispersar `DllImport` en otros archivos
- El Tray nunca escribe en HKLM — siempre a través del servicio por Named Pipe
- `RegistryConfigManager.Sanitize()` se aplica siempre antes de persistir strings
- WQL: siempre escapar con `EscapeWql()` antes de interpolar en consultas WMI
- `HttpClient` siempre `static readonly` — nunca instanciar por llamada
- APIs de .NET Core no disponibles en net48: `string.Contains(string, StringComparison)` → usar `IndexOf`; `Channel<T>` → usar `BlockingCollection`

## Instalador WiX

`Product.wxs` usa WiX v4 con extensión `WixToolset.Util.wixext`.

GUIDs fijos (no regenerar en actualizaciones — solo cambiar la versión del assembly):
- UpgradeCode: `C7A4B5D6-A100-4E00-8F00-BBVA00000001`
- Componente Service: `C7A4B5D6-B200-4E00-8F00-BBVA00000002`
- Componente Tray: `C7A4B5D6-C300-4E00-8F00-BBVA00000003`

La versión del paquete MSI se toma automáticamente del file version de `AlwaysPrintService.exe` mediante `!(bind.FileVersion.filServiceExe)` — no hardcodear `Version` en `Product.wxs`.

Al agregar un nuevo archivo al output: añadir `<File Source=".\dist\nuevo.dll" />` dentro del componente correspondiente en `Product.wxs`.
