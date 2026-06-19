"""
Gestor de conexiones WebSocket con coordinación via Redis pub/sub.

Este módulo implementa el RedisConnectionManager que extiende la funcionalidad
del ConnectionManager original con comunicación inter-worker mediante Redis:
- Pub/Sub para comandos cross-worker y broadcasts organizacionales
- Suscripción por workstation (ws:{id}) y organización (org:{id})
- Fallback graceful cuando Redis no está disponible
- Exponential backoff para reconexión Redis (1s→2s→4s→8s→16s→30s max)
- Command waiters con resolución via pub/sub (cmd_response:{id})

Canales Redis:
- ws:{workstation_id} → Comandos dirigidos a una workstation específica
- org:{organization_id} → Broadcasts organizacionales
- global:broadcast → Broadcasts globales a todos los workers
- cmd_response:{command_id} → Respuestas de comandos cross-worker

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

        # Death pings pendientes de respuesta: {workstation_id: datetime_enviado}
        self._pending_pongs: Dict[str, datetime] = {}

        # Respuestas pendientes de comandos: {command_id: (asyncio.Event, list)}
        self._pending_command_responses: Dict[str, Tuple[asyncio.Event, List[Optional[dict]]]] = {}

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
        Conectar a Redis, suscribir canal global:broadcast, iniciar listener task.

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

            # Crear pub/sub y suscribir canal global
            self._pubsub = self._redis.pubsub()
            await self._pubsub.subscribe("global:broadcast")

            # Iniciar listener task para procesar mensajes pub/sub
            self._listener_task = asyncio.create_task(self._redis_listener())

            # Iniciar heartbeat periódico para WorkerRegistry
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            logger.info(
                "redis.initialized",
                redis_url=self._redis_url,
                channel="global:broadcast",
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
    ) -> None:
        """
        Registra conexión de un Tray Client.

        1. Registra localmente (dict workstation_id → WebSocket)
        2. Suscribe al canal Redis ws:{workstation_id}
        3. Registra en WorkerRegistry

        Args:
            workstation_id: UUID de la workstation
            websocket: Conexión WebSocket (ya aceptada por el endpoint)
            db: Sesión de base de datos
            organization_id: UUID de la organización
        """
        # Registrar localmente (sin lock — asyncio single-threaded, safe entre awaits)
        self.workstation_connections[workstation_id] = websocket
        self.last_pong[workstation_id] = datetime.now(timezone.utc).replace(tzinfo=None)
        self.last_activity[workstation_id] = datetime.now(timezone.utc).replace(tzinfo=None)
        self.org_ids[workstation_id] = organization_id

        # Actualizar estado en base de datos
        from app.services.workstation import WorkstationService
        workstation_service = WorkstationService()
        workstation_service.update_workstation_status(
            db=db,
            workstation_id=workstation_id,
            is_online=True,
        )

        # Suscribir canal Redis para esta workstation (fire-and-forget para no bloquear)
        if self._redis_available and self._pubsub:
            asyncio.ensure_future(self._subscribe_workstation_channel(workstation_id))

        # Registrar en WorkerRegistry (fire-and-forget)
        if self._worker_registry:
            asyncio.ensure_future(self._worker_registry.register_workstation(workstation_id))

    async def _subscribe_workstation_channel(self, workstation_id: str) -> None:
        """Suscribe al canal Redis ws:{workstation_id} de forma no-bloqueante."""
        try:
            await self._pubsub.subscribe(f"ws:{workstation_id}")
        except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as e:
            logger.warning(
                "redis.subscribe_failed",
                channel=f"ws:{workstation_id}",
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
        Desconecta un Tray Client y limpia recursos.

        1. Elimina del estado local
        2. Desuscribe del canal Redis ws:{workstation_id}
        3. Elimina del WorkerRegistry

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

        if should_mark_offline and workstation_id in self.last_pong:
            del self.last_pong[workstation_id]

        if should_mark_offline:
            self.last_activity.pop(workstation_id, None)
            self.org_ids.pop(workstation_id, None)
            self._pending_pongs.pop(workstation_id, None)

        if not should_mark_offline:
            return

        # Desuscribir canal Redis de esta workstation
        if self._redis_available and self._pubsub:
            try:
                await self._pubsub.unsubscribe(f"ws:{workstation_id}")
                logger.debug(
                    "redis.unsubscribe",
                    channel=f"ws:{workstation_id}",
                    workstation_id=workstation_id,
                )
            except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as e:
                logger.warning(
                    "redis.unsubscribe_failed",
                    channel=f"ws:{workstation_id}",
                    error=str(e),
                )

        # Eliminar del WorkerRegistry
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
        Envía mensaje a una workstation.

        Si la workstation está conectada localmente, envía directamente.
        Si no está aquí y Redis está disponible, publica en ws:{workstation_id}.

        Args:
            workstation_id: UUID de la workstation
            message: Mensaje a enviar (dict serializable a JSON)

        Returns:
            True si se envió localmente, False si se publicó en Redis o no se pudo enviar
        """
        # Intentar entrega local primero
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

        # No está local — publicar en Redis para que otro worker lo entregue
        if self._redis_available and self._redis:
            try:
                payload = json.dumps(message, default=str)
                await self._redis.publish(f"ws:{workstation_id}", payload)
                logger.debug(
                    "delivery.remote_publish",
                    workstation_id=workstation_id,
                    message_type=message.get("type", "unknown"),
                    target_channel=f"ws:{workstation_id}",
                )
                return False
            except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as e:
                logger.warning(
                    "redis.publish_failed",
                    channel=f"ws:{workstation_id}",
                    error=str(e),
                )

        # Workstation no conectada localmente y Redis no disponible
        logger.debug(
            "delivery.not_found",
            workstation_id=workstation_id,
            message_type=message.get("type", "unknown"),
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
        db: Session,
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
        async with self._lock:
            local_ws_ids = [
                ws_id for ws_id, org_id in self.org_ids.items()
                if org_id == organization_id
            ]

        for ws_id in local_ws_ids:
            async with self._lock:
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
        - ws:{workstation_id} → entrega local al WebSocket
        - org:{organization_id} → entrega a todas las locales de esa org
        - global:broadcast → entrega a todas las locales
        - cmd_response:{command_id} → resuelve command waiter
        """
        if not self._pubsub:
            return

        logger.info("redis.listener_started")

        # Guardar referencia al event loop
        self._event_loop = asyncio.get_running_loop()

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

                    # Despachar según tipo de canal
                    if channel.startswith("ws:"):
                        workstation_id = channel[3:]
                        await self._deliver_to_local_workstation(workstation_id, payload)
                    elif channel.startswith("org:"):
                        organization_id = channel[4:]
                        await self._deliver_to_local_org_workstations(organization_id, payload)
                    elif channel == "global:broadcast":
                        await self._deliver_global_broadcast(payload)
                    elif channel.startswith("cmd_response:"):
                        command_id = channel[13:]
                        self.resolve_command_response(command_id, payload)

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
        async with self._lock:
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
        Entrega un mensaje a todas las workstations locales de una organización.

        Solo entrega a workstations cuyo org_id coincide con organization_id (Req 1.4).
        Valida explícitamente tenant isolation por cada workstation (Req 5.3, 5.4).

        Args:
            organization_id: UUID de la organización
            payload: Mensaje a entregar
        """
        async with self._lock:
            local_ws_ids = [
                ws_id for ws_id, org_id in self.org_ids.items()
                if org_id == organization_id
            ]

        delivered = 0
        skipped = 0
        for ws_id in local_ws_ids:
            # Verificación explícita de tenant isolation por workstation
            if not self._validate_tenant(ws_id, organization_id):
                skipped += 1
                continue

            async with self._lock:
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
        re-suscribe todos los canales activos y reinicia el listener task.
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

                # Re-crear pub/sub y re-suscribir canales activos
                self._pubsub = self._redis.pubsub()
                await self._pubsub.subscribe("global:broadcast")

                # Re-suscribir canales de workstations conectadas localmente
                async with self._lock:
                    ws_ids = list(self.workstation_connections.keys())

                for ws_id in ws_ids:
                    try:
                        await self._pubsub.subscribe(f"ws:{ws_id}")
                    except Exception:
                        pass

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
                    resubscribed_channels=len(ws_ids) + 1,
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
        Registra un waiter para esperar la respuesta de un comando específico.

        Suscribe al canal cmd_response:{command_id} en Redis para recibir
        respuestas de otros workers.

        Args:
            command_id: ID del comando cuya respuesta se espera

        Returns:
            asyncio.Event que se señalará cuando llegue la respuesta
        """
        event = asyncio.Event()
        self._pending_command_responses[command_id] = (event, [None])

        # Suscribir canal de respuesta en Redis (fire-and-forget)
        if self._redis_available and self._pubsub:
            asyncio.create_task(self._subscribe_command_response(command_id))

        return event

    async def _subscribe_command_response(self, command_id: str) -> None:
        """Suscribe al canal cmd_response:{command_id} para respuestas cross-worker."""
        try:
            if self._pubsub:
                await self._pubsub.subscribe(f"cmd_response:{command_id}")
        except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as e:
            logger.warning(
                "redis.subscribe_cmd_response_failed",
                command_id=command_id,
                error=str(e),
            )

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
            event, container = self._pending_command_responses[command_id]
            container[0] = response
            event.set()
            return True
        return False

    async def wait_for_command_response(
        self, command_id: str, timeout: float = 30.0
    ) -> Optional[dict]:
        """
        Espera la respuesta de un comando con timeout.

        Cuando la workstation responde en otro worker, la respuesta llega
        via pub/sub en cmd_response:{command_id} y resuelve el event.

        Args:
            command_id: ID del comando
            timeout: Tiempo máximo de espera en segundos

        Returns:
            Respuesta del comando o None si timeout
        """
        if command_id not in self._pending_command_responses:
            return None

        event, container = self._pending_command_responses[command_id]

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return container[0]
        except asyncio.TimeoutError:
            return None
        finally:
            # Limpiar waiter y desuscribir canal
            self._pending_command_responses.pop(command_id, None)
            if self._redis_available and self._pubsub:
                try:
                    await self._pubsub.unsubscribe(f"cmd_response:{command_id}")
                except Exception:
                    pass

    async def publish_command_response(
        self, command_id: str, response: dict
    ) -> None:
        """
        Publica la respuesta de un comando en Redis para que el worker
        originador la reciba.

        Args:
            command_id: ID del comando
            response: Respuesta del comando
        """
        if self._redis_available and self._redis:
            try:
                payload = json.dumps(response, default=str)
                await self._redis.publish(f"cmd_response:{command_id}", payload)
                logger.debug(
                    "redis.publish_cmd_response",
                    command_id=command_id,
                )
            except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as e:
                logger.warning(
                    "redis.publish_cmd_response_failed",
                    command_id=command_id,
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
        async with self._lock:
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
            async with self._lock:
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
            async with self._lock:
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
            async with self._lock:
                workstation_ids = list(self.workstation_connections.keys())

            pings_enviados = 0
            for ws_id in workstation_ids:
                async with self._lock:
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
                            async with self._lock:
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

                async with self._lock:
                    for ws_id in dead_workstations:
                        self.workstation_connections.pop(ws_id, None)
                        self.last_activity.pop(ws_id, None)
                        self.last_pong.pop(ws_id, None)
                        self.org_ids.pop(ws_id, None)
                        self._pending_pongs.pop(ws_id, None)

                # Desuscribir canales Redis y unregister de WorkerRegistry
                for ws_id in dead_workstations:
                    if self._redis_available and self._pubsub:
                        try:
                            await self._pubsub.unsubscribe(f"ws:{ws_id}")
                        except Exception:
                            pass
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
