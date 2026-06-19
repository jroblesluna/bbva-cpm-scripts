# Design Document: Redis Pub/Sub Channel Consolidation

## Architecture Overview

El diseño consolida el esquema de canales Redis de O(n) suscripciones dinámicas (`ws:{id}`, `cmd_response:{id}`) a un máximo fijo de 2 + N_orgs_activas canales estáticos por worker:

```
┌─────────────────────────────────────────────────────────────────┐
│                        Redis Pub/Sub                             │
│                                                                  │
│  Canales fijos por worker:                                       │
│    • worker:{worker_id}     ← mensajes dirigidos + cmd_response │
│    • global:broadcast       ← broadcasts globales                │
│                                                                  │
│  Canales lazy (1 por org activa en worker):                     │
│    • org:{org_id}           ← broadcasts organizacionales       │
└─────────────────────────────────────────────────────────────────┘
         │                           │                    │
         ▼                           ▼                    ▼
┌─────────────────┐  ┌──────────────────────┐  ┌─────────────────┐
│  Worker A       │  │  Worker B            │  │  Worker C       │
│  ws1, ws2, ws3  │  │  ws4, ws5            │  │  ws6            │
│  (org1: 2)      │  │  (org1: 1, org2: 1)  │  │  (org2: 1)     │
│  (org2: 1)      │  │                      │  │                 │
└─────────────────┘  └──────────────────────┘  └─────────────────┘
```

### Cambios clave vs. diseño actual

| Aspecto | Antes (O(n)) | Después (O(1)) |
|---------|--------------|----------------|
| Suscripciones por WS | `ws:{ws_id}` cada una | Ninguna |
| Suscripciones por comando | `cmd_response:{cmd_id}` | Ninguna |
| Envío dirigido | Publish a `ws:{target}` | Publish a `worker:{target_worker}` |
| Respuesta comando | Publish a `cmd_response:{id}` | Publish a `worker:{originator}` con type=cmd_response |
| Org channels | Subscribe en connect (siempre) | Lazy: subscribe solo cuando count > 0 |
| Total subs por worker | 1 + N_ws + N_cmds_activos | 2 + N_orgs_activas |

## Components

### 1. RedisConnectionManager (refactored)

**Archivo**: `AlwaysPrintProject/Cloud/backend/app/services/redis_connection_manager.py`

#### Nuevo estado interno

```python
class RedisConnectionManager:
    def __init__(self, redis_url: Optional[str] = None):
        # === Estado local existente (sin cambios) ===
        self.workstation_connections: Dict[str, WebSocket] = {}
        self.operator_connections: Dict[str, Set[WebSocket]] = {}
        self.last_pong: Dict[str, datetime] = {}
        self.last_activity: Dict[str, datetime] = {}
        self.org_ids: Dict[str, str] = {}

        # === Nuevo estado para consolidación ===
        # Contador de workstations por organización (lazy subscribe/unsubscribe)
        self._org_ws_count: Dict[str, int] = {}

        # VLAN de cada workstation conectada (para filtrado local)
        self._ws_vlan_ids: Dict[str, Optional[str]] = {}

        # Command waiters: {command_id: (asyncio.Event, list, originator_worker_id)}
        self._pending_command_responses: Dict[str, Tuple[asyncio.Event, List[Optional[dict]], str]] = {}

        # === Estado Redis (modificado) ===
        self._redis_url = redis_url
        self._redis: Optional[aioredis.Redis] = None
        self._pubsub: Optional[aioredis.client.PubSub] = None
        self._listener_task: Optional[asyncio.Task] = None
        self._redis_available: bool = False
        self._worker_id: str = f"worker_{os.getpid()}"
        self._worker_registry: Optional[WorkerRegistry] = None
        self._heartbeat_task: Optional[asyncio.Task] = None

        # Lock y demás existentes sin cambios...
```

#### Interfaces públicas modificadas

