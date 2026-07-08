# Documento de Diseño — Connectivity Check Scheduled

## Visión General

El Connectivity Check se implementa como una nueva acción `ConnectivityCheck` del ActionEngine que delega la ejecución al Tray vía Named Pipe. El Service solo actúa como orquestador (dispara el timer y envía el comando); el Tray ejecuta los HTTP checks, procesa resultados, muestra notificaciones y escribe en el log.

```
┌──────────────────────────────────────────────────────────────────┐
│                     SERVICE (LocalSystem)                         │
│                                                                    │
│  OnScheduledTask Timer (cada 300s)                                │
│       ↓                                                           │
│  ActionEngine.ExecuteActions()                                    │
│       ↓                                                           │
│  ExecuteConnectivityCheck()                                       │
│       ↓                                                           │
│  PipeServer.SendToClient(ConnectivityCheckRequest)  ← fire & forget│
│                                                                    │
└──────────────────────────────┬───────────────────────────────────┘
                               │ Named Pipe
┌──────────────────────────────▼───────────────────────────────────┐
│                     TRAY (User Session)                            │
│                                                                    │
│  HandleConnectivityCheck(params)                                  │
│       ↓                                                           │
│  1. Detectar proxy del sistema                                    │
│  2. Verificar proxy activo (TCP connect)                          │
│  3. Crear HttpClient con proxy + credentials                      │
│  4. Para cada URL: HEAD/GET con timeout                           │
│       ↓ (si falla)                                                │
│     Esperar retry_delay → reintentar (max_retries veces)          │
│  5. Calcular resultado (% éxito)                                  │
│  6. Escribir en log                                               │
│  7. Mostrar NotificationForm (verde/amarillo/rojo)                │
│                                                                    │
└──────────────────────────────────────────────────────────────────┘
```

## Componentes Modificados

### 1. ActionEngine (Service) — `AlwaysPrintService/Actions/ActionEngine.cs`

**Cambio en `StartScheduledTaskTimer()`**: Leer `run_immediately` del trigger. Si true, primera ejecución en `TimeSpan.Zero`; si false, primera ejecución en `TimeSpan.FromSeconds(intervalSeconds)`.

```csharp
bool runImmediately = _actionEngine.GetTriggerRunImmediately(TriggerEvents.OnScheduledTask);
var firstRun = runImmediately ? TimeSpan.Zero : TimeSpan.FromSeconds(intervalSeconds);

_scheduledTaskTimer = new System.Threading.Timer(
    OnScheduledTaskTick,
    null,
    firstRun,
    TimeSpan.FromSeconds(intervalSeconds));
```

```csharp
case ActionTypes.ConnectivityCheck:
    return ExecuteConnectivityCheck(action);
```

**Implementación de `ExecuteConnectivityCheck`**:
- Extraer parámetros del JSON (urls, timeout, retries, delays, notification timeouts)
- Serializar como `ConnectivityCheckPayload`
- Enviar vía `PipeServer.SendToClient()` con tipo `MessageType.ConnectivityCheck`
- Retornar `true` siempre (fire-and-forget, no bloquea el trigger)
- Si pipe no está conectado → loguear warning, retornar true

### 2. Mensajes IPC — `AlwaysPrint.Shared/Messages/`

**Nuevos tipos en `MessageType.cs`**:
```csharp
ConnectivityCheck,          // Service → Tray: ejecutar check de URLs
ConnectivityCheckResult,    // Tray → Service: resultado (opcional, para log del Service)
```

