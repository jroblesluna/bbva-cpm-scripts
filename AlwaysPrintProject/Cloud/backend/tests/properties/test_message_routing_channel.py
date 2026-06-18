# Feature: websocket-scaling-redis, Property 1: Message Routing to Correct Channel
"""
Property test: Message Routing to Correct Channel

Para cualquier tipo de mensaje (comando a workstation, broadcast organizacional,
o respuesta de comando) y cualquier identificador target, el sistema DEBE publicar
el mensaje en el canal Redis con formato correcto:
- `ws:{workstation_id}` para comandos a workstation
- `org:{organization_id}` para broadcasts organizacionales
- `cmd_response:{command_id}` para respuestas de comando

Se generan UUIDs aleatorios para ws_id, org_id y cmd_id, y se verifica
que las llamadas a Redis.publish() usan los canales correctos.

Feature: websocket-scaling-redis, Property 1: Message Routing to Correct Channel
**Validates: Requirements 1.1, 1.3, 1.6**
"""

import asyncio
import json
from typing import Dict, List, Optional, Set, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings as hypothesis_settings, assume
from hypothesis import strategies as st


# === ESTRATEGIAS DE GENERACIÓN ===

# Generar UUIDs como strings para identificadores
uuid_strategy = st.uuids().map(str)

# Estrategia para tipos de mensaje válidos
message_type_strategy = st.sampled_from([
    "command",
    "check_update",
    "analyze_log",
    "get_latest_log",
    "forced_contingency",
    "config_update",
    "status_update",
    "ping",
    "message",
])

# Estrategia para generar un mensaje dict genérico
message_strategy = st.fixed_dictionaries({
    "type": message_type_strategy,
    "data": st.text(min_size=1, max_size=50),
})


# === MOCK DE REDIS QUE CAPTURA PUBLISH ===


class MockRedisCapture:
    """
    Mock de Redis que captura todas las llamadas a publish()
    para verificar que se envían al canal correcto.
    """

    def __init__(self):
        # Lista de (channel, payload) publicados
        self.published: List[Tuple[str, str]] = []
        # Simular disponibilidad
        self.available = True

    async def publish(self, channel: str, message: str) -> int:
        """Captura la publicación en un canal."""
        self.published.append((channel, message))
        return 1

    async def subscribe(self, *channels, **kwargs):
        """Mock de suscripción."""
        pass

    async def unsubscribe(self, *channels):
        """Mock de desuscripción."""
        pass

    def pipeline(self):
        """Retorna un pipeline mock."""
        return MockPipeline(self)


class MockPipeline:
    """Pipeline mock básico."""

    def __init__(self, redis: MockRedisCapture):
        self._redis = redis

    async def execute(self):
        return []


# === HELPER PARA CREAR RedisConnectionManager CON MOCK ===


async def create_manager_with_mock_redis():
    """
    Crea un RedisConnectionManager con Redis mockeado,
    marcado como disponible, sin intentar conexión real.
    """
    from app.services.redis_connection_manager import RedisConnectionManager

    manager = RedisConnectionManager(redis_url="redis://mock:6379/0")
    mock_redis = MockRedisCapture()

    # Inyectar el mock directamente
    manager._redis = mock_redis
    manager._redis_available = True
    manager._lock = asyncio.Lock()

    return manager, mock_redis


# === PROPERTY TESTS ===


@hypothesis_settings(max_examples=150, deadline=None)
@given(
    workstation_id=uuid_strategy,
    message=message_strategy,
)
async def test_send_to_workstation_publishes_to_ws_channel(
    workstation_id: str,
    message: dict,
):
    """
    Propiedad: Cuando send_to_workstation() se llama con un workstation_id
    que NO está conectado localmente, el sistema DEBE publicar en el canal
    Redis `ws:{workstation_id}`.

    Feature: websocket-scaling-redis, Property 1: Message Routing to Correct Channel
    **Validates: Requirements 1.1, 1.3, 1.6**
    """
    manager, mock_redis = await create_manager_with_mock_redis()

    # No registrar la workstation localmente → forzar publicación via Redis
    # (workstation_connections está vacío)
    result = await manager.send_to_workstation(workstation_id, message)

    # Verificar que se publicó exactamente en ws:{workstation_id}
    assert len(mock_redis.published) == 1, (
        f"Se esperaba exactamente 1 publicación Redis, "
        f"pero se hicieron {len(mock_redis.published)}"
    )

    channel, payload = mock_redis.published[0]
    expected_channel = f"ws:{workstation_id}"
    assert channel == expected_channel, (
        f"El canal de publicación debería ser '{expected_channel}' "
        f"pero fue '{channel}'"
    )

    # Verificar que el payload es el mensaje serializado
    decoded = json.loads(payload)
    assert decoded["type"] == message["type"], (
        f"El tipo de mensaje publicado debería ser '{message['type']}' "
        f"pero fue '{decoded['type']}'"
    )


