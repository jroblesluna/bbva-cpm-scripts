# Requirements Document

## Introduction

Re-introducción de multi-worker con Redis pub/sub para el backend de AlwaysPrint Cloud, sin el componente RegistrationCache que causó exhaustión del pool de conexiones PostgreSQL. El objetivo es soportar 2 uvicorn workers coordinados vía Redis (RedisConnectionManager + WorkerRegistry) manteniendo la estrategia de queries directas a BD (ConfigService + inline queries) que demostró estabilidad con 1500+ WebSockets en un solo worker.

La meta operativa es 1000 workstations (500/worker) en una instancia t3.small (2 GB RAM, 2 vCPU) con RDS db.t3.micro (max_connections=81), latencia < 500ms y cero exhaustión de pool.

## Glossary

- **Backend**: Aplicación FastAPI que sirve la API REST y endpoints WebSocket de AlwaysPrint Cloud
- **Worker**: Proceso uvicorn independiente que ejecuta una instancia del Backend
- **RedisConnectionManager**: Gestor de conexiones WebSocket con coordinación inter-worker via Redis pub/sub (ya implementado)
- **ConnectionManager**: Gestor de conexiones WebSocket in-memory sin Redis (implementación de un solo worker)
- **WorkerRegistry**: Componente que registra qué workstations están en qué worker usando Redis SETs con TTL (ya implementado)
- **RegistrationCache**: Componente de caché en Redis para config/contingencia que causa exhaustión de pool (NO debe usarse)
- **ConfigService**: Servicio que consulta configuración efectiva directamente desde PostgreSQL
- **WebSocket_Endpoint**: El endpoint `/ws/workstation` que gestiona el ciclo de vida de conexiones de Tray Clients
- **Pool_DB**: Pool de conexiones SQLAlchemy hacia PostgreSQL/RDS
- **SessionLocal**: Factory de sesiones SQLAlchemy que crea sesiones cortas on-demand
- **Death_Ping**: Mecanismo selectivo de ping para detección de conexiones muertas por inactividad
- **Consolidated_Channels**: Esquema de canales Redis: `worker:{id}`, `org:{org_id}`, `global:broadcast`
- **Graceful_Shutdown**: Proceso de cierre ordenado que notifica a workstations antes de detener el worker

## Requirements

### Requirement 1: Activación de RedisConnectionManager como gestor de conexiones

**User Story:** Como operador del sistema, quiero que el backend utilice RedisConnectionManager en lugar de ConnectionManager cuando REDIS_URL está configurado, para que múltiples workers se coordinen via Redis pub/sub.

#### Acceptance Criteria

1. WHEN REDIS_URL está configurado en el entorno, THE Backend SHALL instanciar RedisConnectionManager como el connection_manager global en lugar de ConnectionManager
2. WHEN REDIS_URL no está configurado, THE Backend SHALL instanciar ConnectionManager (modo single-worker) como fallback
3. WHEN el Backend arranca con RedisConnectionManager, THE Backend SHALL invocar `connection_manager.initialize()` durante el lifespan startup para conectar a Redis y suscribir canales consolidados
4. THE Backend SHALL exponer la misma interfaz pública (connect_workstation, disconnect_workstation, send_to_workstation, broadcast_to_organization, handle_pong, start_ping_loop, graceful_shutdown_workstations) independientemente del manager activo

### Requirement 2: Configuración de uvicorn multi-worker

**User Story:** Como ingeniero de infraestructura, quiero ejecutar 2 workers uvicorn para aprovechar los 2 vCPU de la instancia t3.small y distribuir la carga de WebSockets.

#### Acceptance Criteria

1. THE Backend SHALL soportar una variable de entorno UVICORN_WORKERS con valor por defecto 1
2. WHEN UVICORN_WORKERS es mayor a 1, THE Backend SHALL requerir que REDIS_URL esté configurado para coordinación inter-worker
3. THE Backend SHALL arrancar uvicorn con el número de workers indicado por UVICORN_WORKERS en el comando de despliegue
4. WHILE se ejecutan múltiples workers, THE Backend SHALL generar un worker_id único por proceso (basado en PID) para identificación en Redis