**Nuevo payload en `Payloads.cs`**:
```csharp
public class ConnectivityCheckPayload
{
    [JsonProperty("urls")]
    public List<string> Urls { get; set; } = new();

    [JsonProperty("timeout_seconds")]
    public int TimeoutSeconds { get; set; } = 5;

    [JsonProperty("max_retries")]
    public int MaxRetries { get; set; } = 2;

    [JsonProperty("retry_delay_seconds")]
    public int RetryDelaySeconds { get; set; } = 30;

    [JsonProperty("notification_green_timeout_seconds")]
    public int NotificationGreenTimeoutSeconds { get; set; } = 5;

    [JsonProperty("notification_yellow_timeout_seconds")]
    public int NotificationYellowTimeoutSeconds { get; set; } = 10;
}
```

### 3. ActionTypes — `AlwaysPrint.Shared/Configuration/ActionConfig.cs`

**Agregar constante**:
```csharp
public const string ConnectivityCheck = "ConnectivityCheck";
```

### 4. Tray — Handler del mensaje `ConnectivityCheck`

**Ubicación**: `AlwaysPrintTray/Cloud/ConnectivityCheckHandler.cs` (nueva clase)

**Responsabilidades**:
- Recibir `ConnectivityCheckPayload` del pipe message
- Ejecutar los checks HTTP en un background thread (no bloquear UI thread)
- Gestionar reintentos con delays
- Calcular resultados
- Invocar NotificationForm en UI thread
- Escribir en log

**Flujo de ejecución HTTP**:
```csharp
public async Task ExecuteCheckAsync(ConnectivityCheckPayload payload)
{
    // 1. Detectar proxy
    var proxyUri = ProxyHelper.GetSystemProxyUri(new Uri(payload.Urls[0]));
    bool proxyActive = false;
    
    if (proxyUri != null)
    {
        // TCP connect al proxy para verificar que está activo
        proxyActive = await TestTcpConnectAsync(proxyUri.Host, proxyUri.Port, 2000);
    }
    
    // 2. Crear HttpClient con proxy del sistema
    var handler = ProxyHelper.CreateHandler();
    using var client = new HttpClient(handler) { Timeout = TimeSpan.FromSeconds(payload.TimeoutSeconds) };
    
    // 3. Ejecutar checks
    var results = new List<UrlCheckResult>();
    foreach (var url in payload.Urls)
    {
        var result = await CheckUrlWithRetriesAsync(client, url, payload);
        results.Add(result);
    }
    
    // 4. Calcular y notificar
    int total = results.Count;
    int ok = results.Count(r => r.Success);
    int percent = (ok * 100) / total;
    
    // 5. Log + Notificación
    LogResults(results, proxyActive, percent);
    ShowNotification(results, percent, payload);
}
```

**Lógica de reintentos**:
```csharp
private async Task<UrlCheckResult> CheckUrlWithRetriesAsync(HttpClient client, string url, ConnectivityCheckPayload payload)
{
    int attempts = 0;
    string lastError = null;
    int lastStatusCode = 0;
    long lastLatencyMs = 0;
    
    for (int i = 0; i <= payload.MaxRetries; i++)
    {
        attempts++;
        if (i > 0) await Task.Delay(payload.RetryDelaySeconds * 1000);
        
        var sw = Stopwatch.StartNew();
        try
        {
            var response = await client.SendAsync(new HttpRequestMessage(HttpMethod.Head, url));
            sw.Stop();
            lastLatencyMs = sw.ElapsedMilliseconds;
            lastStatusCode = (int)response.StatusCode;
            
            if (response.IsSuccessStatusCode || lastStatusCode == 301 || lastStatusCode == 302 || lastStatusCode == 403)
            {
                // 2xx, 3xx redirects, o 403 = el servidor respondió (URL accesible)
                return new UrlCheckResult { Url = url, Success = true, LatencyMs = lastLatencyMs, StatusCode = lastStatusCode, Attempts = attempts };
            }
            lastError = $"HTTP {lastStatusCode}";
        }
        catch (TaskCanceledException)
        {
            sw.Stop();
            lastLatencyMs = sw.ElapsedMilliseconds;
            lastError = "Timeout";
        }
        catch (HttpRequestException ex)
        {
            sw.Stop();
            lastLatencyMs = sw.ElapsedMilliseconds;
            lastError = ex.InnerException?.Message ?? ex.Message;
        }
    }
    
    return new UrlCheckResult { Url = url, Success = false, LatencyMs = lastLatencyMs, StatusCode = lastStatusCode, Attempts = attempts, Error = lastError };
}
```

