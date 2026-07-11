# Design Document: Bulk Actions UX Improvements

## Overview

Mejoras de experiencia de usuario para el sistema de acciones masivas. Se implementan tres cambios principales:
1. Enriquecimiento de workstations fallidas con hostname e IP en el backend
2. Nuevo endpoint para detectar sesiones activas antes de iniciar una nueva
3. Estimación de tiempo restante y ETA en el frontend durante la ejecución

## Architecture

### Componentes afectados

```
┌─────────────────────────────────────────────────────────────────────┐
│                         BACKEND (FastAPI)                            │
│                                                                     │
│  ┌─────────────────────────┐  ┌──────────────────────────────────┐ │
│  │ bulk_actions.py          │  │ bulk_execution.py                │ │
│  │ (endpoints)              │  │ (service)                        │ │
│  │                          │  │                                  │ │
│  │ GET /active  ←───────────│──│─ get_active_session()            │ │
│  │ GET /status/{id} ────────│──│─ get_session_status() [enriched] │ │
│  └─────────────────────────┘  └──────────────────────────────────┘ │
│                                         │                           │
│                                         ▼                           │
│  ┌─────────────────────────┐  ┌──────────────────────────────────┐ │
│  │ bulk_actions.py          │  │ Redis                            │ │
│  │ (schemas)                │  │                                  │ │
│  │                          │  │ bulk:running:{org_id} → session  │ │
│  │ + FailedWorkstationDetail│  │ bulk:session:{id} → hash         │ │
│  │ + ActiveSessionInfo      │  └──────────────────────────────────┘ │
│  └─────────────────────────┘                                        │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                        FRONTEND (Next.js)                            │
│                                                                     │
│  ┌─────────────────────────┐  ┌──────────────────────────────────┐ │
│  │ bulk-actions/page.tsx    │  │ bulk-actions-utils.ts            │ │
│  │                          │  │                                  │ │
│  │ + ActiveSessionAlert     │  │ + calcRemainingMs()              │ │
│  │ + FailedWorkstationsList │  │ + formatRemainingTime()          │ │
│  │ + TimeEstimation display │  │ + calcETA()                      │ │
│  └─────────────────────────┘  └──────────────────────────────────┘ │
│                                                                     │
│  ┌─────────────────────────┐  ┌──────────────────────────────────┐ │
│  │ types/bulk-actions.ts    │  │ lib/api.ts                       │ │
│  │                          │  │                                  │ │
│  │ + FailedWorkstationDetail│  │ + bulkActionsApi.getActive()     │ │
│  │ + ActiveSessionInfo      │  └──────────────────────────────────┘ │
│  └─────────────────────────┘                                        │
└─────────────────────────────────────────────────────────────────────┘
```

## Components

### Backend

#### 1. Schema: `FailedWorkstationDetail`

Nuevo schema en `app/schemas/bulk_actions.py`:

```python
class FailedWorkstationDetail(BaseModel):
    """Detalle enriquecido de una workstation donde falló el envío."""
    id: str = Field(..., description="UUID de la workstation")
    hostname: Optional[str] = Field(default=None, description="Hostname de la workstation (null si no existe en BD)")
    ip_private: str = Field(default="unknown", description="IP privada de la workstation")
```

#### 2. Schema: `ActiveSessionInfo`

Nuevo schema en `app/schemas/bulk_actions.py`:

```python
class ActiveSessionInfo(BaseModel):
    """Información de sesión activa detectada."""
    is_active: bool = Field(..., description="Si hay una sesión bulk activa")
    session_id: Optional[str] = Field(default=None, description="ID de la sesión activa")
    org_id: Optional[str] = Field(default=None, description="ID de la organización con sesión activa")
    org_name: Optional[str] = Field(default=None, description="Nombre de la organización")
    label: Optional[str] = Field(default=None, description="Label de la acción en ejecución")
    started_at: Optional[datetime] = Field(default=None, description="Timestamp de inicio")
    total: Optional[int] = Field(default=None, description="Total de workstations target")
    sent: Optional[int] = Field(default=None, description="Envíos completados")
```