```python
async def initialize(self) -> None:
    """
    Conecta a Redis y suscribe canales fijos: worker:{worker_id} y global:broadcast.
    NO suscribe canales per-workstation ni per-command.
    Inicializa WorkerRegistry y arranca listener + heartbeat tasks.
    """
    ...

async def connect_workstation(
    self,
    workstation_id: str,
    websocket: WebSocket,
    db: Session,
    organization_id: str,
    vlan_id: Optional[str] = None,
) -> None:
    """
    Registra workstation localmente. Zero Redis awaits en hot path.

    Hot path (síncrono):
      1. workstation_connections[ws_id] = websocket
      2. org_ids[ws_id] = organization_id
      3. _ws_vlan_ids[ws_id] = vlan_id
      4. last_pong[ws_id] = now
      5. last_activity[ws_id] = now
      6. _org_ws_count[org_id] += 1

    Fire-and-forget (no bloquea respuesta):
      7. WorkerRegistry.register_workstation(ws_id) — SADD
      8. Si _org_ws_count[org_id] == 1 → SUBSCRIBE org:{org_id}
    """
    ...

async def disconnect_workstation(
    self,
    workstation_id: str,
    db: Session,
    websocket: WebSocket = None,
) -> None:
    """
    Desconecta workstation y limpia estado.

    1. Elimina de workstation_connections, org_ids, _ws_vlan_ids, etc.
    2. _org_ws_count[org_id] -= 1
    3. Si _org_ws_count[org_id] == 0 → UNSUBSCRIBE org:{org_id}, del counter
    4. WorkerRegistry.unregister_workstation(ws_id) — SREM
    """
    ...

async def send_to_workstation(
    self,
    workstation_id: str,
    message: dict,
) -> bool:
    """
    Envía mensaje a workstation.

    1. Si está localmente → envío directo via WebSocket
    2. Si no está local y Redis disponible:
       a. Consultar WorkerRegistry.find_worker_for_workstation(ws_id)
       b. Si encontrado → publish a worker:{target_worker_id}
       c. Si no encontrado → log warning, return False
    3. Si Redis no disponible → log, return False
    """
    ...

def register_command_waiter(self, command_id: str) -> asyncio.Event:
    """
    Registra waiter para respuesta de comando.
    Almacena self._worker_id como originator. NO hace SUBSCRIBE.

    Returns: asyncio.Event que se señala cuando llega la respuesta.
    """
    ...

async def publish_command_response(
    self,
    command_id: str,
    response: dict,
    originator_worker_id: str,
) -> None:
    """
    Publica respuesta de comando al canal del worker originador.
    Publica en worker:{originator_worker_id} con payload:
      {"type": "cmd_response", "command_id": ..., ...response}
    """
    ...

async def wait_for_command_response(
    self, command_id: str, timeout: float = 30.0
) -> Optional[dict]:
    """
    Espera respuesta con timeout. NO hace UNSUBSCRIBE al terminar.
    Solo limpia el waiter del dict interno.
    """
    ...
```

### 2. Listener Redis (refactored)

```python
async def _redis_listener(self) -> None:
    """
    Loop que procesa mensajes de los canales consolidados.

    Despacho por canal:
      - worker:{self._worker_id}:
          • Si payload.type == "cmd_response" → resolve_command_response(payload.command_id, payload)
          • Else → _deliver_to_local_workstation(payload.target_workstation_id, payload)
      - org:{organization_id}:
          • _deliver_to_local_org_workstations(organization_id, payload)
            con filtro VLAN si payload.target_vlan_id presente
      - global:broadcast:
          • _deliver_global_broadcast(payload)
    """
    ...
```

### 3. Entrega local con filtrado VLAN

```python
async def _deliver_to_local_org_workstations(
    self, organization_id: str, payload: dict
) -> None:
    """
    Entrega mensaje organizacional con filtrado opcional por VLAN.

    1. Filtrar workstations locales donde org_ids[ws_id] == organization_id
    2. Si payload contiene target_vlan_id:
       Filtrar adicionalmente donde _ws_vlan_ids[ws_id] == target_vlan_id
    3. Enviar payload a cada workstation que pase ambos filtros
    """
    ...
```

### 4. Reconexión consolidada

