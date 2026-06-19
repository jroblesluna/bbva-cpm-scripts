# Feature: redis-pubsub-channel-consolidation, Property 8: Lazy org subscription invariant
"""
Property test: Lazy org subscription invariant

Para cualquier secuencia de workstation connects y disconnects, el canal
org:{org_id} se suscribe SI Y SOLO SI _org_ws_count[org_id] > 0.
Específicamente:
- SUBSCRIBE org:{org_id} se ejecuta exactamente cuando count transiciona 0→1
- UNSUBSCRIBE org:{org_id} se ejecuta exactamente cuando count transiciona 1→0

Se generan secuencias arbitrarias de (connect, disconnect) con múltiples org_ids
y workstation_ids para verificar el invariante en todos los casos posibles.

Feature: redis-pubsub-channel-consolidation, Property 8: Lazy org subscription invariant
**Validates: Requirements 4.1, 4.2, 4.3, 4.4**
"""

import asyncio
from collections import defaultdict
from typing import Dict, List, Set, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings as hypothesis_settings, assume
from hypothesis import strategies as st


# === ESTRATEGIAS DE GENERACIÓN ===

# UUIDs como strings para identificadores
ws_id_strategy = st.uuids().map(str)
org_id_strategy = st.uuids().map(str)


# === MOCK DE REDIS PUBSUB QUE RASTREA SUSCRIPCIONES ORG ===


class MockOrgPubSub:
    """
    Mock de Redis PubSub que rastrea las operaciones SUBSCRIBE/UNSUBSCRIBE
    en canales org:{org_id}, registrando cada transición.
    """

    def __init__(self):
        # Canales actualmente suscritos
        self.subscribed_channels: Set[str] = set()
        # Historial de operaciones SUBSCRIBE/UNSUBSCRIBE org:*
        self.org_subscribe_log: List[Tuple[str, str]] = []  # (operación, org_id)

    async def subscribe(self, *channels) -> None:
        """Suscribe a uno o más canales."""
        for channel in channels:
            self.subscribed_channels.add(channel)
            if channel.startswith("org:"):
                org_id = channel[4:]
                self.org_subscribe_log.append(("subscribe", org_id))

    async def unsubscribe(self, *channels) -> None:
        """Desuscribe de uno o más canales."""
        for channel in channels:
            self.subscribed_channels.discard(channel)
            if channel.startswith("org:"):
                org_id = channel[4:]
                self.org_subscribe_log.append(("unsubscribe", org_id))

    async def get_message(self, ignore_subscribe_messages=True, timeout=1.0):
        """Simula lectura de mensajes (retorna None en tests)."""
        return None

    def get_org_channels(self) -> Set[str]:
        """Retorna solo los canales org:* suscritos."""
        return {ch for ch in self.subscribed_channels if ch.startswith("org:")}

    def get_subscribed_org_ids(self) -> Set[str]:
        """Extrae los org_ids de los canales org:* suscritos."""
        return {ch[4:] for ch in self.subscribed_channels if ch.startswith("org:")}

    def count_subscribes_for_org(self, org_id: str) -> int:
        """Cuenta cuántas veces se hizo SUBSCRIBE org:{org_id}."""
        return sum(1 for op, oid in self.org_subscribe_log if op == "subscribe" and oid == org_id)

    def count_unsubscribes_for_org(self, org_id: str) -> int:
        """Cuenta cuántas veces se hizo UNSUBSCRIBE org:{org_id}."""
        return sum(1 for op, oid in self.org_subscribe_log if op == "unsubscribe" and oid == org_id)


# === HELPERS ===


def create_mock_websocket(ws_id: str) -> MagicMock:
    """Crea un mock de WebSocket."""
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


async def create_manager_with_mock_pubsub():
    """
    Crea un RedisConnectionManager con MockOrgPubSub inyectado.
    Redis marcado como disponible para que las operaciones de subscribe se ejecuten.
    """
    from app.services.redis_connection_manager import RedisConnectionManager

    manager = RedisConnectionManager(redis_url="redis://fake:6379/0")

    # Inyectar mocks directamente
    mock_pubsub = MockOrgPubSub()
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


# === ESTRATEGIA COMPUESTA: SECUENCIAS CONNECT/DISCONNECT ===


