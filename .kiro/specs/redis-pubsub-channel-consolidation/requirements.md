# Requirements Document

## Introduction

Consolidación del esquema de canales Redis pub/sub en el RedisConnectionManager para eliminar el problema O(n) de suscripciones por workstation que degradó la capacidad de 1500 a 45 conexiones concurrentes. El nuevo diseño reduce los canales a tres tipos fijos (`worker:{worker_id}`, `org:{org_id}`, `global:broadcast`), eliminando las suscripciones dinámicas `ws:{workstation_id}` y `cmd_response:{command_id}`.

## Glossary

- **RedisConnectionManager**: Gestor centralizado de conexiones WebSocket con coordinación inter-worker vía Redis pub/sub, ubicado en `app/services/redis_connection_manager.py`
- **WorkerRegistry**: Registro de workstations por worker con TTL para detección de crashes, mantiene el SET `workers:{worker_id}:workstations` en Redis
- **Worker**: Proceso uvicorn individual identificado por `worker_{pid}`, capaz de gestionar múltiples conexiones WebSocket
- **Workstation**: Dispositivo Windows con Tray Client que se conecta vía WebSocket a un worker específico
- **Canal_Worker**: Canal Redis `worker:{worker_id}` que recibe mensajes dirigidos a workstations conectadas a ese worker y respuestas de comandos
- **Canal_Org**: Canal Redis `org:{org_id}` para broadcasts organizacionales, con suscripción lazy
- **Canal_Global**: Canal Redis `global:broadcast` para broadcasts globales a todos los workers
- **Hot_Path**: Secuencia de operaciones ejecutada durante `connect_workstation`, cuyo rendimiento es crítico
- **Lazy_Subscribe**: Patrón de suscripción diferida donde el canal se suscribe solo cuando el primer interesado lo necesita y se desuscribe cuando el último interesado se desconecta
- **Tenant_Isolation**: Validación de que los mensajes solo se entregan a workstations de la misma organización

## Requirements

### Requirement 1: Eliminación de suscripciones por workstation

**User Story:** Como operador de infraestructura, quiero que el sistema no cree una suscripción Redis por cada workstation conectada, para que el número de suscripciones no crezca O(n) con las conexiones y se mantenga la capacidad de 1500+ conexiones concurrentes.

#### Acceptance Criteria

1. THE RedisConnectionManager SHALL mantener un máximo de N_workers + N_orgs_activas + 1 suscripciones Redis activas en cualquier momento, independientemente del número de workstations conectadas.
2. WHEN una workstation se conecta, THE RedisConnectionManager SHALL registrar la workstation en estado local y en WorkerRegistry sin ejecutar ninguna operación SUBSCRIBE de Redis.
3. WHEN una workstation se desconecta, THE RedisConnectionManager SHALL eliminar la workstation del estado local y de WorkerRegistry sin ejecutar ninguna operación UNSUBSCRIBE de Redis específica para esa workstation.
4. THE RedisConnectionManager SHALL eliminar el canal `ws:{workstation_id}` del esquema de canales Redis, dejando de suscribir y publicar en canales con ese prefijo.

### Requirement 2: Canal worker para mensajes dirigidos

**User Story:** Como sistema de gestión, quiero enviar comandos a una workstation específica publicando en el canal del worker que la tiene conectada, para que la entrega sea eficiente sin requerir suscripciones per-workstation.

#### Acceptance Criteria

1. WHEN el RedisConnectionManager se inicializa, THE RedisConnectionManager SHALL suscribir al canal `worker:{worker_id}` donde `worker_id` corresponde al identificador del proceso actual.
2. WHEN se necesita enviar un mensaje a una workstation no conectada localmente, THE RedisConnectionManager SHALL consultar WorkerRegistry para resolver en qué worker está la workstation destino y publicar el mensaje en el canal `worker:{target_worker_id}`.
3. WHEN un mensaje llega por el canal `worker:{worker_id}`, THE RedisConnectionManager SHALL extraer el campo `target_workstation_id` del payload y entregar el mensaje a la workstation correspondiente si está conectada localmente.
4. WHEN un mensaje llega por el canal `worker:{worker_id}` con `target_workstation_id` que no está conectada localmente, THE RedisConnectionManager SHALL descartar el mensaje y registrar un log debug.
5. IF WorkerRegistry no puede resolver el worker destino para una workstation, THEN THE RedisConnectionManager SHALL registrar un log warning y retornar False indicando que el mensaje no se pudo entregar.

