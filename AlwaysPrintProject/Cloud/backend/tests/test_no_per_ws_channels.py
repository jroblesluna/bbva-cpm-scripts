# Feature: redis-pubsub-channel-consolidation, Property 2: No per-workstation channel operations
"""
Property test: No per-workstation channel operations

Para cualquier secuencia de connect o disconnect de workstations, el
RedisConnectionManager NO DEBE invocar SUBSCRIBE, UNSUBSCRIBE o PUBLISH
en ningún canal que coincida con el patrón `ws:{workstation_id}`.

También verifica que `send_to_workstation` publica en `worker:{worker_id}`
y NO en `ws:{workstation_id}`.

Se verifica que tras ejecutar secuencias aleatorias de operaciones:
1. pubsub.subscribe NUNCA es invocado con un canal `ws:*`
2. pubsub.unsubscribe NUNCA es invocado con un canal `ws:*`
3. redis.publish NUNCA es invocado con un canal `ws:*`

Feature: redis-pubsub-channel-consolidation, Property 2: No per-workstation channel operations
**Validates: Requirements 1.2, 1.3, 1.4**
"""

import asyncio
from typing import List, Set
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings as hypothesis_settings, assume, HealthCheck
from hypothesis import strategies as st

from app.services.redis_connection_manager import RedisConnectionManager


# === ESTRATEGIAS DE GENERACIÓN ===

# IDs de workstation tipo UUID
workstation_id_strategy = st.uuids().map(str)

# IDs de organización (pool reducido para forzar colisiones de org)
org_id_strategy = st.sampled_from([
    "org-aaa-111", "org-bbb-222", "org-ccc-333", "org-ddd-444",
])

# IDs de VLAN opcionales
vlan_id_strategy = st.one_of(
    st.none(),
    st.sampled_from(["vlan-01", "vlan-02", "vlan-03"]),
)

# Mensajes para send_to_workstation
message_strategy = st.fixed_dictionaries({
    "type": st.sampled_from(["command", "status_request", "config_update"]),
    "data": st.text(min_size=1, max_size=20),
})


# === MOCK QUE ESPÍA CANALES ===


class SpyPubSub:
    """
    Mock de Redis PubSub que registra TODAS las llamadas a subscribe/unsubscribe
    para verificar que nunca se usa un canal ws:{id}.
    """

    def __init__(self):
        self.subscribe_calls: List[str] = []
        self.unsubscribe_calls: List[str] = []

    async def subscribe(self, *channels, **kwargs) -> None:
        self.subscribe_calls.extend(channels)

    async def unsubscribe(self, *channels, **kwargs) -> None:
        self.unsubscribe_calls.extend(channels)

    async def get_message(self, ignore_subscribe_messages=True, timeout=1.0):
        return None


# === HELPERS ===


def create_manager_with_spy():
    """
    Crea un RedisConnectionManager con SpyPubSub y mock Redis que registran
    todas las operaciones de canal.

    Returns:
        Tupla (manager, spy_pubsub, publish_calls)
    """
    manager = RedisConnectionManager(redis_url="redis://fake:6379/0")
    manager._redis_available = True
    manager._worker_id = "worker_test_12345"

    # Mock Redis con spy en publish
    publish_calls: List[str] = []
    mock_redis = AsyncMock()

    async def spy_publish(channel, message):
        publish_calls.append(channel)
        return 1

    mock_redis.publish = AsyncMock(side_effect=spy_publish)
    manager._redis = mock_redis

    # SpyPubSub
    spy_pubsub = SpyPubSub()
    manager._pubsub = spy_pubsub

    # Mock WorkerRegistry
    mock_registry = AsyncMock()
    mock_registry.register_workstation = AsyncMock()
    mock_registry.unregister_workstation = AsyncMock()
    mock_registry.find_worker_for_workstation = AsyncMock(return_value="worker_remote_99")
    manager._worker_registry = mock_registry

    return manager, spy_pubsub, publish_calls


def create_mock_websocket() -> AsyncMock:
    """Crea un mock WebSocket."""
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


def create_mock_db() -> MagicMock:
    """Crea un mock de sesión de BD."""
    return MagicMock()


def assert_no_ws_channels(
    spy_pubsub: SpyPubSub,
    publish_calls: List[str],
):
    """
    Verifica que ninguna llamada a subscribe, unsubscribe o publish
    contenga un canal con el patrón `ws:{id}`.
    """
    for channel in spy_pubsub.subscribe_calls:
        assert not str(channel).startswith("ws:"), (
            f"SUBSCRIBE invocado con canal prohibido: '{channel}'. "
            f"El esquema consolidado NO usa canales per-workstation ws:*."
        )

    for channel in spy_pubsub.unsubscribe_calls:
        assert not str(channel).startswith("ws:"), (
            f"UNSUBSCRIBE invocado con canal prohibido: '{channel}'. "
            f"El esquema consolidado NO usa canales per-workstation ws:*."
        )

    for channel in publish_calls:
        assert not str(channel).startswith("ws:"), (
            f"PUBLISH invocado con canal prohibido: '{channel}'. "
            f"Los mensajes dirigidos deben ir a worker:* no a ws:*."
        )


