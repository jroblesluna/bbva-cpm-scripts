"""
Utilidades compartidas para acceso al RegistrationCache singleton.

Proporciona una función get_registration_cache() que puede ser usada
desde cualquier endpoint para obtener la instancia del cache y realizar
invalidaciones tras modificaciones a la BD.

Uso:
    from app.services.cache_utils import get_registration_cache

    cache = get_registration_cache()
    await cache.invalidate_organization(org_id)
"""

from typing import Optional

from app.services.registration_cache import RegistrationCache


# Singleton compartido del RegistrationCache
_registration_cache: Optional[RegistrationCache] = None


def get_registration_cache() -> RegistrationCache:
    """
    Obtiene o crea la instancia singleton de RegistrationCache.

    Si el connection_manager tiene un cliente Redis disponible (_redis),
    lo usa para el cache. Si no, opera en modo fallback (sin cache Redis).

    Returns:
        Instancia singleton de RegistrationCache.
    """
    global _registration_cache
    if _registration_cache is None:
        from app.services.websocket_manager import connection_manager

        # Obtener cliente Redis del connection_manager si está disponible
        redis_client = getattr(connection_manager, "_redis", None)
        _registration_cache = RegistrationCache(redis=redis_client)
    return _registration_cache
