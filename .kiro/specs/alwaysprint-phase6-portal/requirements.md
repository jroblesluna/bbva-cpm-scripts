# Requirements Document

## Introduction

La **Fase 6 — Mejoras al Portal Cloud (APCM)** extiende el backend FastAPI y el frontend Next.js para soportar la configuración de checks de conectividad, locale por organización, almacenamiento y visualización de telemetría, y visualización en tiempo real de resultados de conectividad. Esta fase es la primera centrada exclusivamente en el portal Cloud, construyendo sobre la infraestructura de datos que las Fases 1–5 establecieron en el Client C#.

El alcance incluye: migración Alembic para nuevas tablas (`telemetry_logs`, `connectivity_results`), extensión de schemas Pydantic y respuesta de configuración efectiva con `config_hash` SHA-256, persistencia de telemetría y resultados de conectividad recibidos por WebSocket con broadcast a operadores, nuevos endpoints REST para consulta histórica y estadísticas, página de configuración extendida con editor de checks de conectividad y selector de locale, dashboard de telemetría con historial y tendencias, dashboard de conectividad con actualización en tiempo real vía WebSocket, y tipos TypeScript estrictos para los nuevos modelos de datos.

Al finalizar esta fase, `alembic upgrade head` debe aplicar sin errores, el backend debe pasar todas las pruebas existentes más las nuevas, y `npm run build` en el frontend debe compilar sin errores TypeScript.

## Glossary

- **APCM**: AlwaysPrint Cloud Manager — plataforma SaaS (FastAPI + Next.js) que gestiona las estaciones AlwaysPrint.
- **Backend**: Aplicación FastAPI en `AlwaysPrintProject/Cloud/backend/` que expone la API REST y WebSocket.
- **Frontend**: Aplicación Next.js 15 en `AlwaysPrintProject/Cloud/frontend/` que provee el dashboard de operadores.
- **GlobalConfig**: Modelo SQLAlchemy de configuración a nivel de cuenta (tabla `global_configs`). Aplica a todas las estaciones de una organización.
- **VLANConfig**: Modelo SQLAlchemy de configuración a nivel de VLAN (tabla `vlan_configs`). Sobrescribe GlobalConfig para estaciones en esa VLAN.
- **WorkstationConfig**: Modelo SQLAlchemy de configuración a nivel de estación (tabla `workstation_configs`). Sobrescribe VLANConfig y GlobalConfig.
- **EffectiveConfig**: Configuración resuelta aplicando la jerarquía WorkstationConfig > VLANConfig > GlobalConfig.
- **config_hash**: Hash SHA-256 del JSON de configuración efectiva serializado con `sort_keys=True`. Permite al Client detectar cambios sin comparar campo a campo.
- **TelemetryLog**: Nueva tabla que almacena snapshots periódicos de telemetría enviados por las workstations (estado de cola, contingencia, jobs, tiempos de liberación, desconexiones).
- **ConnectivityResult**: Nueva tabla que almacena resultados individuales de checks de conectividad ejecutados por las workstations.
- **ConnectivityCheck**: Objeto de configuración que define un endpoint a verificar (tipo HTTP/TCP/Ping/DNS, URL/host, timeout).
- **WebSocket_Manager**: Servicio `connection_manager` que gestiona conexiones WebSocket de workstations y operadores, incluyendo broadcast por cuenta.
- **Operator**: Usuario del dashboard (rol operador o admin) que visualiza el estado de las workstations en tiempo real.
- **Tenant_Isolation**: Principio de seguridad que requiere que todas las queries filtren por `organization_id` (account_id) para evitar acceso cruzado entre organizaciones.
- **Alembic**: Herramienta de migraciones de base de datos para SQLAlchemy.
- **React_Query**: Librería de data fetching usada en el frontend para peticiones REST con cache y revalidación.
- **useWebSocket**: Hook existente en el frontend que gestiona la conexión WebSocket con el backend para actualizaciones en tiempo real.

---

## Requirements


### Requirement 1: Migración Alembic — Nuevas tablas de telemetría y conectividad

**User Story:** Como administrador de la plataforma, quiero que la base de datos tenga tablas dedicadas para almacenar telemetría y resultados de conectividad, para que los datos históricos se persistan de forma estructurada y consultable.

