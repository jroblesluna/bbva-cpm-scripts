# Design Document: System Status Metrics

## Overview

Este diseño extiende el sistema de monitoreo existente (`SystemStatusCollector` + `StatusScheduler`) con 5 métricas de escalabilidad orientadas a operar AlwaysPrint Cloud con 5000 workstations concurrentes. La arquitectura añade:

1. Un nuevo endpoint HTTP `GET /api/v1/system/metrics` que recolecta y retorna métricas en tiempo real.
2. Un módulo de colectores (`ScalabilityMetricsCollector`) que lee del sistema de archivos `/proc`, del `ConnectionManager` singleton, y del pool SQLAlchemy.
3. Integración con `SystemStatusCollector.collect_all()` para persistir las métricas en los snapshots periódicos.
4. Un componente React `MetricsCard` en la página System Status del frontend.

**Decisiones clave:**
- Las métricas se recolectan bajo demanda en cada request al endpoint (no cacheadas) para reflejar estado real.
- El estado para cálculo de tasa de red se mantiene in-memory en el singleton del colector (se pierde al reiniciar, comportamiento aceptable — retorna `null` la primera vez).
- El frontend consume el endpoint con polling manual (botón refresh) en la misma página donde ya existe el System Status, sin WebSocket adicional.

## Architecture

```mermaid
graph TD
    subgraph Frontend["Frontend (Next.js)"]
        MSC[MetricsCard Component]
        API_CLIENT[system-status.ts API client]
        MSC --> API_CLIENT
    end

    subgraph Backend["Backend (FastAPI)"]
        EP[GET /api/v1/system/metrics]
        SMC[ScalabilityMetricsCollector]
        SS[StatusScheduler]
        SSC[SystemStatusCollector]
        CM[ConnectionManager singleton]
        DB_ENGINE[SQLAlchemy Engine Pool]
        
        EP --> SMC
        SS --> SSC
        SSC --> SMC
        SMC --> CM
        SMC --> DB_ENGINE
    end

    subgraph System["Linux /proc"]
        PROC_STATUS[/proc/self/status]
        PROC_FD[/proc/self/fd]
        PROC_NET[/proc/net/dev]
    end

    subgraph Database["PostgreSQL RDS"]
        PG_STAT[pg_stat_activity]
        SNAPSHOTS[status_snapshots]
    end

    API_CLIENT -->|HTTP GET| EP
    SMC --> PROC_STATUS
    SMC --> PROC_FD
    SMC --> PROC_NET
    SMC -->|SELECT pg_stat_activity| PG_STAT
    SSC -->|persist snapshot| SNAPSHOTS
```

### Flujo del endpoint (request-time):

1. Request llega a `GET /api/v1/system/metrics` con JWT válido + rol admin.
2. El router invoca `ScalabilityMetricsCollector.collect_all_metrics()`.
3. El colector ejecuta los 5 sub-colectores en paralelo (`asyncio.gather` con `return_exceptions=True`).
4. Cada sub-colector que falla retorna `None` sin afectar a los demás.
5. Se ensambla el response schema y se retorna HTTP 200.

### Flujo del scheduler (periódico):

1. `StatusScheduler` invoca `SystemStatusCollector.collect_all()`.
2. `collect_all()` ahora incluye una llamada a `ScalabilityMetricsCollector.collect_all_metrics()`.
3. El resultado se persiste como campo JSON dentro del `StatusSnapshot` existente.

## Components and Interfaces

### Backend

#### 1. `ScalabilityMetricsCollector` (nuevo)

**Ubicación:** `app/services/scalability_metrics.py`

```python
class ScalabilityMetricsCollector:
    """
    Recolecta las 5 métricas de escalabilidad del sistema.
    
    Mantiene estado in-memory para cálculo de tasas de red.
    Singleton a nivel de módulo.
    """
    
    def __init__(self):
        # Estado para cálculo de tasa de red
        self._prev_net_reading: Optional[NetReading] = None
        self._prev_net_timestamp: Optional[float] = None
        self._last_rates: Optional[NetRates] = None
    
    async def collect_all_metrics(self) -> ScalabilityMetricsResponse:
        """Recolecta todas las métricas, retorna null para las que fallen."""
        ...
    
    def collect_websocket_metrics(self) -> WebSocketMetrics:
        """Lee conteos del ConnectionManager singleton."""
        ...
    
    def collect_python_memory(self) -> PythonMemoryMetrics:
        """Lee VmRSS de /proc/self/status."""
        ...
    
    def collect_file_descriptors(self) -> FileDescriptorMetrics:
        """Cuenta entradas en /proc/self/fd y obtiene límite."""
        ...
    
    def collect_network_traffic(self) -> NetworkTrafficMetrics:
        """Lee /proc/net/dev, calcula tasas comparando con medición previa."""
        ...
    
    async def collect_db_pool_metrics(self, db: Session) -> DbPoolMetrics:
        """Lee estado del pool SQLAlchemy + query a pg_stat_activity."""
        ...


# Singleton
scalability_collector = ScalabilityMetricsCollector()
```

