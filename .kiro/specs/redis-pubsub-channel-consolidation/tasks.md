# Implementation Plan: Redis Pub/Sub Channel Consolidation

## Overview

Refactorización del RedisConnectionManager para consolidar el esquema de canales Redis de O(n) suscripciones dinámicas (`ws:{id}`, `cmd_response:{id}`) a un máximo fijo de 2 + N_orgs_activas canales estáticos por worker (`worker:{worker_id}`, `global:broadcast`, `org:{org_id}`). El refactor se ejecuta de forma incremental, asegurando que cada paso construye sobre el anterior sin código huérfano.

## Tasks

- [x] 1. Agregar nuevo estado interno al RedisConnectionManager
  - [x] 1.1 Añadir variables `_org_ws_count`, `_ws_vlan_ids` y modificar `_pending_command_responses`
    - En `redis_connection_manager.py`, agregar `_org_ws_count: Dict[str, int] = {}` para conteo de workstations por organización
    - Agregar `_ws_vlan_ids: Dict[str, Optional[str]] = {}` para VLAN de cada workstation
    - Modificar `_pending_command_responses` para incluir el `originator_worker_id` como tercer elemento de la tupla: `Dict[str, Tuple[asyncio.Event, List[Optional[dict]], str]]`
    - _Requirements: 4.4, 5.3, 3.4_

- [x] 2. Refactorizar `connect_workstation` (zero Redis awaits, fire-and-forget org subscribe)
  - [x] 2.1 Implementar hot path síncrono y fire-and-forget en `connect_workstation`
    - Modificar la firma para aceptar `vlan_id: Optional[str] = None`
    - Hot path síncrono: asignar `workstation_connections`, `org_ids`, `_ws_vlan_ids`, `last_pong`, `last_activity`, incrementar `_org_ws_count[org_id]`
    - Fire-and-forget: lanzar `asyncio.create_task` para `WorkerRegistry.register_workstation` y para `SUBSCRIBE org:{org_id}` solo si `_org_ws_count[org_id] == 1`
    - Envolver fire-and-forget en try/except que loguea warning sin interrumpir la conexión
    - Eliminar cualquier `SUBSCRIBE ws:{workstation_id}` existente
    - _Requirements: 1.2, 4.1, 4.4, 6.1, 6.2, 6.3_

  - [x] 2.2 Write property test for lazy org subscribe on connect (Property 8)
    - **Property 8: Lazy org subscription invariant**
    - Usar Hypothesis para generar secuencias arbitrarias de connect/disconnect y verificar que SUBSCRIBE org:{org_id} se ejecuta exactamente cuando count transiciona 0→1
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4**

  - [x] 2.3 Write property test for fire-and-forget resilience (Property 15)
    - **Property 15: Fire-and-forget resilience**
    - Usar Hypothesis con mock de Redis que lanza excepciones aleatorias en SADD/SUBSCRIBE y verificar que la workstation permanece en `workstation_connections`
    - **Validates: Requirements 6.3**

- [x] 3. Refactorizar `disconnect_workstation` (org count decrement, conditional unsubscribe)
  - [x] 3.1 Implementar decremento de contador org y conditional UNSUBSCRIBE en `disconnect_workstation`
    - Eliminar workstation de `workstation_connections`, `org_ids`, `_ws_vlan_ids`, `last_pong`, `last_activity`, `_pending_pongs`
    - Decrementar `_org_ws_count[org_id]`; si llega a 0, ejecutar `UNSUBSCRIBE org:{org_id}` y eliminar la key del dict
    - Ejecutar `WorkerRegistry.unregister_workstation(ws_id)` (SREM)
    - Eliminar cualquier `UNSUBSCRIBE ws:{workstation_id}` existente
    - _Requirements: 1.3, 4.2, 4.4_

  - [x] 3.2 Write property test for subscription count invariant (Property 1)
    - **Property 1: Subscription count invariant**
    - Usar Hypothesis para generar secuencias de connect/disconnect y verificar que el número total de suscripciones activas nunca excede 2 + N_orgs_con_count_>_0
    - **Validates: Requirements 1.1**

- [x] 4. Refactorizar `send_to_workstation` (WorkerRegistry lookup + publish a worker channel)
  - [x] 4.1 Implementar resolución de worker y publish a `worker:{target_worker_id}` en `send_to_workstation`
    - Si workstation está local → envío directo via WebSocket (sin cambio)
    - Si no está local y Redis disponible: consultar `WorkerRegistry.find_worker_for_workstation(ws_id)`
    - Si worker encontrado → `PUBLISH worker:{target_worker_id}` con payload incluyendo `target_workstation_id` y `organization_id`
    - Si no encontrado → log warning, return False
    - Si Redis no disponible → log, return False
    - Eliminar cualquier `PUBLISH ws:{workstation_id}` existente
    - _Requirements: 1.4, 2.2, 2.5, 7.1_

  - [x] 4.2 Write property test for cross-worker message routing (Property 5)
    - **Property 5: Cross-worker message routing**
    - Usar Hypothesis para generar workstation_ids y verificar que cuando WorkerRegistry resuelve a un worker_id, el PUBLISH se dirige a `worker:{resolved_worker_id}` con `target_workstation_id` intacto
    - **Validates: Requirements 2.2**

