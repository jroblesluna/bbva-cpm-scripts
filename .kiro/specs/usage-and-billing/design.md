# Design — Usage and Billing

## Overview

Esta funcionalidad extiende AlwaysPrint Cloud (FastAPI + PostgreSQL + Next.js) con un módulo
de facturación por IP privada registrada. El diseño se apoya en la infraestructura existente:

- **Modelo de workstations** (`app/models/workstation.py`) — se le añaden `last_seen` y
  `billing_status`.
- **Modelo de organización** (`app/models/organization.py`) — se le añade `billing_mode` y se
  refuerza el uso de `timezone` (ya existe, default `UTC`).
- **Scheduler existente** (APScheduler `AsyncIOScheduler`, patrón de `status_scheduler.py`) —
  se añade un `BillingCloseScheduler` con cron de medianoche.
- **Loop de ping/offline** (`websocket_manager.py` / `redis_connection_manager.py`) — se
  reutiliza el ciclo de ~60s para el flush de `last_seen` y se ajusta el marcado offline.
- **Pipeline de migraciones** (Alembic) — migración en 3 pasos para columnas NOT NULL sobre
  6,315+ filas en PROD.
- **Pipeline de backup/restore** — las nuevas columnas y tablas se serializan/restauran
  automáticamente al ser columnas ORM (el backup itera `mapper.columns`); las tablas nuevas se
  agregan al listado de tablas del backup.

Los principios rectores (de la propuesta y de las reglas del repo):
- **Tenant isolation:** toda query filtra por `organization_id`.
- **Fail-closed en dinero:** la liquidación anual es informativa y requiere confirmación manual.
- **Inmutabilidad del sustento:** un cierre generado no se recalcula.
- **Todo cálculo en la timezone de la organización.**

## Architecture

```
                         ┌───────────────────────────────────────────────┐
                         │              Frontend (Next.js)                 │
                         │  /dashboard/admin/usage-and-billing             │
                         │  - Config modalidad + timezone (lock)           │
                         │  - Planes tarifarios (superadmin)               │
                         │  - Listado de cierres + detalle por IP          │
                         │  - Generar cierres retroactivos                 │
                         │  - Liquidación anual (informativa)              │
                         └───────────────────┬─────────────────────────────┘
                                             │ REST (JWT)
                         ┌───────────────────▼─────────────────────────────┐
                         │           API v1 (FastAPI routers)              │
                         │  billing.py         (cierres, snapshots)        │
                         │  billing_rates.py   (tarifas/planes, superadmin)│
                         │  billing_annual.py  (suscripción/liquidación)   │
                         │  workstations.py    (borrado interceptado)      │
                         │  organizations.py   (timezone lock, modalidad)  │
                         └───────────────────┬─────────────────────────────┘
                                             │
        ┌────────────────────────────────────┼───────────────────────────────────┐
        │                                    │                                     │
┌───────▼─────────┐              ┌───────────▼──────────┐            ┌─────────────▼────────────┐
│ BillingService  │              │ BillingCloseService  │            │ LastSeenTracker          │
│ - tarifas/planes│              │ - cierre mensual     │            │ - buffer en memoria      │
│ - cálculo tramos│◄─────────────│ - reglas reciclaje   │            │ - flush en loop ~60s     │
│ - liquidación   │              │ - snapshot (cab+det) │            │ - persistencia en trans. │
└───────┬─────────┘              │ - idempotencia/orden │            └─────────────┬────────────┘
        │                        └───────────┬──────────┘                          │
        │                                    │                                     │
┌───────▼────────────────────────────────────▼─────────────────────────────────────▼────────┐
│                                    PostgreSQL                                                │
│  workstations(+last_seen,+billing_status)  organizations(+billing_mode)                     │
│  billing_rate_plans   billing_org_plans   billing_closures   billing_closure_items          │
│  billing_annual_subscriptions                                                                │
└──────────────────────────────────────────────────────────────────────────────────────────┘
        ▲
        │ cron 00:00 (timezone por org)
┌───────┴──────────────┐
│ BillingCloseScheduler│  (APScheduler AsyncIOScheduler, arrancado en lifespan main.py)
└──────────────────────┘
```

