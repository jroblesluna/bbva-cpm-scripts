# Feature: stable-multi-worker-redis, Property 5: Multi-worker requires Redis URL
"""
Property test: Multi-worker requires Redis URL

Para cualquier valor entero de UVICORN_WORKERS mayor a 1, si REDIS_URL es
None o vacío, la validación de Settings DEBE lanzar un ValueError impidiendo
el arranque del sistema.

Esto garantiza que no se puede desplegar en modo multi-worker sin la
coordinación vía Redis, previniendo un estado inconsistente donde los workers
no pueden comunicarse entre sí.

Feature: stable-multi-worker-redis, Property 5: Multi-worker requires Redis URL
**Validates: Requirements 2.2**
"""

from unittest.mock import patch

import pytest
from hypothesis import given, settings as hypothesis_settings
from hypothesis import strategies as st


# === ESTRATEGIA DE GENERACIÓN ===
# Workers en rango [2, 16] — cualquier valor > 1 debe requerir Redis
MULTI_WORKER_STRATEGY = st.integers(min_value=2, max_value=16)

# Valores que representan "sin Redis" — None y cadena vacía
NO_REDIS_VALUES = st.sampled_from([None, ""])


# === PROPERTY 5: MULTI-WORKER REQUIRES REDIS URL ===


@hypothesis_settings(max_examples=100, deadline=None)
@given(workers=MULTI_WORKER_STRATEGY, redis_url=NO_REDIS_VALUES)
def test_property_multi_worker_requires_redis(workers: int, redis_url):
    """
    Propiedad: Para cualquier valor de UVICORN_WORKERS > 1, sin REDIS_URL
    configurado (None o vacío), Settings debe lanzar ValueError.

    Esto impide que el sistema arranque en modo multi-worker sin Redis,
    ya que los workers necesitan pub/sub para coordinación.

    Feature: stable-multi-worker-redis, Property 5: Multi-worker requires Redis URL
    **Validates: Requirements 2.2**
    """
    from app.core.config import Settings

    # Parchear entorno para evitar que .env inyecte un REDIS_URL válido
    env_patch = {"REDIS_URL": ""} if redis_url is not None else {}
    env_remove = ["REDIS_URL"] if redis_url is None else []

    with patch.dict("os.environ", env_patch, clear=False):
        # Eliminar REDIS_URL del entorno si estamos probando None
        for key in env_remove:
            import os
            os.environ.pop(key, None)

        # Construir kwargs para Settings — pasar REDIS_URL explícitamente
        # Los argumentos del constructor tienen máxima prioridad en pydantic-settings
        kwargs = {
            "UVICORN_WORKERS": workers,
            "REDIS_URL": redis_url,
            "DATABASE_URL": "postgresql://test:test@localhost/test",
            "SECRET_KEY": "test-secret-key-solo-para-property-test",
        }

        with pytest.raises(ValueError, match="REDIS_URL es requerido"):
            Settings(**kwargs)
