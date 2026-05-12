# Fase 6 — Mejoras al Portal Cloud (APCM)

**Prerrequisito**: Fases 1–5 completadas en el Client  
**Entregable**: El portal APCM soporta la configuración de checks de conectividad, telemetría, locale por organización y visualización de datos de las fases anteriores  
**Estimación**: 6–8 días

---

## Objetivo

Extender el backend FastAPI y el frontend Next.js para:

1. **Configuración de checks de conectividad** por organización/VLAN/workstation
2. **Locale por organización** (override desde el portal)
3. **Telemetría**: almacenamiento y visualización en el dashboard
4. **Resultados de conectividad**: visualización en tiempo real
5. **Migración Alembic** para los nuevos campos

---

## Backend (FastAPI)

### 6.1 — Migración Alembic: nuevos campos en `GlobalConfig`

**Archivo**: `AlwaysPrintProject/Cloud/backend/alembic/versions/005_add_connectivity_and_telemetry.py`

Nuevos campos en `global_configs`, `vlan_configs`, `workstation_configs`:

```python
# Campos a agregar en las 3 tablas de config:
connectivity_checks      = Column(JSON, nullable=True)   # lista de ConnectivityCheck
locale                   = Column(String(10), nullable=True)  # "es" | "en" | ""
telemetry_enabled        = Column(Boolean, nullable=True)
telemetry_interval_seconds = Column(Integer, nullable=True)
```

Nueva tabla `telemetry_logs`:

```python
class TelemetryLog(Base):
    __tablename__ = "telemetry_logs"
    id                  = Column(GUID, primary_key=True, default=uuid.uuid4)
    workstation_id      = Column(GUID, ForeignKey("workstations.id", ondelete="CASCADE"))
    account_id          = Column(GUID, ForeignKey("accounts.id",     ondelete="CASCADE"))
    queue_status        = Column(String(20), nullable=True)
    contingency_active  = Column(Boolean, nullable=True)
    jobs_identified     = Column(Integer, nullable=True)
    avg_release_time_ms = Column(BigInteger, nullable=True)
    disconnection_count = Column(Integer, nullable=True)
    recorded_at         = Column(DateTime, nullable=False, default=datetime.utcnow)
```

Nueva tabla `connectivity_results`:

```python
class ConnectivityResult(Base):
    __tablename__ = "connectivity_results"
    id             = Column(GUID, primary_key=True, default=uuid.uuid4)
    workstation_id = Column(GUID, ForeignKey("workstations.id", ondelete="CASCADE"))
    account_id     = Column(GUID, ForeignKey("accounts.id",     ondelete="CASCADE"))
    check_id       = Column(String(100), nullable=False)
    check_type     = Column(String(20),  nullable=False)
    success        = Column(Boolean,     nullable=False)
    latency_ms     = Column(BigInteger,  nullable=True)
    error          = Column(String(500), nullable=True)
    recorded_at    = Column(DateTime,    nullable=False, default=datetime.utcnow)
```

---

### 6.2 — Schemas Pydantic: nuevos campos en config

**Archivo**: `AlwaysPrintProject/Cloud/backend/app/schemas/config.py`

Agregar a `GlobalConfigUpdate`, `VLANConfigUpdate`, `WorkstationConfigUpdate`:

```python
connectivity_checks:       Optional[List[ConnectivityCheckSchema]] = None
locale:                    Optional[str] = Field(None, max_length=10)
telemetry_enabled:         Optional[bool] = None
telemetry_interval_seconds: Optional[int] = Field(None, ge=60, le=86400)
```

Nuevo schema:

```python
class ConnectivityCheckSchema(BaseModel):
    id:         str
    type:       Literal["http", "tcp", "ping", "dns"]
    url:        Optional[str] = None
    host:       Optional[str] = None
    hostname:   Optional[str] = None
    port:       Optional[int] = None
    timeout_ms: int = 5000
```

---

### 6.3 — `EffectiveConfigResponse`: incluir nuevos campos

**Archivo**: `AlwaysPrintProject/Cloud/backend/app/schemas/config.py`

```python
class EffectiveConfigResponse(BaseModel):
    corporate_queue_name:       Optional[str]
    search_targets:             Optional[dict]
    pending_task_polling_minutes: Optional[int]
    bootstrap_domains:          Optional[str]
    connectivity_checks:        List[ConnectivityCheckSchema] = []
    locale:                     Optional[str] = ""
    telemetry_enabled:          bool = True
    telemetry_interval_seconds: int = 300
    config_hash:                str  # SHA-256 del JSON serializado
```

El backend calcula `config_hash` antes de devolver la respuesta:

```python
import hashlib, json

def compute_config_hash(config: dict) -> str:
    json_str = json.dumps(config, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(json_str.encode()).hexdigest()
```

---

### 6.4 — WebSocket: recibir telemetría y resultados de conectividad

**Archivo**: `AlwaysPrintProject/Cloud/backend/app/api/v1/websocket/workstation.py`

Agregar casos en el loop de mensajes:

