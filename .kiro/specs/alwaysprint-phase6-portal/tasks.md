# Implementation Plan: Fase 6 — Mejoras al Portal Cloud (APCM)

## Overview

Este plan implementa la Fase 6 del AlwaysPrint Cloud Manager: persistencia de telemetría y conectividad, extensión de schemas de configuración con `config_hash`, WebSocket broadcast, endpoints REST de consulta histórica/estadísticas, y dashboards frontend. El backend usa Python/FastAPI y el frontend TypeScript/Next.js 15.

## Tasks

- [x] 1. Modelos de datos y migración de base de datos
  - [x] 1.1 Crear modelos SQLAlchemy TelemetryLog y ConnectivityResult
    - Crear archivo `app/models/telemetry.py` con los modelos `TelemetryLog` y `ConnectivityResult`
    - Definir columnas según el diseño: id (GUID), workstation_id, account_id, queue_status, contingency_active, jobs_identified, avg_release_time_ms, disconnection_count, recorded_at para TelemetryLog
    - Definir columnas para ConnectivityResult: id, workstation_id, account_id, check_id, check_type, success, latency_ms, error, recorded_at
    - Definir relaciones many-to-one con Workstation y Account usando `back_populates`
    - Registrar ambos modelos en `app/models/__init__.py` agregándolos a `__all__`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [x] 1.2 Crear migración Alembic para tablas telemetry_logs y connectivity_results
    - Crear archivo `alembic/versions/007_add_telemetry_and_connectivity_tables.py`
    - Implementar `upgrade()`: crear tabla `telemetry_logs` con todas las columnas y FKs con CASCADE delete
    - Implementar `upgrade()`: crear tabla `connectivity_results` con todas las columnas y FKs con CASCADE delete
    - Crear índice compuesto `ix_telemetry_logs_ws_recorded` en `(workstation_id, recorded_at)`
    - Crear índice compuesto `ix_connectivity_results_ws_check_recorded` en `(workstation_id, check_id, recorded_at)`
    - Crear índices simples en `account_id` para ambas tablas
    - Implementar `downgrade()`: eliminar solo las tablas e índices creados
    - Declarar `revision` y `down_revision` correctos para encadenar con la migración anterior
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7_

  - [ ]* 1.3 Escribir tests unitarios para modelos SQLAlchemy
    - Verificar creación correcta de TelemetryLog con todos los campos
    - Verificar creación correcta de ConnectivityResult con todos los campos
    - Verificar relaciones bidireccionales con Workstation y Account
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [x] 2. Schemas Pydantic y configuración
  - [x] 2.1 Extender schemas de configuración con ConnectivityCheckItem y locale
    - Modificar `app/schemas/config.py` para agregar `ConnectivityCheckItem` con validación condicional por tipo (HTTP/TCP/Ping/DNS)
    - Implementar `@model_validator(mode="after")` para validar campos requeridos según tipo
    - Agregar campos `connectivity_checks`, `locale`, `telemetry_enabled`, `telemetry_interval_seconds` a `GlobalConfigUpdate`, `VLANConfigUpdate`, `WorkstationConfigUpdate`
    - Agregar `config_hash` (str, 64 chars hex) a `EffectiveConfigResponse`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 4.1_

  - [ ]* 2.2 Escribir property test para ConnectivityCheckItem (Property 1)
    - **Property 1: ConnectivityCheckItem schema validates type-specific required fields**
    - Generar ConnectivityCheckItem aleatorios con combinaciones de tipo y campos usando Hypothesis
    - Verificar que la validación acepta items con campos correctos y rechaza items con campos faltantes
    - `# Feature: alwaysprint-phase6-portal, Property 1: ConnectivityCheckItem schema validates type-specific required fields`
    - **Validates: Requirements 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10**

  - [x] 2.3 Implementar compute_config_hash en ConfigService
    - Modificar `app/services/config.py` para agregar función `compute_config_hash(config_dict: dict) -> str`
    - Excluir campos `source` y `config_hash` del input
    - Serializar con `json.dumps(sort_keys=True, ensure_ascii=False)` y computar SHA-256
    - Integrar en `get_effective_config()` para incluir `config_hash` en la respuesta
    - Manejar valores `None` serializándolos como JSON `null`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_

  - [ ]* 2.4 Escribir property test para config_hash (Property 2)
    - **Property 2: config_hash is a deterministic SHA-256 of effective config excluding source**
    - Generar diccionarios de configuración aleatorios con Hypothesis
    - Verificar formato (64 chars hex lowercase), determinismo (mismo input → mismo output), y exclusión de `source`/`config_hash`
    - `# Feature: alwaysprint-phase6-portal, Property 2: config_hash is a deterministic SHA-256 of effective config excluding source`
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.7**

  - [x] 2.5 Crear schemas Pydantic para telemetría y conectividad
    - Crear archivo `app/schemas/telemetry.py` con schemas de request/response para telemetría
    - Definir `TelemetryMessagePayload` para validar mensajes WebSocket entrantes
    - Definir `ConnectivityResultPayload` para validar mensajes WebSocket entrantes
    - Definir `TelemetryLogResponse` y `ConnectivityResultResponse` para endpoints REST
    - Definir `TelemetryStatsResponse` con campos de estadísticas agregadas
    - _Requirements: 5.1, 6.1, 6.5, 7.3, 8.3, 9.2_