### Requirement 3: Respuestas de comandos por canal worker

**User Story:** Como sistema de comandos, quiero que las respuestas de comandos lleguen por el canal worker consolidado en vez de canales dinámicos `cmd_response:{id}`, para eliminar las suscripciones y desuscripciones dinámicas por cada comando.

#### Acceptance Criteria

1. THE RedisConnectionManager SHALL eliminar el canal `cmd_response:{command_id}` del esquema de canales Redis, dejando de suscribir y publicar en canales con ese prefijo.
2. WHEN una workstation responde a un comando en un worker diferente al originador, THE RedisConnectionManager SHALL publicar la respuesta en el canal `worker:{originator_worker_id}` con el campo `type` igual a `cmd_response` y el campo `command_id` correspondiente.
3. WHEN un mensaje llega por el canal `worker:{worker_id}` con campo `type` igual a `cmd_response`, THE RedisConnectionManager SHALL resolver el command waiter correspondiente usando el campo `command_id` del payload.
4. WHEN se registra un command waiter, THE RedisConnectionManager SHALL almacenar el `worker_id` originador junto con el `command_id` sin ejecutar ninguna operación SUBSCRIBE en Redis.
5. WHEN un command waiter expira por timeout, THE RedisConnectionManager SHALL limpiar el waiter del registro interno sin ejecutar ninguna operación UNSUBSCRIBE en Redis.

### Requirement 4: Suscripción lazy a canales organizacionales

**User Story:** Como operador de infraestructura, quiero que el sistema solo se suscriba a canales organizacionales cuando tiene workstations de esa organización conectadas, para minimizar el tráfico pub/sub procesado por cada worker.

#### Acceptance Criteria

1. WHEN la primera workstation de una organización se conecta a un worker, THE RedisConnectionManager SHALL ejecutar SUBSCRIBE al canal `org:{organization_id}`.
2. WHEN la última workstation de una organización se desconecta de un worker, THE RedisConnectionManager SHALL ejecutar UNSUBSCRIBE del canal `org:{organization_id}`.
3. WHILE hay workstations de una organización conectadas localmente, THE RedisConnectionManager SHALL mantener la suscripción activa al canal `org:{organization_id}` de esa organización.
4. THE RedisConnectionManager SHALL mantener un contador interno por organización que rastree cuántas workstations de cada organización están conectadas localmente.

### Requirement 5: Mensajes por VLAN con filtrado local

**User Story:** Como sistema de gestión, quiero enviar mensajes dirigidos a una VLAN específica dentro de una organización, para que solo las workstations pertenecientes a esa VLAN reciban el mensaje.

#### Acceptance Criteria

1. WHEN se publica un mensaje con campo `target_vlan_id` en el canal `org:{organization_id}`, THE RedisConnectionManager SHALL entregar el mensaje solo a las workstations locales cuyo `vlan_id` coincida con `target_vlan_id`.
2. WHEN se recibe un mensaje organizacional con campo `target_vlan_id` y no hay workstations locales de esa VLAN, THE RedisConnectionManager SHALL descartar el mensaje sin error.
3. THE RedisConnectionManager SHALL mantener el `vlan_id` de cada workstation conectada en el estado local junto con el `organization_id`.

### Requirement 6: Zero Redis roundtrips en connect_workstation

**User Story:** Como desarrollador, quiero que el hot path de conexión de workstations no realice operaciones Redis sincrónicas, para que la latencia de conexión no se vea afectada por la latencia de Redis.

#### Acceptance Criteria

