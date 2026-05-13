# Requirements Document

## Introduction

La **Fase 5 — Resiliencia Offline, Notificaciones y Modo Degradado** implementa la capacidad del AlwaysPrintTray de operar correctamente sin conexión a la nube, notificar al usuario de forma no invasiva sobre el estado de desconexión, gestionar la telemetría acumulada offline, y reconectarse de forma transparente. Sobre la infraestructura de Fase 4 (TelemetryReporter, ConnectivityMonitor, CloudManager con lifecycle), esta fase agrega: clase `OfflineStateManager` para gestionar estados de desconexión y notificaciones, cola de telemetría pendiente con límite de 100 entradas, manejo de modo sin configuración cacheada, cambio visual del icono del tray en modo offline, y balloon tips no invasivos con período de gracia de 1 hora y repetición cada 2 horas.

El mecanismo central es la máquina de estados del Tray respecto a la nube: CLOUD_DISABLED, CLOUD_CONNECTED, CLOUD_OFFLINE_GRACE, CLOUD_OFFLINE_NOTIFIED, y CLOUD_OFFLINE_NO_CONFIG. Las transiciones entre estados disparan acciones específicas (notificaciones, cambio de icono, flush de telemetría pendiente).

Al finalizar esta fase, `dotnet build AlwaysPrint.sln -c Release --nologo` debe producir 0 errores y 0 advertencias, y el comportamiento existente del Client con `CloudEnabled=0` no debe verse alterado.

## Glossary

- **AlwaysPrintService**: Servicio Windows (LocalSystem) que gestiona la cola de impresión corporativa y expone el Named Pipe. No accede a Internet.
- **AlwaysPrintTray**: Aplicación WinForms de bandeja del sistema que se ejecuta en el contexto del usuario. Es el único componente que accede a Internet y a HKCU.
- **APCM**: AlwaysPrint Cloud Manager — plataforma SaaS (FastAPI + Next.js) a la que el Tray se conecta vía WebSocket.
- **OfflineStateManager**: Nueva clase en `AlwaysPrintTray/Cloud/` que gestiona el estado offline del Tray, las notificaciones balloon tip, y el cambio de icono.
- **TelemetryReporter**: Clase existente (Fase 4) en `AlwaysPrintTray/Cloud/` que recopila y envía telemetría periódica. En Fase 5 se extiende con cola de telemetría pendiente.
- **CloudManager**: Clase existente (Fase 2-4) en `AlwaysPrintTray/Cloud/` que orquesta la integración Cloud. En Fase 5 se extiende con integración del OfflineStateManager.
- **CloudWebSocketClient**: Clase existente (Fase 2) en `AlwaysPrintTray/Cloud/` que mantiene la conexión WSS persistente hacia APCM.
- **ConfigurationSync**: Clase existente (Fase 3) que gestiona la descarga y aplicación de configuración desde APCM.
- **Balloon Tip**: Notificación nativa de Windows que aparece brevemente sobre el icono del system tray. No invasiva, no modal.
- **Grace Period**: Período de 1 hora después de la desconexión durante el cual no se muestra ninguna notificación al usuario.
- **NotifyIcon**: Componente WinForms que representa el icono en el system tray y permite mostrar balloon tips.
- **SynchronizationContext**: Mecanismo de .NET para despachar trabajo al hilo de UI desde hilos de fondo.
- **TelemetryPayload**: Objeto que contiene los datos de telemetría ensamblados para un ciclo (queue_status, contingency_active, jobs_identified, avg_release_time_ms, disconnection_log).
- **LocalizationManager**: Clase que gestiona el idioma activo de la interfaz del Tray. Provee strings localizados vía `Get(key)`.
- **AlwaysPrintLogger**: Clase de logging centralizada. Todos los logs deben pasar por ella con mensajes en español.

---

## Requirements

### Requirement 1: OfflineStateManager — Gestión de estado offline

**User Story:** Como usuario de AlwaysPrint, quiero que el sistema gestione internamente los estados de desconexión de la nube, para que las notificaciones y el comportamiento visual se ajusten automáticamente según la duración de la desconexión.

#### Acceptance Criteria

