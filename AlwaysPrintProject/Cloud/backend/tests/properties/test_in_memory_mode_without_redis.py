# Feature: websocket-scaling-redis, Property 14: In-Memory Mode Without Redis
"""
Property test: In-Memory Mode Without Redis

Para cualquier configuración donde REDIS_URL es None o vacío, el sistema DEBE
operar usando el ConnectionManager in-memory sin intentar ninguna conexión Redis,
y toda la entrega local de mensajes DEBE funcionar correctamente.

Verifica que:
1. Cuando REDIS_URL es None, create_connection_manager() retorna ConnectionManager (no Redis)
2. Cuando REDIS_URL es cadena vacía, mismo comportamiento que None
3. El manager retornado opera localmente sin intentar conexión Redis
4. La entrega local de mensajes funciona correctamente sin Redis

Feature: websocket-scaling-redis, Property 14: In-Memory Mode Without Redis
**Validates: Requirements 7.3**
"""

import asyncio
from typing import Dict, List, Optional, Set, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings as hypothesis_settings, assume
from hypothesis import strategies as st


# === ESTRATEGIAS DE GENERACIÓN ===

# Estrategia para valores de REDIS_URL que indican "sin Redis"
# None y cadenas vacías/whitespace-only
redis_url_none_strategy = st.sampled_from([None, "", " ", "  ", "\t", "\n", "   \t  "])

# UUIDs como strings para identificadores
ws_id_strategy = st.uuids().map(str)
org_id_strategy = st.uuids().map(str)

# Estrategia para tipos de mensaje válidos
message_type_strategy = st.sampled_from([
    "command",
    "check_update",
    "forced_contingency",
    "config_update",
    "status_update",
    "ping",
    "message",
])

# Estrategia para mensajes genéricos
message_strategy = st.fixed_dictionaries({
    "type": message_type_strategy,
    "data": st.text(min_size=1, max_size=50),
})


# === HELPERS ===


def create_mock_websocket(ws_id: str) -> MagicMock:
    """Crea un mock de WebSocket con send_json async."""
    mock_ws = AsyncMock()
    mock_ws.send_json = AsyncMock()
    mock_ws.close = AsyncMock()
    mock_ws._ws_id = ws_id
    return mock_ws


def create_mock_db() -> MagicMock:
    """Crea un mock de sesión de BD."""
    mock_db = MagicMock()
    mock_db.query = MagicMock()
    mock_db.commit = MagicMock()
    return mock_db


# === PROPERTY TESTS: FACTORY RETORNA ConnectionManager IN-MEMORY ===


@hypothesis_settings(max_examples=150, deadline=None)
@given(
    redis_url=redis_url_none_strategy,
)
async def test_factory_returns_in_memory_manager_when_redis_url_is_none_or_empty(
    redis_url: Optional[str],
):
    """
    Propiedad: Cuando REDIS_URL es None o cadena vacía/whitespace,
    create_connection_manager() retorna una instancia de ConnectionManager
    in-memory (no RedisConnectionManager).

    Garantiza backward compatibility cuando Redis no está configurado.

    Feature: websocket-scaling-redis, Property 14: In-Memory Mode Without Redis
    **Validates: Requirements 7.3**
    """
    from app.services.websocket_manager import ConnectionManager

    # Parchear settings.REDIS_URL con el valor generado
    with patch("app.core.config.settings") as mock_settings:
        mock_settings.REDIS_URL = redis_url
        # Re-importar la factory para usar el mock
        from app.services.websocket_manager import create_connection_manager

        manager = create_connection_manager()

    # Verificar que es instancia de ConnectionManager in-memory
    assert isinstance(manager, ConnectionManager), (
        f"Con REDIS_URL={repr(redis_url)}, create_connection_manager() debería "
        f"retornar ConnectionManager in-memory, pero retornó {type(manager).__name__}"
    )

    # Verificar que NO es instancia de RedisConnectionManager
    from app.services.redis_connection_manager import RedisConnectionManager

    assert not isinstance(manager, RedisConnectionManager), (
        f"Con REDIS_URL={repr(redis_url)}, create_connection_manager() NO debería "
        f"retornar RedisConnectionManager"
    )


