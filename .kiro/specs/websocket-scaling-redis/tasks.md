# Implementation Plan: WebSocket Scaling con Redis

## Overview

Transformar el backend de single-worker con estado en memoria a multi-worker con Redis pub/sub y cache de registro. La implementación sigue un enfoque incremental: primero la infraestructura (config, logging, pool), luego los componentes core (RedisConnectionManager, RegistrationCache, WorkerRegistry), después la integración con el handler existente, y finalmente el despliegue multi-worker.

## Tasks

- [x] 1. Configuración base y dependencias
  - [x] 1.1 Agregar variables de entorno y settings al config
    - Agregar a `app/core/config.py`: UVICORN_WORKERS (default 1), WS_REDIS_RECONNECT_MAX_INTERVAL (default 30), WORKER_REGISTRY_TTL (default 60), WS_DEBUG_LOGGING (default true), WS_LOG_TIMING (default true)
    - Actualizar DB_POOL_SIZE default a 30
    - _Requirements: 7.1, 7.2, 7.3, 4.3_

  - [x] 1.2 Configurar structlog y reemplazar print() en el WebSocket handler
    - Instalar y configurar `structlog` en `app/core/logging.py` (nuevo archivo)
    - Reemplazar TODOS los `print()` en `app/api/v1/websocket/workstation.py` con structlog calls incluyendo worker_id, workstation_id, timestamp
    - Configurar formato key-value con niveles y contexto
    - _Requirements: 4.1_

  - [x] 1.3 Optimizar pool de conexiones de BD
    - Modificar `app/core/database.py` para usar DB_POOL_SIZE=30 y DB_MAX_OVERFLOW=10 desde settings
    - Verificar que el engine recibe los parámetros correctamente para PostgreSQL
    - _Requirements: 4.3_

- [x] 2. Checkpoint - Verificar que el backend arranca correctamente con structlog y pool optimizado
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Implementar WorkerRegistry
  - [x] 3.1 Crear clase WorkerRegistry
    - Crear `app/services/worker_registry.py`
    - Implementar: register_workstation, unregister_workstation, heartbeat (renueva TTL), cleanup_on_shutdown, find_worker_for_workstation
    - Usar Redis SET `workers:{worker_id}:workstations` con TTL configurable (default 60s)
    - Incluir heartbeat key `workers:{worker_id}:heartbeat` con TTL
    - Fallback graceful si Redis no disponible
    - _Requirements: 2.2, 2.3, 2.6_

  - [x] 3.2 Write property test for WorkerRegistry lifecycle (Property 10)
    - **Property 10: Worker Registry Lifecycle**
    - **Validates: Requirements 2.2, 2.3**
    - Verificar que tras connect, workstation_id aparece en el SET; tras disconnect, no aparece; tras graceful_shutdown, SET vacío

- [x] 4. Implementar RegistrationCache
  - [x] 4.1 Crear clase RegistrationCache
    - Crear `app/services/registration_cache.py`
    - Implementar: get_organization_data, get_vlan_data, get_effective_config, get_forced_contingency_state
    - Implementar: invalidate_organization, invalidate_vlan
    - Namespace todas las keys por organization_id: `cache:org:{org_id}:data`, `cache:org:{org_id}:public_ips`, `cache:vlan:{vlan_id}:data`, `cache:config:{ws_id}:effective`, `cache:contingency:{ws_id}:state`
    - TTL configurable desde CACHE_TTL_SECONDS (default 300)
    - Fallback a PostgreSQL si Redis no disponible
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 5.2_

  - [x] 4.2 Write property test for cache key namespacing (Property 4)
    - **Property 4: Cache Key Namespacing by Organization**
    - **Validates: Requirements 5.2**
    - Verificar que toda key generada por RegistrationCache contiene el organization_id como namespace

  - [x] 4.3 Write property test for cache hit eliminates DB query (Property 5)
    - **Property 5: Cache Hit Eliminates Database Query**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
    - Verificar que si datos existen en Redis con TTL válido, no se ejecuta query a PostgreSQL

  - [x] 4.4 Write property test for cache miss round-trip (Property 6)
    - **Property 6: Cache Miss Round-Trip**
    - **Validates: Requirements 3.5**
    - Verificar que tras cache miss se consulta BD, se almacena en Redis, y la siguiente llamada es cache hit

  - [x] 4.5 Write property test for cache invalidation (Property 7)
    - **Property 7: Cache Invalidation on Modification**
    - **Validates: Requirements 3.8**
    - Verificar que tras invalidate_organization/invalidate_vlan, las keys relacionadas se eliminan de Redis

