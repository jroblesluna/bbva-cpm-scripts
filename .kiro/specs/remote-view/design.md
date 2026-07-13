# Design Document: Remote View

## Overview

Sistema de visualización y control remoto de workstations que opera íntegramente sobre la infraestructura WebSocket TCP existente. El backend actúa exclusivamente como relay de bytes (zero processing de video). Tres modos progresivos: Screenshot (JPEG bajo demanda), Stream (H.264 continuo), Interactive (Stream + input injection).

Referencia de requisitos: #[[file:.kiro/specs/remote-view/requirements.md]]

## Architecture

### Diagrama de Flujo Principal

```
Admin Browser                   Backend (FastAPI/uvicorn)           Workstation Tray (C#)
     |                                   |                                   |
     |── POST /remote-view/start ───────>|                                   |
     |                                   |── WS: remote_view_start ─────────>|
     |                                   |                                   |── [consent popup si requerido]
     |                                   |<── WS: remote_view_accepted ──────|   (monitors, resolutions)
     |<── 200 {session_id, monitors} ────|                                   |
     |                                   |                                   |
     |═══════ FRAME RELAY LOOP (WebSocket) ══════════════════════════════════|
     |                                   |                                   |
     |── WS(op): rv_request_frame ──────>|── WS(ws): rv_request_frame ──────>|  [Screenshot mode]
     |<── WS(op): rv_frame {jpeg_b64} ──|<── WS(ws): rv_frame ─────────────|
     |                                   |                                   |
     |<── WS(op): rv_frame {h264_nal} ──|<── WS(ws): rv_frame (binary) ────|  [Stream mode: continuo]
     |                                   |                                   |
     |── WS(op): rv_input {mouse/key} ─>|── WS(ws): rv_input ─────────────>|  [Interactive mode]
     |── WS(op): rv_clipboard ─────────>|── WS(ws): rv_clipboard ─────────>|
     |<── WS(op): rv_clipboard ────────|<── WS(ws): rv_clipboard ─────────|
     |                                   |                                   |
     |── POST /remote-view/stop ────────>|── WS: remote_view_stop ─────────>|
     |                                   |   (cleanup session in DB)          |── [quitar indicador visual]
```

### Cross-Worker Relay

Cuando el admin (operador WebSocket) está en worker_A y la workstation está en worker_B:

```
Admin WS ──> worker_A ──> Redis pub/sub (canal: rv_session:{session_id}) ──> worker_B ──> Workstation WS
Workstation WS ──> worker_B ──> Redis pub/sub (canal: rv_session:{session_id}:frames) ──> worker_A ──> Admin WS
```

Cada sesión activa tiene 2 canales Redis dedicados:
- `rv_session:{session_id}:commands` — admin→WS (request_frame, input, config changes, stop)
- `rv_session:{session_id}:frames` — WS→admin (frames, clipboard, monitor info)

El SessionManager registra `session_id → {ws_worker_id, admin_worker_id}` para routing directo.

## Componentes por Capa

### Backend (Python/FastAPI)

| Archivo | Responsabilidad |
|---------|-----------------|
| `app/models/remote_view.py` | Modelo SQLAlchemy `RemoteViewSession` |
| `app/schemas/remote_view.py` | Schemas Pydantic: StartRequest, SessionResponse, StatusResponse |
| `app/services/remote_view_session.py` | SessionManager: create, end, get_active, check_timeout, cleanup |
| `app/api/v1/endpoints/remote_view.py` | REST endpoints: start, stop, status |
| `app/api/v1/websocket/workstation.py` | Handler de `rv_frame` entrante (relay a admin) |
| `app/api/v1/websocket/operator.py` | Handler de `rv_request_frame`, `rv_input`, `rv_clipboard` (relay a WS) |
| `app/services/remote_view_relay.py` | Lógica de relay cross-worker vía Redis pub/sub |

### Frontend (Next.js/TypeScript)

