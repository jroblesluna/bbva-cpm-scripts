# Remote View — Especificación Técnica

## Resumen

Sistema de visualización y control remoto de workstations desde el dashboard AlwaysPrint. Permite a administradores y operadores ver la pantalla de una workstation en tiempo real, con opción de control remoto (mouse, teclado, clipboard).

## Modos de Operación

| Modo | Transporte | Latencia | Control Remoto | Caso de Uso |
|------|-----------|----------|----------------|-------------|
| **Screenshot** | WebSocket (JPEG bajo demanda) | 500ms+ | ❌ | Diagnóstico puntual, redes lentas |
| **Stream** | WebSocket (H.264/MSE) | 100-300ms | ❌ | Supervisión continua |
| **Interactive** | WebSocket (VNC/RFB) | 100-200ms | ✅ mouse+teclado+clipboard | Soporte L2/L3 |

Todos usan TCP vía WebSocket existente — funciona a través de proxy corporativo sin infraestructura adicional.

## Configuración por Organización

```json
{
  "remote_view": {
    "enabled": true,
    "modes_allowed": ["screenshot", "stream", "interactive"],
    "default_mode": "stream",
    "remote_control_enabled": true,
    "clipboard_sharing_enabled": true,
    "require_user_consent": true,
    "max_concurrent_sessions": 4,
    "session_timeout_minutes": 5,
    "stream_default_quality": "auto",
    "stream_max_fps": 5
  }
}
```

### Campos

| Campo | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| `enabled` | bool | false | Habilitar/deshabilitar feature completo |
| `modes_allowed` | string[] | ["screenshot"] | Modos disponibles para la org |
| `default_mode` | string | "screenshot" | Modo inicial al conectar |
| `remote_control_enabled` | bool | false | Permitir mouse/teclado en Interactive |
| `clipboard_sharing_enabled` | bool | false | Compartir clipboard bidireccional |
| `require_user_consent` | bool | true | Mostrar popup de consentimiento al usuario |
| `max_concurrent_sessions` | int | 4 | Máx sesiones por operador/admin (0=ilimitado) |
| `session_timeout_minutes` | int | 5 | Timeout por inactividad |
| `stream_default_quality` | string | "auto" | "auto", "720p", "480p", "360p" |
| `stream_max_fps` | int | 5 | FPS máximo para Stream mode |

## UX / Frontend

### Acceso

- Botón dentro del ícono "Ojo" (Ver Detalles) de cada workstation
- Solo visible si `remote_view.enabled = true` para la organización
- Solo activo si la WS está online
- Admin y Operador pueden acceder (operador solo WS de su organización)

### Sesión de Vista Remota

Cada sesión se abre en un **Tab** dentro de una página dedicada `/dashboard/remote-view`.

**Header de cada Tab:**
```
[●] 118.245.114.41 — W1084901P01 | Monitor: [Principal ▼] | Resolución: [Auto ▼] | Mode: [Stream ▼] | ⏱ 3:42 | [✕ Cerrar]
```

**Contenido del Tab:**
- Canvas/video que muestra la pantalla remota
- En modo Interactive: cursor del admin visible, input capturado
- Barra inferior con controles (Ctrl+Alt+Del, clipboard, cambiar monitor)

### Múltiples Sesiones

- Tabs horizontales en la parte superior
- Cada tab muestra IP + hostname de la WS
- Tab activo = sesión activa (recibiendo frames)
- Tabs inactivos = sesión pausada (no consume bandwidth)
- Límite de tabs = `max_concurrent_sessions` de la organización

### Resolución (cambiable en tiempo real)

| Opción | Resolución enviada | Uso |
|--------|-------------------|-----|
| Auto | Se ajusta según bandwidth detectado | Default |
| 720p | 1280×720 | Balance calidad/tráfico |
| 480p | 854×480 | Redes lentas |
| 360p | 640×360 | Mínimo funcional |

### Selección de Monitor

- Al conectar, el cliente reporta monitores disponibles (nombre, resolución)
- Dropdown en el header del tab para cambiar entre monitores
- Default: monitor principal

