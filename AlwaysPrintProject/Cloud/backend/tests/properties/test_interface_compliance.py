# Feature: stable-multi-worker-redis, Property 1: Interface compliance
"""
Property test: Interface compliance

Para cualquier nombre de método en la lista de interfaz pública requerida
(connect_workstation, disconnect_workstation, send_to_workstation, etc.),
tanto ConnectionManager como RedisConnectionManager DEBEN tener dicho nombre
como atributo callable.

Esto garantiza que ambos managers son intercambiables vía duck typing y que
el factory en websocket_manager.py puede seleccionar cualquiera sin romper
el código consumidor.

Feature: stable-multi-worker-redis, Property 1: Interface compliance
**Validates: Requirements 1.4, 10.3**
"""

from hypothesis import given, settings
from hypothesis import strategies as st


# === MÉTODOS REQUERIDOS DE LA INTERFAZ PÚBLICA ===
# Definidos en el diseño como la interfaz compartida entre ambos managers
REQUIRED_METHODS = [
    "connect_workstation",
    "disconnect_workstation",
    "send_to_workstation",
    "broadcast_to_organization",
    "handle_pong",
    "update_last_activity",
    "start_ping_loop",
    "stop_ping_loop",
    "graceful_shutdown_workstations",
    "get_online_workstations",
    "get_connection_count",
    "register_command_waiter",
    "resolve_command_response",
    "wait_for_command_response",
    "connect_operator",
    "disconnect_operator",
    "send_to_operator",
    "broadcast_to_all_operators",
    "get_online_operators",
    "send_direct_to_workstation",
]


# === PROPERTY TEST ===


@settings(max_examples=100)
@given(method_name=st.sampled_from(REQUIRED_METHODS))
def test_property_interface_compliance(method_name: str):
    """
    Propiedad: Para cualquier método de la interfaz pública requerida,
    tanto ConnectionManager como RedisConnectionManager deben tenerlo
    como atributo callable.

    Esto asegura que el factory puede intercambiar managers sin romper
    la compatibilidad con el código consumidor (duck typing).

    Feature: stable-multi-worker-redis, Property 1: Interface compliance
    **Validates: Requirements 1.4, 10.3**
    """
    from app.services.redis_connection_manager import RedisConnectionManager
    from app.services.websocket_manager import ConnectionManager

    # Verificar ConnectionManager (instanciado, no requiere dependencias externas)
    cm = ConnectionManager()
    assert hasattr(cm, method_name), (
        f"ConnectionManager no tiene el método '{method_name}'. "
        f"La interfaz pública requiere que ambos managers implementen este método."
    )
    assert callable(getattr(cm, method_name)), (
        f"ConnectionManager.{method_name} no es callable. "
        f"Debe ser un método invocable para cumplir la interfaz compartida."
    )

    # Verificar RedisConnectionManager (a nivel de clase, no se instancia
    # porque requiere redis_url y conexión activa)
    assert hasattr(RedisConnectionManager, method_name), (
        f"RedisConnectionManager no tiene el método '{method_name}'. "
        f"La interfaz pública requiere que ambos managers implementen este método."
    )
    assert callable(getattr(RedisConnectionManager, method_name)), (
        f"RedisConnectionManager.{method_name} no es callable. "
        f"Debe ser un método invocable para cumplir la interfaz compartida."
    )