1. THE `OfflineStateManager` SHALL be a new `sealed` class in `AlwaysPrintTray/Cloud/OfflineStateManager.cs` within the namespace `AlwaysPrintTray.Cloud`.
2. THE `OfflineStateManager` SHALL accept the following dependencies in its constructor: `SynchronizationContext uiContext` and `NotifyIcon trayIcon`.
3. WHEN `OnDisconnected()` is called, THE `OfflineStateManager` SHALL record the disconnection timestamp (UTC) and start a periodic verification timer that fires every 5 minutes.
4. WHEN `OnReconnected()` is called, THE `OfflineStateManager` SHALL clear the disconnection timestamp, clear the last notification timestamp, stop the verification timer, restore the normal tray icon, and restore the normal tooltip text.
5. THE `OfflineStateManager` SHALL expose a read-only `bool IsOffline` property that returns `true` when a disconnection timestamp is recorded and not yet cleared.
6. THE `OfflineStateManager` SHALL expose a read-only `TimeSpan? OfflineDuration` property that returns the elapsed time since the disconnection timestamp, or `null` if not offline.
7. THE `OfflineStateManager` SHALL NOT show any notification or change any visual state when `CloudEnabled` is `false` — it SHALL remain completely inert.
8. THE verification timer SHALL use `System.Threading.Timer` with a 5-minute interval and SHALL NOT block the UI thread.

---

### Requirement 2: Notificaciones Balloon Tip — Período de gracia y repetición

**User Story:** Como usuario de AlwaysPrint, quiero ser notificado de forma no invasiva cuando la desconexión de la nube supera 1 hora, para que esté informado del estado sin interrumpir mi trabajo.

#### Acceptance Criteria

1. WHILE the offline duration is less than 1 hour (grace period), THE `OfflineStateManager` SHALL NOT show any balloon tip notification to the user.
2. WHEN the offline duration reaches or exceeds 1 hour for the first time, THE `OfflineStateManager` SHALL show a balloon tip with `ToolTipIcon.Warning`, title from `LocalizationManager.Get("BalloonOfflineTitle")`, and text from `LocalizationManager.Get("BalloonOfflineText")`, displayed for 4000 milliseconds.
3. AFTER the first notification has been shown, THE `OfflineStateManager` SHALL repeat the balloon tip notification every 2 hours while the disconnection persists.
4. THE balloon tip SHALL be shown by posting to the UI thread via `SynchronizationContext.Post()` to avoid cross-thread exceptions.
5. WHEN `OnReconnected()` is called after a notification was shown, THE `OfflineStateManager` SHALL show a reconnection balloon tip with `ToolTipIcon.Info`, title from `LocalizationManager.Get("BalloonOfflineTitle")`, and text from `LocalizationManager.Get("BalloonReconnected")`, displayed for 3000 milliseconds.
6. THE `OfflineStateManager` SHALL NOT use `MessageBox`, modal dialogs, or any blocking UI element for notifications — only balloon tips via `NotifyIcon.ShowBalloonTip()`.

---

### Requirement 3: Icono del Tray en modo offline

**User Story:** Como usuario de AlwaysPrint, quiero que el icono del system tray cambie visualmente cuando estoy desconectado de la nube, para que pueda identificar el estado de un vistazo sin necesidad de leer notificaciones.

#### Acceptance Criteria

1. WHEN the offline duration reaches or exceeds 1 hour (same threshold as the first notification), THE `OfflineStateManager` SHALL change the tray icon to a visually distinct "offline" variant (grayscale or with a disconnection indicator).
2. WHEN `OnReconnected()` is called, THE `OfflineStateManager` SHALL restore the tray icon to the normal variant.
3. WHEN the tray icon is changed to offline mode, THE `OfflineStateManager` SHALL also update the tooltip text to `LocalizationManager.Get("TooltipOffline")`.
4. WHEN the tray icon is restored to normal mode, THE `OfflineStateManager` SHALL also restore the tooltip text to `LocalizationManager.Get("TrayTooltip")`.
5. THE offline icon SHALL be embedded as a resource in the AlwaysPrintTray assembly (file `logo_offline.ico` or equivalent).
6. THE icon change SHALL be performed on the UI thread via `SynchronizationContext.Post()`.

---

### Requirement 4: Telemetría offline — Acumulación y envío al reconectar

**User Story:** Como administrador de la plataforma, quiero que la telemetría acumulada durante períodos offline se envíe automáticamente al reconectar, para que no se pierdan datos operativos por desconexiones temporales.

#### Acceptance Criteria

