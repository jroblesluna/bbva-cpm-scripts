# Requirements Document

## Introduction

Escalar el backend de AlwaysPrint Cloud Management para soportar 8100 conexiones WebSocket simultáneas de workstations. Actualmente, con 1 worker uvicorn en una instancia t3.small (2 GB RAM, 2 vCPU), el sistema solo sostiene ~1500 conexiones antes de saturarse (latencia >3s, 7434 fallos de 8100 intentos).

La solución introduce Redis pub/sub como broker de mensajes entre múltiples workers uvicorn, un cache Redis para eliminar queries redundantes durante el registro, y optimizaciones del hot path de conexión. El protocolo WebSocket hacia el cliente C# no cambia. El despliegue inicial es solo para el entorno DEV.

## Glossary

- **Connection_Manager**: Componente que mantiene el estado de conexiones WebSocket activas de workstations y operadores dentro de un worker uvicorn
- **Redis_Broker**: Servicio Redis que actúa como canal pub/sub para sincronizar mensajes entre múltiples workers uvicorn
- **Registration_Cache**: Cache en Redis que almacena datos de organizaciones, VLANs y configuraciones para evitar queries repetitivas a PostgreSQL durante el registro de workstations
- **Worker**: Proceso uvicorn independiente que maneja un subconjunto de conexiones WebSocket
- **Death_Ping**: Mecanismo de detección de conexiones WebSocket muertas basado en inactividad y timeout de pong
- **Cross_Worker_Command**: Comando remoto (check_update, analyze_log, get_latest_log, etc.) que debe llegar a una workstation que puede estar conectada en cualquier worker
- **Forced_Contingency_Broadcast**: Mensaje que debe llegar a TODAS las workstations de una organización independientemente del worker donde estén conectadas
- **Hot_Path**: Secuencia de operaciones ejecutada durante el registro de cada workstation (actualmente 8-12 queries a BD)

## Requirements

### Requirement 1: Redis Pub/Sub como Broker Inter-Worker

**User Story:** Como administrador del sistema, quiero que los workers uvicorn se comuniquen entre sí via Redis pub/sub, para que los comandos y broadcasts lleguen a todas las workstations independientemente del worker donde estén conectadas.

#### Acceptance Criteria

1. WHEN a Cross_Worker_Command is sent to a workstation that is not connected to the current Worker, THE Redis_Broker SHALL publish the command to the Redis channel `ws:{workstation_id}` within 100ms of the send request
2. WHEN a Worker receives a message on a subscribed workstation channel `ws:{workstation_id}`, THE Connection_Manager SHALL deliver the message to the local WebSocket connection within 100ms if the workstation is connected to that Worker
3. WHEN a Forced_Contingency_Broadcast is triggered for an organization, THE Redis_Broker SHALL publish the message to the Redis channel `org:{organization_id}` so all Workers with workstations of that organization receive it
4. WHEN a Worker receives a message on an organization channel `org:{organization_id}`, THE Connection_Manager SHALL deliver the message to all locally-connected workstations whose `org_id` matches the organization_id within 500ms
5. WHEN a Worker starts, THE Connection_Manager SHALL subscribe to a global control channel `global:broadcast` for system-wide broadcasts and confirm subscription before accepting WebSocket connections
6. WHEN a Worker receives a command response from a workstation, THE Redis_Broker SHALL publish the response to channel `cmd_response:{command_id}` so the originating Worker can resolve the pending command waiter within its timeout window
7. IF Redis connection is lost, THEN THE Connection_Manager SHALL continue serving locally-connected workstations without interruption and retry Redis connection with exponential backoff starting at 1 second, doubling per attempt, up to a maximum interval of 30 seconds
8. IF a message is published to a workstation channel and no Worker has that workstation connected locally, THEN THE Connection_Manager SHALL discard the message without error and log the event at debug level
9. WHEN a workstation WebSocket connects to a Worker, THE Connection_Manager SHALL subscribe to the Redis channel `ws:{workstation_id}` for that workstation, and WHEN the WebSocket disconnects, THE Connection_Manager SHALL unsubscribe from that channel within 5 seconds

### Requirement 2: Multi-Worker Uvicorn

**User Story:** Como administrador del sistema, quiero ejecutar múltiples workers uvicorn, para que el backend pueda distribuir la carga de 8100 conexiones WebSocket entre procesos independientes.