#### 2. Endpoint router (nuevo)

**Ubicación:** `app/api/v1/endpoints/system_metrics.py`

```python
router = APIRouter(prefix="/system", tags=["system-metrics"])

@router.get("/metrics", response_model=ScalabilityMetricsResponse)
async def get_system_metrics(
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> ScalabilityMetricsResponse:
    """Endpoint protegido: solo admin. Retorna las 5 métricas de escalabilidad."""
    ...
```

#### 3. Integración con `SystemStatusCollector`

Se añade una llamada a `scalability_collector.collect_all_metrics()` dentro de `collect_all()`:

```python
# En SystemStatusCollector.collect_all():
# 5. Recolectar métricas de escalabilidad
try:
    scalability_metrics = await scalability_collector.collect_all_metrics()
except Exception as e:
    logger.error(f"Error en métricas de escalabilidad: {e}")
    scalability_metrics = None
```

El resultado se incluye en el dict retornado y se persiste como campo JSON en el snapshot.

### Frontend

#### 4. `MetricsCard` component (nuevo)

**Ubicación:** `src/app/dashboard/admin/system-status/components/MetricsCard.tsx`

```typescript
interface MetricsCardProps {
  t: ReturnType<typeof useTranslations>;
}

export default function MetricsCard({ t }: MetricsCardProps) {
  // Fetch metrics from /api/v1/system/metrics
  // Render 5 metric items with threshold indicators
  // Handle loading, error, and null states
}
```

#### 5. Función de evaluación de umbrales (pura)

**Ubicación:** `src/lib/utils/threshold.ts`

```typescript
export type ThresholdColor = 'green' | 'yellow' | 'red';

export interface ThresholdConfig {
  greenMax: number;   // valor <= greenMax → verde
  yellowMax: number;  // greenMax < valor <= yellowMax → amarillo
  // valor > yellowMax → rojo
}

export function evaluateThreshold(
  value: number | null, 
  config: ThresholdConfig
): ThresholdColor | null {
  if (value === null) return null;
  if (value <= config.greenMax) return 'green';
  if (value <= config.yellowMax) return 'yellow';
  return 'red';
}
```

## Data Models

### Pydantic Schemas (Backend)

**Ubicación:** `app/schemas/scalability_metrics.py`

```python
class WebSocketMetricsResponse(BaseModel):
    """Métricas de conexiones WebSocket."""
    workstation_count: int = Field(..., ge=0, le=10000)
    operator_count: int = Field(..., ge=0, le=1000)
    total: int = Field(..., ge=0)
    data_available: bool = Field(default=True)


class PythonMemoryResponse(BaseModel):
    """Métricas de memoria del proceso Python."""
    rss_mb: Optional[float] = Field(None, description="RSS en MB, 2 decimales")
    container_total_mb: Optional[float] = Field(None, description="Memoria total contenedor MB")
    avg_per_workstation_mb: Optional[float] = Field(None, description="Promedio MB/ws")


class FileDescriptorResponse(BaseModel):
    """Métricas de file descriptors."""
    open_count: Optional[int] = Field(None, ge=0)
    limit: Optional[int] = Field(None, gt=0)
    usage_percent: Optional[float] = Field(None)


class NetworkTrafficResponse(BaseModel):
    """Métricas de tráfico de red."""
    rx_bytes: Optional[int] = Field(None, ge=0)
    tx_bytes: Optional[int] = Field(None, ge=0)
    rx_rate_bps: Optional[float] = Field(None)
    tx_rate_bps: Optional[float] = Field(None)


class DbPoolResponse(BaseModel):
    """Métricas del pool de base de datos."""
    checked_out: Optional[int] = Field(None, ge=0)
    idle: Optional[int] = Field(None, ge=0)
    pool_size: Optional[int] = Field(None, gt=0)
    overflow: Optional[int] = Field(None, ge=0)
    max_overflow: Optional[int] = Field(None, ge=0)
    pg_active_connections: Optional[int] = Field(None, ge=0)
    usage_percent: Optional[float] = Field(None)


class ScalabilityMetricsResponse(BaseModel):
    """Respuesta completa del endpoint de métricas de escalabilidad."""
    websocket: Optional[WebSocketMetricsResponse] = None
    python_memory: Optional[PythonMemoryResponse] = None
    file_descriptors: Optional[FileDescriptorResponse] = None
    network: Optional[NetworkTrafficResponse] = None
    db_pool: Optional[DbPoolResponse] = None
    collected_at: datetime
```