## Data Model

### 1. Cambios en `workstations`

```python
# app/models/workstation.py (adiciones)
last_seen = Column(DateTime, nullable=False)          # tras migración; default=first_seen en registro
billing_status = Column(String(16), nullable=False, server_default="new")
# CHECK constraint: billing_status IN ('new','billable','recycled','archived')
```

Nota sobre `last_seen`:
- No se define `DEFAULT` referenciando `first_seen` (imposible en SQL: un DEFAULT no puede
  referenciar otra columna de la misma fila). El valor "= first_seen" se garantiza en el
  **código de registro**. Se fija `server_default=CURRENT_TIMESTAMP` únicamente como red de
  seguridad para satisfacer NOT NULL ante inserts que omitan el campo.

### 2. Cambios en `organizations`

```python
# app/models/organization.py (adiciones)
billing_mode = Column(String(16), nullable=False, server_default="monthly")
# CHECK: billing_mode IN ('monthly','annual')
```
`timezone` ya existe (String(50), default `UTC`). El lock se implementa en el endpoint de update.

### 3. `billing_rate_plans` — tarifas por defecto del sistema (editables por superadmin)

```python
class BillingRatePlan(Base):
    __tablename__ = "billing_rate_plans"
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    mode = Column(String(16), nullable=False)          # 'monthly' | 'annual'
    is_default = Column(Boolean, nullable=False, default=True)   # plan por defecto del sistema
    name = Column(String(100), nullable=False)
    # tramos serializados como JSON ordenado por rango
    # monthly: [{"from":1,"to":100,"rate":0.500}, ...]  (incremental)
    # annual:  [{"from":1,"to":100,"rate":5.00,"free_growth_to":200}, ...]
    tiers = Column(JSON, nullable=False)
    currency = Column(String(3), nullable=False, server_default="USD")
    effective_from = Column(DateTime, nullable=True)   # para cambios programados de defaults
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
```

### 4. `billing_org_plans` — plan individual asignado a una organización por modalidad

```python
class BillingOrgPlan(Base):
    __tablename__ = "billing_org_plans"
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    organization_id = Column(GUID, ForeignKey("organizations.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    mode = Column(String(16), nullable=False)          # 'monthly' | 'annual'
    tiers = Column(JSON, nullable=False)               # copia congelable del plan aplicado
    currency = Column(String(3), nullable=False, server_default="USD")
    # para anual: la tarifa se congela; effective para próxima renovación
    effective_from = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
```
Resolución de tarifa: si la org tiene `billing_org_plans` para la modalidad → usarlo; si no →
usar el `billing_rate_plans` default vigente. Los cambios de defaults NO sobrescriben planes de
org (Req 8.8).

### 5. `billing_closures` — cabecera de cierre (una por org/año/mes)

```python
class BillingClosure(Base):
    __tablename__ = "billing_closures"
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    organization_id = Column(GUID, ForeignKey("organizations.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    period_year = Column(Integer, nullable=False)
    period_month = Column(Integer, nullable=False)     # 1..12 (mes M cerrado)
    cutoff_at = Column(DateTime, nullable=False)       # 00:00 día 1 de M+1 en tz org (guardado en UTC)
    mode = Column(String(16), nullable=False)          # modalidad al momento del cierre
    timezone = Column(String(50), nullable=False)      # tz usada
    total_billable = Column(Integer, nullable=False)
    total_recycled = Column(Integer, nullable=False)
    total_archived = Column(Integer, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)    # monto del mes (0.00 si anual vigente)
    tiers_applied = Column(JSON, nullable=False)        # desglose por tramo
    is_retroactive = Column(Boolean, nullable=False, default=False)
    created_by_id = Column(GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("organization_id", "period_year", "period_month",
                         name="uq_closure_org_period"),   # idempotencia
    )
```

### 6. `billing_closure_items` — detalle por IP (inmutable)