**Nota sobre códigos de éxito**: Se considera "accesible" si el servidor responde (incluso con 403 — significa que la URL es alcanzable pero no autorizada, lo cual está OK para un check de conectividad). Solo se marca como fallo si hay timeout, connection refused, o error de red.

### 5. NotificationForm — `AlwaysPrintTray/Forms/ConnectivityNotificationForm.cs`

**Tipo**: WinForms Form (compatible Windows 7+)

**Diseño visual**:
```
┌─────────────────────────────────────────────────┐
│  [Icono]  Conectividad: Todo OK 100%            │
│                                                   │
│  [Ver Reporte]              [OK / Acknowledge]   │
└─────────────────────────────────────────────────┘
```

**Variantes por severidad**:

| Severidad | Fondo | Icono | Texto | Auto-cierre | Botón |
|-----------|-------|-------|-------|-------------|-------|
| Verde (100%) | #E8F5E9 | ✓ verde | "Todo OK 100%" | 5s | "OK" |
| Amarillo (<100%, >0%) | #FFF3E0 | ⚠ naranja | "Conectividad: {X}% fallidas" | 10s | "OK" |
| Rojo (0%) | #FFEBEE | Impresora roja | "Sin acceso a Internet — Requiere autenticación en ZScaler" | NO auto-cierre | "Entendido" |

**Características del Form**:
- `TopMost = true` (siempre visible sobre otras ventanas)
- Posición: esquina inferior derecha (sobre la barra de tareas, como un toast)
- Animación: fade-in sutil
- Singleton: propiedad estática `Instance` — si ya existe uno, se cierra y se crea nuevo
- Timer interno para auto-cierre (verde/amarillo)
- Botón "Ver Reporte" abre un segundo form (o expande) con la tabla detallada

**Reporte detallado** (al hacer clic en "Ver Reporte"):
```
┌─────────────────────────────────────────────────────────────────┐
│  Reporte de Conectividad — 2026-07-07 16:47:30                  │
│─────────────────────────────────────────────────────────────────│
│  Proxy: 127.0.0.1:8999 (activo)                                 │
│  URLs verificadas: 16 | Exitosas: 14 | Fallidas: 2              │
│─────────────────────────────────────────────────────────────────│
│  URL                              │ Estado │ Latencia │ Intentos │
│  alwaysprint.apps.iol.pe          │   ✓    │   45ms   │    1     │
│  cloud.lexmark.com                │   ✓    │  120ms   │    1     │
│  idp.us.iss.lexmark.com           │   ✗    │ Timeout  │    3     │
│  login.microsoftonline.com        │   ✓    │   89ms   │    1     │
│  ...                                                              │
│─────────────────────────────────────────────────────────────────│
│                                              [Cerrar]            │
└─────────────────────────────────────────────────────────────────┘
```

### 6. Integración en MessageDispatcher (Tray)

El Tray ya recibe push messages del Service vía pipe. Agregar el handling:

```csharp
// En el handler de mensajes push del Service (OnPipeMessageReceived)
case MessageType.ConnectivityCheck:
    var payload = message.GetPayload<ConnectivityCheckPayload>();
    _ = Task.Run(() => _connectivityHandler.ExecuteCheckAsync(payload));
    break;
```

No se espera respuesta — es fire-and-forget desde la perspectiva del pipe.

### 7. Registro en Log

