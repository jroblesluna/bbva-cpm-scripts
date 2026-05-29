# Implementation Plan: System Status Monitoring

## Overview

Implementación del sistema de monitoreo automatizado de infraestructura para AlwaysPrint Cloud. El backend recolecta métricas del sistema (CPU, RAM, disco, swap, Docker, servicios) directamente desde la EC2 usando psutil y Docker SDK, las almacena en PostgreSQL, y las expone via API REST protegida con `require_admin`. El frontend presenta un dashboard con gauges, alertas por umbrales, y gráficos históricos de 30 días usando recharts.

## Tasks

- [x] 1. Modelos de datos y migración Alembic
  - [x] 1.1 Crear modelos SQLAlchemy para system status
    - Crear `app/models/system_status.py` con las 4 tablas: `status_snapshots`, `metric_records`, `health_check_results`, `container_metrics`
    - Importar `Base` desde `app.core.database`
    - Definir relaciones con `ondelete="CASCADE"` y los índices especificados en el diseño
    - Registrar modelos en `app/models/__init__.py`
    - _Requirements: 4.1, 4.2, 4.5_

  - [x] 1.2 Crear migración Alembic
    - Generar migración con `alembic revision --autogenerate -m "add_system_status_tables"`
    - Verificar que crea las 4 tablas con índices y foreign keys correctos
    - _Requirements: 4.1, 4.2, 4.5_

  - [x] 1.3 Crear schemas Pydantic para system status
    - Crear `app/schemas/system_status.py` con todos los schemas de request/response definidos en el diseño
    - Incluir: `StatusSnapshotResponse`, `OsMetricsResponse`, `ContainerMetricsResponse`, `HealthCheckResponse`, `HistoryDataPoint`, `HistoryResponse`, `MetricStats`, `ServiceUptimeResponse`, `AlertResponse`, `HistoryQueryParams`
    - _Requirements: 4.1, 4.2, 6.1, 7.1_

- [x] 2. Servicio de recolección de métricas del sistema
  - [x] 2.1 Implementar recolección de métricas OS
    - Crear `app/services/system_status.py` con la clase `SystemStatusCollector`
    - Implementar `collect_os_metrics()` usando `psutil`: RAM (total, usada, disponible, %), disco (total, usado, disponible, %), CPU (% promedio último minuto), swap (total, usado, disponible), uptime
    - Conversión a MB (bytes / 1048576), porcentajes con 1 decimal
    - Manejo de errores individuales: si una métrica falla, registrar error y continuar con las demás
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6, 1.9_

  - [x] 2.2 Write property test: Metric calculation correctness
    - **Property 1: Metric calculation correctness**
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4**

  - [x] 2.3 Implementar recolección de métricas Docker
    - Implementar `collect_docker_metrics()` usando Docker SDK (`docker` package)
    - Obtener stats por contenedor: CPU%, memoria usada/límite en MB, network I/O en bytes, estado, uptime
    - Timeout de 10 segundos por comando Docker
    - Si Docker daemon no disponible: retornar `docker_available=False` y continuar
    - _Requirements: 1.5, 1.7, 1.8_

  - [x] 2.4 Write property test: Docker stats parsing correctness
    - **Property 2: Docker stats parsing correctness**
    - **Validates: Requirements 1.5, 1.7**

  - [x] 2.5 Write property test: Partial failure resilience
    - **Property 3: Partial failure resilience**
    - **Validates: Requirements 1.8, 1.9**

- [x] 3. Servicio de health checks
  - [x] 3.1 Implementar verificaciones de servicios
    - Añadir `collect_health_checks()` al `SystemStatusCollector`
    - Backend: HTTP GET a `http://localhost:8000/api/v1/health`, disponible si respuesta contiene "healthy"
    - Frontend: HTTP GET a `http://localhost:3000`, disponible si status code es 200, 302 o 307
    - Nginx: verificar estado via `systemctl is-active nginx`
    - Redis: verificar contenedor Docker en estado "running"
    - RDS: verificar conectividad con PostgreSQL (query simple)
    - SSL: verificar certificado, calcular días restantes, clasificar (valid >14, warning 1-14, expired <=0)
    - Timeout de 10 segundos por servicio
    - Generar resumen: conteo de ok, warning, failed
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8_

  - [x] 3.2 Write property test: Backend health check classification
    - **Property 4: Backend health check classification**
    - **Validates: Requirements 2.1**

  - [x] 3.3 Write property test: Frontend health check classification by status code
    - **Property 5: Frontend health check classification by status code**
    - **Validates: Requirements 2.2**

  - [x] 3.4 Write property test: SSL certificate days classification
    - **Property 6: SSL certificate days classification**
    - **Validates: Requirements 2.6**

  - [x] 3.5 Write property test: Health check summary counts
    - **Property 7: Health check summary counts**
    - **Validates: Requirements 2.8**