### TypeScript Types (Frontend)

**Ubicación:** `src/types/scalability-metrics.ts`

```typescript
export interface WebSocketMetrics {
  workstation_count: number;
  operator_count: number;
  total: number;
  data_available: boolean;
}

export interface PythonMemoryMetrics {
  rss_mb: number | null;
  container_total_mb: number | null;
  avg_per_workstation_mb: number | null;
}

export interface FileDescriptorMetrics {
  open_count: number | null;
  limit: number | null;
  usage_percent: number | null;
}

export interface NetworkTrafficMetrics {
  rx_bytes: number | null;
  tx_bytes: number | null;
  rx_rate_bps: number | null;
  tx_rate_bps: number | null;
}

export interface DbPoolMetrics {
  checked_out: number | null;
  idle: number | null;
  pool_size: number | null;
  overflow: number | null;
  max_overflow: number | null;
  pg_active_connections: number | null;
  usage_percent: number | null;
}

export interface ScalabilityMetrics {
  websocket: WebSocketMetrics | null;
  python_memory: PythonMemoryMetrics | null;
  file_descriptors: FileDescriptorMetrics | null;
  network: NetworkTrafficMetrics | null;
  db_pool: DbPoolMetrics | null;
  collected_at: string;
}
```

### Persistencia en Snapshot

Se agrega un campo JSON al modelo `StatusSnapshot` existente:

```python
# En app/models/system_status.py — StatusSnapshot
scalability_metrics_json = Column(Text, nullable=True)
```

Esto almacena el JSON serializado de `ScalabilityMetricsResponse` sin crear tablas adicionales (las métricas de escalabilidad se consultan desde el endpoint en tiempo real; el snapshot es solo para historial).

### Migración Alembic

