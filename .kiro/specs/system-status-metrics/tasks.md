# Implementation Plan: System Status Metrics

## Overview

Implementación de métricas de escalabilidad para el sistema AlwaysPrint Cloud, orientado a monitorear la capacidad de soportar 5000 workstations concurrentes. Incluye un backend con 5 sub-colectores de métricas (WebSocket, memoria Python, file descriptors, red, pool BD), un endpoint protegido, integración con el scheduler existente, migración Alembic, y un componente frontend MetricsCard con indicadores de color por umbral.

## Tasks

- [x] 1. Esquemas Pydantic y tipos base del backend
  - [x] 1.1 Crear schemas Pydantic para las 5 métricas de escalabilidad
    - Crear archivo `app/schemas/scalability_metrics.py`
    - Definir `WebSocketMetricsResponse`, `PythonMemoryResponse`, `FileDescriptorResponse`, `NetworkTrafficResponse`, `DbPoolResponse`, y `ScalabilityMetricsResponse`
    - Incluir validaciones de campo (`ge`, `le`, `gt`) según diseño
    - Incluir campo `collected_at: datetime` en la respuesta principal
    - Exportar schemas en `app/schemas/__init__.py`
    - _Requirements: 1.1, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 4.1, 4.2, 4.3, 5.1, 5.2, 6.1, 6.2, 6.3_

- [x] 2. ScalabilityMetricsCollector — sub-colectores de sistema
  - [x] 2.1 Implementar colector de conexiones WebSocket
    - Crear archivo `app/services/scalability_metrics.py`
    - Implementar clase `ScalabilityMetricsCollector` con método `collect_websocket_metrics()`
    - Obtener `workstation_count` y `operator_count` del `ConnectionManager` singleton
    - Calcular `total = workstation_count + operator_count`
    - Manejar error del ConnectionManager retornando 0 y `data_available=False`
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 2.2 Write property test: WebSocket total is sum of components
    - **Property 2: WebSocket total is sum of components**
    - **Validates: Requirements 2.3**

  - [x] 2.3 Implementar colector de memoria del proceso Python
    - Implementar método `collect_python_memory()` en `ScalabilityMetricsCollector`
    - Leer `VmRSS` de `/proc/self/status` y convertir kB → MB (`round(vmrss_kb / 1024, 2)`)
    - Obtener memoria total del contenedor del `SystemStatusCollector`
    - Calcular `avg_per_workstation_mb = round(rss_mb / ws_count, 2)` cuando `ws_count > 0`, retornar 0 si `ws_count == 0`
    - Retornar `None` si lectura de `/proc/self/status` falla
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x] 2.4 Write property tests: VmRSS conversion y memory per workstation
    - **Property 3: VmRSS kB to MB conversion**
    - **Property 4: Memory per workstation average**
    - **Validates: Requirements 3.1, 3.3**

  - [x] 2.5 Implementar colector de file descriptors
    - Implementar método `collect_file_descriptors()` en `ScalabilityMetricsCollector`
    - Contar entradas en `/proc/self/fd` para obtener `open_count`
    - Obtener `limit` de `resource.getrlimit(resource.RLIMIT_NOFILE)[0]` (soft limit)
    - Calcular `usage_percent = round(open_count / limit * 100, 1)` si `limit > 0`, retornar `None` si `limit == 0`
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [x] 2.6 Write property test: Percentage calculation correctness
    - **Property 5: Percentage calculation correctness**
    - **Validates: Requirements 4.3, 6.3**

  - [x] 2.7 Implementar colector de tráfico de red
    - Implementar método `collect_network_traffic()` en `ScalabilityMetricsCollector`
    - Parsear `/proc/net/dev` para interfaces no-loopback, sumar `rx_bytes` y `tx_bytes`
    - Mantener estado in-memory (`_prev_net_reading`, `_prev_net_timestamp`)
    - Calcular tasas `rx_rate_bps` y `tx_rate_bps` si hay medición anterior y delta_t >= 0.5s
    - Si delta_t < 0.5s, retornar tasas previas sin recalcular
    - Si `current_bytes < prev_bytes` (counter reset), descartar anterior y retornar `null` para tasas
    - Primera invocación: almacenar referencia y retornar `null` para tasas
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x] 2.8 Write property tests: Network interface summing y rate calculation
    - **Property 6: Network interface traffic summing**
    - **Property 7: Network rate calculation**
    - **Validates: Requirements 5.1, 5.2**

  - [x] 2.9 Implementar colector del pool de base de datos
    - Implementar método `collect_db_pool_metrics(db)` en `ScalabilityMetricsCollector`
    - Leer estado del pool SQLAlchemy: `checked_out`, `idle`, `pool_size`, `overflow`, `max_overflow`
    - Ejecutar query a `pg_stat_activity` filtrada por usuario de la app, contando conexiones con state distinto de 'idle'
    - Calcular `usage_percent = round(checked_out / pool_size * 100, 1)`
    - Si query a `pg_stat_activity` falla, retornar `null` para `pg_active_connections`
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [x] 3. Método collect_all_metrics y degradación parcial
  - [x] 3.1 Implementar `collect_all_metrics()` con `asyncio.gather`
    - Ejecutar los 5 sub-colectores en paralelo con `return_exceptions=True`
    - Para cada colector que falle, asignar `None` al campo correspondiente
    - Registrar errores con structured logging (`logger.warning` con `metric_name`, `error_type`, `error_detail`)
    - Instanciar singleton a nivel de módulo: `scalability_collector = ScalabilityMetricsCollector()`
    - Ensamblar `ScalabilityMetricsResponse` con `collected_at=datetime.utcnow()`
    - _Requirements: 1.1, 1.5, 7.3_

  - [x] 3.2 Write property test: Graceful degradation under partial collector failures
    - **Property 1: Graceful degradation under partial collector failures**
    - **Validates: Requirements 1.5, 7.3**