#### Acceptance Criteria

1. WHEN `alembic upgrade head` is executed, THE Migration SHALL create the `telemetry_logs` table with columns: `id` (UUID, primary key), `workstation_id` (UUID, FK to workstations.id with CASCADE delete), `account_id` (UUID, FK to accounts.id with CASCADE delete), `queue_status` (String(20), nullable), `contingency_active` (Boolean, nullable), `jobs_identified` (Integer, nullable), `avg_release_time_ms` (BigInteger, nullable), `disconnection_count` (Integer, nullable), `recorded_at` (DateTime, not null, default utcnow).
2. WHEN `alembic upgrade head` is executed, THE Migration SHALL create the `connectivity_results` table with columns: `id` (UUID, primary key), `workstation_id` (UUID, FK to workstations.id with CASCADE delete), `account_id` (UUID, FK to accounts.id with CASCADE delete), `check_id` (String(100), not null), `check_type` (String(20), not null), `success` (Boolean, not null), `latency_ms` (BigInteger, nullable), `error` (String(500), nullable), `recorded_at` (DateTime, not null, default utcnow).
3. WHEN `alembic downgrade` is executed for this migration, THE Migration SHALL drop only the `telemetry_logs` and `connectivity_results` tables and their associated indexes, leaving all other existing tables and their data unchanged.
4. WHEN `alembic upgrade head` is executed, THE Migration SHALL create a composite index on `telemetry_logs(workstation_id, recorded_at)` for efficient time-range queries.
5. WHEN `alembic upgrade head` is executed, THE Migration SHALL create a composite index on `connectivity_results(workstation_id, check_id, recorded_at)` for efficient filtered time-range queries.
6. THE Migration file SHALL follow the existing naming convention: `007_add_telemetry_and_connectivity_tables.py`.
7. THE Migration SHALL declare `revision` and `down_revision` to chain correctly in the Alembic migration history after the most recent existing migration.

---

### Requirement 2: Modelos SQLAlchemy — TelemetryLog y ConnectivityResult

**User Story:** Como desarrollador del backend, quiero modelos SQLAlchemy para las nuevas tablas, para que las operaciones de lectura y escritura sigan los patrones ORM existentes del proyecto.

#### Acceptance Criteria

1. THE Backend SHALL define a `TelemetryLog` model in `app/models/telemetry.py` with `__tablename__ = "telemetry_logs"` and the following columns: `id` (GUID, primary key, default uuid4), `workstation_id` (GUID, ForeignKey to `workstations.id` with `ondelete="CASCADE"`, not null, indexed), `account_id` (GUID, ForeignKey to `accounts.id` with `ondelete="CASCADE"`, not null, indexed), `queue_status` (String(20), nullable), `contingency_active` (Boolean, nullable), `jobs_identified` (Integer, nullable), `avg_release_time_ms` (BigInteger, nullable), `disconnection_count` (Integer, nullable), `recorded_at` (DateTime, not null, default `datetime.utcnow`, indexed).
2. THE Backend SHALL define a `ConnectivityResult` model in `app/models/telemetry.py` with `__tablename__ = "connectivity_results"` and the following columns: `id` (GUID, primary key, default uuid4), `workstation_id` (GUID, ForeignKey to `workstations.id` with `ondelete="CASCADE"`, not null, indexed), `account_id` (GUID, ForeignKey to `accounts.id` with `ondelete="CASCADE"`, not null, indexed), `check_id` (String(100), not null), `check_type` (String(20), not null), `success` (Boolean, not null), `latency_ms` (BigInteger, nullable), `error` (String(500), nullable), `recorded_at` (DateTime, not null, default `datetime.utcnow`, indexed).
3. THE `TelemetryLog` model SHALL define a many-to-one `relationship` to `Workstation` (via `workstation_id`) and a many-to-one `relationship` to `Account` (via `account_id`), using `back_populates` to enable bidirectional navigation.
4. THE `ConnectivityResult` model SHALL define a many-to-one `relationship` to `Workstation` (via `workstation_id`) and a many-to-one `relationship` to `Account` (via `account_id`), using `back_populates` to enable bidirectional navigation.
5. THE new models SHALL be registered in `app/models/__init__.py` by importing `TelemetryLog` and `ConnectivityResult` from `app.models.telemetry` and adding both to the `__all__` list, enabling Alembic auto-detection.
6. THE `TelemetryLog` and `ConnectivityResult` models SHALL use the existing `GUID` type and inherit from the existing `Base` class, following the same patterns used by `Workstation` and `Account` models.

