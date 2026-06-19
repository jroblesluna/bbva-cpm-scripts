"""
Property test para Task 5.3: Command response routing via worker channel (Property 6).

**Validates: Requirements 3.2**

Property 6: Para cualquier respuesta de comando de una workstation en Worker B
donde el comando fue originado por Worker A, la respuesta SE PUBLICA en el canal
`worker:A` con campos `type`=`cmd_response` y el `command_id` original.
"""
import json
from unittest.mock import AsyncMock

import pytest
from hypothesis import given, settings as hypothesis_settings, assume
from hypothesis import strategies as st

from app.services.redis_connection_manager import RedisConnectionManager


# === Estrategias de generación ===

# Command IDs tipo UUID
command_id_strategy = st.uuids().map(str)

# Worker IDs con formato worker_{pid}
originator_worker_id_strategy = st.integers(min_value=1, max_value=999999).map(
    lambda pid: f"worker_{pid}"
)

# Campos de respuesta (diccionarios con varios campos)
response_value_strategy = st.one_of(
    st.text(min_size=0, max_size=30, alphabet=st.characters(categories=("L", "N", "P"))),
    st.integers(min_value=-10000, max_value=10000),
    st.booleans(),
    st.none(),
)

response_dict_strategy = st.dictionaries(
    keys=st.sampled_from([
        "status", "result", "workstation_id", "organization_id",
        "data", "error", "message", "code", "duration_ms",
    ]),
    values=response_value_strategy,
    min_size=0,
    max_size=5,
)


@pytest.mark.asyncio
@hypothesis_settings(max_examples=100, deadline=None)
@given(
    command_id=command_id_strategy,
    originator_worker_id=originator_worker_id_strategy,
    response=response_dict_strategy,
)
async def test_command_response_publishes_to_originator_worker_channel(
    command_id: str,
    originator_worker_id: str,
    response: dict,
):
    """
    **Validates: Requirements 3.2**

    Para cualquier respuesta de comando cross-worker, el PUBLISH se dirige a
    `worker:{originator_worker_id}` con type=cmd_response y command_id correcto.
    """
    # Evitar colisiones con campos inyectados por publish_command_response
    assume("type" not in response)
    assume("command_id" not in response)

    # Configurar manager con Redis disponible
    manager = RedisConnectionManager(redis_url="redis://localhost:6379/0")
    manager._redis_available = True
    manager._redis = AsyncMock()
    manager._redis.publish = AsyncMock(return_value=1)

    # Ejecutar publish_command_response
    await manager.publish_command_response(command_id, response, originator_worker_id)

    # === Verificaciones de Property 6 ===

    # 1. Se publicó exactamente una vez
    manager._redis.publish.assert_called_once()
    call_args = manager._redis.publish.call_args[0]
    published_channel = call_args[0]
    published_payload = json.loads(call_args[1])

    # 2. El canal es worker:{originator_worker_id}
    assert published_channel == f"worker:{originator_worker_id}", (
        f"El canal debe ser 'worker:{originator_worker_id}', "
        f"pero fue '{published_channel}'"
    )

    # 3. El payload contiene type=cmd_response
    assert published_payload["type"] == "cmd_response", (
        f"type debe ser 'cmd_response', pero fue '{published_payload.get('type')}'"
    )

    # 4. El payload contiene el command_id correcto
    assert published_payload["command_id"] == command_id, (
        f"command_id debe ser '{command_id}', "
        f"pero fue '{published_payload.get('command_id')}'"
    )

    # 5. El payload contiene todos los campos de la respuesta original
    for key, value in response.items():
        assert key in published_payload, (
            f"Campo '{key}' de la respuesta original no está en el payload publicado"
        )
        # Comparar via JSON para manejar serialización correcta
        assert json.dumps(published_payload[key], default=str) == json.dumps(value, default=str), (
            f"Campo '{key}': esperado {value!r}, obtenido {published_payload[key]!r}"
        )


@pytest.mark.asyncio
@hypothesis_settings(max_examples=100, deadline=None)
@given(
    command_id=command_id_strategy,
    originator_worker_id=originator_worker_id_strategy,
    response=response_dict_strategy,
)
async def test_command_response_never_publishes_to_cmd_response_channel(
    command_id: str,
    originator_worker_id: str,
    response: dict,
):
    """
    **Validates: Requirements 3.2**

    Para cualquier respuesta de comando, nunca se publica al canal
    `cmd_response:{command_id}` (patrón antiguo eliminado).
    """
    assume("type" not in response)
    assume("command_id" not in response)

    # Configurar manager con Redis disponible
    manager = RedisConnectionManager(redis_url="redis://localhost:6379/0")
    manager._redis_available = True
    manager._redis = AsyncMock()
    manager._redis.publish = AsyncMock(return_value=1)

    # Ejecutar publish_command_response
    await manager.publish_command_response(command_id, response, originator_worker_id)

    # Verificar que el canal NO usa el patrón cmd_response:{id}
    call_args = manager._redis.publish.call_args[0]
    published_channel = call_args[0]
    assert not published_channel.startswith("cmd_response:"), (
        f"No debe publicar a canales cmd_response:*, "
        f"pero publicó a '{published_channel}'"
    )
    # Verificar que usa el patrón worker:{id}
    assert published_channel.startswith("worker:"), (
        f"Debe publicar a canales worker:*, pero publicó a '{published_channel}'"
    )


@pytest.mark.asyncio
@hypothesis_settings(max_examples=50, deadline=None)
@given(
    command_id=command_id_strategy,
    originator_worker_id=originator_worker_id_strategy,
)
async def test_command_response_with_empty_response_dict(
    command_id: str,
    originator_worker_id: str,
):
    """
    **Validates: Requirements 3.2**

    Incluso con respuesta vacía, se publica correctamente con type y command_id.
    """
    manager = RedisConnectionManager(redis_url="redis://localhost:6379/0")
    manager._redis_available = True
    manager._redis = AsyncMock()
    manager._redis.publish = AsyncMock(return_value=1)

    # Respuesta vacía
    await manager.publish_command_response(command_id, {}, originator_worker_id)

    # Verificaciones
    manager._redis.publish.assert_called_once()
    call_args = manager._redis.publish.call_args[0]
    published_channel = call_args[0]
    published_payload = json.loads(call_args[1])

    # Canal correcto
    assert published_channel == f"worker:{originator_worker_id}"

    # Payload mínimo con type y command_id
    assert published_payload == {
        "type": "cmd_response",
        "command_id": command_id,
    }


@pytest.mark.asyncio
@hypothesis_settings(max_examples=50, deadline=None)
@given(
    command_id=command_id_strategy,
    originator_worker_id=originator_worker_id_strategy,
    response=response_dict_strategy,
)
async def test_command_response_not_published_when_redis_unavailable(
    command_id: str,
    originator_worker_id: str,
    response: dict,
):
    """
    **Validates: Requirements 3.2**

    Cuando Redis no está disponible, publish_command_response no intenta publicar.
    """
    assume("type" not in response)
    assume("command_id" not in response)

    manager = RedisConnectionManager(redis_url="redis://localhost:6379/0")
    manager._redis_available = False
    manager._redis = AsyncMock()
    manager._redis.publish = AsyncMock(return_value=1)

    # Ejecutar - no debe fallar ni publicar
    await manager.publish_command_response(command_id, response, originator_worker_id)

    # No se publicó nada cuando Redis no está disponible
    manager._redis.publish.assert_not_called()
