# Feature: websocket-scaling-redis, Property 8: Graceful Fallback When Redis Unavailable
"""
Property test: Graceful Fallback When Redis Unavailable

Para cualquier operación (envío de mensajes a workstation local, consulta de datos
de registro via RegistrationCache, connect/disconnect/broadcast) cuando Redis es
inalcanzable, el sistema DEBE completar la operación sin lanzar excepciones al cliente:
1. send_to_workstation a una workstation LOCAL completa sin error (entrega directa)
2. RegistrationCache hace fallback a PostgreSQL sin error
3. connect/disconnect/broadcast completan sin lanzar excepciones
4. El sistema opera en modo degradado pero no crashea

Se prueban escenarios con redis_url=None y con _redis_available=False.

Feature: websocket-scaling-redis, Property 8: Graceful Fallback When Redis Unavailable
**Validates: Requirements 1.7, 3.7, 4.6**
"""

import asyncio
import json
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings as hypothesis_settings, assume
from hypothesis import strategies as st


# === ESTRATEGIAS DE GENERACIÓN ===

# UUIDs como strings para identificadores
ws_id_strategy = st.uuids().map(str)
org_id_strategy = st.uuids().map(str)
vlan_id_strategy = st.uuids().map(str)

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

# Estrategia para datos de organización (simulando retorno de BD)
org_data_strategy = st.fixed_dictionaries({
    "id": org_id_strategy,
    "name": st.text(min_size=3, max_size=30),
    "is_active": st.just(True),
    "timezone": st.just("America/Lima"),
    "language": st.just("es"),
    "forced_contingency": st.booleans(),
    "public_ips": st.just([]),
})


# === HELPERS DE MOCK ===


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


async def create_manager_without_redis():
    """
    Crea un RedisConnectionManager con redis_url=None (sin Redis).
    Opera completamente en modo local.
    """
    from app.services.redis_connection_manager import RedisConnectionManager

    manager = RedisConnectionManager(redis_url=None)
    # No llamar initialize() con Redis real, solo setear estado
    manager._redis_available = False
    manager._redis = None
    manager._pubsub = None
    return manager


async def create_manager_redis_unavailable():
    """
    Crea un RedisConnectionManager donde Redis estaba disponible pero
    ahora es inalcanzable (_redis_available=False).
    Simula pérdida de conexión Redis en runtime.
    """
    from app.services.redis_connection_manager import RedisConnectionManager

    manager = RedisConnectionManager(redis_url="redis://fake:6379/0")
    # Simular que Redis se cayó: flag a False, pero redis object existe
    manager._redis_available = False
    manager._redis = AsyncMock()
    # Hacer que cualquier operación Redis lance excepción
    manager._redis.publish = AsyncMock(side_effect=ConnectionError("Redis unreachable"))
    manager._redis.get = AsyncMock(side_effect=ConnectionError("Redis unreachable"))
    manager._pubsub = None
    manager._worker_registry = None
    return manager


# === PROPERTY TESTS: SEND_TO_WORKSTATION LOCAL SIN REDIS ===


@hypothesis_settings(max_examples=100, deadline=None)
@given(
    ws_id=ws_id_strategy,
    org_id=org_id_strategy,
    message=message_strategy,
)
async def test_send_to_local_workstation_without_redis(
    ws_id: str, org_id: str, message: dict
):
    """
    Propiedad: Cuando Redis es inalcanzable, send_to_workstation a una
    workstation LOCAL entrega el mensaje directamente sin error.

    El delivery local no depende de Redis — usa el dict interno de conexiones.

    Feature: websocket-scaling-redis, Property 8: Graceful Fallback When Redis Unavailable
    **Validates: Requirements 1.7, 3.7, 4.6**
    """
    manager = await create_manager_without_redis()

    # Registrar workstation localmente (sin Redis, sin WorkerRegistry)
    mock_ws = create_mock_websocket(ws_id)
    async with manager._lock:
        manager.workstation_connections[ws_id] = mock_ws
        manager.org_ids[ws_id] = org_id

    # Enviar mensaje — NO debe lanzar excepción
    result = await manager.send_to_workstation(ws_id, message)

    # Verificar que se entregó localmente con éxito
    assert result is True, (
        f"send_to_workstation a workstation local debería retornar True "
        f"incluso sin Redis, pero retornó {result}"
    )

    # Verificar que el WebSocket recibió el mensaje
    mock_ws.send_json.assert_called_once_with(message)