#### Acceptance Criteria

1. THE Backend SHALL run with a minimum of 2 uvicorn workers in the DEV environment
2. WHEN a new WebSocket connection is established, THE Worker handling that connection SHALL register the workstation_id in a Redis set associated with its own worker_id, indicating which worker owns that connection
3. WHEN a Worker shuts down gracefully (receives SIGTERM), THE Connection_Manager SHALL remove all its workstation registrations from Redis and close connections with code 1001 before the process exits
4. THE Backend SHALL support scaling to 4 workers without code changes (configuration only)
5. WHEN the Backend starts with multiple workers, THE Death_Ping loop SHALL run independently per worker, only pinging locally-connected workstations
6. IF a Worker crashes or becomes unresponsive without executing graceful shutdown, THEN THE remaining Workers SHALL detect stale registrations via Redis key expiry (TTL no greater than 60 seconds) and discard routing attempts to the dead worker's workstations

### Requirement 3: Cache de Registro en Redis

**User Story:** Como administrador del sistema, quiero cachear en Redis los datos frecuentemente consultados durante el registro de workstations, para reducir la latencia de registro de >3 segundos a menos de 500ms.

#### Acceptance Criteria

1. WHEN a workstation registers and organization data exists in Redis with a non-expired TTL, THE Registration_Cache SHALL serve organization data from Redis cache without querying PostgreSQL (TTL configurable between 1 and 60 minutes, default 5 minutes)
2. WHEN a workstation registers and VLAN data exists in Redis with a non-expired TTL, THE Registration_Cache SHALL serve VLAN data from Redis cache without querying PostgreSQL, using the same configured TTL as organization data
3. WHEN a workstation registers and effective configuration exists in Redis with a non-expired TTL, THE Registration_Cache SHALL serve effective configuration from Redis cache without querying PostgreSQL, using the same configured TTL as organization data
4. WHEN a workstation registers and forced contingency state exists in Redis with a non-expired TTL, THE Registration_Cache SHALL serve forced contingency state from Redis cache without querying PostgreSQL, using the same configured TTL as organization data
5. WHEN cached data is not found in Redis for a registering workstation, THE Registration_Cache SHALL query PostgreSQL, store the result in Redis with the configured TTL, and return the data to the registration flow
6. IF PostgreSQL is unreachable or returns an error during a cache-miss query, THEN THE Registration_Cache SHALL return an error response indicating the data source is unavailable and SHALL NOT store any value in Redis
7. IF Redis is unreachable during a workstation registration, THEN THE Registration_Cache SHALL fall back to querying PostgreSQL directly and return the data without caching
8. WHEN an organization or VLAN configuration is modified via the API, THE Registration_Cache SHALL invalidate all Redis cache entries associated with the modified organization or VLAN within 1 second of the modification
9. THE Hot_Path SHALL complete workstation registration in less than 500ms for cached data at the p95 percentile, measured over a rolling window of 1000 registration requests

### Requirement 4: Optimización del Hot Path de Registro

**User Story:** Como administrador del sistema, quiero eliminar operaciones bloqueantes y queries redundantes del flujo de registro, para que cada conexión consuma menos recursos del worker.

#### Acceptance Criteria

1. THE Backend SHALL replace all blocking print() calls in the WebSocket handler with non-blocking structured logging that includes timestamp, level, and workstation_id as key-value fields
2. WHEN a workstation registers, THE Backend SHALL execute database queries using run_in_executor or an async database driver so that no synchronous I/O blocks the asyncio event loop for more than 5 milliseconds
3. THE Backend SHALL use a connection pool with DB_POOL_SIZE defaulting to 30 and DB_MAX_OVERFLOW defaulting to 10, both configurable via environment variables
4. WHEN multiple workstations from the same organization register within a 60-second window, THE Registration_Cache SHALL serve cached organization and PublicIP data with a TTL of 60 seconds, resulting in at most 1 PostgreSQL query per organization per TTL period
5. THE Backend SHALL resolve the forced contingency state (Organization.forced_contingency, VLAN.forced_contingency, Workstation.forced_contingency) in a single database round-trip using a joined or subquery load instead of 3 sequential queries
6. IF the Registration_Cache is unavailable or returns an error, THEN THE Backend SHALL fall back to direct database queries and log a warning indicating cache failure

### Requirement 5: Tenant Isolation en Entorno Multi-Worker