- [x] 4. Checkpoint - Verificar recolección de métricas
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Lógica de estado general y alertas
  - [x] 5.1 Implementar cálculo de estado general y generación de alertas
    - Añadir `calculate_overall_status()` al collector: healthy/degraded/critical según umbrales
    - Implementar lógica de umbrales: memoria >80%, disco >85%, CPU >90%, SSL <14 días, contenedor no running
    - Generar `AlertResponse` para cada umbral superado
    - Estado `critical` si alguna métrica supera umbral crítico, `degraded` si hay warnings
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_

  - [x] 5.2 Write property test: Threshold alert generation
    - **Property 12: Threshold alert generation**
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.7**

- [x] 6. Persistencia y retención de datos
  - [x] 6.1 Implementar persistencia de snapshots
    - Implementar `save_snapshot()` que persiste StatusSnapshot + MetricRecords + HealthCheckResults + ContainerMetrics en una transacción atómica
    - Rollback completo si falla cualquier parte de la escritura
    - Reintentar hasta 3 veces con 5 segundos entre intentos si PostgreSQL no disponible
    - _Requirements: 4.1, 4.2, 4.5, 4.6, 4.7_

  - [x] 6.2 Implementar limpieza de datos antiguos
    - Implementar `cleanup_old_snapshots()` que elimina registros >90 días
    - CASCADE elimina MetricRecords, HealthCheckResults y ContainerMetrics asociados
    - Ejecutar durante cada ciclo de recolección
    - _Requirements: 4.3, 4.4_

  - [x] 6.3 Write property test: Snapshot persistence round-trip
    - **Property 9: Snapshot persistence round-trip**
    - **Validates: Requirements 4.1, 4.2, 4.5**

  - [x] 6.4 Write property test: Data retention cleanup
    - **Property 10: Data retention cleanup**
    - **Validates: Requirements 4.3, 4.4**

  - [x] 6.5 Write property test: Transaction atomicity on failure
    - **Property 11: Transaction atomicity on failure**
    - **Validates: Requirements 4.7**

- [x] 7. Scheduler con APScheduler
  - [x] 7.1 Implementar StatusScheduler
    - Crear `app/services/status_scheduler.py` con la clase `StatusScheduler`
    - Integrar APScheduler (`AsyncIOScheduler`) en el lifespan de FastAPI (modificar `app/main.py`)
    - Programar ejecución a las 0:00, 6:00, 12:00, 18:00 UTC
    - Protección contra ejecuciones concurrentes (lock asyncio)
    - Reintento: si falla, reintentar una vez después de 5 minutos; si el reintento falla, esperar siguiente programada
    - Timeout de 10 minutos por ejecución
    - Método `trigger_manual_collection()` para ejecución bajo demanda
    - Retornar HTTP 409 si ya hay ejecución en curso
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 7.2 Write property test: Concurrency protection
    - **Property 8: Concurrency protection**
    - **Validates: Requirements 3.6**

- [x] 8. Checkpoint - Verificar backend completo
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. API endpoints
  - [x] 9.1 Implementar endpoints de system status
    - Crear `app/api/v1/endpoints/system_status.py` con los 5 endpoints:
      - `GET /system-status/current` — último snapshot completo
      - `GET /system-status/history` — serie temporal (params: days, metric)
      - `GET /system-status/services` — historial de disponibilidad (uptime %)
      - `POST /system-status/collect` — trigger recolección manual
      - `GET /system-status/alerts` — alertas activas
    - Todos protegidos con `require_admin`
    - Registrar router en `app/api/v1/router.py`
    - Implementar lógica de queries: filtrado por rango temporal, cálculo de estadísticas agregadas (avg, max, min), cálculo de uptime %, cobertura de datos
    - _Requirements: 5.1, 5.2, 5.3, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

  - [x] 9.2 Write property test: Time range filtering
    - **Property 13: Time range filtering**
    - **Validates: Requirements 7.1, 7.2**

  - [x] 9.3 Write property test: Aggregate statistics correctness
    - **Property 14: Aggregate statistics correctness**
    - **Validates: Requirements 7.4**

  - [x] 9.4 Write property test: Service uptime calculation
    - **Property 15: Service uptime calculation**
    - **Validates: Requirements 7.5**

  - [x] 9.5 Write property test: Data coverage calculation
    - **Property 16: Data coverage calculation**
    - **Validates: Requirements 7.6**