```python
class BillingClosureItem(Base):
    __tablename__ = "billing_closure_items"
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    closure_id = Column(GUID, ForeignKey("billing_closures.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    workstation_id = Column(GUID, nullable=True)       # nullable: puede borrarse la ws luego
    ip_private = Column(String(45), nullable=False)
    created_at_ws = Column(DateTime, nullable=False)   # created_at de la workstation
    last_seen_capped = Column(DateTime, nullable=False)# last_seen capado a M+1
    billing_status = Column(String(16), nullable=False)# estado en ESE cierre
    tier_index = Column(Integer, nullable=True)        # tramo aplicado (mensual)
    amount = Column(Numeric(12, 4), nullable=False, server_default="0")  # aporte de esta IP
```

### 7. `billing_annual_subscriptions` — suscripción anual

```python
class BillingAnnualSubscription(Base):
    __tablename__ = "billing_annual_subscriptions"
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    organization_id = Column(GUID, ForeignKey("organizations.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    start_date = Column(DateTime, nullable=False)      # created_at del primer registro
    end_date = Column(DateTime, nullable=False)        # 1 día antes del aniversario
    declared_volume = Column(Integer, nullable=False)  # input manual superadmin
    tier_rate = Column(Numeric(12, 4), nullable=False) # tarifa congelada del tramo
    tier_from = Column(Integer, nullable=False)
    tier_to = Column(Integer, nullable=True)           # null = último tramo (sin tope superior de tramo)
    tier_cap = Column(Integer, nullable=True)          # tope contabilizable (ej. 10000)
    status = Column(String(16), nullable=False, server_default="active")  # active|settled
    settlement = Column(JSON, nullable=True)           # {declared, real, diff, credit, charge}
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
```

## Migración (Alembic) — 3 pasos, segura sobre PROD

Una sola revisión Alembic con este orden estricto:

```python
def upgrade():
    # ── last_seen ──────────────────────────────────────────────
    # Paso 1: columna nullable
    op.add_column("workstations", sa.Column("last_seen", sa.DateTime(), nullable=True))
    # Paso 2: backfill con COALESCE(last_connection, first_seen)
    op.execute("UPDATE workstations SET last_seen = COALESCE(last_connection, first_seen)")
    # Paso 3: default de seguridad + NOT NULL
    op.alter_column("workstations", "last_seen",
                    server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False)

    # ── billing_status ─────────────────────────────────────────
    op.add_column("workstations", sa.Column("billing_status", sa.String(16), nullable=True))
    op.execute("UPDATE workstations SET billing_status = 'new'")
    op.alter_column("workstations", "billing_status",
                    server_default="new", nullable=False)
    op.create_check_constraint(
        "ck_ws_billing_status",
        "workstations",
        "billing_status IN ('new','billable','recycled','archived')")

    # ── organizations.billing_mode ─────────────────────────────
    op.add_column("organizations", sa.Column("billing_mode", sa.String(16),
                  nullable=False, server_default="monthly"))
    op.create_check_constraint("ck_org_billing_mode", "organizations",
                               "billing_mode IN ('monthly','annual')")

    # ── tablas nuevas ──────────────────────────────────────────
    # billing_rate_plans, billing_org_plans, billing_closures,
    # billing_closure_items, billing_annual_subscriptions
    ...
    # Seed de planes por defecto (monthly + annual) con las tarifas de la propuesta.
```

Notas:
- El backfill a `new` es intencional (Req 8/F2): los cierres retroactivos moverán las IPs a
  `billable`/`recycled` mes a mes desde el más antiguo.
- Compatibilidad SQLite (tests): el CHECK y los tipos usan `String`/`GUID` ya soportados; la
  migración usa `batch_alter_table` si `op.get_bind().dialect.name == 'sqlite'` para los
  `alter_column`/constraints.

## `last_seen` — estrategia de actualización (opción B)

### Componente `LastSeenTracker`

Buffer en memoria por worker: `{workstation_id: last_telemetry_ts}`. Alimentado cuando llega
telemetría (sin escribir a BD). Persistencia a BD en:

1. **Transición offline→online** (reconexión WS / telemetría estando offline): escribe
   `last_seen = last_telemetry_ts` (o el ts del evento si no hay telemetría previa).