- [x] 5. Implementar RedisConnectionManager
  - [x] 5.1 Crear clase RedisConnectionManager
    - Crear `app/services/redis_connection_manager.py`
    - Estado local: workstation_connections, operator_connections, last_pong, last_activity, org_ids (mismo que ConnectionManager actual)
    - Redis: _redis client, _pubsub, _listener_task, _redis_available flag
    - Worker identity: _worker_id = f"worker_{os.getpid()}"
    - Implementar initialize(): conectar Redis, suscribir global:broadcast, iniciar listener task
    - Implementar connect_workstation(): registrar local + suscribir ws:{workstation_id} + registrar en WorkerRegistry
    - Implementar disconnect_workstation(): limpiar local + desuscribir canal + unregister de WorkerRegistry
    - Implementar send_to_workstation(): local si está aquí, PUBLISH a ws:{workstation_id} si no
    - Implementar broadcast_to_organization(): enviar a locales + PUBLISH a org:{organization_id}
    - Implementar _redis_listener(): loop async que procesa mensajes pub/sub entrantes
    - Implementar _handle_redis_reconnect(): exponential backoff 1s→2s→4s→8s→16s→30s max
    - Mantener graceful_shutdown_workstations() con close code 1001 + cleanup_on_shutdown de WorkerRegistry
    - Mantener command waiters (register_command_waiter, resolve_command_response, wait_for_command_response) + pub/sub en cmd_response:{command_id}
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.3_

  - [x] 5.2 Implementar validación de tenant isolation en RedisConnectionManager
    - En _deliver_command: verificar command.organization_id == workstation.org_id antes de entregar
    - En broadcast delivery: verificar workstation pertenece a target organization
    - Discard + log security warning si no coincide
    - Discard + log si org_id no determinable
    - _Requirements: 5.1, 5.3, 5.4, 5.5, 5.6_

  - [x] 5.3 Write property test for message routing (Property 1)
    - **Property 1: Message Routing to Correct Channel**
    - **Validates: Requirements 1.1, 1.3, 1.6**
    - Verificar que send_to_workstation publica en ws:{id}, broadcast en org:{id}, command response en cmd_response:{id}

  - [x] 5.4 Write property test for local delivery matching (Property 2)
    - **Property 2: Local Delivery Only to Matching Connections**
    - **Validates: Requirements 1.2, 1.4, 5.3**
    - Verificar que mensajes solo se entregan a conexiones que matchean el canal target

  - [x] 5.5 Write property test for tenant isolation (Property 3)
    - **Property 3: Tenant Isolation at Command Delivery**
    - **Validates: Requirements 5.4, 5.5**
    - Verificar que comando se entrega sii command.org_id == ws.org_id

  - [x] 5.6 Write property test for pub/sub lifecycle symmetry (Property 9)
    - **Property 9: Connection Lifecycle Pub/Sub Symmetry**
    - **Validates: Requirements 1.9**
    - Verificar que canales suscritos == workstation_ids conectados localmente en todo momento

  - [x] 5.7 Write property test for graceful fallback (Property 8)
    - **Property 8: Graceful Fallback When Redis Unavailable**
    - **Validates: Requirements 1.7, 3.7, 4.6**
    - Verificar que operaciones completan sin error cuando Redis es unreachable

- [x] 6. Checkpoint - Verificar que los 3 componentes (WorkerRegistry, RegistrationCache, RedisConnectionManager) funcionan unitariamente
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implementar factory y backward compatibility
  - [x] 7.1 Crear factory para ConnectionManager
    - Modificar `app/services/websocket_manager.py`: crear función `create_connection_manager()` que retorne RedisConnectionManager si REDIS_URL está configurado, o ConnectionManager in-memory si no
    - Mantener `connection_manager` como variable global instanciada por la factory
    - Asegurar que la interfaz pública es idéntica (duck typing o protocol)
    - _Requirements: 7.3_

  - [x] 7.2 Write property test for in-memory mode (Property 14)
    - **Property 14: In-Memory Mode Without Redis**
    - **Validates: Requirements 7.3**
    - Verificar que con REDIS_URL=None el sistema usa in-memory sin intentar conexión Redis