- [x] 3. Servicios de persistencia backend
  - [x] 3.1 Implementar TelemetryService
    - Crear archivo `app/services/telemetry.py`
    - Implementar método `persist_telemetry(db, workstation_id, account_id, payload)` que crea un TelemetryLog
    - Implementar método `get_telemetry_history(db, workstation_id, account_id, from_dt, to_dt, limit)` con filtrado temporal y orden descendente
    - Implementar método `get_telemetry_stats(db, account_id)` con agregaciones de últimas 24h
    - Verificar tenant isolation en todas las queries (filtrar por account_id)
    - Calcular `disconnection_count` como longitud del array `disconnection_log`
    - _Requirements: 5.1, 5.2, 5.5, 7.3, 7.4, 9.2, 9.3_

  - [ ]* 3.2 Escribir property test para persistencia de telemetría (Property 3)
    - **Property 3: Telemetry message persistence preserves all payload fields**
    - Generar payloads de telemetría válidos con Hypothesis, persistir, verificar que el registro coincide
    - `# Feature: alwaysprint-phase6-portal, Property 3: Telemetry message persistence preserves all payload fields`
    - **Validates: Requirements 5.1, 5.2**

  - [x] 3.3 Implementar ConnectivityService
    - Crear archivo `app/services/connectivity.py`
    - Implementar método `persist_connectivity_result(db, workstation_id, account_id, payload)` que crea un ConnectivityResult
    - Implementar método `get_connectivity_history(db, workstation_id, account_id, check_id, from_dt, to_dt, limit)` con filtrado y orden descendente
    - Verificar tenant isolation en todas las queries
    - _Requirements: 6.1, 6.5, 6.6, 8.3, 8.4_

  - [ ]* 3.4 Escribir property test para persistencia de conectividad (Property 5)
    - **Property 5: Connectivity result persistence preserves all payload fields**
    - Generar payloads de connectivity_result válidos con Hypothesis, persistir, verificar que el registro coincide
    - `# Feature: alwaysprint-phase6-portal, Property 5: Connectivity result persistence preserves all payload fields`
    - **Validates: Requirements 6.1, 6.5**

