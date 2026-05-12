# Design Document — Phase 2: Cloud Connect

## Architecture Overview

La Fase 2 agrega conectividad WebSocket persistente entre el AlwaysPrintTray y APCM. Se implementan tres nuevas clases en `AlwaysPrintTray/Cloud/` que se integran con la infraestructura existente de Fase 1 (credenciales HKCU, payloads, tipos de mensaje).

```
┌─────────────────────────────────────────────────────────────────┐
│                    AlwaysPrintTray                               │
│                                                                  │
│  TrayApplicationContext                                          │
│    │                                                             │
│    ├── PipeClient ──────────────────────► AlwaysPrintService     │
│    │                                      (Named Pipe IPC)       │
│    └── CloudManager (si CloudEnabled=1)                          │
│          │                                                       │
│          ├── CloudWebSocketClient ──WSS──► APCM Server           │
│          │     └── WebSocket4Net 0.15.2                          │
│          │                                                       │
│          ├── ProxyHelper (proxy corporativo)                     │
│          │                                                       │
│          └── CloudCredentialsManager (HKCU)                      │
└─────────────────────────────────────────────────────────────────┘
```

**Flujo de datos**:
1. `TrayApplicationContext.BootstrapSequence()` → instancia `CloudManager` si `CloudEnabled=true`
2. `CloudManager.Start()` → crea `CloudWebSocketClient`, conecta vía WSS
3. Al conectar → envía mensaje `register` con datos de la workstation
4. Servidor envía `ping` → cliente responde `pong`
5. Cambios de estado → notificación al Service vía `PipeClient` + `CloudStatusResponsePayload`

---

## Components

### ProxyHelper (static class)

**Archivo**: `AlwaysPrintTray/Cloud/ProxyHelper.cs`  
**Namespace**: `AlwaysPrintTray.Cloud`

Detecta el proxy corporativo del sistema (IE/WinInet) para conexiones HTTP y WebSocket.

```csharp
using System;
using System.Net;
using AlwaysPrint.Shared.Logging;

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
        /// Retorna la URI del proxy del sistema para el target dado, o null si el target es bypassed.
        /// </summary>
        public static Uri? GetSystemProxyUri(Uri targetUri)
        {
            var proxy = WebRequest.GetSystemWebProxy();
            if (proxy.IsBypassed(targetUri)) return null;
            var proxyUri = proxy.GetProxy(targetUri);
            AlwaysPrintLogger.WriteTrayInfo(
                $"ProxyHelper: proxy detectado para {targetUri.Host} → {proxyUri}");
            return proxyUri;
        }
    }
}
```

---

### CloudWebSocketClient (sealed class, IDisposable)

**Archivo**: `AlwaysPrintTray/Cloud/CloudWebSocketClient.cs`  
**Namespace**: `AlwaysPrintTray.Cloud`  
**Dependencia**: `WebSocket4Net` 0.15.2

Cliente WebSocket persistente con reconexión automática y backoff exponencial.