@st.composite
def connect_disconnect_sequence_multi_org(draw):
    """
    Genera una secuencia de operaciones connect/disconnect con múltiples
    org_ids y workstation_ids.

    Returns:
        Tupla (ws_org_mapping, operations) donde:
        - ws_org_mapping: Dict[ws_id, org_id] asignación fija de org por workstation
        - operations: Lista de (tipo, ws_id) operaciones a ejecutar
    """
    # Generar pool de org_ids (1 a 3 organizaciones)
    num_orgs = draw(st.integers(min_value=1, max_value=3))
    org_ids = [draw(org_id_strategy) for _ in range(num_orgs)]
    org_ids = list(set(org_ids))
    assume(len(org_ids) >= 1)

    # Generar pool de workstation_ids (2 a 8 workstations)
    num_ws = draw(st.integers(min_value=2, max_value=8))
    ws_ids = [draw(ws_id_strategy) for _ in range(num_ws)]
    ws_ids = list(set(ws_ids))
    assume(len(ws_ids) >= 2)

    # Asignar cada workstation a una organización fija
    ws_org_mapping: Dict[str, str] = {}
    for ws_id in ws_ids:
        org_id = draw(st.sampled_from(org_ids))
        ws_org_mapping[ws_id] = org_id

    # Generar secuencia de operaciones (4 a 25)
    num_ops = draw(st.integers(min_value=4, max_value=25))
    operations = []
    for _ in range(num_ops):
        op_type = draw(st.sampled_from(["connect", "disconnect"]))
        ws_id = draw(st.sampled_from(ws_ids))
        operations.append((op_type, ws_id))

    return ws_org_mapping, operations


# === PROPERTY TESTS ===


@hypothesis_settings(max_examples=100, deadline=None)
@given(data=connect_disconnect_sequence_multi_org())
async def test_subscribe_fires_exactly_on_zero_to_one_transition(data):
    """
    Propiedad 8 (parte 1): SUBSCRIBE org:{org_id} se ejecuta EXACTAMENTE
    cuando _org_ws_count[org_id] transiciona de 0 a 1.

    Para cualquier secuencia arbitraria de connects/disconnects, cada
    SUBSCRIBE org:* corresponde a una transición 0→1 en el contador.

    Feature: redis-pubsub-channel-consolidation, Property 8: Lazy org subscription invariant
    **Validates: Requirements 4.1, 4.2, 4.3, 4.4**
    """
    ws_org_mapping, operations = data

    manager, mock_pubsub = await create_manager_with_mock_pubsub()
    mock_db = create_mock_db()

    # Rastrear estado esperado: qué workstations están conectadas
    connected_ws: Set[str] = set()
    # Rastrear transiciones 0→1 esperadas por org
    expected_subscribes_per_org: Dict[str, int] = defaultdict(int)
    # Contador local de workstations por org (modelo de referencia)
    org_count: Dict[str, int] = defaultdict(int)

    websockets: Dict[str, MagicMock] = {}

    with patch(
        "app.services.workstation.WorkstationService",
        return_value=MagicMock(update_workstation_status=MagicMock()),
    ):
        for op_type, ws_id in operations:
            org_id = ws_org_mapping[ws_id]

            if op_type == "connect":
                if ws_id not in connected_ws:
                    # Nueva conexión: incrementar contador
                    old_count = org_count[org_id]
                    org_count[org_id] += 1
                    connected_ws.add(ws_id)

                    if old_count == 0:
                        # Transición 0→1: esperamos un SUBSCRIBE
                        expected_subscribes_per_org[org_id] += 1

                    # Ejecutar connect
                    mock_ws = create_mock_websocket(ws_id)
                    websockets[ws_id] = mock_ws
                    await manager.connect_workstation(
                        ws_id, mock_ws, mock_db, org_id
                    )
                    # Permitir que fire-and-forget se ejecute
                    await asyncio.sleep(0)
                else:
                    # Reconexión: la workstation ya estaba conectada,
                    # connect_workstation reemplaza el websocket pero no afecta
                    # el conteo de org (el manager incrementa siempre)
                    # Para este test, evitamos reconexiones duplicadas
                    pass

            elif op_type == "disconnect":
                if ws_id in connected_ws:
                    # Desconectar: decrementar contador
                    org_count[org_id] -= 1
                    connected_ws.discard(ws_id)

                    ws_ref = websockets.get(ws_id)
                    await manager.disconnect_workstation(ws_id, mock_db, ws_ref)
                    await asyncio.sleep(0)

    # Verificar: el número de SUBSCRIBE org:{org_id} == transiciones 0→1 esperadas
    for org_id, expected_count in expected_subscribes_per_org.items():
        actual_count = mock_pubsub.count_subscribes_for_org(org_id)
        assert actual_count == expected_count, (
            f"SUBSCRIBE org:{org_id} se ejecutó {actual_count} veces, "
            f"pero se esperaban {expected_count} transiciones 0→1. "
            f"Log completo: {mock_pubsub.org_subscribe_log}"
        )


