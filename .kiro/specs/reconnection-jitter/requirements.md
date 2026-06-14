# Requirements Document

## Introduction

Implementación de jitter configurable para reconexiones de workstations al backend de AlwaysPrint. El sistema actual permite que 200-300+ workstations se reconecten simultáneamente tras eventos masivos (actualización, reinicio de tray, caída de backend), causando agotamiento del pool de conexiones y crash del backend. Este feature distribuye las reconexiones en una ventana temporal aleatoria para prevenir el efecto "thundering herd".

## Glossary

- **Organization**: Entidad multi-tenant que agrupa workstations (ej: BBVA). Modelo SQLAlchemy existente en `app.models.organization`.
- **Jitter_Window**: Ventana temporal en segundos dentro de la cual se distribuyen aleatoriamente las reconexiones. Valor configurable por organización.
- **Tray**: Aplicación de bandeja del sistema (AlwaysPrintTray) que mantiene la conexión WebSocket con el backend.
- **Service**: Servicio Windows (AlwaysPrintService) que gestiona actualizaciones y reinicia el Tray.
- **Backend**: Servidor FastAPI de AlwaysPrint Cloud Manager que recibe conexiones WebSocket.
- **Registry**: Registro de Windows (HKLM) bajo la ruta `SOFTWARE\Robles.AI\AlwaysPrint` donde se almacena la configuración local.
- **Config_Update**: Mensaje WebSocket de tipo `config_update` que sincroniza configuración de la organización a las workstations.
- **Thundering_Herd**: Patrón donde múltiples clientes se reconectan simultáneamente saturando el servidor.

## Requirements

### Requirement 1: Configuración de Jitter Window a nivel de organización

**User Story:** As an administrator, I want to configure the jitter window per organization, so that I can control how reconnections are distributed over time to prevent backend overload.

#### Acceptance Criteria

1. THE Organization model SHALL include a `jitter_window_seconds` column of type Integer with a default value of 30 and nullable set to False.
2. WHEN an administrator updates the Organization via the PATCH endpoint and includes `jitter_window_seconds` in the request body, THE Backend SHALL persist the new value; if `jitter_window_seconds` is omitted from the request body, THE Backend SHALL preserve the existing value unchanged.
3. IF an administrator sends a `jitter_window_seconds` value that is not an integer, is less than 5, or is greater than 300, THEN THE Backend SHALL reject the request with a response indicating a validation error and SHALL NOT modify the stored value.
4. THE Backend SHALL include `jitter_window_seconds` in every Config_Update payload sent to workstations via WebSocket.
5. THE Backend SHALL provide an Alembic migration to add the `jitter_window_seconds` column to the organizations table, setting the value to 30 for all existing rows.

### Requirement 2: Almacenamiento de configuración de jitter en Registry

**User Story:** As a workstation client, I want to store the jitter configuration in the Windows Registry, so that the Tray can apply the correct delay at startup without requiring a network connection.

#### Acceptance Criteria

1. WHEN the Tray receives a Config_Update message containing `jitter_window_seconds`, THE Tray SHALL write the value as a DWORD named `JitterWindowSeconds` in the Registry under the AlwaysPrint path.
2. WHEN the Tray starts and `JitterWindowSeconds` is not present in the Registry, THE Tray SHALL use a hardcoded default value of 30 seconds for all jitter delay calculations.
3. WHEN a successful msiexec installation completes, THE Service SHALL write a `LastUpdateTimestamp` value (String, ISO 8601 format with second precision in UTC, e.g. `2026-01-15T10:30:00Z`) to the Registry under the AlwaysPrint path.
4. WHEN the Service is about to kill and restart the Tray process, THE Service SHALL write a `LastRestartTimestamp` value (String, ISO 8601 format with second precision in UTC, e.g. `2026-01-15T10:30:00Z`) to the Registry under the AlwaysPrint path before terminating the Tray.
5. IF a Registry write operation for `JitterWindowSeconds`, `LastUpdateTimestamp`, or `LastRestartTimestamp` fails, THEN THE writing component (Tray or Service) SHALL log an error message indicating the failed key name and continue operation without interrupting the current workflow.

### Requirement 3: Jitter tras actualización masiva (Post mass-update)

**User Story:** As a system operator, I want workstations to apply random jitter after a mass update, so that all updated workstations do not reconnect simultaneously and crash the backend.

#### Acceptance Criteria

1. WHEN the Tray starts and the difference between the current time and `LastUpdateTimestamp` in the Registry is less than 60 seconds, THE Tray SHALL delay the WebSocket connection by a uniformly distributed random value between 0 and `JitterWindowSeconds` seconds (inclusive of 0, exclusive of the maximum).
2. WHEN the Tray starts and the difference between the current time and `LastUpdateTimestamp` in the Registry is 60 seconds or more, THE Tray SHALL connect to the WebSocket without additional jitter delay.
3. WHEN the Tray starts and `LastUpdateTimestamp` is not present in the Registry, THE Tray SHALL connect to the WebSocket without additional jitter delay.
4. IF `LastUpdateTimestamp` is present in the Registry but its value is not a valid ISO 8601 string or represents a time in the future relative to the current system clock, THEN THE Tray SHALL treat it as not present and connect without jitter delay.
5. IF `JitterWindowSeconds` is not present in the Registry or contains a value outside the range 5–300, THEN THE Tray SHALL use the hardcoded default of 30 seconds.
6. THE Tray SHALL log the calculated jitter delay value in seconds and the reason (post-update) before waiting.