1. WHEN the TelemetryReporter timer fires and the WebSocket is not connected, THE `TelemetryReporter` SHALL assemble the telemetry payload and enqueue it in a pending queue instead of discarding it.
2. THE pending telemetry queue SHALL have a maximum capacity of 100 entries. When the queue is full and a new payload needs to be enqueued, THE `TelemetryReporter` SHALL dequeue (discard) the oldest entry before enqueuing the new one.
3. WHEN `FlushPending()` is called and the WebSocket is connected, THE `TelemetryReporter` SHALL send all queued telemetry payloads in FIFO order via WebSocket with type "telemetry", stopping if the WebSocket becomes unavailable during the flush.
4. THE `TelemetryReporter` SHALL expose a public `void FlushPending()` method that can be called by `CloudManager` upon reconnection.
5. AFTER a successful flush of all pending payloads, THE pending queue SHALL be empty.
6. THE pending telemetry queue SHALL be protected by the existing `lock(_lock)` for thread safety.
7. THE `TelemetryReporter` SHALL still clear its accumulators (disconnection log, jobs_identified, release times) after assembling each payload for the queue, so that the next cycle starts fresh.

---

### Requirement 5: Modo sin configuración cacheada

**User Story:** Como usuario de AlwaysPrint con una workstation recién instalada que no puede conectarse a la nube, quiero que el sistema opere con valores por defecto y me notifique de forma prominente, para que sepa que la configuración no está completa.

#### Acceptance Criteria

1. WHEN `CloudEnabled=true` and no cached configuration exists in HKCU and the WebSocket is not connected at startup, THE `CloudManager` SHALL log a warning in Spanish indicating operation with defaults.
2. WHEN the no-config-offline condition is detected, THE `CloudManager` SHALL show a balloon tip with `ToolTipIcon.Warning`, title from `LocalizationManager.Get("BalloonOfflineTitle")`, and text from `LocalizationManager.Get("BalloonOfflineNoConfig")`.
3. WHEN operating without cached configuration, THE system SHALL use the default values from `AppConfiguration` (as persisted in HKLM by the installer) without modification.
4. WHEN the WebSocket connection is established for the first time and configuration is successfully downloaded, THE system SHALL transition to normal operation and the no-config warning SHALL not be shown again.
5. THE no-config-offline balloon tip SHALL be shown only once at startup — it SHALL NOT repeat.

---

### Requirement 6: Reconexión transparente

**User Story:** Como usuario de AlwaysPrint, quiero que al restaurarse la conexión con la nube el sistema se sincronice automáticamente sin intervención manual, para que la operación vuelva a la normalidad de forma transparente.

#### Acceptance Criteria

1. WHEN the WebSocket connection is re-established after a disconnection, THE `CloudManager` SHALL call `OfflineStateManager.OnReconnected()` to clear the offline state and restore visual indicators.
2. WHEN the WebSocket connection is re-established, THE `CloudManager` SHALL call `TelemetryReporter.FlushPending()` to send accumulated telemetry before the next periodic cycle.
3. WHEN the WebSocket connection is re-established, THE `CloudManager` SHALL show a reconnection balloon tip via `OfflineStateManager` or directly, with `ToolTipIcon.Info` and text from `LocalizationManager.Get("BalloonReconnected")`.
4. THE telemetry flush SHALL occur before the next periodic telemetry send to ensure chronological ordering of data at the backend.
5. IF `FlushPending()` fails partially (WebSocket disconnects during flush), THE remaining queued payloads SHALL be retained for the next reconnection attempt.

---

### Requirement 7: Strings de localización (i18n)

**User Story:** Como desarrollador de AlwaysPrint, quiero que todos los textos de notificación estén localizados en español e inglés, para que la interfaz sea consistente con el sistema de localización existente.

#### Acceptance Criteria

1. THE following keys SHALL be added to `Strings.resx` (English) and `Strings.es.resx` (Spanish):
   - `BalloonOfflineTitle`: "AlwaysPrint" / "AlwaysPrint"
   - `BalloonOfflineText`: "Using cached config. No cloud connection." / "Usando configuración guardada. Sin conexión a la nube."
   - `BalloonOfflineNoConfig`: "No cloud connection and no cached config. Using defaults." / "Sin conexión a la nube y sin configuración guardada. Usando valores por defecto."
   - `BalloonReconnected`: "Cloud connection restored." / "Conexión con la nube restaurada."
   - `TooltipOffline`: "AlwaysPrint (offline)" / "AlwaysPrint (sin conexión)"
2. ALL notification texts SHALL be retrieved via `LocalizationManager.Get(key)` — no hardcoded strings in the notification logic.
3. THE existing `TrayTooltip` key SHALL be used for the normal (online) tooltip text when restoring from offline state.

---

