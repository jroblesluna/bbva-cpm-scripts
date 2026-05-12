# Requirements Document

## Introduction

La **Fase 2 — Conexión Cloud** implementa la conectividad WebSocket persistente entre el AlwaysPrintTray y AlwaysPrint Cloud Manager (APCM). Sobre la infraestructura preparada en la Fase 1 (campos de configuración, credenciales HKCU, tipos de mensajes y payloads), esta fase agrega: detección de proxy corporativo (`ProxyHelper`), cliente WebSocket con reconexión automática (`CloudWebSocketClient`), orquestador de integración Cloud (`CloudManager`), flujo de registro de workstation, heartbeat (respuesta a ping del servidor), y notificación al AlwaysPrintService del estado de conexión Cloud vía Named Pipe.

El alcance de esta fase se limita a: conexión WSS, registro de workstation, heartbeat (pong a ping), y notificación de estado Cloud al Service. El handler `config_update` del servidor queda fuera de alcance para una fase futura.

Al finalizar esta fase, `dotnet build AlwaysPrint.sln -c Release --nologo` debe producir 0 errores y 0 advertencias, y el comportamiento existente del Client con `CloudEnabled=0` no debe verse alterado.

## Glossary

- **AlwaysPrintService**: Servicio Windows (LocalSystem) que gestiona la cola de impresión corporativa y expone el Named Pipe. No accede a Internet.
- **AlwaysPrintTray**: Aplicación WinForms de bandeja del sistema que se ejecuta en el contexto del usuario. Es el único componente que accede a Internet y a HKCU.
- **APCM**: AlwaysPrint Cloud Manager — plataforma SaaS (FastAPI + Next.js) a la que el Tray se conecta vía WebSocket.
- **AppConfiguration**: Clase de configuración compartida que se persiste en `HKLM\SOFTWARE\Robles.AI\AlwaysPrint`. Contiene `CloudEnabled`, `CloudApiUrl`, `CloudLocale` entre otros campos.
- **CloudCredentialsManager**: Clase en AlwaysPrint.Shared que gestiona credenciales de workstation en `HKCU\SOFTWARE\Robles.AI\AlwaysPrint\Cloud`. Propiedades: `WorkstationId`, `ConfigHash`, `ConfigCachedAt`, `LastConnectedAt`.
- **ProxyHelper**: Nueva clase estática en `AlwaysPrintTray/Cloud/` que detecta y configura el proxy corporativo del sistema (IE/WinInet) para conexiones HTTP y WebSocket.
- **CloudWebSocketClient**: Nueva clase en `AlwaysPrintTray/Cloud/` que mantiene una conexión WSS persistente hacia APCM con reconexión automática mediante backoff exponencial.
- **CloudManager**: Nueva clase en `AlwaysPrintTray/Cloud/` que orquesta la integración Cloud: inicia la conexión, gestiona el registro, despacha mensajes y notifica al Service.
- **WebSocket4Net**: Biblioteca NuGet (versión 0.15.2) para conexiones WebSocket en .NET Framework 4.8 con soporte de proxy corporativo.
- **Backoff_Exponencial**: Estrategia de reconexión con intervalos crecientes: 1s → 2s → 4s → 8s → 16s → 32s → 60s (máximo).
- **Registro_de_Workstation**: Flujo mediante el cual el Tray envía un mensaje `register` al servidor APCM con datos de la workstation para obtener o confirmar un `WorkstationId`.
- **Heartbeat**: Mecanismo keep-alive donde el servidor envía `{"type":"ping"}` y el cliente responde `{"type":"pong"}` inmediatamente.
- **Named_Pipe**: Canal IPC `\\.\pipe\AlwaysPrintService` entre el AlwaysPrintService y el AlwaysPrintTray.
- **PipeClient**: Clase en AlwaysPrintTray que mantiene la conexión al Named Pipe del Service.
- **CloudStatusResponsePayload**: Payload existente (Fase 1) que transporta el estado de conexión Cloud por el Named Pipe.
- **MessageType**: Enumeración de tipos de mensajes del Named Pipe. Incluye `CloudStatusResponse` (definido en Fase 1).
- **AlwaysPrintLogger**: Clase de logging centralizada. Todos los logs deben pasar por ella con mensajes en español.
- **HKCU**: `HKEY_CURRENT_USER` — accesible sin privilegios de administrador.
- **WSS**: WebSocket Secure — conexión WebSocket sobre TLS.
- **Código_1008**: Código de cierre WebSocket que indica que la IP de la workstation no está autorizada en APCM.
- **TrayApplicationContext**: Clase principal del Tray que gestiona el ícono, menú, conexión al pipe y secuencia de bootstrap.