2. **Marcado offline** (flush de disconnect y Death Ping): escribe `last_seen` con el timestamp
   de la última actividad real conocida (no el momento del evento).
3. **Flush periódico** en el loop existente de ~60s (`start_ping_loop`): batch UPDATE del
   `last_seen` de las workstations online cuyo `last_telemetry_ts` en memoria avanzó respecto
   al último `last_seen` persistido.
4. **Registro / re-registro / nueva conexión:** en `services/workstation.py` se setea
   `last_seen` en los mismos puntos donde hoy se setea `last_connection` (L483/L620/L725) y en
   la creación (`= first_seen`).

### Cambios puntuales

- `websocket_manager._flush_disconnect_queue` y su equivalente en `redis_connection_manager`:
  al marcar `is_online=False`, incluir `last_seen` = última actividad conocida (obtenida del
  tracker).
- `start_ping_loop`: añadir el flush batch de `last_seen` de las online.
- Multi-worker (Redis): el `last_telemetry_ts` se maneja por worker; el flush de 60s de cada
  worker cubre sus propias conexiones (coherente con el WorkerRegistry existente).

### Reactivación inmediata de estado (Req 2.8)

Al persistir `last_seen` por actividad (registro, conexión, telemetría estando offline), si la
workstation está en `recycled` o `archived`, se cambia `billing_status = billable` en la misma
transacción. Se implementa en un helper `mark_activity(db, ws, ts)` invocado desde todos los
puntos de actualización de `last_seen`.

## Máquina de estados `billing_status`

```
                 (registro)
                    │
                    ▼
                 ┌─────┐   cierre paso1    ┌──────────┐
                 │ new │ ────────────────▶ │ billable │
                 └──┬──┘                   └──┬───┬───┘
                    │ delete físico           │   │ archive manual (offline)
                    ▼                         │   ▼
               (removed)                      │  ┌──────────┐
                                              │  │ archived │
         cierre reglas reciclaje             │  └────┬─────┘
                    │                         │       │ actividad
                    ▼                         │       ▼
               ┌──────────┐  actividad        │   billable
               │ recycled │ ─────────────────▶┘
               └────┬─────┘
                    │ archive manual (offline)
                    ▼
               ┌──────────┐
               │ archived │   (archived NO vuelve a recycled por proceso automático)
               └──────────┘
```

Validación de transiciones centralizada en `BillingStateMachine.can_transition(old, new)` y
`assert_archivable(ws)` (exige `is_online == False`).

## Motor de cierre mensual (`BillingCloseService`)

### Cálculo de cortes (en timezone de la org)

Para el mes M (año Y):
- `cutoff = 00:00 del día 1 de (M+1)` en `org.timezone`, convertido a UTC para persistir.
- `recycle_cut_case1 = 00:00 del día 1 de (M−2)` (3 meses de inactividad).
- `recycle_cut_case2 = 00:00 del día 1 de (M−3)` (4 meses de inactividad).

Se usa `zoneinfo.ZoneInfo(org.timezone)` para construir los cortes locales y luego
`astimezone(UTC)`.

### Algoritmo

```
close_month(org, year, month, actor, retroactive):
    assert no existe cierre (org, year, month)                 # idempotencia (Req 7.6)
    assert no hay meses anteriores sin cerrar                   # secuencialidad (Req 7.4)
    cutoff, cut1, cut2 = compute_cuts(org.timezone, year, month)

    ws_in_scope = SELECT * FROM workstations
                  WHERE organization_id = org.id
                    AND created_at < cutoff
                    AND billing_status != 'archived'            # archived no se toca

    # Paso 1: new -> billable
    for ws in ws_in_scope where status == 'new':
        ws.billing_status = 'billable'

    # Paso 2: reglas de reciclaje sobre billable (last_seen CRUDO)
    for ws in ws_in_scope where status == 'billable':
        if ws.last_seen < cut2:                                 # Caso 2 abandono
            ws.billing_status = 'recycled'
        elif ws.last_seen < cut1 and (ws.last_seen - ws.created_at) < 24h:  # Caso 1
            ws.billing_status = 'recycled'

    # Snapshot (last_seen CAPADO a cutoff)
    header = BillingClosure(...)  # totales, amount, tiers_applied, is_retroactive
    items = []
    billable_count = count(status=='billable' en scope)
    amount, tiers = compute_amount(org, billable_count)         # 0.00 si anual vigente
    for ws in ws_in_scope + archived_in_scope:
        items.append(BillingClosureItem(
            ip_private, created_at_ws, 
            last_seen_capped = min(ws.last_seen, cutoff),
            billing_status = ws.billing_status,
            tier_index, amount_aporte))

    persist(header, items)  # transacción única
    audit.log(...)
```