@hypothesis_settings(max_examples=100, deadline=None)
@given(
    ws_id=ws_id_strategy,
    org_id=org_id_strategy,
    message=message_strategy,
)
async def test_send_to_local_workstation_with_redis_down(
    ws_id: str, org_id: str, message: dict
):
    """
    Propiedad: Cuando Redis estaba disponible pero se cayó, send_to_workstation
    a una workstation LOCAL aún entrega el mensaje directamente sin error.

    El fallback graceful prioriza entrega local sobre coordinación Redis.

    Feature: websocket-scaling-redis, Property 8: Graceful Fallback When Redis Unavailable
    **Validates: Requirements 1.7, 3.7, 4.6**
    """
    manager = await create_manager_redis_unavailable()

    # Registrar workstation localmente
    mock_ws = create_mock_websocket(ws_id)
    async with manager._lock:
        manager.workstation_connections[ws_id] = mock_ws
        manager.org_ids[ws_id] = org_id

    # Enviar mensaje — NO debe lanzar excepción
    result = await manager.send_to_workstation(ws_id, message)

    # Verificar entrega local exitosa
    assert result is True, (
        f"send_to_workstation a workstation local debería retornar True "
        f"con Redis caído, pero retornó {result}"
    )
    mock_ws.send_json.assert_called_once_with(message)


# === PROPERTY TESTS: REGISTRATION CACHE FALLBACK A POSTGRESQL ===


@hypothesis_settings(max_examples=100, deadline=None)
@given(
    org_id=org_id_strategy,
    org_data=org_data_strategy,
)
async def test_registration_cache_fallback_to_db_without_redis(
    org_id: str, org_data: dict
):
    """
    Propiedad: Cuando Redis es None, RegistrationCache hace fallback a
    PostgreSQL queries sin lanzar excepción.

    El cache opera de forma transparente — si Redis no está, consulta BD directamente.

    Feature: websocket-scaling-redis, Property 8: Graceful Fallback When Redis Unavailable
    **Validates: Requirements 1.7, 3.7, 4.6**
    """
    from app.services.registration_cache import RegistrationCache

    # Crear cache sin Redis (redis=None)
    cache = RegistrationCache(redis=None, ttl_seconds=300)

    # Mock de BD que retorna datos de organización
    mock_db = create_mock_db()
    mock_org = MagicMock()
    mock_org.id = org_id
    mock_org.name = org_data["name"]
    mock_org.is_active = org_data["is_active"]
    mock_org.timezone = org_data["timezone"]
    mock_org.language = org_data["language"]
    mock_org.auto_update_enabled = True
    mock_org.target_version = None
    mock_org.auto_reregister_enabled = False
    mock_org.forced_contingency = org_data["forced_contingency"]
    mock_org.offline_timeout_minutes = 10
    mock_org.jitter_window_seconds = 30

    # Configurar query chain para organización
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = mock_org
    mock_query.filter.return_value = mock_filter
    # Segunda llamada a query (PublicIP)
    mock_query_ips = MagicMock()
    mock_filter_ips = MagicMock()
    mock_filter_ips.all.return_value = []
    mock_query_ips.filter.return_value = mock_filter_ips
    mock_db.query.side_effect = [mock_query, mock_query_ips]

    # Ejecutar — NO debe lanzar excepción
    result = await cache.get_organization_data(org_id, mock_db)

    # Verificar que retornó datos (desde BD)
    assert result is not None, (
        "get_organization_data debería retornar datos desde BD cuando Redis=None"
    )
    assert result["id"] == org_id, (
        f"El org_id en resultado debería ser '{org_id}' pero fue '{result.get('id')}'"
    )
    assert result["name"] == org_data["name"], (
        f"El nombre debería ser '{org_data['name']}' pero fue '{result.get('name')}'"
    )