@hypothesis_settings(max_examples=150, deadline=None)
@given(
    redis_url=redis_url_none_strategy,
)
async def test_factory_does_not_import_redis_when_url_is_none(
    redis_url: Optional[str],
):
    """
    Propiedad: Cuando REDIS_URL es None o vacío, la factory NO intenta
    importar ni instanciar RedisConnectionManager, evitando cualquier
    conexión a Redis.

    Feature: websocket-scaling-redis, Property 14: In-Memory Mode Without Redis
    **Validates: Requirements 7.3**
    """
    with patch("app.core.config.settings") as mock_settings:
        mock_settings.REDIS_URL = redis_url

        # Espiar la importación de RedisConnectionManager
        with patch(
            "app.services.redis_connection_manager.RedisConnectionManager"
        ) as mock_redis_mgr:
            from app.services.websocket_manager import create_connection_manager

            manager = create_connection_manager()

            # Verificar que RedisConnectionManager NO fue instanciado
            mock_redis_mgr.assert_not_called(), (
                f"Con REDIS_URL={repr(redis_url)}, NO se debería intentar "
                f"instanciar RedisConnectionManager"
            )


# === PROPERTY TESTS: IN-MEMORY MANAGER OPERA SIN REDIS ===


@hypothesis_settings(max_examples=150, deadline=None)
@given(
    redis_url=redis_url_none_strategy,
    ws_id=ws_id_strategy,
    org_id=org_id_strategy,
    message=message_strategy,
)
async def test_in_memory_manager_delivers_messages_locally(
    redis_url: Optional[str], ws_id: str, org_id: str, message: dict
):
    """
    Propiedad: El ConnectionManager in-memory entrega mensajes localmente
    sin depender de Redis. send_to_workstation funciona correctamente
    cuando la workstation está conectada localmente.

    Feature: websocket-scaling-redis, Property 14: In-Memory Mode Without Redis
    **Validates: Requirements 7.3**
    """
    with patch("app.core.config.settings") as mock_settings:
        mock_settings.REDIS_URL = redis_url

        from app.services.websocket_manager import create_connection_manager

        manager = create_connection_manager()

    # Registrar workstation directamente en el manager in-memory
    mock_ws = create_mock_websocket(ws_id)
    async with manager._lock:
        manager.workstation_connections[ws_id] = mock_ws
        manager.org_ids[ws_id] = org_id

    # Enviar mensaje — debe funcionar sin Redis
    result = await manager.send_to_workstation(ws_id, message)

    # Verificar entrega exitosa
    assert result is True, (
        f"send_to_workstation debería retornar True en modo in-memory, "
        f"pero retornó {result}"
    )
    mock_ws.send_json.assert_called_once_with(message)


@hypothesis_settings(max_examples=150, deadline=None)
@given(
    redis_url=redis_url_none_strategy,
    user_ids=st.lists(ws_id_strategy, min_size=1, max_size=5, unique=True),
    org_id=org_id_strategy,
    message=message_strategy,
)
async def test_in_memory_manager_broadcasts_to_operators_without_redis(
    redis_url: Optional[str], user_ids: List[str], org_id: str, message: dict
):
    """
    Propiedad: El ConnectionManager in-memory realiza broadcast_to_organization
    a los operadores de la organización sin depender de Redis.
    Consulta la BD para obtener usuarios de la org y envía a operadores conectados.

    Feature: websocket-scaling-redis, Property 14: In-Memory Mode Without Redis
    **Validates: Requirements 7.3**
    """
    with patch("app.core.config.settings") as mock_settings:
        mock_settings.REDIS_URL = redis_url

        from app.services.websocket_manager import create_connection_manager

        manager = create_connection_manager()

    # Registrar operadores localmente
    operator_websockets = {}
    for user_id in user_ids:
        mock_ws = create_mock_websocket(user_id)
        operator_websockets[user_id] = mock_ws
        async with manager._lock:
            if user_id not in manager.operator_connections:
                manager.operator_connections[user_id] = set()
            manager.operator_connections[user_id].add(mock_ws)

    # Crear mock de BD que retorne los usuarios de la organización
    mock_db = create_mock_db()
    mock_users = []
    for user_id in user_ids:
        mock_user = MagicMock()
        mock_user.id = user_id
        mock_users.append(mock_user)

    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.all.return_value = mock_users
    mock_query.filter_by.return_value = mock_filter
    mock_db.query.return_value = mock_query

    # Broadcast — debe funcionar sin Redis, consultando BD para obtener usuarios
    await manager.broadcast_to_organization(org_id, message, mock_db)

    # Verificar que TODOS los operadores conectados recibieron el mensaje
    for user_id in user_ids:
        operator_websockets[user_id].send_json.assert_called_once_with(message), (
            f"Operador '{user_id}' debería haber recibido el broadcast "
            f"en modo in-memory"
        )


# === PROPERTY TESTS: IN-MEMORY NO TIENE ATRIBUTOS REDIS ===


