# Implementation Plan: Bulk Actions UX Improvements

## Overview

Implementación de tres mejoras UX para el sistema de acciones masivas: enriquecimiento de workstations fallidas con hostname/IP, endpoint de detección de sesión activa, y estimación de tiempo restante en frontend. Se sigue un orden backend → frontend → traducciones → tests.

## Tasks

- [x] 1. Backend schemas y modelo de datos
  - [x] 1.1 Agregar `FailedWorkstationDetail` y `ActiveSessionInfo` schemas en `app/schemas/bulk_actions.py`
    - Crear clase `FailedWorkstationDetail(BaseModel)` con campos `id: str`, `hostname: Optional[str]`, `ip_private: str` (default "unknown")
    - Crear clase `ActiveSessionInfo(BaseModel)` con campos `is_active: bool`, `session_id: Optional[str]`, `org_id: Optional[str]`, `org_name: Optional[str]`, `label: Optional[str]`, `started_at: Optional[datetime]`, `total: Optional[int]`, `sent: Optional[int]`
    - _Requirements: 1.1, 2.1, 2.4, 2.5_

  - [x] 1.2 Modificar `BulkSessionStatus` schema para agregar campos enriquecidos
    - Agregar campo `failed_workstation_details: list[FailedWorkstationDetail] = Field(default=[], ...)`
    - Agregar campo `delay_ms: Optional[int] = Field(default=None, ...)`
    - Mantener el campo `failed_workstations` existente para backward compatibility
    - _Requirements: 1.1, 1.5_

- [x] 2. Backend service: enriquecimiento y sesión activa
  - [x] 2.1 Implementar método `_enrich_failed_workstations` en `BulkExecutionService`
    - Consultar tabla `workstations` filtrando por IDs de `failed_workstations` del hash Redis
    - Para IDs existentes en BD: retornar hostname e ip_private reales
    - Para IDs no existentes: retornar `hostname=None`, `ip_private="unknown"`
    - Preservar el orden de la lista de entrada
    - Usar `SessionLocal()` para nueva sesión de BD dentro del método estático
    - _Requirements: 1.1, 1.2, 1.3_

  - [x] 2.2 Modificar `get_session_status` para incluir `failed_workstation_details` y `delay_ms`
    - Llamar a `_enrich_failed_workstations` con los IDs del hash Redis cuando hay workstations fallidas
    - Incluir `delay_ms` del hash Redis en la respuesta
    - Manejar errores de enriquecimiento con graceful degradation (log warning, retornar lista vacía)
    - _Requirements: 1.1, 1.2, 1.3, 1.5_

  - [x] 2.3 Implementar método `get_active_session` en `BulkExecutionService`
    - Para role operator: verificar solo `bulk:running:{user.organization_id}` en Redis
    - Para role admin: escanear con patrón `bulk:running:*` usando SCAN
    - Si detecta sesión activa: leer hash `bulk:session:{session_id}` para extraer `org_id`, `label`, `started_at`, `total`, `sent`
    - Retornar `ActiveSessionInfo` con `is_active=true/false` según corresponda
    - Manejar Redis no disponible con HTTP 503
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [x] 2.4 Modificar `_execute_bulk` para incluir `failed_workstation_details` en mensajes WebSocket
    - En cada progress report vía WebSocket, incluir `failed_workstation_details` enriquecido
    - Llamar a `_enrich_failed_workstations(failed_ws)` solo cuando hay errores (evitar queries innecesarias)
    - Serializar con `.model_dump()` para envío por WebSocket
    - _Requirements: 1.4_

- [x] 3. Backend endpoint: sesión activa
  - [x] 3.1 Implementar endpoint `GET /bulk-actions/active` en `app/api/v1/endpoints/bulk_actions.py`
    - Agregar ruta `@router.get("/active", response_model=ActiveSessionInfo)`
    - Rechazar con HTTP 403 si rol es `readonly`
    - Llamar a `bulk_service.get_active_session(user)`
    - Importar `ActiveSessionInfo` en el archivo de endpoints
    - _Requirements: 2.1, 2.7_

- [x] 4. Checkpoint - Verificar backend
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Frontend types y utilidades
  - [x] 5.1 Agregar interfaces `FailedWorkstationDetail` y `ActiveSessionInfo` en `src/types/bulk-actions.ts`
    - Crear interface `FailedWorkstationDetail` con `id: string`, `hostname: string | null`, `ip_private: string`
    - Crear interface `ActiveSessionInfo` con campos según design (is_active, session_id, org_id, org_name, label, started_at, total, sent)
    - Modificar `BulkSessionStatus` para agregar `failed_workstation_details: FailedWorkstationDetail[]` y `delay_ms: number | null`
    - Modificar `BulkProgressMessage` para agregar `failed_workstation_details: FailedWorkstationDetail[]`
    - _Requirements: 1.1, 1.5, 2.1_

  - [x] 5.2 Implementar funciones de estimación de tiempo en `src/lib/bulk-actions-utils.ts`
    - Agregar `calcRemainingMs(total, sent, elapsedMs)`: retorna `Math.round(((total - sent) / sent) * elapsedMs)` o `null` si `sent === 0`
    - Agregar `formatRemainingTime(ms)`: `< 60000` → `~{N}s`, `>= 60000` → `~{M}m {S}s`
    - Agregar `calcETA(remainingMs)`: retorna `new Date(Date.now() + remainingMs)`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x] 5.3 Agregar método `getActive()` al API client en `src/lib/api.ts`
    - Agregar método en la sección de bulk actions del API client
    - Debe hacer `GET /bulk-actions/active` y retornar `ActiveSessionInfo`
    - _Requirements: 2.1_

