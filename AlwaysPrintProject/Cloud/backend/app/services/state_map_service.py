"""
Servicio de mapa de estado en memoria para distribución push-based.

Mantiene un mapa en memoria por worker con el estado de distribución
(config, certificado, MSI) por organización. La resolución de scope
es jerárquica: org < vlan < workstation (más específico gana).

La BD es la fuente de verdad; este mapa es un caché de lectura rápida
que elimina queries a BD en la ruta de distribución.

Uso:
    from app.services.state_map_service import StateMapService

    state_map = StateMapService(redis_url="redis://localhost:6379/0")
    await state_map.initialize(db_session_factory)
    state = await state_map.get_state(org_id)
    ws_state = await state_map.resolve_workstation_state(org_id, vlan_id, ws_id)
"""

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger

# Bucket y región para construir URLs públicas S3
_S3_BUCKET = settings.S3_DOCS_BUCKET
_S3_REGION = settings.AWS_REGION

# Canal Redis dedicado para sincronización inter-worker del state map
_STATE_MAP_CHANNEL = "state_map:update"

# Threshold para regenerar presigned URL de MSI (5 minutos antes de expirar)
_MSI_URL_REFRESH_THRESHOLD_SECONDS = 300

logger = get_logger(__name__)


@dataclass
class VlanConfigState:
    """Estado de configuración específico para una VLAN."""

    config_hash: str
    config_s3_url: str


@dataclass
class WsConfigState:
    """Estado de configuración específico para una workstation."""

    config_hash: str
    config_s3_url: str


@dataclass
class OrgDistributionState:
    """
    Estado completo de distribución de una organización.

    Incluye la config activa a nivel org (default), certificado ECDSA,
    MSI, y overrides por scope (vlan, workstation).
    """

    # Config activa a nivel org (default)
    config_hash: str | None = None
    config_s3_url: str | None = None

    # Certificado ECDSA
    cert_version: int = 0
    cert_url: str | None = None

    # MSI
    msi_version: str | None = None
    msi_url: str | None = None
    msi_url_expires_at: float = 0.0  # epoch timestamp de expiración presigned URL

    # Config overrides por scope
    vlan_configs: dict[str, VlanConfigState] = field(default_factory=dict)
    ws_configs: dict[str, WsConfigState] = field(default_factory=dict)


@dataclass
class StateMapUpdate:
    """
    Payload de actualización publicado/recibido vía Redis pub/sub.

    Permite a otros workers sincronizar su mapa local cuando un cambio
    ocurre en un worker diferente.
    """

    origin_worker_id: str
    org_id: str
    update_type: str  # "config" | "cert" | "msi"
    data: dict  # Campos actualizados según update_type