| Archivo | Responsabilidad |
|---------|-----------------|
| `src/app/dashboard/remote-view/page.tsx` | Página con tabs de sesiones activas |
| `src/components/remote-view/SessionTab.tsx` | Container de una sesión individual |
| `src/components/remote-view/SessionHeader.tsx` | Barra de controles: monitor, resolución, modo, timer, cerrar |
| `src/components/remote-view/ScreenshotViewer.tsx` | Visor JPEG + refresh/auto-refresh |
| `src/components/remote-view/StreamViewer.tsx` | Decodificador H.264/MSE en `<video>` |
| `src/components/remote-view/InteractiveViewer.tsx` | StreamViewer + captura mouse/teclado + envío |
| `src/components/remote-view/ConsentPending.tsx` | Estado "Esperando aprobación..." con countdown |
| `src/components/remote-view/TimeoutWarning.tsx` | Overlay "Sesión se cerrará en 60s" |
| `src/types/remote-view.ts` | Tipos: Session, Monitor, Frame, InputEvent |

### Cliente C# (AlwaysPrintTray)

| Clase | Namespace | Responsabilidad |
|-------|-----------|-----------------|
| `RemoteViewSession` | `AlwaysPrintTray.RemoteView` | Estado de sesión activa, consent flow, indicador visual |
| `ScreenCapturer` | `AlwaysPrintTray.RemoteView` | Captura pantalla con GDI+ o Desktop Duplication API |
| `MonitorEnumerator` | `AlwaysPrintTray.RemoteView` | Lista monitores via `Screen.AllScreens` con metadata |
| `JpegEncoder` | `AlwaysPrintTray.RemoteView` | Escala + comprime a JPEG con quality configurable |
| `H264Encoder` | `AlwaysPrintTray.RemoteView` | Encodea via Media Foundation (hardware/software) |
| `FrameStreamer` | `AlwaysPrintTray.RemoteView` | Loop de captura continua a N FPS, envía por WebSocket |
| `InputInjector` | `AlwaysPrintTray.RemoteView` | Inyecta mouse/teclado con `SendInput()` API |
| `ClipboardBridge` | `AlwaysPrintTray.RemoteView` | Monitorea clipboard con `AddClipboardFormatListener`, sync bidireccional |
| `ConsentPopup` | `AlwaysPrintTray.RemoteView` | WinForms dialog para aceptar/rechazar con countdown |

## Modelo de Datos

### Tabla `remote_view_sessions`

```sql
CREATE TABLE remote_view_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workstation_id UUID NOT NULL REFERENCES workstations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    mode VARCHAR(20) NOT NULL DEFAULT 'screenshot',  -- screenshot, stream, interactive
    status VARCHAR(20) NOT NULL DEFAULT 'pending_consent',  -- pending_consent, active, expired, rejected, closed
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMP WITH TIME ZONE,
    last_activity_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    monitor_index INT NOT NULL DEFAULT 0,
    resolution VARCHAR(10) NOT NULL DEFAULT 'auto',
    end_reason VARCHAR(30),  -- timeout, admin_closed, ws_disconnected, user_rejected, user_timeout, admin_logout
    consent_given BOOLEAN,  -- true=accepted, false=rejected, null=not_required
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_rv_sessions_ws_status ON remote_view_sessions(workstation_id, status) WHERE status IN ('pending_consent', 'active');
CREATE INDEX ix_rv_sessions_user_status ON remote_view_sessions(user_id, status) WHERE status = 'active';
CREATE INDEX ix_rv_sessions_org ON remote_view_sessions(organization_id);
```

### Campo `remote_view` en Organization (JSONB)

```json
{
  "enabled": false,
  "modes_allowed": ["screenshot"],
  "default_mode": "screenshot",
  "remote_control_enabled": false,
  "clipboard_sharing_enabled": false,
  "require_user_consent": true,
  "max_concurrent_sessions": 4,
  "session_timeout_minutes": 5,
  "quality_mode": "auto",
  "capture_resolution": "1280x720",
  "compression_quality": 70,
  "viewport_adaptive_downscale": true,
  "stream_max_fps": 5
}
```