---

## Requirements

### Requirement 1: ProxyHelper — Detección de proxy corporativo

**User Story:** Como AlwaysPrintTray ejecutándose en una red corporativa con proxy, quiero que el proxy del sistema se detecte automáticamente, para que las conexiones WebSocket y HTTP hacia APCM funcionen sin configuración manual del usuario.

#### Acceptance Criteria

1. THE `ProxyHelper` SHALL be a new `static` class in `AlwaysPrintTray/Cloud/ProxyHelper.cs`.
2. THE `ProxyHelper` SHALL expose a `static HttpClientHandler CreateHandler()` method that returns an `HttpClientHandler` with `UseProxy = true` and `Proxy` set to the system web proxy obtained from `WebRequest.GetSystemWebProxy()`.
3. WHEN `ProxyHelper.CreateHandler()` is called, THE `ProxyHelper` SHALL set `Proxy.Credentials` to `CredentialCache.DefaultCredentials` on the returned handler so that NTLM/Kerberos authentication is used automatically.
4. THE `ProxyHelper` SHALL expose a `static Uri? GetSystemProxyUri(Uri targetUri)` method that returns the proxy URI for the given target, or `null` if the target is bypassed by the proxy configuration.
5. WHEN `ProxyHelper.GetSystemProxyUri(targetUri)` is called and the system proxy indicates the target is bypassed, THE `ProxyHelper` SHALL return `null`.
6. WHEN `ProxyHelper.GetSystemProxyUri(targetUri)` is called and the system proxy provides a proxy URI for the target, THE `ProxyHelper` SHALL return that proxy URI.
7. THE `ProxyHelper` SHALL NOT use `Console.WriteLine` — all diagnostic output SHALL use `AlwaysPrintLogger.WriteTrayInfo()` or `AlwaysPrintLogger.WriteTrayWarning()` with messages in Spanish.

---

### Requirement 2: CloudWebSocketClient — Conexión WSS persistente

**User Story:** Como AlwaysPrintTray, quiero mantener una conexión WebSocket persistente hacia APCM con reconexión automática, para que la workstation permanezca conectada a la nube incluso ante interrupciones de red transitorias.

#### Acceptance Criteria

1. THE `CloudWebSocketClient` SHALL be a new `sealed` class in `AlwaysPrintTray/Cloud/CloudWebSocketClient.cs` that implements `IDisposable`.
2. THE `CloudWebSocketClient` SHALL use the `WebSocket4Net` library (version 0.15.2) for the underlying WebSocket connection.
3. THE `CloudWebSocketClient` SHALL expose the following public events: `Connected` (Action), `Disconnected` (Action), `MessageReceived` (Action<string, string> where parameters are message type and JSON body), `Error` (Action<Exception>).
4. THE `CloudWebSocketClient` SHALL expose a public `bool IsConnected` property that reflects the current connection state.
5. WHEN `CloudWebSocketClient` is constructed with a `cloudApiUrl`, THE `CloudWebSocketClient` SHALL derive the WebSocket URL by replacing the `https://` scheme with `wss://` and appending `/ws/workstation` to the path.
6. WHEN `CloudWebSocketClient` is constructed and a system proxy is detected via `ProxyHelper.GetSystemProxyUri()` for the target URL, THE `CloudWebSocketClient` SHALL configure the WebSocket4Net connection to use that proxy.
7. WHEN `CloudWebSocketClient.Connect()` is called, THE `CloudWebSocketClient` SHALL initiate the WSS connection and, upon successful connection, raise the `Connected` event.
8. WHEN the WebSocket connection is established successfully, THE `CloudWebSocketClient` SHALL reset the reconnection backoff delay to the initial value of 1 second.
9. WHEN the WebSocket connection is lost unexpectedly and the client has not been disposed, THE `CloudWebSocketClient` SHALL attempt reconnection using exponential backoff with delays of 1s, 2s, 4s, 8s, 16s, 32s, and a maximum of 60s.
10. WHEN a reconnection attempt fails, THE `CloudWebSocketClient` SHALL log the attempt number and next retry delay using `AlwaysPrintLogger.WriteTrayWarning()` with a message in Spanish.
11. WHEN the WebSocket connection is lost, THE `CloudWebSocketClient` SHALL raise the `Disconnected` event.
12. WHEN a message is received from the server, THE `CloudWebSocketClient` SHALL parse the JSON to extract the `type` field and raise the `MessageReceived` event with the type and the full JSON string.
13. WHEN a WebSocket error occurs, THE `CloudWebSocketClient` SHALL raise the `Error` event with the exception details.
14. THE `CloudWebSocketClient` SHALL expose a `void Send(string type, object? payload)` method that serializes the message as JSON with a `type` field and sends it through the WebSocket connection.
15. WHEN `CloudWebSocketClient.Disconnect()` is called, THE `CloudWebSocketClient` SHALL close the WebSocket connection gracefully and stop all reconnection attempts.
16. WHEN `CloudWebSocketClient.Dispose()` is called, THE `CloudWebSocketClient` SHALL call `Disconnect()`, release all resources, and ensure no further reconnection attempts occur.
17. THE `CloudWebSocketClient` SHALL be thread-safe — all event raises and state changes SHALL be synchronized to prevent race conditions.
18. THE `CloudWebSocketClient` SHALL NOT use `Console.WriteLine` — all diagnostic output SHALL use `AlwaysPrintLogger` with messages in Spanish.