```python
# alembic/versions/XXX_add_scalability_metrics_to_snapshot.py
def upgrade():
    op.add_column('status_snapshots', 
        sa.Column('scalability_metrics_json', sa.Text(), nullable=True)
    )

def downgrade():
    op.drop_column('status_snapshots', 'scalability_metrics_json')
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Graceful degradation under partial collector failures

*For any* subset of the 5 metric collectors that raise exceptions, the `collect_all_metrics()` method SHALL return a valid `ScalabilityMetricsResponse` where only the failed collectors produce `null` values and all non-failing collectors produce their expected non-null results.

**Validates: Requirements 1.5, 7.3**

### Property 2: WebSocket total is sum of components

*For any* non-negative integer `workstation_count` and non-negative integer `operator_count`, the `total` field in `WebSocketMetricsResponse` SHALL equal `workstation_count + operator_count`.

**Validates: Requirements 2.3**

### Property 3: VmRSS kB to MB conversion

*For any* non-negative integer `vmrss_kb` read from `/proc/self/status`, the `rss_mb` output SHALL equal `round(vmrss_kb / 1024, 2)`.

**Validates: Requirements 3.1**

### Property 4: Memory per workstation average

*For any* `rss_mb >= 0` and `ws_count > 0`, the `avg_per_workstation_mb` output SHALL equal `round(rss_mb / ws_count, 2)`.

**Validates: Requirements 3.3**

### Property 5: Percentage calculation correctness

*For any* non-negative integer `numerator` and positive integer `denominator`, the percentage function `calculate_percent(numerator, denominator, decimals)` SHALL return `round(numerator / denominator * 100, decimals)`.

**Validates: Requirements 4.3, 6.3**

### Property 6: Network interface traffic summing

*For any* parsed `/proc/net/dev` content containing N non-loopback interfaces each with `rx_bytes` and `tx_bytes` values, the total `rx_bytes` output SHALL equal the sum of all individual interface `rx_bytes`, and likewise for `tx_bytes`.

**Validates: Requirements 5.1**

### Property 7: Network rate calculation

*For any* two consecutive network readings `(prev_bytes, prev_time)` and `(curr_bytes, curr_time)` where `curr_bytes >= prev_bytes` and `(curr_time - prev_time) >= 0.5` seconds, the calculated rate SHALL equal `(curr_bytes - prev_bytes) / (curr_time - prev_time)`.

**Validates: Requirements 5.2**

### Property 8: Threshold color evaluation with boundary inclusivity

*For any* numeric value and threshold configuration `{greenMax, yellowMax}`, the `evaluateThreshold` function SHALL return:
- `'green'` when `value <= greenMax`
- `'yellow'` when `greenMax < value <= yellowMax`
- `'red'` when `value > yellowMax`
- `null` when `value` is `null`

In particular, *for any* value exactly equal to a boundary (`greenMax` or `yellowMax`), the function SHALL classify it in the lower zone (inclusive boundary).

**Validates: Requirements 8.2, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7**

## Error Handling

| Escenario | Comportamiento | Código HTTP |
|---|---|---|
| Token JWT inválido/expirado/ausente | Retorna error de autenticación | 401 |
| Usuario autenticado sin rol admin | Retorna error de autorización | 403 |
| Fallo en lectura de `/proc/self/status` | Campo `python_memory` = `null` en response | 200 |
| Fallo en lectura de `/proc/self/fd` | Campo `file_descriptors` = `null` en response | 200 |
| Fallo en lectura de `/proc/net/dev` | Campo `network` = `null` en response | 200 |
| ConnectionManager lanza excepción | `websocket.workstation_count` = 0, `operator_count` = 0, `data_available` = false | 200 |
| Query `pg_stat_activity` timeout/falla | `db_pool.pg_active_connections` = `null`; campos locales del pool sí se retornan | 200 |
| `fd_limit` es 0 o no disponible | `file_descriptors.usage_percent` = `null` | 200 |
| Primera invocación (sin medición previa de red) | `network.rx_rate_bps` = `null`, `network.tx_rate_bps` = `null` | 200 |
| Reinicio de contadores de red detectado | Tasas = `null`, se almacena nueva referencia | 200 |
| Excepción no controlada en el endpoint | Logged + HTTP 500 genérico | 500 |

**Principio general:** El endpoint SIEMPRE retorna HTTP 200 si al menos una métrica se recolecta exitosamente. Solo retorna 5xx ante una excepción catastrófica no manejada.

**Structured logging:** Cada fallo de colector se registra con:
```python
logger.warning(
    "Fallo en recolección de métrica de escalabilidad",
    extra={
        "metric_name": "python_memory",
        "error_type": type(e).__name__,
        "error_detail": str(e),
    }
)
```

## Testing Strategy

### Unit Tests (ejemplo-based)

- **Autenticación/Autorización:** Tests con tokens inválidos, expirados, no-admin → verificar 401/403.
- **Estructura de respuesta:** Test con colectores mockeados → verificar shape JSON correcta.
- **Valores null:** Test con colector mockeado que falla → verificar campo `null` en response.
- **Edge cases:**
  - `ws_count = 0` → `avg_per_workstation_mb = 0`
  - `fd_limit = 0` → `usage_percent = null`
  - Primera invocación de red → rates `null`
  - Counter reset (current < previous) → rates `null`
- **Frontend:**
  - Render MetricsCard con datos completos → 5 métricas visibles
  - Render con métrica `null` → texto "no disponible"
  - Render en estado de error → mensaje de error
  - Render en estado loading → spinner

### Property-Based Tests (Hypothesis - Python, fast-check - TypeScript)

**Librería backend:** `hypothesis` (Python)
**Librería frontend:** `fast-check` (TypeScript)

**Configuración:** Mínimo 100 iteraciones por property test.

Cada property test referencia su propiedad del diseño con el tag:
`Feature: system-status-metrics, Property {N}: {title}`

| Property | Librería | Módulo bajo test |
|---|---|---|
| 1: Graceful degradation | hypothesis | `ScalabilityMetricsCollector.collect_all_metrics()` |
| 2: WebSocket total sum | hypothesis | `collect_websocket_metrics()` |
| 3: VmRSS conversion | hypothesis | `collect_python_memory()` (parse logic) |
| 4: Memory per ws average | hypothesis | cálculo de promedio |
| 5: Percentage calculation | hypothesis | función `calculate_percent()` |
| 6: Network interface summing | hypothesis | parser de `/proc/net/dev` |
| 7: Network rate calculation | hypothesis | lógica de tasa en `collect_network_traffic()` |
| 8: Threshold evaluation | fast-check | `evaluateThreshold()` en `threshold.ts` |

### Integration Tests

- Endpoint completo con DB real (o fixture): verificar response 200 con métricas reales del host.
- `collect_all()` del scheduler incluye `scalability_metrics` en el resultado.
- Persistencia: snapshot con `scalability_metrics_json` no-null después de recolección.
- Query `pg_stat_activity`: verificar que retorna conteo >= 0 contra DB de test.

### Rendimiento

- Test con 3000 conexiones simuladas en ConnectionManager → endpoint responde < 2000ms.