# === ESTRATEGIA COMPUESTA ===


@st.composite
def connect_disconnect_sequence(draw):
    """
    Genera una secuencia de operaciones connect/disconnect con workstation_ids,
    org_ids y vlan_ids aleatorios.

    Returns:
        Lista de tuplas (op, ws_id, org_id, vlan_id) donde op es "connect" o "disconnect"
    """
    # Pool de workstations (2-8)
    num_ws = draw(st.integers(min_value=2, max_value=8))
    ws_ids = list(set(draw(st.lists(workstation_id_strategy, min_size=num_ws, max_size=num_ws))))
    assume(len(ws_ids) >= 2)

    # Asignar org y vlan fijos por workstation
    ws_config = {}
    for ws_id in ws_ids:
        ws_config[ws_id] = {
            "org_id": draw(org_id_strategy),
            "vlan_id": draw(vlan_id_strategy),
        }

    # Generar secuencia de operaciones (4-20)
    num_ops = draw(st.integers(min_value=4, max_value=20))
    operations = []
    for _ in range(num_ops):
        op = draw(st.sampled_from(["connect", "disconnect"]))
        ws_id = draw(st.sampled_from(ws_ids))
        operations.append((op, ws_id, ws_config[ws_id]["org_id"], ws_config[ws_id]["vlan_id"]))

    return operations


# === TESTS ===


@hypothesis_settings(max_examples=100, deadline=None)
@given(data=connect_disconnect_sequence())
async def test_connect_disconnect_no_ws_channel_subscribe(data):
    """
    **Validates: Requirements 1.2, 1.3, 1.4**

    Para cualquier secuencia de connect/disconnect de workstations,
    NUNCA se invoca SUBSCRIBE/UNSUBSCRIBE/PUBLISH en canales ws:{workstation_id}.
    """
    operations = data
    manager, spy_pubsub, publish_calls = create_manager_with_spy()
    db = create_mock_db()

    # Estado local para trackear qué está conectado
    connected: Set[str] = set()
    websockets = {}

    with patch(
        "app.services.workstation.WorkstationService",
        return_value=MagicMock(update_workstation_status=MagicMock()),
    ):
        for op, ws_id, org_id, vlan_id in operations:
            if op == "connect" and ws_id not in connected:
                ws = create_mock_websocket()
                websockets[ws_id] = ws
                await manager.connect_workstation(
                    workstation_id=ws_id,
                    websocket=ws,
                    db=db,
                    organization_id=org_id,
                    vlan_id=vlan_id,
                )
                connected.add(ws_id)
                # Permitir fire-and-forget
                await asyncio.sleep(0)

            elif op == "disconnect" and ws_id in connected:
                ws_ref = websockets.get(ws_id)
                await manager.disconnect_workstation(
                    workstation_id=ws_id,
                    db=db,
                    websocket=ws_ref,
                )
                connected.discard(ws_id)
                await asyncio.sleep(0)

    # === PROPIEDAD PRINCIPAL: nunca se usaron canales ws:* ===
    assert_no_ws_channels(spy_pubsub, publish_calls)


@hypothesis_settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    workstation_id=workstation_id_strategy,
    org_id=org_id_strategy,
    message=message_strategy,
)
async def test_send_to_workstation_no_ws_channel_publish(
    workstation_id: str,
    org_id: str,
    message: dict,
):
    """
    **Validates: Requirements 1.2, 1.3, 1.4**

    Al enviar un mensaje a una workstation remota (no conectada localmente),
    el publish debe ir a `worker:{target_worker_id}` y NUNCA a `ws:{workstation_id}`.
    """
    manager, spy_pubsub, publish_calls = create_manager_with_spy()

    # La workstation NO está conectada localmente → debe resolver via WorkerRegistry
    result = await manager.send_to_workstation(workstation_id, message)

    # El mensaje se publicó en Redis (retorna False porque fue remoto)
    assert result is False, (
        "send_to_workstation a workstation remota debe retornar False"
    )

    # === PROPIEDAD PRINCIPAL: publish fue a worker:* y NO a ws:* ===
    assert_no_ws_channels(spy_pubsub, publish_calls)

    # Verificar que el publish fue al canal worker correcto
    assert len(publish_calls) == 1, (
        f"Se esperaba exactamente 1 publish, pero hubo {len(publish_calls)}"
    )
    assert publish_calls[0] == "worker:worker_remote_99", (
        f"El publish debe ir a 'worker:worker_remote_99', "
        f"pero fue a '{publish_calls[0]}'"
    )