---

### Requirement 3: Schemas Pydantic — Extensión de configuración con checks de conectividad y locale

**User Story:** Como desarrollador del backend, quiero que los schemas Pydantic de configuración incluyan los campos de conectividad, locale y telemetría, para que la validación de entrada sea consistente en todos los niveles de la jerarquía.

#### Acceptance Criteria

1. THE `GlobalConfigUpdate` schema SHALL include the fields: `connectivity_checks` (Optional[List[ConnectivityCheckItem]], max 50 items), `locale` (Optional[str], max_length=10), `telemetry_enabled` (Optional[bool]), `telemetry_interval_seconds` (Optional[int], ge=10, le=86400).
2. THE `VLANConfigUpdate` schema SHALL include the same four fields as GlobalConfigUpdate with identical validation constraints.
3. THE `WorkstationConfigUpdate` schema SHALL include the same four fields as GlobalConfigUpdate with identical validation constraints.
4. THE `ConnectivityCheckItem` schema SHALL accept `type` values limited to `"http"`, `"tcp"`, `"ping"`, and `"dns"`, rejecting any other value with a validation error.
5. IF `type` is `"http"`, THEN THE `ConnectivityCheckItem` SHALL require the `url` field and return a validation error when it is absent.
6. IF `type` is `"tcp"`, THEN THE `ConnectivityCheckItem` SHALL require the `host` and `port` fields and return a validation error when either is absent.
7. IF `type` is `"ping"`, THEN THE `ConnectivityCheckItem` SHALL require the `host` field and return a validation error when it is absent.
8. IF `type` is `"dns"`, THEN THE `ConnectivityCheckItem` SHALL require the `hostname` field and return a validation error when it is absent.
9. THE `ConnectivityCheckItem` SHALL have a `timeout_ms` field with default value 5000, minimum 100, and maximum 30000.
10. IF a `ConnectivityCheckItem` includes fields not applicable to its `type` (e.g., `url` for `"ping"` type), THEN THE schema SHALL ignore those fields without raising a validation error.
11. IF `connectivity_checks` contains more than 50 items, THEN THE schema SHALL return a validation error indicating the list exceeds the maximum allowed length.

---

### Requirement 4: EffectiveConfigResponse — Inclusión de config_hash

**User Story:** Como desarrollador del Client C#, quiero que la respuesta de configuración efectiva incluya un hash SHA-256, para que el Client pueda detectar cambios de configuración comparando hashes sin analizar cada campo.

#### Acceptance Criteria

1. THE `EffectiveConfigResponse` SHALL include a `config_hash` field of type `str` with exactly 64 lowercase hexadecimal characters.
2. THE Backend SHALL compute `config_hash` as the SHA-256 hex digest of the UTF-8 encoding of the JSON serialization of the effective config fields with `sort_keys=True` and `ensure_ascii=False`.
3. THE `config_hash` computation SHALL exclude the `source` field from the hash input.
4. THE `config_hash` computation SHALL exclude the `config_hash` field itself from the hash input.
5. THE Backend SHALL produce the same `config_hash` value when computing the hash of the same effective config field values across multiple invocations (determinism property).
6. THE endpoint `GET /api/v1/workstations/{id}/config` SHALL include `config_hash` in the response body.
7. IF the effective config contains fields with `None` values, THEN THE Backend SHALL serialize them as JSON `null` before computing `config_hash`.

---

### Requirement 5: WebSocket — Persistencia de telemetría en base de datos

**User Story:** Como administrador de la plataforma, quiero que los mensajes de telemetría recibidos por WebSocket se persistan en la base de datos, para que pueda consultar el historial de estado de las workstations.

#### Acceptance Criteria

