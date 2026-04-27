# CLAUDE.md — AlwaysPrint

Guía para agentes de IA al trabajar con esta solución.

**Versión:** 1.26.426.HHMM (formato: Major.YY.MMDD.HHMM)  
**Última actualización:** 26 de abril de 2026

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

**Versionado automático:**
El script `build.ps1` genera la versión del MSI automáticamente con formato `1.YY.MMDD.HHMM`:
- Major: 1 (fijo)
- Minor: YY (últimos 2 dígitos del año)
- Build: MMDD (mes y día)
- Revision: HHMM (hora y minuto)

Ejemplo: `1.26.426.1211` = 26 de abril de 2026, 12:11

---

## Proyectos y namespaces

| Proyecto | Namespace raíz | Rol |
|---|---|---|
| `AlwaysPrint.Shared` | `AlwaysPrint.Shared` | DTOs, config, logging — referenciado por ambos EXEs |
| `AlwaysPrintService` | `AlwaysPrintService` | Windows Service — toda escritura en Registro ocurre aquí |
| `AlwaysPrintTray` | `AlwaysPrintTray` | WinForms tray — nunca escribe en HKLM directamente |

## Archivos críticos

| Archivo | Función |
|---|---|
| `AlwaysPrintService/AlwaysPrintWindowsService.cs` | Orquestación completa: ciclo de vida, máquina de estados, bucle de sesión. **Punto de entrada principal del servicio.** |
| `AlwaysPrintService/ServiceStateMachine.cs` | Máquina de estados thread-safe con eventos de transición |
| `AlwaysPrintService/Pipe/PipeServer.cs` | Named pipe server; un thread por cliente; DACL explícita (LocalSystem + AuthenticatedUsers) |
| `AlwaysPrintService/Pipe/MessageDispatcher.cs` | Router de mensajes entrantes hacia handlers/tareas. **Aquí se agregan nuevos comandos.** |
| `AlwaysPrintService/Queue/TaskQueueManager.cs` | `BlockingCollection<IServiceTask>` con worker thread dedicado para tareas en background |
| `AlwaysPrintService/UserSession/InteractiveProcessLauncher.cs` | `CreateProcessAsUser` para lanzar el Tray desde Session 0 |
| `AlwaysPrintService/UserSession/SessionMonitor.cs` | Detecta sesiones interactivas usando WTS APIs |
| `AlwaysPrintService/UserSession/NativeMethods.cs` | Todos los P/Invoke de WTS/advapi32/userenv. **No agregar P/Invoke en otros archivos.** |
| `AlwaysPrintService/Tasks/IServiceTask.cs` | Interfaz para todas las tareas ejecutables |
| `AlwaysPrintService/Tasks/CheckCorporateQueueTask.cs` | Inspecciona colas de impresión usando WMI (inline, < 1s) |
| `AlwaysPrintService/Tasks/CheckServiceStatusTask.cs` | Consulta estado de servicios Windows usando WMI (inline, < 1s) |
| `AlwaysPrintService/Tasks/UpdateConfigurationTask.cs` | Actualiza configuración en registro (encolado, modifica estado) |
| `AlwaysPrint.Shared/Configuration/RegistryConfigManager.cs` | Única clase que lee/escribe `HKLM\SOFTWARE\Robles.AI\AlwaysPrint`. **Thread-safe.** |
| `AlwaysPrint.Shared/Configuration/AppConfiguration.cs` | DTO de configuración con valores por defecto |
| `AlwaysPrint.Shared/Logging/AlwaysPrintLogger.cs` | Logger de archivo con rotación diaria. **No usa Event Log.** |
| `AlwaysPrint.Shared/Messages/PipeConstants.cs` | Nombre del pipe centralizado (`"AlwaysPrintService"`) — usar siempre esta constante |
| `AlwaysPrint.Shared/Messages/MessageType.cs` | Enum de tipos de mensaje del protocolo pipe |
| `AlwaysPrint.Shared/Messages/PipeMessage.cs` | Estructura de mensaje con serialización JSON |
| `AlwaysPrint.Shared/Messages/Payloads.cs` | Todos los DTOs de request/response del protocolo pipe |
| `AlwaysPrint.Shared/Models/ServiceState.cs` | Enum de estados del servicio |
| `AlwaysPrintTray/TrayApplicationContext.cs` | Lógica principal del tray: icono, menú, bootstrap, pipe, marshal UI. **Punto de entrada del Tray.** |
| `AlwaysPrintTray/Bootstrap/DomainHealthChecker.cs` | HTTP GET a `alwaysprint.{dominio}/health` → HTTP 200 = OK (timeout 5s) |
| `AlwaysPrintTray/Pipe/PipeClient.cs` | Cliente del Named Pipe con timeout de 30s, thread-safe con lock |
| `AlwaysPrintTray/Forms/AboutForm.cs` | Diálogo "Acerca de" con información de versión |
| `AlwaysPrintTray/Forms/ConfigurationForm.cs` | Formulario de configuración que lee/escribe via pipe |
| `Product.wxs` | Instalador WiX v4: service, registry defaults, iconos. **GUIDs fijos, no regenerar.** |
| `build.ps1` | Script de build completo: limpieza, publish, generación de versión, MSI |
| `convert-icon.ps1` | Convierte logo.png a logo.ico con múltiples resoluciones |

