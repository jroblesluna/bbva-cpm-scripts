# Feature: redis-pubsub-channel-consolidation, Property: Connection Lifecycle Pub/Sub Symmetry
"""
Property test: Connection Lifecycle Pub/Sub Symmetry (Esquema Consolidado)

Para cualquier secuencia de operaciones connect_workstation/disconnect_workstation
sobre un RedisConnectionManager, se verifica que:
1. NO se suscribe/desuscribe canales `ws:{workstation_id}` (eliminados)
2. SUBSCRIBE org:{org_id} ocurre exactamente cuando _org_ws_count transiciona 0→1
3. UNSUBSCRIBE org:{org_id} ocurre exactamente cuando _org_ws_count transiciona 1→0
4. En CUALQUIER punto durante la secuencia, los canales org:* suscritos
   == organizaciones con al menos 1 workstation conectada localmente

Se generan secuencias aleatorias de connect/disconnect con workstation_ids
y organization_ids aleatorios para verificar la simetría del lifecycle.

Feature: redis-pubsub-channel-consolidation
**Validates: Requirements 1.2, 1.3, 4.1, 4.2, 4.3, 4.4**
"""

import asyncio
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings as hypothesis_settings, assume
from hypothesis import strategies as st


# === ESTRATEGIAS DE GENERACIÓN ===

# Generar UUIDs como strings para workstation_id
ws_id_strategy = st.uuids().map(str)

# Pool reducido de org_ids para forzar colisiones (múltiples ws en misma org)
org_id_strategy = st.sampled_from([
    "org-aaa-111", "org-bbb-222", "org-ccc-333", "org-ddd-444",
])


# === MOCK DE REDIS PUBSUB QUE RASTREA SUSCRIPCIONES ===


class MockPubSub:
    """
    Mock de Redis PubSub que rastrea los canales suscritos.
    Permite verificar que no se usan canales ws:{id} y que org:{id}
    sigue el patrón lazy subscribe/unsubscribe.
    """

    def __init__(self):
        # Canales actualmente suscritos
        self.subscribed_channels: Set[str] = set()
        # Historial de operaciones para debugging
        self.operations_log: List[Tuple[str, str]] = []
        # Registro específico de operaciones sobre canales ws:* (deberían ser 0)
        self.ws_channel_operations: List[Tuple[str, str]] = []

    async def subscribe(self, *channels) -> None:
        """Suscribe a uno o más canales."""
        for channel in channels:
            self.subscribed_channels.add(channel)
            self.operations_log.append(("subscribe", channel))
            if channel.startswith("ws:"):
                self.ws_channel_operations.append(("subscribe", channel))

    async def unsubscribe(self, *channels) -> None:
        """Desuscribe de uno o más canales."""
        for channel in channels:
            self.subscribed_channels.discard(channel)
            self.operations_log.append(("unsubscribe", channel))
            if channel.startswith("ws:"):
                self.ws_channel_operations.append(("unsubscribe", channel))

    async def get_message(self, ignore_subscribe_messages=True, timeout=1.0):
        """Simula lectura de mensajes (retorna None siempre en tests)."""
        return None

    def get_org_channels(self) -> Set[str]:
        """
        Retorna solo los canales de organización (org:{id}).
        """
        return {ch for ch in self.subscribed_channels if ch.startswith("org:")}

    def get_org_ids_from_channels(self) -> Set[str]:
        """
        Extrae los org_ids de los canales org:* suscritos.
        "org:abc-123" → "abc-123"
        """
        return {ch[4:] for ch in self.subscribed_channels if ch.startswith("org:")}


# === HELPERS ===


def create_mock_websocket(ws_id: str) -> AsyncMock:
    """Crea un mock de WebSocket para tests."""
    mock_ws = AsyncMock()
    mock_ws.send_json = AsyncMock()
    mock_ws.close = AsyncMock()
    mock_ws._ws_id = ws_id
    return mock_ws


def create_mock_db() -> MagicMock:
    """Crea un mock de sesión de base de datos."""
    return MagicMock()