- [x] 4. Checkpoint - Backend collectors
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Endpoint API y autenticación
  - [x] 5.1 Crear endpoint `GET /api/v1/system/metrics`
    - Crear archivo `app/api/v1/endpoints/system_metrics.py`
    - Implementar router con `prefix="/system"` y `tags=["system-metrics"]`
    - Proteger con `Depends(get_current_admin_user)` para autenticación JWT + rol admin
    - Invocar `scalability_collector.collect_all_metrics()` pasando la sesión de BD
    - Retornar `ScalabilityMetricsResponse` con HTTP 200
    - Registrar el router en `app/api/v1/api.py`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 5.2 Write unit tests de autenticación/autorización del endpoint
    - Test con token inválido → HTTP 401
    - Test con token válido no-admin → HTTP 403
    - Test con token válido admin → HTTP 200
    - _Requirements: 1.2, 1.3_

- [x] 6. Integración con StatusScheduler
  - [x] 6.1 Integrar `collect_all_metrics()` en `SystemStatusCollector.collect_all()`
    - Modificar `app/services/status_scheduler.py` (o el archivo donde reside `SystemStatusCollector.collect_all()`)
    - Añadir llamada a `scalability_collector.collect_all_metrics()` dentro de `collect_all()`
    - Envolver en try/except: si falla, log error y asignar `None`
    - Incluir resultado en el dict/snapshot retornado
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

- [x] 7. Migración Alembic
  - [x] 7.1 Crear migración para campo `scalability_metrics_json`
    - Generar migración Alembic: añadir columna `scalability_metrics_json` (tipo `Text`, nullable=True) a la tabla `status_snapshots`
    - Implementar `upgrade()` y `downgrade()`
    - Actualizar modelo SQLAlchemy `StatusSnapshot` si corresponde
    - _Requirements: 7.2_

