# Implementation Plan: Death Ping Optimization

## Overview

Reemplazar el ping masivo a todas las workstations por un mecanismo selectivo basado en inactividad. Se rastrean timestamps de actividad en memoria, se consulta el timeout configurable por organización, y solo se envía Death Ping a workstations inactivas. Las que no responden en 30s se desconectan via batch UPDATE.

## Tasks

- [x] 1. Modelo, schema y migración de Organization
  - [x] 1.1 Agregar campo `offline_timeout_minutes` al modelo Organization
    - Agregar columna `Integer, nullable=False, default=10, server_default='10'` en `app/models/organization.py`
    - Importar `Integer` de sqlalchemy si no existe
    - _Requirements: 2.1, 2.2_

  - [x] 1.2 Actualizar schemas Pydantic de Organization
    - Agregar `offline_timeout_minutes: Optional[int] = Field(None, ge=1)` a `OrganizationUpdate`
    - Agregar `offline_timeout_minutes: int = 10` a `OrganizationResponse`
    - Agregar validación `ge=1` para rechazar valores menores a 1
    - _Requirements: 2.4, 7.2, 7.3, 7.4_

  - [x] 1.3 Crear migración Alembic `015_add_offline_timeout`
    - Archivo: `alembic/versions/015_add_offline_timeout.py`
    - `op.add_column('organizations', Column('offline_timeout_minutes', Integer, nullable=False, server_default='10'))`
    - down_revision: `014_add_scalability_json`
    - _Requirements: 2.1, 2.2_

  - [x] 1.4 Write property test para validación de offline_timeout_minutes
    - **Property 2: Validación de offline_timeout_minutes**
    - Generar enteros aleatorios, verificar aceptación si >= 1 y rechazo si < 1
    - Archivo: `tests/properties/test_timeout_validation_properties.py`
    - **Validates: Requirements 2.4, 7.2, 7.3**

- [x] 2. ConnectionManager: nuevos atributos y métodos
  - [x] 2.1 Agregar atributos `last_activity`, `org_ids`, `_pending_pongs` al ConnectionManager
    - Inicializar `self.last_activity: Dict[str, datetime] = {}` en `__init__`
    - Inicializar `self.org_ids: Dict[str, str] = {}` en `__init__`
    - Inicializar `self._pending_pongs: Dict[str, datetime] = {}` en `__init__`
    - Agregar constante `PONG_TIMEOUT_SECONDS = 30` a nivel de módulo
    - _Requirements: 1.6, 4.1_

  - [x] 2.2 Modificar `connect_workstation` para aceptar `organization_id`
    - Agregar parámetro `organization_id: str` a la firma del método
    - Inicializar `self.last_activity[workstation_id]` con timestamp UTC actual
    - Almacenar `self.org_ids[workstation_id] = organization_id`
    - _Requirements: 1.6, 3.2_

  - [x] 2.3 Implementar método `update_last_activity`
    - Método async que actualiza `self.last_activity[workstation_id]` con `datetime.now(timezone.utc).replace(tzinfo=None)`
    - Solo actualizar si `workstation_id in self.workstation_connections`
    - Usar `self._lock` para thread-safety
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 2.4 Modificar `disconnect_workstation` para limpiar nuevos dicts
    - Agregar `self.last_activity.pop(workstation_id, None)` al bloque de limpieza
    - Agregar `self.org_ids.pop(workstation_id, None)`
    - Agregar `self._pending_pongs.pop(workstation_id, None)`
    - _Requirements: 5.2, 5.3_

  - [x] 2.5 Write property test para actualización de last_activity
    - **Property 1: Actualización de last_activity por mensaje recibido**
    - Generar ws_ids y tipos de mensaje aleatorios, verificar que last_activity se actualiza
    - Archivo: `tests/properties/test_last_activity_properties.py`
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6**

  - [x] 2.6 Write property test para limpieza en desconexión
    - **Property 5: Limpieza completa en desconexión**
    - Generar ws muertas, ejecutar cleanup, verificar que no existen en ningún dict
    - Archivo: `tests/properties/test_disconnect_cleanup_properties.py`
    - **Validates: Requirements 5.2, 5.3**