```python
async def _handle_redis_reconnect(self) -> None:
    """
    Reconexión con exponential backoff (1s → 2s → ... → max_interval).

    Al reconectar exitosamente:
    1. Crear nuevo PubSub
    2. SUBSCRIBE worker:{self._worker_id}
    3. SUBSCRIBE global:broadcast
    4. Para cada org_id en _org_ws_count con count > 0:
       SUBSCRIBE org:{org_id}
    5. Re-registrar ALL local workstations en WorkerRegistry
    6. Reiniciar listener task

    Total subscribe operations: 2 + len(orgs_activas)
    NO itera sobre workstations para suscripciones.
    """
    ...
```

### 5. WorkerRegistry (minor addition)

**Archivo**: `AlwaysPrintProject/Cloud/backend/app/services/worker_registry.py`

El método `find_worker_for_workstation` ya existe y utiliza SCAN + SISMEMBER. No se requieren cambios estructurales, solo se usa desde `send_to_workstation`.

## Data Flow

### Flujo 1: Envío de comando a workstation remota

```
┌──────────────┐      ┌──────────────────┐      ┌────────────────┐
│  API/Worker A│      │     Redis        │      │    Worker B    │
│  (originador)│      │                  │      │  (tiene ws-X)  │
└──────┬───────┘      └────────┬─────────┘      └───────┬────────┘
       │                       │                         │
       │ 1. send_to_workstation("ws-X", cmd)             │
       │    → ws-X no está local                         │
       │                       │                         │
       │ 2. WorkerRegistry.find_worker_for_workstation   │
       │    → SISMEMBER workers:B:workstations "ws-X"    │
       │    → returns "worker_B"                         │
       │                       │                         │
       │ 3. PUBLISH worker:B   │                         │
       │    {"type":"command",  │                         │
       │     "target_workstation_id":"ws-X",             │
       │     "organization_id":"org-1",                  │
       │     "command_id":"cmd-123",                     │
       │     ...}              │                         │
       │──────────────────────►│                         │
       │                       │  4. Message on          │
       │                       │     worker:B channel    │
       │                       │────────────────────────►│
       │                       │                         │
       │                       │     5. Extract          │
       │                       │     target_workstation_id
       │                       │     Validate tenant     │
       │                       │     Deliver to ws-X     │
       │                       │                         │
```

### Flujo 2: Respuesta de comando cross-worker

```
┌──────────────┐      ┌──────────────────┐      ┌────────────────┐
│  Worker A    │      │     Redis        │      │    Worker B    │
│  (originador)│      │                  │      │  (tiene ws-X)  │
└──────┬───────┘      └────────┬─────────┘      └───────┬────────┘
       │                       │                         │
       │ register_command_waiter("cmd-123")              │
       │ stores: originator = "worker_A"                 │
       │                       │                         │
       │                       │         ws-X responde   │
       │                       │         al comando      │
       │                       │                         │
       │                       │  6. PUBLISH worker:A    │
       │                       │  {"type":"cmd_response",│
       │                       │   "command_id":"cmd-123"│
       │                       │   ...response_data}     │
       │                       │◄────────────────────────│
       │                       │                         │
       │  7. Message on        │                         │
       │     worker:A channel  │                         │
       │◄──────────────────────│                         │
       │                       │                         │
       │  8. type == cmd_response                        │
       │     resolve_command_response("cmd-123", data)   │
       │     → Event.set()                               │
       │                       │                         │
```

### Flujo 3: Lazy org subscribe/unsubscribe

```
Secuencia: ws1(org-A) connect → ws2(org-A) connect → ws1 disconnect → ws2 disconnect

Estado _org_ws_count["org-A"]:
  0 → 1  [SUBSCRIBE org:org-A]
  1 → 2  [noop]
  2 → 1  [noop]
  1 → 0  [UNSUBSCRIBE org:org-A, del key]
```

### Flujo 4: Filtrado VLAN en mensajes organizacionales

