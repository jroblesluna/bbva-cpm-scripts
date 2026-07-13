# Implementation Plan: Remote View

## Overview

Implementación incremental en 4 fases. Cada fase es funcional de forma independiente. Fase 1 (Screenshot) es el MVP mínimo, las fases 2-4 agregan capacidades progresivamente.

## Tasks

- [ ] 1. Infraestructura base (modelo, config, endpoints)
  - [ ] 1.1 Agregar campo `remote_view` (JSONB) al modelo Organization
    - Migración Alembic para agregar columna con default `{"enabled": false}`
    - Schema Pydantic para validación del JSON
    - _Requirements: 1.1, 1.2_

  - [ ] 1.2 Crear modelo SQLAlchemy RemoteViewSession
    - Tabla `remote_view_sessions` con campos del diseño
    - Índices para workstation_id+status y user_id+status
    - Migración Alembic
    - _Requirements: 7.1, 10.1_

  - [ ] 1.3 Crear SessionManager service
    - `start_session()`: verifica exclusividad, crea registro, retorna session_id
    - `end_session()`: actualiza status, end_reason, ended_at
    - `get_active_session()`: busca sesión activa por workstation_id
    - `check_timeout()`: verifica last_activity_at vs timeout config
    - `cleanup_expired()`: task periódico para limpiar sesiones expiradas
    - _Requirements: 2.2, 2.3, 7.1, 7.4, 7.5_

  - [ ] 1.4 Crear endpoints REST para remote view
    - POST `/workstations/{id}/remote-view/start` — inicia sesión
    - POST `/workstations/{id}/remote-view/stop` — termina sesión
    - GET `/workstations/{id}/remote-view/status` — estado actual
    - Validaciones: online, permisos, exclusividad, org config
    - _Requirements: 2.1, 2.2, 2.3, 2.5, 2.6, 11.1, 11.2_

  - [ ] 1.5 Agregar configuración de Remote View en frontend (Org settings)
    - Sección en la página de edición de organización
    - Toggles para enabled, modes, consent, control, clipboard
    - Inputs numéricos para max_sessions, timeout, fps
    - _Requirements: 1.3, 1.4_

- [ ] 2. Fase 1: Screenshot Mode
  - [ ] 2.1 Implementar ScreenCapturer en C# (Tray)
    - `CaptureScreen(int monitorIndex, int quality, string resolution)` → byte[] JPEG
    - Usar `Graphics.CopyFromScreen()` con scaling a resolución target
    - Enumerar monitores con `Screen.AllScreens`
    - _Requirements: 4.1, 4.2, 4.6, 8.1_

  - [ ] 2.2 Implementar handler de remote_view_start en CloudManager
    - Recibir comando WebSocket `remote_view_start`
    - Si consent requerido: mostrar popup, esperar respuesta (30s timeout)
    - Si acepta: enviar `remote_view_accepted` con lista de monitores
    - Si rechaza: enviar `remote_view_rejected`
    - Almacenar sesión activa en memoria del Tray
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

  - [ ] 2.3 Implementar captura bajo demanda
    - Handler de `rv_request_frame` → captura screenshot → envía `rv_frame`
    - Mostrar indicador visual de "siendo monitoreado" en Tray
    - Handler de `remote_view_stop` → limpiar sesión
    - _Requirements: 4.3, 4.4, 3.7_

  - [ ] 2.4 Implementar relay en backend (WebSocket)
    - Rutear `rv_frame` de WS worker → operador WS session
    - Rutear `rv_request_frame` de operador → WS worker
    - Usar session_id para mapear admin↔workstation
    - _Requirements: 4.3_

  - [ ] 2.5 Implementar ScreenshotViewer en frontend
    - Componente que muestra imagen JPEG base64
    - Botón "Refresh" para solicitar nuevo frame
    - Toggle "Auto-refresh" (cada 2s)
    - _Requirements: 4.4, 4.5_

  - [ ] 2.6 Crear página /dashboard/remote-view con tabs
    - Layout de tabs horizontales
    - SessionHeader con controles (monitor, resolution, mode, timer, close)
    - Integración con ScreenshotViewer
    - Lógica de timeout (warning 60s antes)
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 7.2, 7.3_

  - [ ] 2.7 Agregar botón "Ver Pantalla" en workstation detail
    - Dentro del ícono Ojo (Ver Detalles)
    - Solo visible si remote_view.enabled y WS online
    - Navega a /dashboard/remote-view con parámetros
    - Verificar exclusividad antes de navegar
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [ ] 2.8 Implementar audit trail
    - Log REMOTE_VIEW_START y REMOTE_VIEW_STOP en audit_log
    - Incluir mode, duration, end_reason, consent_given
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

