# Implementation Plan: stable-multi-worker-redis

## Overview

Activar el modo multi-worker (2 uvicorn workers) coordinados vía Redis pub/sub, reconectando el `RedisConnectionManager` y `WorkerRegistry` ya implementados al sistema, sin introducir `RegistrationCache`. El enfoque es incremental: primero configuración y factory, luego adaptación del endpoint, luego tests.

## Tasks

- [x] 1. Configuración de settings multi-worker y factory de connection_manager
  - [x] 1.1 Añadir UVICORN_WORKERS, WORKER_REGISTRY_TTL, WS_REDIS_RECONNECT_MAX_INTERVAL a Settings en config.py con validador multi-worker→Redis
    - Añadir `UVICORN_WORKERS: int = 1`, `WORKER_REGISTRY_TTL: int = 60`, `WS_REDIS_RECONNECT_MAX_INTERVAL: int = 30`
    - Añadir `@model_validator(mode="after")` `_validate_multi_worker` que lanza `ValueError` si `UVICORN_WORKERS > 1` y `REDIS_URL` es None/vacío
    - _Requirements: 2.1, 2.2, 5.1, 5.2, 5.3, 5.4_

  - [x] 1.2 Restaurar websocket_manager.py como factory condicional
    - Mover la clase `ConnectionManager` a permanecer en el mismo archivo (antes del factory)
    - Añadir `vlan_id=None` como parámetro a `connect_workstation` del `ConnectionManager` (se ignora internamente)
    - Al final del archivo, reemplazar `connection_manager = ConnectionManager()` por el factory condicional: si `settings.REDIS_URL` → `RedisConnectionManager(redis_url=settings.REDIS_URL)`, else → `ConnectionManager()`
    - _Requirements: 1.1, 1.2, 10.1, 10.2, 10.3, 9.3_

  - [x] 1.3 Añadir inicialización de RedisConnectionManager en lifespan de main.py
    - Antes del `ping_task`, añadir: `if hasattr(connection_manager, 'initialize'): await connection_manager.initialize()`
    - _Requirements: 1.3, 8.4_

- [x] 2. Adaptación del endpoint WebSocket
  - [x] 2.1 Añadir vlan_id a la llamada connect_workstation en workstation.py
    - En la llamada `await connection_manager.connect_workstation(...)`, añadir `vlan_id=str(workstation.vlan_id) if workstation.vlan_id else None`
    - _Requirements: 9.3_

  - [x] 2.2 Verificar y eliminar cualquier importación de registration_cache en workstation.py
    - Confirmar que no existe `import registration_cache` ni `from ... import registration_cache` en el archivo
    - Si existe, eliminarlo
    - _Requirements: 3.1, 3.2, 3.3_

- [x] 3. Checkpoint — Verificar que el backend arranca correctamente
  - Ensure all tests pass, ask the user if questions arise.
  - Verificar que `from app.services.websocket_manager import connection_manager` funciona sin errores de import
  - Verificar que el validador de multi-worker funciona (UVICORN_WORKERS=2 sin REDIS_URL → error)

- [x] 4. Tests de lint guard e import ban
  - [x] 4.1 Crear tests/test_import_ban.py con test de importaciones prohibidas
    - Verificar que `registration_cache` no aparece en ningún archivo del flujo WebSocket: `workstation.py`, `operator.py`, `websocket_manager.py`, `redis_connection_manager.py`, `worker_registry.py`
    - Usar `pathlib.Path` para leer contenido y assert que el string no está presente
    - _Requirements: 3.3, 3.4_

  - [x] 4.2 Write property test para import ban (Property 2)
    - **Property 2: RegistrationCache import ban**
    - **Validates: Requirements 3.3, 3.4**
    - Usar `hypothesis` con `st.sampled_from(WS_FLOW_FILES)` para verificar que ningún archivo del flujo WS contiene "registration_cache"

- [x] 5. Property tests para correctness properties del diseño
  - [x] 5.1 Write property test para interface compliance (Property 1)
    - **Property 1: Interface compliance**
    - **Validates: Requirements 1.4, 10.3**
    - Usar `st.sampled_from(REQUIRED_METHODS)` para verificar que tanto `ConnectionManager` como `RedisConnectionManager` tienen cada método como callable

  - [x] 5.2 Write property test para session lifecycle (Property 3)
    - **Property 3: Session lifecycle — no DB held during WebSocket await**
    - **Validates: Requirements 4.1, 4.2, 4.3**
    - Usar `st.lists(st.sampled_from(MSG_TYPES))` para generar secuencias de mensajes y verificar que la sesión se cierra antes de cada await

  - [x] 5.3 Write property test para pool sizing constraint (Property 4)
    - **Property 4: Pool sizing constraint**
    - **Validates: Requirements 5.5**
    - Usar `st.integers` para workers, pool_size y overflow; verificar que `workers × (pool_size + overflow) <= 81 - 21`

  - [x] 5.4 Write property test para multi-worker requires Redis (Property 5)
    - **Property 5: Multi-worker requires Redis URL**
    - **Validates: Requirements 2.2**
    - Usar `st.integers(min_value=2, max_value=16)` para workers con REDIS_URL=None; verificar que Settings lanza ValueError

- [x] 6. Checkpoint — Ejecutar property tests existentes y nuevos
  - Ensure all tests pass, ask the user if questions arise.
  - Verificar que los 15 property tests de redis-pubsub-channel-consolidation siguen pasando
  - Verificar que los nuevos property tests del punto 5 pasan
  - Verificar que los tests existentes relacionados (`test_graceful_fallback_redis_unavailable.py`, `test_in_memory_mode_without_redis.py`, etc.) siguen pasando

- [x] 7. Integración final y wiring
  - [x] 7.1 Verificar que el factory selecciona correctamente según REDIS_URL
    - Sin REDIS_URL → `ConnectionManager`
    - Con REDIS_URL → `RedisConnectionManager`
    - Confirmar que el import público `from app.services.websocket_manager import connection_manager` funciona en ambos modos
    - _Requirements: 10.1, 10.2_

  - [x] 7.2 Verificar shutdown graceful con cleanup de Redis en lifespan
    - Confirmar que `graceful_shutdown_workstations` se invoca en shutdown
    - Si el manager tiene `cleanup_on_shutdown` (WorkerRegistry), verificar que se invoca
    - _Requirements: 8.1, 8.2_

- [x] 8. Final checkpoint — Suite completa de tests
  - Ensure all tests pass, ask the user if questions arise.
  - Ejecutar toda la suite de tests para confirmar cero regresiones
  - Verificar que no hay imports de `registration_cache` en archivos de producción del flujo WS

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Los archivos `redis_connection_manager.py` y `worker_registry.py` NO se modifican (ya están correctos)
- El endpoint ya usa sesiones cortas (SessionLocal) — solo se verifica, no se modifica ese patrón
- El `ConnectionManager` necesita aceptar `vlan_id` en su firma para cumplir la interfaz compartida

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3"] },
    { "id": 2, "tasks": ["2.1", "2.2"] },
    { "id": 3, "tasks": ["4.1", "4.2"] },
    { "id": 4, "tasks": ["5.1", "5.2", "5.3", "5.4"] },
    { "id": 5, "tasks": ["7.1", "7.2"] }
  ]
}
```
