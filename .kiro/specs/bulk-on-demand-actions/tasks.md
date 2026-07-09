# Implementation Plan: Bulk On-Demand Actions

## Overview

Implementación del sistema de ejecución masiva de acciones OnDemand que permite a operadores/admins ejecutar una acción del alwaysconfig activo contra todas las workstations online de una organización, con throttling configurable, progreso en tiempo real vía WebSocket, y cancelación. El backend se implementa en Python (FastAPI) y el frontend en TypeScript (Next.js).

## Tasks

- [ ] 1. Definir schemas, tipos y helpers de extracción
  - [ ] 1.1 Crear schemas Pydantic para bulk actions
    - Crear `app/schemas/bulk_actions.py` con los modelos: `OnDemandAction`, `BulkStartRequest`, `BulkPreviewRequest`, `BulkPreview`, `BulkSessionStatus`, `BulkStartResponse`
    - Incluir validaciones de rango `delay_ms` (50-10000) y `label` (min 1, max 255)
    - _Requirements: 2.4, 2.5, 6.1, 6.2_

  - [ ] 1.2 Implementar función de extracción de triggers OnDemand
    - Crear `app/services/bulk_execution.py` con el método `get_available_actions` que parsea el alwaysconfig activo (scope=org) y extrae triggers con `event == "OnDemand"` y `label` no vacío
    - Retornar lista de `OnDemandAction` con `label` y `description`
    - Manejar caso de org sin config activa (error) y sin triggers OnDemand (lista vacía)
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [ ] 1.3 Implementar validación de label contra config activa
    - En `BulkExecutionService`, agregar método para validar que un label existe en el alwaysconfig activo de la organización
    - _Requirements: 2.1, 2.6_

  - [ ] 1.4 Write property tests for trigger extraction and label validation
    - **Property 1: OnDemand trigger extraction** — Generar configs aleatorios con mezcla de triggers, verificar que solo se extraen los que tienen `event == "OnDemand"` y `label` no vacío
    - **Property 2: Label validation against active config** — Generar configs y labels arbitrarios, verificar aceptación/rechazo correcto
    - **Property 3: Throttle range validation** — Generar enteros arbitrarios, verificar que solo se aceptan valores en [50, 10000]
    - Crear archivo `tests/properties/test_bulk_actions_properties.py`
    - **Validates: Requirements 1.1, 1.2, 1.4, 2.1, 2.4, 2.5, 2.6**

  - [ ] 1.5 Crear tipos TypeScript para bulk actions
    - Crear `src/types/bulk-actions.ts` con interfaces: `OnDemandAction`, `BulkPreview`, `BulkSessionStatus`, `BulkProgressMessage`, `BulkStartRequest`, `BulkPreviewRequest`
    - Agregar `BulkProgressMessage` al union type de mensajes WebSocket del operador en `src/types/websocket.ts`
    - _Requirements: 3.1, 3.2, 8.5_

- [ ] 2. Checkpoint - Verificar schemas y helpers
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 3. Implementar servicio de ejecución masiva con throttling
  - [ ] 3.1 Implementar lógica de mutex y sesión en Redis
    - En `BulkExecutionService`, implementar `start_session` que: verifica mutex `bulk:running:{org_id}`, crea hash `bulk:session:{session_id}` con estado `running`, retorna `BulkStartResponse`
    - Implementar obtención del preview (`get_preview`) con fórmula `(workstations_online - 1) * delay_ms`
    - Implementar `get_session_status` que lee el hash Redis de la sesión
    - _Requirements: 2.2, 2.7, 6.1, 6.2_

  - [ ] 3.2 Implementar background task de ejecución throttled
    - Implementar `_execute_bulk` como método async que: itera workstations online, envía `execute_on_demand` via `ConnectionManager.send_to_workstation`, aplica `asyncio.sleep(delay_ms/1000)` entre envíos, actualiza métricas en Redis tras cada envío
    - Verificar flag `bulk:cancel:{session_id}` antes de cada envío
    - Incrementar errores si send falla, registrar workstation_id fallido, continuar con siguiente
    - Renovar TTL del mutex cada 5 minutos durante ejecución
    - Al finalizar: DEL mutex, HSET status=completed, enviar progress_report final
    - _Requirements: 2.3, 3.1, 3.4, 4.3_

  - [ ] 3.3 Implementar cancelación de sesión
    - Implementar `cancel_session` que: verifica que la sesión está en estado `running`, SET `bulk:cancel:{session_id}` con TTL 5min, retorna estado actualizado
    - Rechazar cancelación si sesión no está en estado `running`
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [ ] 3.4 Implementar envío de progress reports vía WebSocket
    - Tras cada envío exitoso o fallido, broadcast a operadores de la organización un mensaje tipo `bulk_progress` con métricas actualizadas usando `broadcast_to_organization`
    - Enviar progress_report final con estado `completed` o `cancelled`
    - _Requirements: 3.1, 3.2, 3.3_

  - [ ] 3.5 Write property tests for execution progress invariants and cancellation
    - **Property 5: Execution progress invariants** — Generar listas de workstations con patrones de fallo aleatorios, mock send, verificar que `sent == success + errors`, `sent <= total`, y al completar `sent == total`
    - **Property 6: Cancellation correctness** — Generar listas y puntos de cancelación aleatorios, verificar estado final `cancelled`, `sent <= P + 1`, y no nuevos envíos post-cancelación
    - Agregar en `tests/properties/test_bulk_actions_properties.py`
    - **Validates: Requirements 2.3, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4**

  - [ ] 3.6 Write property test for preview time estimation
    - **Property 8: Preview time estimation** — Generar valores `workstations_online` (>= 1) y `delay_ms` en [50, 10000], verificar resultado exacto `(workstations_online - 1) * delay_ms`
    - Agregar en `tests/properties/test_bulk_actions_properties.py`
    - **Validates: Requirements 6.1, 6.2**