1. WHEN a valid `telemetry` message is received via WebSocket, THE Backend SHALL create a new `TelemetryLog` record with the workstation_id, account_id, queue_status, contingency_active, jobs_identified, avg_release_time_ms, and disconnection_count extracted from the message payload, where queue_status is one of "ok", "missing", or "error", jobs_identified is an integer between 0 and 2,147,483,647, and avg_release_time_ms is a nullable integer between 0 and 9,223,372,036,854,775,807.
2. WHEN a valid `telemetry` message is received, THE Backend SHALL set `disconnection_count` to the length of the `disconnection_log` array in the payload, accepting a value between 0 and 1000 elements.
3. WHEN a valid `telemetry` message is successfully persisted in the database, THE Backend SHALL broadcast a `telemetry_received` message to all connected operators of the same account via `connection_manager.broadcast_to_account()` within 2 seconds of persistence completion.
4. IF the `telemetry` message payload fails Pydantic validation, THEN THE Backend SHALL log the validation error with the workstation_id and discard the message without closing the WebSocket connection, and the connection SHALL continue accepting subsequent messages.
5. WHEN persisting a `TelemetryLog` record, THE Backend SHALL verify that the workstation_id exists in the `workstations` table filtered by the sender's `account_id` (tenant isolation) before writing the record.
6. IF the workstation_id in the telemetry payload does not correspond to an existing workstation within the sender's account, THEN THE Backend SHALL discard the message, log the error, and keep the WebSocket connection open.
7. IF the database write fails during telemetry persistence, THEN THE Backend SHALL log the error with the workstation_id and message details, skip the broadcast to operators, and keep the WebSocket connection open for subsequent messages.

---

### Requirement 6: WebSocket — Persistencia de resultados de conectividad en base de datos

**User Story:** Como administrador de la plataforma, quiero que los resultados de checks de conectividad recibidos por WebSocket se persistan en la base de datos, para que pueda consultar el historial de disponibilidad de los endpoints monitoreados.

#### Acceptance Criteria

1. WHEN a valid `connectivity_result` message is received via WebSocket, THE Backend SHALL create a new `ConnectivityResult` record with the workstation_id, account_id, check_id, check_type (taken from the `check_type` field in the message payload), success, latency_ms (integer between 0 and 2,147,483,647, or null if check failed), error (string up to 500 characters, or null if check succeeded), and a `recorded_at` timestamp set to the current UTC time.
2. WHEN a valid `connectivity_result` message is persisted, THE Backend SHALL broadcast a `connectivity_result` message containing the workstation_id, check_id, check_type, success, latency_ms, and error fields to all connected operators of the same account via `connection_manager.broadcast_to_account()`.
3. IF the `connectivity_result` message payload fails Pydantic validation, THEN THE Backend SHALL log the validation error at ERROR level with the workstation_id and discard the message without closing the WebSocket connection.
4. IF the workstation_id does not exist for the given account_id (tenant isolation), THEN THE Backend SHALL log a warning with the workstation_id and account_id, and discard the message without persisting a record or broadcasting.
5. THE `ConnectivityResultMessage` schema SHALL include a `check_type` field with allowed values `"http"`, `"tcp"`, `"ping"`, `"dns"`.
6. THE connectivity result persistence query SHALL filter by `account_id` to enforce tenant isolation when verifying the workstation exists before persisting the record.

---

### Requirement 7: Endpoints REST — Historial de telemetría por workstation

**User Story:** Como operador del dashboard, quiero consultar el historial de telemetría de una workstation específica, para que pueda analizar tendencias y diagnosticar problemas.

#### Acceptance Criteria