- [x] 10. Montar Docker socket en docker-compose
  - [x] 10.1 Actualizar docker-compose para montar Docker socket
    - Modificar la plantilla `user_data.sh.tpl` (Terraform) para añadir el volumen `/var/run/docker.sock:/var/run/docker.sock` al servicio backend en el docker-compose generado
    - Añadir dependencias `psutil`, `docker`, `apscheduler`, `httpx` al `requirements.txt`
    - _Requirements: 1.5, 1.7, 1.8_

- [x] 11. Checkpoint - Verificar API y configuración
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Frontend - Tipos y API client
  - [x] 12.1 Crear tipos TypeScript para system status
    - Crear `src/types/system-status.ts` con interfaces: `StatusSnapshot`, `OsMetrics`, `ContainerMetrics`, `HealthCheck`, `Alert`, `HistoryDataPoint`, `HistoryResponse`, `MetricStats`, `ServiceUptime`
    - _Requirements: 6.1, 7.1_

  - [x] 12.2 Crear funciones de API client
    - Crear `src/lib/api/system-status.ts` con funciones para llamar a los 5 endpoints del backend
    - Usar el patrón existente del proyecto (fetch con token JWT)
    - _Requirements: 5.1, 6.1, 7.1_

- [x] 13. Frontend - Dashboard de estado actual
  - [x] 13.1 Implementar página principal de system status
    - Crear `src/app/dashboard/admin/system-status/page.tsx`
    - Layout con tabs: "Estado Actual" y "Histórico"
    - Tab "Estado Actual": gauges circulares (CPU, RAM, Disco), estado Docker por contenedor, tabla de health checks, sección de alertas, botón de recolección manual
    - Indicadores de color según umbrales (verde/amarillo/rojo)
    - Banner fijo para estado `critical`
    - Fecha/hora de última recolección en zona horaria del usuario
    - Estado vacío si no hay snapshots
    - Botón de recolección manual con loading state y timeout de 30s
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8_

  - [x] 13.2 Write frontend tests for system status dashboard
    - Tests con vitest + React Testing Library
    - Verificar: renderizado de gauges con valores límite, estado vacío, alertas (max 10), colores de umbrales
    - _Requirements: 6.1, 6.2, 8.1, 8.8_

- [x] 14. Frontend - Reportes históricos
  - [x] 14.1 Implementar tab de histórico con gráficos recharts
    - Gráficos de línea temporal para memoria, disco, CPU, swap (últimos 30 días)
    - Selector de rango: 7, 14, 30 días
    - Eje Y de 0% a 100%, resolución mínima 1 punto/hora
    - Resaltar puntos que superan umbrales con marcador diferenciado
    - Estadísticas agregadas (promedio, máximo, mínimo) por período
    - Historial de disponibilidad (uptime %) por servicio
    - Indicar visualmente intervalos sin datos y % de cobertura
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

- [x] 15. Frontend - Control de acceso y navegación
  - [x] 15.1 Implementar control de acceso en frontend
    - Añadir enlace "System Status" al menú de navegación admin (visible solo para rol admin)
    - Ocultar sección y enlace para usuarios sin rol admin
    - Redirigir a dashboard principal si usuario sin admin accede directamente a la URL
    - _Requirements: 5.4, 5.5, 5.6_

- [x] 16. Checkpoint final - Verificar integración completa
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- Backend: Python 3.12, FastAPI, SQLAlchemy, psutil, docker SDK, APScheduler, httpx, Hypothesis
- Frontend: TypeScript, Next.js 15, React 18, recharts, shadcn/ui, vitest
- Todos los comentarios y logs en español
- Importar Base desde `app.core.database`
- Docker socket se monta via `user_data.sh.tpl` (Terraform template)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.3", "10.1"] },
    { "id": 1, "tasks": ["1.2", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "3.1"] },
    { "id": 3, "tasks": ["2.4", "2.5", "3.2", "3.3", "3.4", "3.5"] },
    { "id": 4, "tasks": ["5.1"] },
    { "id": 5, "tasks": ["5.2", "6.1", "6.2"] },
    { "id": 6, "tasks": ["6.3", "6.4", "6.5", "7.1"] },
    { "id": 7, "tasks": ["7.2", "9.1"] },
    { "id": 8, "tasks": ["9.2", "9.3", "9.4", "9.5"] },
    { "id": 9, "tasks": ["12.1", "12.2"] },
    { "id": 10, "tasks": ["13.1", "14.1", "15.1"] },
    { "id": 11, "tasks": ["13.2"] }
  ]
}
```