Notas:
- El cierre actualiza la columna **viva** `billing_status`. En un **cierre retroactivo**, para
  no retroceder el estado vivo actual (Req 6.5), la actualización viva de un mes M solo se
  aplica si ese cierre es el más reciente ejecutado; los cierres retroactivos anteriores al
  último ejecutado registran el estado histórico **solo en el snapshot** y no revierten la
  columna viva. Implementación: el estado vivo lo determina siempre el cierre de mayor
  `(year, month)`; los items del snapshot guardan el estado histórico calculado para ese mes.
- Ejecución en thread (como restore) o dentro del job del scheduler; transacción única por
  cierre con `organization_id` scope.

### Cálculo de monto mensual (incremental por tramos)

```
compute_amount_monthly(count, tiers):
    total = 0
    for tier in tiers:                # tiers ordenados por 'from'
        lo, hi, rate = tier.from, tier.to, tier.rate
        if count < lo: break
        ips_in_tier = min(count, hi) - lo + 1     # hi = inf en último tramo
        total += ips_in_tier * rate
    return round(total, 2)            # half-up a 2 decimales
```
Ejemplo 3,136 IPs → 100×0.50 + 1,900×0.25 + 1,136×0.20 = 752.20 ✓

## Suscripción y liquidación anual (informativa)

- Durante la vigencia, cada cierre mensual genera `amount = 0.00` (Req 9.2).
- En el aniversario: `real = min(billable_count, tier_cap)`;
  `diff = declared_volume − real`; `credit = max(diff,0)×tier_rate`;
  `charge = max(−diff,0)×tier_rate`. Se guarda en `settlement` (JSON) con estado `active`.
- La aplicación (`status='settled'`) requiere confirmación manual del superadmin (Req 9.5).
- "Crecimiento libre": informativo; se marca si `real` está dentro del `free_growth_to` del
  tramo o si requiere reclasificación (no se reclasifica automáticamente en esta spec — Req 9.6,
  D4-3 informativo).

## Restricción de eliminación

`workstations.delete_workstation` (L2069) se modifica:

```
if ws.billing_status == 'new':
    db.delete(ws)                    # eliminación física
else:
    if ws.is_online:
        raise HTTP 409 "debe estar offline para archivar"
    ws.billing_status = 'archived'   # soft-delete
```

Se añade un endpoint de borrado masivo `POST /workstations/bulk-delete` que procesa cada una
según su estado y devuelve un reporte:
```json
{ "deleted": ["ip1","ip2"], "archived": ["ip3"], "rejected": [{"ip":"ip4","reason":"online"}] }
```
Se centraliza la lógica en `BillingDeletionService.delete_or_archive(db, ws)` reutilizada por
ambos endpoints (Req 3.4).

## Timezone lock

En `update_organization` (PUT `/{org_id}`) y `update_my_organization` (PUT `/me`):
```
if "timezone" in update_data and update_data["timezone"] != org.timezone:
    has_closures = db.query(BillingClosure).filter_by(organization_id=org.id).first()
    if has_closures:
        raise HTTP 409 "no se puede cambiar la timezone: la organización ya tiene cierres"
```

## Scheduler de cierre automático

`app/services/billing_close_scheduler.py` — clase `BillingCloseScheduler` con
`AsyncIOScheduler`, patrón idéntico a `status_scheduler`. Arrancado/detenido en el `lifespan`
de `main.py`.

