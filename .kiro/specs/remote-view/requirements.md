# Requirements Document: Remote View

## Introduction

Sistema de visualización y control remoto de workstations desde el dashboard AlwaysPrint. Permite a administradores y operadores ver la pantalla de una workstation en tiempo real, con opción de control remoto (mouse, teclado, clipboard). Todos los modos operan sobre WebSocket TCP existente — compatible con proxies corporativos restrictivos sin infraestructura adicional.

Referencia completa: #[[file:AlwaysPrintProject/Cloud/REMOTE_VIEW_SPEC.md]]

## Glossary

- **Remote View Session**: Conexión activa entre un admin/operador y una workstation para visualizar su pantalla.
- **Screenshot Mode**: Captura JPEG bajo demanda enviada por WebSocket.
- **Stream Mode**: Flujo continuo de frames H.264 codificados, decodificados en frontend con MSE.
- **Interactive Mode**: Stream + captura de input (mouse, teclado, clipboard) enviados a la workstation.
- **User Consent**: Popup que aparece en la workstation solicitando aprobación del usuario para la sesión.
- **Session Exclusivity**: Solo un admin/operador puede conectarse a una workstation a la vez.
- **MSE (Media Source Extensions)**: API del browser para decodificar H.264 fragments en un `<video>` element.
- **Desktop Duplication API**: API de Windows para captura de pantalla eficiente (hardware accelerated).
- **VNC/RFB**: Protocolo Remote Frame Buffer para envío de pantalla + recepción de input.

## Requirements

### Requirement 1: Configuración por Organización

**User Story:** Como administrador, quiero configurar las capacidades de vista remota por organización, para controlar qué modos están disponibles según la infraestructura y políticas del cliente.

#### Acceptance Criteria

1. THE Organization model SHALL include a `remote_view` JSON field with configuration for the feature
2. THE configuration SHALL include: `enabled` (bool), `modes_allowed` (array of "screenshot"|"stream"|"interactive"), `default_mode` (string), `remote_control_enabled` (bool), `clipboard_sharing_enabled` (bool), `require_user_consent` (bool), `max_concurrent_sessions` (int, 0=unlimited), `session_timeout_minutes` (int), `stream_default_quality` (string: "auto"|"720p"|"480p"|"360p"), `stream_max_fps` (int)
3. THE frontend Organization settings page SHALL provide UI to configure all remote_view fields
4. WHEN `enabled` is false, THE "Ver Pantalla" button SHALL NOT appear in workstation actions

### Requirement 2: Inicio de Sesión de Vista Remota

**User Story:** Como admin/operador, quiero iniciar una sesión de vista remota desde el botón "Ojo" (Ver Detalles) de una workstation, para ver su pantalla.

#### Acceptance Criteria