## Exclusividad de Sesión

- **Una sola sesión activa por workstation** a la vez
- Si un admin/operador intenta conectarse a una WS que ya tiene sesión activa:
  - Muestra: "Esta workstation ya está siendo monitoreada por [nombre_usuario]"
  - No permite conectar
- El mismo usuario no puede abrir dos tabs a la misma WS
- Al desconectar (cerrar tab, timeout, o navegar fuera) → la sesión se libera inmediatamente

## Consentimiento del Usuario

Cuando `require_user_consent = true`:

1. Al iniciar sesión, el Tray muestra popup al usuario:
   ```
   ┌─────────────────────────────────────────┐
   │  🖥️ Solicitud de Vista Remota           │
   │                                         │
   │  [Nombre Admin] solicita ver tu         │
   │  pantalla.                              │
   │                                         │
   │  [Permitir]  [Rechazar]                 │
   │                                         │
   │  Respuesta automática en 30s: Rechazar  │
   └─────────────────────────────────────────┘
   ```
2. Si acepta → sesión inicia
3. Si rechaza → admin ve "El usuario rechazó la conexión" + botón "Reintentar"
4. Si no responde en 30s → se rechaza automáticamente
5. Mientras la sesión está activa, el Tray muestra ícono/indicador de "siendo monitoreado"

Cuando `require_user_consent = false`:
- La sesión inicia inmediatamente sin preguntar
- El Tray muestra indicador visual de monitoreo activo (obligatorio por ética/legalidad)

## Timeout por Inactividad

- El timer se resetea con cualquier interacción del admin (click en el canvas, cambio de tab, cambio de resolución)
- 60s antes del timeout: mensaje "La sesión se cerrará por inactividad en 60s"
- Al expirar: sesión se cierra, tab se marca como "Sesión expirada"

## Protocolo de Comunicación

### Señalización (WebSocket existente)

```
Admin→Backend→WS: {"type":"remote_view_start", "session_id":"...", "mode":"stream", "resolution":"720p", "monitor":0}
WS→Backend→Admin: {"type":"remote_view_accepted", "session_id":"...", "monitors":[{"name":"Principal","width":1920,"height":1080},...]}
WS→Backend→Admin: {"type":"remote_view_rejected", "session_id":"...", "reason":"user_declined"}
Admin→Backend→WS: {"type":"remote_view_stop", "session_id":"..."}
```

### Datos de Pantalla

#### Screenshot Mode
```
WS→Backend→Admin: {"type":"frame", "session_id":"...", "data":"base64_jpeg", "timestamp":...}
```
- Admin solicita frame, WS responde con JPEG
- Botón "Refresh" o auto-refresh cada 2s

#### Stream Mode
```
WS→Backend→Admin: {"type":"frame", "session_id":"...", "data":"base64_h264_nal", "keyframe":true/false, "timestamp":...}
```
- WS envía frames continuamente (1-5 FPS configurable)
- Frontend decodifica con MSE (Media Source Extensions) en `<video>`
- Keyframe cada 2s para permitir join tardío

#### Interactive Mode
```
WS→Backend→Admin: {"type":"frame", ...} // Igual que Stream
Admin→Backend→WS: {"type":"input", "session_id":"...", "event":"mousemove", "x":500, "y":300}
Admin→Backend→WS: {"type":"input", "session_id":"...", "event":"keydown", "key":"a", "modifiers":["ctrl"]}
Admin→Backend→WS: {"type":"clipboard", "session_id":"...", "text":"contenido copiado"}
WS→Backend→Admin: {"type":"clipboard", "session_id":"...", "text":"contenido del clipboard remoto"}
```

## Implementación por Componente

### Cliente C# (Tray)

| Clase | Responsabilidad |
|-------|-----------------|
| `ScreenCapturer` | Captura pantalla con `Graphics.CopyFromScreen()` o Desktop Duplication API |
| `FrameEncoder` | Comprime a JPEG (screenshot) o H.264 (stream) |
| `RemoteViewSession` | Gestiona estado de sesión, timeout, consentimiento |
| `InputInjector` | Inyecta eventos mouse/teclado con `SendInput()` API |
| `ClipboardBridge` | Sincroniza clipboard vía `Clipboard.GetText()`/`SetText()` |