@hypothesis_settings(max_examples=100, deadline=None)
@given(
    org_id=org_id_strategy,
    org_data=org_data_strategy,
)
async def test_registration_cache_fallback_when_redis_connection_error(
    org_id: str, org_data: dict
):
    """
    Propiedad: Cuando Redis lanza ConnectionError, RegistrationCache hace
    fallback a PostgreSQL sin lanzar excepción al caller.

    El error de Redis se captura internamente y se consulta BD directamente.

    Feature: websocket-scaling-redis, Property 8: Graceful Fallback When Redis Unavailable
    **Validates: Requirements 1.7, 3.7, 4.6**
    """
    import redis.asyncio as aioredis
    from app.services.registration_cache import RegistrationCache

    # Crear Redis mock que lanza ConnectionError
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(side_effect=aioredis.ConnectionError("Redis unreachable"))

    cache = RegistrationCache(redis=mock_redis, ttl_seconds=300)

    # Mock de BD
    mock_db = create_mock_db()
    mock_org = MagicMock()
    mock_org.id = org_id
    mock_org.name = org_data["name"]
    mock_org.is_active = org_data["is_active"]
    mock_org.timezone = org_data["timezone"]
    mock_org.language = org_data["language"]
    mock_org.auto_update_enabled = True
    mock_org.target_version = None
    mock_org.auto_reregister_enabled = False
    mock_org.forced_contingency = org_data["forced_contingency"]
    mock_org.offline_timeout_minutes = 10
    mock_org.jitter_window_seconds = 30

    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = mock_org
    mock_query.filter.return_value = mock_filter
    mock_query_ips = MagicMock()
    mock_filter_ips = MagicMock()
    mock_filter_ips.all.return_value = []
    mock_query_ips.filter.return_value = mock_filter_ips
    mock_db.query.side_effect = [mock_query, mock_query_ips]

    # Ejecutar — NO debe lanzar excepción pese a Redis caído
    result = await cache.get_organization_data(org_id, mock_db)

    # Verificar fallback exitoso a BD
    assert result is not None, (
        "get_organization_data debería hacer fallback a BD cuando Redis lanza ConnectionError"
    )
    assert result["id"] == org_id


# === PROPERTY TESTS: CONNECT/DISCONNECT SIN REDIS ===


@hypothesis_settings(max_examples=100, deadline=None)
@given(
    ws_id=ws_id_strategy,
    org_id=org_id_strategy,
)
async def test_connect_workstation_without_redis_no_exception(
    ws_id: str, org_id: str
):
    """
    Propiedad: connect_workstation completa sin excepción cuando Redis no
    está disponible. La workstation se registra localmente y se marca online
    en BD, sin intentar suscripción Redis.

    Feature: websocket-scaling-redis, Property 8: Graceful Fallback When Redis Unavailable
    **Validates: Requirements 1.7, 3.7, 4.6**
    """
    manager = await create_manager_without_redis()
    mock_ws = create_mock_websocket(ws_id)
    mock_db = create_mock_db()

    # Parchear WorkstationService para evitar operaciones BD reales
    with patch(
        "app.services.workstation.WorkstationService",
        return_value=MagicMock(update_workstation_status=MagicMock()),
    ):
        # NO debe lanzar excepción
        await manager.connect_workstation(ws_id, mock_ws, mock_db, org_id)

    # Verificar registro local exitoso
    assert ws_id in manager.workstation_connections, (
        f"Workstation '{ws_id}' debería estar registrada localmente tras connect "
        f"incluso sin Redis"
    )
    assert manager.org_ids.get(ws_id) == org_id, (
        f"El org_id de la workstation debería ser '{org_id}'"
    )


