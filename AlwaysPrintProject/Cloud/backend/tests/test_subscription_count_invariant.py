# Feature: redis-pubsub-channel-consolidation, Property 1: Subscription count invariant
"""
Property test: Subscription count invariant

Para cualquier secuencia de operaciones connect y disconnect en una instancia
de RedisConnectionManager, el número de suscripciones Redis activas NUNCA
excede 2 + el número de organization_ids distintos con al menos una workstation
conectada localmente.

Las 2 suscripciones fijas son:
- worker:{worker_id} (suscrita durante initialize)
- global:broadcast (suscrita durante initialize)

Los canales org:{org_id} se suscriben lazy: cuando la primera WS de esa org
se conecta, y se desuscriben cuando la última WS de esa org se desconecta.

Feature: redis-pubsub-channel-consolidation, Property 1: Subscription count invariant
**Validates: Requirements 1.1**
"""

import asyncio
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings as hypothesis_settings, assume
from hypothesis import strategies as st


# === ESTRATEGIAS DE GENERACIÓN ===

ws_id_strategy = st.uuids().map(str)
org_id_strategy = st.uuids().map(str)


# === MOCK DE REDIS PUBSUB QUE RASTREA SUSCRIPCIONES ===


class MockSubCountPubSub:
    """
    Mock de Redis PubSub que rastrea TODAS las suscripciones activas
    para verificar el invariante de conteo.
    """

    def __init__(self):
        # Canales actualmente suscritos (iniciar con los 2 fijos)
        self.subscribed_channels: Set[str] = {"worker:test_worker", "global:broadcast"}
        # Historial de operaciones para debug
        self.operation_log: List[Tuple[str, str]] = []

    async def subscribe(self, *channels) -> None:
        """Suscribe a uno o más canales."""
        for channel in channels:
            self.subscribed_channels.add(channel)
            self.operation_log.append(("subscribe", channel))

    async def unsubscribe(self, *channels) -> None:
        """Desuscribe de uno o más canales."""
        for channel in channels:
            self.subscribed_channels.discard(channel)
            self.operation_log.append(("unsubscribe", channel))

    async def get_message(self, ignore_subscribe_messages=True, timeout=1.0):
        """Simula lectura de mensajes (retorna None en tests)."""
        return None


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
    Crea un RedisConnectionManager con MockSubCountPubSub inyectado.
    Los 2 canales fijos ya están en subscribed_channels (simulando initialize()).
    """
    from app.services.redis_connection_manager import RedisConnectionManager

    manager = RedisConnectionManager(redis_url="redis://fake:6379/0")

    # Inyectar mocks directamente
    mock_pubsub = MockSubCountPubSub()
    manager._redis = AsyncMock()
    manager._redis.ping = AsyncMock(return_value=True)
    manager._pubsub = mock_pubsub
    manager._redis_available = True
    manager._worker_id = "test_worker"

    # Mock del WorkerRegistry para evitar llamadas a Redis real
    mock_registry = AsyncMock()
    mock_registry.register_workstation = AsyncMock()
    mock_registry.unregister_workstation = AsyncMock()
    manager._worker_registry = mock_registry

    return manager, mock_pubsub


# === ESTRATEGIA COMPUESTA: SECUENCIAS CONNECT/DISCONNECT ===


@st.composite
def connect_disconnect_sequence(draw):
    """
    Genera una secuencia de operaciones connect/disconnect con múltiples
    org_ids y workstation_ids.

    Returns:
        Tupla (ws_org_mapping, operations) donde:
        - ws_org_mapping: Dict[ws_id, org_id] asignación fija de org por workstation
        - operations: Lista de (tipo, ws_id) operaciones a ejecutar
    """
    # Generar pool de org_ids (1 a 4 organizaciones)
    num_orgs = draw(st.integers(min_value=1, max_value=4))
    org_ids = [draw(org_id_strategy) for _ in range(num_orgs)]
    org_ids = list(set(org_ids))
    assume(len(org_ids) >= 1)

    # Generar pool de workstation_ids (2 a 10 workstations)
    num_ws = draw(st.integers(min_value=2, max_value=10))
    ws_ids = [draw(ws_id_strategy) for _ in range(num_ws)]
    ws_ids = list(set(ws_ids))
    assume(len(ws_ids) >= 2)

    # Asignar cada workstation a una organización fija
    ws_org_mapping: Dict[str, str] = {}
    for ws_id in ws_ids:
        org_id = draw(st.sampled_from(org_ids))
        ws_org_mapping[ws_id] = org_id

    # Generar secuencia de operaciones (5 a 30)
    num_ops = draw(st.integers(min_value=5, max_value=30))
    operations = []
    for _ in range(num_ops):
        op_type = draw(st.sampled_from(["connect", "disconnect"]))
        ws_id = draw(st.sampled_from(ws_ids))
        operations.append((op_type, ws_id))

    return ws_org_mapping, operations


# === PROPERTY TESTS ===


@hypothesis_settings(max_examples=100, deadline=None)
@given(data=connect_disconnect_sequence())
async def test_subscription_count_never_exceeds_limit(data):
    """
    Propiedad 1: Para cualquier secuencia de operaciones connect/disconnect,
    el número de suscripciones Redis activas NUNCA excede
    2 + N_orgs_con_al_menos_una_workstation_conectada.

    Después de CADA operación se verifica el invariante:
        len(subscribed_channels) <= 2 + active_orgs

    Feature: redis-pubsub-channel-consolidation, Property 1: Subscription count invariant
    **Validates: Requirements 1.1**
    """
    ws_org_mapping, operations = data

    manager, mock_pubsub = await create_manager_with_mock_pubsub()
    mock_db = create_mock_db()

    # Rastrear workstations conectadas (modelo de referencia)
    connected_ws: Set[str] = set()
    websockets: Dict[str, MagicMock] = {}

    with patch(
        "app.services.workstation.WorkstationService",
        return_value=MagicMock(update_workstation_status=MagicMock()),
    ):
        for i, (op_type, ws_id) in enumerate(operations):
            org_id = ws_org_mapping[ws_id]

            if op_type == "connect":
                if ws_id not in connected_ws:
                    connected_ws.add(ws_id)
                    mock_ws = create_mock_websocket(ws_id)
                    websockets[ws_id] = mock_ws
                    await manager.connect_workstation(
                        ws_id, mock_ws, mock_db, org_id
                    )
                    # Permitir que fire-and-forget se ejecute
                    await asyncio.sleep(0)

            elif op_type == "disconnect":
                if ws_id in connected_ws:
                    connected_ws.discard(ws_id)
                    ws_ref = websockets.get(ws_id)
                    await manager.disconnect_workstation(ws_id, mock_db, ws_ref)
                    await asyncio.sleep(0)

            # === VERIFICAR INVARIANTE DESPUÉS DE CADA OPERACIÓN ===
            active_orgs = sum(
                1 for count in manager._org_ws_count.values() if count > 0
            )
            total_subs = len(mock_pubsub.subscribed_channels)
            assert total_subs <= 2 + active_orgs, (
                f"Operación #{i} ({op_type}, {ws_id}): "
                f"Subscription count {total_subs} excede límite "
                f"2 + {active_orgs} = {2 + active_orgs}. "
                f"Canales suscritos: {mock_pubsub.subscribed_channels}. "
                f"_org_ws_count: {manager._org_ws_count}"
            )


@hypothesis_settings(max_examples=100, deadline=None)
@given(data=connect_disconnect_sequence())
async def test_subscription_count_equals_expected_at_end(data):
    """
    Propiedad 1 (parte 2): Al finalizar cualquier secuencia, el número
    de suscripciones activas es EXACTAMENTE 2 + N_orgs_activas.

    Esto verifica que no hay "leaks" de suscripciones (canales que
    quedan suscritos cuando ya no deberían).

    Feature: redis-pubsub-channel-consolidation, Property 1: Subscription count invariant
    **Validates: Requirements 1.1**
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

    # Calcular orgs activas esperadas
    expected_active_orgs: Set[str] = set()
    for ws_id in connected_ws:
        expected_active_orgs.add(ws_org_mapping[ws_id])

    # Verificar conteo exacto
    expected_total_subs = 2 + len(expected_active_orgs)
    actual_total_subs = len(mock_pubsub.subscribed_channels)

    assert actual_total_subs == expected_total_subs, (
        f"Al final de la secuencia, se esperaban exactamente "
        f"{expected_total_subs} suscripciones (2 fijas + {len(expected_active_orgs)} orgs), "
        f"pero hay {actual_total_subs}. "
        f"Canales suscritos: {mock_pubsub.subscribed_channels}. "
        f"Orgs esperadas: {expected_active_orgs}. "
        f"Workstations conectadas: {connected_ws}"
    )