#### 3. Modificación de `BulkSessionStatus`

Agregar campos al schema existente:

```python
class BulkSessionStatus(BaseModel):
    # ... campos existentes ...
    failed_workstation_details: list[FailedWorkstationDetail] = Field(
        default=[], description="Detalles enriquecidos de workstations fallidas"
    )
    delay_ms: Optional[int] = Field(default=None, description="Delay configurado entre envíos (ms)")
```

#### 4. Servicio: `get_session_status` (modificación)

Enriquecer la respuesta con detalles de workstations fallidas:

```python
async def get_session_status(self, session_id: UUID, org_id: UUID = None) -> BulkSessionStatus:
    # ... lógica existente de Redis ...

    # Enriquecer failed_workstations con hostname e ip_private
    failed_ws_ids = json.loads(data.get("failed_workstations", "[]"))
    failed_details = []
    if failed_ws_ids:
        failed_details = self._enrich_failed_workstations(failed_ws_ids)

    return BulkSessionStatus(
        # ... campos existentes ...
        failed_workstation_details=failed_details,
        delay_ms=int(data.get("delay_ms", "0")) or None,
    )
```

#### 5. Método interno: `_enrich_failed_workstations`

```python
@staticmethod
def _enrich_failed_workstations(ws_ids: list[str]) -> list[FailedWorkstationDetail]:
    """
    Consulta la tabla workstations para obtener hostname e ip_private.
    Si un ID no existe en BD, retorna hostname=None, ip_private="unknown".
    """
    db = SessionLocal()
    try:
        from app.models.workstation import Workstation
        rows = db.query(Workstation.id, Workstation.hostname, Workstation.ip_private).filter(
            Workstation.id.in_(ws_ids)
        ).all()

        # Mapear resultados por ID
        found = {str(row.id): row for row in rows}

        details = []
        for ws_id in ws_ids:
            if ws_id in found:
                row = found[ws_id]
                details.append(FailedWorkstationDetail(
                    id=ws_id,
                    hostname=row.hostname,
                    ip_private=row.ip_private or "unknown",
                ))
            else:
                details.append(FailedWorkstationDetail(
                    id=ws_id,
                    hostname=None,
                    ip_private="unknown",
                ))
        return details
    finally:
        db.close()
```

#### 6. Servicio: `get_active_session`

Nuevo método en `BulkExecutionService`:

```python
async def get_active_session(self, user: User) -> ActiveSessionInfo:
    """
    Detecta si hay una sesión bulk activa.
    - Operator: solo verifica su propia organización.
    - Admin: escanea todas las organizaciones.
    """
    redis_client = self._get_redis_client()
    try:
        if user.role == UserRole.OPERATOR:
            mutex_key = f"bulk:running:{user.organization_id}"
            session_id_str = await redis_client.get(mutex_key)
            if not session_id_str:
                return ActiveSessionInfo(is_active=False)
            return await self._build_active_info(redis_client, session_id_str)

        elif user.role == UserRole.ADMIN:
            # SCAN para encontrar cualquier bulk:running:*
            cursor = 0
            while True:
                cursor, keys = await redis_client.scan(cursor, match="bulk:running:*", count=100)
                if keys:
                    session_id_str = await redis_client.get(keys[0])
                    if session_id_str:
                        return await self._build_active_info(redis_client, session_id_str)
                if cursor == 0:
                    break
            return ActiveSessionInfo(is_active=False)

    finally:
        await redis_client.aclose()
```

#### 7. Endpoint: `GET /bulk-actions/active`

Nuevo endpoint en `app/api/v1/endpoints/bulk_actions.py`:

```python
@router.get("/active", response_model=ActiveSessionInfo)
async def get_active_session(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Detecta si hay una sesión bulk activa para el usuario/organización."""
    if user.role == UserRole.READONLY:
        raise HTTPException(status_code=403, detail="Permisos insuficientes")
    return await bulk_service.get_active_session(user, db)
```

#### 8. Modificación de `_execute_bulk`