- [ ] 4. Checkpoint - Verificar servicio de ejecución
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Implementar API REST y seguridad
  - [ ] 5.1 Crear router de bulk actions con endpoints REST
    - Crear `app/api/v1/endpoints/bulk_actions.py` con 5 endpoints: `GET /bulk-actions/available-actions`, `POST /bulk-actions/preview`, `POST /bulk-actions/start`, `GET /bulk-actions/status/{session_id}`, `POST /bulk-actions/cancel/{session_id}`
    - Todos requieren rol `admin` u `operator`, aplicar tenant isolation para operadores
    - Retornar 403 para usuarios `readonly`
    - Registrar el router en `app/api/v1/router.py`
    - _Requirements: 5.1, 5.2, 5.3, 1.1, 2.2, 4.1, 6.1_

  - [ ] 5.2 Implementar registro de auditoría
    - Al inicio de sesión: registrar user_id, organization_id, label, delay_ms, total workstations, timestamp
    - Al finalizar sesión: registrar session_id, estado final, duración, éxitos, errores
    - Usar el servicio de auditoría existente (`app/services/audit.py`)
    - _Requirements: 7.1, 7.2_

  - [ ] 5.3 Write integration tests for API endpoints
    - Test flujo completo: start → progress → complete
    - Test cancelación: start → cancel → final report
    - Test mutex: segundo start rechazado con 409
    - Test auth: readonly user gets 403
    - Test tenant isolation: operator cannot start for other org
    - Test audit logs creados correctamente
    - Crear `tests/integration/test_bulk_actions.py`
    - _Requirements: 2.7, 4.1, 5.1, 5.2, 5.3, 7.1, 7.2_

- [ ] 6. Checkpoint - Verificar API y seguridad
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Implementar interfaz frontend
  - [ ] 7.1 Crear página de bulk actions y componente selector de acciones
    - Crear directorio `src/app/dashboard/workstations/bulk-actions/`
    - Crear `page.tsx` con verificación de rol (solo admin/operator)
    - Implementar componente `ActionSelector` que obtiene acciones OnDemand del endpoint `GET /bulk-actions/available-actions` y muestra dropdown
    - Implementar `ThrottleConfig` con input numérico (default 500ms, rango 50-10000ms)
    - _Requirements: 8.1, 8.2, 8.3_

  - [ ] 7.2 Implementar diálogo de confirmación y preview
    - Implementar `ConfirmationDialog` que llama a `POST /bulk-actions/preview` y muestra: nombre de acción, workstations afectadas, tiempo estimado
    - Botón de confirmar inicia la ejecución vía `POST /bulk-actions/start`
    - _Requirements: 8.4, 6.1_

  - [ ] 7.3 Implementar panel de progreso en tiempo real
    - Implementar componente `ExecutionProgress` que escucha mensajes WebSocket tipo `bulk_progress`
    - Mostrar barra de progreso (sent/total), contadores (total, enviados, éxitos, errores), botón de cancelación
    - Fallback: polling via `GET /bulk-actions/status/{session_id}` cada 3s si WebSocket pierde conexión
    - Al finalizar, mostrar `ExecutionSummary` con resultado y métricas finales
    - _Requirements: 8.5, 8.6, 3.1, 3.2_

  - [ ] 7.4 Write unit tests for frontend components
    - Test: componente oculto para rol readonly
    - Test: ThrottleConfig valida rango 50-10000
    - Test: ConfirmationDialog muestra datos correctos del preview
    - Test: ExecutionProgress actualiza contadores con mensajes WebSocket
    - Crear tests con Vitest en la carpeta de tests del frontend
    - _Requirements: 8.1, 8.3, 8.4, 8.5_

- [ ] 8. Integración final y wiring
  - [ ] 8.1 Conectar todos los componentes e integrar navegación
    - Agregar enlace a bulk actions en la navegación del dashboard (sección workstations)
    - Verificar que el flujo completo funciona: selección de acción → config throttle → preview → confirmación → ejecución → progreso → resultado final
    - Verificar manejo de errores en cada paso (org sin config, label inválido, sesión ya running)
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

- [ ] 9. Final checkpoint - Verificar integración completa
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marcadas con `*` son opcionales y pueden saltarse para un MVP más rápido
- Cada task referencia requirements específicos para trazabilidad
- Los checkpoints aseguran validación incremental
- Property tests validan propiedades universales de correctitud (usando Hypothesis)
- Unit tests validan ejemplos específicos y casos borde
- El backend usa Python 3.12 + FastAPI, el frontend usa TypeScript + Next.js 15
- Redis se usa para estado efímero (sesiones bulk), PostgreSQL solo para auditoría
- El broadcast de progreso usa `broadcast_to_organization` que solo envía a operadores (no a workstations)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.5"] },
    { "id": 1, "tasks": ["1.2", "1.3"] },
    { "id": 2, "tasks": ["1.4", "3.1"] },
    { "id": 3, "tasks": ["3.2", "3.3", "3.6"] },
    { "id": 4, "tasks": ["3.4", "3.5"] },
    { "id": 5, "tasks": ["5.1", "5.2"] },
    { "id": 6, "tasks": ["5.3", "7.1"] },
    { "id": 7, "tasks": ["7.2"] },
    { "id": 8, "tasks": ["7.3", "7.4"] },
    { "id": 9, "tasks": ["8.1"] }
  ]
}
```