1. THE workstation detail view SHALL include a "Ver Pantalla" button when remote_view is enabled and the WS is online
2. WHEN clicking "Ver Pantalla", THE system SHALL verify no other session exists for that workstation
3. IF another session exists, THE system SHALL show "Esta workstation está siendo monitoreada por [nombre_usuario]" and prevent connection
4. IF no session exists, THE system SHALL open a new tab in `/dashboard/remote-view` with the session
5. THE user SHALL NOT be able to open two tabs to the same workstation
6. Admin and Operator roles SHALL both have access (Operator limited to their organization's workstations)

### Requirement 3: Consentimiento del Usuario

**User Story:** Como usuario de la workstation, quiero poder aceptar o rechazar una solicitud de monitoreo, para mantener mi privacidad cuando la política de la organización lo requiere.

#### Acceptance Criteria

1. WHEN `require_user_consent` is true AND a session is initiated, THE Tray SHALL show a consent popup to the workstation user
2. THE popup SHALL display the name of the admin/operator requesting access
3. THE user SHALL have options to "Permitir" or "Rechazar"
4. IF no response within 30 seconds, THE system SHALL auto-reject
5. IF the user rejects, THE admin SHALL see "El usuario rechazó la conexión" with a "Reintentar" button
6. WHEN `require_user_consent` is false, THE session SHALL start immediately without popup
7. WHILE a session is active, THE Tray SHALL show a visual indicator that the screen is being monitored (mandatory regardless of consent setting)

### Requirement 4: Screenshot Mode

**User Story:** Como admin/operador, quiero capturar screenshots de una workstation bajo demanda, para diagnosticar problemas visuales sin consumo continuo de bandwidth.

#### Acceptance Criteria

1. IN Screenshot mode, THE Tray SHALL capture the screen using `Graphics.CopyFromScreen()` when requested
2. THE capture SHALL be encoded as JPEG with configurable quality (default 70%)
3. THE image SHALL be sent as base64 via the existing WebSocket connection
4. THE frontend SHALL display the image in the session tab with a "Refresh" button
5. AN optional auto-refresh toggle SHALL allow automatic capture every 2 seconds
6. THE resolution SHALL match the selected quality setting (auto/720p/480p/360p) via scaling before encode

### Requirement 5: Stream Mode (H.264 over WebSocket)

**User Story:** Como admin/operador, quiero ver la pantalla de una workstation en tiempo real con video fluido, para supervisar actividad de forma continua.

#### Acceptance Criteria

1. IN Stream mode, THE Tray SHALL capture frames using Desktop Duplication API (or GDI+ fallback)
2. THE frames SHALL be encoded to H.264 using Media Foundation (hardware acceleration when available)
3. THE encoded NAL units SHALL be sent via WebSocket as binary frames
4. THE frontend SHALL decode and render using Media Source Extensions (MSE) in a `<video>` element
5. A keyframe SHALL be sent every 2 seconds to allow late-joiners to start rendering
6. THE FPS SHALL be configurable (1-5 FPS, default from org config `stream_max_fps`)
7. THE resolution SHALL be changeable in real-time without restarting the session
8. THE admin SHALL be able to switch between monitors in real-time

### Requirement 6: Interactive Mode (Control Remoto)

**User Story:** Como admin/operador de soporte L2/L3, quiero controlar remotamente una workstation (mouse, teclado, clipboard) para resolver problemas directamente.

#### Acceptance Criteria

1. WHEN `remote_control_enabled` is true AND mode is "interactive", THE frontend SHALL capture mouse and keyboard events on the session canvas
2. Mouse events (move, click, scroll) SHALL be sent to the workstation and injected using Windows `SendInput()` API
3. Keyboard events SHALL be sent and injected, including modifier keys (Ctrl, Alt, Shift, Win)
4. A "Ctrl+Alt+Del" button SHALL be available in the toolbar (cannot be captured by browser)
5. WHEN `clipboard_sharing_enabled` is true, clipboard content SHALL sync bidirectionally between admin browser and workstation
6. THE Tray SHALL indicate visually when remote control is active (distinct from view-only indicator)

### Requirement 7: Gestión de Sesiones

**User Story:** Como sistema, quiero gestionar las sesiones activas con timeouts y limpieza automática, para prevenir sesiones huérfanas y uso de recursos innecesario.

#### Acceptance Criteria

1. THE session SHALL timeout after `session_timeout_minutes` of admin inactivity (no clicks, no interaction with the tab)
2. 60 seconds before timeout, THE system SHALL show a warning "La sesión se cerrará por inactividad en 60s"
3. WHEN timeout occurs, THE session SHALL close and the tab SHALL show "Sesión expirada"
4. WHEN the admin closes the tab or navigates away, THE session SHALL terminate immediately
5. THE system SHALL enforce `max_concurrent_sessions` per admin/operator (reject new sessions if at limit)
6. IF the workstation goes offline during a session, THE session SHALL show "Workstation desconectada" and auto-close after 30s

### Requirement 8: Monitor Selection

**User Story:** Como admin/operador, quiero seleccionar qué monitor de la workstation estoy viendo, cuando la workstation tiene múltiples monitores.

#### Acceptance Criteria

1. WHEN a session starts, THE workstation SHALL report available monitors (name, resolution, position)
2. THE session header SHALL include a monitor dropdown selector
3. WHEN the admin changes the selected monitor, THE stream SHALL switch to that monitor within 1 second
4. THE default SHALL be the primary monitor

### Requirement 9: UI de Sesión (Frontend)

**User Story:** Como admin/operador, quiero una interfaz limpia con tabs para múltiples sesiones y controles accesibles.

#### Acceptance Criteria

1. Remote view sessions SHALL open in a dedicated page `/dashboard/remote-view`
2. Multiple sessions SHALL appear as tabs at the top of the page
3. Each tab SHALL show the workstation IP + hostname
4. THE active tab SHALL receive frames; inactive tabs SHALL pause streaming (save bandwidth)
5. THE session header SHALL display: IP, hostname, monitor selector, resolution selector, mode selector, session timer, close button
6. THE resolution selector SHALL allow real-time changes: Auto, 720p, 480p, 360p
7. THE mode selector SHALL allow switching between allowed modes without restarting the session

### Requirement 10: Audit Trail

**User Story:** Como administrador de seguridad, quiero un registro de quién vio qué workstation y cuándo, para cumplir con políticas de auditoría.

#### Acceptance Criteria

1. WHEN a session starts, THE system SHALL log: user_id, workstation_id, mode, timestamp
2. WHEN a session ends, THE system SHALL log: duration, end_reason (timeout/closed/disconnected/rejected)
3. THE audit_log entries SHALL use action_types: REMOTE_VIEW_START, REMOTE_VIEW_STOP
4. THE audit trail SHALL be queryable from the existing Audit page in the dashboard

### Requirement 11: Seguridad

**User Story:** Como responsable de seguridad, quiero garantizar que el monitoreo remoto se use de forma controlada y auditable.

#### Acceptance Criteria

1. ONLY authenticated admin/operator users SHALL be able to initiate sessions
2. Operator users SHALL only access workstations of their own organization (tenant isolation)
3. Sessions SHALL be invalidated when the admin/operator's JWT expires or they logout
4. Frames SHALL NOT be persisted to disk or database (relay in memory only)
5. THE visual indicator on the monitored workstation SHALL NOT be hideable by the admin
6. Clipboard sharing SHALL be opt-in per organization (disabled by default)
