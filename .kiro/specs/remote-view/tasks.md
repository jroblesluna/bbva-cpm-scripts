# Implementation Plan: Remote View

## Overview

Implementación incremental en 5 bloques. Cada fase es funcional de forma independiente. El bloque 1 establece infraestructura base. Las fases 2-4 implementan los 3 modos progresivamente. La fase 5 pule la experiencia y agrega tests.

## Tasks

- [x] 1. Infraestructura base (modelo, config, sesiones, endpoints)
  - [x] 1.1 Agregar campo `remote_view` (JSONB) al modelo Organization
    - Migración Alembic: columna `remote_view` JSONB con default `{"enabled": false}`
    - Schema Pydantic `RemoteViewConfig` con los 13 campos y validación de rangos
    - Endpoint PATCH de org actualiza el campo
    - _Requirements: 1.1, 1.2, 12.7_

  - [x] 1.2 Crear modelo SQLAlchemy RemoteViewSession
    - Tabla `remote_view_sessions` con todos los campos del design (id, workstation_id, user_id, organization_id, mode, status, started_at, ended_at, last_activity_at, monitor_index, resolution, end_reason, consent_given)
    - Índices parciales: `ix_rv_sessions_ws_status` (WHERE status IN pending_consent, active), `ix_rv_sessions_user_status` (WHERE status = active)
    - Migración Alembic
    - _Requirements: 7.1, 10.1, 11.1_

  - [x] 1.3 Crear SessionManager service
    - `create_session(workstation_id, user_id, org_id, mode)` → session_id o error (exclusividad)
    - `end_session(session_id, end_reason)` → actualiza status, ended_at
    - `get_active_for_workstation(workstation_id)` → sesión activa o None (para exclusividad y visibilidad)
    - `get_active_for_user(user_id)` → lista de sesiones activas (para límite concurrente)
    - `update_activity(session_id)` → actualiza last_activity_at
    - `update_mode(session_id, new_mode)` → actualiza mode
    - `cleanup_expired()` → busca sesiones expiradas por timeout y consent timeout, cierra
    - _Requirements: 2.2, 2.3, 2.6, 2.9, 7.1, 7.4, 7.5, 7.6, 10.1_

  - [x] 1.4 Crear endpoints REST para remote view
    - POST `/workstations/{id}/remote-view/start` — verifica permisos, org config enabled, WS online, exclusividad, límite sesiones → crea sesión → envía remote_view_start via WS
    - POST `/workstations/{id}/remote-view/stop` — valida ownership de sesión → envía remote_view_stop → end_session
    - GET `/workstations/{id}/remote-view/status` — retorna {active, user_name, user_email, started_at, mode} o {active: false}
    - _Requirements: 2.1, 2.2, 2.3, 2.7, 2.8, 2.9, 10.1, 10.2, 12.1, 12.2_

  - [x] 1.5 Implementar cleanup periódico
    - APScheduler job cada 60s que llama `SessionManager.cleanup_expired()`
    - Cierra sesiones active con `last_activity_at < NOW() - timeout`
    - Cierra sesiones pending_consent con `started_at < NOW() - 35s`
    - Envía remote_view_stop a WS afectadas
    - _Requirements: 7.1, 7.4_

  - [x] 1.6 Implementar audit trail para remote view
    - AuditService.log_action con REMOTE_VIEW_START al crear sesión activa
    - AuditService.log_action con REMOTE_VIEW_STOP al cerrar sesión
    - AuditService.log_action con REMOTE_VIEW_MODE_CHANGE al cambiar modo
    - Incluir campos: mode, consent_given, duration_seconds, end_reason, old_mode, new_mode
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

  - [x] 1.7 Agregar configuración de Remote View en frontend (Org settings)
    - Sección colapsable "Vista Remota" en la página de edición de organización
    - Toggle master `enabled`
    - Multi-select `modes_allowed`
    - Toggles: `remote_control_enabled`, `clipboard_sharing_enabled`, `require_user_consent`, `viewport_adaptive_downscale`
    - Inputs numéricos: `max_concurrent_sessions`, `session_timeout_minutes`, `stream_max_fps`, `compression_quality`
    - Select: `quality_mode` (auto/manual), `default_mode`, `capture_resolution`
    - Condicional: ocultar `capture_resolution` y `compression_quality` cuando `quality_mode=auto`
    - _Requirements: 1.3, 1.4, 1.5, 1.6_

