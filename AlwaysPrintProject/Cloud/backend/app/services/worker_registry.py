"""
Registro de workstations por worker con TTL para detección de crashes.

Este módulo implementa el WorkerRegistry que gestiona:
- Registro de qué workstations están en qué worker (Redis SET con TTL)
- Detección de workers muertos vía expiración de keys
- Resolución de a qué worker enviar un comando
- Heartbeat periódico para renovar TTL

Claves Redis utilizadas:
- `workers:{worker_id}:workstations` → SET de workstation_ids (TTL configurable)
- `workers:{worker_id}:heartbeat` → timestamp del último heartbeat (TTL configurable)

Uso:
    from app.services.worker_registry import WorkerRegistry

    registry = WorkerRegistry(redis=redis_client, worker_id="worker_1234", ttl=60)
    await registry.register_workstation("ws-uuid-123")
    await registry.heartbeat()
"""

from typing import Optional

import redis.asyncio as aioredis

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class WorkerRegistry:
    """
    Registro de workstations por worker con TTL para detección de crashes.

    Cada worker mantiene un SET en Redis con las workstation_ids que tiene
    conectadas localmente. El TTL del SET se renueva periódicamente via
    heartbeat. Si un worker crashea sin hacer cleanup, el SET expira
    automáticamente tras el TTL, permitiendo a otros workers descartar
    rutas hacia workstations del worker muerto.
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        worker_id: str,
        ttl: int = settings.WORKER_REGISTRY_TTL,
    ):
        """
        Inicializa el registro de worker.

        Args:
            redis: Cliente Redis async (redis.asyncio.Redis)
            worker_id: Identificador único del worker (ej: "worker_12345")
            ttl: Tiempo de vida en segundos para las keys del worker (default desde settings)
        """
        self._redis = redis
        self._worker_id = worker_id
        self._ttl = ttl

    @property
    def _workstations_key(self) -> str:
        """Key del SET de workstations de este worker."""
        return f"workers:{self._worker_id}:workstations"

    @property
    def _heartbeat_key(self) -> str:
        """Key del heartbeat de este worker."""
        return f"workers:{self._worker_id}:heartbeat"

    async def register_workstation(self, workstation_id: str) -> None:
        """
        Registra una workstation en el SET del worker con TTL.

        Agrega el workstation_id al SET y renueva el TTL tanto del SET
        como del heartbeat key.

        Args:
            workstation_id: UUID de la workstation a registrar
        """
        try:
            pipe = self._redis.pipeline()
            pipe.sadd(self._workstations_key, workstation_id)
            pipe.expire(self._workstations_key, self._ttl)
            pipe.set(self._heartbeat_key, "alive", ex=self._ttl)
            await pipe.execute()

            logger.debug(
                "worker.register_ws",
                workstation_id=workstation_id,
                ttl=self._ttl,
            )
        except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as e:
            logger.warning(
                "worker.register_ws_fallback",
                workstation_id=workstation_id,
                error=str(e),
            )

    async def unregister_workstation(self, workstation_id: str) -> None:
        """
        Elimina una workstation del SET del worker.

        Remueve el workstation_id del SET. Si el SET queda vacío,
        Redis lo eliminará automáticamente.

        Args:
            workstation_id: UUID de la workstation a eliminar
        """
        try:
            await self._redis.srem(self._workstations_key, workstation_id)

            logger.debug(
                "worker.unregister_ws",
                workstation_id=workstation_id,
            )
        except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as e:
            logger.warning(
                "worker.unregister_ws_fallback",
                workstation_id=workstation_id,
                error=str(e),
            )

    async def heartbeat(self) -> None:
        """
        Renueva el TTL del SET de workstations y del heartbeat key.

        Debe llamarse periódicamente (ej: cada TTL/2 segundos) para
        evitar que las keys expiren mientras el worker está vivo.
        Si Redis no está disponible, se loguea warning y continúa sin error.
        """
        try:
            pipe = self._redis.pipeline()
            pipe.expire(self._workstations_key, self._ttl)
            pipe.set(self._heartbeat_key, "alive", ex=self._ttl)
            await pipe.execute()

            logger.debug("worker.heartbeat", ttl=self._ttl)
        except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as e:
            logger.warning(
                "worker.heartbeat_fallback",
                error=str(e),
            )

    async def cleanup_on_shutdown(self) -> None:
        """
        Elimina todo el SET del worker y el heartbeat key (shutdown graceful).

        Se invoca durante el apagado ordenado del worker (SIGTERM) para
        limpiar inmediatamente las keys en Redis sin esperar a que expiren
        por TTL. Esto permite a otros workers saber de inmediato que este
        worker ya no está activo.
        """
        try:
            pipe = self._redis.pipeline()
            pipe.delete(self._workstations_key)
            pipe.delete(self._heartbeat_key)
            await pipe.execute()

            logger.info("worker.cleanup_on_shutdown")
        except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as e:
            logger.warning(
                "worker.cleanup_on_shutdown_fallback",
                error=str(e),
            )

    async def find_worker_for_workstation(
        self, workstation_id: str
    ) -> Optional[str]:
        """
        Busca en qué worker está registrada una workstation.

        Escanea todos los SETs de workers activos (aquellos con heartbeat
        key vigente) para encontrar cuál contiene el workstation_id.

        Args:
            workstation_id: UUID de la workstation a buscar

        Returns:
            worker_id del worker que tiene la workstation, o None si no se encuentra
        """
        try:
            # Buscar todas las keys de heartbeat activas para identificar workers vivos
            cursor = "0"
            while cursor:
                cursor, keys = await self._redis.scan(
                    cursor=cursor,
                    match="workers:*:heartbeat",
                    count=100,
                )
                for key in keys:
                    # Extraer worker_id de la key "workers:{worker_id}:heartbeat"
                    key_str = key if isinstance(key, str) else key.decode("utf-8")
                    parts = key_str.split(":")
                    if len(parts) >= 3:
                        candidate_worker_id = parts[1]
                        ws_key = f"workers:{candidate_worker_id}:workstations"
                        is_member = await self._redis.sismember(ws_key, workstation_id)
                        if is_member:
                            return candidate_worker_id

                # cursor devuelto como 0 o b"0" indica fin del scan
                if cursor == 0 or cursor == b"0":
                    break

            return None
        except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as e:
            logger.warning(
                "worker.find_worker_fallback",
                workstation_id=workstation_id,
                error=str(e),
            )
            return None
