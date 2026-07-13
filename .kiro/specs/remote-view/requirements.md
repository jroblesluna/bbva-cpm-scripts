# Requirements Document: Remote View

## Introduction

Sistema de visualización y control remoto de workstations desde el dashboard AlwaysPrint. Permite a administradores y operadores ver la pantalla de una workstation en tiempo real, con opción de control remoto (mouse, teclado, clipboard). Todos los modos operan sobre WebSocket TCP existente — compatible con proxies corporativos restrictivos sin infraestructura adicional.

El sistema funciona sin restricciones tanto en modo normal como en modo contingencia de la workstation (la conexión WebSocket al Cloud se mantiene activa en ambos modos).

Referencia de diseño: #[[file:AlwaysPrintProject/Cloud/REMOTE_VIEW_SPEC.md]]

## Glossary

- **Remote View Session**: Conexión activa entre un admin/operador y una workstation para visualizar su pantalla. Solo una sesión por workstation a la vez.
- **Screenshot Mode**: Captura JPEG bajo demanda enviada por WebSocket. El admin solicita un frame, la WS lo envía.
- **Stream Mode**: Flujo continuo de frames H.264 codificados a 1-5 FPS, decodificados en frontend con MSE.
- **Interactive Mode**: Stream + captura y envío de input (mouse, teclado, clipboard) a la workstation para control remoto.
- **User Consent**: Popup que aparece en la workstation solicitando aprobación del usuario antes de iniciar la sesión.
- **Session Exclusivity**: Solo un admin/operador puede conectarse a una workstation a la vez. Otros ven quién la está monitoreando.
- **Resolución de Captura**: Tamaño en píxeles de la imagen capturada del monitor de la workstation (ej: 1920×1080, 1280×720).
- **Calidad de Compresión**: Porcentaje de calidad del encoder JPEG (1-100%) o bitrate del encoder H.264. Controla fidelidad vs tamaño.
- **Viewport-Adaptive Downscale**: Reducción automática de la resolución de captura para coincidir con el tamaño real del panel del browser del admin. Solo reduce, nunca amplía.
- **MSE (Media Source Extensions)**: API del browser para decodificar H.264 fragments en un `<video>` element sin plugins.
- **Desktop Duplication API**: API de Windows para captura de pantalla hardware-accelerated (disponible desde Windows 8+).
- **SendInput API**: API de Windows para inyectar eventos de mouse y teclado a nivel de sistema operativo.
- **Frame Relay**: El backend solo retransmite bytes entre la WS y el admin sin procesar/decodificar el contenido. Zero CPU de procesamiento de video.
- **Cross-Worker Relay**: Cuando el admin y la WS están en workers distintos del backend, los frames se rutean vía Redis pub/sub (misma infraestructura que `send_to_workstation`).

## Requirements

### Requirement 1: Configuración por Organización

**User Story:** Como administrador, quiero configurar las capacidades de vista remota por organización, para controlar qué modos están disponibles según la infraestructura y políticas del cliente.

#### Acceptance Criteria

1. THE Organization model SHALL include a `remote_view` JSON field with the complete configuration for the feature
2. THE configuration SHALL include all of the following fields:
   - `enabled` (bool, default: false) — habilita/deshabilita el feature completo
   - `modes_allowed` (string[], default: ["screenshot"]) — modos disponibles: "screenshot", "stream", "interactive"
   - `default_mode` (string, default: "screenshot") — modo inicial al conectar
   - `remote_control_enabled` (bool, default: false) — permitir mouse/teclado en Interactive mode
   - `clipboard_sharing_enabled` (bool, default: false) — compartir clipboard bidireccional
   - `require_user_consent` (bool, default: true) — mostrar popup de consentimiento al usuario
   - `max_concurrent_sessions` (int, default: 4) — máx sesiones simultáneas por admin/operador (0=ilimitado)
   - `session_timeout_minutes` (int, default: 5) — timeout por inactividad del admin
   - `quality_mode` (string, default: "auto") — "auto" o "manual"
   - `capture_resolution` (string, default: "1280x720") — resolución de captura cuando quality_mode="manual" (ej: "1920x1080", "1280x720", "854x480", "640x360")
   - `compression_quality` (int, default: 70) — porcentaje de calidad JPEG/bitrate cuando quality_mode="manual" (1-100)
   - `viewport_adaptive_downscale` (bool, default: true) — reducir resolución de envío al tamaño del viewport del admin
   - `stream_max_fps` (int, default: 5) — FPS máximo para Stream/Interactive mode (1-10)