```
Worker tiene: ws1(org-A, vlan=V1), ws2(org-A, vlan=V2), ws3(org-A, vlan=None)

Mensaje en org:org-A con target_vlan_id="V1":
  → Entrega solo a ws1

Mensaje en org:org-A sin target_vlan_id:
  → Entrega a ws1, ws2, ws3
```

## Message Format

### Mensajes en canal `worker:{worker_id}`

```python
# Comando/mensaje dirigido a workstation
{
    "type": "command" | "status_request" | "config_update" | ...,
    "target_workstation_id": "ws-uuid-123",
    "organization_id": "org-uuid-456",
    "command_id": "cmd-uuid-789",  # opcional, solo si espera respuesta
    # ...payload específico del tipo
}

# Respuesta de comando (cross-worker)
{
    "type": "cmd_response",
    "command_id": "cmd-uuid-789",
    "workstation_id": "ws-uuid-123",  # quién respondió
    "organization_id": "org-uuid-456",
    # ...response data
}
```

### Mensajes en canal `org:{organization_id}`

```python
{
    "type": "org_broadcast" | "config_change" | ...,
    "organization_id": "org-uuid-456",
    "target_vlan_id": "vlan-uuid-001",  # opcional, para filtrado VLAN
    # ...payload
}
```

### Mensajes en canal `global:broadcast`

```python
{
    "type": "global_announcement" | "maintenance" | ...,
    # ...payload
}
```

## Error Handling

| Escenario | Comportamiento |
|-----------|----------------|
| Redis no disponible en initialize() | Opera en modo local, inicia reconexión background |
| Redis cae durante operación | `_redis_available = False`, fallback local, inicia reconexión |
| WorkerRegistry.find_worker returns None | Log warning, return False |
| Fire-and-forget SADD falla | Log warning, workstation sigue conectada localmente |
| Fire-and-forget SUBSCRIBE org falla | Log warning, org messages no llegarán hasta reconexión |
| Tenant validation falla | Descarta mensaje, log warning con IDs |
| Workstation no conectada localmente (msg en worker channel) | Descarta, log debug |
| Command waiter timeout | Limpia waiter del dict, return None, NO unsubscribe |

## Performance Characteristics

| Operación | Antes | Después |
|-----------|-------|---------|
| connect_workstation (hot path) | 1 SADD + 1 SUBSCRIBE | 0 await (fire-and-forget: 1 SADD + conditional SUBSCRIBE) |
| disconnect_workstation | 1 SREM + 1 UNSUBSCRIBE | 1 SREM + conditional UNSUBSCRIBE (solo si last-of-org) |
| send_to_workstation (remoto) | PUBLISH ws:{id} | 1 SISMEMBER (find worker) + 1 PUBLISH worker:{id} |
| register_command_waiter | 1 SUBSCRIBE cmd_response:{id} | 0 (solo estado local) |
| command timeout/resolve | 1 UNSUBSCRIBE | 0 (solo limpieza local) |
| Reconexión Redis | 1 + N_ws SUBSCRIBE ops | 2 + N_orgs SUBSCRIBE ops |

**Trade-off en send_to_workstation remoto**: Se añade 1 SISMEMBER (O(1) en Redis) para resolver el worker target. Este costo es aceptable porque:
1. Solo aplica a mensajes cross-worker (no locales)
2. SISMEMBER es O(1) contra un SET
3. Elimina N suscripciones permanentes que degradaban la conexión

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Subscription count invariant

*For any* sequence of connect and disconnect operations on a RedisConnectionManager instance, the number of active Redis subscriptions SHALL never exceed 2 + the number of distinct organization_ids with at least one locally connected workstation.

**Validates: Requirements 1.1**

### Property 2: No per-workstation channel operations

*For any* workstation connect or disconnect operation, the RedisConnectionManager SHALL NOT invoke SUBSCRIBE or UNSUBSCRIBE on any channel matching the pattern `ws:{workstation_id}`, and SHALL NOT invoke PUBLISH on any channel matching that pattern.

**Validates: Requirements 1.2, 1.3, 1.4**

### Property 3: No per-command channel operations