@hypothesis_settings(max_examples=100, deadline=None)
@given(data=connect_disconnect_sequence())
async def test_subscribed_channels_are_exactly_expected_set(data):
    """
    Propiedad 1 (parte 3): Al finalizar cualquier secuencia, el SET
    de canales suscritos es exactamente {worker:{id}, global:broadcast}
    ∪ {org:{org_id} para cada org con al menos 1 WS conectada}.

    Verifica tanto el contenido como la cardinalidad.

    Feature: redis-pubsub-channel-consolidation, Property 1: Subscription count invariant
    **Validates: Requirements 1.1**
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

    # Construir el set esperado de canales
    expected_channels: Set[str] = {"worker:test_worker", "global:broadcast"}
    for ws_id in connected_ws:
        org_id = ws_org_mapping[ws_id]
        expected_channels.add(f"org:{org_id}")

    # Verificar igualdad exacta de sets
    assert mock_pubsub.subscribed_channels == expected_channels, (
        f"El set de canales suscritos no coincide con lo esperado. "
        f"Esperado: {expected_channels}. "
        f"Obtenido: {mock_pubsub.subscribed_channels}. "
        f"Diferencia (en más): {mock_pubsub.subscribed_channels - expected_channels}. "
        f"Diferencia (falta): {expected_channels - mock_pubsub.subscribed_channels}"
    )