3. THE frontend Organization settings page SHALL provide UI to configure all remote_view fields
4. WHEN `quality_mode` is "auto", THE system SHALL hide capture_resolution and compression_quality fields (uses auto-adjustment logic)
5. WHEN `quality_mode` is "manual", THE system SHALL show capture_resolution and compression_quality as editable fields
6. WHEN `enabled` is false, THE "Ver Pantalla" button SHALL NOT appear in workstation actions for that organization

### Requirement 2: Inicio de Sesión de Vista Remota

**User Story:** Como admin/operador, quiero iniciar una sesión de vista remota desde el detalle de una workstation, para ver su pantalla.

#### Acceptance Criteria

1. THE workstation detail view (modal del botón "Ojo") SHALL include a "Ver Pantalla" button ONLY when `remote_view.enabled = true` for the organization AND the workstation is online
2. WHEN clicking "Ver Pantalla", THE system SHALL verify no other active session exists for that workstation (query backend)
3. IF another session exists, THE system SHALL show "Esta workstation está siendo monitoreada por [nombre_completo_del_usuario]" and prevent connection
4. IF no session exists AND consent is not required, THE system SHALL open a new tab in `/dashboard/remote-view` with the session starting immediately
5. IF no session exists AND consent IS required, THE system SHALL open the tab showing "Esperando aprobación del usuario..." until the WS user responds
6. THE same admin/operator SHALL NOT be able to open two tabs to the same workstation
7. Admin AND Operator roles SHALL both have access to initiate sessions
8. Operator users SHALL only access workstations belonging to their own organization (tenant isolation)
9. WHEN `max_concurrent_sessions` is reached for the admin/operator, THE system SHALL reject new session with message "Límite de sesiones simultáneas alcanzado ({N}/{max})"

### Requirement 3: Consentimiento del Usuario

**User Story:** Como usuario de la workstation, quiero poder aceptar o rechazar una solicitud de monitoreo, para mantener mi privacidad cuando la política de la organización lo requiere.

#### Acceptance Criteria

1. WHEN `require_user_consent` is true AND a session is initiated, THE Tray SHALL show a consent popup to the workstation user within 2 seconds of receiving the request
2. THE popup SHALL display the full name of the admin/operator requesting access (not just username)
3. THE popup SHALL have exactly two buttons: "Permitir" and "Rechazar"
4. THE popup SHALL display a countdown: "Respuesta automática en Xs: Rechazar" (starting at 30s)
5. IF no response within 30 seconds, THE system SHALL auto-reject and notify the admin
6. IF the user clicks "Rechazar", THE admin SHALL see "El usuario rechazó la conexión" with a "Reintentar" button
7. IF the user clicks "Permitir", THE session SHALL start immediately and the admin's tab transitions from "Esperando..." to showing frames
8. WHEN `require_user_consent` is false, THE session SHALL start immediately without any popup to the user
9. WHILE a session is active (regardless of consent setting), THE Tray SHALL show a persistent visual indicator (icon overlay or balloon) that the screen is being monitored — THIS INDICATOR SHALL NOT BE HIDEABLE by the admin or by configuration
10. THE consent decision (accepted/rejected/timed_out) SHALL be recorded in the audit trail
11. THE single consent at session start SHALL cover all mode changes within the same session (changing from Stream to Interactive does NOT require a second consent)

### Requirement 4: Screenshot Mode

**User Story:** Como admin/operador, quiero capturar screenshots de una workstation bajo demanda, para diagnosticar problemas visuales sin consumo continuo de bandwidth.