- [x] 5. Refactorizar command waiters (sin subscribe/unsubscribe, publish response a worker:{originator})
  - [x] 5.1 Refactorizar `register_command_waiter`, `publish_command_response` y `wait_for_command_response`
    - `register_command_waiter`: almacenar `self._worker_id` como originator en la tupla, NO hacer SUBSCRIBE
    - `publish_command_response`: publicar en `worker:{originator_worker_id}` con payload `{"type": "cmd_response", "command_id": ..., ...}`
    - `wait_for_command_response`: esperar con timeout, limpiar waiter del dict sin UNSUBSCRIBE
    - Agregar método `resolve_command_response` que busca el command_id en el dict y hace `event.set()` con los datos
    - Eliminar cualquier `SUBSCRIBE cmd_response:{id}` y `UNSUBSCRIBE cmd_response:{id}` existente
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x] 5.2 Write property test for no per-command channel operations (Property 3)
    - **Property 3: No per-command channel operations**
    - Usar Hypothesis para generar secuencias de register/resolve/timeout de command waiters y verificar que nunca se invoca SUBSCRIBE/UNSUBSCRIBE en `cmd_response:{id}`
    - **Validates: Requirements 3.1, 3.4, 3.5**

  - [x] 5.3 Write property test for command response routing (Property 6)
    - **Property 6: Command response routing via worker channel**
    - Usar Hypothesis para verificar que las respuestas de comandos cross-worker se publican en `worker:{originator}` con type=cmd_response y command_id correcto
    - **Validates: Requirements 3.2**

- [x] 6. Checkpoint - Verificar funcionalidad core
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Refactorizar el listener Redis para despacho por nuevo esquema de canales
  - [x] 7.1 Implementar `_redis_listener` con despacho por canal consolidado
    - Canal `worker:{self._worker_id}`: si `type == "cmd_response"` → `resolve_command_response(command_id, payload)`; else → `_deliver_to_local_workstation(target_workstation_id, payload)` con validación de tenant
    - Canal `org:{organization_id}`: → `_deliver_to_local_org_workstations(organization_id, payload)` con filtro VLAN
    - Canal `global:broadcast`: → `_deliver_global_broadcast(payload)` a todas las workstations locales
    - Eliminar despacho a canales `ws:{id}` y `cmd_response:{id}`
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 8.1, 8.2, 8.3_

  - [x] 7.2 Implementar `_deliver_to_local_org_workstations` con filtrado VLAN
    - Filtrar workstations locales por `org_ids[ws_id] == organization_id`
    - Si payload contiene `target_vlan_id`: filtrar adicionalmente por `_ws_vlan_ids[ws_id] == target_vlan_id`
    - Enviar payload a cada workstation que pase ambos filtros
    - _Requirements: 5.1, 5.2, 5.3, 8.3_

  - [x] 7.3 Write property test for worker channel dispatch correctness (Property 4)
    - **Property 4: Worker channel dispatch correctness**
    - Usar Hypothesis para generar mensajes con target_workstation_id aleatorios y verificar entrega correcta o descarte según si la workstation está local
    - **Validates: Requirements 2.3, 2.4, 9.1**

  - [x] 7.4 Write property test for VLAN filtering (Property 9)
    - **Property 9: VLAN filtering on org messages**
    - Usar Hypothesis para generar workstations con VLAN variados y mensajes con/sin target_vlan_id, verificar que solo las workstations correctas reciben el mensaje
    - **Validates: Requirements 5.1, 5.3**

  - [x] 7.5 Write property test for tenant isolation (Property 10)
    - **Property 10: Tenant isolation**
    - Usar Hypothesis para generar mensajes con organization_id mismatched y verificar que se descartan
    - **Validates: Requirements 8.1, 8.3**

  - [x] 7.6 Write property test for global broadcast delivery (Property 11)
    - **Property 11: Global broadcast delivery**
    - Verificar que mensajes en global:broadcast se entregan a TODAS las workstations sin filtrado
    - **Validates: Requirements 9.4**