## Protocolo Named Pipe

- Pipe name: `PipeConstants.PipeName` → `\\.\pipe\AlwaysPrintService`
- Framing: una línea JSON por mensaje (`\n`-terminated)
- Cada `PipeMessage` tiene `id`, `correlationId`, `type` (enum `MessageType`), `payload` (JSON inner DTO)
- El cliente envía un request y lee la siguiente línea como response (sincrónico con lock)
- Timeout de lectura en el cliente: **30 segundos** — si el servidor no responde en ese tiempo, `Send` devuelve `null`
- DACL del pipe: LocalSystem = FullControl, AuthenticatedUsers = ReadWrite
- Nuevos comandos: agregar valor a `MessageType`, nuevo payload en `Payloads.cs`, handler en `MessageDispatcher.Dispatch()`

### Tipos de mensaje disponibles

| Tipo | Dirección | Payload Request | Payload Response | Ejecución |
|---|---|---|---|---|
| `Ping` | Tray → Servicio | — | — | Inline |
| `Pong` | Servicio → Tray | — | — | — |
| `TrayInitialized` | Tray → Servicio | `TrayInitializedPayload` | `AckPayload` | Inline + Event |
| `UpdateConfiguration` | Tray → Servicio | `UpdateConfigurationPayload` | `AckPayload` | Encolado |
| `GetCurrentConfiguration` | Tray → Servicio | — | `GetConfigurationResponsePayload` | Inline |
| `CheckCorporateQueue` | Tray → Servicio | `CheckCorporateQueuePayload` | `CheckCorporateQueueResponsePayload` | Inline (WMI) |
| `CheckServiceStatus` | Tray → Servicio | `CheckServiceStatusPayload` | `CheckServiceStatusResponsePayload` | Inline (WMI) |
| `Ack` | Servicio → Tray | — | `AckPayload` | — |
| `Error` | Servicio → Tray | — | `ErrorPayload` | — |

**Nota sobre ejecución:**
- **Inline:** Se ejecuta en el thread del pipe handler y devuelve resultado inmediato
- **Encolado:** Se encola en `TaskQueueManager` y devuelve `Ack` inmediato; el resultado se procesa en background
- **Inline (WMI):** Se ejecuta inline porque las consultas WMI son suficientemente rápidas (< 1s típicamente)

## Ciclo de vida del servicio (estados)

```
Starting → WaitingUser → TrayStarting → TrayStarted → Running
                ↑               ↓ (logoff)                ↓ (logoff)
                └───────────────┴─────────────────────────┘
                                     ↘ TrayError (timeout 30 min) → SCM reinicia
```

El ciclo WaitingUser → Running se repite en cada logon/logoff sin reiniciar el servicio (`RunSessionLoop`).

### Constantes de tiempo críticas

| Constante | Valor | Ubicación | Propósito |
|---|---|---|---|
| `TrayTimeoutSeconds` | 1800 (30 min) | `AlwaysPrintWindowsService.cs` | Tiempo máximo para que el Tray complete el handshake |
| `UserPollSeconds` | 60 | `AlwaysPrintWindowsService.cs` | Intervalo de polling para detectar sesión de usuario |
| Delay pre-launch | 3000 ms | `LaunchTray()` | Espera antes de lanzar el Tray para asegurar que el pipe esté listo |
| Reintentos de conexión | 5 | `TrayApplicationContext.BootstrapSequence()` | Intentos del Tray para conectarse al pipe |
| Delay entre reintentos | 1000 ms | `TrayApplicationContext.BootstrapSequence()` | Espera entre intentos de conexión |
| Timeout de lectura pipe | 30000 ms | `PipeClient.Send()` | Timeout para leer respuesta del servicio |
| Heartbeat del Tray | 30000 ms | `TrayApplicationContext.MonitoringLoop()` | Intervalo de ping al servicio |