## Protocolo de Mensajes WebSocket

### Señalización (JSON)

```jsonc
// Admin → Backend → WS: Iniciar sesión
{
  "type": "remote_view_start",
  "session_id": "uuid",
  "mode": "stream",
  "resolution": "720p",
  "quality": 70,
  "monitor": 0,
  "user_name": "Javier Robles",
  "viewport_width": 960,
  "viewport_height": 540
}

// WS → Backend → Admin: Sesión aceptada
{
  "type": "remote_view_accepted",
  "session_id": "uuid",
  "monitors": [
    {"index": 0, "name": "Principal", "width": 1920, "height": 1080, "primary": true},
    {"index": 1, "name": "Monitor 2", "width": 1920, "height": 1080, "primary": false}
  ]
}

// WS → Backend → Admin: Sesión rechazada
{
  "type": "remote_view_rejected",
  "session_id": "uuid",
  "reason": "user_declined"  // user_declined | user_timeout
}

// Admin → Backend → WS: Cambio de configuración en vivo
{
  "type": "remote_view_config",
  "session_id": "uuid",
  "resolution": "480p",
  "quality": 60,
  "monitor": 1,
  "fps": 3,
  "viewport_width": 800,
  "viewport_height": 450
}

// Admin → Backend → WS: Pausar/Reanudar (tab switching)
{
  "type": "remote_view_pause",  // o remote_view_resume
  "session_id": "uuid"
}

// Admin → Backend → WS: Terminar sesión
{
  "type": "remote_view_stop",
  "session_id": "uuid",
  "reason": "admin_closed"
}
```

### Frames (Screenshot mode — JSON)

```jsonc
// Admin → Backend → WS: Solicitar frame
{
  "type": "rv_request_frame",
  "session_id": "uuid"
}

// WS → Backend → Admin: Frame JPEG
{
  "type": "rv_frame",
  "session_id": "uuid",
  "format": "jpeg",
  "width": 1280,
  "height": 720,
  "data": "base64_encoded_jpeg..."
}
```

### Frames (Stream mode — Binary WebSocket)

Para performance, los frames H.264 se envían como binary WebSocket frames con header compacto:

```
[4 bytes: session_id_hash (primeros 4 bytes del UUID)]
[1 byte: flags]
  bit 0: keyframe (1=IDR)
  bit 1-2: monitor_index (0-3)
  bit 3-7: reserved
[2 bytes: width (uint16 big-endian)]
[2 bytes: height (uint16 big-endian)]
[N bytes: H.264 NAL unit payload]
```

Total header: 9 bytes. El frontend matchea el session_id_hash con la sesión activa para rutear al tab correcto.

### Input (Interactive mode — JSON)

```jsonc
// Mouse
{
  "type": "rv_input",
  "session_id": "uuid",
  "event": "mousemove",  // mousemove, mousedown, mouseup, wheel
  "x": 500,              // coordenada X normalizada (0.0 - 1.0 del stream)
  "y": 300,              // coordenada Y normalizada (0.0 - 1.0 del stream)
  "button": "left",      // left, right, middle (solo para mousedown/up)
  "delta": 120           // solo para wheel (positivo=scroll up)
}

// Teclado
{
  "type": "rv_input",
  "session_id": "uuid",
  "event": "keydown",    // keydown, keyup
  "code": "KeyA",        // KeyboardEvent.code (layout-independent)
  "key": "a",            // KeyboardEvent.key (para display)
  "modifiers": ["ctrl"]  // ctrl, alt, shift, meta (array de activos)
}

// Ctrl+Alt+Del (botón especial)
{
  "type": "rv_input",
  "session_id": "uuid",
  "event": "sas"         // Secure Attention Sequence
}

// Clipboard
{
  "type": "rv_clipboard",
  "session_id": "uuid",
  "direction": "to_ws",  // to_ws | to_admin
  "text": "contenido del clipboard"
}
```

