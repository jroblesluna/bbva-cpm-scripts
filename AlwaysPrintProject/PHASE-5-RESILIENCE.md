# Fase 5 — Resiliencia Offline, Notificaciones y Modo Degradado

**Prerrequisito**: Fase 4 completada  
**Entregable**: El Tray opera correctamente sin conexión a la nube, notifica al usuario de forma no invasiva y gestiona el modo degradado  
**Estimación**: 3–4 días

---

## Objetivo

1. **Modo offline completo**: operar indefinidamente con la última config descargada
2. **Notificación no invasiva**: balloon tip pequeño a 1 hora de desconexión, repetir cada 2 horas
3. **Log de desconexiones**: registrar inicio/fin de cada período offline
4. **Reconexión transparente**: al volver a conectar, sincronizar config y limpiar estado offline
5. **Telemetría offline**: acumular telemetría en memoria y enviarla al reconectar

---

## Estados del Tray respecto a la Nube

```
CloudEnabled = 0
    → CLOUD_DISABLED (no intenta conectar, sin notificaciones)

CloudEnabled = 1, conectado
    → CLOUD_CONNECTED (operación normal)

CloudEnabled = 1, desconectado < 1 hora
    → CLOUD_OFFLINE_GRACE (sin notificación al usuario)

CloudEnabled = 1, desconectado ≥ 1 hora
    → CLOUD_OFFLINE_NOTIFIED (balloon tip mostrado, repetir cada 2 horas)

CloudEnabled = 1, sin config cacheada y desconectado
    → CLOUD_OFFLINE_NO_CONFIG (warning más prominente, operar con defaults)
```

---

## Componentes

### 5.1 — `OfflineStateManager.cs`

**Archivo**: `AlwaysPrintProject/Client/AlwaysPrintTray/Cloud/OfflineStateManager.cs`

```csharp
namespace AlwaysPrintTray.Cloud
{
    /// <summary>
    /// Gestiona el estado offline del Tray respecto a la nube.
    ///
    /// Reglas:
    ///   - Desconexión < 1 hora: silencioso
    ///   - Desconexión ≥ 1 hora: balloon tip (una vez)
    ///   - Cada 2 horas adicionales: repetir balloon tip
    ///   - Al reconectar: limpiar estado, no mostrar notificación
    /// </summary>
    public sealed class OfflineStateManager
    {
        private DateTime? _disconnectedAt;
        private DateTime? _lastNotifiedAt;
        private readonly SynchronizationContext _uiContext;
        private readonly NotifyIcon _trayIcon;

        private static readonly TimeSpan GracePeriod       = TimeSpan.FromHours(1);
        private static readonly TimeSpan NotifyRepeatEvery = TimeSpan.FromHours(2);

        public bool IsOffline => _disconnectedAt.HasValue;
        public TimeSpan? OfflineDuration => _disconnectedAt.HasValue
            ? DateTime.UtcNow - _disconnectedAt.Value
            : (TimeSpan?)null;

        public OfflineStateManager(SynchronizationContext uiContext, NotifyIcon trayIcon) { }

        /// <summary>Llamar cuando se pierde la conexión con APCM.</summary>
        public void OnDisconnected()
        {
            _disconnectedAt = DateTime.UtcNow;
            _lastNotifiedAt = null;
            // Iniciar timer de verificación cada 5 minutos
        }

        /// <summary>Llamar cuando se restaura la conexión con APCM.</summary>
        public void OnReconnected()
        {
            _disconnectedAt = null;
            _lastNotifiedAt = null;
            // Detener timer
        }

        /// <summary>Verificar si corresponde mostrar notificación. Llamar periódicamente.</summary>
        public void CheckAndNotify()
        {
            if (!IsOffline) return;

            var duration = OfflineDuration!.Value;

            // Primera notificación: al superar 1 hora
            if (duration >= GracePeriod && _lastNotifiedAt == null)
            {
                ShowOfflineNotification();
                _lastNotifiedAt = DateTime.UtcNow;
                return;
            }

            // Notificaciones repetidas: cada 2 horas
            if (_lastNotifiedAt.HasValue &&
                DateTime.UtcNow - _lastNotifiedAt.Value >= NotifyRepeatEvery)
            {
                ShowOfflineNotification();
                _lastNotifiedAt = DateTime.UtcNow;
            }
        }

        private void ShowOfflineNotification()
        {
            _uiContext.Post(_ =>
            {
                _trayIcon.BalloonTipIcon  = ToolTipIcon.Warning;
                _trayIcon.BalloonTipTitle = LocalizationManager.Get("BalloonOfflineTitle");
                _trayIcon.BalloonTipText  = LocalizationManager.Get("BalloonOfflineText");
                _trayIcon.ShowBalloonTip(4000);
            }, null);
        }
    }
}
```

**Strings i18n necesarios** (agregar a `Strings.resx` y `Strings.es.resx`):

| Key | Español | English |
|---|---|---|
| `BalloonOfflineTitle` | `AlwaysPrint` | `AlwaysPrint` |
| `BalloonOfflineText` | `Usando configuración guardada. Sin conexión a la nube.` | `Using cached config. No cloud connection.` |
| `BalloonOfflineNoConfig` | `Sin conexión a la nube y sin configuración guardada. Usando valores por defecto.` | `No cloud connection and no cached config. Using defaults.` |
| `BalloonReconnected` | `Conexión con la nube restaurada.` | `Cloud connection restored.` |
| `TooltipOffline` | `AlwaysPrint (sin conexión)` | `AlwaysPrint (offline)` |

---

### 5.2 — Icono del Tray en modo offline