- [x] 2. Fase 1: Screenshot Mode (MVP)
  - [x] 2.1 Implementar RemoteViewSession en C# (Tray)
    - Clase que gestiona estado de una sesión activa en el Tray
    - Handler de `remote_view_start` recibido por WebSocket
    - Almacena session_id, mode, resolution, quality, monitor, viewport
    - Handler de `remote_view_stop` → limpia estado, quita indicador
    - Handler de `remote_view_config` → actualiza parámetros en vivo
    - Handler de `remote_view_pause` / `remote_view_resume`
    - _Requirements: 4.1, 5.8, 5.9, 5.10, 7.4, 9.4, 9.5_

  - [x] 2.2 Implementar ConsentPopup en C# (Tray)
    - WinForms dialog modal con nombre del admin, botones Permitir/Rechazar
    - Countdown visual de 30s ("Respuesta automática en Xs: Rechazar")
    - Si timeout → auto-reject → envía remote_view_rejected reason=user_timeout
    - Si Permitir → envía remote_view_accepted con lista de monitores
    - Si Rechazar → envía remote_view_rejected reason=user_declined
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

  - [x] 2.3 Implementar indicador visual de monitoreo en Tray
    - Icono overlay o cambio de icono del Tray cuando sesión activa
    - Tooltip diferente para view-only ("Pantalla monitoreada") vs interactive ("Control remoto activo")
    - NO ocultable por ningún medio
    - Se quita al recibir remote_view_stop o al perder conexión WS
    - _Requirements: 3.9, 6.8, 12.5_

  - [x] 2.4 Implementar ScreenCapturer + MonitorEnumerator
    - `MonitorEnumerator.GetMonitors()` → lista de {index, name, width, height, primary, x, y}
    - `ScreenCapturer.Capture(monitorIndex, targetWidth, targetHeight)` → Bitmap escalado
    - Usa `Graphics.CopyFromScreen()` con el bounds del monitor seleccionado
    - Escala al target resolution ANTES de retornar (Req 4.2)
    - _Requirements: 4.1, 4.2, 8.1, 8.4_

  - [x] 2.5 Implementar JpegEncoder
    - `Encode(Bitmap, quality)` → byte[] JPEG
    - Aplica viewport-adaptive downscale si viewport < capture resolution (Req 4.4)
    - Calidad configurable 1-100%
    - _Requirements: 4.3, 4.4_

  - [x] 2.6 Implementar handler de rv_request_frame
    - Recibe solicitud → ScreenCapturer.Capture → JpegEncoder.Encode → envía rv_frame (base64 JSON)
    - Incluye width, height en el mensaje para que frontend conozca dimensiones
    - _Requirements: 4.5_

  - [x] 2.7 Implementar relay en backend (WebSocket)
    - En websocket/operator.py: handler de `rv_request_frame` → relay a WS vía send_to_workstation
    - En websocket/workstation.py: handler de `rv_frame` → relay a admin vía Redis pub/sub canal dedicado
    - Registrar mapping session_id → {ws_worker_id, admin_worker_id} para cross-worker relay
    - _Requirements: 13.1, 13.5_

  - [x] 2.8 Crear página /dashboard/remote-view con tabs
    - Route `/dashboard/remote-view?session={id}&ws={workstation_id}`
    - Layout: tabs horizontales + contenido del tab activo
    - Cada tab label: "IP — Hostname"
    - Tab activo envía frames/input; tabs inactivos envían rv_pause
    - Al volver a un tab: rv_resume → esperar keyframe
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

  - [x] 2.9 Implementar SessionHeader
    - Connection indicator (● verde/rojo)
    - IP — Hostname
    - Monitor dropdown (oculto si solo 1 monitor)
    - Resolution/quality selector: Alta/Media/Baja/Mínima/Auto (o manual si org config)
    - Mode selector: solo modos en modes_allowed
    - Timer MM:SS (counting up desde started_at)
    - Botón cerrar (✕)
    - _Requirements: 9.6, 9.7, 9.8, 8.2, 8.5_

  - [x] 2.10 Implementar ScreenshotViewer
    - Componente que recibe base64 JPEG y muestra en `<img>` con object-fit: contain
    - Botón "Refresh" (envía rv_request_frame)
    - Toggle "Auto-refresh" (cada 2s dispara rv_request_frame)
    - _Requirements: 4.6, 4.7, 4.8_

  - [x] 2.11 Implementar ConsentPending component
    - Muestra "Esperando aprobación del usuario..." con spinner
    - Si recibe remote_view_rejected: muestra "El usuario rechazó" + botón "Reintentar"
    - Si recibe remote_view_accepted: transiciona a ScreenshotViewer/StreamViewer
    - _Requirements: 2.5, 3.6, 3.7_

  - [x] 2.12 Implementar TimeoutWarning overlay
    - Se muestra cuando faltan 60s para timeout
    - Mensaje: "La sesión se cerrará por inactividad en {X}s"
    - Botón "Mantener activa" (resets activity timer)
    - Si timeout alcanzado: muestra "Sesión expirada" permanentemente en el tab
    - _Requirements: 7.2, 7.3, 7.4_

  - [x] 2.13 Implementar auto-adjust RTT (quality_mode=auto)
    - Frontend mide RTT de cada frame (timestamp envío request → timestamp recepción frame)
    - Cada 5 frames: calcula avg RTT
    - Si avg > 2000ms → envía remote_view_config con nivel inferior
    - Si avg < 500ms → envía remote_view_config con nivel superior
    - 4 niveles: 1080p/80%, 720p/70%, 480p/60%, 360p/50%
    - _Requirements: 4.9_

  - [x] 2.14 Agregar botón "Ver Pantalla" en workstation detail
    - Dentro del modal del Ojo (Ver Detalles)
    - Solo visible si remote_view.enabled y WS online
    - Al click: GET /remote-view/status → si active muestra quién + desde cuándo → si no, POST /start → navega a /remote-view
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 10.1, 10.2_

  - [x] 2.15 Implementar detección de WS offline durante sesión
    - Backend detecta disconnect del WS de la workstation
    - Envía mensaje al admin "Workstation desconectada"
    - Timer 30s → si no reconecta → end_session(ws_disconnected)
    - _Requirements: 7.7_

  - [x] 2.16 Implementar invalidación de sesiones al logout/JWT expiry
    - En el logout handler: buscar sesiones activas del user → end_session(admin_logout) para cada una
    - En el WebSocket operator disconnect handler: misma lógica
    - _Requirements: 7.5, 12.3_

