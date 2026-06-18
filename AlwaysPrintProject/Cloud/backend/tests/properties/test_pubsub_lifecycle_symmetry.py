# Feature: websocket-scaling-redis, Property 9: Connection Lifecycle Pub/Sub Symmetry
"""
Property test: Connection Lifecycle Pub/Sub Symmetry

Para cualquier secuencia de operaciones connect_workstation/disconnect_workstation
sobre un RedisConnectionManager, se verifica que:
1. Después de connect_workstation(ws_id, ...), el pubsub está suscrito al canal "ws:{ws_id}"
2. Después de disconnect_workstation(ws_id, ...), el pubsub NO está suscrito a "ws:{ws_id}"
3. En CUALQUIER punto durante la secuencia, el conjunto de canales suscritos de workstations
   == conjunto de workstation_ids conectados localmente

Se generan secuencias aleatorias de connect/disconnect con workstation_ids aleatorios
para verificar la simetría del lifecycle en todos los casos posibles.

Feature: websocket-scaling-redis, Property 9: Connection Lifecycle Pub/Sub Symmetry
**Validates: Requirements 1.9**
"""

import asyncio
from typing import Dict, List, Optional, Set, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings as hypothesis_settings, assume
from hypothesis import strategies as st


# === ESTRATEGIAS DE GENERACIÓN ===

# Generar UUIDs como strings para workstation_id
ws_id_strategy = st.uuids().map(str)

# Generar UUIDs como strings para organization_id
org_id_strategy = st.uuids().map(str)


# === MOCK DE REDIS PUBSUB QUE RASTREA SUSCRIPCIONES ===


class MockPubSub:
    """
    Mock de Redis PubSub que rastrea los canales suscritos.
    Permite verificar la simetría entre conexiones y suscripciones.
    """

    def __init__(self):
        # Canales actualmente suscritos
        self.subscribed_channels: Set[str] = set()
        # Historial de operaciones para debugging
        self.operations_log: List[Tuple[str, str]] = []

    async def subscribe(self, *channels) -> None:
        """Suscribe a uno o más canales."""
        for channel in channels:
            self.subscribed_channels.add(channel)
            self.operations_log.append(("subscribe", channel))

    async def unsubscribe(self, *channels) -> None:
        """Desuscribe de uno o más canales."""
        for channel in channels:
            self.subscribed_channels.discard(channel)
            self.operations_log.append(("unsubscribe", channel))

    async def get_message(self, ignore_subscribe_messages=True, timeout=1.0):
        """Simula lectura de mensajes (retorna None siempre en tests)."""
        return None

    def get_workstation_channels(self) -> Set[str]:
        """
        Retorna solo los canales de workstation (ws:{id}).
        Excluye global:broadcast y otros canales no-workstation.
        """
        return {ch for ch in self.subscribed_channels if ch.startswith("ws:")}

    def get_workstation_ids_from_channels(self) -> Set[str]:
        """
        Extrae los workstation_ids de los canales suscritos.
        "ws:abc-123" → "abc-123"
        """
        return {ch[3:] for ch in self.subscribed_channels if ch.startswith("ws:")}


class MockRedis:
    """Mock mínimo de Redis para las operaciones que usa RedisConnectionManager."""

    def __init__(self):
        self._available = True

    async def ping(self) -> bool:
        return True

    async def publish(self, channel: str, message: str) -> int:
        return 1

    def pubsub(self) -> MockPubSub:
        return MockPubSub()


# === HELPERS PARA CREAR MOCKS ===


def create_mock_websocket(ws_id: str) -> MagicMock:
    """
    Crea un mock de WebSocket para tests.
    Cada workstation tiene su propio mock único.
    """
    mock_ws = AsyncMock()
    mock_ws.send_json = AsyncMock()
    mock_ws.close = AsyncMock()
    mock_ws._ws_id = ws_id  # Para identificación en debugging
    return mock_ws


def create_mock_db() -> MagicMock:
    """Crea un mock de sesión de base de datos."""
    mock_db = MagicMock()
    mock_db.query = MagicMock()
    mock_db.commit = MagicMock()
    return mock_db


# === ESTRATEGIA PARA SECUENCIAS DE OPERACIONES ===