```csharp
using System;
using System.Threading;
using AlwaysPrint.Shared.Logging;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using WebSocket4Net;

namespace AlwaysPrintTray.Cloud
{
    public sealed class CloudWebSocketClient : IDisposable
    {
        // === Eventos públicos ===
        public event Action?                 Connected;
        public event Action?                 Disconnected;
        public event Action<string, string>? MessageReceived;  // (type, fullJson)
        public event Action<Exception>?      Error;

        // === Estado ===
        public bool IsConnected { get; private set; }

        // === Backoff ===
        private const int InitialDelayMs   = 1_000;
        private const int MaxDelayMs       = 60_000;
        private const int LongRetryDelayMs = 300_000;  // 5 min para código 1008

        private int  _currentDelayMs = InitialDelayMs;
        private bool _longRetryMode  = false;

        // === Internos ===
        private readonly string _wsUrl;
        private readonly Uri?   _proxyUri;
        private readonly object _lock = new object();
        private WebSocket?      _ws;
        private CancellationTokenSource _cts = new CancellationTokenSource();
        private bool _disposed;

        public CloudWebSocketClient(string cloudApiUrl)
        {
            // Derivar URL WSS: https://host → wss://host/ws/workstation
            _wsUrl = cloudApiUrl
                .Replace("https://", "wss://")
                .Replace("http://", "ws://")
                .TrimEnd('/') + "/ws/workstation";

            // Detectar proxy
            var targetUri = new Uri(cloudApiUrl);
            _proxyUri = ProxyHelper.GetSystemProxyUri(targetUri);
        }

        public void Connect()
        {
            lock (_lock)
            {
                if (_disposed) return;
                CreateAndOpenSocket();
            }
        }

        public void Send(string type, object? payload)
        {
            lock (_lock)
            {
                if (_ws?.State != WebSocketState.Open) return;

                var msg = payload != null
                    ? JObject.FromObject(payload)
                    : new JObject();
                msg["type"] = type;

                _ws.Send(msg.ToString(Formatting.None));
            }
        }

        public void Disconnect()
        {
            lock (_lock)
            {
                _cts.Cancel();
                if (_ws != null)
                {
                    _ws.Close();
                    _ws = null;
                }
                IsConnected = false;
            }
        }

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;
            Disconnect();
            _cts.Dispose();
        }

        // === Privados ===

        private void CreateAndOpenSocket()
        {
            _ws?.Dispose();

            if (_proxyUri != null)
            {
                var endpoint = new SuperSocket.ClientEngine.Proxy.HttpConnectProxy(
                    new System.Net.IPEndPoint(
                        System.Net.Dns.GetHostAddresses(_proxyUri.Host)[0],
                        _proxyUri.Port));
                _ws = new WebSocket(_wsUrl);
                _ws.Proxy = endpoint;
            }
            else
            {
                _ws = new WebSocket(_wsUrl);
            }

            _ws.Opened          += OnOpened;
            _ws.Closed           += OnClosed;
            _ws.MessageReceived  += OnMessage;
            _ws.Error            += OnError;

            _ws.Open();
        }

        private void OnOpened(object? sender, EventArgs e)
        {
            lock (_lock)
            {
                IsConnected    = true;
                _currentDelayMs = InitialDelayMs;
                _longRetryMode  = false;
            }
            Connected?.Invoke();
        }

        private void OnClosed(object? sender, EventArgs e)
        {
            bool wasConnected;
            lock (_lock)
            {
                wasConnected = IsConnected;
                IsConnected  = false;
            }

            // Detectar código 1008 (IP no autorizada)
            if (sender is WebSocket ws && ws.CloseStatusCode == 1008)
            {
                _longRetryMode = true;
                AlwaysPrintLogger.WriteTrayWarning(
                    "CloudWebSocketClient: conexión rechazada por APCM (código 1008 — IP no autorizada). " +
                    $"Reintentando cada {LongRetryDelayMs / 1000}s.");
            }

            if (wasConnected) Disconnected?.Invoke();
            ScheduleReconnect();
        }

        private void OnMessage(object? sender, MessageReceivedEventArgs e)
        {
            try
            {
                var json = e.Message;
                var obj  = JObject.Parse(json);
                var type = obj["type"]?.ToString() ?? "unknown";
                MessageReceived?.Invoke(type, json);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"CloudWebSocketClient: error parseando mensaje. {ex.Message}");
            }
        }

        private void OnError(object? sender, SuperSocket.ClientEngine.ErrorEventArgs e)
        {
            AlwaysPrintLogger.WriteTrayError(
                $"CloudWebSocketClient: error WebSocket. {e.Exception.Message}");
            Error?.Invoke(e.Exception);
        }

        private void ScheduleReconnect()
        {
            if (_disposed || _cts.IsCancellationRequested) return;

            var delay = _longRetryMode ? LongRetryDelayMs : _currentDelayMs;

            AlwaysPrintLogger.WriteTrayWarning(
                $"CloudWebSocketClient: reconectando en {delay / 1000}s...");

            // Avanzar backoff exponencial (solo en modo normal)
            if (!_longRetryMode)
                _currentDelayMs = Math.Min(_currentDelayMs * 2, MaxDelayMs);

            ThreadPool.QueueUserWorkItem(_ =>
            {
                try
                {
                    _cts.Token.WaitHandle.WaitOne(delay);
                    if (!_cts.IsCancellationRequested)
                    {
                        lock (_lock) { CreateAndOpenSocket(); }
                    }
                }
                catch (ObjectDisposedException) { }
            });
        }
    }
}
```