1. THE Backend SHALL expose `GET /api/v1/workstations/{id}/telemetry` endpoint where `{id}` is a valid workstation UUID.
2. THE endpoint SHALL accept optional query parameters: `from` (ISO 8601 datetime), `to` (ISO 8601 datetime), `limit` (integer, minimum 1, default 100, maximum 1000).
3. WHEN called with valid parameters, THE endpoint SHALL return a JSON array of TelemetryLog records containing the fields `id`, `workstation_id`, `queue_status`, `contingency_active`, `jobs_identified`, `avg_release_time_ms`, `disconnection_count`, and `recorded_at`, ordered by `recorded_at` descending, limited to the number specified by `limit`. WHEN no records match the query, THE endpoint SHALL return an empty JSON array `[]` with HTTP 200.
4. THE endpoint SHALL filter results by the authenticated user's `account_id` (tenant isolation).
5. IF the workstation does not exist or does not belong to the user's account, THEN THE endpoint SHALL return HTTP 404.
6. IF the Bearer token is missing or invalid, THEN THE endpoint SHALL return HTTP 401 with an error message indicating authentication failure.
7. IF `from` is later than `to`, or `limit` is less than 1 or greater than 1000, or datetime parameters are not valid ISO 8601 format, THEN THE endpoint SHALL return HTTP 422 with an error message indicating the validation failure.
8. WHEN `from` and `to` are both omitted, THE endpoint SHALL return the most recent records up to `limit` without time filtering. WHEN only `from` is provided, THE endpoint SHALL return records from that datetime onward. WHEN only `to` is provided, THE endpoint SHALL return records up to that datetime.

---

### Requirement 8: Endpoints REST — Resultados de conectividad por workstation

**User Story:** Como operador del dashboard, quiero consultar el historial de resultados de conectividad de una workstation, para que pueda identificar patrones de fallo en endpoints específicos.

#### Acceptance Criteria

1. THE Backend SHALL expose `GET /api/v1/workstations/{id}/connectivity` endpoint.
2. THE endpoint SHALL accept optional query parameters: `check_id` (string, max 255 characters, filter by specific check), `from` (ISO 8601 datetime), `to` (ISO 8601 datetime), `limit` (integer, default 100, min 1, max 1000).
3. WHEN called with valid parameters, THE endpoint SHALL return a JSON array of ConnectivityResult records ordered by `recorded_at` descending, where each record contains: `id` (UUID), `check_id` (string), `check_type` (string), `success` (boolean), `latency_ms` (integer or null), `error` (string or null), and `recorded_at` (ISO 8601 datetime).
4. THE endpoint SHALL filter results by the authenticated user's `account_id` (tenant isolation).
5. IF the workstation does not exist or does not belong to the user's account, THEN THE endpoint SHALL return HTTP 404.
6. THE endpoint SHALL require authentication via Bearer token.
7. IF any query parameter is invalid (non-ISO 8601 datetime in `from`/`to`, `limit` outside 1–1000 range, `check_id` exceeding 255 characters, or `from` later than `to`), THEN THE endpoint SHALL return HTTP 422 with an error message indicating which parameter is invalid.
8. WHEN called with valid parameters that match no records, THE endpoint SHALL return an empty JSON array with HTTP 200.

---

### Requirement 9: Endpoints REST — Estadísticas de telemetría por cuenta

**User Story:** Como operador del dashboard, quiero ver estadísticas agregadas de telemetría de toda mi organización, para que pueda tener una visión general del estado de la flota de workstations.

#### Acceptance Criteria

1. THE Backend SHALL expose `GET /api/v1/accounts/{id}/telemetry/stats` endpoint.
2. WHEN the endpoint is called with a valid Bearer token and the account exists, THE endpoint SHALL return a JSON object with: `total_workstations` (int, total workstations registered for the account), `workstations_reporting` (int, workstations with at least one telemetry record in the last 24 hours UTC), `avg_jobs_identified` (float, arithmetic mean of `jobs_identified` across all telemetry records of the last 24 hours UTC, rounded to 2 decimal places), `contingency_active_count` (int, number of workstations whose most recent telemetry record within the last 24 hours UTC has `contingency_active = true`), `queue_status_summary` (object with integer counts per status: `ok`, `missing`, `error`, derived from the most recent telemetry record per workstation within the last 24 hours UTC), `last_updated` (ISO 8601 datetime in UTC of the most recent telemetry record for the account, or `null` if no records exist in the last 24 hours).
3. THE endpoint SHALL compute statistics exclusively from telemetry records whose `recorded_at` falls within the last 24 hours relative to the current server time in UTC.
4. THE endpoint SHALL filter all queries by the authenticated user's `account_id` to enforce tenant isolation.
5. IF the account does not exist or the authenticated user's `account_id` does not match the requested `{id}`, THEN THE endpoint SHALL return HTTP 404 with no body revealing account existence.
6. THE endpoint SHALL require authentication via Bearer token.
7. IF the Bearer token is missing, expired, or invalid, THEN THE endpoint SHALL return HTTP 401 with an error message indicating authentication failure.
8. IF no telemetry records exist for the account within the last 24 hours, THEN THE endpoint SHALL return the JSON object with `workstations_reporting` set to 0, `avg_jobs_identified` set to 0.0, `contingency_active_count` set to 0, `queue_status_summary` with all counts set to 0, and `last_updated` set to `null`.
9. THE endpoint SHALL return the response within 2000 milliseconds for accounts with up to 10000 workstations.