### Requirement 3: Exclusión absoluta de RegistrationCache

**User Story:** Como ingeniero de backend, quiero garantizar que RegistrationCache no se use en ningún flujo, para evitar la regresión de exhaustión de pool "idle in transaction" confirmada en load testing.

#### Acceptance Criteria

1. THE WebSocket_Endpoint SHALL obtener configuración efectiva exclusivamente vía ConfigService.get_effective_config(db, workstation_id) con queries directas a PostgreSQL
2. THE WebSocket_Endpoint SHALL resolver datos de contingencia mediante queries inline a las tablas Organization, VLAN, Device y Workstation
3. THE Backend SHALL no importar ni instanciar el módulo registration_cache en ningún archivo de producción relacionado con el flujo WebSocket
4. IF RegistrationCache es importado en un archivo del flujo WebSocket, THEN THE Backend SHALL fallar la validación de código (linter/test de importaciones prohibidas)

### Requirement 4: Gestión de sesiones de BD sin retención durante awaits

**User Story:** Como ingeniero de backend, quiero que cada operación de BD use sesiones cortas (SessionLocal) que se cierren inmediatamente después del uso, para que los awaits de WebSocket no retengan conexiones del pool.

#### Acceptance Criteria

1. THE WebSocket_Endpoint SHALL cerrar la sesión de BD (db.close()) después de completar el bloque de setup inicial (registro, config, contingencia, mensajes pendientes)
2. WHILE el WebSocket_Endpoint espera mensajes en el loop (receive_json), THE WebSocket_Endpoint SHALL no retener ninguna sesión de BD abierta
3. WHEN un mensaje llega en el loop, THE WebSocket_Endpoint SHALL crear una nueva sesión vía SessionLocal(), procesar el mensaje, y cerrar la sesión antes del siguiente await
4. THE WebSocket_Endpoint SHALL no utilizar Depends(get_db) para sesiones que persistan durante toda la vida de la conexión WebSocket en el loop de mensajes

### Requirement 5: Configuración del pool de BD para multi-worker

**User Story:** Como ingeniero de infraestructura, quiero que el pool de BD esté configurado para operar dentro de los límites de RDS db.t3.micro (max_connections=81) con 2 workers.

#### Acceptance Criteria

1. THE Backend SHALL configurar DB_POOL_SIZE=20 por worker (40 total con 2 workers)
2. THE Backend SHALL configurar DB_MAX_OVERFLOW=10 por worker (máximo 30 por worker bajo burst, 60 total en peor caso)
3. THE Backend SHALL configurar DB_POOL_TIMEOUT=30 para que requests esperen por una conexión disponible antes de fallar
4. THE Backend SHALL configurar DB_POOL_RECYCLE=1800 para evitar conexiones stale por timeout de RDS
5. WHILE operan 2 workers, THE Pool_DB SHALL no exceder 60 conexiones totales al RDS (dejando 21 conexiones libres de las 81 disponibles)

### Requirement 6: Rendimiento bajo carga target

**User Story:** Como operador del sistema, quiero que el backend soporte 1000 workstations simultáneas (500/worker) con latencia aceptable y sin degradación del pool de BD.

#### Acceptance Criteria

1. WHILE 1000 workstations están conectadas simultáneamente, THE Backend SHALL responder al registro de cada workstation en menos de 500ms (P95)
2. WHILE 1000 workstations están conectadas simultáneamente, THE Pool_DB SHALL mantener cero sesiones en estado "idle in transaction" por más de 5 segundos
3. WHEN se ejecuta un ramp-up de conexiones con intervalo de 0.1s, THE Backend SHALL aceptar todas las conexiones sin errores de pool exhaustion (QueuePool limit overflow)
4. WHILE 1000 workstations están conectadas, THE Backend SHALL consumir menos de 1.5 GB de memoria RSS total (2 workers combinados) para operar dentro de los 2 GB de la t3.small