**Comportamiento de backoff**:
- Normal: 1s → 2s → 4s → 8s → 16s → 32s → 60s (máximo)
- Código 1008: 300s fijo hasta reconexión exitosa
- Reset a 1s tras conexión exitosa

---

### CloudManager (sealed class, IDisposable)

**Archivo**: `AlwaysPrintTray/Cloud/CloudManager.cs`  
**Namespace**: `AlwaysPrintTray.Cloud`

Orquestador principal de la integración Cloud.

```csharp
using System;
using System.Linq;
using System.Management;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Threading;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Messages;
using AlwaysPrintTray.Localization;
using AlwaysPrintTray.Pipe;
using Newtonsoft.Json.Linq;

namespace AlwaysPrintTray.Cloud
{
    public sealed class CloudManager : IDisposable
    {
        public bool IsConnected { get; private set; }

        private readonly AppConfiguration        _config;
        private readonly CloudCredentialsManager  _credentials;
        private readonly PipeClient               _pipe;
        private readonly SynchronizationContext   _uiContext;

        private CloudWebSocketClient? _wsClient;
        private bool _disposed;

        public CloudManager(
            AppConfiguration config,
            CloudCredentialsManager credentials,
            PipeClient pipe,
            SynchronizationContext uiContext)
        {
            _config      = config;
            _credentials = credentials;
            _pipe        = pipe;
            _uiContext   = uiContext;
        }

        public void Start()
        {
            _credentials.Load();

            _wsClient = new CloudWebSocketClient(_config.CloudApiUrl);
            _wsClient.Connected       += OnConnected;
            _wsClient.Disconnected    += OnDisconnected;
            _wsClient.MessageReceived += OnMessageReceived;
            _wsClient.Error           += OnError;

            _wsClient.Connect();
            AlwaysPrintLogger.WriteTrayInfo("CloudManager: conexión WebSocket iniciada.");
        }

        public void Stop()
        {
            _wsClient?.Disconnect();
            IsConnected = false;
        }

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;
            Stop();
            _wsClient?.Dispose();
        }

        // === Handlers de eventos ===

        private void OnConnected()
        {
            IsConnected = true;
            AlwaysPrintLogger.WriteTrayInfo("CloudManager: conectado a APCM.");

            SendRegistration();
            NotifyServiceCloudStatus(connected: true);
        }

        private void OnDisconnected()
        {
            IsConnected = false;
            AlwaysPrintLogger.WriteTrayWarning("CloudManager: desconectado de APCM.");
            NotifyServiceCloudStatus(connected: false);
        }

        private void OnMessageReceived(string type, string json)
        {
            switch (type)
            {
                case "ping":
                    HandlePing();
                    break;
                case "registered":
                    HandleRegistered(json);
                    break;
                default:
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"CloudManager: mensaje recibido tipo='{type}' (sin handler).");
                    break;
            }
        }

        private void OnError(Exception ex)
        {
            AlwaysPrintLogger.WriteTrayError(
                $"CloudManager: error en WebSocket. {ex.Message}");
        }

        // === Registro ===

        private void SendRegistration()
        {
            try
            {
                var payload = new JObject
                {
                    ["ip_private"]     = GetPrivateIp(),
                    ["hostname"]       = Environment.MachineName,
                    ["os_serial"]      = GetOsSerial(),
                    ["current_user"]   = Environment.UserName,
                    ["locale"]         = LocalizationManager.CurrentLocale,
                    ["client_version"] = Assembly.GetExecutingAssembly()
                                            .GetName().Version?.ToString() ?? "0.0.0.0",
                    ["workstation_id"] = _credentials.IsRegistered
                                            ? _credentials.WorkstationId
                                            : null
                };

                _wsClient!.Send("register", payload);
                AlwaysPrintLogger.WriteTrayInfo("CloudManager: mensaje de registro enviado.");
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudManager: error enviando registro. {ex.Message}");
            }
        }

        private void HandleRegistered(string json)
        {
            try
            {
                var obj = JObject.Parse(json);
                var workstationId = obj["workstation_id"]?.ToString();

                if (!string.IsNullOrEmpty(workstationId))
                {
                    _credentials.SaveWorkstationId(workstationId);
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"CloudManager: WorkstationId registrado = {workstationId}");
                }

                _credentials.SaveLastConnected(DateTime.UtcNow);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudManager: error procesando respuesta de registro. {ex.Message}");
            }
        }

        // === Heartbeat ===

        private void HandlePing()
        {
            try
            {
                _wsClient!.Send("pong", null);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"CloudManager: error enviando pong. {ex.Message}");
            }
        }

        // === Notificación al Service ===

        private void NotifyServiceCloudStatus(bool connected)
        {
            try
            {
                if (!_pipe.IsConnected)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "CloudManager: pipe no conectado, no se puede notificar estado Cloud.");
                    return;
                }

                var payload = new CloudStatusResponsePayload
                {
                    IsConnected      = connected,
                    LastConnectedAt  = connected
                        ? DateTime.UtcNow.ToString("o")
                        : _credentials.LastConnectedAt?.ToString("o"),
                    ConfigHash       = _credentials.ConfigHash,
                    UsingCachedConfig = !connected
                };

                _pipe.Send(PipeMessage.Create(MessageType.CloudStatusResponse, payload));
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudManager: error notificando estado Cloud al Service. {ex.Message}");
            }
        }

        // === Utilidades ===

        private static string GetPrivateIp()
        {
            try
            {
                var addresses = Dns.GetHostAddresses(Dns.GetHostName());
                var privateIp = addresses.FirstOrDefault(a =>
                    a.AddressFamily == AddressFamily.InterNetwork &&
                    IsPrivateIp(a));
                return privateIp?.ToString() ?? "0.0.0.0";
            }
            catch { return "0.0.0.0"; }
        }

        private static bool IsPrivateIp(IPAddress ip)
        {
            var bytes = ip.GetAddressBytes();
            return bytes[0] == 10 ||
                   (bytes[0] == 172 && bytes[1] >= 16 && bytes[1] <= 31) ||
                   (bytes[0] == 192 && bytes[1] == 168);
        }

        private static string GetOsSerial()
        {
            try
            {
                using var searcher = new ManagementObjectSearcher(
                    "SELECT SerialNumber FROM Win32_OperatingSystem");
                foreach (var obj in searcher.Get())
                    return obj["SerialNumber"]?.ToString() ?? "";
                return "";
            }
            catch { return ""; }
        }
    }
}
```