---

### Requirement 10: Frontend — Editor de checks de conectividad en página de configuración

**User Story:** Como operador del dashboard, quiero configurar los checks de conectividad desde la página de configuración, para que pueda definir qué endpoints deben monitorear las workstations de mi organización.

#### Acceptance Criteria

1. THE Frontend SHALL display a "Checks de Conectividad" section in the existing config page (`/dashboard/config`).
2. THE section SHALL show a table listing existing connectivity checks with columns: ID, Tipo, URL/Host, Timeout (ms).
3. WHEN the user clicks "Agregar check", THE Frontend SHALL display a modal form with fields: tipo (select: HTTP/TCP/Ping/DNS), URL (for HTTP), host (for TCP/Ping), hostname (for DNS), port (for TCP), timeout_ms (number input, default 5000).
4. WHEN the user submits the modal form with valid data, THE Frontend SHALL add the check to the local list and mark the configuration as modified.
5. WHEN the user clicks the delete button on a check row, THE Frontend SHALL remove the check from the local list and mark the configuration as modified.
6. WHEN the user saves the configuration, THE Frontend SHALL include the `connectivity_checks` array in the PUT request to `/api/v1/config/global`.
7. THE Frontend SHALL validate that each check has a unique `id` within the list before saving.
8. THE Frontend SHALL enforce the maximum of 50 connectivity checks per configuration.
9. THE modal form SHALL conditionally show/hide fields based on the selected type: URL field visible only for HTTP, host field visible for TCP and Ping, hostname field visible only for DNS, port field visible only for TCP.
10. IF the user attempts to save with validation errors (duplicate IDs, missing required fields per type, exceeding 50 checks), THEN THE Frontend SHALL display an inline error message and prevent the save operation.

---

### Requirement 11: Frontend — Selector de locale en página de configuración

**User Story:** Como operador del dashboard, quiero seleccionar el idioma (locale) para las workstations de mi organización desde la página de configuración, para que los mensajes del Tray se muestren en el idioma correcto.

#### Acceptance Criteria

1. THE Frontend SHALL display a "Locale" selector in the config page with options: "" (Automático/Sistema), "es" (Español), "en" (English).
2. WHEN the user selects a locale value, THE Frontend SHALL mark the configuration as modified.
3. WHEN the user saves the configuration, THE Frontend SHALL include the `locale` field in the PUT request to `/api/v1/config/global`.
4. THE locale selector SHALL display the current saved value when the page loads.

---

### Requirement 12: Frontend — Dashboard de telemetría

**User Story:** Como operador del dashboard, quiero una página dedicada para visualizar la telemetría de las workstations, para que pueda monitorear el estado operativo de la flota y detectar anomalías.

#### Acceptance Criteria