Incluir `failed_workstation_details` en los mensajes WebSocket de progreso:

```python
# En el progress report, incluir detalles enriquecidos cuando hay errores
failed_details = []
if failed_ws:
    failed_details = self._enrich_failed_workstations(failed_ws)

progress_report = {
    "type": "bulk_progress",
    # ... campos existentes ...
    "failed_workstation_details": [d.model_dump() for d in failed_details],
}
```

### Frontend

#### 9. Interfaces TypeScript

Agregar a `src/types/bulk-actions.ts`:

```typescript
/** Detalle enriquecido de workstation fallida. */
export interface FailedWorkstationDetail {
  id: string
  hostname: string | null
  ip_private: string
}

/** Información de sesión activa detectada. */
export interface ActiveSessionInfo {
  is_active: boolean
  session_id: string | null
  org_id: string | null
  org_name: string | null
  label: string | null
  started_at: string | null
  total: number | null
  sent: number | null
}
```

Modificar `BulkSessionStatus`:

```typescript
export interface BulkSessionStatus {
  // ... campos existentes ...
  failed_workstation_details: FailedWorkstationDetail[]
  delay_ms: number | null
}
```

Modificar `BulkProgressMessage`:

```typescript
export interface BulkProgressMessage {
  // ... campos existentes ...
  failed_workstation_details: FailedWorkstationDetail[]
}
```

#### 10. Funciones de tiempo en `bulk-actions-utils.ts`

```typescript
/**
 * Calcula el tiempo restante estimado en milisegundos.
 * Fórmula: ((total - sent) / sent) * elapsedMs
 * Retorna null si sent === 0 (no hay datos para estimar).
 */
export function calcRemainingMs(total: number, sent: number, elapsedMs: number): number | null {
  if (sent === 0) return null;
  return Math.round(((total - sent) / sent) * elapsedMs);
}

/**
 * Formatea milisegundos de tiempo restante a texto legible.
 * < 60s: "~45s"
 * >= 60s: "~2m 30s"
 */
export function formatRemainingTime(ms: number): string {
  if (ms < 60000) return `~${Math.round(ms / 1000)}s`;
  const min = Math.floor(ms / 60000);
  const sec = Math.round((ms % 60000) / 1000);
  return `~${min}m ${sec}s`;
}

/**
 * Calcula la hora estimada de finalización (ETA).
 */
export function calcETA(remainingMs: number): Date {
  return new Date(Date.now() + remainingMs);
}
```

#### 11. API client

Agregar a `bulkActionsApi` en `src/lib/api.ts`:

```typescript
/** Detectar sesión activa. */
getActive: () => apiClient.get('/bulk-actions/active'),
```

#### 12. Componente `ActiveSessionAlert`

Se renderiza en la página de bulk-actions al montarse. Llama a `GET /bulk-actions/active` y si `is_active === true`, muestra un alert card con información de la sesión y un botón "Ver Progreso" que establece el `sessionId` en el state para mostrar el panel de progreso.

#### 13. Componente `FailedWorkstationsList`

Sección expandible dentro de `ExecutionProgressSection` que se muestra cuando `failed_workstation_details` tiene items. Cada item muestra hostname (o ID si null) y la IP privada.

#### 14. Estimación de tiempo

Dentro de `ExecutionProgressSection`, debajo del tiempo transcurrido, se muestra:
- Tiempo restante: `formatRemainingTime(calcRemainingMs(total, sent, elapsed_ms))`
- ETA: `calcETA(remainingMs)` formateado con `Intl.DateTimeFormat` usando el locale activo
- Si `sent === 0`: mostrar texto "Calculando..." del i18n

### Traducciones

Nuevas keys en `messages/es.json` y `messages/en.json` bajo el namespace `bulkActions`:

