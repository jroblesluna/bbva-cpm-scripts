# Feature: redis-pubsub-channel-consolidation, Property 3: No per-command channel operations
"""
Property test: No per-command channel operations

Para cualquier secuencia de register_command_waiter, resolve_command_response
y wait_for_command_response (timeout), el RedisConnectionManager NO DEBE invocar
SUBSCRIBE o UNSUBSCRIBE en ningún canal que coincida con el patrón `cmd_response:{command_id}`.

Se verifica que tras ejecutar secuencias aleatorias de operaciones de command waiters:
1. pubsub.subscribe NUNCA es invocado con un canal `cmd_response:*`
2. pubsub.unsubscribe NUNCA es invocado con un canal `cmd_response:*`
3. Las operaciones completan correctamente sin suscripciones dinámicas

Feature: redis-pubsub-channel-consolidation, Property 3: No per-command channel operations
**Validates: Requirements 3.1, 3.4, 3.5**
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, call

import pytest
from hypothesis import given, settings as hypothesis_settings, HealthCheck
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, initialize

from app.services.redis_connection_manager import RedisConnectionManager


# === ESTRATEGIAS DE GENERACIÓN ===

# IDs de comando tipo UUID
command_id_strategy = st.uuids().map(str)

# Respuestas de comando: diccionarios con datos aleatorios
response_strategy = st.fixed_dictionaries({
    "status": st.sampled_from(["success", "error", "timeout", "partial"]),
}).map(lambda d: {**d, "data": "result"})

# Tipo de operación sobre command waiters
operation_strategy = st.sampled_from(["register", "resolve", "wait_timeout"])


# === HELPERS ===

def create_manager_with_spy_pubsub() -> tuple:
    """
    Crea un RedisConnectionManager con _redis_available=True y un mock PubSub
    que registra TODAS las llamadas a subscribe/unsubscribe para inspección.

    Returns:
        Tupla (manager, subscribe_calls, unsubscribe_calls)
    """
    manager = RedisConnectionManager(redis_url="redis://localhost:6379/0")
    manager._redis_available = True

    # Mock Redis
    mock_redis = AsyncMock()
    mock_redis.publish = AsyncMock(return_value=1)
    manager._redis = mock_redis

    # Mock PubSub con spy que registra todas las llamadas
    mock_pubsub = AsyncMock()
    subscribe_calls = []
    unsubscribe_calls = []

    async def spy_subscribe(*channels, **kwargs):
        subscribe_calls.extend(channels)

    async def spy_unsubscribe(*channels, **kwargs):
        unsubscribe_calls.extend(channels)

    mock_pubsub.subscribe = AsyncMock(side_effect=spy_subscribe)
    mock_pubsub.unsubscribe = AsyncMock(side_effect=spy_unsubscribe)
    manager._pubsub = mock_pubsub

    return manager, subscribe_calls, unsubscribe_calls


def assert_no_cmd_response_channels(subscribe_calls: list, unsubscribe_calls: list):
    """
    Verifica que ninguna llamada a subscribe o unsubscribe contenga
    un canal con el patrón `cmd_response:*`.
    """
    for channel in subscribe_calls:
        assert not str(channel).startswith("cmd_response:"), (
            f"SUBSCRIBE invocado con canal prohibido: '{channel}'. "
            f"Los command waiters NO deben crear suscripciones dinámicas."
        )

    for channel in unsubscribe_calls:
        assert not str(channel).startswith("cmd_response:"), (
            f"UNSUBSCRIBE invocado con canal prohibido: '{channel}'. "
            f"Los command waiters NO deben crear desuscripciones dinámicas."
        )


# === TESTS ===

@pytest.mark.asyncio
@hypothesis_settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    command_ids=st.lists(command_id_strategy, min_size=1, max_size=10),
    responses=st.lists(response_strategy, min_size=1, max_size=10),
)
async def test_register_then_resolve_no_subscribe(
    command_ids: list,
    responses: list,
):
    """
    **Validates: Requirements 3.1, 3.4, 3.5**

    Para cualquier secuencia de register → resolve, nunca se invoca
    SUBSCRIBE/UNSUBSCRIBE en canales cmd_response:{command_id}.
    """
    manager, subscribe_calls, unsubscribe_calls = create_manager_with_spy_pubsub()

    # Ejecutar register → resolve para cada command_id
    for i, cmd_id in enumerate(command_ids):
        event = manager.register_command_waiter(cmd_id)
        response = responses[i % len(responses)]
        manager.resolve_command_response(cmd_id, response)

    # Verificar que NO se usaron canales cmd_response:*
    assert_no_cmd_response_channels(subscribe_calls, unsubscribe_calls)


@pytest.mark.asyncio
@hypothesis_settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    command_ids=st.lists(command_id_strategy, min_size=1, max_size=5),
)
async def test_register_then_timeout_no_unsubscribe(
    command_ids: list,
):
    """
    **Validates: Requirements 3.1, 3.4, 3.5**

    Para cualquier secuencia de register → wait_for_command_response (con timeout corto),
    nunca se invoca SUBSCRIBE/UNSUBSCRIBE en canales cmd_response:{command_id}.
    El cleanup solo limpia el dict interno, sin operaciones Redis.
    """
    manager, subscribe_calls, unsubscribe_calls = create_manager_with_spy_pubsub()

    # Ejecutar register → timeout (muy corto) para cada command_id
    for cmd_id in command_ids:
        manager.register_command_waiter(cmd_id)
        result = await manager.wait_for_command_response(cmd_id, timeout=0.001)
        # El resultado debe ser None (timeout)
        assert result is None, (
            f"Se esperaba None por timeout para cmd_id={cmd_id}, pero obtuvo {result}"
        )

    # Verificar que NO se usaron canales cmd_response:*
    assert_no_cmd_response_channels(subscribe_calls, unsubscribe_calls)

    # Verificar que los waiters se limpiaron del dict interno
    for cmd_id in command_ids:
        assert cmd_id not in manager._pending_command_responses, (
            f"El waiter para {cmd_id} debería haberse limpiado tras timeout"
        )


@pytest.mark.asyncio
@hypothesis_settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    data=st.data(),
    num_operations=st.integers(min_value=3, max_value=10),
)
async def test_mixed_operations_sequence_no_cmd_response_channels(
    data,
    num_operations: int,
):
    """
    **Validates: Requirements 3.1, 3.4, 3.5**

    Para cualquier secuencia mezclada de register, resolve y timeout de command waiters,
    NUNCA se invoca SUBSCRIBE/UNSUBSCRIBE en canales cmd_response:{command_id}.

    Genera secuencias tipo: register-resolve-register-timeout-register-resolve...
    """
    manager, subscribe_calls, unsubscribe_calls = create_manager_with_spy_pubsub()

    # Estado para tracking de command_ids registrados pero no resueltos/expirados
    registered_ids = []

    for _ in range(num_operations):
        op = data.draw(operation_strategy)

        if op == "register":
            cmd_id = data.draw(command_id_strategy)
            manager.register_command_waiter(cmd_id)
            registered_ids.append(cmd_id)

        elif op == "resolve" and registered_ids:
            # Resolver un command_id registrado previamente
            idx = data.draw(st.integers(min_value=0, max_value=len(registered_ids) - 1))
            cmd_id = registered_ids[idx]
            response = data.draw(response_strategy)
            manager.resolve_command_response(cmd_id, response)
            registered_ids.pop(idx)

        elif op == "wait_timeout" and registered_ids:
            # Hacer timeout de un command_id registrado
            idx = data.draw(st.integers(min_value=0, max_value=len(registered_ids) - 1))
            cmd_id = registered_ids[idx]
            result = await manager.wait_for_command_response(cmd_id, timeout=0.001)
            registered_ids.pop(idx)

    # === PROPIEDAD PRINCIPAL: nunca se usaron canales cmd_response:* ===
    assert_no_cmd_response_channels(subscribe_calls, unsubscribe_calls)


@pytest.mark.asyncio
@hypothesis_settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    command_id=command_id_strategy,
    response=response_strategy,
)
async def test_register_resolve_wait_full_cycle_no_channels(
    command_id: str,
    response: dict,
):
    """
    **Validates: Requirements 3.1, 3.4, 3.5**

    Ciclo completo: register → resolve → wait devuelve respuesta.
    En ningún punto del ciclo se invocan operaciones de canal cmd_response:*.
    """
    manager, subscribe_calls, unsubscribe_calls = create_manager_with_spy_pubsub()

    # Register
    event = manager.register_command_waiter(command_id)
    assert not event.is_set(), "El event no debe estar señalado antes de resolve"

    # Resolve
    resolved = manager.resolve_command_response(command_id, response)
    assert resolved is True, "resolve_command_response debe retornar True si hay waiter"

    # Wait (debe retornar inmediatamente porque ya se resolvió)
    result = await manager.wait_for_command_response(command_id, timeout=1.0)
    assert result == response, (
        f"La respuesta debe ser {response}, pero fue {result}"
    )

    # Verificar propiedad principal
    assert_no_cmd_response_channels(subscribe_calls, unsubscribe_calls)

    # Verificar cleanup
    assert command_id not in manager._pending_command_responses, (
        f"El waiter para {command_id} debería haberse limpiado tras wait"
    )