**User Story:** Como administrador del sistema, quiero que el aislamiento por tenant se mantenga en el entorno multi-worker, para que ninguna organización pueda recibir datos de otra.

#### Acceptance Criteria

1. WHEN the Redis_Broker publishes to an organization channel, THE channel name SHALL include the organization_id to prevent cross-tenant message delivery
2. THE Registration_Cache SHALL namespace all cache keys by organization_id, including organization data, VLAN data, effective configuration, and forced contingency state
3. WHEN a Worker delivers a broadcast message, THE Connection_Manager SHALL verify that the receiving workstation belongs to the target organization by checking the workstation's registered organization_id before delivering the message
4. IF a workstation_id is claimed by a Worker but belongs to a different organization than the message target, THEN THE Connection_Manager SHALL discard the message and log a security warning that includes the workstation_id, the workstation's organization_id, and the target organization_id
5. WHEN a Worker delivers a Cross_Worker_Command to an individual workstation, THE Connection_Manager SHALL verify that the command's originating organization_id matches the workstation's registered organization_id before delivering the command
6. IF the Connection_Manager cannot determine the organization membership of a workstation at delivery time, THEN THE Connection_Manager SHALL discard the message and log a security warning indicating that tenant validation failed

### Requirement 6: Compatibilidad del Protocolo WebSocket

**User Story:** Como administrador del sistema, quiero que el protocolo WebSocket hacia el cliente C# permanezca sin cambios, para que no sea necesario actualizar el software en las 8100 workstations.

#### Acceptance Criteria

1. THE Backend SHALL maintain the same WebSocket endpoint path (/ws/workstation) with no changes to query parameters or required headers for the handshake
2. THE Backend SHALL maintain the same JSON message structure (field names, field types, and nesting) for all existing message types: register, registered, config_update, forced_contingency, ping, pong, status_update, command, command_result, telemetry, connectivity_result, message, request_reregister, and error
3. THE Backend SHALL maintain the same WebSocket close codes for all error scenarios: 1008 for policy violations (unauthorized IP, inactive organization, invalid registration), 1011 for unexpected server errors, 1001 for graceful server shutdown, and 1000 for normal closure (e.g., re-registro requerido)
4. THE Backend SHALL maintain the same registration flow sequence: accept connection → receive register message → validate credentials → respond with registered message → send config_update → send forced_contingency (with enabled=true or enabled=false) → send pending messages
5. IF a workstation previously registered on Worker A reconnects and is assigned to Worker B, THEN THE Backend SHALL complete the registration flow identically to a fresh connection without requiring client-side changes

### Requirement 7: Configuración para Entorno DEV

**User Story:** Como administrador del sistema, quiero que toda la configuración de Redis y multi-worker sea activable por variables de entorno, para que el despliegue en DEV no afecte PROD.

#### Acceptance Criteria

1. THE Backend SHALL read Redis connection URL from the REDIS_URL environment variable (already defined in Settings)
2. THE Backend SHALL read the number of uvicorn workers from an environment variable (UVICORN_WORKERS, default 1)
3. WHEN REDIS_URL is not configured, THE Backend SHALL operate in single-worker mode with the existing in-memory Connection_Manager (backward compatible)
4. THE docker-compose configuration SHALL connect the backend container to the existing Redis service via the internal Docker network
5. THE Backend SHALL expose a health check endpoint that reports Redis connectivity status and per-worker connection counts

### Requirement 8: Capacidad y Rendimiento

**User Story:** Como administrador del sistema, quiero que el sistema soporte 8100 conexiones WebSocket simultáneas con latencia aceptable, para que todas las workstations de la organización puedan operar sin degradación.

#### Acceptance Criteria

1. THE Backend SHALL sustain 8100 concurrent WebSocket connections distributed across all workers without connection failures
2. WHEN 8100 workstations are connected simultaneously, THE Backend SHALL maintain registration latency below 500ms at p95
3. WHEN 8100 workstations are connected simultaneously, THE Backend SHALL deliver Cross_Worker_Commands within 200ms of publication to Redis
4. WHEN 8100 workstations are connected simultaneously, THE Backend SHALL deliver Forced_Contingency_Broadcasts to all workstations of an organization within 2 seconds
5. THE Backend SHALL consume less than 1.8 GB of RAM total across all workers when handling 8100 connections (leaving headroom on the 2 GB t3.small instance)