| Key | ES | EN |
|-----|----|----|
| `activeSessionAlert` | "Hay una ejecución masiva en curso" | "There is a bulk execution in progress" |
| `activeSessionOrg` | "Organización: {org}" | "Organization: {org}" |
| `activeSessionAction` | "Acción: {label}" | "Action: {label}" |
| `viewProgress` | "Ver Progreso" | "View Progress" |
| `remainingTime` | "Tiempo restante: {time}" | "Remaining time: {time}" |
| `eta` | "Hora estimada: {time}" | "Estimated time: {time}" |
| `calculating` | "Calculando..." | "Calculating..." |
| `failedWorkstations` | "Workstations fallidas" | "Failed workstations" |
| `hostname` | "Hostname" | "Hostname" |
| `ipPrivate` | "IP Privada" | "Private IP" |
| `unknownIp` | "Desconocida" | "Unknown" |

## Data Models

### Redis Session Hash (modificación)

El hash `bulk:session:{session_id}` ya almacena `delay_ms`. Se expone en la respuesta de `get_session_status`.

No se requieren cambios al esquema de Redis ni a la base de datos PostgreSQL.

### Flujo de datos para enriquecimiento

```
Redis hash (failed_workstations: ["uuid1", "uuid2"])
    │
    ▼
Query: SELECT id, hostname, ip_private FROM workstations WHERE id IN (...)
    │
    ▼
Merge: found → (id, hostname, ip_private)
       not found → (id, null, "unknown")
    │
    ▼
Response: failed_workstation_details: [...]
```

## Error Handling

| Escenario | Comportamiento |
|-----------|---------------|
| Redis no disponible en `/active` | HTTP 503 con mensaje descriptivo |
| Sesión no encontrada en `/status` | HTTP 404 (sin cambios) |
| Workstation no existe en BD | Fallback: hostname=null, ip_private="unknown" |
| Usuario readonly accede a `/active` | HTTP 403 |
| Error en enriquecimiento de WS | Log warning, retornar lista vacía de details (graceful degradation) |
| WebSocket desconectado durante ejecución | Frontend sigue usando polling cada 3s como fallback |

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Failed workstation enrichment correctness

*For any* set of failed workstation IDs (some existing in the database, some not), calling `_enrich_failed_workstations` SHALL produce a list where each entry has: (a) if the ID exists in DB → `hostname` and `ip_private` match the DB values, (b) if the ID does not exist in DB → `hostname` is null and `ip_private` is "unknown". The output list SHALL have the same length as the input list and preserve ID order.

**Validates: Requirements 1.1, 1.3**

### Property 2: Backward compatibility of failed workstations response

*For any* session status response that contains failed workstation information, both `failed_workstations` (list of string IDs) and `failed_workstation_details` (list of enriched objects) SHALL be present, and the set of IDs in `failed_workstation_details[*].id` SHALL equal the set of strings in `failed_workstations`.

**Validates: Requirements 1.5**

### Property 3: Active session tenant isolation

*For any* operator user with organization O and any set of active sessions across multiple organizations, the `/bulk-actions/active` endpoint SHALL only return session information for organization O. *For any* admin user, the endpoint SHALL return session information from any organization that has an active session.

**Validates: Requirements 2.2, 2.3, 2.4**

### Property 4: Remaining time calculation

*For any* positive integers `total` and `sent` where `0 < sent <= total`, and any positive `elapsedMs`, `calcRemainingMs(total, sent, elapsedMs)` SHALL return `Math.round(((total - sent) / sent) * elapsedMs)`. When `sent === 0`, the function SHALL return `null`.

**Validates: Requirements 3.1, 3.3**

### Property 5: ETA calculation

*For any* positive integer `remainingMs`, `calcETA(remainingMs)` SHALL return a Date whose timestamp equals `Date.now() + remainingMs` (within a tolerance of 5ms for execution time).

**Validates: Requirements 3.2**

### Property 6: Time formatting threshold

*For any* positive millisecond value `ms`: if `ms < 60000`, `formatRemainingTime(ms)` SHALL return a string matching the pattern `~{N}s` where N = `Math.round(ms / 1000)`; if `ms >= 60000`, it SHALL return a string matching `~{M}m {S}s` where M = `Math.floor(ms / 60000)` and S = `Math.round((ms % 60000) / 1000)`.

**Validates: Requirements 3.4, 3.5**