@st.composite
def connect_disconnect_sequence(draw):
    """
    Genera una secuencia de operaciones connect/disconnect sobre
    un conjunto de workstation_ids generados aleatoriamente.

    Cada operación es una tupla (tipo, ws_id, org_id) donde:
    - tipo: "connect" o "disconnect"
    - ws_id: UUID de la workstation
    - org_id: UUID de la organización (para connect)
    """
    # Generar pool de workstation_ids disponibles (2 a 6)
    num_ws = draw(st.integers(min_value=2, max_value=6))
    ws_ids = [draw(ws_id_strategy) for _ in range(num_ws)]
    ws_ids = list(set(ws_ids))
    assume(len(ws_ids) >= 2)

    # Generar org_id compartido o variado
    org_id = draw(org_id_strategy)

    # Generar secuencia de operaciones (4 a 20)
    num_ops = draw(st.integers(min_value=4, max_value=20))
    operations = []
    for _ in range(num_ops):
        op_type = draw(st.sampled_from(["connect", "disconnect"]))
        ws_id = draw(st.sampled_from(ws_ids))
        operations.append((op_type, ws_id, org_id))

    return ws_ids, operations


# === SETUP HELPER PARA RedisConnectionManager ===


async def create_manager_with_mock_pubsub():
    """
    Crea un RedisConnectionManager con un MockPubSub inyectado.
    Evita la conexión real a Redis pero mantiene el tracking de suscripciones.

    Returns:
        Tupla (manager, mock_pubsub) para verificar estado.
    """
    from app.services.redis_connection_manager import RedisConnectionManager

    manager = RedisConnectionManager(redis_url="redis://fake:6379/0")

    # Inyectar mocks directamente en el estado interno
    mock_pubsub = MockPubSub()
    manager._redis = AsyncMock()
    manager._redis.ping = AsyncMock(return_value=True)
    manager._pubsub = mock_pubsub
    manager._redis_available = True

    # Mock del WorkerRegistry para evitar llamadas a Redis real
    mock_registry = AsyncMock()
    mock_registry.register_workstation = AsyncMock()
    mock_registry.unregister_workstation = AsyncMock()
    manager._worker_registry = mock_registry

    return manager, mock_pubsub


# === PROPERTY TESTS ===


@hypothesis_settings(max_examples=100, deadline=None)
@given(
    ws_ids=st.lists(ws_id_strategy, min_size=1, max_size=8, unique=True),
    org_id=org_id_strategy,
)
async def test_connect_subscribes_to_workstation_channel(
    ws_ids: List[str], org_id: str
):
    """
    Propiedad: Después de connect_workstation(ws_id, ...), el pubsub DEBE
    estar suscrito al canal "ws:{ws_id}".

    Para cada workstation conectada, existe una suscripción correspondiente
    en el Redis pub/sub.

    Feature: websocket-scaling-redis, Property 9: Connection Lifecycle Pub/Sub Symmetry
    **Validates: Requirements 1.9**
    """
    manager, mock_pubsub = await create_manager_with_mock_pubsub()
    mock_db = create_mock_db()

    # Parchear WorkstationService (importado localmente dentro de connect_workstation)
    with patch(
        "app.services.workstation.WorkstationService",
        return_value=MagicMock(update_workstation_status=MagicMock()),
    ):
        # Conectar cada workstation y verificar suscripción
        for ws_id in ws_ids:
            mock_ws = create_mock_websocket(ws_id)
            await manager.connect_workstation(ws_id, mock_ws, mock_db, org_id)

            # Verificar que el canal ws:{ws_id} está suscrito
            expected_channel = f"ws:{ws_id}"
            assert expected_channel in mock_pubsub.subscribed_channels, (
                f"Después de connect_workstation('{ws_id}'), el canal "
                f"'{expected_channel}' debería estar suscrito en el pubsub "
                f"pero no se encontró. Canales suscritos: {mock_pubsub.subscribed_channels}"
            )

    # Verificar que TODOS los canales de workstation están suscritos
    subscribed_ws_ids = mock_pubsub.get_workstation_ids_from_channels()
    assert set(ws_ids) == subscribed_ws_ids, (
        f"Los canales suscritos deberían corresponder exactamente a los ws_ids conectados. "
        f"Esperado: {set(ws_ids)}, Obtenido: {subscribed_ws_ids}"
    )