- [x] 4. Checkpoint - Verificar modelos, schemas y servicios
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. WebSocket handlers — Telemetría y conectividad
  - [x] 5.1 Extender WebSocket handler para mensajes de telemetría
    - Modificar `app/api/v1/websocket/workstation.py` para manejar mensajes tipo `telemetry`
    - Validar payload con Pydantic schema `TelemetryMessagePayload`
    - Verificar que workstation_id existe para el account_id del sender (tenant isolation)
    - Persistir usando `TelemetryService.persist_telemetry()`
    - Tras persistir exitosamente, broadcast `telemetry_received` a operadores de la misma cuenta via `connection_manager.broadcast_to_account()`
    - Si validación falla: log ERROR, descartar mensaje, NO cerrar conexión
    - Si workstation_id no existe para la cuenta: log WARNING, descartar, NO cerrar conexión
    - Si escritura BD falla: log ERROR, omitir broadcast, NO cerrar conexión
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_

  - [x] 5.2 Extender WebSocket handler para mensajes de connectivity_result
    - Modificar `app/api/v1/websocket/workstation.py` para manejar mensajes tipo `connectivity_result`
    - Validar payload con Pydantic schema `ConnectivityResultPayload`
    - Verificar tenant isolation (workstation_id pertenece al account_id del sender)
    - Persistir usando `ConnectivityService.persist_connectivity_result()`
    - Tras persistir, broadcast `connectivity_result` a operadores de la misma cuenta
    - Manejar errores sin cerrar la conexión WebSocket
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [ ]* 5.3 Escribir property test para rechazo de mensajes inválidos (Property 4)
    - **Property 4: Invalid WebSocket messages are rejected without closing the connection**
    - Generar payloads inválidos (validación fallida o workstation inexistente) con Hypothesis
    - Verificar que se descartan sin persistir y sin cerrar la conexión
    - `# Feature: alwaysprint-phase6-portal, Property 4: Invalid WebSocket messages are rejected without closing the connection`
    - **Validates: Requirements 5.4, 5.5, 5.6, 6.3, 6.4, 6.6**

- [x] 6. Endpoints REST — Telemetría y conectividad
  - [x] 6.1 Implementar endpoint GET /api/v1/workstations/{id}/telemetry
    - Crear archivo `app/api/v1/endpoints/telemetry.py`
    - Implementar endpoint con parámetros opcionales: `from` (ISO 8601), `to` (ISO 8601), `limit` (1-1000, default 100)
    - Retornar array JSON de TelemetryLog ordenado por `recorded_at` DESC
    - Verificar tenant isolation: workstation debe pertenecer al account del usuario autenticado
    - Retornar 404 si workstation no existe o no pertenece a la cuenta
    - Retornar 401 si token ausente/inválido
    - Retornar 422 si parámetros inválidos (from > to, limit fuera de rango)
    - Retornar 200 con array vacío si no hay registros
    - Usar `Depends(get_current_user)` y `Depends(get_db)`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8_

  - [ ]* 6.2 Escribir property test para endpoint de telemetría (Property 6)
    - **Property 6: Telemetry endpoint returns correctly ordered and filtered results**
    - Generar conjuntos de TelemetryLog con timestamps aleatorios, consultar con parámetros from/to/limit
    - Verificar orden descendente, filtrado temporal correcto, y respeto del limit
    - `# Feature: alwaysprint-phase6-portal, Property 6: Telemetry endpoint returns correctly ordered and filtered results`
    - **Validates: Requirements 7.2, 7.3, 7.7**

  - [x] 6.3 Implementar endpoint GET /api/v1/workstations/{id}/connectivity
    - Crear archivo `app/api/v1/endpoints/connectivity.py`
    - Implementar endpoint con parámetros opcionales: `check_id` (string, max 255), `from`, `to`, `limit` (1-1000, default 100)
    - Retornar array JSON de ConnectivityResult ordenado por `recorded_at` DESC
    - Verificar tenant isolation, retornar 404/401/422 según corresponda
    - Retornar 200 con array vacío si no hay registros
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8_

  - [ ]* 6.4 Escribir property test para endpoint de conectividad (Property 7)
    - **Property 7: Connectivity endpoint returns correctly ordered and filtered results**
    - Generar conjuntos de ConnectivityResult, consultar con parámetros, verificar orden y filtrado
    - `# Feature: alwaysprint-phase6-portal, Property 7: Connectivity endpoint returns correctly ordered and filtered results`
    - **Validates: Requirements 8.2, 8.3, 8.7**

  - [x] 6.5 Implementar endpoint GET /api/v1/accounts/{id}/telemetry/stats
    - Agregar endpoint en `app/api/v1/endpoints/telemetry.py`
    - Computar estadísticas de últimas 24h UTC: total_workstations, workstations_reporting, avg_jobs_identified, contingency_active_count, queue_status_summary, last_updated
    - Verificar tenant isolation: account_id del token debe coincidir con {id} (o rol admin)
    - Retornar 404 si cuenta no existe o no coincide
    - Retornar objeto con zeros/null si no hay datos en 24h
    - Optimizar para respuesta < 2000ms con hasta 10000 workstations
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9_

  - [ ]* 6.6 Escribir property test para estadísticas de telemetría (Property 9)
    - **Property 9: Telemetry stats aggregation correctness**
    - Generar conjuntos de TelemetryLog con timestamps dentro/fuera de 24h
    - Verificar cálculos de workstations_reporting, avg_jobs_identified, contingency_active_count
    - `# Feature: alwaysprint-phase6-portal, Property 9: Telemetry stats aggregation correctness`
    - **Validates: Requirements 9.2, 9.3**

  - [x] 6.7 Registrar nuevos routers en app/api/v1/router.py
    - Importar y registrar router de telemetría
    - Importar y registrar router de conectividad
    - _Requirements: 7.1, 8.1, 9.1_