### Mecanismo de wake-up entre threads

`_userArrivedGate` (`ManualResetEventSlim`) es el único mecanismo de señalización entre `OnSessionChange` y los bucles de espera:

- `OnSessionChange` (logon/unlock) → `_userArrivedGate.Set()` → despierta `WaitForUser`
- `OnSessionChange` (logoff) → `_userArrivedGate.Set()` → despierta `MonitoringLoop` para que detecte el cambio de estado y salga
- `OnStop` → `_userArrivedGate.Set()` + `_cts.Cancel()` → desbloquea cualquier espera activa

**CRÍTICO:** No usar `Monitor.PulseAll` ni `Thread.Interrupt` — ambos son incorrectos en este contexto. El gate se resetea inmediatamente después de cada `Set()` para evitar señales espurias.

## Agregar una nueva tarea al servicio

1. Crear `AlwaysPrintService/Tasks/MiNuevaTarea.cs` implementando `IServiceTask`
2. Agregar el tipo de mensaje a `MessageType.cs` y los DTOs a `Payloads.cs`
3. Agregar el `case` correspondiente en `MessageDispatcher.Dispatch()`
4. **Decidir estrategia de ejecución:**
   - **Inline:** Si la tarea es rápida (< 1s) y no bloquea, ejecutar directamente y devolver resultado
   - **Encolado:** Si la tarea es lenta o modifica estado, encolar con `_taskQueue.Enqueue(...)` y devolver `Ack` inmediato
5. Si necesita resultado síncrono (como `CheckCorporateQueue`): ejecutar inline y devolver `result.Data` como payload

**CRÍTICO:** El dispatcher debe devolver el payload tipado específico (no `AckPayload` genérico) para que el Tray pueda deserializarlo correctamente con `GetPayload<T>()`.

### Ejemplo de tarea inline con resultado tipado

```csharp
// En MessageDispatcher.cs
private PipeMessage HandleMiNuevoCheck(PipeMessage req)
{
    var payload = req.GetPayload<MiNuevoCheckPayload>();
    if (payload == null)
        return PipeMessage.Reply(req, MessageType.Error,
            new ErrorPayload { Code = "INVALID_PAYLOAD", Message = "Payload missing." });

    var task = new MiNuevoCheckTask(payload.Parametro);
    var result = task.Execute();   // inline

    if (!result.Success)
        return PipeMessage.Reply(req, MessageType.Error,
            new ErrorPayload { Code = "CHECK_FAILED", Message = result.Message });

    // Devuelve el payload tipado para que el Tray pueda leer los campos específicos
    return PipeMessage.Reply(req, MessageType.Ack, result.Data);
}
```

## Registro de Windows

Clave: `HKLM\SOFTWARE\Robles.AI\AlwaysPrint`

El servicio llama a `_registry.EnsureDefaults()` en cada arranque (idempotente). Al modificar un valor:
- El Tray envía `UpdateConfiguration` con el nuevo `AppConfiguration` serializado
- `MessageDispatcher` encola un `UpdateConfigurationTask`
- `UpdateConfigurationTask.Execute()` llama a `_registry.Save()` con validación y sanitización

`RegistryConfigManager.Load()` loggea errores con `EventLogWriter.WriteWarning` en lugar de silenciarlos — nunca usar catch vacío en esta clase.

## Logging (Event IDs fijos)

**IMPORTANTE:** AlwaysPrint NO usa Windows Event Log. Todos los logs se escriben en archivos de texto.

**Ubicación:** `C:\ProgramData\AlwaysPrint\logs\AlwaysPrint_yyyyMMdd.log`  
**Formato:** `[yyyy-MM-dd HH:mm:ss] [SVC|APP] Event XXXX: mensaje`  
**Rotación:** Automática diaria (un archivo por día, sin límite de tamaño)

| Rango | Categoría | Origen |
|---|---|---|
| 1000–1009 | Ciclo de vida del servicio | SVC |
| 1010 | TrayError | SVC/APP |
| 1020–1022 | Tareas (dispatched / completed / failed) | SVC |
| 1030 | Configuración guardada | SVC |
| 1090–1091 | Warning/Error genérico | SVC/APP |

**Orígenes:**
- `SVC` = AlwaysPrintService (servicio)
- `APP` = AlwaysPrintTray (aplicación de usuario)