@hypothesis_settings(max_examples=100, deadline=None)
@given(
    ws_ids=st.lists(ws_id_strategy, min_size=1, max_size=8, unique=True),
    org_id=org_id_strategy,
)
async def test_disconnect_unsubscribes_from_workstation_channel(
    ws_ids: List[str], org_id: str
):
    """
    Propiedad: Después de disconnect_workstation(ws_id, ...), el pubsub NO DEBE
    estar suscrito al canal "ws:{ws_id}".

    La desuscripción debe ocurrir para cada workstation desconectada.

    Feature: websocket-scaling-redis, Property 9: Connection Lifecycle Pub/Sub Symmetry
    **Validates: Requirements 1.9**
    """
    manager, mock_pubsub = await create_manager_with_mock_pubsub()
    mock_db = create_mock_db()

    # Primero conectar todas las workstations
    websockets = {}
    with patch(
        "app.services.workstation.WorkstationService",
        return_value=MagicMock(update_workstation_status=MagicMock()),
    ):
        for ws_id in ws_ids:
            mock_ws = create_mock_websocket(ws_id)
            websockets[ws_id] = mock_ws
            await manager.connect_workstation(ws_id, mock_ws, mock_db, org_id)

    # Desconectar cada workstation y verificar desuscripción
    for ws_id in ws_ids:
        await manager.disconnect_workstation(ws_id, mock_db, websockets[ws_id])

        # Verificar que el canal ws:{ws_id} ya NO está suscrito
        expected_channel = f"ws:{ws_id}"
        assert expected_channel not in mock_pubsub.subscribed_channels, (
            f"Después de disconnect_workstation('{ws_id}'), el canal "
            f"'{expected_channel}' NO debería estar suscrito en el pubsub "
            f"pero sigue presente. Canales suscritos: {mock_pubsub.subscribed_channels}"
        )

    # Verificar que no quedan canales de workstation suscritos
    remaining_ws_channels = mock_pubsub.get_workstation_channels()
    assert len(remaining_ws_channels) == 0, (
        f"Después de desconectar todas las workstations, no deberían quedar "
        f"canales ws:* suscritos pero quedan: {remaining_ws_channels}"
    )


@hypothesis_settings(max_examples=100, deadline=None)
@given(data=connect_disconnect_sequence())
async def test_subscribed_channels_equal_connected_workstations_at_all_times(data):
    """
    Propiedad: En CUALQUIER punto durante una secuencia arbitraria de
    connect/disconnect, el conjunto de canales workstation suscritos en el pubsub
    es exactamente igual al conjunto de workstation_ids conectados localmente.

    Esta es la propiedad principal de simetría lifecycle: los canales suscritos
    siempre reflejan el estado real de las conexiones locales.

    Feature: websocket-scaling-redis, Property 9: Connection Lifecycle Pub/Sub Symmetry
    **Validates: Requirements 1.9**
    """
    ws_ids, operations = data

    manager, mock_pubsub = await create_manager_with_mock_pubsub()
    mock_db = create_mock_db()

    # Rastrear estado esperado localmente
    expected_connected: Set[str] = set()
    # Mantener referencia al WebSocket mock por ws_id
    websockets: Dict[str, MagicMock] = {}

    with patch(
        "app.services.workstation.WorkstationService",
        return_value=MagicMock(update_workstation_status=MagicMock()),
    ):
        # Ejecutar secuencia de operaciones verificando invariante en cada paso
        for op_type, ws_id, org_id in operations:
            if op_type == "connect":
                mock_ws = create_mock_websocket(ws_id)
                websockets[ws_id] = mock_ws
                await manager.connect_workstation(ws_id, mock_ws, mock_db, org_id)
                expected_connected.add(ws_id)
            else:  # disconnect
                if ws_id in expected_connected:
                    ws_ref = websockets.get(ws_id)
                    await manager.disconnect_workstation(ws_id, mock_db, ws_ref)
                    expected_connected.discard(ws_id)
                # Si no está conectado, disconnect es no-op (no afecta el invariante)

            # === INVARIANTE PRINCIPAL ===
            # Los canales ws:* suscritos deben ser exactamente los ws_ids conectados
            subscribed_ws_ids = mock_pubsub.get_workstation_ids_from_channels()
            assert subscribed_ws_ids == expected_connected, (
                f"INVARIANTE VIOLADO después de {op_type}('{ws_id}'): "
                f"canales suscritos ({subscribed_ws_ids}) != "
                f"workstations conectadas ({expected_connected}). "
                f"Diferencia: suscritos_extra={subscribed_ws_ids - expected_connected}, "
                f"faltantes={expected_connected - subscribed_ws_ids}"
            )


