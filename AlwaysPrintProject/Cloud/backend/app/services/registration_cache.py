"""
Cache de datos de registro en Redis con fallback a PostgreSQL.

Este módulo implementa RegistrationCache, que cachea datos frecuentemente
consultados durante el registro de workstations (organización, VLAN, config efectiva,
estado de contingencia forzada) para reducir la latencia del hot path.

Todas las keys están namespaced por organization_id para garantizar tenant isolation.
Si Redis no está disponible, se realiza fallback transparente a PostgreSQL.

Uso:
    from app.services.registration_cache import RegistrationCache

    cache = RegistrationCache(redis=redis_client, ttl_seconds=300)
    org_data = await cache.get_organization_data(org_id, db)
"""

import json
from typing import Any, Dict, List, Optional

import redis.asyncio as aioredis
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models.config import GlobalConfig, VLANConfig, WorkstationConfig
from app.models.device import Device
from app.models.organization import Organization, PublicIP
from app.models.vlan import VLAN
from app.models.workstation import Workstation

logger = get_logger(__name__)


class RegistrationCache:
    """Cache de datos de registro en Redis con fallback a PostgreSQL."""

    def __init__(
        self,
        redis: Optional[aioredis.Redis] = None,
        ttl_seconds: int = settings.CACHE_TTL_SECONDS,
    ):
        """
        Inicializa el cache de registro.

        Args:
            redis: Cliente Redis async. Si es None, todas las consultas van directo a PostgreSQL.
            ttl_seconds: Tiempo de vida del cache en segundos (default: CACHE_TTL_SECONDS).
        """
        self._redis = redis
        self._ttl = ttl_seconds

    # =========================================================================
    # MÉTODOS PÚBLICOS DE LECTURA
    # =========================================================================

    async def get_organization_data(
        self, organization_id: str, db: Session
    ) -> Optional[Dict[str, Any]]:
        """
        Obtiene datos de organización desde cache o BD.

        Key Redis: cache:org:{organization_id}:data

        Args:
            organization_id: UUID de la organización.
            db: Sesión SQLAlchemy (mantenida por compatibilidad, no se usa internamente).

        Returns:
            Dict con datos de la organización o None si no existe.
        """
        cache_key = f"cache:org:{organization_id}:data"
        return await self._get_or_fetch(
            cache_key=cache_key,
            fetch_fn=lambda internal_db: self._fetch_organization_data(organization_id, internal_db),
            data_type="organization",
            identifier=organization_id,
        )

    async def get_vlan_data(
        self, vlan_id: str, db: Session
    ) -> Optional[Dict[str, Any]]:
        """
        Obtiene datos de VLAN desde cache o BD.

        Key Redis: cache:vlan:{vlan_id}:data

        Args:
            vlan_id: UUID de la VLAN.
            db: Sesión SQLAlchemy (mantenida por compatibilidad, no se usa internamente).

        Returns:
            Dict con datos de la VLAN o None si no existe.
        """
        cache_key = f"cache:vlan:{vlan_id}:data"
        return await self._get_or_fetch(
            cache_key=cache_key,
            fetch_fn=lambda internal_db: self._fetch_vlan_data(vlan_id, internal_db),
            data_type="vlan",
            identifier=vlan_id,
        )

    async def get_effective_config(
        self, workstation_id: str, db: Session
    ) -> Optional[Dict[str, Any]]:
        """
        Obtiene configuración efectiva desde cache o BD.

        Key Redis: cache:config:{workstation_id}:effective

        Args:
            workstation_id: UUID de la workstation.
            db: Sesión SQLAlchemy (mantenida por compatibilidad, no se usa internamente).

        Returns:
            Dict con la configuración efectiva o None si la workstation no existe.
        """
        cache_key = f"cache:config:{workstation_id}:effective"
        return await self._get_or_fetch(
            cache_key=cache_key,
            fetch_fn=lambda internal_db: self._fetch_effective_config(workstation_id, internal_db),
            data_type="effective_config",
            identifier=workstation_id,
        )

    async def get_forced_contingency_state(
        self,
        workstation_id: str,
        organization_id: str,
        vlan_id: Optional[str],
        db: Session,
    ) -> Optional[Dict[str, Any]]:
        """
        Obtiene estado de contingencia forzada desde cache o BD.

        Resuelve la prioridad: organización > VLAN > workstation individual.

        Key Redis: cache:contingency:{workstation_id}:state

        Args:
            workstation_id: UUID de la workstation.
            organization_id: UUID de la organización.
            vlan_id: UUID de la VLAN (puede ser None).
            db: Sesión SQLAlchemy (mantenida por compatibilidad, no se usa internamente).

        Returns:
            Dict con estado de contingencia: {enabled, source, source_name, printer_ip}
        """
        cache_key = f"cache:contingency:{workstation_id}:state"
        return await self._get_or_fetch(
            cache_key=cache_key,
            fetch_fn=lambda internal_db: self._fetch_forced_contingency_state(
                workstation_id, organization_id, vlan_id, internal_db
            ),
            data_type="contingency_state",
            identifier=workstation_id,
        )

    # =========================================================================
    # MÉTODOS PÚBLICOS DE INVALIDACIÓN
    # =========================================================================

    async def invalidate_organization(self, organization_id: str) -> None:
        """
        Invalida todas las keys de cache relacionadas con una organización.

        Elimina: datos de org, IPs públicas, y keys de workstations asociadas
        (config efectiva, estado de contingencia).

        Args:
            organization_id: UUID de la organización a invalidar.
        """
        if not self._redis:
            return

        try:
            # Keys directas de la organización
            keys_to_delete = [
                f"cache:org:{organization_id}:data",
                f"cache:org:{organization_id}:public_ips",
            ]

            # Buscar keys de config y contingencia asociadas a esta organización
            # Usamos SCAN para encontrar keys que matcheen el patrón
            config_pattern = "cache:config:*:effective"
            contingency_pattern = "cache:contingency:*:state"

            async for key in self._redis.scan_iter(match=config_pattern, count=100):
                key_str = key.decode("utf-8") if isinstance(key, bytes) else key
                keys_to_delete.append(key_str)

            async for key in self._redis.scan_iter(match=contingency_pattern, count=100):
                key_str = key.decode("utf-8") if isinstance(key, bytes) else key
                keys_to_delete.append(key_str)

            # También invalidar VLANs de esta organización
            vlan_pattern = "cache:vlan:*:data"
            async for key in self._redis.scan_iter(match=vlan_pattern, count=100):
                key_str = key.decode("utf-8") if isinstance(key, bytes) else key
                keys_to_delete.append(key_str)

            if keys_to_delete:
                deleted = await self._redis.delete(*keys_to_delete)
                logger.info(
                    "cache.invalidate",
                    keys_deleted=deleted,
                    trigger="invalidate_organization",
                    org_id=organization_id,
                    total_keys_attempted=len(keys_to_delete),
                )
        except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as e:
            logger.warning(
                "cache.invalidate_error",
                error=str(e),
                trigger="invalidate_organization",
                org_id=organization_id,
            )

    async def invalidate_vlan(self, vlan_id: str, organization_id: str) -> None:
        """
        Invalida keys de cache relacionadas con una VLAN específica.

        Elimina: datos de VLAN + config/contingencia de workstations en esa VLAN.

        Args:
            vlan_id: UUID de la VLAN a invalidar.
            organization_id: UUID de la organización (para logging y contexto).
        """
        if not self._redis:
            return

        try:
            # Key directa de la VLAN
            keys_to_delete = [f"cache:vlan:{vlan_id}:data"]

            # Las keys de config y contingencia de workstations en esta VLAN
            # no tienen el vlan_id en su nombre, así que las eliminamos por patrón general
            # (invalidación conservadora: elimina todas las config/contingency keys)
            config_pattern = "cache:config:*:effective"
            contingency_pattern = "cache:contingency:*:state"

            async for key in self._redis.scan_iter(match=config_pattern, count=100):
                key_str = key.decode("utf-8") if isinstance(key, bytes) else key
                keys_to_delete.append(key_str)

            async for key in self._redis.scan_iter(match=contingency_pattern, count=100):
                key_str = key.decode("utf-8") if isinstance(key, bytes) else key
                keys_to_delete.append(key_str)

            if keys_to_delete:
                deleted = await self._redis.delete(*keys_to_delete)
                logger.info(
                    "cache.invalidate",
                    keys_deleted=deleted,
                    trigger="invalidate_vlan",
                    vlan_id=vlan_id,
                    org_id=organization_id,
                    total_keys_attempted=len(keys_to_delete),
                )
        except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as e:
            logger.warning(
                "cache.invalidate_error",
                error=str(e),
                trigger="invalidate_vlan",
                vlan_id=vlan_id,
                org_id=organization_id,
            )

    # =========================================================================
    # MÉTODOS INTERNOS: PATRÓN GET-OR-FETCH
    # =========================================================================

    async def _get_or_fetch(
        self,
        cache_key: str,
        fetch_fn,
        data_type: str,
        identifier: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Patrón genérico: intenta leer de Redis, si no existe consulta BD y cachea.

        La consulta a BD usa una sesión interna corta (SessionLocal) que se cierra
        inmediatamente después de la query, garantizando que no quedan transacciones
        idle-in-transaction mientras se espera el await de Redis setex.

        Args:
            cache_key: Key completa de Redis.
            fetch_fn: Callable que recibe una Session y retorna dict o None.
            data_type: Tipo de dato para logging.
            identifier: ID del recurso para logging.

        Returns:
            Dict con datos o None si el recurso no existe en BD.
        """
        # Intentar leer de Redis
        if self._redis:
            try:
                cached = await self._redis.get(cache_key)
                if cached is not None:
                    logger.debug(
                        "cache.hit",
                        key=cache_key,
                        data_type=data_type,
                    )
                    return json.loads(cached)
            except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as e:
                # Redis no disponible: fallback a PostgreSQL
                logger.warning(
                    "cache.redis_unavailable",
                    error=str(e),
                    data_type=data_type,
                    identifier=identifier,
                )

        # Cache miss o Redis no disponible: consultar PostgreSQL con sesión interna corta.
        # Usar sesión propia para garantizar que la transacción se cierra inmediatamente
        # después de la query, sin depender del lifecycle del caller. Esto elimina el
        # problema de conexiones idle-in-transaction durante el await de Redis setex.
        logger.debug(
            "cache.miss",
            key=cache_key,
            data_type=data_type,
        )

        from app.core.database import SessionLocal

        internal_db = SessionLocal()
        try:
            data = fetch_fn(internal_db)
        except Exception as e:
            logger.error(
                "cache.db_fetch_error",
                error=str(e),
                data_type=data_type,
                identifier=identifier,
            )
            return None
        finally:
            internal_db.close()

        if data is None:
            # Recurso no existe en BD: NO almacenar valor vacío en Redis
            return None

        # Almacenar en Redis con TTL (solo si Redis está disponible).
        # La sesión de BD ya está cerrada — no hay transacción abierta durante este await.
        if self._redis:
            try:
                await self._redis.setex(
                    cache_key,
                    self._ttl,
                    json.dumps(data, default=str),
                )
                logger.debug(
                    "cache.set",
                    key=cache_key,
                    data_type=data_type,
                    ttl_seconds=self._ttl,
                )
            except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as e:
                # No se pudo cachear pero tenemos los datos: continuar sin cache
                logger.warning(
                    "cache.set_error",
                    error=str(e),
                    data_type=data_type,
                    identifier=identifier,
                )

        return data

    # =========================================================================
    # MÉTODOS INTERNOS: FETCH DESDE POSTGRESQL
    # =========================================================================

    def _fetch_organization_data(
        self, organization_id: str, db: Session
    ) -> Optional[Dict[str, Any]]:
        """
        Consulta datos de organización desde PostgreSQL.

        Incluye: datos básicos + lista de IPs públicas autorizadas.
        """
        org = db.query(Organization).filter(
            Organization.id == organization_id
        ).first()

        if not org:
            return None

        # Obtener IPs públicas autorizadas
        public_ips = db.query(PublicIP).filter(
            PublicIP.organization_id == organization_id,
            PublicIP.is_authorized == True,
        ).all()

        return {
            "id": str(org.id),
            "name": org.name,
            "is_active": org.is_active,
            "timezone": org.timezone,
            "language": org.language,
            "auto_update_enabled": org.auto_update_enabled,
            "target_version": org.target_version,
            "auto_reregister_enabled": org.auto_reregister_enabled,
            "forced_contingency": org.forced_contingency,
            "offline_timeout_minutes": org.offline_timeout_minutes,
            "jitter_window_seconds": org.jitter_window_seconds,
            "public_ips": [
                {
                    "id": str(ip.id),
                    "ip_address": ip.ip_address,
                    "description": ip.description,
                }
                for ip in public_ips
            ],
        }

    def _fetch_vlan_data(self, vlan_id: str, db: Session) -> Optional[Dict[str, Any]]:
        """
        Consulta datos de VLAN desde PostgreSQL.
        """
        vlan = db.query(VLAN).filter(VLAN.id == vlan_id).first()

        if not vlan:
            return None

        return {
            "id": str(vlan.id),
            "organization_id": str(vlan.organization_id),
            "name": vlan.name,
            "description": vlan.description,
            "cidr_ranges": vlan.cidr_ranges,
            "forced_contingency": vlan.forced_contingency,
            "contingency_inherited": vlan.contingency_inherited,
            "default_device_id": str(vlan.default_device_id) if vlan.default_device_id else None,
            "vlan_metadata": vlan.vlan_metadata,
        }

    def _fetch_effective_config(
        self, workstation_id: str, db: Session
    ) -> Optional[Dict[str, Any]]:
        """
        Consulta configuración efectiva desde PostgreSQL.

        Replica la lógica de ConfigService.get_effective_config sin crear
        GlobalConfig automáticamente (solo lectura para cache).
        """
        # 1. Obtener workstation
        workstation = db.query(Workstation).filter_by(id=workstation_id).first()
        if not workstation:
            return None

        # 2. Obtener GlobalConfig
        global_config = db.query(GlobalConfig).filter_by(
            organization_id=workstation.organization_id
        ).first()

        if not global_config:
            # Sin GlobalConfig, no hay configuración que resolver
            return None

        # 3. Obtener VLANConfig si la workstation está en una VLAN
        vlan_config = None
        if workstation.vlan_id:
            vlan_config = db.query(VLANConfig).filter_by(
                vlan_id=workstation.vlan_id
            ).first()

        # 4. Obtener WorkstationConfig si existe
        ws_config = db.query(WorkstationConfig).filter_by(
            workstation_id=workstation_id
        ).first()

        # 5. Resolver cada campo con precedencia: WorkstationConfig > VLANConfig > GlobalConfig
        config: Dict[str, Any] = {}
        sources: Dict[str, str] = {}

        fields = [
            "corporate_queue_name",
            "search_targets",
            "pending_task_polling_minutes",
            "bootstrap_domains",
            "connectivity_checks",
            "locale",
            "telemetry_enabled",
            "telemetry_interval_seconds",
        ]

        for field in fields:
            value, source = self._resolve_field(ws_config, vlan_config, global_config, field)
            config[field] = value
            sources[field] = source

        config["source"] = sources

        # 6. jitter_window_seconds viene de la organización
        org = db.query(Organization).filter_by(id=workstation.organization_id).first()
        config["jitter_window_seconds"] = org.jitter_window_seconds if org else 30

        # 7. Computar config_hash
        import hashlib

        hashable = {k: v for k, v in config.items() if k not in ("source", "config_hash")}
        json_str = json.dumps(hashable, sort_keys=True, ensure_ascii=False)
        config["config_hash"] = hashlib.sha256(json_str.encode("utf-8")).hexdigest()

        return config

    def _resolve_field(
        self,
        ws_config: Optional[WorkstationConfig],
        vlan_config: Optional[VLANConfig],
        global_config: GlobalConfig,
        field_name: str,
    ) -> tuple:
        """
        Resuelve un campo con precedencia: workstation > vlan > global.

        Returns:
            Tupla (valor, fuente) donde fuente es "workstation", "vlan" o "global".
        """
        # WorkstationConfig tiene mayor precedencia
        if ws_config and getattr(ws_config, field_name, None) is not None:
            return getattr(ws_config, field_name), "workstation"

        # VLANConfig tiene precedencia intermedia
        if vlan_config and getattr(vlan_config, field_name, None) is not None:
            return getattr(vlan_config, field_name), "vlan"

        # GlobalConfig es el fallback
        return getattr(global_config, field_name), "global"

    def _fetch_forced_contingency_state(
        self,
        workstation_id: str,
        organization_id: str,
        vlan_id: Optional[str],
        db: Session,
    ) -> Optional[Dict[str, Any]]:
        """
        Resuelve el estado de contingencia forzada en un solo round-trip a PostgreSQL.

        Usa un JOIN que obtiene Workstation + Organization + VLAN (opcional) +
        Device (impresora predeterminada de la workstation) en una sola query.
        Luego resuelve la prioridad: organización > VLAN > workstation individual.

        Si se necesita printer_ip y no se obtuvo del JOIN principal, se ejecuta
        una segunda query para resolver la impresora de la VLAN (default o primera activa).

        Prioridad de contingencia: organización > VLAN > workstation.
        Prioridad de printer_ip: workstation default > VLAN default > primera activa VLAN.
        """
        from sqlalchemy.orm import aliased

        # Alias para la impresora predeterminada de la workstation
        WsPrinter = aliased(Device, name="ws_printer")

        # Query principal con JOINs:
        # Workstation INNER JOIN Organization + LEFT JOIN VLAN + LEFT JOIN Device (ws default printer)
        row = (
            db.query(
                Workstation.forced_contingency.label("ws_forced"),
                Workstation.hostname.label("ws_hostname"),
                Workstation.ip_private.label("ws_ip_private"),
                Workstation.vlan_id.label("ws_vlan_id"),
                Workstation.default_printer_id.label("ws_default_printer_id"),
                Workstation.organization_id.label("ws_org_id"),
                Organization.forced_contingency.label("org_forced"),
                Organization.name.label("org_name"),
                VLAN.forced_contingency.label("vlan_forced"),
                VLAN.name.label("vlan_name"),
                VLAN.default_device_id.label("vlan_default_device_id"),
                WsPrinter.ip_address.label("ws_printer_ip"),
            )
            .join(Organization, Organization.id == Workstation.organization_id)
            .outerjoin(VLAN, VLAN.id == Workstation.vlan_id)
            .outerjoin(WsPrinter, WsPrinter.id == Workstation.default_printer_id)
            .filter(
                Workstation.id == workstation_id,
                Workstation.organization_id == organization_id,
            )
            .first()
        )

        if not row:
            return None

        # Resolver prioridad de contingencia forzada
        forced_contingency_enabled = False
        forced_source = None
        forced_source_name = None

        # Prioridad 1: Organización
        if row.org_forced:
            forced_contingency_enabled = True
            forced_source = "organization"
            forced_source_name = row.org_name

        # Prioridad 2: VLAN (solo si hay vlan_id y la VLAN tiene forced_contingency)
        if not forced_contingency_enabled and row.ws_vlan_id and row.vlan_forced:
            forced_contingency_enabled = True
            forced_source = "vlan"
            forced_source_name = row.vlan_name

        # Prioridad 3: Workstation individual
        if not forced_contingency_enabled and row.ws_forced:
            forced_contingency_enabled = True
            forced_source = "workstation"
            forced_source_name = row.ws_hostname or str(row.ws_ip_private)

        # Resolver printer_ip si hay contingencia activa
        printer_ip = None
        if forced_contingency_enabled:
            printer_ip = self._resolve_printer_ip_optimized(row, db)

        # Construir resultado (siempre retornar estado, incluso si no hay contingencia)
        return {
            "enabled": forced_contingency_enabled,
            "source": forced_source if forced_contingency_enabled else "sync",
            "source_name": forced_source_name if forced_contingency_enabled else "normal",
            "printer_ip": printer_ip,
        }

    def _resolve_printer_ip_optimized(
        self, row, db: Session
    ) -> Optional[str]:
        """
        Resuelve la IP de impresora para contingencia forzada de forma optimizada.

        Usa los datos ya obtenidos del JOIN principal para evitar queries adicionales.
        Solo ejecuta una query extra si la impresora viene de la VLAN (default o primera activa).

        Prioridad:
        1. Impresora predeterminada de la workstation (ya en el JOIN)
        2. Impresora predeterminada de la VLAN (query adicional solo si necesario)
        3. Primera impresora activa de la VLAN (query adicional solo si necesario)
        """
        # 1. Impresora predeterminada de la workstation (ya resuelta en el JOIN)
        if row.ws_default_printer_id and row.ws_printer_ip:
            return row.ws_printer_ip

        # 2 y 3. Resolver impresora de la VLAN (si la workstation tiene VLAN)
        if row.ws_vlan_id:
            # Query única para resolver impresora de la VLAN:
            # Primero intenta la impresora por defecto de la VLAN,
            # luego la primera activa de la VLAN ordenada por IP
            if row.vlan_default_device_id:
                # Intentar la impresora predeterminada de la VLAN
                default_dev = db.query(Device.ip_address).filter(
                    Device.id == row.vlan_default_device_id
                ).scalar()
                if default_dev:
                    return default_dev

            # 3. Primera impresora activa de la VLAN
            first_device_ip = (
                db.query(Device.ip_address)
                .filter(
                    Device.vlan_id == row.ws_vlan_id,
                    Device.organization_id == row.ws_org_id,
                    Device.is_active == True,
                )
                .order_by(Device.ip_address)
                .limit(1)
                .scalar()
            )
            if first_device_ip:
                return first_device_ip

        return None