@hypothesis_settings(max_examples=150, deadline=None)
@given(
    organization_id=uuid_strategy,
    message=message_strategy,
)
async def test_broadcast_to_organization_publishes_to_org_channel(
    organization_id: str,
    message: dict,
):
    """
    Propiedad: Cuando broadcast_to_organization() se llama con un organization_id,
    el sistema DEBE publicar en el canal Redis `org:{organization_id}`.

    Feature: websocket-scaling-redis, Property 1: Message Routing to Correct Channel
    **Validates: Requirements 1.1, 1.3, 1.6**
    """
    manager, mock_redis = await create_manager_with_mock_redis()

    # Crear un mock de db session (no se usa para publicación Redis)
    mock_db = MagicMock()

    await manager.broadcast_to_organization(organization_id, message, mock_db)

    # Verificar que se publicó en org:{organization_id}
    assert len(mock_redis.published) == 1, (
        f"Se esperaba exactamente 1 publicación Redis para broadcast, "
        f"pero se hicieron {len(mock_redis.published)}"
    )

    channel, payload = mock_redis.published[0]
    expected_channel = f"org:{organization_id}"
    assert channel == expected_channel, (
        f"El canal de publicación debería ser '{expected_channel}' "
        f"pero fue '{channel}'"
    )

    # Verificar que el payload contiene el mensaje correcto
    decoded = json.loads(payload)
    assert decoded["type"] == message["type"], (
        f"El tipo de mensaje en broadcast debería ser '{message['type']}' "
        f"pero fue '{decoded['type']}'"
    )


@hypothesis_settings(max_examples=150, deadline=None)
@given(
    command_id=uuid_strategy,
    response=st.fixed_dictionaries({
        "command_id": uuid_strategy,
        "success": st.booleans(),
        "output": st.text(min_size=0, max_size=100),
    }),
)
async def test_publish_command_response_publishes_to_cmd_response_channel(
    command_id: str,
    response: dict,
):
    """
    Propiedad: Cuando publish_command_response() se llama con un command_id,
    el sistema DEBE publicar la respuesta en el canal Redis `cmd_response:{command_id}`.

    Feature: websocket-scaling-redis, Property 1: Message Routing to Correct Channel
    **Validates: Requirements 1.1, 1.3, 1.6**
    """
    manager, mock_redis = await create_manager_with_mock_redis()

    await manager.publish_command_response(command_id, response)

    # Verificar que se publicó en cmd_response:{command_id}
    assert len(mock_redis.published) == 1, (
        f"Se esperaba exactamente 1 publicación Redis para command response, "
        f"pero se hicieron {len(mock_redis.published)}"
    )

    channel, payload = mock_redis.published[0]
    expected_channel = f"cmd_response:{command_id}"
    assert channel == expected_channel, (
        f"El canal de publicación debería ser '{expected_channel}' "
        f"pero fue '{channel}'"
    )

    # Verificar que el payload es la respuesta serializada
    decoded = json.loads(payload)
    assert decoded["success"] == response["success"], (
        f"El campo 'success' debería ser {response['success']} "
        f"pero fue {decoded['success']}"
    )


@hypothesis_settings(max_examples=100, deadline=None)
@given(
    workstation_id=uuid_strategy,
    organization_id=uuid_strategy,
    command_id=uuid_strategy,
    message=message_strategy,
)
async def test_channel_format_consistency(
    workstation_id: str,
    organization_id: str,
    command_id: str,
    message: dict,
):
    """
    Propiedad: Los tres tipos de canal SIEMPRE siguen el formato correcto:
    - ws:{id} contiene exactamente el prefijo "ws:" seguido del workstation_id
    - org:{id} contiene exactamente el prefijo "org:" seguido del organization_id
    - cmd_response:{id} contiene exactamente el prefijo "cmd_response:" seguido del command_id

    Ningún canal debe contener espacios adicionales, slashes, o caracteres inesperados.

    Feature: websocket-scaling-redis, Property 1: Message Routing to Correct Channel
    **Validates: Requirements 1.1, 1.3, 1.6**
    """
    manager, mock_redis = await create_manager_with_mock_redis()
    mock_db = MagicMock()

    # Ejecutar las tres operaciones
    await manager.send_to_workstation(workstation_id, message)
    await manager.broadcast_to_organization(organization_id, message, mock_db)
    await manager.publish_command_response(command_id, {"success": True})

    # Verificar que se publicaron 3 mensajes
    assert len(mock_redis.published) == 3, (
        f"Se esperaban 3 publicaciones pero hubo {len(mock_redis.published)}"
    )

    # Verificar formato de cada canal
    ws_channel = mock_redis.published[0][0]
    org_channel = mock_redis.published[1][0]
    cmd_channel = mock_redis.published[2][0]

    # Canal workstation: debe ser exactamente "ws:{workstation_id}"
    assert ws_channel == f"ws:{workstation_id}", (
        f"Canal workstation incorrecto: '{ws_channel}' != 'ws:{workstation_id}'"
    )
    assert ":" in ws_channel and ws_channel.split(":", 1)[0] == "ws", (
        f"Formato de canal ws inválido: '{ws_channel}'"
    )

    # Canal organización: debe ser exactamente "org:{organization_id}"
    assert org_channel == f"org:{organization_id}", (
        f"Canal organización incorrecto: '{org_channel}' != 'org:{organization_id}'"
    )
    assert ":" in org_channel and org_channel.split(":", 1)[0] == "org", (
        f"Formato de canal org inválido: '{org_channel}'"
    )

    # Canal command response: debe ser exactamente "cmd_response:{command_id}"
    assert cmd_channel == f"cmd_response:{command_id}", (
        f"Canal cmd_response incorrecto: '{cmd_channel}' != 'cmd_response:{command_id}'"
    )
    assert "cmd_response:" in cmd_channel, (
        f"Formato de canal cmd_response inválido: '{cmd_channel}'"
    )