### Requirement 7: Redis listener sin bloqueo de nuevas conexiones

**User Story:** Como ingeniero de backend, quiero que el listener de Redis pub/sub no bloquee la aceptación de nuevas conexiones WebSocket, para mantener throughput durante ramp-up.

#### Acceptance Criteria

1. THE RedisConnectionManager SHALL ejecutar el _redis_listener como una asyncio.Task independiente que no comparte el event loop con la aceptación de WebSocket handshakes
2. WHEN el _redis_listener hace sleep(0.5s) entre ciclos de lectura, THE Backend SHALL continuar aceptando nuevas conexiones WebSocket sin delay adicional
3. IF Redis se desconecta durante operación, THEN THE RedisConnectionManager SHALL continuar operando en modo local (fallback graceful) sin interrumpir conexiones activas
4. WHEN Redis se reconecta, THE RedisConnectionManager SHALL restaurar suscripciones a canales consolidados y re-registrar workstations en WorkerRegistry

### Requirement 8: Shutdown graceful multi-worker

**User Story:** Como ingeniero de infraestructura, quiero que cada worker realice un shutdown ordenado que limpie su estado en Redis y notifique a las workstations, para evitar workstations "fantasma" en el registro.

#### Acceptance Criteria

1. WHEN un worker recibe señal de terminación (SIGTERM), THE Backend SHALL ejecutar graceful_shutdown_workstations() enviando close frame con código 1001 a todas las workstations locales
2. WHEN un worker se detiene, THE WorkerRegistry SHALL ejecutar cleanup_on_shutdown() eliminando el SET de workstations y el heartbeat key de Redis
3. WHEN un worker crashea sin cleanup, THE WorkerRegistry SHALL detectar la muerte vía expiración del TTL del heartbeat key
4. THE Backend SHALL ejecutar la limpieza inicial al arrancar (marcar offline workstations sin conexión activa) para recuperar estado consistente tras un crash

### Requirement 9: Compatibilidad con tests de propiedades existentes

**User Story:** Como ingeniero de QA, quiero que los 15 property tests existentes de redis-pubsub-channel-consolidation sigan pasando sin modificación, para garantizar que la integración no rompe el comportamiento verificado.

#### Acceptance Criteria

1. THE Backend SHALL mantener el esquema de canales consolidados (worker:{id}, org:{org_id}, global:broadcast) sin modificaciones
2. WHEN se ejecutan los property tests de redis-pubsub-channel-consolidation, THE Backend SHALL pasar los 15 tests sin fallos
3. THE RedisConnectionManager SHALL mantener la interfaz de connect_workstation con soporte para vlan_id como parámetro opcional
4. THE WorkerRegistry SHALL mantener la interfaz existente (register_workstation, unregister_workstation, heartbeat, cleanup_on_shutdown, find_worker_for_workstation)

### Requirement 10: Integración del factory websocket_manager con selección condicional

**User Story:** Como ingeniero de backend, quiero que el módulo websocket_manager.py actúe como factory que selecciona el manager correcto según la configuración, para que el resto del código use `connection_manager` de forma transparente.

#### Acceptance Criteria

1. THE Backend SHALL definir en websocket_manager.py una instancia global `connection_manager` que sea RedisConnectionManager cuando REDIS_URL está presente, o ConnectionManager cuando no lo está
2. WHEN el código importa `from app.services.websocket_manager import connection_manager`, THE Backend SHALL proveer el manager correcto sin que el código consumidor necesite saber cuál es
3. THE Backend SHALL asegurar que ambos managers (ConnectionManager y RedisConnectionManager) implementen los métodos: connect_workstation, disconnect_workstation, send_to_workstation, broadcast_to_organization, handle_pong, update_last_activity, start_ping_loop, stop_ping_loop, graceful_shutdown_workstations, get_online_workstations, get_connection_count, register_command_waiter, resolve_command_response, wait_for_command_response