#### Acceptance Criteria

1. IN Screenshot mode, THE Tray SHALL capture the screen of the selected monitor using `Graphics.CopyFromScreen()` when a frame is requested by the admin
2. THE capture SHALL be scaled to the configured capture resolution BEFORE encoding (scaling reduces at source, not at frontend)
3. THE scaled image SHALL be encoded as JPEG with the configured compression quality percentage
4. WHEN `viewport_adaptive_downscale` is enabled AND the admin's viewport is smaller than the capture resolution, THE Tray SHALL further reduce the capture to match the viewport dimensions (never upscale — if viewport > capture, send at capture resolution)
5. THE JPEG data SHALL be sent as base64 encoded string via the existing WebSocket connection to the backend, which relays it to the admin
6. THE frontend SHALL display the received image scaled to fit the session panel (CSS object-fit: contain)
7. THE frontend SHALL provide a "Refresh" button to request a new frame manually
8. THE frontend SHALL provide an "Auto-refresh" toggle that, when active, requests a new frame every 2 seconds automatically
9. WHEN `quality_mode` is "auto", THE system SHALL start at 1280×720 / 70% quality and adjust based on frame RTT: if avg RTT of last 5 frames > 2000ms → reduce one level; if avg RTT < 500ms → increase one level. Levels: 1920×1080/80%, 1280×720/70%, 854×480/60%, 640×360/50%

### Requirement 5: Stream Mode (H.264 over WebSocket)

**User Story:** Como admin/operador, quiero ver la pantalla de una workstation en tiempo real con video fluido, para supervisar actividad de forma continua.

#### Acceptance Criteria

1. IN Stream mode, THE Tray SHALL capture frames continuously using Desktop Duplication API on Windows 8+ (fallback to `Graphics.CopyFromScreen()` if Desktop Duplication is unavailable)
2. THE frames SHALL be encoded to H.264 Baseline Profile using Windows Media Foundation (uses GPU hardware acceleration when available, falls back to software encoding)
3. THE encoded H.264 NAL units SHALL be sent via WebSocket as binary frames to the backend for relay
4. THE frontend SHALL decode and render H.264 using Media Source Extensions (MSE) API in a `<video>` element
5. A keyframe (IDR frame) SHALL be sent every 2 seconds to allow the frontend to start rendering even if it missed previous frames
6. THE FPS SHALL be limited to `stream_max_fps` from organization config (default 5, range 1-10)
7. THE capture resolution and quality SHALL follow the same rules as Screenshot mode (org config or auto-adjust)
8. WHEN `viewport_adaptive_downscale` is enabled, THE Tray SHALL adjust capture resolution when the admin resizes the browser (with 1 second debounce to avoid constant reconfiguration)
9. THE admin SHALL be able to switch between monitors in real-time by selecting from the monitor dropdown (Tray reconfigures capture source within 1 second)
10. THE admin SHALL be able to change resolution/quality preset in real-time without restarting the session (Tray reconfigures encoder parameters)

### Requirement 6: Interactive Mode (Control Remoto)

**User Story:** Como admin/operador de soporte L2/L3, quiero controlar remotamente una workstation (mouse, teclado, clipboard) para resolver problemas directamente.

#### Acceptance Criteria

1. Interactive mode SHALL only be available when BOTH `"interactive"` is in `modes_allowed` AND `remote_control_enabled` is true in the organization config
2. IN Interactive mode, THE frontend SHALL capture mouse events (move, click, double-click, right-click, scroll) on the video/canvas element and send them to the workstation via WebSocket
3. THE Tray SHALL inject received mouse events using Windows `SendInput()` API, translating coordinates from the stream resolution to the actual monitor resolution
4. IN Interactive mode, THE frontend SHALL capture keyboard events (keydown, keyup) when the video/canvas element has focus, including modifier keys (Ctrl, Alt, Shift, Win)
5. THE Tray SHALL inject keyboard events using `SendInput()` API with correct virtual key codes and modifier state
6. THE frontend toolbar SHALL include a "Ctrl+Alt+Del" button that sends the Secure Attention Sequence (since browsers cannot capture this key combination)
7. WHEN `clipboard_sharing_enabled` is true, THE system SHALL synchronize clipboard content bidirectionally:
   - Admin copies text → sent to workstation → `Clipboard.SetText()` on WS
   - WS user copies text → detected via `AddClipboardFormatListener` → sent to admin → available in browser clipboard API