Cambiar el icono del tray para indicar visualmente el estado offline:

```csharp
// En OfflineStateManager.ShowOfflineNotification():
// Cambiar icono a versión "gris" o con indicador de desconexión
_trayIcon.Icon = LoadOfflineIcon();
_trayIcon.Text = LocalizationManager.Get("TooltipOffline");

// En OnReconnected():
_trayIcon.Icon = LoadNormalIcon();
_trayIcon.Text = LocalizationManager.Get("TrayTooltip");
```

Crear `logo_offline.ico` (versión gris del logo) y embeber como recurso.

---

### 5.3 — Telemetría offline: acumulación y envío al reconectar

En `TelemetryReporter`, si el WebSocket no está conectado, acumular en memoria:

```csharp
private readonly Queue<TelemetryPayload> _pendingTelemetry = new Queue<TelemetryPayload>();
private const int MaxPendingTelemetry = 100;  // evitar crecimiento ilimitado

private void SendOrQueue(TelemetryPayload payload)
{
    if (_wsClient.IsConnected)
    {
        _wsClient.Send("telemetry", payload);
    }
    else
    {
        if (_pendingTelemetry.Count >= MaxPendingTelemetry)
            _pendingTelemetry.Dequeue();  // descartar el más antiguo
        _pendingTelemetry.Enqueue(payload);
    }
}

// Llamar al reconectar:
public void FlushPending()
{
    while (_pendingTelemetry.Count > 0 && _wsClient.IsConnected)
    {
        var payload = _pendingTelemetry.Dequeue();
        _wsClient.Send("telemetry", payload);
    }
}
```

---

### 5.4 — Modo sin config cacheada

Si `CloudEnabled=1` pero no hay config en cache y no hay conexión:

```csharp
// En CloudManager.Start():
var cachedConfig = _configSync.LoadFromCache();
if (cachedConfig == null && !_wsClient.IsConnected)
{
    AlwaysPrintLogger.WriteTrayWarning(
        "Sin conexión a la nube y sin configuración cacheada. Usando defaults.",
        AlwaysPrintLogger.EvtGenericWarning);

    ShowBalloon(
        LocalizationManager.Get("BalloonOfflineTitle"),
        LocalizationManager.Get("BalloonOfflineNoConfig"),
        ToolTipIcon.Warning);
}
else if (cachedConfig != null)
{
    // Aplicar config cacheada al Service mientras se conecta
    ApplyCachedConfig(cachedConfig);
}
```

---

### 5.5 — Integración en `CloudManager`

```csharp
// En CloudManager:
private readonly OfflineStateManager _offlineState;

// Al iniciar:
_offlineState = new OfflineStateManager(_uiContext, _trayIcon);

// Al desconectar:
_wsClient.Disconnected += () =>
{
    IsConnected = false;
    UsingCachedConfig = true;
    _offlineState.OnDisconnected();
    _telemetryReporter.RecordDisconnection(DateTime.UtcNow);
    NotifyServiceCloudStatus(connected: false);
};

// Al reconectar:
_wsClient.Connected += () =>
{
    IsConnected = true;
    UsingCachedConfig = false;
    _offlineState.OnReconnected();
    _telemetryReporter.FlushPending();
    NotifyServiceCloudStatus(connected: true);
    ShowBalloon(
        LocalizationManager.Get("BalloonOfflineTitle"),
        LocalizationManager.Get("BalloonReconnected"),
        ToolTipIcon.Info);
};
```

---

### 5.6 — Log de desconexiones en `TelemetryReporter`

```csharp
private readonly List<DisconnectionEvent> _disconnectionLog = new List<DisconnectionEvent>();
private DisconnectionEvent? _currentDisconnection;

public void RecordDisconnection(DateTime startedAt)
{
    _currentDisconnection = new DisconnectionEvent
    {
        StartedAt = startedAt.ToString("o")
    };
}

public void RecordReconnection(DateTime reconnectedAt)
{
    if (_currentDisconnection == null) return;
    _currentDisconnection.ReconnectedAt  = reconnectedAt.ToString("o");
    _currentDisconnection.DurationSeconds = (long)(reconnectedAt - DateTime.Parse(_currentDisconnection.StartedAt)).TotalSeconds;
    _disconnectionLog.Add(_currentDisconnection);
    _currentDisconnection = null;
}
```

---

## Criterios de Aceptación

- [ ] Con `CloudEnabled=0`: sin notificaciones de offline, sin intentos de conexión
- [ ] Desconexión < 1 hora: sin notificación al usuario
- [ ] Desconexión ≥ 1 hora: balloon tip pequeño, no invasivo
- [ ] Balloon tip se repite cada 2 horas mientras persiste la desconexión
- [ ] Al reconectar: balloon tip de "conexión restaurada", icono vuelve a normal
- [ ] El icono del tray cambia visualmente en modo offline
- [ ] La telemetría acumulada offline se envía al reconectar (máx 100 entradas)
- [ ] Sin config cacheada + offline: warning más prominente, operar con defaults
- [ ] El log de desconexiones incluye inicio, fin y duración de cada período

---

## Notas para el Desarrollador

- El balloon tip de offline debe ser **pequeño y no invasivo** — no usar `MessageBox` ni ventanas modales.
- El timer de verificación de estado offline se ejecuta cada 5 minutos en un thread de fondo.
- El icono offline puede ser simplemente el mismo logo con reducción de opacidad o en escala de grises.
- La telemetría pendiente tiene un límite de 100 entradas para evitar crecimiento ilimitado en memoria.
- Al reconectar, enviar la telemetría pendiente **antes** de la siguiente telemetría periódica.
