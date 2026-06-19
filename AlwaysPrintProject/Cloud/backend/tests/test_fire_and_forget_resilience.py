# Feature: redis-pubsub-channel-consolidation, Property 15: Fire-and-forget resilience
"""
Property test: Fire-and-forget resilience

Para cualquier operación fire-and-forget de Redis (WorkerRegistry SADD, lazy SUBSCRIBE)
que lance una excepción durante connect_workstation, la workstation DEBE permanecer en
`workstation_connections` y el estado local NO DEBE verse afectado.

Se verifica que tras ejecutar _fire_and_forget_connect con excepciones aleatorias:
1. workstation_id permanece en workstation_connections
2. org_ids[workstation_id] es correcto
3. _ws_vlan_ids[workstation_id] es correcto
4. last_pong[workstation_id] existe
5. last_activity[workstation_id] existe
6. _org_ws_count[org_id] > 0

Feature: redis-pubsub-channel-consolidation, Property 15: Fire-and-forget resilience
**Validates: Requirements 6.3**
"""

from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock

import pytest
from hypothesis import given, settings as hypothesis_settings, HealthCheck
from hypothesis import strategies as st

from app.services.redis_connection_manager import RedisConnectionManager


# === ESTRATEGIAS DE GENERACIÓN ===

ws_id_strategy = st.uuids().map(str)
org_id_strategy = st.uuids().map(str)
vlan_id_strategy = st.one_of(st.none(), st.uuids().map(str))

# Tipos de excepción que Redis puede lanzar en SADD/SUBSCRIBE
redis_exception_strategy = st.sampled_from([
    ConnectionError("Redis connection refused"),
    TimeoutError("Redis operation timed out"),
    OSError("Network unreachable"),
    ConnectionError("Connection reset by peer"),
    TimeoutError("Timeout waiting for Redis response"),
    OSError("Broken pipe"),
])


# === HELPERS ===


def setup_manager_with_local_state(
    ws_id: str,
    org_id: str,
    vlan_id: Optional[str],
    exception: Exception,
) -> RedisConnectionManager:
    """
    Crea un RedisConnectionManager simulando el hot path síncrono de
    connect_workstation (registra estado local), con Redis mocks que lanzan
    excepciones en SADD/SUBSCRIBE para simular fallos fire-and-forget.
    """
    manager = RedisConnectionManager(redis_url="redis://fake:6379/0")
    manager._redis_available = True

    # Simular hot path síncrono
    mock_ws = AsyncMock()
    mock_ws.send_json = AsyncMock()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    manager.workstation_connections[ws_id] = mock_ws
    manager.org_ids[ws_id] = org_id
    manager._ws_vlan_ids[ws_id] = vlan_id
    manager.last_pong[ws_id] = now
    manager.last_activity[ws_id] = now
    manager._org_ws_count[org_id] = manager._org_ws_count.get(org_id, 0) + 1

    # Configurar Redis mocks que fallan
    mock_redis = AsyncMock()
    mock_redis.publish = AsyncMock(side_effect=exception)
    manager._redis = mock_redis

    mock_pubsub = AsyncMock()
    mock_pubsub.subscribe = AsyncMock(side_effect=exception)
    mock_pubsub.unsubscribe = AsyncMock(side_effect=exception)
    manager._pubsub = mock_pubsub

    mock_registry = AsyncMock()
    mock_registry.register_workstation = AsyncMock(side_effect=exception)
    mock_registry.unregister_workstation = AsyncMock(side_effect=exception)
    manager._worker_registry = mock_registry

    return manager


# === PROPERTY TEST ===


@hypothesis_settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    ws_id=ws_id_strategy,
    org_id=org_id_strategy,
    vlan_id=vlan_id_strategy,
    exception=redis_exception_strategy,
)
async def test_fire_and_forget_resilience_all_invariants(
    ws_id: str, org_id: str, vlan_id: Optional[str], exception: Exception
):
    """
    Propiedad: Para cualquier operación fire-and-forget de Redis que lance
    una excepción (ConnectionError, TimeoutError, OSError) durante
    connect_workstation, la workstation permanece en workstation_connections
    y TODO el estado local queda intacto.

    Verifica las 6 invariantes simultáneamente:
    1. workstation_id en workstation_connections
    2. org_ids[workstation_id] == organization_id original
    3. _ws_vlan_ids[workstation_id] == vlan_id original
    4. last_pong[workstation_id] existe y es datetime
    5. last_activity[workstation_id] existe y es datetime
    6. _org_ws_count[org_id] > 0

    El método _fire_and_forget_connect envuelve las operaciones Redis en
    try/except, capturando excepciones sin propagarlas ni afectar el estado
    que fue establecido previamente en el hot path síncrono.

    Feature: redis-pubsub-channel-consolidation, Property 15: Fire-and-forget resilience
    **Validates: Requirements 6.3**
    """
    manager = setup_manager_with_local_state(ws_id, org_id, vlan_id, exception)

    # Ejecutar _fire_and_forget_connect directamente
    # (simula lo que asyncio.create_task lanza tras el hot path)
    is_first_of_org = manager._org_ws_count[org_id] == 1
    await manager._fire_and_forget_connect(ws_id, org_id, is_first_of_org)

    # === Invariante 1: workstation_id en workstation_connections ===
    assert ws_id in manager.workstation_connections, (
        f"[Invariante 1] workstation_connections no contiene '{ws_id}' "
        f"tras excepción '{type(exception).__name__}: {exception}'"
    )

    # === Invariante 2: org_ids correcto ===
    assert manager.org_ids.get(ws_id) == org_id, (
        f"[Invariante 2] org_ids['{ws_id}'] = '{manager.org_ids.get(ws_id)}' "
        f"esperado '{org_id}'"
    )

    # === Invariante 3: _ws_vlan_ids correcto ===
    assert manager._ws_vlan_ids.get(ws_id) == vlan_id, (
        f"[Invariante 3] _ws_vlan_ids['{ws_id}'] = '{manager._ws_vlan_ids.get(ws_id)}' "
        f"esperado '{vlan_id}'"
    )

    # === Invariante 4: last_pong existe ===
    assert ws_id in manager.last_pong, (
        f"[Invariante 4] last_pong no contiene '{ws_id}'"
    )
    assert isinstance(manager.last_pong[ws_id], datetime), (
        f"[Invariante 4] last_pong['{ws_id}'] debería ser datetime, "
        f"fue {type(manager.last_pong[ws_id])}"
    )

    # === Invariante 5: last_activity existe ===
    assert ws_id in manager.last_activity, (
        f"[Invariante 5] last_activity no contiene '{ws_id}'"
    )
    assert isinstance(manager.last_activity[ws_id], datetime), (
        f"[Invariante 5] last_activity['{ws_id}'] debería ser datetime, "
        f"fue {type(manager.last_activity[ws_id])}"
    )

    # === Invariante 6: _org_ws_count > 0 ===
    assert manager._org_ws_count.get(org_id, 0) > 0, (
        f"[Invariante 6] _org_ws_count['{org_id}'] = "
        f"{manager._org_ws_count.get(org_id, 0)}, esperado > 0"
    )