- [x] 8. Refactorizar `_handle_redis_reconnect` con re-suscripción consolidada
  - [x] 8.1 Implementar reconexión con exponential backoff y re-suscripción de canales consolidados
    - Al reconectar: crear nuevo PubSub, SUBSCRIBE `worker:{self._worker_id}`, SUBSCRIBE `global:broadcast`
    - Iterar `_org_ws_count` y SUBSCRIBE `org:{org_id}` para cada org con count > 0
    - Re-registrar TODAS las workstations locales en WorkerRegistry via SADD
    - Reiniciar listener task
    - Total subscribe ops: 2 + len(orgs_activas), independiente del número de workstations
    - Eliminar cualquier lógica de re-suscripción per-workstation existente
    - _Requirements: 7.3, 7.4, 10.1, 10.2, 10.3_

  - [x] 8.2 Write property test for reconnect channel set (Property 12)
    - **Property 12: Reconnect subscribes exact channel set**
    - Usar Hypothesis para generar estado arbitrario de workstations conectadas y verificar que la reconexión suscribe exactamente el set correcto de canales
    - **Validates: Requirements 7.3, 10.1, 10.2**

  - [x] 8.3 Write property test for reconnect re-registers workstations (Property 13)
    - **Property 13: Reconnect re-registers all local workstations**
    - Verificar que tras reconexión, todas las workstations en `workstation_connections.keys()` se re-registran via SADD
    - **Validates: Requirements 7.4**

- [x] 9. Refactorizar `initialize()` para suscribir solo canales fijos
  - [x] 9.1 Modificar `initialize()` para suscribir `worker:{worker_id}` y `global:broadcast` únicamente
    - Conectar a Redis, crear PubSub
    - SUBSCRIBE solo `worker:{self._worker_id}` y `global:broadcast` (2 canales fijos)
    - Inicializar WorkerRegistry y arrancar listener task + heartbeat task
    - NO suscribir canales per-workstation ni per-command
    - Actualizar docstring del módulo para reflejar nuevo esquema de canales
    - _Requirements: 2.1, 1.4_

  - [x] 9.2 Write property test for no per-workstation channel operations (Property 2)
    - **Property 2: No per-workstation channel operations**
    - Usar Hypothesis para verificar que en ninguna secuencia de operaciones se invoca SUBSCRIBE/UNSUBSCRIBE/PUBLISH en canales `ws:{id}`
    - **Validates: Requirements 1.2, 1.3, 1.4**

- [x] 10. Propagar `vlan_id` desde WebSocket endpoint a `connect_workstation`
  - [x] 10.1 Modificar endpoint WebSocket para pasar `vlan_id` a `connect_workstation`
    - En `workstation.py`, tras el registro exitoso de la workstation, extraer `workstation.vlan_id` del objeto ORM
    - Pasar `vlan_id=str(workstation.vlan_id) if workstation.vlan_id else None` en la llamada a `connection_manager.connect_workstation()`
    - _Requirements: 5.3_

- [x] 11. Checkpoint - Verificar integración completa
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Property tests de fallback graceful
  - [x] 12.1 Write property test for graceful fallback without Redis (Property 14)
    - **Property 14: Graceful fallback without Redis**
    - Usar Hypothesis para generar operaciones (send, connect, disconnect) con `_redis_available=False` y verificar que no se intentan operaciones Redis y las operaciones locales completan sin error
    - **Validates: Requirements 7.1, 7.2**

  - [x] 12.2 Write property test for command response resolves waiter (Property 7)
    - **Property 7: Command response resolves waiter**
    - Usar Hypothesis para generar mensajes cmd_response y verificar que el waiter correcto se resuelve con el payload
    - **Validates: Requirements 3.3, 9.2**

- [x] 13. Final checkpoint - Verificar todos los tests
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties using Hypothesis (Python)
- Unit tests validate specific examples and edge cases
- El archivo principal a modificar es `AlwaysPrintProject/Cloud/backend/app/services/redis_connection_manager.py`
- Archivo secundario: `AlwaysPrintProject/Cloud/backend/app/services/worker_registry.py` (sin cambios estructurales)
- Endpoint: `AlwaysPrintProject/Cloud/backend/app/api/v1/websocket/workstation.py` (solo Task 10)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "9.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "3.1"] },
    { "id": 3, "tasks": ["3.2", "4.1"] },
    { "id": 4, "tasks": ["4.2", "5.1"] },
    { "id": 5, "tasks": ["5.2", "5.3", "7.1"] },
    { "id": 6, "tasks": ["7.2", "7.3", "7.4", "7.5", "7.6"] },
    { "id": 7, "tasks": ["8.1"] },
    { "id": 8, "tasks": ["8.2", "8.3", "10.1"] },
    { "id": 9, "tasks": ["9.2", "12.1", "12.2"] }
  ]
}
```