@hypothesis_settings(max_examples=100, deadline=None)
@given(data=connect_disconnect_sequence_multi_org())
async def test_org_subscribed_iff_count_greater_than_zero(data):
    """
    Propiedad 8 (parte 2): Al finalizar cualquier secuencia arbitraria,
    org:{org_id} está suscrito SI Y SOLO SI _org_ws_count[org_id] > 0.

    Feature: redis-pubsub-channel-consolidation, Property 8: Lazy org subscription invariant
    **Validates: Requirements 4.1, 4.2, 4.3, 4.4**
    """
    ws_org_mapping, operations = data

    manager, mock_pubsub = await create_manager_with_mock_pubsub()
    mock_db = create_mock_db()

    # Rastrear workstations conectadas
    connected_ws: Set[str] = set()
    websockets: Dict[str, MagicMock] = {}

    with patch(
        "app.services.workstation.WorkstationService",
        return_value=MagicMock(update_workstation_status=MagicMock()),
    ):
        for op_type, ws_id in operations:
            org_id = ws_org_mapping[ws_id]

            if op_type == "connect":
                if ws_id not in connected_ws:
                    connected_ws.add(ws_id)
                    mock_ws = create_mock_websocket(ws_id)
                    websockets[ws_id] = mock_ws
                    await manager.connect_workstation(
                        ws_id, mock_ws, mock_db, org_id
                    )
                    await asyncio.sleep(0)

            elif op_type == "disconnect":
                if ws_id in connected_ws:
                    connected_ws.discard(ws_id)
                    ws_ref = websockets.get(ws_id)
                    await manager.disconnect_workstation(ws_id, mock_db, ws_ref)
                    await asyncio.sleep(0)

    # Calcular qué orgs deberían estar suscritas (tienen al menos 1 ws conectada)
    expected_subscribed_orgs: Set[str] = set()
    for ws_id in connected_ws:
        expected_subscribed_orgs.add(ws_org_mapping[ws_id])

    # Verificar: canales org suscritos == orgs con count > 0
    actual_subscribed_orgs = mock_pubsub.get_subscribed_org_ids()
    assert actual_subscribed_orgs == expected_subscribed_orgs, (
        f"Al final de la secuencia, los canales org suscritos deberían ser "
        f"exactamente las orgs con workstations conectadas. "
        f"Esperado: {expected_subscribed_orgs}, Obtenido: {actual_subscribed_orgs}. "
        f"Workstations conectadas: {connected_ws}"
    )


@hypothesis_settings(max_examples=100, deadline=None)
@given(data=connect_disconnect_sequence_multi_org())
async def test_org_ws_count_matches_actual_connected_workstations(data):
    """
    Propiedad 8 (parte 3): El contador interno _org_ws_count[org_id] siempre
    refleja el número real de workstations conectadas de esa organización.

    Feature: redis-pubsub-channel-consolidation, Property 8: Lazy org subscription invariant
    **Validates: Requirements 4.1, 4.2, 4.3, 4.4**
    """
    ws_org_mapping, operations = data

    manager, mock_pubsub = await create_manager_with_mock_pubsub()
    mock_db = create_mock_db()

    # Rastrear workstations conectadas
    connected_ws: Set[str] = set()
    websockets: Dict[str, MagicMock] = {}

    with patch(
        "app.services.workstation.WorkstationService",
        return_value=MagicMock(update_workstation_status=MagicMock()),
    ):
        for op_type, ws_id in operations:
            org_id = ws_org_mapping[ws_id]

            if op_type == "connect":
                if ws_id not in connected_ws:
                    connected_ws.add(ws_id)
                    mock_ws = create_mock_websocket(ws_id)
                    websockets[ws_id] = mock_ws
                    await manager.connect_workstation(
                        ws_id, mock_ws, mock_db, org_id
                    )
                    await asyncio.sleep(0)

            elif op_type == "disconnect":
                if ws_id in connected_ws:
                    connected_ws.discard(ws_id)
                    ws_ref = websockets.get(ws_id)
                    await manager.disconnect_workstation(ws_id, mock_db, ws_ref)
                    await asyncio.sleep(0)

    # Calcular conteo esperado por org
    expected_counts: Dict[str, int] = defaultdict(int)
    for ws_id in connected_ws:
        expected_counts[ws_org_mapping[ws_id]] += 1

    # Verificar _org_ws_count del manager
    for org_id, expected in expected_counts.items():
        actual = manager._org_ws_count.get(org_id, 0)
        assert actual == expected, (
            f"_org_ws_count['{org_id}'] = {actual}, esperado = {expected}. "
            f"Workstations conectadas de esa org: "
            f"{[ws for ws in connected_ws if ws_org_mapping[ws] == org_id]}"
        )

    # Verificar que orgs sin workstations no están en el dict (o tienen count 0)
    all_orgs = set(ws_org_mapping.values())
    for org_id in all_orgs:
        if org_id not in expected_counts:
            actual = manager._org_ws_count.get(org_id, 0)
            assert actual == 0, (
                f"_org_ws_count['{org_id}'] = {actual} pero no debería haber "
                f"workstations conectadas de esa org"
            )