- [x] 3. Checkpoint - Verificar modelo y ConnectionManager
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Nuevo ping loop selectivo (Death Ping)
  - [x] 4.1 Reescribir `start_ping_loop` con lógica de inactividad selectiva
    - Fase 1: Verificar `_pending_pongs` del ciclo anterior (> 30s sin pong → dead)
    - Fase 2: Consultar `offline_timeout_minutes` por org desde BD (`SELECT id, offline_timeout_minutes FROM organizations WHERE id IN (...)`)
    - Fase 3: Para cada ws, comparar `last_activity` con threshold del org; si inactiva → enviar `{"type": "ping"}` y registrar en `_pending_pongs`
    - Fase 4: Batch disconnect de muertas (remover de dicts + UPDATE en BD)
    - Mantener `CHECK_INTERVAL = 60` (constante existente `WS_PING_INTERVAL`)
    - Si excepción al enviar ping → agregar a dead inmediatamente
    - Si excepción al consultar BD de timeouts → usar default 10 para todas
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.3, 4.4, 5.1, 5.4, 6.1, 6.4_

  - [x] 4.2 Integrar respuesta de pong con `_pending_pongs`
    - Modificar `handle_pong` para también remover `workstation_id` de `self._pending_pongs`
    - Actualizar `last_activity` al recibir pong (ya cubierto desde endpoint)
    - _Requirements: 4.2_

  - [x] 4.3 Write property test para selectividad del Death Ping
    - **Property 3: Selectividad del Death Ping**
    - Generar conjuntos de ws con last_activity y timeouts variados, verificar que solo las inactivas reciben ping
    - Archivo: `tests/properties/test_death_ping_selectivity_properties.py`
    - **Validates: Requirements 3.3, 3.4, 3.5**

  - [x] 4.4 Write property test para timeout de pong
    - **Property 4: Timeout de pong resulta en desconexión**
    - Generar ws con pending_pongs y tiempos variados, verificar que solo las que exceden 30s van a disconnect
    - Archivo: `tests/properties/test_pong_timeout_properties.py`
    - **Validates: Requirements 4.3**

- [x] 5. WebSocket endpoint: integrar update_last_activity
  - [x] 5.1 Actualizar llamada a `connect_workstation` con `organization_id`
    - Pasar `organization_id=str(workstation.organization_id)` como nuevo parámetro en `app/api/v1/websocket/workstation.py`
    - _Requirements: 1.6, 3.2_

  - [x] 5.2 Agregar `update_last_activity` en cada tipo de mensaje del loop
    - Agregar `await connection_manager.update_last_activity(workstation_id)` en handlers de: pong, status_update, telemetry, connectivity_result
    - El registro (connect) ya inicializa last_activity via `connect_workstation`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 5.3 Write unit tests para el endpoint WebSocket modificado
    - Verificar que connect_workstation recibe organization_id
    - Verificar que update_last_activity se invoca en cada tipo de mensaje
    - Archivo: `tests/unit/test_death_ping_unit.py`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

- [x] 6. Checkpoint - Verificar loop y endpoint
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Frontend: campo offline_timeout_minutes en admin de organizaciones
  - [x] 7.1 Agregar campo `offline_timeout_minutes` a la UI de configuración de organizaciones
    - Agregar input numérico (min=1) en la página de edición de organización: `src/app/dashboard/admin/organizations/page.tsx`
    - Incluir en el formulario de edición y en la vista de detalle
    - Etiqueta en español: "Timeout inactividad (minutos)"
    - Validación frontend: solo enteros >= 1
    - _Requirements: 7.1, 7.2, 7.3_

- [x] 8. Checkpoint final - Verificar integración completa
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marcadas con `*` son opcionales y pueden omitirse para MVP más rápido
- Cada task referencia requisitos específicos para trazabilidad
- Los checkpoints aseguran validación incremental
- Los property tests validan propiedades universales de correctitud del diseño
- Los unit tests validan ejemplos específicos y edge cases
- El mecanismo existente de `_flush_disconnect_queue` (commit bef6b8c) NO se modifica; el nuevo loop usa su propio batch UPDATE directamente
- Comentarios y logs en español según convención del proyecto
- Importar `Base` desde `app.core.database` (no `app.db`)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "2.1"] },
    { "id": 1, "tasks": ["1.4", "2.2", "2.3", "2.4"] },
    { "id": 2, "tasks": ["2.5", "2.6", "4.1", "5.1"] },
    { "id": 3, "tasks": ["4.2", "5.2"] },
    { "id": 4, "tasks": ["4.3", "4.4", "5.3"] },
    { "id": 5, "tasks": ["7.1"] }
  ]
}
```