---

### Requirement 3: CloudManager — Orquestador de integración Cloud

**User Story:** Como AlwaysPrintTray, quiero un orquestador que gestione el ciclo de vida completo de la conexión Cloud (inicio, registro, despacho de mensajes, parada), para que la integración Cloud sea un componente cohesivo y fácil de controlar.

#### Acceptance Criteria

1. THE `CloudManager` SHALL be a new `sealed` class in `AlwaysPrintTray/Cloud/CloudManager.cs` that implements `IDisposable`.
2. THE `CloudManager` SHALL accept the following dependencies in its constructor: `AppConfiguration`, `CloudCredentialsManager`, `PipeClient`, and `SynchronizationContext`.
3. THE `CloudManager` SHALL expose a public `bool IsConnected` property that reflects the current Cloud connection state.
4. THE `CloudManager` SHALL expose a `void Start()` method that initiates the Cloud connection and registration flow.
5. THE `CloudManager` SHALL expose a `void Stop()` method that gracefully disconnects from APCM and stops all Cloud activity.
6. WHEN `CloudManager.Start()` is called, THE `CloudManager` SHALL create a `CloudWebSocketClient` instance using the `CloudApiUrl` from `AppConfiguration`.
7. WHEN `CloudManager.Start()` is called, THE `CloudManager` SHALL subscribe to the `Connected`, `Disconnected`, `MessageReceived`, and `Error` events of the `CloudWebSocketClient`.
8. WHEN `CloudManager.Start()` is called, THE `CloudManager` SHALL load credentials from `CloudCredentialsManager` and initiate the WebSocket connection.
9. WHEN the `CloudWebSocketClient` raises the `Connected` event, THE `CloudManager` SHALL send the registration message to APCM (see Requirement 4).
10. WHEN the `CloudWebSocketClient` raises the `Connected` event, THE `CloudManager` SHALL update `IsConnected` to `true` and notify the AlwaysPrintService of the connected state via Named Pipe (see Requirement 6).
11. WHEN the `CloudWebSocketClient` raises the `Disconnected` event, THE `CloudManager` SHALL update `IsConnected` to `false` and notify the AlwaysPrintService of the disconnected state via Named Pipe (see Requirement 6).
12. WHEN the `CloudWebSocketClient` raises the `MessageReceived` event with type `"ping"`, THE `CloudManager` SHALL respond with a `"pong"` message immediately (see Requirement 5).
13. WHEN the `CloudWebSocketClient` raises the `MessageReceived` event with type `"registered"` containing a `workstation_id` field, THE `CloudManager` SHALL save the `WorkstationId` using `CloudCredentialsManager.SaveWorkstationId()` and update `LastConnectedAt` using `CloudCredentialsManager.SaveLastConnected()`.
14. WHEN `CloudManager.Dispose()` is called, THE `CloudManager` SHALL call `Stop()` and dispose the `CloudWebSocketClient`.
15. THE `CloudManager` SHALL NOT use `Console.WriteLine` — all diagnostic output SHALL use `AlwaysPrintLogger` with messages in Spanish.
16. THE `CloudManager` SHALL be thread-safe — state transitions and event handling SHALL be synchronized.