- [x] 3. Fase 2: Stream Mode (H.264/WebSocket)
  - [x] 3.1 Implementar captura con Desktop Duplication API
    - Clase `DesktopDuplicator` que usa DXGI Output Duplication
    - Fallback a `Graphics.CopyFromScreen()` si DDA no disponible (Windows 7, VM sin GPU)
    - Retorna frame como Bitmap o byte[] sin encode
    - _Requirements: 5.1_

  - [x] 3.2 Implementar H264Encoder con Media Foundation
    - Inicializa MFT H.264 encoder (hardware → software fallback)
    - H.264 Baseline Profile para máxima compatibilidad
    - Output: raw NAL units (sin MP4 container)
    - Forzar keyframe (IDR) cada 2 segundos
    - Resolución y bitrate cambiables en runtime sin recrear encoder
    - _Requirements: 5.2, 5.3, 5.5, 5.7, 5.10_

  - [x] 3.3 Implementar FrameStreamer (loop de captura continua)
    - Loop async: captura → encode → envía a FPS configurado
    - Throttle con timer preciso (no Task.Delay que driftea)
    - Respeta pause/resume (deja de capturar en pause)
    - Monitorea buffer de WebSocket para backpressure
    - _Requirements: 5.6, 9.4, 13.4_

  - [x] 3.4 Implementar backpressure en FrameStreamer
    - Monitorear pending bytes en el WebSocket send buffer
    - >1 MB: reducir FPS a la mitad + bajar calidad 1 nivel
    - <256 KB por 5 frames: restaurar configuración original
    - >3 MB: pausar captura 5 segundos
    - Log cada cambio de estado
    - _Requirements: 13.4_

  - [x] 3.5 Implementar envío binario de frames H.264
    - Construir header de 9 bytes: session_hash(4B) + flags(1B) + width(2B) + height(2B)
    - Enviar como binary WebSocket frame (no text/JSON)
    - _Requirements: 5.3_

  - [x] 3.6 Implementar StreamViewer en frontend con MSE
    - Crear MediaSource + SourceBuffer('video/mp4; codecs="avc1.42E01E"')
    - Parsear header de 9 bytes para identificar sesión y keyframe flag
    - Append NAL units al SourceBuffer (wrapped en MP4 fragment via mux.js o manual)
    - Manejar buffer overflow (remove old segments si buffered > 5s)
    - Mostrar en `<video autoplay muted>` sin controles nativos
    - _Requirements: 5.4_

  - [x] 3.7 Implementar cambio de monitor y resolución en vivo (Stream)
    - Enviar `remote_view_config` con nuevos parámetros
    - Tray: reconfigura DesktopDuplicator (nuevo monitor) + H264Encoder (nueva resolución)
    - Forzar keyframe inmediato después del cambio
    - Frontend: detecta cambio de resolución en header → reset SourceBuffer
    - _Requirements: 5.8, 5.9, 5.10, 8.3_

  - [x] 3.8 Implementar viewport-adaptive downscale para Stream
    - Frontend envía viewport_width/height al iniciar y al resize (1s debounce)
    - Tray: si viewport < capture_res → escala antes de encode
    - Nunca upscale
    - _Requirements: 5.8_