@hypothesis_settings(max_examples=100, deadline=None)
@given(
    ws_ids=st.lists(ws_id_strategy, min_size=2, max_size=6, unique=True),
    org_id=org_id_strategy,
)
async def test_reconnect_same_workstation_maintains_symmetry(
    ws_ids: List[str], org_id: str
):
    """
    Propiedad: Reconectar una workstation (disconnect + connect) mantiene
    la simetría pub/sub. El canal se desuscribe y se re-suscribe correctamente.

    Esto es importante para el caso de reconexión donde la misma workstation
    vuelve a conectarse (posiblemente a otro worker).

    Feature: websocket-scaling-redis, Property 9: Connection Lifecycle Pub/Sub Symmetry
    **Validates: Requirements 1.9**
    """
    manager, mock_pubsub = await create_manager_with_mock_pubsub()
    mock_db = create_mock_db()

    with patch(
        "app.services.workstation.WorkstationService",
        return_value=MagicMock(update_workstation_status=MagicMock()),
    ):
        # Conectar todas las workstations inicialmente
        websockets = {}
        for ws_id in ws_ids:
            mock_ws = create_mock_websocket(ws_id)
            websockets[ws_id] = mock_ws
            await manager.connect_workstation(ws_id, mock_ws, mock_db, org_id)

        # Reconectar la primera workstation (disconnect + connect con nuevo websocket)
        target_ws_id = ws_ids[0]
        old_ws = websockets[target_ws_id]
        await manager.disconnect_workstation(target_ws_id, mock_db, old_ws)

        # Verificar que el canal se desuscribió
        assert f"ws:{target_ws_id}" not in mock_pubsub.subscribed_channels, (
            f"Después de disconnect, el canal 'ws:{target_ws_id}' debería estar "
            f"desuscrito pero sigue presente"
        )

        # Reconectar con nuevo WebSocket
        new_ws = create_mock_websocket(target_ws_id)
        websockets[target_ws_id] = new_ws
        await manager.connect_workstation(target_ws_id, new_ws, mock_db, org_id)

        # Verificar que el canal se re-suscribió
        assert f"ws:{target_ws_id}" in mock_pubsub.subscribed_channels, (
            f"Después de reconectar, el canal 'ws:{target_ws_id}' debería estar "
            f"suscrito nuevamente pero no se encontró"
        )

        # Verificar invariante global: canales == conexiones locales
        subscribed_ws_ids = mock_pubsub.get_workstation_ids_from_channels()
        assert subscribed_ws_ids == set(ws_ids), (
            f"Después de reconectar, los canales suscritos deberían corresponder "
            f"a todas las workstations conectadas. "
            f"Esperado: {set(ws_ids)}, Obtenido: {subscribed_ws_ids}"
        )


@hypothesis_settings(max_examples=100, deadline=None)
@given(
    ws_ids=st.lists(ws_id_strategy, min_size=1, max_size=5, unique=True),
    org_id=org_id_strategy,
)
async def test_disconnect_nonexistent_does_not_break_symmetry(
    ws_ids: List[str], org_id: str
):
    """
    Propiedad: Intentar desconectar una workstation que no está conectada
    no rompe la simetría pub/sub. Es una operación no-op segura.

    Feature: websocket-scaling-redis, Property 9: Connection Lifecycle Pub/Sub Symmetry
    **Validates: Requirements 1.9**
    """
    manager, mock_pubsub = await create_manager_with_mock_pubsub()
    mock_db = create_mock_db()

    with patch(
        "app.services.workstation.WorkstationService",
        return_value=MagicMock(update_workstation_status=MagicMock()),
    ):
        # Conectar solo la primera mitad de las workstations
        connected_ids = ws_ids[: len(ws_ids) // 2 + 1]
        for ws_id in connected_ids:
            mock_ws = create_mock_websocket(ws_id)
            await manager.connect_workstation(ws_id, mock_ws, mock_db, org_id)

    # Intentar desconectar workstations que NO están conectadas
    not_connected_ids = ws_ids[len(ws_ids) // 2 + 1:]
    for ws_id in not_connected_ids:
        # No debería causar error ni alterar las suscripciones
        await manager.disconnect_workstation(ws_id, mock_db, None)

    # Verificar que la simetría se mantiene intacta
    subscribed_ws_ids = mock_pubsub.get_workstation_ids_from_channels()
    assert subscribed_ws_ids == set(connected_ids), (
        f"Desconectar workstations no conectadas no debería alterar los canales. "
        f"Esperado: {set(connected_ids)}, Obtenido: {subscribed_ws_ids}"
    )