- [x] 6. Frontend UI components
  - [x] 6.1 Implementar componente `ActiveSessionAlert` en la página de bulk-actions
    - Al montar la página, llamar a `GET /bulk-actions/active`
    - Si `is_active === true`, mostrar alert card con info de sesión (org, label, progreso)
    - Incluir botón "Ver Progreso" que establece el sessionId en state
    - Usar traducciones de next-intl para textos
    - _Requirements: 2.1, 2.4_

  - [x] 6.2 Implementar sección `FailedWorkstationsList` en `ExecutionProgressSection`
    - Sección expandible que muestra `failed_workstation_details` cuando hay items
    - Cada item muestra hostname (o UUID si null) y la IP privada
    - Usar traducciones de next-intl para labels
    - _Requirements: 1.1, 1.3_

  - [x] 6.3 Implementar visualización de estimación de tiempo en `ExecutionProgressSection`
    - Debajo del tiempo transcurrido, mostrar tiempo restante con `formatRemainingTime(calcRemainingMs(...))`
    - Mostrar ETA formateada con `Intl.DateTimeFormat` usando locale activo
    - Si `sent === 0`, mostrar "Calculando..." (i18n key)
    - Al llegar a estado terminal, ocultar estimación y mostrar tiempo final
    - Actualizar en cada mensaje WebSocket de progreso sin API calls adicionales
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

- [x] 7. Traducciones i18n
  - [x] 7.1 Agregar keys de traducción en `messages/es.json` y `messages/en.json`
    - Agregar bajo namespace `bulkActions` las keys: `activeSessionAlert`, `activeSessionOrg`, `activeSessionAction`, `viewProgress`, `remainingTime`, `eta`, `calculating`, `failedWorkstations`, `hostname`, `ipPrivate`, `unknownIp`
    - Valores en español (es.json) y en inglés (en.json) según tabla del design
    - _Requirements: 3.8_

- [x] 8. Checkpoint - Verificar integración frontend
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Property tests y unit tests
  - [x] 9.1 Write property test: Failed workstation enrichment correctness
    - **Property 1: Failed workstation enrichment correctness**
    - **Validates: Requirements 1.1, 1.3**
    - Para cualquier set de IDs (existentes y no existentes en BD), verificar que `_enrich_failed_workstations` produce lista con mismo largo, preserva orden, y aplica hostname/ip_private correcto según existencia en BD

  - [x] 9.2 Write property test: Backward compatibility of failed workstations response
    - **Property 2: Backward compatibility of failed workstations response**
    - **Validates: Requirements 1.5**
    - Para cualquier sesión con failed workstations, verificar que `failed_workstations` (list[str]) y `failed_workstation_details[*].id` contienen los mismos IDs

  - [x] 9.3 Write property test: Active session tenant isolation
    - **Property 3: Active session tenant isolation**
    - **Validates: Requirements 2.2, 2.3**
    - Para operador: solo ve sesiones de su organización. Para admin: ve sesiones de cualquier organización.

  - [x] 9.4 Write property test: Remaining time calculation
    - **Property 4: Remaining time calculation**
    - **Validates: Requirements 3.1, 3.3**
    - Para total > 0, sent > 0, elapsedMs > 0: verificar `calcRemainingMs` retorna `Math.round(((total - sent) / sent) * elapsedMs)`. Para sent === 0: retorna null.

  - [x] 9.5 Write property test: ETA calculation
    - **Property 5: ETA calculation**
    - **Validates: Requirements 3.2**
    - Para cualquier remainingMs positivo, `calcETA(remainingMs)` retorna Date con timestamp = `Date.now() + remainingMs` (tolerancia 5ms)

  - [x] 9.6 Write property test: Time formatting threshold
    - **Property 6: Time formatting threshold**
    - **Validates: Requirements 3.4, 3.5**
    - Para ms < 60000: formato `~{N}s`. Para ms >= 60000: formato `~{M}m {S}s`. Verificar patrón regex y valores correctos.

- [x] 10. Final checkpoint - Verificar todo
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- El backend usa Python 3.12 con FastAPI, el frontend usa TypeScript con Next.js 15
- Los property tests de backend usan Hypothesis, los de frontend usan fast-check con Vitest
- Importar `Base` siempre desde `app.core.database`, no desde `app.db`
- Mantener tenant isolation en todas las queries (filtrar por `organization_id`)
- El endpoint `GET /active` debe ir ANTES de `/status/{session_id}` en el router para evitar conflictos de matching

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "5.1"] },
    { "id": 2, "tasks": ["2.1", "2.3", "5.2", "5.3"] },
    { "id": 3, "tasks": ["2.2", "2.4", "3.1"] },
    { "id": 4, "tasks": ["6.1", "6.2", "6.3", "7.1"] },
    { "id": 5, "tasks": ["9.1", "9.2", "9.3", "9.4", "9.5", "9.6"] }
  ]
}
```