1. THE Frontend SHALL create a new page at `/dashboard/telemetry` accessible from the sidebar navigation, listed after the existing "workstations" entry.
2. THE page SHALL display a table of workstations with their most recent telemetry entry per workstation, showing the following columns: workstation name, queue_status (badge: OK/Missing/Error), contingency_active (badge: active/inactive), jobs_identified (integer), avg_release_time_ms (integer with "ms" suffix), and disconnection_count (integer).
3. WHEN the user selects a workstation from the table, THE page SHALL display the telemetry history for the last 24 hours fetched from `GET /api/v1/workstations/{id}/telemetry`, limited to a maximum of 100 entries sorted by `recorded_at` descending.
4. THE page SHALL display account-level statistics fetched from `GET /api/v1/accounts/{id}/telemetry/stats` at the top of the page, showing: total workstations reporting, count of workstations with queue_status "error" or "missing", count of workstations with contingency_active true, and average avg_release_time_ms across all workstations.
5. THE page SHALL use React Query for data fetching with a staleTime of 60 seconds and automatic cache invalidation on window refocus and on each auto-refresh cycle.
6. WHILE the page is mounted and visible, THE page SHALL auto-refresh the workstation list and account-level statistics every 60 seconds without requiring user interaction.
7. THE page SHALL use strict TypeScript types (no `any`) for all data models, referencing the `TelemetryEntry` interface defined in `src/types/telemetry.ts`.
8. IF the telemetry API request fails or returns an error, THEN THE page SHALL display an error message indicating the failure reason and a retry button, while preserving any previously loaded data on screen.
9. WHILE telemetry data is being fetched for the first time, THE page SHALL display a loading skeleton placeholder matching the layout of the table and statistics cards.
10. IF no telemetry data exists for the selected workstation or for the account, THEN THE page SHALL display an empty-state message indicating that no telemetry has been recorded yet.

---

### Requirement 13: Frontend — Dashboard de conectividad en tiempo real

**User Story:** Como operador del dashboard, quiero una página dedicada para visualizar los resultados de conectividad en tiempo real, para que pueda detectar inmediatamente cuando un endpoint falla y tomar acción correctiva.

#### Acceptance Criteria

1. THE Frontend SHALL create a new page at `/dashboard/connectivity` accessible from the sidebar navigation.
2. THE page SHALL display a list of workstations with their configured connectivity checks and the latest result for each check: check_id, check_type, success (green/red indicator), latency_ms, last error message.
3. WHEN a `connectivity_result` WebSocket message is received, THE page SHALL update the corresponding check's status in real-time without requiring a page refresh.
4. WHEN the user selects a workstation, THE page SHALL display the connectivity history for the last 24 hours fetched from `GET /api/v1/workstations/{id}/connectivity`.
5. THE page SHALL use the existing `useWebSocket` hook for real-time updates from the operator WebSocket connection.
6. THE page SHALL use strict TypeScript types (no `any`) for all data models.
7. THE page SHALL display a visual indicator (green/red dot) for each check's current status.
8. IF the connectivity API request fails, THEN THE page SHALL display an error message and a retry button while preserving previously loaded data.
9. WHILE connectivity data is being fetched for the first time, THE page SHALL display a loading skeleton placeholder.

---

### Requirement 14: Frontend — Tipos TypeScript para nuevos modelos de datos

**User Story:** Como desarrollador del frontend, quiero tipos TypeScript estrictos para los nuevos modelos de telemetría y conectividad, para que el código sea type-safe y el compilador detecte errores en tiempo de desarrollo.

#### Acceptance Criteria

1. THE Frontend SHALL define a `TelemetryEntry` interface in `src/types/telemetry.ts` with fields: `id` (string), `workstation_id` (string), `queue_status` ('ok' | 'missing' | 'error'), `contingency_active` (boolean), `jobs_identified` (number), `avg_release_time_ms` (number | null), `disconnection_count` (number), `recorded_at` (string, ISO 8601 format).
2. THE Frontend SHALL define a `ConnectivityResult` interface in `src/types/telemetry.ts` with fields: `id` (string), `workstation_id` (string), `check_id` (string), `check_type` ('http' | 'tcp' | 'ping' | 'dns'), `success` (boolean), `latency_ms` (number | null), `error` (string | null), `recorded_at` (string, ISO 8601 format).
3. THE Frontend SHALL define a `TelemetryStats` interface in `src/types/telemetry.ts` with fields: `total_workstations` (number), `workstations_reporting` (number), `avg_jobs_identified` (number), `contingency_active_count` (number), `queue_status_summary` ({ ok: number; missing: number; error: number }), `last_updated` (string | null).
4. THE Frontend SHALL extend the existing `EffectiveConfig` interface in `src/types/config.ts` to include the following additional fields while preserving all existing fields: `connectivity_checks` (ConnectivityCheck[]), `locale` (string), `telemetry_enabled` (boolean), `telemetry_interval_seconds` (number), `config_hash` (string).
5. THE Frontend SHALL define a `ConnectivityCheck` interface in `src/types/config.ts` with fields: `id` (string), `type` ('http' | 'tcp' | 'ping' | 'dns'), `url` (string | undefined), `host` (string | undefined), `hostname` (string | undefined), `port` (number | undefined), `timeout_ms` (number).
6. ALL new types SHALL use union types or literal types instead of `any`, and SHALL use `| null` for fields that may be absent in API responses and `| undefined` (or optional `?`) for fields that are conditionally present based on the check type.
7. THE Frontend SHALL re-export all new types from `src/types/telemetry.ts` through the barrel file `src/types/index.ts`.
8. WHEN `npm run build` is executed with the project's existing `tsconfig.json` strict mode settings, THE Frontend SHALL compile with 0 TypeScript errors related to the new or modified type definitions.