class StateMapService:
    """
    Servicio de mapa de estado en memoria por worker.

    Mantiene un dict org_id → OrgDistributionState que se consulta
    en O(1) para distribución push y enriquecimiento de registro.
    La sincronización inter-worker se hace vía Redis pub/sub (Task 1.4).
    """

    def __init__(self, redis_url: str | None = None):
        """
        Inicializa el servicio con un mapa vacío.

        Args:
            redis_url: URL de Redis para sincronización inter-worker.
                       Si es None, opera en modo single-worker (sin sync).
        """
        self._state: dict[str, OrgDistributionState] = {}
        self._redis_url = redis_url
        self._db_session_factory = None
        # Worker ID único para identificar mensajes propios en pub/sub
        self._worker_id: str = f"worker_{os.getpid()}_{uuid.uuid4().hex[:8]}"
        # Campos Redis para sincronización inter-worker
        self._redis: aioredis.Redis | None = None
        self._pubsub: aioredis.client.PubSub | None = None
        self._listener_task: asyncio.Task | None = None
        self._redis_available: bool = False
        # Servicio S3 para regenerar presigned URLs de MSI (lazy init)
        self._s3_update_service = None

    async def initialize(self, db_session_factory) -> None:
        """
        Carga estado inicial desde BD para todas las orgs activas.
        Si redis_url está configurado, conecta a Redis y suscribe al canal
        state_map:update para sincronización inter-worker.

        Ejecuta una query JOIN entre organizations y action_configs para
        poblar el mapa de estado con datos actuales. Construye URLs S3
        a partir de las claves almacenadas en BD.

        Args:
            db_session_factory: Callable que retorna una sesión de SQLAlchemy.
        """
        self._db_session_factory = db_session_factory
        db = db_session_factory()
        try:
            # Query JOIN: orgs activas + sus action_configs activas
            query = text("""
                SELECT
                    o.id AS org_id,
                    o.ecdsa_cert_version AS cert_version,
                    o.ecdsa_cert_s3_key AS cert_s3_key,
                    o.target_version AS msi_version,
                    o.auto_update_enabled,
                    ac.config_hash,
                    ac.storage_path AS config_s3_key,
                    ac.scope,
                    ac.vlan_id,
                    ac.workstation_id
                FROM organizations o
                LEFT JOIN action_configs ac
                    ON ac.organization_id = o.id AND ac.is_active = true
                WHERE o.is_active = true
            """)

            rows = db.execute(query).fetchall()

            # Procesar filas y construir el mapa de estado
            for row in rows:
                org_id = str(row.org_id)
                org_state = self._state.get(org_id)

                if org_state is None:
                    # Primera fila de esta org: crear estado con cert y MSI
                    cert_url = None
                    if row.cert_s3_key:
                        cert_url = self._build_public_url(row.cert_s3_key)

                    # Resolver msi_version: explícita o latest de S3
                    resolved_msi_version = row.msi_version
                    if not resolved_msi_version and row.auto_update_enabled:
                        try:
                            from app.services.s3_update_service import S3UpdateService
                            s3_service = S3UpdateService()
                            metadata = s3_service.get_msi_metadata()
                            if metadata and metadata.get("version"):
                                resolved_msi_version = metadata["version"]
                        except Exception:
                            pass  # Si S3 no está disponible, msi_version queda None

                    org_state = OrgDistributionState(
                        cert_version=row.cert_version or 0,
                        cert_url=cert_url,
                        msi_version=resolved_msi_version,
                    )
                    self._state[org_id] = org_state

                # Procesar action_config (puede ser None por LEFT JOIN)
                if row.config_hash and row.config_s3_key:
                    config_s3_url = self._build_public_url(row.config_s3_key)
                    scope = row.scope

                    if scope == "org":
                        org_state.config_hash = row.config_hash
                        org_state.config_s3_url = config_s3_url
                    elif scope == "vlan" and row.vlan_id:
                        vlan_id = str(row.vlan_id)
                        org_state.vlan_configs[vlan_id] = VlanConfigState(
                            config_hash=row.config_hash,
                            config_s3_url=config_s3_url,
                        )
                    elif scope == "workstation" and row.workstation_id:
                        ws_id = str(row.workstation_id)
                        org_state.ws_configs[ws_id] = WsConfigState(
                            config_hash=row.config_hash,
                            config_s3_url=config_s3_url,
                        )

            logger.info(
                "state_map.inicializado",
                total_orgs=len(self._state),
            )
        finally:
            db.close()

        # Inicializar conexión Redis y suscripción al canal de sincronización
        await self._initialize_redis()

    async def _initialize_redis(self) -> None:
        """
        Conecta a Redis y suscribe al canal state_map:update.

        Si Redis no está disponible al iniciar, el servicio opera
        en modo single-worker (sin sincronización inter-worker).
        Un task de reconexión con exponential backoff se lanza en background.
        """
        if not self._redis_url:
            logger.info(
                "state_map.redis_deshabilitado",
                msg="Sin REDIS_URL, operando en modo single-worker",
            )
            return

        try:
            self._redis = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                retry_on_error=[aioredis.ConnectionError, aioredis.TimeoutError],
            )
            await self._redis.ping()
            self._redis_available = True

            # Crear pub/sub y suscribir al canal de sincronización
            self._pubsub = self._redis.pubsub()
            await self._pubsub.subscribe(_STATE_MAP_CHANNEL)

            # Iniciar listener task en background
            self._listener_task = asyncio.create_task(self._state_map_listener())

            logger.info(
                "state_map.redis_conectado",
                worker_id=self._worker_id,
                canal=_STATE_MAP_CHANNEL,
            )
        except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as e:
            logger.warning(
                "state_map.redis_no_disponible_al_iniciar",
                error=str(e),
                msg="State map cargado desde BD. Sin sync inter-worker hasta que Redis vuelva",
            )
            self._redis_available = False
            # Lanzar reconexión en background
            asyncio.create_task(self._handle_redis_reconnect())

    async def _load_org_state(
        self, db: Session | None = None, org_id: str = ""
    ) -> OrgDistributionState | None:
        """
        Carga estado de una org individual desde BD (fallback en cache miss).

        Ejecuta la misma query que initialize() pero filtrada por org_id.
        Almacena el resultado en self._state para evitar futuras queries.

        Args:
            db: Sesión de SQLAlchemy activa. Si es None, se crea una
                usando self._db_session_factory.
            org_id: UUID de la organización a cargar.

        Returns:
            OrgDistributionState cargado, o None si la org no existe/no está activa.
        """
        close_db = False
        if db is None:
            if self._db_session_factory is None:
                logger.warning(
                    "state_map.load_org_sin_factory",
                    org_id=org_id,
                )
                return None
            db = self._db_session_factory()
            close_db = True

        try:
            query = text("""
                SELECT
                    o.id AS org_id,
                    o.ecdsa_cert_version AS cert_version,
                    o.ecdsa_cert_s3_key AS cert_s3_key,
                    o.target_version AS msi_version,
                    o.auto_update_enabled,
                    ac.config_hash,
                    ac.storage_path AS config_s3_key,
                    ac.scope,
                    ac.vlan_id,
                    ac.workstation_id
                FROM organizations o
                LEFT JOIN action_configs ac
                    ON ac.organization_id = o.id AND ac.is_active = true
                WHERE o.is_active = true AND o.id = :org_id
            """)

            rows = db.execute(query, {"org_id": org_id}).fetchall()

            if not rows:
                logger.debug(
                    "state_map.load_org_no_encontrada",
                    org_id=org_id,
                )
                return None

            # Construir estado a partir de las filas
            org_state = OrgDistributionState()

            for row in rows:
                # Cert y MSI (se toman de la primera fila, son iguales para todas)
                if org_state.cert_version == 0:
                    org_state.cert_version = row.cert_version or 0
                    if row.cert_s3_key:
                        org_state.cert_url = self._build_public_url(row.cert_s3_key)
                    org_state.msi_version = row.msi_version

                # Procesar action_config (puede ser None por LEFT JOIN)
                if row.config_hash and row.config_s3_key:
                    config_s3_url = self._build_public_url(row.config_s3_key)
                    scope = row.scope

                    if scope == "org":
                        org_state.config_hash = row.config_hash
                        org_state.config_s3_url = config_s3_url
                    elif scope == "vlan" and row.vlan_id:
                        vlan_id = str(row.vlan_id)
                        org_state.vlan_configs[vlan_id] = VlanConfigState(
                            config_hash=row.config_hash,
                            config_s3_url=config_s3_url,
                        )
                    elif scope == "workstation" and row.workstation_id:
                        ws_id = str(row.workstation_id)
                        org_state.ws_configs[ws_id] = WsConfigState(
                            config_hash=row.config_hash,
                            config_s3_url=config_s3_url,
                        )

            # Almacenar en el mapa para evitar futuras queries
            self._state[str(org_id)] = org_state

            logger.info(
                "state_map.org_cargada_desde_bd",
                org_id=org_id,
                config_hash=org_state.config_hash,
                cert_version=org_state.cert_version,
                vlans=len(org_state.vlan_configs),
                workstations=len(org_state.ws_configs),
            )

            return org_state
        finally:
            if close_db:
                db.close()

    # =========================================================================
    # REDIS PUB/SUB - SINCRONIZACIÓN INTER-WORKER
    # =========================================================================

    async def _handle_redis_reconnect(self) -> None:
        """
        Reconexión con exponential backoff cuando Redis no está disponible.

        Intenta reconectar con delays crecientes: 1s, 2s, 4s, 8s, 16s, 30s (max).
        Al reconectar exitosamente, resuscribe al canal y relanza el listener.
        """
        delays = [1, 2, 4, 8, 16, 30]
        attempt = 0

        while True:
            delay = delays[min(attempt, len(delays) - 1)]
            await asyncio.sleep(delay)
            attempt += 1

            try:
                if self._redis is None:
                    self._redis = aioredis.from_url(
                        self._redis_url,
                        decode_responses=True,
                        retry_on_error=[aioredis.ConnectionError, aioredis.TimeoutError],
                    )
                await self._redis.ping()
                self._redis_available = True

                # Re-suscribir al canal
                self._pubsub = self._redis.pubsub()
                await self._pubsub.subscribe(_STATE_MAP_CHANNEL)

                # Relanzar listener
                if self._listener_task and not self._listener_task.done():
                    self._listener_task.cancel()
                self._listener_task = asyncio.create_task(self._state_map_listener())

                logger.info(
                    "state_map.redis_reconectado",
                    worker_id=self._worker_id,
                    intentos=attempt,
                )
                return
            except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as e:
                logger.debug(
                    "state_map.redis_reconexion_fallida",
                    intento=attempt,
                    delay_siguiente=delays[min(attempt, len(delays) - 1)],
                    error=str(e),
                )

    async def _state_map_listener(self) -> None:
        """
        Background task que escucha mensajes en el canal state_map:update.

        Usa get_message(timeout=1.0) blocking para no saturar el event loop
        (regla de AGENTS.md: NO polling con timeout=0.001 + sleep).
        """
        if not self._pubsub:
            return

        logger.info(
            "state_map.listener_iniciado",
            worker_id=self._worker_id,
            canal=_STATE_MAP_CHANNEL,
        )

        while True:
            try:
                # Blocking get_message: suspende la coroutine hasta que llega un mensaje
                # o expira el timeout (1s). NO consume CPU innecesariamente.
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if message is None:
                    continue  # Timeout sin mensaje — reintentar

                if message["type"] != "message":
                    continue

                # Procesar mensaje recibido
                await self._on_redis_message(message)

            except asyncio.CancelledError:
                logger.info("state_map.listener_cancelado")
                break
            except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as e:
                logger.warning(
                    "state_map.listener_conexion_perdida",
                    error=str(e),
                )
                self._redis_available = False
                # Lanzar reconexión en background y terminar este listener
                asyncio.create_task(self._handle_redis_reconnect())
                break
            except Exception as e:
                logger.error(
                    "state_map.listener_error_inesperado",
                    error=str(e),
                )
                await asyncio.sleep(1)

    async def _publish_update(
        self, org_id: str, update_type: str, data: dict
    ) -> None:
        """
        Publica un cambio de estado en el canal Redis state_map:update.

        Serializa un StateMapUpdate a JSON y lo publica para que otros
        workers sincronicen su mapa local. Si Redis no está disponible,
        loguea warning y continúa (el state map local queda correcto).

        Args:
            org_id: UUID de la organización afectada.
            update_type: Tipo de actualización ("config", "cert", "msi").
            data: Dict con los campos actualizados según update_type.
        """
        if not self._redis or not self._redis_available:
            logger.warning(
                "state_map.publish_sin_redis",
                org_id=org_id,
                update_type=update_type,
                msg="Redis no disponible, actualización no propagada a otros workers",
            )
            return

        payload = {
            "origin_worker_id": self._worker_id,
            "org_id": org_id,
            "update_type": update_type,
            "data": data,
        }

        try:
            await self._redis.publish(_STATE_MAP_CHANNEL, json.dumps(payload))
            logger.debug(
                "state_map.update_publicado",
                org_id=org_id,
                update_type=update_type,
                worker_id=self._worker_id,
            )
        except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as e:
            logger.warning(
                "state_map.publish_fallido",
                org_id=org_id,
                update_type=update_type,
                error=str(e),
                msg="No se pudo publicar actualización, continuando con state map local",
            )

    async def _on_redis_message(self, message: dict) -> None:
        """
        Handler para mensajes recibidos en el canal state_map:update.

        Deserializa el JSON, verifica que no sea un mensaje propio
        (origin_worker_id), y actualiza el state map local según el
        update_type recibido.

        Args:
            message: Mensaje raw de Redis pub/sub con campo 'data' (str JSON).
        """
        try:
            data = message.get("data")
            if not data or not isinstance(data, str):
                return

            payload = json.loads(data)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(
                "state_map.mensaje_invalido",
                error=str(e),
            )
            return

        # Ignorar mensajes propios (evita loop)
        origin_worker_id = payload.get("origin_worker_id")
        if origin_worker_id == self._worker_id:
            return

        org_id = payload.get("org_id")
        update_type = payload.get("update_type")
        update_data = payload.get("data", {})

        if not org_id or not update_type:
            logger.warning(
                "state_map.mensaje_incompleto",
                payload_keys=list(payload.keys()),
            )
            return

        # Obtener o crear estado de la org
        org_state = self._get_or_create_org_state(org_id)

        # Detectar inconsistencias ANTES de aplicar el cambio (Task 1.5)
        self._detect_inconsistency(
            org_id, update_type, update_data, org_state, origin_worker_id
        )

        # Aplicar actualización según tipo (modifica self._state directamente)
        if update_type == "config":
            scope = update_data.get("scope", "org")
            scope_id = update_data.get("scope_id")
            config_hash = update_data.get("config_hash")
            config_s3_url = update_data.get("config_s3_url")

            if scope == "org":
                org_state.config_hash = config_hash
                org_state.config_s3_url = config_s3_url
            elif scope == "vlan" and scope_id:
                org_state.vlan_configs[scope_id] = VlanConfigState(
                    config_hash=config_hash,
                    config_s3_url=config_s3_url,
                )
            elif scope == "workstation" and scope_id:
                org_state.ws_configs[scope_id] = WsConfigState(
                    config_hash=config_hash,
                    config_s3_url=config_s3_url,
                )

        elif update_type == "cert":
            org_state.cert_version = update_data.get("cert_version", 0)
            org_state.cert_url = update_data.get("cert_url")

        elif update_type == "msi":
            org_state.msi_version = update_data.get("msi_version")
            org_state.msi_url = update_data.get("msi_url")
            org_state.msi_url_expires_at = update_data.get("msi_url_expires_at", 0.0)

        else:
            logger.warning(
                "state_map.update_type_desconocido",
                update_type=update_type,
                org_id=org_id,
            )
            return

        logger.info(
            "state_map.sync_recibido",
            org_id=org_id,
            update_type=update_type,
            origin_worker=origin_worker_id,
            worker_id=self._worker_id,
        )

    @staticmethod
    def _build_public_url(s3_key: str) -> str:
        """
        Construye la URL pública de un objeto en S3.

        Sigue el patrón existente del proyecto:
        https://{bucket}.s3.{region}.amazonaws.com/{s3_key}

        Args:
            s3_key: Clave del objeto en S3 (ej: "configs/org-id/hash.signed").

        Returns:
            URL pública completa.
        """
        return f"https://{_S3_BUCKET}.s3.{_S3_REGION}.amazonaws.com/{s3_key}"

    async def get_state(self, org_id: str) -> OrgDistributionState | None:
        """
        Retorna el estado de distribución de una org (O(1) lookup).

        Args:
            org_id: UUID de la organización a consultar.

        Returns:
            OrgDistributionState si la org existe en el mapa, None si no.
        """
        return self._state.get(org_id)

    def _get_or_create_org_state(self, org_id: str) -> OrgDistributionState:
        """
        Obtiene el estado de una org, creándolo si no existe.

        Args:
            org_id: UUID de la organización.

        Returns:
            OrgDistributionState existente o recién creado.
        """
        if org_id not in self._state:
            logger.info(
                "state_map.org_creada",
                org_id=org_id,
                motivo="primera_actualizacion",
            )
            self._state[org_id] = OrgDistributionState()
        return self._state[org_id]

    async def update_config(
        self,
        org_id: str,
        config_hash: str,
        config_s3_url: str,
        scope: str,
        scope_id: str | None,
    ) -> None:
        """
        Actualiza config en el map local según scope y publica a Redis.

        Maneja tres scopes:
        - "org": actualiza config_hash y config_s3_url a nivel org (default).
        - "vlan": actualiza/crea entrada en vlan_configs[scope_id].
        - "workstation": actualiza/crea entrada en ws_configs[scope_id].

        Después de la actualización local, publica el cambio vía Redis
        para que otros workers sincronicen su state map.

        Args:
            org_id: UUID de la organización.
            config_hash: Hash SHA256 corto de la config activa.
            config_s3_url: URL pública S3 del archivo .signed.
            scope: Scope de la config ("org", "vlan", "workstation").
            scope_id: ID del scope (vlan_id o workstation_id). None para scope "org".
        """
        org_state = self._get_or_create_org_state(org_id)

        if scope == "org":
            org_state.config_hash = config_hash
            org_state.config_s3_url = config_s3_url
            logger.info(
                "state_map.config_actualizada",
                org_id=org_id,
                scope=scope,
                config_hash=config_hash,
            )
        elif scope == "vlan":
            org_state.vlan_configs[scope_id] = VlanConfigState(
                config_hash=config_hash,
                config_s3_url=config_s3_url,
            )
            logger.info(
                "state_map.config_actualizada",
                org_id=org_id,
                scope=scope,
                scope_id=scope_id,
                config_hash=config_hash,
            )
        elif scope == "workstation":
            org_state.ws_configs[scope_id] = WsConfigState(
                config_hash=config_hash,
                config_s3_url=config_s3_url,
            )
            logger.info(
                "state_map.config_actualizada",
                org_id=org_id,
                scope=scope,
                scope_id=scope_id,
                config_hash=config_hash,
            )
        else:
            logger.warning(
                "state_map.scope_desconocido",
                org_id=org_id,
                scope=scope,
            )
            return

        # Publicar actualización a otros workers vía Redis
        await self._publish_update(org_id, "config", {
            "config_hash": config_hash,
            "config_s3_url": config_s3_url,
            "scope": scope,
            "scope_id": scope_id,
        })

    async def update_cert(self, org_id: str, cert_version: int, cert_url: str) -> None:
        """
        Actualiza cert en el map local y publica a Redis.

        Args:
            org_id: UUID de la organización.
            cert_version: Nueva versión del certificado ECDSA.
            cert_url: URL pública S3 del archivo .cer.
        """
        org_state = self._get_or_create_org_state(org_id)
        org_state.cert_version = cert_version
        org_state.cert_url = cert_url

        logger.info(
            "state_map.cert_actualizado",
            org_id=org_id,
            cert_version=cert_version,
        )

        # Publicar actualización a otros workers vía Redis
        await self._publish_update(org_id, "cert", {
            "cert_version": cert_version,
            "cert_url": cert_url,
        })

    async def update_msi(
        self,
        org_id: str,
        msi_version: str,
        msi_url: str,
        msi_url_expires_at: float = 0.0,
    ) -> None:
        """
        Actualiza MSI en el map local y publica a Redis.

        Args:
            org_id: UUID de la organización.
            msi_version: Versión target del MSI (e.g. "2.1.0").
            msi_url: Presigned URL S3 del MSI.
            msi_url_expires_at: Epoch timestamp de expiración de la presigned URL.
        """
        org_state = self._get_or_create_org_state(org_id)
        org_state.msi_version = msi_version
        org_state.msi_url = msi_url
        org_state.msi_url_expires_at = msi_url_expires_at

        logger.info(
            "state_map.msi_actualizado",
            org_id=org_id,
            msi_version=msi_version,
            msi_url_expires_at=msi_url_expires_at,
        )

        # Publicar actualización a otros workers vía Redis
        await self._publish_update(org_id, "msi", {
            "msi_version": msi_version,
            "msi_url": msi_url,
            "msi_url_expires_at": msi_url_expires_at,
        })

    async def resolve_workstation_state(
        self, org_id: str, vlan_id: str | None, ws_id: str
    ) -> dict:
        """
        Resuelve el estado efectivo para una workstation aplicando herencia de scope.

        Prioridad de resolución (más específico gana):
            workstation > vlan > org

        Para config_hash y config_s3_url se aplica la jerarquía completa.
        Para cert y MSI siempre se usa el valor a nivel org (no tienen scope).

        Args:
            org_id: UUID de la organización.
            vlan_id: ID de la VLAN (puede ser None si no aplica).
            ws_id: ID de la workstation.

        Returns:
            Dict con las claves: config_hash, config_s3_url, cert_version,
            cert_url, msi_version, msi_url. Valores None si no hay datos.
        """
        org_state = self._state.get(org_id)

        if org_state is None:
            logger.debug(
                "state_map.resolve_ws_sin_datos",
                org_id=org_id,
                ws_id=ws_id,
            )
            return {
                "config_hash": None,
                "config_s3_url": None,
                "cert_version": 0,
                "cert_url": None,
                "msi_version": None,
                "msi_url": None,
            }

        # Resolución jerárquica de config: org < vlan < workstation
        config_hash = org_state.config_hash
        config_s3_url = org_state.config_s3_url

        # Override por VLAN (si existe)
        if vlan_id and vlan_id in org_state.vlan_configs:
            vlan_state = org_state.vlan_configs[vlan_id]
            config_hash = vlan_state.config_hash
            config_s3_url = vlan_state.config_s3_url

        # Override por workstation (más específico, gana siempre)
        if ws_id in org_state.ws_configs:
            ws_state = org_state.ws_configs[ws_id]
            config_hash = ws_state.config_hash
            config_s3_url = ws_state.config_s3_url

        # Verificar expiración de presigned URL de MSI y regenerar si es necesario
        msi_url = org_state.msi_url
        if org_state.msi_version and org_state.msi_url:
            msi_url = await self._check_msi_url_expiration(org_id, org_state)

        return {
            "config_hash": config_hash,
            "config_s3_url": config_s3_url,
            "cert_version": org_state.cert_version,
            "cert_url": org_state.cert_url,
            "msi_version": org_state.msi_version,
            "msi_url": msi_url,
        }

    # =========================================================================
    # DETECCIÓN DE INCONSISTENCIAS INTER-WORKER (Task 1.5)
    # =========================================================================

    def _detect_inconsistency(
        self,
        org_id: str,
        update_type: str,
        data: dict,
        org_state: OrgDistributionState,
        origin_worker_id: str,
    ) -> None:
        """
        Detecta inconsistencias entre el valor local y el valor remoto.

        Si el estado local tiene un valor DIFERENTE al que otro worker
        acaba de publicar (para el mismo campo), se loguea ERROR como
        señal diagnóstica. El valor remoto se aplicará de todos modos
        (remote wins).

        Args:
            org_id: UUID de la organización.
            update_type: Tipo de actualización.
            data: Datos remotos del otro worker.
            org_state: Estado local actual de la org.
            origin_worker_id: ID del worker que originó el cambio.
        """
        local_value = None
        remote_value = None

        if update_type == "config":
            scope = data.get("scope", "org")
            scope_id = data.get("scope_id")
            remote_value = data.get("config_hash")

            if scope == "org":
                local_value = org_state.config_hash
            elif scope == "vlan" and scope_id:
                vlan_state = org_state.vlan_configs.get(scope_id)
                local_value = vlan_state.config_hash if vlan_state else None
            elif scope == "workstation" and scope_id:
                ws_state = org_state.ws_configs.get(scope_id)
                local_value = ws_state.config_hash if ws_state else None

        elif update_type == "cert":
            local_value = org_state.cert_version
            remote_value = data.get("cert_version", 0)

        elif update_type == "msi":
            local_value = org_state.msi_version
            remote_value = data.get("msi_version")

        # Solo reportar inconsistencia si AMBOS valores existen y difieren
        # (si local es None, es porque no tenía datos — no es inconsistencia)
        if local_value is not None and remote_value is not None and local_value != remote_value:
            logger.error(
                "state_map.inconsistencia_detectada",
                org_id=org_id,
                update_type=update_type,
                local_value=local_value,
                remote_value=remote_value,
                origin_worker_id=origin_worker_id,
                msg="Valor local difiere del remoto. Aplicando valor remoto (más reciente).",
            )

    # =========================================================================
    # REGENERACIÓN DE PRESIGNED URL MSI (Task 1.5)
    # =========================================================================

    async def _check_msi_url_expiration(
        self, org_id: str, org_state: OrgDistributionState
    ) -> str | None:
        """
        Verifica si la presigned URL de MSI está por expirar y la regenera si es necesario.

        Si `msi_url_expires_at - time.time() < 300` (5 minutos), se regenera
        la presigned URL usando S3UpdateService. Si la regeneración falla,
        retorna la URL actual (posiblemente expirada) y loguea warning.

        Args:
            org_id: UUID de la organización.
            org_state: Estado de distribución de la org.

        Returns:
            URL de MSI válida (regenerada o existente).
        """
        if not org_state.msi_url or not org_state.msi_version:
            return org_state.msi_url

        # Verificar si la URL está por expirar
        time_remaining = org_state.msi_url_expires_at - time.time()

        if time_remaining > _MSI_URL_REFRESH_THRESHOLD_SECONDS:
            # URL aún válida, no necesita regeneración
            return org_state.msi_url

        # URL por expirar o ya expirada — intentar regenerar
        logger.info(
            "state_map.msi_url_expirando",
            org_id=org_id,
            msi_version=org_state.msi_version,
            tiempo_restante_segundos=int(time_remaining),
        )

        try:
            # Lazy init del servicio S3
            if self._s3_update_service is None:
                from app.services.s3_update_service import S3UpdateService
                self._s3_update_service = S3UpdateService()

            # Generar nueva presigned URL (1 hora de expiración por defecto)
            expires_in = 3600
            new_url = self._s3_update_service.generate_download_url(
                key=f"versions/{org_state.msi_version}/AlwaysPrint.msi",
                expires_in=expires_in,
            )

            # Actualizar el state map con la nueva URL y expiración
            new_expires_at = time.time() + expires_in
            org_state.msi_url = new_url
            org_state.msi_url_expires_at = new_expires_at

            logger.info(
                "state_map.msi_url_regenerada",
                org_id=org_id,
                msi_version=org_state.msi_version,
                nueva_expiracion=new_expires_at,
            )

            return new_url

        except Exception as e:
            # Si la regeneración falla, retornar la URL actual y loguear warning
            logger.warning(
                "state_map.msi_url_regeneracion_fallida",
                org_id=org_id,
                msi_version=org_state.msi_version,
                error=str(e),
                msg="Retornando URL actual (posiblemente expirada)",
            )
            return org_state.msi_url

    # =========================================================================
    # SHUTDOWN
    # =========================================================================

    async def shutdown(self) -> None:
        """
        Detiene el listener y cierra conexión Redis.

        Se llama durante el shutdown del worker para limpiar recursos.
        """
        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass

        if self._pubsub:
            try:
                await self._pubsub.unsubscribe(_STATE_MAP_CHANNEL)
                await self._pubsub.close()
            except Exception:
                pass

        if self._redis:
            try:
                await self._redis.close()
            except Exception:
                pass

        logger.info("state_map.shutdown_completado", worker_id=self._worker_id)