### Requirement 4: Jitter tras reinicio masivo de Tray (Post restart_tray command)

**User Story:** As a system operator, I want workstations to apply random jitter after receiving a mass restart command, so that all restarted trays do not reconnect simultaneously.

#### Acceptance Criteria

1. WHEN the Tray starts and the difference between the current time and `LastRestartTimestamp` in the Registry is less than 60 seconds, THE Tray SHALL delay the WebSocket connection by a uniformly distributed random value between 0 and `JitterWindowSeconds` seconds (inclusive of 0, exclusive of the maximum).
2. WHEN the Tray starts and the difference between the current time and `LastRestartTimestamp` in the Registry is 60 seconds or more, THE Tray SHALL connect to the WebSocket without additional jitter delay.
3. WHEN the Tray starts and `LastRestartTimestamp` is not present in the Registry, THE Tray SHALL connect to the WebSocket without additional jitter delay.
4. IF both `LastUpdateTimestamp` and `LastRestartTimestamp` are within 60 seconds of the current time, THEN THE Tray SHALL apply jitter only once using the timestamp closest to the current time, and SHALL log which timestamp was selected as the jitter source.
5. IF `LastRestartTimestamp` is present in the Registry but its value is not a valid ISO 8601 string or represents a time in the future relative to the current system clock, THEN THE Tray SHALL treat it as not present and connect to the WebSocket without additional jitter delay.
6. THE Tray SHALL log the calculated jitter delay value in seconds and the reason (post-restart) before waiting.

### Requirement 5: Jitter tras desconexión WebSocket (Backend restart/crash)

**User Story:** As a system operator, I want the first reconnection attempt after a WebSocket disconnection to use random jitter, so that a backend restart does not trigger a thundering herd of simultaneous reconnections.

#### Acceptance Criteria

1. WHILE the Tray is running, WHEN the WebSocket connection is lost, THE Tray SHALL delay the first reconnection attempt by a uniformly distributed random value between 0 and `JitterWindowSeconds` seconds (read from the Registry) instead of the current fixed 1-second initial delay.
2. WHEN the first reconnection attempt after disconnection fails, THE Tray SHALL continue with exponential backoff starting at 2 seconds for subsequent attempts (2s, 4s, 8s, up to a maximum of 60 seconds).
3. THE Tray SHALL log the jitter delay value in seconds applied for the first reconnection attempt.
4. IF the WebSocket connection is lost and `JitterWindowSeconds` cannot be read from the Registry or contains a value outside the range 5–300, THEN THE Tray SHALL use the hardcoded default of 30 seconds as the jitter window for the first reconnection attempt.

### Requirement 6: Interfaz de usuario para configuración de jitter

**User Story:** As an administrator, I want to configure the jitter window from the frontend dashboard, so that I can adjust the reconnection distribution without accessing the database directly.

#### Acceptance Criteria

1. THE Frontend SHALL display a numeric input field for `jitter_window_seconds` in the organization settings page, accepting only integer values with a minimum of 5, a maximum of 300, and a step of 1.
2. WHEN the administrator changes the jitter window value and the active workstation count (N) is greater than 0, THE Frontend SHALL display a calculation showing: "Con X segundos de ventana y N workstations activas, aproximadamente N/X conexiones por segundo durante eventos masivos".
3. THE Frontend SHALL retrieve the count of active workstations (N) for the current organization when the settings page loads.
4. WHEN the administrator submits a jitter window value less than 5 or greater than 300, THE Frontend SHALL display a validation error indicating the allowed range (5-300) before sending the request to the Backend.
5. WHEN the administrator modifies the jitter window input value, THE Frontend SHALL update the displayed calculation within 300 milliseconds of the last keystroke.
6. IF the active workstation count (N) is 0, THEN THE Frontend SHALL display the calculation text without the connections-per-second rate, indicating that there are no active workstations to compute the estimate.
7. WHEN the administrator submits a valid jitter window value and the Backend confirms the update, THE Frontend SHALL display a success notification and reflect the saved value in the input field.

### Requirement 7: Sincronización de configuración a workstations

**User Story:** As a workstation client, I want to receive jitter window updates in real-time, so that configuration changes take effect without requiring a restart.

#### Acceptance Criteria

1. WHEN an administrator updates `jitter_window_seconds` for an organization, THE Backend SHALL broadcast a Config_Update message containing the new value to all connected workstations of that organization within 5 seconds of persisting the change.
2. WHEN the Tray receives a Config_Update with a new `jitter_window_seconds` value, THE Tray SHALL write the updated `JitterWindowSeconds` value to the Registry within 1 second of receiving the message.
3. THE Tray SHALL use the most recently synced `JitterWindowSeconds` value from the Registry for all subsequent jitter calculations.
4. IF the Tray fails to write `JitterWindowSeconds` to the Registry after receiving a Config_Update, THEN THE Tray SHALL log the failure and continue using the previous `JitterWindowSeconds` value already stored in the Registry.