---

### Integración en TrayApplicationContext

Modificación en `BootstrapSequence()` después del health check:

```csharp
// Campo privado nuevo:
private CloudManager? _cloudManager;

// En BootstrapSequence(), después del health check exitoso:
if (cfg.CloudEnabled && !string.IsNullOrWhiteSpace(cfg.CloudApiUrl))
{
    try
    {
        var credentials = new CloudCredentialsManager();
        _cloudManager = new CloudManager(cfg, credentials, _pipe, _uiContext);
        _cloudManager.Start();
        AlwaysPrintLogger.WriteTrayInfo("CloudManager iniciado correctamente.");
    }
    catch (Exception ex)
    {
        AlwaysPrintLogger.WriteTrayError(
            $"Error iniciando CloudManager, continuando en modo local. {ex.Message}");
    }
}

// En Dispose():
_cloudManager?.Dispose();
```

---

## Data Models

### Mensajes WebSocket (JSON)

**Registro (cliente → servidor)**:
```json
{
  "type": "register",
  "ip_private": "192.168.1.100",
  "hostname": "W10BBVA01",
  "os_serial": "XXXXX-XXXXX-XXXXX-XXXXX",
  "current_user": "ope01",
  "locale": "es",
  "client_version": "1.26.511.2032",
  "workstation_id": null
}
```

**Registro exitoso (servidor → cliente)**:
```json
{
  "type": "registered",
  "workstation_id": "uuid-asignado-por-apcm"
}
```

**Heartbeat (servidor → cliente)**:
```json
{"type": "ping"}
```

**Heartbeat response (cliente → servidor)**:
```json
{"type": "pong"}
```

### CloudStatusResponsePayload (Named Pipe)

Payload existente de Fase 1 reutilizado para notificar al Service:

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `IsConnected` | bool | Estado actual de conexión |
| `LastConnectedAt` | string? | ISO-8601 UTC de última conexión |
| `ConfigHash` | string? | SHA-256 de última config descargada |
| `UsingCachedConfig` | bool | true si desconectado |

---

## Interfaces

### CloudWebSocketClient — Public API

