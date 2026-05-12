# Fase 2 — Conexión Cloud: WebSocket, Registro, Heartbeat

**Prerrequisito**: Fase 1 completada  
**Entregable**: El Tray se conecta a APCM vía WebSocket, se registra y mantiene la conexión activa  
**Estimación**: 5–7 días

---

## Objetivo

Implementar en el Tray:
1. `CloudWebSocketClient` — conexión WSS persistente con reconexión automática
2. `ProxyHelper` — detección de proxy corporativo
3. Flujo de registro de workstation (primer arranque con `CloudEnabled=1`)
4. Heartbeat automático (respuesta a `ping` del servidor)
5. Notificación al Service del estado de conexión Cloud

---

## Componentes a Crear

### 2.1 — `ProxyHelper.cs`

**Archivo**: `AlwaysPrintProject/Client/AlwaysPrintTray/Cloud/ProxyHelper.cs`

```csharp
namespace AlwaysPrintTray.Cloud
{
    /// <summary>
    /// Detecta y configura el proxy corporativo para las conexiones HTTP/WebSocket del Tray.
    /// Usa el proxy del sistema (configurado en IE/WinInet) como primera opción.
    /// </summary>
    public static class ProxyHelper
    {
        /// <summary>
        /// Retorna un HttpClientHandler configurado con el proxy del sistema si existe.
        /// </summary>
        public static HttpClientHandler CreateHandler()
        {
            var handler = new HttpClientHandler
            {
                UseProxy = true,
                Proxy    = WebRequest.GetSystemWebProxy()
            };
            handler.Proxy.Credentials = CredentialCache.DefaultCredentials;
            return handler;
        }

        /// <summary>
        /// Retorna la URI del proxy del sistema, o null si no hay proxy.
        /// </summary>
        public static Uri? GetSystemProxyUri(Uri targetUri)
        {
            var proxy = WebRequest.GetSystemWebProxy();
            if (proxy.IsBypassed(targetUri)) return null;
            return proxy.GetProxy(targetUri);
        }
    }
}
```

---

### 2.2 — `CloudWebSocketClient.cs`

**Archivo**: `AlwaysPrintProject/Client/AlwaysPrintTray/Cloud/CloudWebSocketClient.cs`

**Dependencia NuGet**: `WebSocket4Net` (versión 0.15.2) — compatible con net48 y soporta WSS con proxy.

> **Por qué WebSocket4Net**: `System.Net.WebSockets.ClientWebSocket` en net48 no soporta proxy corporativo correctamente. WebSocket4Net es la librería estándar para net48 con soporte completo de WSS + proxy.

```csharp
namespace AlwaysPrintTray.Cloud
{
    /// <summary>
    /// Cliente WebSocket persistente hacia APCM.
    ///
    /// Protocolo:
    ///   - Primer mensaje enviado: {"type":"register", ...}
    ///   - Servidor envía {"type":"ping"} cada 30 s → cliente responde {"type":"pong"}
    ///   - Reconexión automática con backoff exponencial (1s, 2s, 4s, 8s, máx 60s)
    ///   - Eventos: Connected, Disconnected, MessageReceived, Error
    /// </summary>
    public sealed class CloudWebSocketClient : IDisposable
    {
        // Eventos públicos
        public event Action?                    Connected;
        public event Action?                    Disconnected;
        public event Action<string, string>?    MessageReceived;  // (type, json)
        public event Action<Exception>?         Error;

        public bool IsConnected { get; private set; }

        public CloudWebSocketClient(string cloudApiUrl, ProxyHelper proxyHelper) { }

        public void Connect(RegisterPayload registration) { }
        public void Send(string type, object payload) { }
        public void Disconnect() { }
        public void Dispose() { }
    }
}
```

**Comportamiento de reconexión**:
- Backoff exponencial: 1 s → 2 s → 4 s → 8 s → 16 s → 32 s → 60 s (máximo)
- Resetear backoff al conectar exitosamente
- No reconectar si `_cts` fue cancelado (shutdown del Tray)
- Loggear cada intento con `AlwaysPrintLogger`

**Construcción de la URL WebSocket**:
```
CloudApiUrl = "https://alwaysprint.apps.iol.pe"
→ WSS URL = "wss://alwaysprint.apps.iol.pe/ws/workstation"
```

---

### 2.3 — `CloudManager.cs` — Orquestador principal

**Archivo**: `AlwaysPrintProject/Client/AlwaysPrintTray/Cloud/CloudManager.cs`

```csharp
namespace AlwaysPrintTray.Cloud
{
    /// <summary>
    /// Orquesta toda la integración Cloud del Tray.
    /// Se instancia solo si CloudEnabled = 1.
    ///
    /// Responsabilidades:
    ///   - Iniciar CloudWebSocketClient
    ///   - Gestionar el flujo de registro
    ///   - Despachar mensajes entrantes a los handlers correspondientes
    ///   - Notificar al Service del estado de conexión
    ///   - Gestionar el estado offline
    /// </summary>
    public sealed class CloudManager : IDisposable
    {
        public bool IsConnected { get; private set; }
        public bool UsingCachedConfig { get; private set; }

        public CloudManager(
            AppConfiguration config,
            CloudCredentialsManager credentials,
            PipeClient pipe,
            SynchronizationContext uiContext) { }

        public void Start() { }
        public void Stop() { }
        public void Dispose() { }
    }
}
```

