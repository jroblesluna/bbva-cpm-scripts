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

        # Contador de workstations por organización (lazy subscribe/unsubscribe)
        self._org_ws_count: Dict[str, int] = {}

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
            self._listener_task = asyncio.create_task(self._redis_listener())

            # Iniciar heartbeat periódico para WorkerRegistry
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

        Espera 1 segundo, luego hace SADD batch de todas las workstations
        pendientes + SUBSCRIBE de organizaciones nuevas. Esto evita crear
        un asyncio.Task individual por cada connect_workstation durante
        ramp-up rápido (que saturaba el event loop con 100+ tasks).
        """
        await asyncio.sleep(1)

        # Copiar y limpiar colas
        ws_ids = self._pending_registrations.copy()
        org_ids = self._pending_org_subscribes.copy()
        self._pending_registrations.clear()
        self._pending_org_subscribes.clear()

        if not ws_ids and not org_ids:
            return

        try:
            # Batch SADD de todas las workstations al WorkerRegistry
            if self._worker_registry and ws_ids:
                for ws_id in ws_ids:
                    await self._worker_registry.register_workstation(ws_id)

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
                logger.debug(
                    "delivery.local",
                    workstation_id=workstation_id,
                    message_type=message.get("type", "unknown"),
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

                # 2b. Worker encontrado → publicar en worker:{target_worker_id}
                # Enriquecer payload con target_workstation_id y organization_id
                org_id = message.get("organization_id") or self.org_ids.get(workstation_id)
                enriched_message = {
                    **message,
                    "target_workstation_id": workstation_id,
                }
                if org_id:
                    enriched_message["organization_id"] = org_id

                payload = json.dumps(enriched_message, default=str)
                target_channel = f"worker:{target_worker_id}"
                await self._redis.publish(target_channel, payload)
                logger.debug(
                    "delivery.remote_publish",
                    workstation_id=workstation_id,
                    message_type=message.get("type", "unknown"),
                    target_channel=target_channel,
                    target_worker_id=target_worker_id,
                )
                return False

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
        Envía mensaje a todas las workstations de una organización.

        1. Envía a todas las workstations locales de la organización
        2. Publica en org:{organization_id} para que otros workers entreguen a las suyas

        Args:
            organization_id: UUID de la organización
            message: Mensaje a enviar
            db: Sesión de base de datos
        """
        # Entregar a workstations locales de esta organización
        local_count = 0
        local_ws_ids = [
            ws_id for ws_id, org_id in self.org_ids.items()
            if org_id == organization_id
        ]

        for ws_id in local_ws_ids:
            ws = self.workstation_connections.get(ws_id)
            if ws:
                try:
                    await ws.send_json(message)
                    local_count += 1
                except Exception:
                    pass  # Conexión muerta, será limpiada por Death Ping

        # Publicar en Redis para que otros workers entreguen a sus locales
        if self._redis_available and self._redis:
            try:
                payload = json.dumps(message, default=str)
                await self._redis.publish(f"org:{organization_id}", payload)
                logger.debug(
                    "delivery.org_broadcast",
                    org_id=organization_id,
                    local_count=local_count,
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
                local_count=local_count,
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
                # Procesar TODOS los mensajes disponibles en batch antes de ceder
                # Esto evita que el listener solo procese 1 mensaje por iteración
                messages_processed = 0
                while True:
                    message = await self._pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=0.001,  # Non-blocking: retorna inmediatamente si no hay mensajes
                    )
                    if message is None:
                        break  # No hay más mensajes, salir del batch

                    if message["type"] != "message":
                        continue

                    channel = message["channel"]
                    data = message["data"]

                    try:
                        payload = json.loads(data) if isinstance(data, str) else data
                    except (json.JSONDecodeError, TypeError):
                        continue

                    # Despachar según tipo de canal (esquema consolidado)
                    # Solo se procesan: worker:{worker_id}, org:{org_id}, global:broadcast
                    # Canales ws:{id} y cmd_response:{id} han sido eliminados del esquema
                    if channel == worker_channel:
                        # Canal worker consolidado: cmd_response o mensaje dirigido
                        msg_type = payload.get("type") if isinstance(payload, dict) else None
                        if msg_type == "cmd_response":
                            command_id = payload.get("command_id")
                            if command_id:
                                self.resolve_command_response(command_id, payload)
                        else:
                            target_ws_id = payload.get("target_workstation_id") if isinstance(payload, dict) else None
                            if target_ws_id:
                                await self._deliver_to_local_workstation(target_ws_id, payload)
                            else:
                                logger.debug(
                                    "redis.listener_no_target_ws",
                                    channel=channel,
                                    msg_type=msg_type,
                                )
                    elif channel.startswith("org:"):
                        organization_id = channel[4:]
                        await self._deliver_to_local_org_workstations(organization_id, payload)
                    elif channel == "global:broadcast":
                        await self._deliver_global_broadcast(payload)

                    messages_processed += 1
                    if messages_processed >= 50:
                        break  # Procesar máx 50 por batch, luego ceder

                # Ceder el event loop generosamente — 500ms cuando no hay mensajes
                # Esto es el fix clave: el listener NO compite con los registros
                await asyncio.sleep(0.5)

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
        """
        interval = settings.WORKER_REGISTRY_TTL // 2
        while True:
            try:
                await asyncio.sleep(interval)
                if self._worker_registry and self._redis_available:
                    await self._worker_registry.heartbeat()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("worker.heartbeat_error", error=str(e))

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
            return True
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
                logger.debug(
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

    def is_workstation_online(self, workstation_id: str) -> bool:
        """Verifica si una workstation está online en este worker."""
        return workstation_id in self.workstation_connections

    def get_connection_count(self) -> dict:
        """Obtiene conteo de conexiones locales."""
        return {
            "workstations": len(self.workstation_connections),
            "operators": len(self.operator_connections),
        }