| Miembro | Tipo | Descripción |
|---------|------|-------------|
| `Connected` | event Action | Conexión WSS establecida |
| `Disconnected` | event Action | Conexión WSS perdida |
| `MessageReceived` | event Action<string, string> | Mensaje recibido (type, json) |
| `Error` | event Action<Exception> | Error de WebSocket |
| `IsConnected` | bool | Estado actual |
| `Connect()` | void | Iniciar conexión |
| `Send(type, payload)` | void | Enviar mensaje JSON |
| `Disconnect()` | void | Cerrar conexión |
| `Dispose()` | void | Liberar recursos |

### CloudManager — Public API

| Miembro | Tipo | Descripción |
|---------|------|-------------|
| `IsConnected` | bool | Estado de conexión Cloud |
| `Start()` | void | Iniciar integración Cloud |
| `Stop()` | void | Detener integración Cloud |
| `Dispose()` | void | Liberar recursos |

---

## Error Handling

| Escenario | Comportamiento |
|-----------|----------------|
| Proxy no disponible | Conexión directa (sin proxy) |
| Conexión WSS falla | Backoff exponencial: 1s → 60s max |
| Código 1008 (IP no autorizada) | Long retry: 300s fijo |
| Error enviando registro | Log + esperar reconexión |
| Error enviando pong | Log warning + reconexión automática |
| Pipe no conectado al notificar | Log warning, no throw |
| Error en pipe send | Log error, no propagar excepción |
| CloudManager.Start() falla | Log error, Tray continúa en modo local |
| Excepción en CloudCredentialsManager | Log + continuar operación |

---

## NuGet Dependency

Agregar a `AlwaysPrintTray.csproj`:

```xml
<PackageReference Include="WebSocket4Net" Version="0.15.2" />
```

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: URL derivation preserves host and appends correct path

*For any* valid HTTPS URL string `url`, constructing a `CloudWebSocketClient(url)` SHALL produce a WebSocket URL where the scheme is `wss://`, the host and port are identical to the original, and the path ends with `/ws/workstation`.

**Validates: Requirements 2.5**

### Property 2: Exponential backoff sequence is correct

*For any* number of consecutive reconnection failures `n` (where n ≥ 1) in standard mode, the delay before the nth attempt SHALL be `min(2^(n-1) * 1000, 60000)` milliseconds.

**Validates: Requirements 2.8, 2.9**

### Property 3: Long retry mode uses fixed 300s interval

*For any* number of consecutive reconnection failures after a close code 1008, the delay before each attempt SHALL be exactly 300,000 milliseconds regardless of the failure count.

**Validates: Requirements 8.2, 8.3, 8.5**

### Property 4: Successful connection resets backoff state

*For any* sequence of failures (in either standard or long-retry mode) followed by a successful connection, the next disconnection SHALL use the initial backoff delay of 1,000 milliseconds.

**Validates: Requirements 2.8, 8.4**

### Property 5: Message parsing extracts type field correctly

*For any* valid JSON string containing a `"type"` field, the `MessageReceived` event SHALL be raised with the first parameter equal to the value of the `"type"` field and the second parameter equal to the full original JSON string.

**Validates: Requirements 2.12**

### Property 6: Send serializes with type field

*For any* type string `t` and payload object `p`, calling `Send(t, p)` SHALL produce a JSON string where the `"type"` field equals `t` and all properties of `p` are present.

**Validates: Requirements 2.14**

### Property 7: Registration payload contains all required fields

*For any* invocation of the registration flow, the JSON message sent SHALL contain all six required fields (`ip_private`, `hostname`, `os_serial`, `current_user`, `locale`, `client_version`) as non-null strings, plus `workstation_id` (string or null).

**Validates: Requirements 4.3**

### Property 8: Ping always produces pong

*For any* message received with `type` = `"ping"`, the CloudManager SHALL invoke `Send("pong", null)` exactly once with no other messages interleaved before it.

**Validates: Requirements 3.12, 5.1**

### Property 9: Cloud status notification payload is consistent with connection state

*For any* connection state change, the `CloudStatusResponsePayload` sent via Named Pipe SHALL have `IsConnected` matching the new state, `UsingCachedConfig` equal to `!IsConnected`, and `LastConnectedAt` set to UTC now (if connecting) or the stored value (if disconnecting).

**Validates: Requirements 6.1, 6.2**