- [x] 8. Integrar con el WebSocket handler
  - [x] 8.1 Integrar RegistrationCache en el flujo de registro
    - Modificar `app/api/v1/websocket/workstation.py` para usar RegistrationCache en vez de queries directas para: organization data, VLAN data, effective config, forced contingency state
    - Ejecutar queries sync restantes (register_workstation) en run_in_executor para no bloquear event loop
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 4.2, 4.4_

  - [x] 8.2 Optimizar resolución de contingencia forzada a single query
    - Crear query JOIN que resuelva Organization.forced_contingency + VLAN.forced_contingency + Workstation.forced_contingency en un solo round-trip
    - Reemplazar las 3 queries secuenciales actuales en el handler
    - Cachear resultado en RegistrationCache
    - _Requirements: 4.5_

  - [x] 8.3 Write property test for contingency equivalence (Property 12)
    - **Property 12: Single-Query Contingency Equivalence**
    - **Validates: Requirements 4.5**
    - Verificar que la query optimizada produce el mismo resultado (enabled, source, source_name, printer_ip) que el enfoque secuencial actual para todas las combinaciones de flags

  - [x] 8.4 Integrar RedisConnectionManager en el startup de la app
    - Modificar `app/main.py`: llamar `connection_manager.initialize()` en startup event
    - Configurar ping loop para que solo ping workstations locales
    - Registrar graceful shutdown en SIGTERM handler
    - _Requirements: 1.5, 2.3, 2.5_

  - [x] 8.5 Write property test for ping loop isolation (Property 11)
    - **Property 11: Ping Loop Isolation**
    - **Validates: Requirements 2.5**
    - Verificar que el Death Ping solo envía pings a workstations localmente conectadas

  - [x] 8.6 Write property test for worker-independent registration (Property 13)
    - **Property 13: Worker-Independent Registration Result**
    - **Validates: Requirements 6.5**
    - Verificar que la secuencia de mensajes (registered, config_update, forced_contingency, pending_messages) es idéntica independientemente del worker

- [x] 9. Checkpoint - Verificar integración completa en modo single-worker con Redis
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Implementar cache invalidation hooks en la API
  - [x] 10.1 Agregar invalidación de cache en endpoints de modificación
    - Identificar endpoints que modifican organización o VLAN (ej: update_organization, update_vlan, toggle_forced_contingency)
    - Llamar RegistrationCache.invalidate_organization() o invalidate_vlan() tras cada modificación exitosa
    - Asegurar que la invalidación ocurre dentro de 1 segundo de la modificación
    - _Requirements: 3.8_

- [x] 11. Implementar health check detallado
  - [x] 11.1 Crear endpoint /api/v1/health/detailed
    - Reportar: status, redis connectivity + latency, worker_id, connection counts (workstations, operators), cache hit ratio, registration p95 latency, memory_mb, uptime_seconds
    - Implementar en `app/api/v1/endpoints/health.py` o archivo apropiado
    - _Requirements: 7.5_

- [x] 12. Configurar despliegue multi-worker
  - [x] 12.1 Modificar user_data.sh.tpl para multi-worker
    - Cambiar comando uvicorn en docker-compose: `uvicorn app.main:app --host 0.0.0.0 --port ${backend_port} --workers ${UVICORN_WORKERS:-2} --ws-ping-interval 300 --ws-ping-timeout 300`
    - Agregar REDIS_URL=redis://redis:6379/0 al .env del backend
    - Agregar UVICORN_WORKERS=2 al .env del backend
    - Asegurar que backend depende de redis en docker-compose y comparten red
    - _Requirements: 2.1, 2.4, 7.2, 7.4_

  - [x] 12.2 Verificar compatibilidad del protocolo WebSocket
    - Verificar que el endpoint path /ws/workstation no cambia
    - Verificar que los JSON message types mantienen misma estructura
    - Verificar close codes: 1008, 1011, 1001, 1000
    - Verificar secuencia de registro: accept → register → registered → config_update → forced_contingency → pending messages
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

- [x] 13. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (14 properties total)
- Unit tests validate specific examples and edge cases
- The existing load test at `AlwaysPrintProject/Cloud/load-test.py` can validate performance requirements (8.1-8.5) after deployment
- `structlog` debe instalarse como dependencia (`pip install structlog`)
- `redis[hiredis]` (aioredis es parte de redis-py >= 4.2) debe instalarse como dependencia
- El RedisConnectionManager mantiene la misma interfaz pública que ConnectionManager para backward compatibility

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["3.1", "4.1"] },
    { "id": 2, "tasks": ["3.2", "4.2", "4.3", "4.4", "4.5", "5.1"] },
    { "id": 3, "tasks": ["5.2", "5.3", "5.4", "5.5", "5.6", "5.7"] },
    { "id": 4, "tasks": ["7.1"] },
    { "id": 5, "tasks": ["7.2", "8.1", "8.2"] },
    { "id": 6, "tasks": ["8.3", "8.4"] },
    { "id": 7, "tasks": ["8.5", "8.6", "10.1", "11.1"] },
    { "id": 8, "tasks": ["12.1", "12.2"] }
  ]
}
```