8. THE Tray SHALL show a DISTINCT visual indicator when Interactive mode is active (different from view-only Stream indicator) — e.g., "Control remoto activo" vs "Pantalla siendo monitoreada"
9. Switching from Stream to Interactive mode within the same session SHALL NOT require a new consent popup (covered by Requirement 3, AC 11)

### Requirement 7: Gestión de Sesiones y Timeout

**User Story:** Como sistema, quiero gestionar las sesiones activas con timeouts, limpieza automática y detección de desconexiones, para prevenir sesiones huérfanas.

#### Acceptance Criteria

1. THE session SHALL timeout after `session_timeout_minutes` (default 5) of admin inactivity. Inactivity = no mouse interaction with the session canvas, no button clicks in session controls, no mode/resolution changes
2. THE inactivity timer SHALL reset on ANY interaction: click on canvas, keyboard input, button click in session header, resolution change, monitor change, mode change
3. 60 seconds before timeout, THE frontend SHALL show an overlay warning: "La sesión se cerrará por inactividad en 60s" with a "Mantener activa" button
4. WHEN timeout occurs, THE session SHALL close cleanly: notify WS to stop capturing, update DB status to "expired", show "Sesión expirada" in the tab
5. WHEN the admin closes the browser tab, navigates away from `/dashboard/remote-view`, or logs out, THE backend SHALL detect the WebSocket disconnection and immediately terminate all active sessions for that user
6. THE system SHALL enforce `max_concurrent_sessions` per admin/operator at session creation time (not per organization total — each admin has their own limit)
7. IF the workstation WebSocket disconnects during an active session, THE frontend SHALL show "Workstation desconectada" and auto-close the session after 30 seconds if the WS does not reconnect

### Requirement 8: Selección de Monitor

**User Story:** Como admin/operador, quiero seleccionar qué monitor de la workstation estoy viendo, cuando tiene múltiples pantallas.

#### Acceptance Criteria

1. WHEN a session is accepted by the workstation, THE Tray SHALL report all available monitors: display name (from Windows), native resolution, position (x,y), and which is the primary monitor
2. THE session header SHALL include a monitor dropdown selector populated with the reported monitors
3. WHEN the admin changes the selected monitor, THE Tray SHALL switch capture source to that monitor and send a new keyframe within 1 second
4. THE default selected monitor SHALL be the primary monitor (as reported by Windows `Screen.PrimaryScreen`)
5. IF the workstation has only 1 monitor, THE dropdown SHALL be hidden (not disabled — completely not shown)

### Requirement 9: UI de Sesión (Frontend)

**User Story:** Como admin/operador, quiero una interfaz limpia con tabs para múltiples sesiones y controles accesibles en todo momento.

#### Acceptance Criteria

1. Remote view sessions SHALL open in a dedicated page at route `/dashboard/remote-view`
2. Multiple active sessions SHALL appear as horizontal tabs at the top of the page
3. Each tab label SHALL show: workstation IP + hostname (e.g., "118.245.114.41 — W1084901P01")
4. THE active (selected) tab SHALL receive frames from the backend; inactive tabs SHALL send a pause signal to the WS (stop capturing) to save bandwidth and CPU
5. WHEN switching back to a paused tab, THE frontend SHALL send a resume signal and the WS SHALL send a keyframe within 1 second
6. THE session header bar (below tabs, above video) SHALL display: connection indicator (●), IP — hostname, monitor dropdown, resolution/quality selector, mode selector, session timer (MM:SS counting up), close (✕) button
7. THE resolution/quality selector SHALL offer: "Alta (1080p)", "Media (720p)", "Baja (480p)", "Mínima (360p)", "Auto" — OR if org config is manual, show the org's configured values
8. THE mode selector SHALL show only modes present in `modes_allowed` of the organization config
9. Switching mode from the selector SHALL NOT restart the session — the Tray seamlessly transitions (e.g., stops sending input events when leaving Interactive, or starts continuous capture when entering Stream from Screenshot)