---

### Requirement 4: Flujo de registro de workstation

**User Story:** Como workstation AlwaysPrint conectándose a APCM por primera vez, quiero que el Tray envíe mis datos de identificación al servidor, para que APCM pueda registrarme y asignarme un WorkstationId único.

#### Acceptance Criteria

1. WHEN the `CloudWebSocketClient` connects successfully and `CloudCredentialsManager.IsRegistered` is `false`, THE `CloudManager` SHALL send a registration message with `type` = `"register"` and `workstation_id` = `null`.
2. WHEN the `CloudWebSocketClient` connects successfully and `CloudCredentialsManager.IsRegistered` is `true`, THE `CloudManager` SHALL send a registration message with `type` = `"register"` and `workstation_id` set to the stored `WorkstationId` value.
3. THE registration message payload SHALL include the following fields: `ip_private` (string — first IPv4 private address of the workstation), `hostname` (string — machine hostname), `os_serial` (string — Windows OS serial number from WMI `Win32_OperatingSystem.SerialNumber`), `current_user` (string — current Windows username), `locale` (string — active locale from `LocalizationManager.CurrentLocale`), `client_version` (string — assembly version of AlwaysPrintTray).
4. WHEN the `ip_private` field is populated, THE `CloudManager` SHALL obtain the value by resolving `Dns.GetHostAddresses(Dns.GetHostName())` and selecting the first IPv4 address in a private range (10.x.x.x, 172.16-31.x.x, or 192.168.x.x).
5. WHEN the `os_serial` field is populated, THE `CloudManager` SHALL obtain the value from WMI class `Win32_OperatingSystem`, property `SerialNumber`.
6. WHEN the `client_version` field is populated, THE `CloudManager` SHALL obtain the value from the `AlwaysPrintTray` assembly's `AssemblyVersion` attribute.
7. WHEN APCM responds with a message of type `"registered"` containing a `workstation_id` field, THE `CloudManager` SHALL persist the `workstation_id` using `CloudCredentialsManager.SaveWorkstationId()`.
8. WHEN APCM responds with a message of type `"registered"`, THE `CloudManager` SHALL call `CloudCredentialsManager.SaveLastConnected(DateTime.UtcNow)` to record the connection timestamp.
9. IF the registration message cannot be sent due to a WebSocket error, THEN THE `CloudManager` SHALL log the error using `AlwaysPrintLogger.WriteTrayError()` with a message in Spanish and rely on the reconnection mechanism to retry.

---

### Requirement 5: Heartbeat — Respuesta a ping del servidor

**User Story:** Como conexión WebSocket activa hacia APCM, quiero responder inmediatamente a los mensajes ping del servidor, para que APCM pueda verificar que la workstation sigue conectada y activa.

#### Acceptance Criteria

1. WHEN the `CloudWebSocketClient` receives a message with `type` = `"ping"` from the server, THE `CloudManager` SHALL send a message with `type` = `"pong"` through the `CloudWebSocketClient` immediately.
2. THE pong response SHALL be sent within the same event handler invocation without introducing artificial delays.
3. IF sending the pong response fails due to a WebSocket error, THEN THE `CloudManager` SHALL log the error using `AlwaysPrintLogger.WriteTrayWarning()` with a message in Spanish and allow the reconnection mechanism to handle the broken connection.
4. THE heartbeat mechanism SHALL NOT initiate ping messages from the client — only the server initiates the ping/pong cycle.

---

### Requirement 6: Notificación al Service del estado de conexión Cloud

**User Story:** Como AlwaysPrintService, quiero recibir notificaciones del estado de conexión Cloud del Tray, para que pueda reportar el estado correcto cuando se consulte y tomar decisiones operativas basadas en la conectividad Cloud.

#### Acceptance Criteria