---

### Requirement 15: Extensión de tipos WebSocket para operadores

**User Story:** Como desarrollador del frontend, quiero tipos TypeScript para los nuevos mensajes WebSocket de telemetría y conectividad, para que el manejo de mensajes en tiempo real sea type-safe.

#### Acceptance Criteria

1. THE Frontend SHALL define a `TelemetryReceivedMessage` interface in `src/types/websocket.ts` with fields: `type` ('telemetry_received'), `workstation_id` (string), `queue_status` (string), `contingency_active` (boolean), `jobs_identified` (number), `avg_release_time_ms` (number | null), `disconnection_count` (number).
2. THE Frontend SHALL define a `ConnectivityResultReceivedMessage` interface in `src/types/websocket.ts` with fields: `type` ('connectivity_result'), `workstation_id` (string), `check_id` (string), `check_type` (string), `success` (boolean), `latency_ms` (number | null), `error` (string | null).
3. THE `OperatorMessage` union type SHALL be extended to include `TelemetryReceivedMessage` and `ConnectivityResultReceivedMessage`.

---

### Requirement 16: Tenant isolation y seguridad en nuevos endpoints

**User Story:** Como arquitecto del sistema, quiero que todos los nuevos endpoints respeten el aislamiento por organización, para que ningún operador pueda acceder a datos de otra organización.

#### Acceptance Criteria

1. THE telemetry endpoint SHALL verify that the requested workstation belongs to the authenticated user's account before returning data.
2. THE connectivity endpoint SHALL verify that the requested workstation belongs to the authenticated user's account before returning data.
3. THE telemetry stats endpoint SHALL only aggregate data from workstations belonging to the authenticated user's account.
4. THE WebSocket telemetry persistence SHALL associate each record with the correct `account_id` derived from the workstation's account relationship.
5. THE WebSocket connectivity persistence SHALL associate each record with the correct `account_id` derived from the workstation's account relationship.
6. IF a user with role `admin` requests data, THEN THE endpoints SHALL allow access to any account's data (consistent with existing endpoint behavior).

---

### Requirement 17: Reglas de arquitectura, logging y convenciones

**User Story:** Como arquitecto del sistema, quiero que todos los cambios de la Fase 6 respeten las convenciones del proyecto, para que el código sea consistente y mantenible.

#### Acceptance Criteria

1. ALL Python comments and log messages in new backend code SHALL be written in Spanish.
2. ALL TypeScript comments in new frontend code SHALL be written in Spanish.
3. THE Backend SHALL NOT use `print()` for logging — all diagnostic output SHALL use the `logging` module with appropriate log levels.
4. THE Frontend SHALL NOT use `any` type anywhere in new code — all variables and parameters SHALL have explicit types.
5. THE new REST endpoints SHALL follow the existing pattern of using `Depends(get_current_user)` for authentication and `Depends(get_db)` for database sessions.
6. THE new Pydantic schemas SHALL follow the existing pattern of using `Field()` with descriptions in Spanish for documentation.
7. ALL new frontend pages SHALL use the existing `apiClient` for HTTP requests and follow the existing component patterns (Tailwind CSS, lucide-react icons, shadcn/ui components).
8. THE new migration file SHALL follow the existing Alembic conventions (revision chain, upgrade/downgrade functions).
