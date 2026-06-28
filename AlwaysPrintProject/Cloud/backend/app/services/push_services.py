"""
Módulo de acceso singleton a los servicios de distribución push-based.

Provee acceso a StateMapService y PushDistributionService como singletons
lazy-initialized. La inicialización completa (carga desde BD + Redis) se
realiza en el lifespan del app (Task 9.1). Hasta entonces, los servicios
operan en modo "best-effort": si no están inicializados, las operaciones
de push se logean como warning y no bloquean el flujo normal de los endpoints.

Uso:
    from app.services.push_services import get_state_map_service, get_push_distribution_service

    state_map = get_state_map_service()
    push_service = get_push_distribution_service()
"""

import logging

from app.services.state_map_service import StateMapService
from app.services.push_distribution_service import PushDistributionService
from app.services.websocket_manager import connection_manager
from app.core.config import settings

logger = logging.getLogger(__name__)

# Singletons lazy-initialized
_state_map_service: StateMapService | None = None
_push_distribution_service: PushDistributionService | None = None


def get_state_map_service() -> StateMapService:
    """
    Retorna la instancia singleton del StateMapService.

    Si no ha sido inicializada aún, la crea con la configuración de Redis.
    La inicialización completa (carga desde BD) se hace por separado
    vía initialize() durante el lifespan del app (Task 9.1).
    """
    global _state_map_service
    if _state_map_service is None:
        redis_url = getattr(settings, "REDIS_URL", None)
        _state_map_service = StateMapService(redis_url=redis_url)
        logger.info(
            "StateMapService instanciado (redis_url=%s)",
            "configurado" if redis_url else "sin Redis",
        )
    return _state_map_service


def get_push_distribution_service() -> PushDistributionService:
    """
    Retorna la instancia singleton del PushDistributionService.

    Usa el connection_manager global y el StateMapService singleton.
    """
    global _push_distribution_service
    if _push_distribution_service is None:
        state_map = get_state_map_service()
        _push_distribution_service = PushDistributionService(
            connection_manager=connection_manager,
            state_map_service=state_map,
        )
        logger.info("PushDistributionService instanciado")
    return _push_distribution_service