### Backend (Python/FastAPI)

| Componente | Responsabilidad |
|------------|-----------------|
| Endpoint POST `/workstations/{id}/remote-view/start` | Inicia sesión, verifica permisos y exclusividad |
| Endpoint POST `/workstations/{id}/remote-view/stop` | Termina sesión |
| Endpoint GET `/workstations/{id}/remote-view/status` | Estado de sesión activa (quién está conectado) |
| WebSocket relay | Retransmite frames WS→Admin y input Admin→WS |
| SessionManager | Tracking de sesiones activas, timeouts, limpieza |

### Frontend (Next.js)

| Componente | Responsabilidad |
|------------|-----------------|
| `RemoteViewPage` | Página con tabs de sesiones activas |
| `RemoteViewTab` | Canvas/video + controles por sesión |
| `ScreenshotViewer` | Muestra JPEG con botón refresh |
| `StreamViewer` | Decodifica H.264 con MSE |
| `InteractiveViewer` | Stream + captura de mouse/teclado + envío |
| `ConsentDialog` | Muestra estado de consentimiento pendiente |
| `SessionHeader` | IP, hostname, monitor selector, resolution, timer |

## Audit Trail

Cada sesión registra en `audit_log`:
- `action_type`: REMOTE_VIEW_START / REMOTE_VIEW_STOP
- `entity_type`: workstation
- `entity_id`: workstation_id
- `user_id`: quién conectó
- `new_values`: {mode, duration_seconds, monitor, consent_given}

## Modelo de Datos

### Tabla `remote_view_sessions`

| Campo | Tipo | Descripción |
|-------|------|-------------|
| id | UUID | PK |
| workstation_id | UUID | FK workstations |
| user_id | UUID | FK users (quién inició) |
| organization_id | UUID | FK organizations |
| mode | enum | screenshot/stream/interactive |
| status | enum | pending_consent/active/expired/rejected/closed |
| started_at | timestamp | Inicio |
| ended_at | timestamp | Fin (null si activa) |
| last_activity_at | timestamp | Última interacción del admin |
| monitor_index | int | Monitor seleccionado |
| resolution | string | Resolución actual |

## Fases de Implementación

### Fase 1: Screenshot (1-2 días)
- Captura JPEG en Tray
- Endpoint start/stop + relay por WebSocket
- Frontend: dialog con imagen + refresh button
- Consentimiento básico
- Audit trail

### Fase 2: Stream H.264 (3-5 días)
- Desktop Duplication API + Media Foundation encoder en Tray
- MSE decoder en frontend
- Cambio de resolución en vivo
- Selección de monitor
- Timeout por inactividad

### Fase 3: Interactive VNC (3-5 días)
- InputInjector con SendInput API
- Captura de mouse/teclado en frontend
- Clipboard bidireccional
- Indicador visual en Tray ("siendo monitoreado")

### Fase 4: Configuración + UI (2-3 días)
- Settings de organización en frontend
- Página de tabs con múltiples sesiones
- Exclusividad + mensajes de ocupado
- Límite de sesiones concurrentes

## Seguridad

- Solo admin/operador autenticado puede iniciar sesión
- Operador solo ve WS de su organización (tenant isolation)
- Sesiones se invalidan al cerrar sesión del admin
- Frames no se persisten (solo relay en memoria)
- Audit trail inmutable
- Indicador visual obligatorio en la WS monitoreada (no se puede ocultar)
- Clipboard sharing es opt-in por organización

## Consideraciones de Performance

- Stream a 3 FPS, 720p, JPEG quality 70 ≈ 150-300 KB/s por sesión
- H.264 stream a 5 FPS, 720p ≈ 200-500 KB/s por sesión
- Con 4 sesiones simultáneas: máx 2 MB/s de tráfico por admin
- Backend solo hace relay (no procesa video) — cero CPU adicional
- Tray: captura + encode ≈ 5-10% CPU en la WS monitoreada
