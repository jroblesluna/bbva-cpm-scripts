# CLAUDE.md — AlwaysPrint

Guía para Claude Code al trabajar con esta solución.

## Qué es esto

Solución C# .NET Framework 4.8 compuesta por un Windows Service (`AlwaysPrintService`) y una Tray app WinForms (`AlwaysPrintTray`) que se comunican por Named Pipe. El servicio corre como LocalSystem; el Tray corre en la sesión interactiva del usuario, lanzado por el servicio con `CreateProcessAsUser`.

## Build

```powershell
# Un solo comando desde Workstations/AlwaysPrint/
.\build.ps1
# Produce: dist\ con los EXEs/DLLs, y AlwaysPrint.msi
```

Requiere .NET SDK 8+ y wix CLI (el script lo instala si falta).  
Target: `net48`, x64, framework-dependent (no self-contained).

## Proyectos y namespaces

| Proyecto | Namespace raíz | Rol |
|---|---|---|
| `AlwaysPrint.Shared` | `AlwaysPrint.Shared` | DTOs, config, logging — referenciado por ambos EXEs |
| `AlwaysPrintService` | `AlwaysPrintService` | Windows Service — toda escritura en Registro ocurre aquí |
| `AlwaysPrintTray` | `AlwaysPrintTray` | WinForms tray — nunca escribe en HKLM directamente |

## Archivos críticos

| Archivo | Función |
|---|---|
| `AlwaysPrintService/AlwaysPrintWindowsService.cs` | Orquestación completa del ciclo de vida del servicio y máquina de estados |
| `AlwaysPrintService/Pipe/PipeServer.cs` | Named pipe server; un thread por cliente; DACL explícita |
| `AlwaysPrintService/Pipe/MessageDispatcher.cs` | Router de mensajes entrantes hacia handlers/tareas |
| `AlwaysPrintService/Queue/TaskQueueManager.cs` | `BlockingCollection<IServiceTask>` con worker thread dedicado |
| `AlwaysPrintService/UserSession/InteractiveProcessLauncher.cs` | `CreateProcessAsUser` para lanzar el Tray desde Session 0 |
| `AlwaysPrintService/UserSession/NativeMethods.cs` | Todos los P/Invoke de WTS/advapi32/userenv |
| `AlwaysPrint.Shared/Configuration/RegistryConfigManager.cs` | Única clase que lee/escribe `HKLM\SOFTWARE\Robles.AI\AlwaysPrint` |
| `AlwaysPrint.Shared/Messages/PipeMessage.cs` + `Payloads.cs` | Contrato completo del protocolo Named Pipe |
| `AlwaysPrintTray/TrayApplicationContext.cs` | Lógica principal del tray: icono, menú, bootstrap, pipe |
| `AlwaysPrintTray/Bootstrap/DomainHealthChecker.cs` | HTTP GET a `alwaysprint.{dominio}/health` → HTTP 200 = OK |
| `Product.wxs` | Instalador WiX v4: service, event log source, registry defaults |

## Protocolo Named Pipe

- Pipe name: `AlwaysPrintService` → `\\.\pipe\AlwaysPrintService`
- Framing: una línea JSON por mensaje (`\n`-terminated)
- Cada `PipeMessage` tiene `id`, `correlationId`, `type` (enum `MessageType`), `payload` (JSON inner DTO)
- El cliente envía un request y lee la siguiente línea como response (sincrónico con lock)
- Nuevos comandos: agregar valor a `MessageType`, nuevo payload en `Payloads.cs`, handler en `MessageDispatcher.Dispatch()`

## Agregar una nueva tarea al servicio

1. Crear `AlwaysPrintService/Tasks/MiNuevaTarea.cs` implementando `IServiceTask`
2. Agregar el tipo de mensaje a `MessageType.cs` y los DTOs a `Payloads.cs`
3. Agregar el `case` correspondiente en `MessageDispatcher.Dispatch()`
4. Si la tarea es de larga duración: encollarla con `_taskQueue.Enqueue(...)` y devolver `Ack` inmediato
5. Si necesita resultado síncrono (como `CheckCorporateQueue`): ejecutar inline y devolver el resultado

## Ciclo de vida del servicio (estados)

```
Starting → WaitingUser → TrayStarting → TrayStarted → Running
                                     ↘ TrayError (timeout 5 min) → SCM reinicia
```

- `OnSessionChange` del SCM detecta logon/logoff y activa/mata el Tray
- `WTSGetActiveConsoleSessionId` + `WTSQueryUserToken` + `CreateProcessAsUser` para cruzar Session 0

## Registro de Windows

Clave: `HKLM\SOFTWARE\Robles.AI\AlwaysPrint`

El servicio llama a `_registry.EnsureDefaults()` en cada arranque (idempotente). Al modificar un valor:
- El Tray envía `UpdateConfiguration` con el nuevo `AppConfiguration` serializado
- `MessageDispatcher` encola un `UpdateConfigurationTask`
- `UpdateConfigurationTask.Execute()` llama a `_registry.Save()` con validación

## Logging (Event IDs fijos)

Todos los eventos van a `EventLog Application`, source `AlwaysPrint`.

| Rango | Categoría |
|---|---|
| 1000–1009 | Ciclo de vida del servicio |
| 1010 | TrayError |
| 1020–1022 | Tareas (dispatched / completed / failed) |
| 1030 | Configuración guardada |
| 1090–1091 | Warning/Error genérico |

## Añadir nueva forma al Tray

1. Crear `AlwaysPrintTray/Forms/MiForm.cs` como `Form` normal en código (sin designer)
2. Añadir el ítem al menú en `TrayApplicationContext.BuildTrayIcon()`
3. Si necesita datos del servicio: usar `_pipe.Send(PipeMessage.Create(...))` sincrónicamente

## Convenciones de código

- Comentarios técnicos en inglés
- Sin comentarios obvios; solo cuando el `por qué` no es evidente del código
- P/Invoke en `NativeMethods.cs` únicamente — no dispersar `DllImport` en otros archivos
- El Tray nunca escribe en HKLM — siempre a través del servicio por Named Pipe
- `RegistryConfigManager.Sanitize()` se aplica siempre antes de persistir strings
- WQL: siempre escapar con `EscapeWql()` antes de interpolar en consultas WMI

## Instalador WiX

`Product.wxs` usa WiX v4 con extensión `WixToolset.Util.wixext`.  
GUIDs fijos (no regenerar en actualizaciones — solo cambiar `Version`):
- UpgradeCode: `C7A4B5D6-A100-4E00-8F00-BBVA00000001`
- Componente Service: `C7A4B5D6-B200-4E00-8F00-BBVA00000002`
- Componente Tray: `C7A4B5D6-C300-4E00-8F00-BBVA00000003`

Al agregar un nuevo archivo al output: añadir `<File Source=".\dist\nuevo.dll" />` dentro del componente correspondiente en `Product.wxs`.