**Métodos de logging:**
```csharp
// Desde el servicio
AlwaysPrintLogger.WriteInfo(message, eventId);
AlwaysPrintLogger.WriteWarning(message, eventId);
AlwaysPrintLogger.WriteError(message, eventId);
AlwaysPrintLogger.WriteError(message, exception, eventId);

// Desde el Tray
AlwaysPrintLogger.WriteTrayInfo(message, eventId);
AlwaysPrintLogger.WriteTrayWarning(message, eventId);
AlwaysPrintLogger.WriteTrayError(message, eventId);
AlwaysPrintLogger.WriteTrayError(message, exception, eventId);
```

**Truncamiento:** Los mensajes se truncan a 30,000 caracteres para evitar archivos excesivamente grandes.

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
- Logging: usar `AlwaysPrintLogger` con Event IDs apropiados; nunca usar `Console.WriteLine` o `Debug.WriteLine` en producción
- Thread safety: usar `lock` para estado compartido; `ManualResetEventSlim` para señalización entre threads
- Timeout de operaciones: siempre especificar timeouts explícitos en operaciones de red/IPC (30s para pipe, 5s para HTTP)
- Recursos IDisposable: siempre usar `using` o `try/finally` para liberar recursos
- Validación de entrada: validar y sanitizar todos los datos del usuario antes de usar en WMI, registro o sistema de archivos

## Instalador WiX

`Product.wxs` usa WiX v4 con extensión `WixToolset.Util.wixext`.

**GUIDs fijos** (no regenerar en actualizaciones — solo cambiar la versión del assembly):
- UpgradeCode: `C7A4B5D6-A100-4E00-8F00-BBVA00000001`
- Componente Service: `C7A4B5D6-B200-4E00-8F00-BBVA00000002`
- Componente Tray: `C7A4B5D6-C300-4E00-8F00-BBVA00000003`

**Versionado automático:**
La versión del paquete MSI se genera automáticamente en `build.ps1` con el formato:
```
Major.Minor.Build.Revision
  1  . YY  .MMDD . HHMM
```

Ejemplo: `1.26.426.1211` = 26 de abril de 2026, 12:11

El script pasa la versión a WiX mediante `-d "ProductVersion=$version"`. No hardcodear `Version` en `Product.wxs`.

**Límites de Windows Installer:**
- Major < 256
- Minor < 256
- Build < 65536
- Revision < 65536 (ignorado por MSI, pero WiX lo valida)

**Al agregar un nuevo archivo al output:** añadir `<File Source=".\dist\nuevo.dll" />` dentro del componente correspondiente en `Product.wxs`.

**Iconos:**
- El MSI embebe `logo.ico` para el Panel de Control
- Los EXEs embeben `logo.ico` en tiempo de compilación si existe en la raíz del proyecto
- Si `logo.ico` no existe pero `logo.png` sí, `build.ps1` ejecuta `convert-icon.ps1` automáticamente

---

## Decisiones de Arquitectura Clave

### ¿Por qué Named Pipe y no otros mecanismos IPC?

- **WCF:** Obsoleto en .NET moderno, excesivamente complejo para este caso
- **HTTP/REST:** Requiere reservación de URL y permisos adicionales; overkill para IPC local
- **Memoria compartida:** Requiere sincronización manual compleja
- **Named Pipe:** Nativo de Windows, seguro (DACL), simple, rápido, ideal para IPC local

### ¿Por qué el servicio lanza el Tray en lugar de usar Startup?

- **Control total:** El servicio controla cuándo y cómo se lanza el Tray
- **Sesión correcta:** `CreateProcessAsUser` garantiza que el Tray aparece en la sesión interactiva correcta
- **Reinicio automático:** El servicio relanza el Tray automáticamente tras logoff/logon sin intervención del usuario
- **Sin dependencia de Startup:** No requiere configuración manual en cada perfil de usuario

### ¿Por qué timeout de 30 minutos para el handshake del Tray?

- **Arranque lento:** En máquinas lentas o con muchos programas de inicio, el Tray puede tardar varios minutos en arrancar
- **Redes lentas:** El health check HTTP puede tardar si la red está lenta o hay problemas de DNS
- **Margen de seguridad:** 30 minutos es suficientemente generoso para cualquier escenario real sin ser infinito
- **Recuperación automática:** Si falla, el SCM reinicia el servicio automáticamente

### ¿Por qué logging en archivos y no Event Log?

- **Simplicidad:** No requiere permisos especiales para crear el source
- **Portabilidad:** Los logs son archivos de texto plano, fáciles de copiar/analizar
- **Rotación automática:** Un archivo por día, sin límite de tamaño, sin configuración adicional
- **Debugging:** Más fácil de leer y filtrar que Event Viewer
- **Sin dependencias:** No requiere que el Event Log esté funcionando correctamente

### ¿Por qué BlockingCollection y no Channel<T>?