### Requirement 10: Visibilidad de Sesiones Activas

**User Story:** Como admin/operador, quiero saber si una workstation ya está siendo monitoreada y por quién, para evitar conflictos y coordinar con el equipo.

#### Acceptance Criteria

1. WHEN another admin/operator has an active session on a workstation, ANY user attempting to connect SHALL see: "Esta workstation está siendo monitoreada por [Nombre Completo] ([email])"
2. THE message SHALL include a timestamp of when the session started: "Desde las HH:MM"
3. THE workstation list (table/card view) MAY show a visual indicator (e.g., small eye icon) when a remote view session is active on that WS
4. Admins SHALL see the monitoring user regardless of organization; Operators SHALL only see this information for workstations of their own organization

### Requirement 11: Audit Trail

**User Story:** Como administrador de seguridad, quiero un registro completo de quién vio qué workstation, cuándo, durante cuánto tiempo, y con qué capacidades.

#### Acceptance Criteria

1. WHEN a session starts, THE system SHALL create an audit_log entry with action_type=REMOTE_VIEW_START containing: user_id, workstation_id, organization_id, mode, consent_given (true/false/not_required), timestamp
2. WHEN a session ends, THE system SHALL create an audit_log entry with action_type=REMOTE_VIEW_STOP containing: user_id, workstation_id, session_duration_seconds, end_reason (one of: "timeout", "admin_closed", "ws_disconnected", "user_rejected", "admin_logout", "limit_reached")
3. THE audit entries SHALL be visible in the existing Audit page of the dashboard, filterable by action_type
4. IF mode changes occur during a session (e.g., Stream→Interactive), EACH change SHALL be logged as a separate audit entry with action_type=REMOTE_VIEW_MODE_CHANGE

### Requirement 12: Seguridad y Privacidad

**User Story:** Como responsable de seguridad, quiero garantizar que el monitoreo remoto sea controlado, auditable y respetuoso de la privacidad.

#### Acceptance Criteria

1. ONLY authenticated users with role admin or operator SHALL be able to initiate remote view sessions
2. Operator users SHALL only initiate sessions on workstations belonging to their own organization (enforced at backend, not just frontend)
3. ALL active sessions for a user SHALL be immediately terminated when their JWT token expires or they explicitly log out
4. Video frames SHALL NEVER be persisted to disk, database, or any storage — backend performs memory-only relay
5. THE visual monitoring indicator on the workstation Tray SHALL NOT be suppressible via configuration, API, or any mechanism — it is always visible to the workstation user when a session is active
6. Clipboard sharing SHALL be disabled by default (opt-in per organization) and SHALL only function when explicitly enabled in org config
7. THE remote view feature SHALL be disabled by default for all organizations (must be explicitly enabled)
8. ALL WebSocket frames containing video data SHALL be transmitted over TLS (wss://) — same security as existing WebSocket connections

### Requirement 13: Performance y Límites

**User Story:** Como administrador de infraestructura, quiero garantizar que el remote view no degrade el servicio principal de AlwaysPrint.

#### Acceptance Criteria

1. THE backend SHALL perform zero video processing — only byte relay between WebSockets (no decode, no transcode, no analysis)
2. THE backend SHALL support at least 30 concurrent remote view sessions without degrading WebSocket telemetry or HTTP API response times
3. THE Tray screen capture + encode SHALL consume no more than 10% CPU on the monitored workstation at the configured FPS and resolution
4. WHEN the WebSocket send buffer grows beyond 1 MB (backpressure detected), THE Tray SHALL automatically reduce quality/FPS until the buffer drains
5. Cross-worker frame relay (when admin and WS are on different uvicorn workers) SHALL use the existing Redis pub/sub infrastructure with dedicated channels per session (not broadcast)
