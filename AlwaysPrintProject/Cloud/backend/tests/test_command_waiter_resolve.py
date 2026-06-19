"""
Property test para Task 12.2: Command response resolves waiter (Property 7).

**Validates: Requirements 3.3, 9.2**

Property 7: Para cualquier mensaje con `type=cmd_response`, el command waiter
que coincide con `command_id` SE RESUELVE con el payload de la respuesta.
"""
import asyncio
from unittest.mock import AsyncMock

import pytest
from hypothesis import given, settings as hypothesis_settings, assume
from hypothesis import strategies as st

from app.services.redis_connection_manager import RedisConnectionManager


# === Estrategias de generación ===

# Command IDs tipo UUID
command_id_strategy = st.uuids().map(str)

# Valores de respuesta
response_value_strategy = st.one_of(
    st.text(min_size=0, max_size=30, alphabet=st.characters(categories=("L", "N", "P"))),
    st.integers(min_value=-10000, max_value=10000),
    st.booleans(),
    st.none(),
)

# Diccionarios de respuesta
response_dict_strategy = st.dictionaries(
    keys=st.sampled_from([
        "status", "result", "workstation_id", "organization_id",
        "data", "error", "message", "code", "duration_ms",
    ]),
    values=response_value_strategy,
    min_size=1,
    max_size=5,
)


@pytest.mark.asyncio
@hypothesis_settings(max_examples=100, deadline=None)
@given(
    command_id=command_id_strategy,
    response=response_dict_strategy,
)
async def test_resolve_sets_event_and_stores_response(
    command_id: str,
    response: dict,
):
    """
    **Validates: Requirements 3.3, 9.2**

    Registrar un waiter, resolver con una respuesta → event.is_set() == True
    y el container almacena la respuesta.
    """
    manager = RedisConnectionManager(redis_url="redis://localhost:6379/0")
    manager._redis_available = False  # No necesitamos Redis real para este test

    # Registrar waiter
    event = manager.register_command_waiter(command_id)

    # Verificar estado inicial: event no señalado
    assert not event.is_set(), "El event debe estar sin señalar antes de resolver"

    # Resolver con respuesta
    result = manager.resolve_command_response(command_id, response)

    # Verificaciones:
    # 1. resolve retorna True (había un waiter esperando)
    assert result is True, "resolve_command_response debe retornar True cuando existe el waiter"

    # 2. El event está señalado
    assert event.is_set(), "El event debe estar señalado después de resolver"

    # 3. El container tiene la respuesta correcta
    _, container, _ = manager._pending_command_responses[command_id]
    assert container[0] == response, (
        f"La respuesta almacenada debe ser {response!r}, "
        f"pero fue {container[0]!r}"
    )


@pytest.mark.asyncio
@hypothesis_settings(max_examples=100, deadline=None)
@given(
    command_id=command_id_strategy,
    response=response_dict_strategy,
)
async def test_wait_returns_resolved_response(
    command_id: str,
    response: dict,
):
    """
    **Validates: Requirements 3.3, 9.2**

    Registrar waiter, resolver, luego esperar → wait_for_command_response
    retorna la respuesta correcta.
    """
    manager = RedisConnectionManager(redis_url="redis://localhost:6379/0")
    manager._redis_available = False

    # Registrar waiter
    manager.register_command_waiter(command_id)

    # Resolver con respuesta (simula llegada de cmd_response por listener)
    manager.resolve_command_response(command_id, response)

    # Esperar la respuesta (ya resuelta, debe retornar inmediatamente)
    result = await manager.wait_for_command_response(command_id, timeout=5.0)

    # Verificaciones:
    # 1. El resultado no es None
    assert result is not None, "wait_for_command_response no debe retornar None si ya se resolvió"

    # 2. El resultado coincide con la respuesta original
    assert result == response, (
        f"La respuesta recibida debe ser {response!r}, pero fue {result!r}"
    )

    # 3. El waiter fue limpiado del dict interno
    assert command_id not in manager._pending_command_responses, (
        "El waiter debe ser eliminado del dict tras wait_for_command_response"
    )


@pytest.mark.asyncio
@hypothesis_settings(max_examples=100, deadline=None)
@given(
    command_id=command_id_strategy,
    response=response_dict_strategy,
)
async def test_resolve_nonexistent_command_returns_false(
    command_id: str,
    response: dict,
):
    """
    **Validates: Requirements 3.3, 9.2**

    Resolver con un command_id desconocido → retorna False sin error.
    """
    manager = RedisConnectionManager(redis_url="redis://localhost:6379/0")
    manager._redis_available = False

    # NO registrar ningún waiter — resolver directamente con un command_id desconocido
    result = manager.resolve_command_response(command_id, response)

    # Verificaciones:
    # 1. Retorna False (no había waiter)
    assert result is False, (
        "resolve_command_response debe retornar False cuando no existe el waiter"
    )

    # 2. No se creó ninguna entrada en el dict
    assert command_id not in manager._pending_command_responses, (
        "No debe crearse una entrada en _pending_command_responses para un command_id inexistente"
    )