- [x] 4. Fase 3: Interactive Mode (Control Remoto)
  - [x] 4.1 Implementar InputInjector en C# (Tray)
    - `InjectMouseMove(normalizedX, normalizedY)` → convierte a coordenadas de monitor real
    - `InjectMouseDown/Up(button, x, y)` → SendInput con MOUSEEVENTF flags
    - `InjectWheel(delta)` → SendInput con MOUSEEVENTF_WHEEL
    - `InjectKeyDown/Up(virtualKey, modifiers)` → SendInput con KEYEVENTF flags
    - `InjectSAS()` → Ctrl+Alt+Del via `SendSAS()` API (requiere privilegios)
    - Mapeo: coordenadas normalizadas (0.0-1.0) × monitor_resolution = posición real
    - _Requirements: 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 4.2 Implementar handler de rv_input en Tray
    - Recibe mensajes rv_input del WebSocket
    - Parsea event type (mousemove, mousedown, mouseup, wheel, keydown, keyup, sas)
    - Delega a InputInjector con conversión de coordenadas
    - Solo activo si mode=interactive en la sesión actual
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

  - [x] 4.3 Implementar captura de input en frontend (InteractiveViewer)
    - Extiende StreamViewer con event listeners en el `<video>` element
    - onMouseMove/Down/Up/Wheel: normaliza coordenadas (offsetX/video.width) → envía rv_input
    - onKeyDown/Up (cuando video tiene focus): envía rv_input con code + modifiers
    - Botón "Ctrl+Alt+Del" en toolbar: envía rv_input event=sas
    - Cursor: muestra cursor personalizado sobre el video (indica que input está activo)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.6_

  - [x] 4.4 Implementar ClipboardBridge en Tray
    - Usa `AddClipboardFormatListener` para detectar cambios en clipboard local
    - Al detectar cambio: lee `Clipboard.GetText()` → envía rv_clipboard direction=to_admin
    - Al recibir rv_clipboard direction=to_ws: `Clipboard.SetText(text)`
    - Solo activo si clipboard_sharing_enabled=true en la sesión
    - _Requirements: 6.7_

  - [x] 4.5 Implementar clipboard sync en frontend
    - Al recibir rv_clipboard direction=to_admin: `navigator.clipboard.writeText(text)`
    - Botón "Pegar desde mi clipboard" → `navigator.clipboard.readText()` → envía rv_clipboard to_ws
    - Nota: Clipboard API del browser requiere user gesture para readText()
    - _Requirements: 6.7_

  - [x] 4.6 Implementar relay de rv_input y rv_clipboard en backend
    - operator.py: handler de rv_input → relay a WS (mismo patrón que rv_request_frame)
    - operator.py: handler de rv_clipboard direction=to_ws → relay a WS
    - workstation.py: handler de rv_clipboard direction=to_admin → relay a admin
    - _Requirements: 6.2, 6.7, 13.1_

- [x] 5. Fase 4: Pulido, visibilidad, i18n, tests
  - [x] 5.1 Implementar mode switching seamless
    - Dropdown de modo en SessionHeader envía remote_view_config con nuevo mode
    - Tray: cambia behavior sin recrear sesión (Screenshot→Stream: inicia loop; Stream→Interactive: activa InputInjector; Interactive→Stream: desactiva input; etc.)
    - Frontend: cambia viewer component (ScreenshotViewer ↔ StreamViewer ↔ InteractiveViewer)
    - Log audit REMOTE_VIEW_MODE_CHANGE
    - _Requirements: 9.9, 11.4, 3.11_

  - [x] 5.2 Implementar indicador de sesión activa en lista de workstations
    - GET /remote-view/status incluido en la query de workstations (o campo calculado)
    - Icono pequeño de "ojo" en la fila/card cuando hay sesión activa
    - Admin ve siempre; Operador solo su org
    - _Requirements: 10.3, 10.4_

  - [x] 5.3 Implementar visibilidad detallada de sesión activa
    - Al intentar conectar a WS con sesión activa: mostrar nombre completo + email + hora inicio
    - Formato: "Monitoreada por Javier Robles (antonio@robles.ai) desde las 15:30"
    - _Requirements: 10.1, 10.2_

  - [x] 5.4 Textos i18n para toda la feature
    - Namespace `remoteView` en messages/es.json y messages/en.json
    - Todos los labels, tooltips, mensajes de error, estados de sesión, confirmaciones
    - Namespace `orgSettings` extender con sección de remote_view
    - _Requirements: todos (UI)_

  - [x] 5.5 Tests de integración
    - Test: start session → verify exclusivity (second start returns 409)
    - Test: session timeout (simulate inactivity → verify status=expired)
    - Test: consent flow (accept, reject, timeout)
    - Test: max_concurrent_sessions enforcement
    - Test: tenant isolation (operator can't start on other org's WS)
    - Test: mode change logs audit entry
    - Test: WS disconnect → session closes after 30s
    - _Requirements: 2.2, 2.9, 3.4, 3.5, 7.1, 7.7, 11.4, 12.2_