1. WHEN una workstation se conecta, THE Hot_Path SHALL completar el registro local (diccionarios en memoria) sin ejecutar ninguna operación await contra Redis.
2. WHEN una workstation se conecta, THE RedisConnectionManager SHALL delegar las operaciones Redis (registro en WorkerRegistry, lazy subscribe organizacional) como tareas fire-and-forget que no bloquean la respuesta al cliente.
3. IF una tarea fire-and-forget de Redis falla durante la conexión, THEN THE RedisConnectionManager SHALL registrar un log warning y continuar operando sin interrumpir la conexión de la workstation.

### Requirement 7: Fallback graceful sin Redis

**User Story:** Como operador de infraestructura, quiero que el sistema siga funcionando localmente cuando Redis no está disponible, para garantizar continuidad de servicio.

#### Acceptance Criteria

1. WHILE Redis no está disponible, THE RedisConnectionManager SHALL entregar mensajes solo a workstations conectadas localmente sin intentar publicar en Redis.
2. WHILE Redis no está disponible, THE RedisConnectionManager SHALL omitir operaciones de suscripción lazy organizacional sin generar errores.
3. WHEN Redis se restaura tras una desconexión, THE RedisConnectionManager SHALL re-suscribir el canal `worker:{worker_id}`, el canal `global:broadcast`, y los canales `org:{org_id}` de las organizaciones con workstations conectadas localmente.
4. WHEN Redis se restaura tras una desconexión, THE RedisConnectionManager SHALL re-registrar todas las workstations locales en WorkerRegistry.

### Requirement 8: Tenant isolation en entrega de mensajes

**User Story:** Como responsable de seguridad, quiero que los mensajes solo se entreguen a workstations de la organización correcta, para garantizar aislamiento entre tenants.

#### Acceptance Criteria

1. WHEN un mensaje llega por el canal `worker:{worker_id}` con campo `organization_id`, THE RedisConnectionManager SHALL validar que el `organization_id` del mensaje coincide con el `organization_id` registrado para la workstation destino antes de entregar.
2. IF la validación de tenant isolation falla para un mensaje dirigido, THEN THE RedisConnectionManager SHALL descartar el mensaje y registrar un log warning con los IDs involucrados.
3. WHEN un mensaje llega por el canal `org:{organization_id}`, THE RedisConnectionManager SHALL entregar solo a workstations cuyo `organization_id` registrado coincide con el del canal.

### Requirement 9: Despacho del listener por tipo de canal

**User Story:** Como desarrollador, quiero que el listener Redis despache mensajes según el nuevo esquema de canales, para procesar correctamente cada tipo de mensaje.

#### Acceptance Criteria

1. WHEN un mensaje llega por el canal `worker:{worker_id}` con campo `type` diferente de `cmd_response`, THE RedisConnectionManager SHALL despachar el mensaje a la workstation indicada en `target_workstation_id`.
2. WHEN un mensaje llega por el canal `worker:{worker_id}` con campo `type` igual a `cmd_response`, THE RedisConnectionManager SHALL resolver el command waiter correspondiente al `command_id` del payload.
3. WHEN un mensaje llega por el canal `org:{organization_id}`, THE RedisConnectionManager SHALL entregar el mensaje a todas las workstations locales de esa organización, aplicando filtro por `target_vlan_id` si está presente.
4. WHEN un mensaje llega por el canal `global:broadcast`, THE RedisConnectionManager SHALL entregar el mensaje a todas las workstations conectadas localmente.

### Requirement 10: Reconexión Redis con re-suscripción consolidada

**User Story:** Como operador de infraestructura, quiero que la reconexión Redis restaure solo los canales consolidados, para que la reconexión sea rápida independientemente del número de workstations conectadas.

#### Acceptance Criteria

1. WHEN Redis se reconecta tras una caída, THE RedisConnectionManager SHALL suscribir exactamente: el canal `worker:{worker_id}`, el canal `global:broadcast`, y un canal `org:{org_id}` por cada organización con al menos una workstation conectada localmente.
2. WHEN Redis se reconecta, THE RedisConnectionManager SHALL completar la re-suscripción en tiempo O(1 + N_orgs_activas), independientemente del número de workstations conectadas.
3. THE RedisConnectionManager SHALL utilizar exponential backoff para reintentos de reconexión Redis con intervalo máximo configurable vía `WS_REDIS_RECONNECT_MAX_INTERVAL`.
