# Feature: stable-multi-worker-redis, Property 2: RegistrationCache import ban
"""
Property test: RegistrationCache import ban

Para cualquier archivo fuente Python en el flujo WebSocket (workstation.py,
operator.py, websocket_manager.py, redis_connection_manager.py, worker_registry.py),
el contenido del archivo NO DEBE contener la cadena "registration_cache" como
import o referencia.

Esto garantiza que el componente RegistrationCache —que causó exhaustión del pool
de conexiones PostgreSQL— no se reintroduzca accidentalmente en el flujo WS.

Feature: stable-multi-worker-redis, Property 2: RegistrationCache import ban
**Validates: Requirements 3.3, 3.4**
"""

from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st


# === ARCHIVOS DEL FLUJO WEBSOCKET ===
# Rutas relativas desde la raíz del backend
_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent

WS_FLOW_FILES = [
    str(_BACKEND_ROOT / "app" / "api" / "v1" / "websocket" / "workstation.py"),
    str(_BACKEND_ROOT / "app" / "api" / "v1" / "websocket" / "operator.py"),
    str(_BACKEND_ROOT / "app" / "services" / "websocket_manager.py"),
    str(_BACKEND_ROOT / "app" / "services" / "redis_connection_manager.py"),
    str(_BACKEND_ROOT / "app" / "services" / "worker_registry.py"),
]

# Cadena prohibida que indica uso de RegistrationCache
BANNED_IMPORT = "registration_cache"


# === PROPERTY TEST ===


@settings(max_examples=100)
@given(filepath=st.sampled_from(WS_FLOW_FILES))
def test_property_no_registration_cache(filepath: str):
    """
    Propiedad: Para cualquier archivo del flujo WebSocket, el contenido
    NO debe contener la cadena "registration_cache".

    Esto previene la reintroducción del componente que causó exhaustión
    del pool de conexiones PostgreSQL (idle in transaction).

    Feature: stable-multi-worker-redis, Property 2: RegistrationCache import ban
    **Validates: Requirements 3.3, 3.4**
    """
    path = Path(filepath)
    assert path.exists(), (
        f"El archivo del flujo WS no existe: {filepath}. "
        f"Verificar que la estructura del proyecto es correcta."
    )

    content = path.read_text(encoding="utf-8")
    assert BANNED_IMPORT not in content, (
        f"PROHIBIDO: {filepath} importa o referencia '{BANNED_IMPORT}'. "
        f"Usar ConfigService + queries inline en su lugar. "
        f"RegistrationCache causa exhaustión del pool de conexiones PostgreSQL."
    )