**Formato de log de resumen**:
```
[SVC] Event 1090: ConnectivityCheck: comando enviado al Tray (16 URLs, timeout=5s, retries=2)
[APP] Event 1090: ConnectivityCheck: inicio. Proxy=127.0.0.1:8999 (activo). URLs=16
[APP] Event 1090: ConnectivityCheck: completado. OK=14/16 (87%). Duración total=45s
[APP] Event 1091: ConnectivityCheck: FALLO idp.us.iss.lexmark.com — Timeout (3 intentos, última latencia=5000ms)
[APP] Event 1091: ConnectivityCheck: FALLO prod-lex-cloud-iot.azure-devices.net — HTTP 407 Proxy Auth Required (3 intentos)
```

## Flujo de Datos

```
alwaysconfig (JSON)
    ↓ (cargado por ActionEngine al inicio)
OnScheduledTask Timer (cada interval_seconds)
    ↓
ActionEngine.ExecuteConnectivityCheck()
    ↓ (extrae params, serializa payload)
PipeServer.SendToClient(MessageType.ConnectivityCheck, payload)
    ↓ (Named Pipe)
Tray.OnPipeMessageReceived()
    ↓ (deserializa ConnectivityCheckPayload)
ConnectivityCheckHandler.ExecuteCheckAsync()
    ↓ (detecta proxy, crea HttpClient)
    ↓ (ejecuta HEAD por cada URL con reintentos)
    ↓
Resultados → Log (AlwaysPrintLogger)
    ↓
Resultados → NotificationForm (UI thread vía Invoke)
```

## Consideraciones de Rendimiento

- Los checks se ejecutan **secuencialmente** (no en paralelo) para evitar saturar el proxy o disparar rate limits.
- Con 16 URLs × 5s timeout × 3 intentos × 30s delay = worst case ~24 minutos. En la práctica, las URLs que responden lo hacen en <1s, y las que fallan hacen timeout rápido. Caso típico: ~20-30 segundos para los 16 checks con reintentos.
- El intervalo de 300s (5 min) es suficiente margen para que un check complete antes del siguiente. Si un check aún está ejecutándose cuando el timer dispara de nuevo, se ignora (flag `_checkInProgress`).

## Consideraciones de Thread Safety

- `ConnectivityCheckHandler` mantiene un flag `_checkInProgress` (volatile bool) para evitar ejecuciones superpuestas.
- `NotificationForm` se crea/muestra siempre en el UI thread (`_uiContext.Post()` o `Invoke()`).
- El cierre del form anterior se hace en UI thread antes de crear el nuevo.

## Archivos Nuevos

| Archivo | Propósito |
|---------|-----------|
| `AlwaysPrintTray/Connectivity/ConnectivityCheckHandler.cs` | Orquestador: ejecuta checks, calcula resultados, invoca UI |
| `AlwaysPrintTray/Connectivity/UrlCheckResult.cs` | Modelo de resultado por URL |
| `AlwaysPrintTray/Forms/ConnectivityNotificationForm.cs` | Form de notificación (toast) |
| `AlwaysPrintTray/Forms/ConnectivityReportForm.cs` | Form de reporte detallado (tabla) |

## Archivos Modificados

| Archivo | Cambio |
|---------|--------|
| `AlwaysPrint.Shared/Messages/MessageType.cs` | Agregar `ConnectivityCheck` |
| `AlwaysPrint.Shared/Messages/Payloads.cs` | Agregar `ConnectivityCheckPayload` |
| `AlwaysPrint.Shared/Configuration/ActionConfig.cs` | Agregar `ActionTypes.ConnectivityCheck` |
| `AlwaysPrintService/Actions/ActionEngine.cs` | Agregar case + método `ExecuteConnectivityCheck` |
| `AlwaysPrintTray/TrayApplicationContext.cs` | Registrar handler para `MessageType.ConnectivityCheck` en `OnPipeMessageReceived` |
| `AlwaysPrintProject/AlwaysConfig/CPM_Compliant.alwaysconfig` | Agregar trigger `OnScheduledTask` con `ConnectivityCheck` |
