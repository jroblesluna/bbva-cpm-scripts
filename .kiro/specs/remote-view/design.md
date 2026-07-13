# Design Document: Remote View

## Overview

Sistema de visualización y control remoto de workstations desde el dashboard AlwaysPrint, implementado en 3 modos sobre WebSocket TCP existente. No requiere infraestructura adicional (TURN, STUN, VPN). Compatible con proxies corporativos.

Referencia de diseño completa: #[[file:AlwaysPrintProject/Cloud/REMOTE_VIEW_SPEC.md]]

## Architecture

### Diagrama de flujo

```
Admin Browser                Backend (FastAPI)              Workstation Tray
     |                            |                              |
     |-- POST /remote-view/start -|                              |
     |                            |-- WS: remote_view_start ---->|
     |                            |                              |-- [consent popup?]
     |                            |<-- WS: remote_view_accepted -|
     |<-- 200 {session_id} -------|                              |
     |                            |                              |
     |== Frame relay loop (WebSocket) ===========================|
     |                            |                              |
     |<-- WS: frame (jpeg/h264) --|<-- WS: frame --------------|
     |-- WS: input (mouse/key) -->|-- WS: input --------------->|
     |                            |                              |
     |-- POST /remote-view/stop --|                              |
     |                            |-- WS: remote_view_stop ----->|
```

### Componentes

#### Backend (Python/FastAPI)

| Archivo | Responsabilidad |
|---------|-----------------|
| `app/api/v1/endpoints/remote_view.py` | Endpoints REST: start, stop, status |
| `app/services/remote_view_session.py` | SessionManager: tracking, timeout, exclusividad |
| `app/models/remote_view.py` | Modelo SQLAlchemy `RemoteViewSession` |
| `app/api/v1/websocket/workstation.py` | Relay de frames WS→Admin |
| `app/api/v1/websocket/operator.py` | Relay de input Admin→WS |

#### Frontend (Next.js/TypeScript)

| Archivo | Responsabilidad |
|---------|-----------------|
| `src/app/dashboard/remote-view/page.tsx` | Página con tabs de sesiones |
| `src/components/remote-view/ScreenshotViewer.tsx` | Visor JPEG + refresh |
| `src/components/remote-view/StreamViewer.tsx` | Decodificador H.264/MSE |
| `src/components/remote-view/InteractiveViewer.tsx` | Stream + input capture |
| `src/components/remote-view/SessionHeader.tsx` | Controles de sesión |
| `src/components/remote-view/ConsentPending.tsx` | Estado de consentimiento |

#### Cliente C# (Tray)

| Clase | Responsabilidad |
|-------|-----------------|
| `RemoteViewSession.cs` | Estado de sesión, timeout, consent |
| `ScreenCapturer.cs` | Captura pantalla (GDI+ o Desktop Duplication) |
| `JpegEncoder.cs` | Comprime a JPEG con quality/resolution config |
| `H264Encoder.cs` | Encodea con Media Foundation (Fase 2) |
| `InputInjector.cs` | Inyecta mouse/teclado con SendInput (Fase 3) |
| `ClipboardBridge.cs` | Sync clipboard bidireccional (Fase 3) |
| `MonitorEnumerator.cs` | Lista monitores disponibles |

### Protocolo de Mensajes

#### Señalización

```json
// Admin → Backend → WS: iniciar sesión
{"type": "remote_view_start", "session_id": "uuid", "mode": "stream", "resolution": "720p", "monitor": 0, "user_name": "Admin"}

// WS → Backend → Admin: aceptado (con info de monitores)
{"type": "remote_view_accepted", "session_id": "uuid", "monitors": [{"name": "Principal", "width": 1920, "height": 1080}, ...]}

// WS → Backend → Admin: rechazado
{"type": "remote_view_rejected", "session_id": "uuid", "reason": "user_declined"}

// Cambio de config en vivo
{"type": "remote_view_config", "session_id": "uuid", "resolution": "480p", "monitor": 1, "fps": 3}

// Fin de sesión
{"type": "remote_view_stop", "session_id": "uuid", "reason": "admin_closed"}
```

#### Datos (frame relay)

```json
// Screenshot mode
{"type": "rv_frame", "session_id": "uuid", "format": "jpeg", "data": "base64...", "width": 1280, "height": 720}

// Stream mode (binary WebSocket frame, no JSON wrapper para performance)
// Header: 4 bytes session_id_hash + 1 byte flags (keyframe, monitor_idx) + payload H.264 NAL

// Input (Interactive mode)
{"type": "rv_input", "session_id": "uuid", "event": "mousemove", "x": 500, "y": 300}
{"type": "rv_input", "session_id": "uuid", "event": "click", "button": "left", "x": 500, "y": 300}
{"type": "rv_input", "session_id": "uuid", "event": "keydown", "key": "a", "modifiers": ["ctrl"]}
{"type": "rv_clipboard", "session_id": "uuid", "direction": "to_ws", "text": "..."}
```

### Modelo de Datos

```sql
CREATE TABLE remote_view_sessions (
    id UUID PRIMARY KEY,
    workstation_id UUID NOT NULL REFERENCES workstations(id),
    user_id UUID NOT NULL REFERENCES users(id),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    mode VARCHAR(20) NOT NULL, -- screenshot, stream, interactive
    status VARCHAR(20) NOT NULL, -- pending_consent, active, expired, rejected, closed
    started_at TIMESTAMP NOT NULL,
    ended_at TIMESTAMP,
    last_activity_at TIMESTAMP NOT NULL,
    monitor_index INT DEFAULT 0,
    resolution VARCHAR(10) DEFAULT 'auto',
    end_reason VARCHAR(30) -- timeout, admin_closed, ws_disconnected, user_rejected
);

CREATE INDEX ix_rv_sessions_ws ON remote_view_sessions(workstation_id, status);
CREATE INDEX ix_rv_sessions_user ON remote_view_sessions(user_id, status);
```

### Performance

| Modo | FPS | Resolución | Bandwidth |
|------|-----|-----------|-----------|
| Screenshot | on-demand | 720p | ~50-100 KB per frame |
| Stream JPEG | 3 | 720p | ~150-300 KB/s |
| Stream H.264 | 5 | 720p | ~200-500 KB/s |
| Interactive | 5 | 720p | ~200-500 KB/s + input ~1 KB/s |

CPU en workstation monitoreada: 5-10% (captura + encode).

### Seguridad

- Frames solo en memoria (relay), nunca persisted
- Tenant isolation en todas las queries
- JWT validation en cada request
- Indicador visual no-hideable en Tray
- Audit trail inmutable