1. WHEN the Cloud connection state changes to connected, THE `CloudManager` SHALL send a `PipeMessage` of type `MessageType.CloudStatusResponse` to the AlwaysPrintService via `PipeClient` with `CloudStatusResponsePayload.IsConnected = true`, `LastConnectedAt` set to the current UTC time in ISO-8601 format, `ConfigHash` set to the current value from `CloudCredentialsManager.ConfigHash`, and `UsingCachedConfig = false`.
2. WHEN the Cloud connection state changes to disconnected, THE `CloudManager` SHALL send a `PipeMessage` of type `MessageType.CloudStatusResponse` to the AlwaysPrintService via `PipeClient` with `CloudStatusResponsePayload.IsConnected = false`, `LastConnectedAt` set to the last known connection time from `CloudCredentialsManager.LastConnectedAt` in ISO-8601 format, `ConfigHash` set to the current value from `CloudCredentialsManager.ConfigHash`, and `UsingCachedConfig = true`.
3. IF the Named Pipe is not connected when a Cloud status notification is attempted, THEN THE `CloudManager` SHALL log a warning using `AlwaysPrintLogger.WriteTrayWarning()` with a message in Spanish and SHALL NOT throw an exception.
4. IF sending the Cloud status notification via Named Pipe fails, THEN THE `CloudManager` SHALL log the error using `AlwaysPrintLogger.WriteTrayError()` with a message in Spanish and SHALL NOT propagate the exception.

---

### Requirement 7: Integración en TrayApplicationContext

**User Story:** Como AlwaysPrintTray, quiero que el CloudManager se inicie automáticamente durante el bootstrap si la integración Cloud está habilitada, para que la conexión a APCM se establezca sin intervención del usuario.

#### Acceptance Criteria

1. WHEN `TrayApplicationContext.BootstrapSequence()` completes the health check successfully and `AppConfiguration.CloudEnabled` is `true` and `AppConfiguration.CloudApiUrl` is not null or whitespace, THE `TrayApplicationContext` SHALL instantiate a `CloudManager` and call `Start()`.
2. WHEN `AppConfiguration.CloudEnabled` is `false`, THE `TrayApplicationContext` SHALL NOT instantiate or start a `CloudManager`.
3. WHEN `AppConfiguration.CloudApiUrl` is null or whitespace (even if `CloudEnabled` is `true`), THE `TrayApplicationContext` SHALL NOT instantiate or start a `CloudManager`.
4. WHEN `CloudManager` is started successfully, THE `TrayApplicationContext` SHALL log the event using `AlwaysPrintLogger.WriteTrayInfo()` with a message in Spanish.
5. WHEN `TrayApplicationContext.Dispose()` is called, THE `TrayApplicationContext` SHALL call `Dispose()` on the `CloudManager` instance if it was created.
6. IF `CloudManager.Start()` throws an exception, THEN THE `TrayApplicationContext` SHALL log the error using `AlwaysPrintLogger.WriteTrayError()` with a message in Spanish and SHALL continue operating in local mode without Cloud connectivity.
7. THE `TrayApplicationContext` SHALL declare the `CloudManager` field as a nullable private field (`CloudManager? _cloudManager`) and SHALL pass the existing `_pipe` and `_uiContext` instances to the `CloudManager` constructor.

---

### Requirement 8: Manejo de rechazo por IP no autorizada (código 1008)

**User Story:** Como AlwaysPrintTray conectándose a APCM desde una IP no autorizada, quiero que el Tray reintente la conexión con un backoff largo en lugar de quedarse inactivo, para que la workstation se conecte automáticamente cuando la IP sea autorizada sin esperar un reinicio del Tray.

#### Acceptance Criteria

1. WHEN the WebSocket connection is closed by the server with close code 1008, THE `CloudManager` SHALL log the rejection using `AlwaysPrintLogger.WriteTrayWarning()` with a message in Spanish indicating that the IP is not authorized in APCM.
2. WHEN the WebSocket connection is closed with code 1008, THE `CloudWebSocketClient` SHALL switch to a long retry interval of 300 seconds (5 minutes) instead of the standard exponential backoff.
3. WHILE the `CloudWebSocketClient` is in long-retry mode due to a 1008 rejection, THE `CloudWebSocketClient` SHALL continue attempting reconnection every 300 seconds until a successful connection is established or the client is disposed.
4. WHEN a connection attempt succeeds after a 1008 rejection, THE `CloudWebSocketClient` SHALL reset to the standard exponential backoff strategy for future disconnections.
5. THE `CloudManager` SHALL NOT stop the reconnection loop upon receiving a 1008 close code — reconnection attempts SHALL continue with the long retry interval.