- [x] 7. Checkpoint - Verificar endpoints REST y WebSocket handlers
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 8. Tenant isolation — Test transversal
  - [ ]* 8.1 Escribir property test para tenant isolation (Property 8)
    - **Property 8: Tenant isolation — no cross-account data access**
    - Generar datos para múltiples cuentas, verificar que cada usuario solo ve datos de su cuenta
    - Verificar que requests a workstations de otra cuenta retornan 404
    - `# Feature: alwaysprint-phase6-portal, Property 8: Tenant isolation — no cross-account data access`
    - **Validates: Requirements 7.4, 7.5, 8.4, 8.5, 9.4, 9.5, 16.1, 16.2, 16.3, 16.4, 16.5**

- [x] 9. Frontend — Tipos TypeScript
  - [x] 9.1 Crear tipos TypeScript para telemetría y conectividad
    - Crear archivo `src/types/telemetry.ts` con interfaces `TelemetryEntry`, `ConnectivityResult`, `TelemetryStats`
    - Usar union types y literal types (no `any`), `| null` para campos ausentes en API
    - Re-exportar desde `src/types/index.ts`
    - _Requirements: 14.1, 14.2, 14.3, 14.6, 14.7_

  - [x] 9.2 Extender tipos de configuración y WebSocket
    - Modificar `src/types/config.ts`: agregar campos `connectivity_checks`, `locale`, `telemetry_enabled`, `telemetry_interval_seconds`, `config_hash` a `EffectiveConfig`
    - Definir interfaz `ConnectivityCheck` en `src/types/config.ts`
    - Modificar `src/types/websocket.ts`: agregar `TelemetryReceivedMessage` y `ConnectivityResultReceivedMessage`
    - Extender union type `OperatorMessage` con los nuevos tipos
    - _Requirements: 14.4, 14.5, 14.8, 15.1, 15.2, 15.3_

- [x] 10. Frontend — Componentes de configuración
  - [x] 10.1 Implementar componente ConnectivityCheckEditor
    - Crear archivo `src/components/ConnectivityCheckEditor.tsx`
    - Implementar tabla con columnas: ID, Tipo, URL/Host, Timeout (ms)
    - Implementar modal "Agregar check" con campos condicionales según tipo seleccionado
    - Implementar botón de eliminar por fila
    - Validar IDs únicos y máximo 50 checks
    - Mostrar/ocultar campos según tipo: URL para HTTP, host para TCP/Ping, hostname para DNS, port para TCP
    - Mostrar errores inline si validación falla al guardar
    - Usar componentes shadcn/ui y lucide-react icons
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 10.10_

  - [x] 10.2 Implementar componente LocaleSelector
    - Crear archivo `src/components/LocaleSelector.tsx`
    - Implementar selector con opciones: "" (Automático/Sistema), "es" (Español), "en" (English)
    - Mostrar valor actual guardado al cargar
    - Marcar configuración como modificada al cambiar
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

  - [x] 10.3 Integrar ConnectivityCheckEditor y LocaleSelector en página de configuración
    - Modificar `src/app/dashboard/config/page.tsx`
    - Agregar sección "Checks de Conectividad" con el editor
    - Agregar selector de locale
    - Incluir `connectivity_checks` y `locale` en el PUT request al guardar
    - _Requirements: 10.1, 10.6, 11.3_

