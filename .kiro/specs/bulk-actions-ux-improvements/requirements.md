# Requirements Document

## Introduction

Mejoras de experiencia de usuario para el sistema de acciones masivas (Bulk On-Demand Actions) de AlwaysPrint Cloud Manager. Se enriquece la información de workstations fallidas con hostname e IP, se añade un endpoint para detectar sesiones activas, y se implementa estimación de tiempo restante en el frontend durante la ejecución.

## Glossary

- **Bulk_Actions_API**: Conjunto de endpoints REST bajo `/api/v1/bulk-actions` que orquestan la ejecución masiva de acciones OnDemand.
- **Session_Status_Endpoint**: Endpoint `GET /bulk-actions/status/{session_id}` que retorna el estado actual de una sesión bulk.
- **Active_Session_Endpoint**: Nuevo endpoint `GET /bulk-actions/active` que detecta si hay una sesión bulk en ejecución.
- **Failed_Workstation_Detail**: Objeto enriquecido con id, hostname e ip_private de una workstation donde falló el envío.
- **Bulk_Progress_Frontend**: Componente del frontend que muestra el progreso de la ejecución masiva en tiempo real.
- **Redis_Mutex_Key**: Clave Redis con patrón `bulk:running:{org_id}` que indica una sesión activa para una organización.
- **Operator**: Usuario con rol `operator` que gestiona workstations de su propia organización.
- **Admin**: Usuario con rol `admin` que puede gestionar workstations de cualquier organización.

## Requirements

### Requirement 1: Enriquecimiento de workstations fallidas

**User Story:** Como operador, quiero ver el hostname e IP de las workstations donde falló el envío, para poder identificar rápidamente qué máquinas tuvieron problemas sin necesidad de buscar UUIDs manualmente.

#### Acceptance Criteria

1. WHEN the Session_Status_Endpoint returns a completed or cancelled session, THE Bulk_Actions_API SHALL include a `failed_workstation_details` field containing a list of objects with `id` (string), `hostname` (string or null), and `ip_private` (string) for each failed workstation.
2. WHEN the Session_Status_Endpoint resolves failed workstation details, THE Bulk_Actions_API SHALL query the workstations table filtering by the IDs stored in `failed_workstations` of the Redis session hash.
3. IF a failed workstation ID does not exist in the database, THEN THE Bulk_Actions_API SHALL return an entry with `id` set to the UUID, `hostname` set to null, and `ip_private` set to "unknown".
4. WHEN a bulk_progress WebSocket message is sent to operators, THE Bulk_Actions_API SHALL include the `failed_workstation_details` field with the same enriched format as the REST endpoint.
5. THE Bulk_Actions_API SHALL maintain backward compatibility by keeping the existing `failed_workstations` field (list of string IDs) alongside the new `failed_workstation_details` field.

### Requirement 2: Detección de sesión activa

**User Story:** Como operador, quiero saber si ya hay una ejecución masiva en curso antes de intentar iniciar una nueva, para evitar el error HTTP 409 y entender quién está ejecutando.

#### Acceptance Criteria

1. WHEN an authenticated user with role Operator or Admin sends a GET request to `/bulk-actions/active`, THE Active_Session_Endpoint SHALL return a JSON response indicating whether a bulk session is currently running.
2. WHILE the user has role Operator, THE Active_Session_Endpoint SHALL scan only the Redis_Mutex_Key for the user's own organization (`bulk:running:{user.organization_id}`).
3. WHILE the user has role Admin, THE Active_Session_Endpoint SHALL scan Redis_Mutex_Keys across all organizations using the key pattern `bulk:running:*`.
4. WHEN a running session is detected, THE Active_Session_Endpoint SHALL return `is_active: true` along with the `session_id` (string), `org_id` (string), and `started_at` (ISO datetime) extracted from the session hash in Redis.
5. WHEN no running session is detected, THE Active_Session_Endpoint SHALL return `is_active: false` with `session_id`, `org_id`, and `started_at` set to null.
6. IF Redis is unavailable, THEN THE Active_Session_Endpoint SHALL return HTTP 503 with a descriptive error message.
7. WHEN a user with role `readonly` sends a GET request to `/bulk-actions/active`, THE Active_Session_Endpoint SHALL return HTTP 403.

### Requirement 3: Estimación de tiempo restante en frontend

**User Story:** Como operador, quiero ver cuánto tiempo falta y a qué hora se estima que termine la ejecución masiva, para poder planificar mis actividades mientras espero.

#### Acceptance Criteria

1. WHILE a bulk session has status `running` and `sent` is greater than zero, THE Bulk_Progress_Frontend SHALL display the estimated remaining time calculated as `(total - sent) * (elapsed_ms / sent)` milliseconds.
2. WHILE a bulk session has status `running` and `sent` is greater than zero, THE Bulk_Progress_Frontend SHALL display the estimated completion time (ETA) calculated as the current timestamp plus the remaining time in milliseconds.
3. WHILE a bulk session has status `running` and `sent` is zero, THE Bulk_Progress_Frontend SHALL display "Calculating..." instead of a numeric time estimate.
4. WHEN the estimated remaining time is less than 60 seconds, THE Bulk_Progress_Frontend SHALL format the value as seconds (e.g., "~45s remaining").
5. WHEN the estimated remaining time is 60 seconds or more, THE Bulk_Progress_Frontend SHALL format the value as minutes and seconds (e.g., "~2m 30s remaining").
6. WHEN the bulk session transitions to a terminal status (completed, cancelled, or failed), THE Bulk_Progress_Frontend SHALL stop displaying the time estimation and show the final elapsed time instead.
7. THE Bulk_Progress_Frontend SHALL update the time estimation on each WebSocket progress message received, without making additional API calls.
8. THE Bulk_Progress_Frontend SHALL display the ETA in localized format using the active locale (es or en) from next-intl.