@hypothesis_settings(max_examples=150, deadline=None)
@given(
    redis_url=redis_url_none_strategy,
)
async def test_in_memory_manager_has_no_redis_attributes(
    redis_url: Optional[str],
):
    """
    Propiedad: El ConnectionManager in-memory NO tiene atributos _redis,
    _pubsub, ni _redis_available que indicarían integración con Redis.

    Esto confirma que el manager opera puramente en memoria sin ningún
    intento de conexión a Redis.

    Feature: websocket-scaling-redis, Property 14: In-Memory Mode Without Redis
    **Validates: Requirements 7.3**
    """
    with patch("app.core.config.settings") as mock_settings:
        mock_settings.REDIS_URL = redis_url

        from app.services.websocket_manager import create_connection_manager

        manager = create_connection_manager()

    # El ConnectionManager in-memory NO debería tener atributos de Redis
    assert not hasattr(manager, "_redis"), (
        f"ConnectionManager in-memory no debería tener atributo '_redis', "
        f"esto indica que es un RedisConnectionManager"
    )
    assert not hasattr(manager, "_pubsub"), (
        f"ConnectionManager in-memory no debería tener atributo '_pubsub'"
    )
    assert not hasattr(manager, "_redis_available"), (
        f"ConnectionManager in-memory no debería tener atributo '_redis_available'"
    )
    assert not hasattr(manager, "_worker_registry"), (
        f"ConnectionManager in-memory no debería tener atributo '_worker_registry'"
    )


# === PROPERTY TESTS: CONNECT/DISCONNECT LIFECYCLE SIN REDIS ===


@hypothesis_settings(max_examples=150, deadline=None)
@given(
    redis_url=redis_url_none_strategy,
    ws_id=ws_id_strategy,
    org_id=org_id_strategy,
)
async def test_in_memory_connect_disconnect_lifecycle(
    redis_url: Optional[str], ws_id: str, org_id: str
):
    """
    Propiedad: El ciclo connect → disconnect en el ConnectionManager
    in-memory funciona correctamente sin depender de Redis.
    Tras connect, la workstation aparece en el estado local.
    Tras disconnect, se limpia completamente.

    Feature: websocket-scaling-redis, Property 14: In-Memory Mode Without Redis
    **Validates: Requirements 7.3**
    """
    with patch("app.core.config.settings") as mock_settings:
        mock_settings.REDIS_URL = redis_url

        from app.services.websocket_manager import create_connection_manager

        manager = create_connection_manager()

    mock_ws = create_mock_websocket(ws_id)
    mock_db = create_mock_db()

    # Parchear WorkstationService para evitar operaciones BD reales
    with patch(
        "app.services.workstation.WorkstationService",
        return_value=MagicMock(update_workstation_status=MagicMock()),
    ):
        # Connect
        await manager.connect_workstation(ws_id, mock_ws, mock_db, org_id)

        # Verificar que está registrada localmente
        assert ws_id in manager.workstation_connections, (
            f"Workstation '{ws_id}' debería estar registrada tras connect "
            f"en modo in-memory"
        )
        assert manager.org_ids.get(ws_id) == org_id, (
            f"org_id debería ser '{org_id}' tras connect"
        )

        # Disconnect
        await manager.disconnect_workstation(ws_id, mock_db, mock_ws)

        # Verificar limpieza
        assert ws_id not in manager.workstation_connections, (
            f"Workstation '{ws_id}' no debería estar registrada tras disconnect "
            f"en modo in-memory"
        )
        assert ws_id not in manager.org_ids, (
            f"org_id de '{ws_id}' debería haberse limpiado tras disconnect"
        )


# === PROPERTY TESTS: MENSAJES A WS NO CONECTADA ===


@hypothesis_settings(max_examples=150, deadline=None)
@given(
    redis_url=redis_url_none_strategy,
    ws_id=ws_id_strategy,
    message=message_strategy,
)
async def test_in_memory_send_to_disconnected_workstation_returns_false(
    redis_url: Optional[str], ws_id: str, message: dict
):
    """
    Propiedad: En modo in-memory, enviar mensaje a una workstation NO
    conectada retorna False sin error (no intenta routing via Redis).

    Feature: websocket-scaling-redis, Property 14: In-Memory Mode Without Redis
    **Validates: Requirements 7.3**
    """
    with patch("app.core.config.settings") as mock_settings:
        mock_settings.REDIS_URL = redis_url

        from app.services.websocket_manager import create_connection_manager

        manager = create_connection_manager()

    # Intentar enviar a workstation que NO está conectada
    result = await manager.send_to_workstation(ws_id, message)

    # Debería retornar False (no conectada) sin intentar Redis
    assert result is False, (
        f"send_to_workstation a workstation no conectada debería retornar False "
        f"en modo in-memory, pero retornó {result}"
    )