- [x] 11. Frontend — Dashboard de telemetría
  - [x] 11.1 Crear página de dashboard de telemetría
    - Crear archivo `src/app/dashboard/telemetry/page.tsx`
    - Implementar cards de estadísticas en la parte superior (total reporting, errores, contingencia activa, avg release time)
    - Implementar tabla de workstations con última telemetría: nombre, queue_status (badge), contingency_active (badge), jobs_identified, avg_release_time_ms, disconnection_count
    - Al seleccionar workstation, mostrar historial de últimas 24h (max 100 entries, orden DESC)
    - Usar React Query con staleTime 60s y auto-refresh cada 60s
    - Implementar estados: loading skeleton, error con retry, empty-state
    - Usar `apiClient` existente para requests HTTP
    - Usar tipos estrictos `TelemetryEntry` y `TelemetryStats`
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7, 12.8, 12.9, 12.10_

- [x] 12. Frontend — Dashboard de conectividad en tiempo real
  - [x] 12.1 Crear página de dashboard de conectividad
    - Crear archivo `src/app/dashboard/connectivity/page.tsx`
    - Implementar lista de workstations con checks configurados y último resultado: check_id, check_type, success (indicador verde/rojo), latency_ms, error
    - Integrar hook `useWebSocket` para actualizaciones en tiempo real de `connectivity_result`
    - Al seleccionar workstation, mostrar historial de últimas 24h desde endpoint REST
    - Implementar estados: loading skeleton, error con retry
    - Usar tipos estrictos `ConnectivityResult` y `ConnectivityResultReceivedMessage`
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8, 13.9_

- [x] 13. Frontend — Navegación y wiring final
  - [x] 13.1 Agregar entradas de navegación en sidebar
    - Modificar `src/app/dashboard/layout.tsx`
    - Agregar entrada "Telemetría" apuntando a `/dashboard/telemetry` después de "workstations"
    - Agregar entrada "Conectividad" apuntando a `/dashboard/connectivity`
    - _Requirements: 12.1, 13.1_

  - [ ]* 13.2 Escribir tests de componentes frontend
    - Verificar renderizado de ConnectivityCheckEditor (tabla, modal, validación)
    - Verificar renderizado de LocaleSelector
    - Verificar que useWebSocket procesa correctamente los nuevos tipos de mensaje
    - Verificar compilación TypeScript sin errores (`npm run build`)
    - _Requirements: 14.8, 17.4_

- [x] 14. Checkpoint final - Verificar integración completa
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marcadas con `*` son opcionales y pueden omitirse para un MVP más rápido
- Cada task referencia requirements específicos para trazabilidad
- Los checkpoints aseguran validación incremental
- Property tests validan propiedades universales de correctitud (Hypothesis, min 100 ejemplos)
- Unit tests validan ejemplos específicos y edge cases
- Todos los comentarios y mensajes de log deben estar en español (Requirement 17)
- No usar `any` en TypeScript ni `print()` en Python (Requirement 17)
- Tenant isolation es transversal a todos los endpoints y handlers (Requirement 16)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.5", "9.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "2.1", "9.2"] },
    { "id": 2, "tasks": ["2.2", "2.3"] },
    { "id": 3, "tasks": ["2.4", "3.1", "3.3"] },
    { "id": 4, "tasks": ["3.2", "3.4", "5.1", "5.2"] },
    { "id": 5, "tasks": ["5.3", "6.1", "6.3", "6.5"] },
    { "id": 6, "tasks": ["6.2", "6.4", "6.6", "6.7"] },
    { "id": 7, "tasks": ["8.1", "10.1", "10.2"] },
    { "id": 8, "tasks": ["10.3", "11.1"] },
    { "id": 9, "tasks": ["12.1", "13.1"] },
    { "id": 10, "tasks": ["13.2"] }
  ]
}
```