- [ ] 3. Fase 2: Stream Mode (H.264/WebSocket)
  - [ ] 3.1 Implementar captura continua con Desktop Duplication API
    - Clase `DesktopDuplicator` que captura frames delta-only
    - Fallback a GDI+ si Desktop Duplication no disponible
    - Loop de captura con FPS configurable (1-5)
    - _Requirements: 5.1_

  - [ ] 3.2 Implementar H264Encoder con Media Foundation
    - Encoder hardware-accelerated (GPU) con fallback a software
    - Output: NAL units raw (sin container MP4)
    - Keyframe forzado cada 2 segundos
    - Resolución dinámica (cambiable sin reiniciar encoder)
    - _Requirements: 5.2, 5.3, 5.5, 5.7_

  - [ ] 3.3 Implementar envío continuo de frames por WebSocket
    - Enviar NAL units como binary WebSocket frames
    - Header compacto: session_hash(4B) + flags(1B) + payload
    - Throttle basado en FPS config
    - Detectar backpressure (si el WS buffer crece, bajar calidad)
    - _Requirements: 5.3, 5.6_

  - [ ] 3.4 Implementar StreamViewer en frontend con MSE
    - Crear MediaSource + SourceBuffer para H.264
    - Append NAL units al SourceBuffer
    - Manejar buffering, seek-to-live, buffer overflow
    - Mostrar en `<video>` element sin controles nativos
    - _Requirements: 5.4_

  - [ ] 3.5 Implementar cambio de monitor y resolución en vivo
    - Enviar `remote_view_config` al cambiar dropdown
    - Tray reconfigura encoder sin detener sesión
    - Frontend maneja codec change con nuevo keyframe
    - _Requirements: 5.7, 5.8, 8.2, 8.3_

- [ ] 4. Fase 3: Interactive Mode (Control Remoto)
  - [ ] 4.1 Implementar InputInjector en C# (Tray)
    - `InjectMouseMove(x, y)`, `InjectClick(button, x, y)`, `InjectScroll(delta)`
    - `InjectKeyDown(vkey, modifiers)`, `InjectKeyUp(vkey)`
    - Usar Windows `SendInput()` API
    - Mapeo de coordenadas escaladas (resolución real vs resolución del stream)
    - _Requirements: 6.1, 6.2, 6.3_

  - [ ] 4.2 Implementar captura de input en frontend
    - Capturar mouse events en canvas/video (move, click, scroll)
    - Capturar keyboard events (keydown, keyup) cuando canvas tiene focus
    - Enviar como `rv_input` messages por WebSocket
    - Botón "Ctrl+Alt+Del" en toolbar
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

  - [ ] 4.3 Implementar ClipboardBridge
    - Tray monitorea clipboard con `AddClipboardFormatListener`
    - Al cambiar: envía `rv_clipboard` al admin
    - Al recibir clipboard del admin: `Clipboard.SetText()`
    - Solo activo si `clipboard_sharing_enabled`
    - _Requirements: 6.5_

  - [ ] 4.4 Indicador visual de control remoto
    - Badge distinto en Tray cuando Interactive está activo (vs view-only)
    - Texto "Control remoto activo" en tooltip
    - _Requirements: 6.6_

- [ ] 5. Fase 4: Pulido y configuración
  - [ ] 5.1 Implementar pausa de tabs inactivos
    - Tab no-activo envía `rv_pause` → Tray deja de capturar
    - Tab re-activado envía `rv_resume` → Tray reanuda
    - _Requirements: 9.4_

  - [ ] 5.2 Implementar mode switching sin reiniciar sesión
    - Dropdown de modo en SessionHeader
    - Enviar `remote_view_config` con nuevo mode
    - Tray cambia de JPEG a H.264 o activa/desactiva input
    - _Requirements: 9.7_

  - [ ] 5.3 Implementar detección de WS offline durante sesión
    - Backend detecta disconnect del WebSocket de la workstation
    - Envía "Workstation desconectada" al admin
    - Auto-close después de 30s si no reconecta
    - _Requirements: 7.6_

  - [ ] 5.4 Textos i18n para toda la feature
    - Namespace `remoteView` en messages/es.json y messages/en.json
    - Todos los labels, tooltips, mensajes de error, confirmaciones
    - _Requirements: todos (UI)_

  - [ ] 5.5 Tests de integración
    - Test: inicio/fin de sesión con exclusividad
    - Test: timeout por inactividad
    - Test: consentimiento accept/reject/timeout
    - Test: tenant isolation (operador no accede a otra org)
    - _Requirements: 2.2, 7.1, 3.4, 11.2_