@hypothesis_settings(max_examples=100, deadline=None)
@given(
    ws_id=ws_id_strategy,
    org_id=org_id_strategy,
)
async def test_disconnect_workstation_without_redis_no_exception(
    ws_id: str, org_id: str
):
    """
    Propiedad: disconnect_workstation completa sin excepción cuando Redis no
    está disponible. La workstation se elimina del estado local sin intentar
    desuscripción Redis.

    Feature: websocket-scaling-redis, Property 8: Graceful Fallback When Redis Unavailable
    **Validates: Requirements 1.7, 3.7, 4.6**
    """
    manager = await create_manager_without_redis()
    mock_ws = create_mock_websocket(ws_id)
    mock_db = create_mock_db()

    # Primero conectar localmente
    with patch(
        "app.services.workstation.WorkstationService",
        return_value=MagicMock(update_workstation_status=MagicMock()),
    ):
        await manager.connect_workstation(ws_id, mock_ws, mock_db, org_id)

    # Desconectar — NO debe lanzar excepción
    await manager.disconnect_workstation(ws_id, mock_db, mock_ws)

    # Verificar limpieza local
    assert ws_id not in manager.workstation_connections, (
        f"Workstation '{ws_id}' no debería estar en conexiones tras disconnect"
    )
    assert ws_id not in manager.org_ids, (
        f"org_id de '{ws_id}' debería haberse limpiado tras disconnect"
    )


# === PROPERTY TESTS: BROADCAST SIN REDIS ===


@hypothesis_settings(max_examples=100, deadline=None)
@given(
    ws_ids=st.lists(ws_id_strategy, min_size=1, max_size=5, unique=True),
    org_id=org_id_strategy,
    message=message_strategy,
)
async def test_broadcast_to_organization_without_redis_no_exception(
    ws_ids: List[str], org_id: str, message: dict
):
    """
    Propiedad: broadcast_to_organization completa sin excepción cuando Redis
    no está disponible. Entrega mensajes a workstations locales de la org
    sin intentar publicar en Redis.

    Feature: websocket-scaling-redis, Property 8: Graceful Fallback When Redis Unavailable
    **Validates: Requirements 1.7, 3.7, 4.6**
    """
    manager = await create_manager_without_redis()
    mock_db = create_mock_db()

    # Registrar workstations localmente (sin Redis)
    websockets = {}
    for ws_id in ws_ids:
        mock_ws = create_mock_websocket(ws_id)
        websockets[ws_id] = mock_ws
        async with manager._lock:
            manager.workstation_connections[ws_id] = mock_ws
            manager.org_ids[ws_id] = org_id

    # Broadcast — NO debe lanzar excepción
    await manager.broadcast_to_organization(org_id, message, mock_db)

    # Verificar que TODAS las workstations locales recibieron el mensaje
    for ws_id in ws_ids:
        websockets[ws_id].send_json.assert_called_once_with(message), (
            f"Workstation '{ws_id}' debería haber recibido el broadcast "
            f"incluso sin Redis"
        )


@hypothesis_settings(max_examples=100, deadline=None)
@given(
    ws_ids=st.lists(ws_id_strategy, min_size=1, max_size=5, unique=True),
    org_id=org_id_strategy,
    message=message_strategy,
)
async def test_broadcast_with_redis_down_delivers_locally(
    ws_ids: List[str], org_id: str, message: dict
):
    """
    Propiedad: Cuando Redis estaba disponible pero se cayó, broadcast_to_organization
    aún entrega a workstations locales sin error. Solo la publicación a Redis
    se omite (modo degradado).

    Feature: websocket-scaling-redis, Property 8: Graceful Fallback When Redis Unavailable
    **Validates: Requirements 1.7, 3.7, 4.6**
    """
    manager = await create_manager_redis_unavailable()
    mock_db = create_mock_db()

    # Registrar workstations localmente
    websockets = {}
    for ws_id in ws_ids:
        mock_ws = create_mock_websocket(ws_id)
        websockets[ws_id] = mock_ws
        async with manager._lock:
            manager.workstation_connections[ws_id] = mock_ws
            manager.org_ids[ws_id] = org_id

    # Broadcast — NO debe lanzar excepción
    await manager.broadcast_to_organization(org_id, message, mock_db)

    # Verificar entrega local exitosa
    for ws_id in ws_ids:
        websockets[ws_id].send_json.assert_called_once_with(message)