### Requirement 8: Integración con CloudManager

**User Story:** Como desarrollador de AlwaysPrint, quiero que el OfflineStateManager se integre correctamente en el ciclo de vida del CloudManager, para que los estados de conexión/desconexión se propaguen automáticamente.

#### Acceptance Criteria

1. THE `CloudManager` SHALL instantiate `OfflineStateManager` during `Start()` passing the UI `SynchronizationContext` and the `NotifyIcon` reference.
2. WHEN the `CloudWebSocketClient` raises the `Disconnected` event, THE `CloudManager` SHALL call `OfflineStateManager.OnDisconnected()` in addition to the existing `TelemetryReporter.RecordDisconnection()`.
3. WHEN the `CloudWebSocketClient` raises the `Connected` event, THE `CloudManager` SHALL call `OfflineStateManager.OnReconnected()` and `TelemetryReporter.FlushPending()` in addition to the existing `TelemetryReporter.RecordReconnection()`.
4. WHEN `CloudManager.Stop()` is called, THE `CloudManager` SHALL call `OfflineStateManager.Dispose()` to release the verification timer.
5. THE `OfflineStateManager` SHALL implement `IDisposable` to properly release the verification timer on disposal.
6. WHILE `CloudEnabled` is `false`, THE `CloudManager` SHALL NOT instantiate `OfflineStateManager` and no offline-related notifications SHALL be shown.

---

### Requirement 9: CloudEnabled=false — Sin impacto

**User Story:** Como usuario de AlwaysPrint con la integración cloud deshabilitada, quiero que ninguna funcionalidad de resiliencia offline se active, para que el sistema se comporte exactamente como antes de la Fase 5.

#### Acceptance Criteria

1. WHILE `CloudEnabled` is `false` in the configuration, THE `CloudManager` SHALL NOT instantiate `OfflineStateManager`, SHALL NOT show any balloon tips related to cloud connectivity, and SHALL NOT change the tray icon.
2. WHILE `CloudEnabled` is `false`, THE `TelemetryReporter` SHALL NOT be instantiated and no telemetry queue SHALL exist.
3. ALL Tray features present before Phase 5 (Named Pipe communication, local configuration display, system tray icon and menu) SHALL remain functional without modification when `CloudEnabled=false`.

---

### Requirement 10: Reglas de arquitectura y logging

**User Story:** Como arquitecto del sistema AlwaysPrint, quiero que todos los cambios de la Fase 5 respeten las reglas de arquitectura establecidas, para que la separación de responsabilidades se mantenga y el sistema sea auditable.

#### Acceptance Criteria

1. THE `OfflineStateManager` class SHALL reside in `AlwaysPrintTray/Cloud/` and SHALL NOT be placed in `AlwaysPrint.Shared` or `AlwaysPrintService`.
2. THE new code SHALL NOT use `Console.WriteLine` anywhere — all diagnostic output SHALL use `AlwaysPrintLogger` with messages in Spanish.
3. THE `AlwaysPrintService` project SHALL NOT reference any class under `AlwaysPrintTray/Cloud/` — the Service is not affected by Phase 5.
4. ALL state mutations in `OfflineStateManager` SHALL be thread-safe, using appropriate synchronization (lock or volatile) since the timer callback runs on a ThreadPool thread.
5. THE pending telemetry queue in `TelemetryReporter` SHALL be protected by the existing `lock(_lock)` — no new lock objects SHALL be introduced.
6. ALL log messages generated by Phase 5 code SHALL be in Spanish and SHALL use `WriteTrayInfo`, `WriteTrayWarning`, or `WriteTrayError`.
7. THE offline icon resource SHALL be embedded in the assembly — no external file dependencies at runtime.

---

### Requirement 11: Compilación sin errores ni advertencias

**User Story:** Como desarrollador de AlwaysPrint, quiero que la solución compile sin errores ni advertencias después de implementar la Fase 5, para que el pipeline de CI/CD no se vea afectado.

#### Acceptance Criteria

1. WHEN `dotnet build AlwaysPrint.sln -c Release --nologo` is executed from the `AlwaysPrintProject/Client/` directory, THE build SHALL complete with 0 errors and 0 warnings across all three projects (AlwaysPrint.Shared, AlwaysPrintService, AlwaysPrintTray).
2. ALL new files SHALL be included in the corresponding `.csproj` project file (if not auto-included by SDK-style project).
3. THE embedded resource `logo_offline.ico` SHALL be correctly referenced in the AlwaysPrintTray project file.