```python
elif message_type == "telemetry":
    # Guardar en telemetry_logs
    telemetry_service.save_telemetry(db, workstation_id, data)
    # Notificar a operadores
    await connection_manager.broadcast_to_account(
        account_id=str(workstation.account_id),
        message={"type": "telemetry_received", "workstation_id": workstation_id, **data},
        db=db
    )

elif message_type == "connectivity_result":
    # Guardar en connectivity_results
    connectivity_service.save_result(db, workstation_id, data)
    # Notificar a operadores en tiempo real
    await connection_manager.broadcast_to_account(
        account_id=str(workstation.account_id),
        message={"type": "connectivity_result", "workstation_id": workstation_id, **data},
        db=db
    )
```

---

### 6.5 — Nuevos endpoints REST

```python
# Telemetría de una workstation
GET /api/v1/workstations/{id}/telemetry?from=ISO&to=ISO&limit=100

# Resultados de conectividad de una workstation
GET /api/v1/workstations/{id}/connectivity?check_id=c1&from=ISO&to=ISO

# Estadísticas de telemetría por cuenta
GET /api/v1/accounts/{id}/telemetry/stats
```

---

## Frontend (Next.js)

### 6.6 — Página de configuración: checks de conectividad

**Archivo**: `AlwaysPrintProject/Cloud/frontend/src/app/dashboard/config/page.tsx`

Agregar sección "Checks de Conectividad":
- Lista de checks existentes (tabla)
- Botón "Agregar check"
- Modal con formulario: tipo (HTTP/TCP/Ping/DNS), URL/host/puerto, timeout
- Botón eliminar por check
- Selector de locale por organización

---

### 6.7 — Dashboard: panel de telemetría

**Archivo nuevo**: `AlwaysPrintProject/Cloud/frontend/src/app/dashboard/telemetry/page.tsx`

Mostrar por workstation:
- Estado de cola (badge: OK / Missing / Error)
- Contingencia activa (badge)
- Jobs identificados (número)
- Tiempo promedio de liberación (ms)
- Historial de desconexiones (tabla con inicio, fin, duración)
- Gráfico de tendencia (últimas 24h)

---

### 6.8 — Dashboard: panel de conectividad

**Archivo nuevo**: `AlwaysPrintProject/Cloud/frontend/src/app/dashboard/connectivity/page.tsx`

Mostrar por workstation:
- Lista de checks configurados
- Estado actual de cada check (verde/rojo)
- Latencia en tiempo real (actualizada por WebSocket)
- Historial de resultados (últimas 24h)

---

### 6.9 — Tipos TypeScript nuevos

**Archivo**: `AlwaysPrintProject/Cloud/frontend/src/types/config.ts`

```typescript
export interface ConnectivityCheck {
  id:         string;
  type:       'http' | 'tcp' | 'ping' | 'dns';
  url?:       string;
  host?:      string;
  hostname?:  string;
  port?:      number;
  timeout_ms: number;
}

export interface EffectiveConfig {
  corporate_queue_name?:        string;
  search_targets?:              { ips: string; ranges: string };
  pending_task_polling_minutes?: number;
  bootstrap_domains?:           string;
  connectivity_checks:          ConnectivityCheck[];
  locale?:                      string;
  telemetry_enabled:            boolean;
  telemetry_interval_seconds:   number;
  config_hash:                  string;
}
```

**Archivo**: `AlwaysPrintProject/Cloud/frontend/src/types/telemetry.ts`

```typescript
export interface TelemetryEntry {
  id:                   string;
  workstation_id:       string;
  queue_status:         'ok' | 'missing' | 'error';
  contingency_active:   boolean;
  jobs_identified:      number;
  avg_release_time_ms?: number;
  disconnection_count:  number;
  recorded_at:          string;
}

export interface ConnectivityResult {
  id:             string;
  workstation_id: string;
  check_id:       string;
  check_type:     string;
  success:        boolean;
  latency_ms?:    number;
  error?:         string;
  recorded_at:    string;
}
```

---

## Criterios de Aceptación

### Backend
- [ ] Migración `005` aplica sin errores: `alembic upgrade head`
- [ ] `GET /api/v1/workstations/{id}/config` incluye `connectivity_checks`, `locale`, `telemetry_enabled`, `telemetry_interval_seconds`, `config_hash`
- [ ] El `config_hash` es SHA-256 del JSON con `sort_keys=True`
- [ ] Los mensajes WebSocket `telemetry` y `connectivity_result` se persisten en BD
- [ ] Los nuevos endpoints de telemetría y conectividad devuelven datos correctos

### Frontend
- [ ] La página de config muestra y permite editar checks de conectividad
- [ ] El selector de locale funciona (es/en)
- [ ] El panel de telemetría muestra datos históricos
- [ ] El panel de conectividad se actualiza en tiempo real vía WebSocket
- [ ] TypeScript compila sin errores: `npm run build`

---

## Notas para el Desarrollador

- El `config_hash` debe calcularse **en el backend** con `sort_keys=True` para garantizar determinismo. El cliente calcula el hash del JSON recibido tal cual — si el servidor garantiza orden, los hashes coincidirán.
- La tabla `telemetry_logs` puede crecer rápidamente. Considerar una política de retención (ej: 90 días) implementada como cron job o trigger de BD.
- Los checks de conectividad se configuran a nivel de `GlobalConfig` y pueden ser overrideados a nivel de `VLANConfig` o `WorkstationConfig` siguiendo la misma jerarquía que el resto de la config.
- El frontend usa React Query para las peticiones REST y el hook `useWebSocket` existente para las actualizaciones en tiempo real.