---

### 2.4 — Flujo de Registro

Al iniciar `CloudManager.Start()`:

```
1. Leer CloudCredentialsManager
2. Si WorkstationId está vacío → es primer registro
   a. Conectar WebSocket
   b. Enviar mensaje "register" con ip_private, hostname, os_serial, current_user, locale, client_version
   c. Esperar respuesta del servidor (config_update o error)
   d. Si éxito: guardar WorkstationId en HKCU
3. Si WorkstationId existe → reconexión
   a. Conectar WebSocket
   b. Enviar mensaje "register" con WorkstationId incluido
```

**Payload de registro**:
```json
{
  "type": "register",
  "ip_private": "192.168.1.100",
  "hostname": "W10BBVA01",
  "os_serial": "XXXXX",
  "current_user": "ope01",
  "locale": "es",
  "client_version": "1.26.511.2032",
  "workstation_id": "uuid-si-ya-registrado-o-null"
}
```

**Obtener ip_private**: usar `Dns.GetHostAddresses(Dns.GetHostName())` filtrando por IPv4 privada.

**Obtener os_serial**: WMI `Win32_OperatingSystem.SerialNumber` (el Service ya lo puede hacer; el Tray puede leerlo directamente también).

---

### 2.5 — Heartbeat (respuesta a ping)

El servidor envía `{"type":"ping"}` cada 30 s. El Tray responde `{"type":"pong"}` inmediatamente.

Esto se maneja en el handler de `MessageReceived` del `CloudWebSocketClient`:

```csharp
if (type == "ping")
    _wsClient.Send("pong", null);
```

No hay heartbeat iniciado por el cliente — el servidor controla el keep-alive.

---

### 2.6 — Notificación al Service del estado Cloud

Cuando el estado de conexión cambia, el Tray notifica al Service vía Named Pipe:

```csharp
// Al conectar:
_pipe.Send(PipeMessage.Create(MessageType.CloudStatusResponse, new CloudStatusResponsePayload
{
    IsConnected      = true,
    LastConnectedAt  = DateTime.UtcNow.ToString("o"),
    ConfigHash       = _credentials.ConfigHash,
    UsingCachedConfig = false
}));

// Al desconectar:
_pipe.Send(PipeMessage.Create(MessageType.CloudStatusResponse, new CloudStatusResponsePayload
{
    IsConnected       = false,
    LastConnectedAt   = _credentials.LastConnectedAt?.ToString("o"),
    ConfigHash        = _credentials.ConfigHash,
    UsingCachedConfig = true
}));
```

---

### 2.7 — Integración en `TrayApplicationContext`

En `BootstrapSequence()`, después del health check, agregar:

```csharp
// 6. Iniciar integración Cloud si está habilitada
if (cfg.CloudEnabled && !string.IsNullOrWhiteSpace(cfg.CloudApiUrl))
{
    _cloudManager = new CloudManager(cfg, _credentials, _pipe, _uiContext);
    _cloudManager.Start();
    AlwaysPrintLogger.WriteTrayInfo("CloudManager iniciado.", AlwaysPrintLogger.EvtServiceStarted);
}
```

En `Dispose()`:
```csharp
_cloudManager?.Dispose();
```

---

### 2.8 — Dependencia NuGet

Agregar a `AlwaysPrintTray.csproj`:

```xml
<PackageReference Include="WebSocket4Net" Version="0.15.2" />
```

---

## Criterios de Aceptación

- [ ] Con `CloudEnabled=0`: el Tray arranca igual que antes, sin intentar conectar
- [ ] Con `CloudEnabled=1` y URL válida: el Tray conecta al WebSocket de APCM
- [ ] El Tray responde `pong` a cada `ping` del servidor
- [ ] Si la IP no está autorizada en APCM: el Tray loggea el rechazo y opera en modo local
- [ ] Si la conexión se pierde: el Tray reconecta con backoff exponencial
- [ ] El Service recibe notificación de estado Cloud vía Named Pipe
- [ ] El proxy corporativo se detecta automáticamente
- [ ] Todos los logs de Cloud usan `AlwaysPrintLogger.WriteTrayInfo/Warning/Error`

---

## Notas para el Desarrollador

- El `CloudWebSocketClient` debe ser thread-safe — los eventos se disparan desde threads de red.
- Usar `_uiContext.Post(...)` para cualquier actualización de UI desde los handlers de eventos.
- El `WorkstationId` se guarda en `HKCU` inmediatamente al recibirlo — no esperar a que la config se descargue.
- Si APCM rechaza la conexión con código 1008 (IP no autorizada), loggear con `EvtGenericWarning` y NO reintentar automáticamente — esperar al siguiente arranque del Tray.
- La URL del WebSocket se construye reemplazando `https://` por `wss://` y agregando `/ws/workstation`.