- Trigger: `cron` cada día a las 00:05 (margen sobre medianoche) evaluando **todas** las orgs;
  para cada org calcula su medianoche local del día 1. Alternativa preferida: cron horario que
  verifica qué orgs acaban de cruzar `00:00 del día 1` en su tz y aún no tienen el cierre del
  mes anterior. Esto cubre múltiples timezones con un solo scheduler UTC.
- Protección de concurrencia con `asyncio.Lock` (como status_scheduler).
- Reusa `BillingCloseService.close_month` respetando secuencialidad/idempotencia.

## API Endpoints

| Método | Ruta | Rol | Descripción |
|---|---|---|---|
| GET | `/billing/organizations/{org_id}/summary` | admin | Modalidad, tz, plan vigente |
| PUT | `/billing/organizations/{org_id}/mode` | superadmin | Set modalidad (validaciones) |
| GET | `/billing/organizations/{org_id}/closures` | admin | Lista de cierres (cabecera) |
| GET | `/billing/closures/{closure_id}/items` | admin | Detalle por IP (paginado) |
| POST | `/billing/organizations/{org_id}/closures/retroactive` | superadmin | Cierra el mes pendiente más antiguo |
| GET | `/billing/rate-plans` | superadmin | Tarifas por defecto |
| PUT | `/billing/rate-plans/{id}` | superadmin | Editar/programar defaults |
| PUT | `/billing/organizations/{org_id}/plan` | superadmin | Plan individual de la org |
| POST | `/billing/organizations/{org_id}/annual-subscription` | superadmin | Crear suscripción anual |
| GET | `/billing/organizations/{org_id}/annual-settlement` | superadmin | Liquidación (informativa) |
| POST | `/billing/organizations/{org_id}/annual-settlement/confirm` | superadmin | Aplicar liquidación |
| POST | `/workstations/bulk-delete` | admin | Borrado masivo (delete/archive/reject) |

Todos filtran por `organization_id`. Superadmin = rol de mayor privilegio (a confirmar el
nombre exacto del rol en `UserRole` durante implementación).

## Frontend

- Nueva ruta `src/app/dashboard/admin/usage-and-billing/page.tsx`.
- Componentes: `BillingModeCard`, `RatePlanEditor` (superadmin), `ClosuresTable`,
  `ClosureDetailDrawer`, `RetroactiveCloseButton`, `AnnualSettlementCard`.
- Listado de workstations: añadir filtro "ocultar archived" (default ON), análogo al de online.
- Diálogo de borrado: consulta el estado y muestra si será delete físico o archive, con la razón.
- TypeScript estricto (sin `any`), tipos en `src/types/billing.ts`.

## Testing Strategy

- **Unit (backend):** `compute_amount_monthly` (casos de la propuesta: 13, 585, 3136, 6276),
  cálculo de cortes en distintas timezones (America/Lima, UTC, cruces de DST), reglas de
  reciclaje caso 1/2 con `last_seen` crudo, capping en snapshot, máquina de estados
  (transiciones válidas/ inválidas), liquidación anual.
- **Integración:** migración 3 pasos sobre BD con datos (verificar backfill), cierre secuencial
  e idempotente, borrado interceptado (new→delete, no-new offline→archive, no-new online→reject),
  timezone lock.
- **Property-based (hypothesis):** invariantes — nadie vuelve a `new`; `archived` no pasa a
  `recycled` por cierre; monto mensual monótono no decreciente al crecer el conteo.
- **Verificación en PROD (solo lectura) antes de aplicar:** contar IPs por `created_at` mensual
  para dimensionar los cierres retroactivos de BBVA (mayo–agosto 2026).

## Consideraciones de compatibilidad e impacto

- `last_connection` permanece; el dashboard y exports actuales no cambian de fuente en esta
  spec (se documenta que "actividad de billing" usa `last_seen`).
- Backup/restore: las nuevas tablas se añaden al listado de tablas del backup service; las
  columnas nuevas se serializan automáticamente. Verificar orden FK en restore
  (billing_closures antes de billing_closure_items).
- Multi-worker: el flush de `last_seen` es por worker; no requiere coordinación Redis adicional.
- Rendimiento del cierre: para ~6,315 IPs el cierre es un batch acotado; se ejecuta en
  transacción única por org, fuera del hot path de WS.
```