- **Compatibilidad:** `Channel<T>` no existe en .NET Framework 4.8
- **Simplicidad:** `BlockingCollection` es más simple y suficiente para este caso
- **Thread-safe:** Manejo automático de sincronización sin código adicional

### ¿Por qué inline para CheckCorporateQueue en lugar de encolado?

- **Latencia baja:** Las consultas WMI típicamente toman < 1 segundo
- **Resultado síncrono:** El Tray necesita el resultado inmediatamente para mostrar en la UI
- **Sin bloqueo:** El timeout del pipe (30s) es suficiente para manejar casos lentos
- **Simplicidad:** Evita complejidad de callbacks o polling para obtener el resultado

---

## Troubleshooting Avanzado

### El servicio no detecta logon/logoff

**Causa:** `CanHandleSessionChangeEvent` no está habilitado o el servicio no está registrado correctamente.

**Solución:**
```csharp
// Verificar en AlwaysPrintWindowsService.cs constructor:
base.CanHandleSessionChangeEvent = true;
```

### El Tray se lanza pero no aparece el icono

**Causa:** El Tray está corriendo pero el icono no se muestra en el system tray.

**Diagnóstico:**
```powershell
# Verificar que el proceso existe
Get-Process AlwaysPrintTray

# Revisar logs del Tray (origen APP)
Get-Content "C:\ProgramData\AlwaysPrint\logs\AlwaysPrint_$(Get-Date -Format 'yyyyMMdd').log" | Select-String "APP"
```

**Solución:** El icono puede estar oculto en el overflow del system tray. Verificar configuración de Windows.

### WMI queries fallan con Access Denied

**Causa:** El servicio corre como LocalSystem pero WMI puede tener restricciones adicionales.

**Solución:**
```powershell
# Verificar permisos WMI para LocalSystem
wmimgmt.msc
# Root → WMI Control → Properties → Security → Root\CIMV2
# Asegurar que SYSTEM tiene permisos de lectura
```

### El pipe se desconecta aleatoriamente

**Causa:** El cliente no maneja correctamente las desconexiones o el servidor cierra el pipe prematuramente.

**Diagnóstico:**
- Revisar logs alrededor del momento de la desconexión
- Verificar que no hay excepciones no manejadas en `PipeServer` o `PipeClient`
- Confirmar que el timeout de 30s es suficiente para las operaciones

**Solución:** El Tray reintenta la conexión automáticamente. Si persiste, revisar la lógica de manejo de excepciones en ambos lados del pipe.

---

## Extensibilidad

### Agregar un nuevo formulario al Tray

1. Crear `AlwaysPrintTray/Forms/MiNuevoForm.cs` heredando de `Form`
2. Implementar la lógica en código (sin designer para mantener simplicidad)
3. Agregar ítem al menú en `TrayApplicationContext.BuildTrayIcon()`:
   ```csharp
   menu.Items.Add("Mi Nueva Función", null, (_, __) => ShowMiNuevoForm());
   ```
4. Implementar el método:
   ```csharp
   private void ShowMiNuevoForm()
   {
       if (!_pipe.IsConnected && !_pipe.Connect())
       {
           MessageBox.Show("No hay conexión con el servicio.", "AlwaysPrint", 
               MessageBoxButtons.OK, MessageBoxIcon.Warning);
           return;
       }
       using var form = new MiNuevoForm(_pipe);
       form.ShowDialog();
   }
   ```
5. Cargar datos en el evento `Shown` del formulario, no en el constructor

### Agregar un nuevo parámetro de configuración

1. Agregar propiedad a `AppConfiguration.cs` con valor por defecto
2. Actualizar `RegistryConfigManager.Load()` para leer el nuevo valor
3. Actualizar `RegistryConfigManager.Save()` para escribir el nuevo valor
4. Actualizar `RegistryConfigManager.EnsureDefaults()` para crear el valor si no existe
5. Agregar control en `ConfigurationForm` para editar el valor
6. El servicio leerá el nuevo valor automáticamente en el siguiente ciclo

### Agregar una nueva tarea programada

1. Crear `AlwaysPrintService/Tasks/MiTareaProgramadaTask.cs` implementando `IServiceTask`
2. En `AlwaysPrintWindowsService.MonitoringLoop()`, encolar la tarea periódicamente:
   ```csharp
   var task = new MiTareaProgramadaTask();
   _taskQueue.Enqueue(task);
   ```
3. La tarea se ejecutará en el worker thread de `TaskQueueManager`
4. Los resultados se loggean automáticamente (Event 1021 success, 1022 failure)

---