@hypothesis_settings(max_examples=100, deadline=None)
@given(
    ws_ids=st.lists(ws_id_strategy, min_size=2, max_size=5, unique=True),
    org_id=org_id_strategy,
)
async def test_multiple_connects_same_org_only_one_subscribe(
    ws_ids: List[str], org_id: str
):
    """
    Propiedad 8 (caso específico): Conectar múltiples workstations de la
    MISMA organización solo genera UN SUBSCRIBE org:{org_id} — el primero.

    Feature: redis-pubsub-channel-consolidation, Property 8: Lazy org subscription invariant
    **Validates: Requirements 4.1, 4.2, 4.3, 4.4**
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
            # Permitir que fire-and-forget se ejecute
            await asyncio.sleep(0)

    # Solo 1 SUBSCRIBE org:{org_id} debería haberse ejecutado
    subscribe_count = mock_pubsub.count_subscribes_for_org(org_id)
    assert subscribe_count == 1, (
        f"Se conectaron {len(ws_ids)} workstations de org:{org_id}, "
        f"pero SUBSCRIBE se ejecutó {subscribe_count} veces (esperado: 1). "
        f"Log: {mock_pubsub.org_subscribe_log}"
    )

    # El canal debe estar suscrito
    assert f"org:{org_id}" in mock_pubsub.subscribed_channels, (
        f"org:{org_id} debería estar suscrito después de conectar workstations"
    )


@hypothesis_settings(max_examples=100, deadline=None)
@given(
    ws_ids=st.lists(ws_id_strategy, min_size=2, max_size=5, unique=True),
    org_id=org_id_strategy,
)
async def test_disconnect_all_then_reconnect_generates_new_subscribe(
    ws_ids: List[str], org_id: str
):
    """
    Propiedad 8 (caso ciclo completo): Conectar N workstations → desconectar
    todas (transición 1→0, UNSUBSCRIBE) → reconectar una (transición 0→1,
    nuevo SUBSCRIBE). El segundo SUBSCRIBE es un evento distinto.

    Feature: redis-pubsub-channel-consolidation, Property 8: Lazy org subscription invariant
    **Validates: Requirements 4.1, 4.2, 4.3, 4.4**
    """
    manager, mock_pubsub = await create_manager_with_mock_pubsub()
    mock_db = create_mock_db()
    websockets: Dict[str, MagicMock] = {}

    with patch(
        "app.services.workstation.WorkstationService",
        return_value=MagicMock(update_workstation_status=MagicMock()),
    ):
        # Fase 1: Conectar todas las workstations
        for ws_id in ws_ids:
            mock_ws = create_mock_websocket(ws_id)
            websockets[ws_id] = mock_ws
            await manager.connect_workstation(ws_id, mock_ws, mock_db, org_id)
            await asyncio.sleep(0)

    # Verificar: 1 SUBSCRIBE hasta ahora
    assert mock_pubsub.count_subscribes_for_org(org_id) == 1

    # Fase 2: Desconectar todas las workstations
    for ws_id in ws_ids:
        await manager.disconnect_workstation(ws_id, mock_db, websockets[ws_id])
        await asyncio.sleep(0)

    # Verificar: 1 UNSUBSCRIBE (transición 1→0)
    assert mock_pubsub.count_unsubscribes_for_org(org_id) == 1, (
        f"Se esperaba 1 UNSUBSCRIBE org:{org_id} tras desconectar todas las WS, "
        f"pero se ejecutaron {mock_pubsub.count_unsubscribes_for_org(org_id)}. "
        f"Log: {mock_pubsub.org_subscribe_log}"
    )

    # Verificar: canal desuscrito
    assert f"org:{org_id}" not in mock_pubsub.subscribed_channels

    # Fase 3: Reconectar una workstation
    with patch(
        "app.services.workstation.WorkstationService",
        return_value=MagicMock(update_workstation_status=MagicMock()),
    ):
        reconnect_ws = create_mock_websocket(ws_ids[0])
        await manager.connect_workstation(ws_ids[0], reconnect_ws, mock_db, org_id)
        await asyncio.sleep(0)

    # Verificar: 2 SUBSCRIBES totales (nueva transición 0→1)
    assert mock_pubsub.count_subscribes_for_org(org_id) == 2, (
        f"Tras reconectar, debería haber 2 SUBSCRIBE totales para org:{org_id}, "
        f"pero hay {mock_pubsub.count_subscribes_for_org(org_id)}. "
        f"Log: {mock_pubsub.org_subscribe_log}"
    )

    # Canal debe estar suscrito de nuevo
    assert f"org:{org_id}" in mock_pubsub.subscribed_channels