*For any* command waiter registration, resolution, or timeout, the RedisConnectionManager SHALL NOT invoke SUBSCRIBE or UNSUBSCRIBE on any channel matching the pattern `cmd_response:{command_id}`.

**Validates: Requirements 3.1, 3.4, 3.5**

### Property 4: Worker channel dispatch correctness

*For any* message arriving on channel `worker:{worker_id}` with field `target_workstation_id`, IF the workstation is connected locally THEN the message SHALL be delivered to its WebSocket, ELSE the message SHALL be discarded without error.

**Validates: Requirements 2.3, 2.4, 9.1**

### Property 5: Cross-worker message routing

*For any* message sent to a workstation not connected locally, IF WorkerRegistry resolves the workstation to a worker_id, THEN the message SHALL be published to `worker:{resolved_worker_id}` with the original payload including `target_workstation_id`.

**Validates: Requirements 2.2**

### Property 6: Command response routing via worker channel

*For any* command response from a workstation on Worker B where the command was originated by Worker A, the response SHALL be published to channel `worker:A` with fields `type`=`cmd_response` and the original `command_id`.

**Validates: Requirements 3.2**

### Property 7: Command response resolves waiter

*For any* message arriving on channel `worker:{worker_id}` with field `type`=`cmd_response`, the command waiter matching the `command_id` field SHALL be resolved with the response payload.

**Validates: Requirements 3.3, 9.2**

### Property 8: Lazy org subscription invariant

*For any* sequence of workstation connects and disconnects, the channel `org:{org_id}` SHALL be subscribed if and only if `_org_ws_count[org_id] > 0`. Specifically: SUBSCRIBE fires exactly when count transitions 0→1, and UNSUBSCRIBE fires exactly when count transitions 1→0.

**Validates: Requirements 4.1, 4.2, 4.3, 4.4**

### Property 9: VLAN filtering on org messages

*For any* message arriving on channel `org:{organization_id}` with field `target_vlan_id`, the message SHALL be delivered only to locally connected workstations whose stored `vlan_id` equals `target_vlan_id`. Workstations with a different or None vlan_id SHALL NOT receive the message.

**Validates: Requirements 5.1, 5.3**

### Property 10: Tenant isolation

*For any* message delivered to a workstation (via worker channel or org channel), the `organization_id` in the message or channel SHALL match the `organization_id` stored for that workstation. Messages with mismatched organization_id SHALL be discarded.

**Validates: Requirements 8.1, 8.3**

### Property 11: Global broadcast delivery

*For any* message arriving on channel `global:broadcast`, the message SHALL be delivered to ALL workstations in `workstation_connections` without filtering.

**Validates: Requirements 9.4**

### Property 12: Reconnect subscribes exact channel set

*For any* state of locally connected workstations at the moment of Redis reconnection, the set of channels subscribed SHALL be exactly `{worker:{self._worker_id}, global:broadcast} ∪ {org:{org_id} for org_id in _org_ws_count where count > 0}`. The number of SUBSCRIBE operations SHALL equal 2 + len(active_orgs), independent of the number of connected workstations.

**Validates: Requirements 7.3, 10.1, 10.2**

### Property 13: Reconnect re-registers all local workstations

*For any* state of locally connected workstations at the moment of Redis reconnection, every workstation_id in `workstation_connections.keys()` SHALL be re-registered in WorkerRegistry via SADD.

**Validates: Requirements 7.4**

### Property 14: Graceful fallback without Redis

*For any* operation (send, connect, disconnect) performed while `_redis_available` is False, the RedisConnectionManager SHALL NOT attempt any Redis operation (PUBLISH, SUBSCRIBE, UNSUBSCRIBE, SADD, SREM) and SHALL complete the local portion of the operation without error.

**Validates: Requirements 7.1, 7.2**

### Property 15: Fire-and-forget resilience

*For any* fire-and-forget Redis operation (WorkerRegistry SADD, lazy SUBSCRIBE) that raises an exception during connect_workstation, the workstation SHALL remain in `workstation_connections` and local state SHALL be unaffected.

**Validates: Requirements 6.3**