async def create_manager_with_mock_pubsub():
    """
    Crea un RedisConnectionManager con un MockPubSub inyectado.

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
    manager._worker_id = "worker_test_12345"

    # Mock del WorkerRegistry para evitar llamadas a Redis real
    mock_registry = AsyncMock()
    mock_registry.register_workstation = AsyncMock()
    mock_registry.unregister_workstation = AsyncMock()
    manager._worker_registry = mock_registry

    return manager, mock_pubsub


# === ESTRATEGIA PARA SECUENCIAS DE OPERACIONES ===


@st.composite
def connect_disconnect_sequence(draw):
    """
    Genera una secuencia de operaciones connect/disconnect sobre
    un conjunto de workstation_ids con diferentes org_ids.

    Cada operación es una tupla (tipo, ws_id, org_id).
    """
    # Generar pool de workstation_ids disponibles (2 a 6)
    num_ws = draw(st.integers(min_value=2, max_value=6))
    ws_ids = [draw(ws_id_strategy) for _ in range(num_ws)]
    ws_ids = list(set(ws_ids))
    assume(len(ws_ids) >= 2)

    # Asignar org_id fijo por workstation
    ws_org_map = {}
    for ws_id in ws_ids:
        ws_org_map[ws_id] = draw(org_id_strategy)

    # Generar secuencia de operaciones (4 a 20)
    num_ops = draw(st.integers(min_value=4, max_value=20))
    operations = []
    for _ in range(num_ops):
        op_type = draw(st.sampled_from(["connect", "disconnect"]))
        ws_id = draw(st.sampled_from(ws_ids))
        operations.append((op_type, ws_id, ws_org_map[ws_id]))

    return ws_ids, ws_org_map, operations


# === PROPERTY TESTS ===


@hypothesis_settings(max_examples=100, deadline=None)
@given(
    ws_ids=st.lists(ws_id_strategy, min_size=1, max_size=8, unique=True),
    org_id=org_id_strategy,
)
async def test_connect_never_subscribes_ws_channel(
    ws_ids: List[str], org_id: str
):
    """
    Propiedad: Después de connect_workstation(ws_id, ...), el pubsub NO debe
    estar suscrito al canal "ws:{ws_id}". El esquema consolidado NO usa canales
    per-workstation.

    Feature: redis-pubsub-channel-consolidation
    **Validates: Requirements 1.2, 4.1**
    """
    manager, mock_pubsub = await create_manager_with_mock_pubsub()
    mock_db = create_mock_db()

    with patch(
        "app.services.workstation.WorkstationService",
        return_value=MagicMock(update_workstation_status=MagicMock()),
    ):
        for ws_id in ws_ids:
            mock_ws = create_mock_websocket(ws_id)
            await manager.connect_workstation(ws_id, mock_ws, mock_db, org_id)
            # Permitir fire-and-forget
            await asyncio.sleep(0)

    # === PROPIEDAD: nunca se suscribió a ws:{id} ===
    assert len(mock_pubsub.ws_channel_operations) == 0, (
        f"No debería haber operaciones sobre canales ws:*, pero hubo: "
        f"{mock_pubsub.ws_channel_operations}"
    )

    # Verificar que org:{org_id} SÍ se suscribió (primera transición 0→1)
    assert f"org:{org_id}" in mock_pubsub.subscribed_channels, (
        f"El canal 'org:{org_id}' debería estar suscrito (lazy subscribe) "
        f"pero no se encontró. Canales suscritos: {mock_pubsub.subscribed_channels}"
    )


@hypothesis_settings(max_examples=100, deadline=None)
@given(
    ws_ids=st.lists(ws_id_strategy, min_size=1, max_size=8, unique=True),
    org_id=org_id_strategy,
)
async def test_disconnect_never_unsubscribes_ws_channel(
    ws_ids: List[str], org_id: str
):
    """
    Propiedad: Después de disconnect_workstation(ws_id, ...), el pubsub NO debe
    haber ejecutado UNSUBSCRIBE en "ws:{ws_id}". La desuscripción solo aplica
    a canales org:{org_id} cuando el count llega a 0.

    Feature: redis-pubsub-channel-consolidation
    **Validates: Requirements 1.3, 4.2**
    """
    manager, mock_pubsub = await create_manager_with_mock_pubsub()
    mock_db = create_mock_db()

    # Conectar todas
    websockets = {}
    with patch(
        "app.services.workstation.WorkstationService",
        return_value=MagicMock(update_workstation_status=MagicMock()),
    ):
        for ws_id in ws_ids:
            mock_ws = create_mock_websocket(ws_id)
            websockets[ws_id] = mock_ws
            await manager.connect_workstation(ws_id, mock_ws, mock_db, org_id)
            await asyncio.sleep(0)

    # Desconectar todas
    for ws_id in ws_ids:
        await manager.disconnect_workstation(ws_id, mock_db, websockets[ws_id])

    # === PROPIEDAD: nunca se operó sobre canales ws:* ===
    assert len(mock_pubsub.ws_channel_operations) == 0, (
        f"No debería haber operaciones sobre canales ws:*, pero hubo: "
        f"{mock_pubsub.ws_channel_operations}"
    )

    # Verificar que org:{org_id} se desuscribió (última transición 1→0)
    assert f"org:{org_id}" not in mock_pubsub.subscribed_channels, (
        f"Después de desconectar todas las ws, el canal 'org:{org_id}' "
        f"debería estar desuscrito pero sigue presente. "
        f"Canales suscritos: {mock_pubsub.subscribed_channels}"
    )


@hypothesis_settings(max_examples=100, deadline=None)
@given(data=connect_disconnect_sequence())
async def test_org_channels_equal_active_orgs_at_all_times(data):
    """
    Propiedad: En CUALQUIER punto durante una secuencia arbitraria de
    connect/disconnect, el conjunto de canales org:* suscritos es exactamente
    igual al conjunto de org_ids que tienen al menos 1 workstation conectada.

    Nunca se usan canales ws:{id}.

    Feature: redis-pubsub-channel-consolidation
    **Validates: Requirements 4.1, 4.2, 4.3, 4.4**
    """
    ws_ids, ws_org_map, operations = data

    manager, mock_pubsub = await create_manager_with_mock_pubsub()
    mock_db = create_mock_db()

    # Rastrear estado esperado
    connected: Set[str] = set()
    websockets: Dict[str, AsyncMock] = {}

    with patch(
        "app.services.workstation.WorkstationService",
        return_value=MagicMock(update_workstation_status=MagicMock()),
    ):
        for op_type, ws_id, org_id in operations:
            if op_type == "connect" and ws_id not in connected:
                mock_ws = create_mock_websocket(ws_id)
                websockets[ws_id] = mock_ws
                await manager.connect_workstation(ws_id, mock_ws, mock_db, org_id)
                connected.add(ws_id)
                await asyncio.sleep(0)
            elif op_type == "disconnect" and ws_id in connected:
                ws_ref = websockets.get(ws_id)
                await manager.disconnect_workstation(ws_id, mock_db, ws_ref)
                connected.discard(ws_id)

            # === INVARIANTE: canales org suscritos == orgs con ws conectadas ===
            expected_orgs = {ws_org_map[ws] for ws in connected}
            actual_org_ids = mock_pubsub.get_org_ids_from_channels()
            assert actual_org_ids == expected_orgs, (
                f"INVARIANTE VIOLADO después de {op_type}('{ws_id}'): "
                f"canales org suscritos ({actual_org_ids}) != "
                f"organizaciones activas ({expected_orgs}). "
                f"Diferencia: extra={actual_org_ids - expected_orgs}, "
                f"faltantes={expected_orgs - actual_org_ids}"
            )

    # === PROPIEDAD: nunca se operó sobre canales ws:* ===
    assert len(mock_pubsub.ws_channel_operations) == 0, (
        f"No debería haber operaciones sobre canales ws:*, pero hubo: "
        f"{mock_pubsub.ws_channel_operations}"
    )


@hypothesis_settings(max_examples=100, deadline=None)
@given(
    ws_ids=st.lists(ws_id_strategy, min_size=2, max_size=6, unique=True),
    org_id=org_id_strategy,
)
async def test_reconnect_same_workstation_maintains_org_symmetry(
    ws_ids: List[str], org_id: str
):
    """
    Propiedad: Reconectar una workstation (disconnect + connect) mantiene
    la simetría org pub/sub. Si hay otras ws de la misma org, el canal
    org:{org_id} permanece suscrito durante toda la reconexión.

    Feature: redis-pubsub-channel-consolidation
    **Validates: Requirements 4.1, 4.2, 4.3, 4.4**
    """
    manager, mock_pubsub = await create_manager_with_mock_pubsub()
    mock_db = create_mock_db()

    with patch(
        "app.services.workstation.WorkstationService",
        return_value=MagicMock(update_workstation_status=MagicMock()),
    ):
        # Conectar todas las workstations
        websockets = {}
        for ws_id in ws_ids:
            mock_ws = create_mock_websocket(ws_id)
            websockets[ws_id] = mock_ws
            await manager.connect_workstation(ws_id, mock_ws, mock_db, org_id)
            await asyncio.sleep(0)

        # org:{org_id} debe estar suscrito
        assert f"org:{org_id}" in mock_pubsub.subscribed_channels

        # Desconectar la primera ws (quedan al menos 1 más de la misma org)
        target_ws_id = ws_ids[0]
        await manager.disconnect_workstation(target_ws_id, mock_db, websockets[target_ws_id])

        # org:{org_id} debe seguir suscrito (hay más ws de la misma org)
        assert f"org:{org_id}" in mock_pubsub.subscribed_channels, (
            f"El canal 'org:{org_id}' debería seguir suscrito porque hay "
            f"otras workstations de la misma org conectadas"
        )

        # Reconectar
        new_ws = create_mock_websocket(target_ws_id)
        websockets[target_ws_id] = new_ws
        await manager.connect_workstation(target_ws_id, new_ws, mock_db, org_id)
        await asyncio.sleep(0)

        # org:{org_id} sigue suscrito
        assert f"org:{org_id}" in mock_pubsub.subscribed_channels

    # === PROPIEDAD: nunca se operó sobre canales ws:* ===
    assert len(mock_pubsub.ws_channel_operations) == 0


@hypothesis_settings(max_examples=100, deadline=None)
@given(
    ws_ids=st.lists(ws_id_strategy, min_size=1, max_size=5, unique=True),
    org_id=org_id_strategy,
)
async def test_disconnect_nonexistent_does_not_break_org_symmetry(
    ws_ids: List[str], org_id: str
):
    """
    Propiedad: Intentar desconectar una workstation que no está conectada
    no rompe la simetría org pub/sub. Es una operación no-op segura.

    Feature: redis-pubsub-channel-consolidation
    **Validates: Requirements 4.3, 4.4**
    """
    manager, mock_pubsub = await create_manager_with_mock_pubsub()
    mock_db = create_mock_db()

    with patch(
        "app.services.workstation.WorkstationService",
        return_value=MagicMock(update_workstation_status=MagicMock()),
    ):
        # Conectar solo la primera mitad
        connected_ids = ws_ids[: len(ws_ids) // 2 + 1]
        for ws_id in connected_ids:
            mock_ws = create_mock_websocket(ws_id)
            await manager.connect_workstation(ws_id, mock_ws, mock_db, org_id)
            await asyncio.sleep(0)

    # Intentar desconectar workstations que NO están conectadas
    not_connected_ids = ws_ids[len(ws_ids) // 2 + 1:]
    for ws_id in not_connected_ids:
        await manager.disconnect_workstation(ws_id, mock_db, None)

    # org:{org_id} debe seguir suscrito (hay ws conectadas)
    assert f"org:{org_id}" in mock_pubsub.subscribed_channels, (
        f"Desconectar workstations no conectadas no debería alterar los canales org. "
        f"'org:{org_id}' debería seguir suscrito."
    )

    # === PROPIEDAD: nunca se operó sobre canales ws:* ===
    assert len(mock_pubsub.ws_channel_operations) == 0
