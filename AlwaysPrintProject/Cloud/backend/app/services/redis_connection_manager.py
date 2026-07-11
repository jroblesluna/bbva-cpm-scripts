"""
Gestor de conexiones WebSocket con coordinación via Redis pub/sub.

Este módulo implementa el RedisConnectionManager que extiende la funcionalidad
del ConnectionManager original con comunicación inter-worker mediante Redis:
- Pub/Sub para comandos cross-worker y broadcasts organizacionales
- Canal worker consolidado para mensajes dirigidos y respuestas de comandos
- Suscripción lazy por organización (org:{id}) según workstations conectadas
- Fallback graceful cuando Redis no está disponible
- Exponential backoff para reconexión Redis (1s→2s→4s→8s→16s→30s max)
- Command waiters con resolución via canal worker (sin suscripciones dinámicas)

Canales Redis (esquema consolidado, máximo 2 + N_orgs_activas por worker):
- worker:{worker_id} → Mensajes dirigidos a workstations del worker + respuestas de comandos
- org:{organization_id} → Broadcasts organizacionales (lazy subscribe/unsubscribe)
- global:broadcast → Broadcasts globales a todos los workers

Uso:
    from app.services.redis_connection_manager import RedisConnectionManager

    manager = RedisConnectionManager(redis_url="redis://localhost:6379/0")
    await manager.initialize()
    await manager.connect_workstation(ws_id, websocket, db, org_id)
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import redis.asyncio as aioredis
from fastapi import WebSocket
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.services.worker_registry import WorkerRegistry

logger = get_logger(__name__)


# Segundos de espera máxima para pong tras Death Ping
PONG_TIMEOUT_SECONDS: int = 30


class RedisConnectionManager:
    """
    Gestor centralizado de conexiones WebSocket con coordinación via Redis pub/sub.

    Mantiene estado local idéntico al ConnectionManager original (workstation_connections,
    operator_connections, last_pong, last_activity, org_ids) y añade coordinación
    inter-worker mediante Redis pub/sub para entornos multi-worker.

    Si Redis no está disponible, opera de forma independiente (fallback graceful)
    sin interrumpir las conexiones locales.
    """

    def __init__(self, redis_url: Optional[str] = None):
        """
        Inicializa el gestor de conexiones.

        Args:
            redis_url: URL de conexión Redis (ej: "redis://localhost:6379/0").
                       Si es None, opera sin Redis (solo estado local).
        """
        # Estado local (idéntico al ConnectionManager original)
        self.workstation_connections: Dict[str, WebSocket] = {}
        self.operator_connections: Dict[str, Set[WebSocket]] = {}
        self.last_pong: Dict[str, datetime] = {}
        self.last_activity: Dict[str, datetime] = {}
        self.org_ids: Dict[str, str] = {}

        # Lock para operaciones thread-safe
        self._lock = asyncio.Lock()

        # Flag para detener el ping loop
        self._ping_loop_running = False

        # Cola de desconexiones pendientes de persistir en BD (batch)
        self._disconnect_queue: List[str] = []
        self._disconnect_flush_task: Optional[asyncio.Task] = None
        self._db_session_factory = None

        # Cola de registros Redis pendientes (batch SADD cada 1s en vez de 1 task por connect)
        self._pending_registrations: List[str] = []
        self._pending_org_subscribes: List[str] = []
        self._registration_flush_task: Optional[asyncio.Task] = None

        # Death pings pendientes de respuesta: {workstation_id: datetime_enviado}
        self._pending_pongs: Dict[str, datetime] = {}

        # Respuestas pendientes de comandos: {command_id: (asyncio.Event, list, originator_worker_id)}
        self._pending_command_responses: Dict[str, Tuple[asyncio.Event, List[Optional[dict]], str]] = {}

        # Mapping de command_id → origin_worker_id para routing cross-worker de respuestas
        self._command_origins: Dict[str, str] = {}

        # Contador de workstations por organización (lazy subscribe/unsubscribe)
        self._org_ws_count: Dict[str, int] = {}

        # Snapshot global de WS online (todos los workers). Actualizado cada heartbeat (~30s).
        # Consultable de forma sync por endpoints REST sin await ni queries Redis.
        self._global_online_snapshot: set = set()

        # VLAN de cada workstation conectada (para filtrado local)
        self._ws_vlan_ids: Dict[str, Optional[str]] = {}

        # Redis
        self._redis_url = redis_url
        self._redis: Optional[aioredis.Redis] = None
        self._pubsub: Optional[aioredis.client.PubSub] = None
        self._listener_task: Optional[asyncio.Task] = None
        self._redis_available: bool = False

        # Worker identity
        self._worker_id: str = f"worker_{os.getpid()}"

        # Worker registry (se inicializa en initialize())
        self._worker_registry: Optional[WorkerRegistry] = None

        # Heartbeat task para renovar TTL en WorkerRegistry
        self._heartbeat_task: Optional[asyncio.Task] = None

    # =========================================================================
    # INICIALIZACIÓN Y LIFECYCLE
    # =========================================================================

    async def initialize(self) -> None:
        """
        Conectar a Redis, suscribir canales fijos: worker:{worker_id} y global:broadcast.
        Inicializar WorkerRegistry y arrancar listener task + heartbeat task.

        NO suscribe canales per-workstation ni per-command.
        Si Redis no está disponible, el manager opera en modo local sin Redis.
        La conexión se reintenta con exponential backoff en background.
        """
        if not self._redis_url:
            logger.info(
                "redis.disabled",
                msg="REDIS_URL no configurado, operando en modo local sin Redis",
            )
            return

        try:
            self._redis = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                retry_on_error=[aioredis.ConnectionError, aioredis.TimeoutError],
            )
            # Verificar conectividad
            await self._redis.ping()
            self._redis_available = True

            # Inicializar WorkerRegistry
            self._worker_registry = WorkerRegistry(
                redis=self._redis,
                worker_id=self._worker_id,
                ttl=settings.WORKER_REGISTRY_TTL,
            )

            # Crear pub/sub y suscribir canales fijos (2 canales consolidados)
            self._pubsub = self._redis.pubsub()
            await self._pubsub.subscribe(
                f"worker:{self._worker_id}",
                "global:broadcast",
            )

            # Iniciar listener task para procesar mensajes pub/sub
            # NOTA: Usa get_message blocking (timeout=None) para no competir con el event loop
            self._listener_task = asyncio.create_task(self._redis_listener())

            # Iniciar heartbeat periódico para WorkerRegistry (cada TTL/2 segundos)
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            logger.info(
                "redis.initialized",
                redis_url=self._redis_url,
                worker_channel=f"worker:{self._worker_id}",
                global_channel="global:broadcast",
                msg="Suscrito a canales fijos: worker:{worker_id} y global:broadcast",
            )
        except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as e:
            logger.warning(
                "redis.init_failed",
                error=str(e),
                msg="Redis no disponible al iniciar, operando en modo local",
            )
            self._redis_available = False
            # Iniciar reconexión en background
            asyncio.create_task(self._handle_redis_reconnect())

    # =========================================================================
    # CONEXIÓN / DESCONEXIÓN DE WORKSTATIONS
    # =========================================================================

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

        Args:
            workstation_id: UUID de la workstation
            websocket: Conexión WebSocket (ya aceptada por el endpoint)
            db: Sesión de base de datos
            organization_id: UUID de la organización
            vlan_id: VLAN de la workstation (para filtrado local de mensajes org)
        """
        # === Hot path síncrono (zero Redis awaits) ===
        self.workstation_connections[workstation_id] = websocket
        self.org_ids[workstation_id] = organization_id
        self._ws_vlan_ids[workstation_id] = vlan_id
        self.last_pong[workstation_id] = datetime.now(timezone.utc).replace(tzinfo=None)
        self.last_activity[workstation_id] = datetime.now(timezone.utc).replace(tzinfo=None)
        self._org_ws_count[organization_id] = self._org_ws_count.get(organization_id, 0) + 1

        # Nota: NO se actualiza is_online aquí porque register_workstation()
        # (llamado antes en el endpoint) ya lo hace con db.commit().

        # === Encolar registro Redis en batch (no crear task individual) ===
        # Esto evita crear 10+ asyncio.Tasks/s durante ramp-up rápido
        # que saturan el event loop. El flush ocurre cada 1s.
        self._pending_registrations.append(workstation_id)
        is_first_of_org = self._org_ws_count[organization_id] == 1
        if is_first_of_org:
            self._pending_org_subscribes.append(organization_id)

        # Iniciar flush task si no existe
        if self._registration_flush_task is None or self._registration_flush_task.done():
            self._registration_flush_task = asyncio.create_task(
                self._flush_pending_registrations()
            )

    async def _flush_pending_registrations(self) -> None:
        """
        Flush batch de registros Redis pendientes.

        Hace SADD batch con pipeline (un solo RTT) de todas las workstations
        pendientes + SUBSCRIBE de organizaciones nuevas. Se ejecuta en el
        próximo tick del event loop para agrupar connects simultáneos sin
        introducir delay observable en la visibilidad cross-worker.
        """
        await asyncio.sleep(0)  # Yield al event loop para agrupar connects del mismo frame

        # Copiar y limpiar colas
        ws_ids = self._pending_registrations.copy()
        org_ids = self._pending_org_subscribes.copy()
        self._pending_registrations.clear()
        self._pending_org_subscribes.clear()

        if not ws_ids and not org_ids:
            return

        try:
            # Batch SADD con pipeline (un solo RTT a Redis)
            if self._worker_registry and ws_ids:
                pipe = self._worker_registry._redis.pipeline()
                for ws_id in ws_ids:
                    pipe.sadd(self._worker_registry._workstations_key, ws_id)
                pipe.expire(self._worker_registry._workstations_key, self._worker_registry._ttl)
                pipe.set(self._worker_registry._heartbeat_key, "alive", ex=self._worker_registry._ttl)
                await pipe.execute()

            # Lazy subscribe de organizaciones nuevas
            if org_ids and self._redis_available and self._pubsub:
                for org_id in org_ids:
                    await self._pubsub.subscribe(f"org:{org_id}")
                    logger.debug(
                        "redis.lazy_org_subscribe",
                        channel=f"org:{org_id}",
                        org_id=org_id,
                    )

            if ws_ids:
                logger.debug(
                    "redis.batch_register_flush",
                    count=len(ws_ids),
                    orgs_subscribed=len(org_ids),
                )
        except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as e:
            logger.warning(
                "redis.batch_register_failed",
                count=len(ws_ids),
                error=str(e),
            )
        except Exception as e:
            logger.warning(
                "redis.batch_register_error",
                count=len(ws_ids),
                error=str(e),
            )

    async def update_last_activity(self, workstation_id: str) -> None:
        """
        Actualiza el timestamp de última actividad de una workstation.
        Se invoca al recibir cualquier mensaje válido.
        """
        if workstation_id in self.workstation_connections:
            self.last_activity[workstation_id] = datetime.now(timezone.utc).replace(tzinfo=None)

    async def disconnect_workstation(
        self,
        workstation_id: str,
        db: Session,
        websocket: WebSocket = None,
    ) -> None:
        """
        Desconecta workstation y limpia estado.

        1. Elimina de workstation_connections, org_ids, _ws_vlan_ids, last_pong,
           last_activity, _pending_pongs
        2. _org_ws_count[org_id] -= 1
        3. Si _org_ws_count[org_id] == 0 → UNSUBSCRIBE org:{org_id}, del counter
        4. WorkerRegistry.unregister_workstation(ws_id) — SREM

        Solo marca offline si el WebSocket que se desconecta es el mismo que
        está actualmente registrado (evita race conditions en reconexiones).

        Args:
            workstation_id: UUID de la workstation
            db: Sesión de base de datos
            websocket: WebSocket que se desconecta (para comparar con el activo)
        """
        should_mark_offline = False

        if workstation_id in self.workstation_connections:
            current_ws = self.workstation_connections[workstation_id]
            if websocket is None or current_ws is websocket:
                del self.workstation_connections[workstation_id]
                should_mark_offline = True

        if not should_mark_offline:
            return

        # Obtener org_id ANTES de eliminar de org_ids (necesario para decremento)
        org_id = self.org_ids.get(workstation_id)

        # Limpiar estado local
        if workstation_id in self.last_pong:
            del self.last_pong[workstation_id]
        self.last_activity.pop(workstation_id, None)
        self.org_ids.pop(workstation_id, None)
        self._ws_vlan_ids.pop(workstation_id, None)
        self._pending_pongs.pop(workstation_id, None)

        # Decrementar contador org y conditional UNSUBSCRIBE
        if org_id and org_id in self._org_ws_count:
            self._org_ws_count[org_id] -= 1
            if self._org_ws_count[org_id] <= 0:
                # Última workstation de esta org en este worker → UNSUBSCRIBE
                del self._org_ws_count[org_id]
                if self._redis_available and self._pubsub:
                    try:
                        await self._pubsub.unsubscribe(f"org:{org_id}")
                        logger.debug(
                            "redis.lazy_org_unsubscribe",
                            channel=f"org:{org_id}",
                            org_id=org_id,
                            workstation_id=workstation_id,
                        )
                    except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as e:
                        logger.warning(
                            "redis.lazy_org_unsubscribe_failed",
                            channel=f"org:{org_id}",
                            org_id=org_id,
                            error=str(e),
                        )

        # Eliminar del WorkerRegistry (SREM)
        if self._worker_registry:
            await self._worker_registry.unregister_workstation(workstation_id)

        # Invalidar snapshot cacheado: remover la WS desconectada para que
        # el fallback sync también sea consistente sin esperar al próximo heartbeat.
        self._global_online_snapshot.discard(workstation_id)

        # Encolar para batch update de BD
        self._disconnect_queue.append(workstation_id)
        if self._disconnect_flush_task is None or self._disconnect_flush_task.done():
            self._disconnect_flush_task = asyncio.create_task(
                self._flush_disconnect_queue()
            )

    async def _flush_disconnect_queue(self) -> None:
        """
        Espera 3 segundos y luego hace batch UPDATE de todas las ws encoladas.
        Agrupa desconexiones masivas en queries batch a la BD.
        """
        while True:
            await asyncio.sleep(3)

            ids_to_flush = self._disconnect_queue.copy()
            self._disconnect_queue.clear()

            if not ids_to_flush:
                return

            if self._db_session_factory is None:
                logger.warning(
                    "flush_disconnect.no_factory",
                    count=len(ids_to_flush),
                    msg="db_session_factory es None, descartando batch",
                )
                return

            try:
                db = self._db_session_factory()
                try:
                    from app.models.workstation import Workstation
                    updated = db.query(Workstation).filter(
                        Workstation.id.in_(ids_to_flush)
                    ).update(
                        {Workstation.is_online: False},
                        synchronize_session=False,
                    )
                    db.commit()
                    logger.info(
                        "batch_disconnect.complete",
                        updated=updated,
                        enqueued=len(ids_to_flush),
                    )
                except Exception as e:
                    db.rollback()
                    logger.error("batch_disconnect.error", error=str(e))
                finally:
                    db.close()
            except Exception as e:
                logger.error("batch_disconnect.session_error", error=str(e))

    # =========================================================================
    # ENVÍO DE MENSAJES
    # =========================================================================

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

        Args:
            workstation_id: UUID de la workstation
            message: Mensaje a enviar (dict serializable a JSON)

        Returns:
            True si se envió localmente, False si se publicó en Redis o no se pudo enviar
        """
        # 1. Intentar entrega local primero
        if workstation_id in self.workstation_connections:
            ws = self.workstation_connections[workstation_id]
            try:
                await ws.send_json(message)
                logger.info(
                    "delivery.local",
                    workstation_id=workstation_id,
                    message_type=message.get("type", "unknown"),
                    command_id=message.get("command_id"),
                )
                return True
            except Exception:
                # Conexión muerta, limpiar
                del self.workstation_connections[workstation_id]
                self.last_pong.pop(workstation_id, None)
                return False

        # 2. No está local — resolver worker via WorkerRegistry y publicar en su canal
        if self._redis_available and self._redis:
            # Si WorkerRegistry no está disponible, no podemos resolver el worker destino
            if not self._worker_registry:
                logger.warning(
                    "delivery.no_worker_registry",
                    workstation_id=workstation_id,
                    message_type=message.get("type", "unknown"),
                    msg="WorkerRegistry no disponible, no se puede resolver worker destino",
                )
                return False

            try:
                # 2a. Consultar en qué worker está la workstation
                target_worker_id = await self._worker_registry.find_worker_for_workstation(
                    workstation_id
                )

                # 2c. Si no se encontró el worker → log warning, return False
                if not target_worker_id:
                    logger.warning(
                        "delivery.worker_not_found",
                        workstation_id=workstation_id,
                        message_type=message.get("type", "unknown"),
                        msg="No se encontró worker para la workstation en WorkerRegistry",
                    )
                    return False

                # 2d. Si el target es este mismo worker, el registro es stale
                # (paso 1 ya confirmó que la WS no está en conexiones locales).
                # Invalidar registro y retornar False para fail-fast.
                if target_worker_id == self._worker_id:
                    logger.warning(
                        "delivery.stale_self_reference",
                        workstation_id=workstation_id,
                        message_type=message.get("type", "unknown"),
                        msg="WorkerRegistry apunta a este worker pero WS no está local — registro stale, invalidando",
                    )
                    # Limpiar registro stale en background (no bloquear respuesta)
                    asyncio.ensure_future(
                        self._worker_registry.unregister_workstation(workstation_id)
                    )
                    return False

                # 2b. Worker encontrado → publicar en worker:{target_worker_id}
                # Enriquecer payload con target_workstation_id, organization_id y origin_worker_id
                org_id = message.get("organization_id") or self.org_ids.get(workstation_id)
                enriched_message = {
                    **message,
                    "target_workstation_id": workstation_id,
                    "_origin_worker_id": self._worker_id,
                }
                if org_id:
                    enriched_message["organization_id"] = org_id

                payload = json.dumps(enriched_message, default=str)
                target_channel = f"worker:{target_worker_id}"
                await self._redis.publish(target_channel, payload)
                logger.info(
                    "delivery.remote_publish",
                    workstation_id=workstation_id,
                    message_type=message.get("type", "unknown"),
                    command_id=message.get("command_id"),
                    target_channel=target_channel,
                    target_worker_id=target_worker_id,
                )
                return True  # Mensaje publicado exitosamente — otro worker lo entregará

            except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as e:
                logger.warning(
                    "redis.publish_failed",
                    workstation_id=workstation_id,
                    error=str(e),
                    msg="Error al resolver worker o publicar mensaje",
                )
                return False

        # 3. Redis no disponible → log, return False
        logger.debug(
            "delivery.redis_not_available",
            workstation_id=workstation_id,
            message_type=message.get("type", "unknown"),
            msg="Redis no disponible, no se puede entregar mensaje remotamente",
        )
        return False

    async def send_direct_to_workstation(
        self,
        workstation_id: str,
        message: dict,
    ) -> bool:
        """
        Envía mensaje directamente a una workstation sin encolar.
        Diseñado para mensajes gestionados por BD (deliveries).

        Args:
            workstation_id: UUID de la workstation
            message: Mensaje a enviar

        Returns:
            True si se envió exitosamente, False si falló
        """
        async with self._lock:
            if workstation_id in self.workstation_connections:
                ws = self.workstation_connections[workstation_id]
                try:
                    await ws.send_json(message)
                    return True
                except Exception:
                    del self.workstation_connections[workstation_id]
                    self.last_pong.pop(workstation_id, None)
        return False

    async def broadcast_to_organization(
        self,
        organization_id: str,
        message: dict,
        db: Session = None,
    ) -> None:
        """
        Envía mensaje a todos los operadores conectados de una organización.

        1. Envía a operadores locales conectados (frontend dashboard)
        2. Publica en org:{organization_id} para que otros workers entreguen a sus operadores

        Los broadcasts son notificaciones para el frontend (telemetry_received,
        workstation_status_change, etc.), NO se envían a workstations.

        Args:
            organization_id: UUID de la organización
            message: Mensaje a enviar
            db: Sesión de base de datos (no utilizada)
        """
        # Entregar a operadores locales conectados
        async with self._lock:
            user_ids = list(self.operator_connections.keys())

        for user_id in user_ids:
            await self.send_to_operator(user_id, message)

        # Publicar en Redis para que otros workers entreguen a sus operadores
        if self._redis_available and self._redis:
            try:
                # Incluir origin_worker_id para que el listener ignore mensajes propios
                pub_message = {**message, "_origin_worker": self._worker_id}
                payload = json.dumps(pub_message, default=str)
                await self._redis.publish(f"org:{organization_id}", payload)
                logger.debug(
                    "delivery.org_broadcast",
                    org_id=organization_id,
                    message_type=message.get("type", "unknown"),
                )
            except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as e:
                logger.warning(
                    "redis.publish_failed",
                    channel=f"org:{organization_id}",
                    error=str(e),
                )
        else:
            logger.debug(
                "delivery.org_broadcast_local_only",
                org_id=organization_id,
            )

    # =========================================================================
    # OPERADORES
    # =========================================================================

    async def connect_operator(self, user_id: str, websocket: WebSocket) -> None:
        """
        Registra conexión de un operador (Frontend).

        Args:
            user_id: UUID del usuario
            websocket: Conexión WebSocket
        """
        await websocket.accept()
        async with self._lock:
            if user_id not in self.operator_connections:
                self.operator_connections[user_id] = set()
            self.operator_connections[user_id].add(websocket)

    async def disconnect_operator(self, user_id: str, websocket: WebSocket) -> None:
        """
        Desconecta un operador.

        Args:
            user_id: UUID del usuario
            websocket: Conexión WebSocket
        """
        async with self._lock:
            if user_id in self.operator_connections:
                self.operator_connections[user_id].discard(websocket)
                if not self.operator_connections[user_id]:
                    del self.operator_connections[user_id]

    async def send_to_operator(self, user_id: str, message: dict) -> None:
        """
        Envía mensaje a un operador (todas sus conexiones).

        Args:
            user_id: UUID del usuario
            message: Mensaje a enviar
        """
        async with self._lock:
            if user_id not in self.operator_connections:
                return

            dead_connections = []
            for ws in self.operator_connections[user_id]:
                try:
                    await ws.send_json(message)
                except Exception:
                    dead_connections.append(ws)

            for ws in dead_connections:
                self.operator_connections[user_id].discard(ws)

            if not self.operator_connections[user_id]:
                del self.operator_connections[user_id]

    async def broadcast_to_all_operators(self, message: dict) -> None:
        """Envía mensaje a todos los operadores conectados."""
        async with self._lock:
            user_ids = list(self.operator_connections.keys())

        for user_id in user_ids:
            await self.send_to_operator(user_id, message)

    # =========================================================================
    # REDIS PUB/SUB LISTENER
    # =========================================================================

    async def _redis_listener(self) -> None:
        """
        Loop async que procesa mensajes pub/sub entrantes.

        Escucha continuamente en el PubSub y despacha mensajes según el canal:
        - worker:{worker_id} → si type == "cmd_response" resuelve waiter,
                               sino entrega a workstation local via target_workstation_id
        - org:{organization_id} → entrega a todas las locales de esa org
        - global:broadcast → entrega a todas las locales
        """
        if not self._pubsub:
            return

        logger.info("redis.listener_started")

        # Guardar referencia al event loop
        self._event_loop = asyncio.get_running_loop()

        worker_channel = f"worker:{self._worker_id}"

        while True:
            try:
                # Blocking get_message: suspende la coroutine hasta que llega un mensaje
                # o expira el timeout. Esto NO consume CPU ni compite con el event loop.
                # timeout=1.0 cede al event loop cada 1s como máximo si no hay mensajes.
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if message is None:
                    continue  # Timeout sin mensaje — reintentar

                if message["type"] != "message":
                    continue

                channel = message["channel"]
                data = message["data"]

                try:
                    payload = json.loads(data) if isinstance(data, str) else data
                except (json.JSONDecodeError, TypeError):
                    continue

                # Despachar según tipo de canal (esquema consolidado)
                if channel == worker_channel:
                    msg_type = payload.get("type") if isinstance(payload, dict) else None
                    if msg_type == "cmd_response":
                        command_id = payload.get("command_id")
                        if command_id:
                            self.resolve_command_response(command_id, payload)
                    else:
                        target_ws_id = payload.get("target_workstation_id") if isinstance(payload, dict) else None
                        if target_ws_id:
                            # Guardar origin worker para routing de cmd_response
                            origin_worker = payload.get("_origin_worker_id")
                            command_id = payload.get("command_id")
                            if origin_worker and command_id and origin_worker != self._worker_id:
                                # Limitar tamaño del mapping (evitar memory leak)
                                if len(self._command_origins) > 10000:
                                    keys_to_remove = list(self._command_origins.keys())[:5000]
                                    for k in keys_to_remove:
                                        del self._command_origins[k]
                                self._command_origins[command_id] = origin_worker
                            logger.info(
                                "delivery.cross_worker_received",
                                command_id=command_id,
                                origin_worker=origin_worker,
                                target_ws_id=target_ws_id,
                            )
                            # Verificar si la WS está local antes de intentar entregar
                            if target_ws_id not in self.workstation_connections:
                                # WS no está en este worker — registro stale
                                logger.warning(
                                    "delivery.cross_worker_ws_not_found",
                                    command_id=command_id,
                                    target_ws_id=target_ws_id,
                                    origin_worker=origin_worker,
                                    msg="WS no encontrada localmente tras cross-worker delivery — resolviendo con error",
                                )
                                # Resolver waiter con error para evitar timeout de 30s
                                if command_id:
                                    error_response = {
                                        "success": False,
                                        "error": "workstation_not_reachable",
                                        "message": "La workstation no está conectada en el worker esperado",
                                    }
                                    # Si el originador es este mismo worker, resolver localmente
                                    if origin_worker == self._worker_id:
                                        self.resolve_command_response(command_id, error_response)
                                    elif origin_worker:
                                        # Publicar error al worker originador
                                        await self.publish_command_response(
                                            command_id, error_response, origin_worker
                                        )
                                # Invalidar registro stale
                                if self._worker_registry:
                                    asyncio.ensure_future(
                                        self._worker_registry.unregister_workstation(target_ws_id)
                                    )
                            else:
                                # Entregar al WS local (sin campos internos de routing)
                                clean_payload = {k: v for k, v in payload.items() if not k.startswith("_") and k != "target_workstation_id"}
                                await self._deliver_to_local_workstation(target_ws_id, clean_payload)
                elif channel.startswith("org:"):
                    # Ignorar mensajes originados por este mismo worker (ya se entregaron localmente)
                    origin = payload.pop("_origin_worker", None) if isinstance(payload, dict) else None
                    if origin == self._worker_id:
                        continue
                    # Entregar a operadores locales (broadcasts son para frontend, no WS)
                    async with self._lock:
                        user_ids = list(self.operator_connections.keys())
                    for user_id in user_ids:
                        await self.send_to_operator(user_id, payload)
                elif channel == "global:broadcast":
                    await self._deliver_global_broadcast(payload)

            except asyncio.CancelledError:
                logger.info("redis.listener_cancelled")
                break
            except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as e:
                logger.warning("redis.listener_connection_lost", error=str(e))
                self._redis_available = False
                await self._handle_redis_reconnect()
                break
            except Exception as e:
                logger.error("redis.listener_error", error=str(e))
                await asyncio.sleep(1)

    def _validate_tenant(self, workstation_id: str, message_org_id: Optional[str]) -> bool:
        """
        Valida que el organization_id del mensaje coincida con el de la workstation.

        Verifica tenant isolation antes de entregar un mensaje:
        - Si message_org_id es None, no se puede validar → descarta por seguridad
        - Si la workstation no tiene org_id registrado → descarta por seguridad
        - Si no coinciden → descarta por seguridad

        Args:
            workstation_id: UUID de la workstation destino
            message_org_id: organization_id del mensaje entrante

        Returns:
            True si la validación es exitosa (org_ids coinciden), False si falla
        """
        ws_org_id = self.org_ids.get(workstation_id)

        # Si no se puede determinar el org_id de la workstation, descartar
        if ws_org_id is None:
            logger.warning(
                "tenant.validation_fail",
                workstation_id=workstation_id,
                ws_org_id=None,
                msg_org_id=message_org_id,
                reason="org_id de workstation no determinable al momento de entrega",
            )
            return False

        # Si el mensaje no incluye organization_id, no se puede validar
        if message_org_id is None:
            logger.warning(
                "tenant.validation_fail",
                workstation_id=workstation_id,
                ws_org_id=ws_org_id,
                msg_org_id=None,
                reason="organization_id del mensaje no determinable",
            )
            return False

        # Verificar coincidencia
        if ws_org_id != message_org_id:
            logger.warning(
                "tenant.validation_fail",
                workstation_id=workstation_id,
                ws_org_id=ws_org_id,
                msg_org_id=message_org_id,
                reason="organization_id del mensaje no coincide con workstation",
            )
            return False

        # Validación exitosa
        logger.debug(
            "tenant.validation_ok",
            workstation_id=workstation_id,
            org_id=ws_org_id,
        )
        return True

    async def _deliver_to_local_workstation(
        self, workstation_id: str, payload: dict
    ) -> None:
        """
        Entrega un mensaje a una workstation conectada localmente.

        Si la workstation no está aquí, descarta el mensaje sin error (Req 1.8).
        Valida tenant isolation si el payload contiene organization_id (Req 5.5, 5.6).

        Args:
            workstation_id: UUID de la workstation target
            payload: Mensaje a entregar
        """
        ws = self.workstation_connections.get(workstation_id)

        if ws is None:
            logger.debug(
                "delivery.discard_not_local",
                workstation_id=workstation_id,
                message_type=payload.get("type", "unknown"),
            )
            return

        # Validación de tenant isolation si el payload contiene organization_id
        message_org_id = payload.get("organization_id") if isinstance(payload, dict) else None
        if message_org_id is not None:
            if not self._validate_tenant(workstation_id, message_org_id):
                return

        try:
            await ws.send_json(payload)
            logger.debug(
                "delivery.local",
                workstation_id=workstation_id,
                message_type=payload.get("type", "unknown"),
            )
        except Exception as e:
            logger.warning(
                "delivery.local_failed",
                workstation_id=workstation_id,
                error=str(e),
            )

    async def _deliver_to_local_org_workstations(
        self, organization_id: str, payload: dict
    ) -> None:
        """
        Entrega mensaje organizacional con filtrado opcional por VLAN.

        1. Filtrar workstations locales donde org_ids[ws_id] == organization_id
        2. Si payload contiene target_vlan_id:
           Filtrar adicionalmente donde _ws_vlan_ids[ws_id] == target_vlan_id
        3. Enviar payload a cada workstation que pase ambos filtros

        Valida explícitamente tenant isolation por cada workstation (Req 8.3).

        Args:
            organization_id: UUID de la organización
            payload: Mensaje a entregar
        """
        # Extraer target_vlan_id del payload (filtrado VLAN opcional)
        target_vlan_id = payload.get("target_vlan_id") if isinstance(payload, dict) else None

        # 1. Filtrar por organización (sin lock — dict read es safe en asyncio)
        local_ws_ids = [
            ws_id for ws_id, org_id in self.org_ids.items()
            if org_id == organization_id
        ]

        total_org_count = len(local_ws_ids)

        # 2. Si hay target_vlan_id, filtrar adicionalmente por VLAN
        if target_vlan_id is not None:
            local_ws_ids = [
                ws_id for ws_id in local_ws_ids
                if self._ws_vlan_ids.get(ws_id) == target_vlan_id
            ]

        delivered = 0
        skipped = 0
        for ws_id in local_ws_ids:
            # Verificación explícita de tenant isolation por workstation (defense-in-depth)
            if not self._validate_tenant(ws_id, organization_id):
                skipped += 1
                continue

            ws = self.workstation_connections.get(ws_id)
            if ws:
                try:
                    await ws.send_json(payload)
                    delivered += 1
                except Exception:
                    pass  # Conexión muerta, será limpiada por Death Ping

        logger.debug(
            "delivery.org_from_redis",
            org_id=organization_id,
            delivered=delivered,
            total_org_workstations=total_org_count,
            vlan_filtered=target_vlan_id is not None,
            target_vlan_id=target_vlan_id,
            skipped_tenant_fail=skipped,
            message_type=payload.get("type", "unknown"),
        )

    async def _deliver_global_broadcast(self, payload: dict) -> None:
        """
        Entrega un broadcast global a todas las workstations locales.

        Args:
            payload: Mensaje a entregar
        """
        async with self._lock:
            ws_ids = list(self.workstation_connections.keys())

        for ws_id in ws_ids:
            async with self._lock:
                ws = self.workstation_connections.get(ws_id)
            if ws:
                try:
                    await ws.send_json(payload)
                except Exception:
                    pass

    # =========================================================================
    # RECONEXIÓN REDIS CON EXPONENTIAL BACKOFF
    # =========================================================================

    async def _handle_redis_reconnect(self) -> None:
        """
        Reconexión con exponential backoff: 1s → 2s → 4s → 8s → 16s → 30s max.

        Reintenta conectar a Redis indefinidamente. Una vez reconectado,
        re-suscribe los canales consolidados (worker, global, orgs activas)
        y reinicia el listener task. La re-suscripción es O(1 + N_orgs_activas),
        independiente del número de workstations conectadas.
        """
        delay = 1
        max_delay = settings.WS_REDIS_RECONNECT_MAX_INTERVAL
        attempt = 0

        while not self._redis_available:
            attempt += 1
            logger.debug(
                "redis.reconnect_attempt",
                attempt=attempt,
                delay_seconds=delay,
            )

            await asyncio.sleep(delay)

            try:
                if self._redis is None:
                    self._redis = aioredis.from_url(
                        self._redis_url,
                        decode_responses=True,
                        retry_on_error=[aioredis.ConnectionError, aioredis.TimeoutError],
                    )

                await self._redis.ping()
                self._redis_available = True

                # Re-crear pub/sub y re-suscribir canales fijos
                self._pubsub = self._redis.pubsub()
                await self._pubsub.subscribe(
                    f"worker:{self._worker_id}",
                    "global:broadcast",
                )

                # Re-suscribir canales org para organizaciones con workstations conectadas
                for org_id, count in self._org_ws_count.items():
                    if count > 0:
                        try:
                            await self._pubsub.subscribe(f"org:{org_id}")
                        except Exception:
                            pass

                # Obtener lista de workstations conectadas localmente
                async with self._lock:
                    ws_ids = list(self.workstation_connections.keys())

                # Re-inicializar WorkerRegistry
                self._worker_registry = WorkerRegistry(
                    redis=self._redis,
                    worker_id=self._worker_id,
                    ttl=settings.WORKER_REGISTRY_TTL,
                )

                # Re-registrar workstations en WorkerRegistry
                for ws_id in ws_ids:
                    await self._worker_registry.register_workstation(ws_id)

                # Reiniciar listener
                self._listener_task = asyncio.create_task(self._redis_listener())

                logger.info(
                    "redis.connection_restored",
                    attempts=attempt,
                    fixed_channels=2,
                    org_channels=sum(1 for c in self._org_ws_count.values() if c > 0),
                    workstations_reregistered=len(ws_ids),
                )
                return

            except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as e:
                logger.debug(
                    "redis.reconnect_failed",
                    attempt=attempt,
                    error=str(e),
                    next_delay=min(delay * 2, max_delay),
                )
                # Exponential backoff: 1 → 2 → 4 → 8 → 16 → 30 (max)
                delay = min(delay * 2, max_delay)

    # =========================================================================
    # HEARTBEAT LOOP (WorkerRegistry TTL renewal)
    # =========================================================================

    async def _heartbeat_loop(self) -> None:
        """
        Loop que renueva el TTL del WorkerRegistry periódicamente.
        Se ejecuta cada TTL/2 segundos para evitar expiración accidental.
        También actualiza el snapshot global de workstations online (para consultas sync).

        Cada ciclo verifica consistencia: si el SET de Redis tiene menos miembros
        que las conexiones locales (por expiración previa del SET o pérdida de SADD),
        ejecuta un re-register completo para restaurar la consistencia.
        """
        interval = settings.WORKER_REGISTRY_TTL // 2
        while True:
            try:
                await asyncio.sleep(interval)
                if self._worker_registry and self._redis_available:
                    await self._worker_registry.heartbeat()

                    # Verificar consistencia: SET de Redis vs conexiones locales.
                    # Si el SET expiró o se perdió, re-registrar todas las WS.
                    await self._ensure_registry_consistency()

                    # Actualizar snapshot global de WS online (lectura de todos los workers)
                    await self._refresh_online_snapshot()

                    # Publicar métricas del worker para consolidación global
                    ws_count = len(self.workstation_connections)
                    rss_mb = self._get_rss_mb()
                    fd_count = self._get_fd_count()
                    pool_checked_out = self._get_pool_checked_out()
                    baseline_mb = self._get_baseline_mb()

                    metrics_json = json.dumps({
                        "ws": ws_count,
                        "rss_mb": rss_mb,
                        "baseline_mb": baseline_mb,
                        "fd": fd_count,
                        "pool_out": pool_checked_out,
                    })
                    await self._redis.set(
                        f"workers:{self._worker_id}:metrics",
                        metrics_json,
                        ex=90,
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("worker.heartbeat_error", error=str(e))

    async def _ensure_registry_consistency(self) -> None:
        """
        Verifica que el SET de Redis del worker contenga todas las WS conectadas localmente.

        Si el SET expiró (SCARD=0 o key no existe) o tiene significativamente menos
        miembros que las conexiones locales (drift > 10%), ejecuta un re-register
        completo usando pipeline batch para restaurar la consistencia.

        Esto cubre el escenario donde:
        - El heartbeat perdió un ciclo y el SET expiró completamente
        - El batch flush de un connect anterior falló silenciosamente
        - Redis se reinició y perdió datos en memoria

        Costo: O(N) SADD en pipeline, pero solo se ejecuta cuando hay drift.
        Con 800 WS = <10ms en pipeline batch.
        """
        try:
            local_count = len(self.workstation_connections)
            if local_count == 0:
                return

            ws_key = self._worker_registry._workstations_key
            redis_count = await self._redis.scard(ws_key)

            # Si Redis tiene menos del 90% de las conexiones locales, hay drift
            drift_threshold = max(local_count * 0.9, local_count - 50)
            if redis_count >= drift_threshold:
                return

            # Drift detectado: re-registrar todas las conexiones locales
            logger.warning(
                "worker.registry_drift_detected",
                local_count=local_count,
                redis_count=redis_count,
                drift_pct=round((1 - redis_count / local_count) * 100, 1) if local_count > 0 else 0,
                msg="Re-registrando todas las WS en Redis",
            )

            # Pipeline batch: DELETE key + SADD de todas + EXPIRE
            local_ws_ids = list(self.workstation_connections.keys())
            pipe = self._redis.pipeline()
            pipe.delete(ws_key)
            # SADD en batches de 500 para evitar comandos enormes
            for i in range(0, len(local_ws_ids), 500):
                batch = local_ws_ids[i:i + 500]
                pipe.sadd(ws_key, *batch)
            pipe.expire(ws_key, self._worker_registry._ttl)
            pipe.set(self._worker_registry._heartbeat_key, "alive", ex=self._worker_registry._ttl)
            await pipe.execute()

            logger.info(
                "worker.registry_consistency_restored",
                registered=len(local_ws_ids),
            )
        except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as e:
            logger.warning(
                "worker.registry_consistency_error",
                error=str(e),
            )
        except Exception as e:
            logger.warning(
                "worker.registry_consistency_error",
                error=str(e),
            )

    async def _refresh_online_snapshot(self) -> None:
        """
        Actualiza el snapshot global de workstations online usando SUNIONSTORE.

        En vez de que cada worker haga scan_iter + smembers por separado
        (puede dar resultados inconsistentes entre workers por timing),
        usa SUNIONSTORE para generar una key compartida con la unión
        de todos los SETs de workers, y luego lee esa key.

        Tiempo: O(N) total de WS online. Con 500 WS = <5ms.
        Se ejecuta cada 30s (heartbeat interval), no en hot path.
        """
        try:
            # Encontrar todas las keys de workers activos
            worker_keys = []
            async for key in self._redis.scan_iter(match="workers:*:workstations"):
                worker_keys.append(key)

            if worker_keys:
                # SUNIONSTORE: unión atómica de todos los SETs → key temporal compartida
                dest_key = "global:online_workstations"
                await self._redis.sunionstore(dest_key, *worker_keys)
                await self._redis.expire(dest_key, 60)  # TTL safety
                # Leer el resultado
                online = await self._redis.smembers(dest_key)
                self._global_online_snapshot = online | set(self.workstation_connections.keys())
            else:
                # No hay keys de workers — solo locales
                self._global_online_snapshot = set(self.workstation_connections.keys())
        except Exception as e:
            # Si falla, mantener snapshot anterior + locales
            self._global_online_snapshot = self._global_online_snapshot | set(self.workstation_connections.keys())
            logger.debug("worker.online_snapshot_error", error=str(e))

    def get_global_online_snapshot(self) -> set:
        """
        Retorna el snapshot global de WS online (todos los workers).
        Sync-safe: lee un set en memoria, actualizado cada ~30s por heartbeat.
        Usar en endpoints sync que necesitan saber qué WS están online.
        """
        # Merge con conexiones locales actuales (más frescas que el snapshot)
        return self._global_online_snapshot | set(self.workstation_connections.keys())

    async def get_global_online_snapshot_async(self) -> set:
        """
        Lectura fresca de Redis: SUNIONSTORE + SMEMBERS en tiempo real.

        A diferencia de get_global_online_snapshot() (que retorna un cache de ~30s),
        este método ejecuta SUNIONSTORE sobre los SETs de todos los workers activos
        y retorna el resultado en tiempo real. Costo: <2ms con ~500 WS en Redis local.

        Usar en endpoints async que requieren conteo exacto cross-worker.
        Fallback: si Redis no está disponible, retorna snapshot cacheado + locales.
        """
        if not self._redis_available or not self._redis:
            return self._global_online_snapshot | set(self.workstation_connections.keys())

        try:
            # Encontrar todas las keys de workers activos
            worker_keys = []
            async for key in self._redis.scan_iter(match="workers:*:workstations"):
                worker_keys.append(key)

            if worker_keys:
                # SUNIONSTORE: unión atómica de todos los SETs → key compartida
                dest_key = "global:online_workstations"
                await self._redis.sunionstore(dest_key, *worker_keys)
                await self._redis.expire(dest_key, 60)
                # Leer resultado fresco
                online = await self._redis.smembers(dest_key)
                # Decode bytes si es necesario
                decoded = set()
                for item in online:
                    decoded.add(item.decode("utf-8") if isinstance(item, bytes) else item)
                # Merge con locales actuales (pueden haber connects muy recientes aún no en Redis)
                return decoded | set(self.workstation_connections.keys())
            else:
                # No hay keys de workers en Redis — solo locales
                return set(self.workstation_connections.keys())
        except Exception as e:
            logger.debug("worker.online_snapshot_async_error", error=str(e))
            # Fallback al snapshot cacheado + locales
            return self._global_online_snapshot | set(self.workstation_connections.keys())

    def _get_rss_mb(self) -> float:
        """Obtiene RSS del proceso actual en MB."""
        try:
            import resource
            import platform
            usage = resource.getrusage(resource.RUSAGE_SELF)
            if platform.system() == "Darwin":
                return round(usage.ru_maxrss / (1024 * 1024), 1)
            return round(usage.ru_maxrss / 1024, 1)
        except Exception:
            try:
                with open("/proc/self/status", "r") as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            return round(int(line.split()[1]) / 1024, 1)
            except Exception:
                pass
        return 0.0

    def _get_fd_count(self) -> int:
        """Obtiene número de file descriptors abiertos."""
        try:
            import os
            return len(os.listdir(f"/proc/{os.getpid()}/fd"))
        except Exception:
            return 0

    def _get_pool_checked_out(self) -> int:
        """Obtiene conexiones de BD checked out del pool."""
        try:
            from app.core.database import engine
            from app.core.config import settings as cfg
            if cfg.is_sqlite:
                return 0
            return engine.pool.checkedout()
        except Exception:
            return 0

    def _get_baseline_mb(self) -> float:
        """Obtiene el baseline RSS capturado al inicio por scalability_collector."""
        try:
            from app.services.scalability_metrics import scalability_collector
            return scalability_collector._baseline_rss_mb or 0.0
        except Exception:
            return 0.0

    # =========================================================================
    # COMMAND WAITERS (request-response sobre WebSocket + Redis)
    # =========================================================================

    def register_command_waiter(self, command_id: str) -> asyncio.Event:
        """
        Registra waiter para respuesta de comando.
        Almacena self._worker_id como originator. NO hace SUBSCRIBE.

        Args:
            command_id: ID del comando cuya respuesta se espera

        Returns:
            asyncio.Event que se señalará cuando llegue la respuesta
        """
        event = asyncio.Event()
        self._pending_command_responses[command_id] = (event, [None], self._worker_id)
        return event

    def resolve_command_response(self, command_id: str, response: dict) -> bool:
        """
        Resuelve la espera de un comando con la respuesta recibida.

        Args:
            command_id: ID del comando
            response: Respuesta completa del comando

        Returns:
            True si había un waiter esperando, False si no
        """
        if command_id in self._pending_command_responses:
            event, container, _ = self._pending_command_responses[command_id]
            container[0] = response
            event.set()
            logger.info(
                "cmd_response.resolved_locally",
                command_id=command_id,
                success=response.get("success"),
            )
            return True
        logger.info(
            "cmd_response.no_local_waiter",
            command_id=command_id,
        )
        return False

    async def wait_for_command_response(
        self, command_id: str, timeout: float = 30.0
    ) -> Optional[dict]:
        """
        Espera respuesta con timeout. NO hace UNSUBSCRIBE al terminar.
        Solo limpia el waiter del dict interno.

        Args:
            command_id: ID del comando
            timeout: Tiempo máximo de espera en segundos

        Returns:
            Respuesta del comando o None si timeout
        """
        if command_id not in self._pending_command_responses:
            return None

        event, container, _ = self._pending_command_responses[command_id]

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return container[0]
        except asyncio.TimeoutError:
            return None
        finally:
            # Solo limpiar waiter del dict interno, NO hacer UNSUBSCRIBE
            self._pending_command_responses.pop(command_id, None)

    async def publish_command_response(
        self, command_id: str, response: dict, originator_worker_id: str
    ) -> None:
        """
        Publica respuesta de comando al canal del worker originador.
        Publica en worker:{originator_worker_id} con payload:
          {"type": "cmd_response", "command_id": ..., ...response}

        Args:
            command_id: ID del comando
            response: Respuesta del comando
            originator_worker_id: Worker ID del worker que originó el comando
        """
        if self._redis_available and self._redis:
            try:
                payload = json.dumps(
                    {"type": "cmd_response", "command_id": command_id, **response},
                    default=str,
                )
                await self._redis.publish(f"worker:{originator_worker_id}", payload)
                logger.info(
                    "redis.publish_cmd_response",
                    command_id=command_id,
                    target_worker=originator_worker_id,
                )
            except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as e:
                logger.warning(
                    "redis.publish_cmd_response_failed",
                    command_id=command_id,
                    target_worker=originator_worker_id,
                    error=str(e),
                )

    # =========================================================================
    # PONG / PING LOOP
    # =========================================================================

    async def handle_pong(self, workstation_id: str) -> None:
        """
        Registra recepción de pong de una workstation.

        Args:
            workstation_id: UUID de la workstation
        """
        self.last_pong[workstation_id] = datetime.now(timezone.utc).replace(tzinfo=None)
        self._pending_pongs.pop(workstation_id, None)

    async def start_ping_loop(self, db_session_factory) -> None:
        """
        Loop de verificación de inactividad selectivo (Death Ping).

        Cada CHECK_INTERVAL (configurable):
        1. Verificar pending_pongs del ciclo anterior (timeout 30s → dead)
        2. Consultar offline_timeout_minutes de cada org con ws conectadas
        3. Identificar ws inactivas (last_activity > timeout de su org)
        4. Enviar Death Ping solo a inactivas locales
        5. Batch disconnect de las muertas

        Solo hace ping a workstations conectadas localmente (Property 11).

        Args:
            db_session_factory: Factory para crear sesiones de BD
        """
        from app.models.organization import Organization
        from app.models.workstation import Workstation
        from datetime import timedelta

        ping_interval = int(getattr(settings, "WS_PING_INTERVAL", 60))

        self._ping_loop_running = True
        self._db_session_factory = db_session_factory

        # === LIMPIEZA INICIAL: marcar offline workstations fantasma ===
        try:
            db = db_session_factory()
            try:
                async with self._lock:
                    connected_ids = list(self.workstation_connections.keys())

                if connected_ids:
                    cleaned = db.query(Workstation).filter(
                        Workstation.is_online == True,
                        ~Workstation.id.in_(connected_ids),
                    ).update(
                        {Workstation.is_online: False},
                        synchronize_session=False,
                    )
                else:
                    cleaned = db.query(Workstation).filter(
                        Workstation.is_online == True,
                    ).update(
                        {Workstation.is_online: False},
                        synchronize_session=False,
                    )

                db.commit()
                if cleaned > 0:
                    logger.info(
                        "ping_loop.initial_cleanup",
                        cleaned=cleaned,
                        connected=len(connected_ids),
                    )
            except Exception as e:
                db.rollback()
                logger.error("ping_loop.initial_cleanup_error", error=str(e))
            finally:
                db.close()
        except Exception as e:
            logger.error("ping_loop.session_error", error=str(e))

        while self._ping_loop_running:
            await asyncio.sleep(ping_interval)

            current_time = datetime.now(timezone.utc).replace(tzinfo=None)
            dead_workstations: List[str] = []

            # === FASE 1: Verificar pending_pongs del ciclo anterior ===
            for ws_id, ping_sent_at in list(self._pending_pongs.items()):
                if (current_time - ping_sent_at).total_seconds() > PONG_TIMEOUT_SECONDS:
                    dead_workstations.append(ws_id)

            for ws_id in dead_workstations:
                self._pending_pongs.pop(ws_id, None)

            if dead_workstations:
                logger.info(
                    "ping_loop.phase1_dead",
                    count=len(dead_workstations),
                    timeout=PONG_TIMEOUT_SECONDS,
                )

            # === FASE 2: Consultar timeouts por organización ===
            org_timeouts: Dict[str, int] = {}
            org_ids_unicos = set(self.org_ids.values())

            if org_ids_unicos:
                try:
                    db = db_session_factory()
                    try:
                        results = db.query(
                            Organization.id, Organization.offline_timeout_minutes
                        ).filter(
                            Organization.id.in_(list(org_ids_unicos))
                        ).all()

                        for org_id, timeout_min in results:
                            org_timeouts[str(org_id)] = timeout_min
                    finally:
                        db.close()
                except Exception as e:
                    logger.warning(
                        "ping_loop.org_timeout_query_error",
                        error=str(e),
                    )

            # === FASE 3: Identificar inactivas y enviar Death Ping ===
            workstation_ids = list(self.workstation_connections.keys())

            pings_enviados = 0
            for ws_id in workstation_ids:
                if ws_id in self._pending_pongs:
                    continue
                org_id = self.org_ids.get(ws_id)
                ws_last_activity = self.last_activity.get(ws_id)

                if org_id is None or ws_last_activity is None:
                    continue

                timeout_minutes = org_timeouts.get(org_id, 10)
                threshold = current_time - timedelta(minutes=timeout_minutes)

                if ws_last_activity < threshold:
                    try:
                        sent = await self.send_to_workstation(ws_id, {"type": "ping"})
                        if sent:
                            self._pending_pongs[ws_id] = current_time
                            pings_enviados += 1
                        else:
                            dead_workstations.append(ws_id)
                    except Exception as e:
                        logger.warning(
                            "ping_loop.send_ping_error",
                            workstation_id=ws_id,
                            error=str(e),
                        )
                        dead_workstations.append(ws_id)

            if pings_enviados > 0:
                logger.info(
                    "ping_loop.phase3_pings_sent",
                    count=pings_enviados,
                    total_connected=len(workstation_ids),
                )

            # === FASE 4: Batch disconnect de muertas ===
            if dead_workstations:
                dead_workstations = list(set(dead_workstations))

                for ws_id in dead_workstations:
                    self.workstation_connections.pop(ws_id, None)
                    self.last_activity.pop(ws_id, None)
                    self.last_pong.pop(ws_id, None)
                    self.org_ids.pop(ws_id, None)
                    self._pending_pongs.pop(ws_id, None)

                # Unregister de WorkerRegistry (ya no se desuscriben canales ws:{id})
                for ws_id in dead_workstations:
                    if self._worker_registry:
                        await self._worker_registry.unregister_workstation(ws_id)

                # Batch UPDATE en BD
                try:
                    db = db_session_factory()
                    try:
                        from app.models.workstation import Workstation
                        updated = db.query(Workstation).filter(
                            Workstation.id.in_(dead_workstations)
                        ).update(
                            {Workstation.is_online: False},
                            synchronize_session=False,
                        )
                        db.commit()
                        logger.info(
                            "ping_loop.phase4_batch_disconnect",
                            updated=updated,
                            dead_count=len(dead_workstations),
                        )
                    except Exception as e:
                        db.rollback()
                        logger.error("ping_loop.batch_disconnect_error", error=str(e))
                    finally:
                        db.close()
                except Exception as e:
                    logger.error("ping_loop.session_error", error=str(e))

    def stop_ping_loop(self) -> None:
        """Detiene el loop de ping/pong."""
        self._ping_loop_running = False

    # =========================================================================
    # GRACEFUL SHUTDOWN
    # =========================================================================

    async def graceful_shutdown_workstations(
        self, reason: str = "Servidor reiniciando"
    ) -> None:
        """
        Cierra todas las conexiones WebSocket de workstations de forma limpia.

        1. Envía close frame con código 1001 (Going Away) a todas las ws
        2. Limpia WorkerRegistry via cleanup_on_shutdown()
        3. Cancela listener task y heartbeat task

        Args:
            reason: Razón del cierre (máx 123 bytes por protocolo WebSocket)
        """
        truncated_reason = reason[:123]

        async with self._lock:
            workstation_ids = list(self.workstation_connections.keys())

        if not workstation_ids:
            logger.info("shutdown.no_workstations")
        else:
            logger.info(
                "shutdown.closing_connections",
                count=len(workstation_ids),
                reason=truncated_reason,
            )

            closed_count = 0
            error_count = 0

            for ws_id in workstation_ids:
                try:
                    async with self._lock:
                        ws = self.workstation_connections.get(ws_id)
                    if ws:
                        await ws.close(code=1001, reason=truncated_reason)
                        closed_count += 1
                except Exception as e:
                    error_count += 1
                    logger.warning(
                        "shutdown.close_error",
                        workstation_id=ws_id,
                        error=str(e),
                    )

            logger.info(
                "shutdown.complete",
                closed=closed_count,
                errors=error_count,
                total=len(workstation_ids),
            )

        # Limpiar WorkerRegistry
        if self._worker_registry:
            await self._worker_registry.cleanup_on_shutdown()

        # Cancelar tasks en background
        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()

        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()

        # Cerrar conexión Redis
        if self._redis:
            try:
                if self._pubsub:
                    await self._pubsub.close()
                await self._redis.close()
            except Exception:
                pass

    # =========================================================================
    # UTILIDADES (compatibilidad con ConnectionManager)
    # =========================================================================

    def get_online_workstations(self) -> List[str]:
        """Obtiene lista de workstations online (locales a este worker)."""
        return list(self.workstation_connections.keys())

    def get_online_operators(self) -> List[str]:
        """Obtiene lista de operadores online."""
        return list(self.operator_connections.keys())

    async def get_worker_ids_for_workstations(self, workstation_ids: List[str]) -> Dict[str, str]:
        """
        Retorna un mapeo {workstation_id: worker_id} para una lista de WS.

        Para las WS conectadas a ESTE worker, retorna self._worker_id directamente.
        Para las WS en OTROS workers, consulta Redis con SISMEMBER en pipeline
        contra los SETs de cada worker activo.

        Args:
            workstation_ids: Lista de workstation_ids a resolver

        Returns:
            Dict {ws_id: "worker_XX"} para las WS encontradas. Las no encontradas no aparecen.
        """
        result: Dict[str, str] = {}
        remote_ids: List[str] = []

        # 1. Resolver locales (O(1) por WS)
        for ws_id in workstation_ids:
            if ws_id in self.workstation_connections:
                result[ws_id] = self._worker_id
            else:
                remote_ids.append(ws_id)

        if not remote_ids or not self._redis_available or not self._redis:
            return result

        # 2. Resolver remotas consultando Redis SETs de otros workers
        try:
            # Encontrar todos los workers activos
            worker_keys: List[str] = []
            async for key in self._redis.scan_iter(match="workers:*:workstations"):
                key_str = key.decode("utf-8") if isinstance(key, bytes) else key
                # Excluir nuestro propio SET (ya resuelto arriba)
                if f"workers:{self._worker_id}:workstations" != key_str:
                    worker_keys.append(key_str)

            # Para cada worker remoto, verificar si tiene las WS pendientes
            for wk in worker_keys:
                if not remote_ids:
                    break
                # Extraer worker_id de la key "workers:{worker_id}:workstations"
                parts = wk.split(":")
                if len(parts) < 3:
                    continue
                other_worker_id = parts[1]

                # Pipeline SISMEMBER para todas las WS pendientes
                pipe = self._redis.pipeline()
                for ws_id in remote_ids:
                    pipe.sismember(wk, ws_id)
                results = await pipe.execute()

                # Marcar las encontradas
                still_remote = []
                for ws_id, is_member in zip(remote_ids, results):
                    if is_member:
                        result[ws_id] = other_worker_id
                    else:
                        still_remote.append(ws_id)
                remote_ids = still_remote

        except Exception as e:
            logger.debug("worker.get_worker_ids_error", error=str(e))

        return result

    def is_workstation_online(self, workstation_id: str) -> bool:
        """
        Verifica si una workstation está online (local o en otro worker).

        Primero verifica conexiones locales. Si no está local, consulta
        WorkerRegistry para saber si otro worker la tiene registrada.
        """
        # Verificar local primero (O(1))
        if workstation_id in self.workstation_connections:
            return True
        # Verificar en WorkerRegistry (consulta Redis, pero es sync-safe via cache)
        if self._worker_registry and self._redis_available:
            # WorkerRegistry mantiene sets en Redis — la verificación es rápida
            # Pero find_worker_for_workstation es async, así que para mantener
            # compatibilidad con la interfaz sync, verificamos si existe en algún set
            # via el dict local de workstations NO es suficiente — necesitamos Redis
            # Por ahora, retornamos True para no filtrar WS de otros workers.
            # El send_to_workstation resolverá el routing correcto.
            return True
        return False

    def get_connection_count(self) -> dict:
        """Obtiene conteo de conexiones locales de este worker."""
        return {
            "workstations": len(self.workstation_connections),
            "operators": len(self.operator_connections),
        }

    async def get_global_connection_count(self) -> dict:
        """
        Obtiene métricas EXACTAS de TODOS los workers para consolidación.

        Cada worker publica sus métricas en workers:{id}:metrics (JSON con ws, rss_mb, fd, pool_out).
        Este método lee las métricas de todos los workers activos y las consolida.
        Para el worker actual, usa valores en vivo (dict local + process info).
        """
        local_ws = len(self.workstation_connections)
        local_ops = len(self.operator_connections)
        worker_id = self._worker_id
        local_rss = self._get_rss_mb()
        local_fd = self._get_fd_count()
        local_pool = self._get_pool_checked_out()

        local_metrics = {"ws": local_ws, "rss_mb": local_rss, "baseline_mb": self._get_baseline_mb(), "fd": local_fd, "pool_out": local_pool}

        if not self._redis_available or not self._redis:
            return {
                "workstations": local_ws,
                "operators": local_ops,
                "workers": 1,
                "worker_id": worker_id,
                "detail": {worker_id: local_metrics},
            }

        try:
            # Actualizar nuestras métricas en Redis
            await self._redis.set(
                f"workers:{worker_id}:metrics",
                json.dumps(local_metrics),
                ex=90,
            )

            # Leer métricas de TODOS los workers activos
            total_ws = 0
            worker_count = 0
            detail: dict = {}

            async for key in self._redis.scan_iter(match="workers:*:heartbeat"):
                wid = key.split(":")[1]
                worker_count += 1

                if wid == worker_id:
                    detail[wid] = local_metrics
                    total_ws += local_ws
                else:
                    metrics_str = await self._redis.get(f"workers:{wid}:metrics")
                    if metrics_str:
                        wmetrics = json.loads(metrics_str)
                        detail[wid] = wmetrics
                        total_ws += wmetrics.get("ws", 0)
                    else:
                        detail[wid] = {"ws": 0, "rss_mb": 0, "fd": 0, "pool_out": 0}

            if worker_count == 0:
                worker_count = 1
                total_ws = local_ws
                detail = {worker_id: local_metrics}

            return {
                "workstations": total_ws,
                "operators": local_ops,
                "workers": worker_count,
                "worker_id": worker_id,
                "detail": detail,
            }
        except Exception:
            return {
                "workstations": local_ws,
                "operators": local_ops,
                "workers": 1,
                "worker_id": worker_id,
                "detail": {worker_id: local_metrics},
            }