---

### Requirement 9: Dependencia NuGet — WebSocket4Net

**User Story:** Como desarrollador de AlwaysPrint, quiero que el proyecto AlwaysPrintTray incluya la dependencia WebSocket4Net 0.15.2, para que el CloudWebSocketClient pueda usar una biblioteca WebSocket compatible con .NET Framework 4.8 y proxy corporativo.

#### Acceptance Criteria

1. THE `AlwaysPrintTray.csproj` SHALL include a `<PackageReference>` element for `WebSocket4Net` with `Version="0.15.2"`.
2. WHEN `dotnet restore AlwaysPrint.sln` is executed, THE NuGet restore SHALL resolve `WebSocket4Net` version 0.15.2 without errors.
3. THE `WebSocket4Net` package SHALL be the only new NuGet dependency added in this phase — no other new packages SHALL be introduced.

---

### Requirement 10: Reglas de arquitectura y logging

**User Story:** Como arquitecto del sistema AlwaysPrint, quiero que todos los cambios de la Fase 2 respeten las reglas de arquitectura establecidas, para que la separación de responsabilidades se mantenga y el sistema sea auditable.

#### Acceptance Criteria

1. THE new classes `ProxyHelper`, `CloudWebSocketClient`, and `CloudManager` SHALL reside in the `AlwaysPrintTray/Cloud/` directory and SHALL NOT be placed in `AlwaysPrint.Shared` or `AlwaysPrintService`.
2. THE new Cloud classes SHALL NOT write to `HKLM` under any circumstance — all credential persistence SHALL use `CloudCredentialsManager` which writes exclusively to `HKCU`.
3. THE new Cloud classes SHALL NOT use `Console.WriteLine` anywhere — all diagnostic output SHALL use `AlwaysPrintLogger` with messages in Spanish.
4. THE `CloudWebSocketClient` SHALL raise events in a thread-safe manner, using appropriate synchronization to prevent race conditions when multiple threads subscribe or unsubscribe.
5. THE `CloudManager` SHALL use the `SynchronizationContext` received in its constructor to marshal UI-related operations to the UI thread when necessary.
6. THE `AlwaysPrintService` project SHALL NOT reference any class under `AlwaysPrintTray/Cloud/`.
7. WHEN `CloudCredentialsManager` operations are called from `CloudManager`, THE `CloudManager` SHALL handle any exceptions gracefully by logging with `AlwaysPrintLogger` and continuing operation.
8. THE new code added in Phase 2 SHALL preserve all existing behavior of the AlwaysPrintTray when `CloudEnabled` is `false` — the Tray SHALL function identically to its pre-Phase-2 behavior in local mode.

---

### Requirement 11: Compilación sin errores ni advertencias

**User Story:** Como desarrollador de AlwaysPrint, quiero que la solución compile sin errores ni advertencias después de implementar la Fase 2, para que el pipeline de CI/CD no se vea afectado y el instalador MSI pueda generarse correctamente.

#### Acceptance Criteria

1. WHEN `dotnet build AlwaysPrint.sln -c Release --nologo` is executed after all Phase 2 changes, THE `AlwaysPrint.Shared` project SHALL compile with 0 errors and 0 warnings.
2. WHEN `dotnet build AlwaysPrint.sln -c Release --nologo` is executed after all Phase 2 changes, THE `AlwaysPrintService` project SHALL compile with 0 errors and 0 warnings.
3. WHEN `dotnet build AlwaysPrint.sln -c Release --nologo` is executed after all Phase 2 changes, THE `AlwaysPrintTray` project SHALL compile with 0 errors and 0 warnings.
4. WHEN `build.ps1` is executed after all Phase 2 changes, THE `build.ps1` script SHALL generate the MSI file without errors.
5. THE `WebSocket4Net` NuGet package SHALL resolve correctly during build without version conflicts with existing dependencies.