- [x] 8. Checkpoint - Backend completo
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Frontend — tipos TypeScript y utilidades
  - [x] 9.1 Crear tipos TypeScript para las métricas de escalabilidad
    - Crear archivo `src/types/scalability-metrics.ts`
    - Definir interfaces: `WebSocketMetrics`, `PythonMemoryMetrics`, `FileDescriptorMetrics`, `NetworkTrafficMetrics`, `DbPoolMetrics`, `ScalabilityMetrics`
    - _Requirements: 1.1, 8.1_

  - [x] 9.2 Implementar función `evaluateThreshold` y configuraciones de umbrales
    - Crear archivo `src/lib/utils/threshold.ts`
    - Implementar función pura `evaluateThreshold(value, config): ThresholdColor | null`
    - Definir `ThresholdConfig` interface con `greenMax` y `yellowMax`
    - Crear constantes de umbral para cada métrica: WS total (3000/4500), memoria/ws (2/4), FD% (60/80), pool% (60/80), tx rate MB/s (50/80)
    - Retornar `null` si `value === null`
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_

  - [x] 9.3 Write property test: Threshold color evaluation
    - **Property 8: Threshold color evaluation with boundary inclusivity**
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7**

- [x] 10. Frontend — traducciones i18n
  - [x] 10.1 Agregar traducciones `next-intl` para métricas de escalabilidad
    - Agregar claves en archivos de mensajes (es/en) bajo namespace `systemMetrics`
    - Incluir labels para cada métrica, unidades, estados (loading, error, no disponible), y títulos de card
    - _Requirements: 8.3, 8.4, 8.5_

- [x] 11. Frontend — componente MetricsCard
  - [x] 11.1 Implementar componente `MetricsCard`
    - Crear archivo `src/app/dashboard/admin/system-status/components/MetricsCard.tsx`
    - Implementar fetch al endpoint `/api/v1/system/metrics` con token JWT
    - Renderizar las 5 métricas con label, valor numérico + unidad, e indicador de color
    - Aplicar `evaluateThreshold` para determinar color (verde/amarillo/rojo) de cada métrica
    - Usar `useTranslations` de `next-intl` para todos los textos
    - Manejar estados: loading (spinner), error (mensaje localizado), métrica null (texto "no disponible", sin indicador de color)
    - Implementar botón de refresh manual
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

  - [x] 11.2 Integrar `MetricsCard` en la página System Status
    - Importar y renderizar `MetricsCard` en la página existente de System Status
    - Posicionar como nueva sección/card dedicada
    - _Requirements: 8.1_

- [x] 12. Checkpoint - Frontend completo
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Tests de integración
  - [x] 13.1 Write integration tests del endpoint completo
    - Test endpoint con DB real/fixture: verificar response 200 con estructura correcta
    - Test `collect_all()` del scheduler incluye `scalability_metrics` en resultado
    - Test persistencia: snapshot con `scalability_metrics_json` no-null después de recolección
    - Test query `pg_stat_activity`: retorna conteo >= 0
    - _Requirements: 1.1, 7.1, 7.2, 6.2_

  - [x] 13.2 Write integration tests del frontend MetricsCard
    - Test render con datos completos → 5 métricas visibles con colores correctos
    - Test render con métrica `null` → texto "no disponible" sin indicador de color
    - Test render en estado error → mensaje localizado de error
    - Test render en estado loading → spinner visible
    - _Requirements: 8.1, 8.2, 8.4, 8.5, 8.6_

- [x] 14. Final checkpoint
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- Backend: Python 3.12, FastAPI, SQLAlchemy async, Hypothesis para PBT
- Frontend: TypeScript, Next.js 15, React 18, fast-check para PBT
- Importar `Base` siempre desde `app.core.database`
- Structured logging en español para todos los mensajes
- El colector de red mantiene estado in-memory (se pierde al reiniciar, comportamiento aceptable)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "2.5", "2.7", "9.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.6", "2.9", "9.2"] },
    { "id": 3, "tasks": ["2.4", "2.8", "3.1", "9.3"] },
    { "id": 4, "tasks": ["3.2", "5.1", "10.1"] },
    { "id": 5, "tasks": ["5.2", "6.1", "7.1", "11.1"] },
    { "id": 6, "tasks": ["11.2"] },
    { "id": 7, "tasks": ["13.1", "13.2"] }
  ]
}
```