# === PROPERTY TESTS: GRACEFUL SHUTDOWN SIN REDIS ===


@hypothesis_settings(max_examples=100, deadline=None)
@given(
    ws_ids=st.lists(ws_id_strategy, min_size=1, max_size=5, unique=True),
    org_id=org_id_strategy,
)
async def test_graceful_shutdown_without_redis_no_exception(
    ws_ids: List[str], org_id: str
):
    """
    Propiedad: graceful_shutdown_workstations completa sin excepción cuando
    Redis no está disponible. Cierra todos los WebSockets con código 1001
    sin depender de Redis para cleanup.

    Feature: websocket-scaling-redis, Property 8: Graceful Fallback When Redis Unavailable
    **Validates: Requirements 1.7, 3.7, 4.6**
    """
    manager = await create_manager_without_redis()

    # Registrar workstations localmente
    websockets = {}
    for ws_id in ws_ids:
        mock_ws = create_mock_websocket(ws_id)
        websockets[ws_id] = mock_ws
        async with manager._lock:
            manager.workstation_connections[ws_id] = mock_ws
            manager.org_ids[ws_id] = org_id

    # Graceful shutdown — NO debe lanzar excepción
    await manager.graceful_shutdown_workstations(reason="Test shutdown")

    # Verificar que se cerraron los WebSockets con código 1001
    for ws_id in ws_ids:
        websockets[ws_id].close.assert_called_once()
        call_kwargs = websockets[ws_id].close.call_args
        # Verificar código 1001 (Going Away)
        assert call_kwargs[1]["code"] == 1001 or call_kwargs[0][0] == 1001 if call_kwargs[0] else call_kwargs[1].get("code") == 1001, (
            f"WebSocket de '{ws_id}' debería cerrarse con código 1001"
        )


# === PROPERTY TESTS: OPERACIONES COMBINADAS EN MODO DEGRADADO ===


@hypothesis_settings(max_examples=100, deadline=None)
@given(
    ws_ids=st.lists(ws_id_strategy, min_size=2, max_size=6, unique=True),
    org_id=org_id_strategy,
    messages=st.lists(message_strategy, min_size=1, max_size=3),
)
async def test_full_lifecycle_without_redis_no_exception(
    ws_ids: List[str], org_id: str, messages: List[dict]
):
    """
    Propiedad: Un ciclo completo de connect → send → broadcast → disconnect
    completa sin excepción cuando Redis no está disponible.

    El sistema opera en modo degradado (solo local) pero no crashea.

    Feature: websocket-scaling-redis, Property 8: Graceful Fallback When Redis Unavailable
    **Validates: Requirements 1.7, 3.7, 4.6**
    """
    manager = await create_manager_without_redis()
    mock_db = create_mock_db()

    with patch(
        "app.services.workstation.WorkstationService",
        return_value=MagicMock(update_workstation_status=MagicMock()),
    ):
        websockets = {}

        # Fase 1: Conectar todas las workstations (sin Redis)
        for ws_id in ws_ids:
            mock_ws = create_mock_websocket(ws_id)
            websockets[ws_id] = mock_ws
            await manager.connect_workstation(ws_id, mock_ws, mock_db, org_id)

        # Verificar que todas están conectadas localmente
        assert len(manager.workstation_connections) == len(ws_ids)

        # Fase 2: Enviar mensajes a workstations locales (sin Redis)
        for msg in messages:
            for ws_id in ws_ids:
                result = await manager.send_to_workstation(ws_id, msg)
                assert result is True, (
                    f"send_to_workstation local debería retornar True sin Redis"
                )

        # Fase 3: Broadcast a organización (sin Redis)
        for msg in messages:
            await manager.broadcast_to_organization(org_id, msg, mock_db)

        # Fase 4: Desconectar todas las workstations (sin Redis)
        for ws_id in ws_ids:
            await manager.disconnect_workstation(ws_id, mock_db, websockets[ws_id])

        # Verificar limpieza completa
        assert len(manager.workstation_connections) == 0, (
            "Todas las workstations deberían estar desconectadas tras el ciclo completo"
        )