## Resolución y Calidad: Lógica de Auto-Adjust

Cuando `quality_mode = "auto"`:

```
Niveles (ordenados de mayor a menor calidad):
  Level 4: 1920×1080, quality=80%, target ~150KB/frame
  Level 3: 1280×720, quality=70%, target ~80KB/frame  ← DEFAULT START
  Level 2: 854×480, quality=60%, target ~40KB/frame
  Level 1: 640×360, quality=50%, target ~20KB/frame

Algoritmo (ejecutado cada 10 frames):
  avg_rtt = promedio RTT de los últimos 10 frames
  IF avg_rtt > 2000ms → bajar 1 nivel (min: Level 1)
  IF avg_rtt < 500ms → subir 1 nivel (max: Level 4)
  IF avg_rtt entre 500-2000ms → mantener nivel actual
```

RTT se mide en Screenshot mode como tiempo entre `rv_request_frame` y recepción de `rv_frame`. En Stream mode, se mide con un ping periódico cada 5s (el Tray responde con timestamp del frame, el frontend calcula la diferencia).

### Viewport-Adaptive Downscale

Cuando está habilitado:
1. Frontend reporta `viewport_width` y `viewport_height` al iniciar sesión y al redimensionar (con 1s debounce)
2. Si `viewport_width < capture_resolution_width` → el Tray escala la captura a `viewport_width × viewport_height` antes de encodear
3. Si `viewport_width >= capture_resolution_width` → se envía a capture_resolution (no upscale)
4. El cálculo respeta aspect ratio del monitor (puede haber letterboxing)

## SessionManager: Ciclo de Vida

```
                    ┌─── user_rejected ───> [rejected]
                    │
[not exists] ──> [pending_consent] ──> [active] ──> [closed]
                    │                      │  │         ↑
                    └─── user_timeout ─────┘  │         │
                                              │    admin_closed
                                              │    admin_logout
                                              ↓
                                          [expired] (timeout)
                                              │
                                              ↓
                                          [closed] (ws_disconnected after 30s)
```

### Cleanup periódico (cada 60s):
- Buscar sesiones `active` donde `last_activity_at < NOW() - session_timeout_minutes`
- Marcar como `expired`, enviar `remote_view_stop` a la WS
- Buscar sesiones `pending_consent` donde `started_at < NOW() - 35s` (30s consent + 5s grace)
- Marcar como `rejected` con reason `user_timeout`

## Seguridad

| Control | Implementación |
|---------|---------------|
| Autenticación | JWT validation en endpoint start + WebSocket handshake |
| Autorización | Role check (admin/operator) + org matching para operators |
| Tenant isolation | `organization_id` filter en todas las queries |
| No persistencia | Frames relay en memoria, nunca llegan a disco/BD |
| Indicador visual | Ícono overlay en Tray no-dismissable mientras sesión activa |
| Expiración sesiones | JWT expiry → backend cierra todas las sesiones del user |
| Clipboard control | Solo activo si `clipboard_sharing_enabled=true` en org config |
| TLS | Todos los WebSocket son wss:// (TLS 1.3) |

## Performance

| Métrica | Valor esperado | Límite |
|---------|---------------|--------|
| CPU backend (relay only) | ~0.5ms por frame | 30 sesiones × 5 FPS = 75ms/s = 7.5% core |
| Memoria backend (buffers) | ~500KB por sesión activa | 30 sesiones = 15 MB |
| CPU workstation (captura+encode) | 5-10% | Backpressure reduce si > threshold |
| Bandwidth por sesión (Stream) | 200-500 KB/s | Configurable via quality/fps |
| Latencia end-to-end (Stream) | 100-300ms | Depende de red + proxy |
| Sesiones concurrentes soportadas | 30-40 | Sin degradar telemetría/HTTP |
| Redis pub/sub overhead | ~0.3ms por frame cross-worker | Negligible con 30 sesiones |
