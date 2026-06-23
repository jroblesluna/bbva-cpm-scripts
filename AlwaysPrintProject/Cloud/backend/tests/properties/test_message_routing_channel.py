# Feature: redis-pubsub-channel-consolidation, Property: Message Routing to Correct Channel
"""
Property test: Message Routing to Correct Channel (Esquema Consolidado)

Para cualquier tipo de mensaje (comando a workstation, broadcast organizacional,
o respuesta de comando) y cualquier identificador target, el sistema DEBE publicar
el mensaje en el canal Redis con formato correcto:
- `worker:{target_worker_id}` para comandos a workstation remota
- `org:{organization_id}` para broadcasts organizacionales
- `worker:{originator_worker_id}` con type=cmd_response para respuestas de comando

Se generan UUIDs aleatorios para worker_id, org_id y cmd_id, y se verifica
que las llamadas a Redis.publish() usan los canales correctos.

Feature: redis-pubsub-channel-consolidation
**Validates: Requirements 1.4, 2.2, 3.2**
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


# === HELPER PARA CREAR RedisConnectionManager CON MOCK ===


async def create_manager_with_mock_redis(resolved_worker_id: str = "worker_remote_99"):
    """
    Crea un RedisConnectionManager con Redis mockeado,
    marcado como disponible, sin intentar conexión real.

    Args:
        resolved_worker_id: El worker_id que WorkerRegistry resuelve
    """
    from app.services.redis_connection_manager import RedisConnectionManager

    manager = RedisConnectionManager(redis_url="redis://mock:6379/0")
    mock_redis = MockRedisCapture()

    # Inyectar el mock directamente
    manager._redis = mock_redis
    manager._redis_available = True
    manager._worker_id = "worker_local_12345"

    # Mock WorkerRegistry que resuelve al worker_id dado
    mock_registry = AsyncMock()
    mock_registry.register_workstation = AsyncMock()
    mock_registry.unregister_workstation = AsyncMock()
    mock_registry.find_worker_for_workstation = AsyncMock(return_value=resolved_worker_id)
    manager._worker_registry = mock_registry

    # Mock pubsub
    mock_pubsub = AsyncMock()
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.unsubscribe = AsyncMock()
    manager._pubsub = mock_pubsub

    return manager, mock_redis


# === PROPERTY TESTS ===


@hypothesis_settings(max_examples=150, deadline=None)
@given(
    workstation_id=uuid_strategy,
    target_worker_id=st.from_regex(r"worker_[a-z0-9]{5,10}", fullmatch=True),
    message=message_strategy,
)
async def test_send_to_workstation_publishes_to_worker_channel(
    workstation_id: str,
    target_worker_id: str,
    message: dict,
):
    """
    Propiedad: Cuando send_to_workstation() se llama con un workstation_id
    que NO está conectado localmente, el sistema DEBE publicar en el canal
    Redis `worker:{target_worker_id}` resuelto via WorkerRegistry.

    NO se publica en `ws:{workstation_id}` (canal eliminado).

    Feature: redis-pubsub-channel-consolidation
    **Validates: Requirements 1.4, 2.2**
    """
    manager, mock_redis = await create_manager_with_mock_redis(
        resolved_worker_id=target_worker_id
    )

    # No registrar la workstation localmente → forzar publicación via Redis
    result = await manager.send_to_workstation(workstation_id, message)

    # Retorna True porque se publicó exitosamente via Redis
    assert result is True, (
        "send_to_workstation con publicación Redis exitosa debe retornar True"
    )

    # Verificar que se publicó exactamente en worker:{target_worker_id}
    assert len(mock_redis.published) == 1, (
        f"Se esperaba exactamente 1 publicación Redis, "
        f"pero se hicieron {len(mock_redis.published)}"
    )

    channel, payload = mock_redis.published[0]
    expected_channel = f"worker:{target_worker_id}"
    assert channel == expected_channel, (
        f"El canal de publicación debería ser '{expected_channel}' "
        f"pero fue '{channel}'"
    )

    # Verificar que NO se usó el canal ws:{workstation_id} (eliminado)
    assert channel != f"ws:{workstation_id}", (
        f"El canal ws:{workstation_id} está ELIMINADO. "
        f"Los mensajes deben ir a worker:*"
    )

    # Verificar que el payload contiene target_workstation_id
    decoded = json.loads(payload)
    assert decoded.get("target_workstation_id") == workstation_id, (
        f"El payload debe contener target_workstation_id='{workstation_id}' "
        f"pero fue '{decoded.get('target_workstation_id')}'"
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

    Feature: redis-pubsub-channel-consolidation
    **Validates: Requirements 1.4**
    """
    manager, mock_redis = await create_manager_with_mock_redis()

    # Crear un mock de db session
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
    originator_worker_id=st.from_regex(r"worker_[a-z0-9]{5,10}", fullmatch=True),
    response=st.fixed_dictionaries({
        "success": st.booleans(),
        "output": st.text(min_size=0, max_size=100),
    }),
)
async def test_publish_command_response_publishes_to_worker_channel(
    command_id: str,
    originator_worker_id: str,
    response: dict,
):
    """
    Propiedad: Cuando publish_command_response() se llama con un command_id
    y originator_worker_id, el sistema DEBE publicar la respuesta en el canal
    Redis `worker:{originator_worker_id}` con type=cmd_response y command_id.

    NO se publica en `cmd_response:{command_id}` (canal eliminado).

    Feature: redis-pubsub-channel-consolidation
    **Validates: Requirements 3.2**
    """
    manager, mock_redis = await create_manager_with_mock_redis()

    await manager.publish_command_response(command_id, response, originator_worker_id)

    # Verificar que se publicó en worker:{originator_worker_id}
    assert len(mock_redis.published) == 1, (
        f"Se esperaba exactamente 1 publicación Redis para command response, "
        f"pero se hicieron {len(mock_redis.published)}"
    )

    channel, payload = mock_redis.published[0]
    expected_channel = f"worker:{originator_worker_id}"
    assert channel == expected_channel, (
        f"El canal de publicación debería ser '{expected_channel}' "
        f"pero fue '{channel}'"
    )

    # Verificar que NO se usó el canal cmd_response:{command_id} (eliminado)
    assert channel != f"cmd_response:{command_id}", (
        f"El canal cmd_response:{command_id} está ELIMINADO. "
        f"Las respuestas van a worker:{originator_worker_id}"
    )

    # Verificar que el payload tiene type=cmd_response y command_id
    decoded = json.loads(payload)
    assert decoded.get("type") == "cmd_response", (
        f"El campo 'type' debería ser 'cmd_response' "
        f"pero fue '{decoded.get('type')}'"
    )
    assert decoded.get("command_id") == command_id, (
        f"El campo 'command_id' debería ser '{command_id}' "
        f"pero fue '{decoded.get('command_id')}'"
    )
    assert decoded.get("success") == response["success"], (
        f"El campo 'success' debería ser {response['success']} "
        f"pero fue {decoded.get('success')}"
    )


@hypothesis_settings(max_examples=100, deadline=None)
@given(
    workstation_id=uuid_strategy,
    organization_id=uuid_strategy,
    command_id=uuid_strategy,
    originator_worker_id=st.from_regex(r"worker_[a-z0-9]{5,10}", fullmatch=True),
    target_worker_id=st.from_regex(r"worker_[a-z0-9]{5,10}", fullmatch=True),
    message=message_strategy,
)
async def test_channel_format_consistency(
    workstation_id: str,
    organization_id: str,
    command_id: str,
    originator_worker_id: str,
    target_worker_id: str,
    message: dict,
):
    """
    Propiedad: Los tres tipos de canal consolidado SIEMPRE siguen el formato correcto:
    - worker:{id} para mensajes dirigidos a workstations remotas
    - org:{id} para broadcasts organizacionales
    - worker:{originator} con type=cmd_response para respuestas de comandos

    Ningún canal debe ser ws:{id} ni cmd_response:{id} (eliminados).

    Feature: redis-pubsub-channel-consolidation
    **Validates: Requirements 1.4, 2.2, 3.2**
    """
    manager, mock_redis = await create_manager_with_mock_redis(
        resolved_worker_id=target_worker_id
    )
    mock_db = MagicMock()

    # Ejecutar las tres operaciones
    await manager.send_to_workstation(workstation_id, message)
    await manager.broadcast_to_organization(organization_id, message, mock_db)
    await manager.publish_command_response(command_id, {"success": True}, originator_worker_id)

    # Verificar que se publicaron 3 mensajes
    assert len(mock_redis.published) == 3, (
        f"Se esperaban 3 publicaciones pero hubo {len(mock_redis.published)}"
    )

    # Verificar formato de cada canal
    ws_channel = mock_redis.published[0][0]
    org_channel = mock_redis.published[1][0]
    cmd_channel = mock_redis.published[2][0]

    # Canal para workstation: debe ser "worker:{target_worker_id}"
    assert ws_channel == f"worker:{target_worker_id}", (
        f"Canal workstation incorrecto: '{ws_channel}' != 'worker:{target_worker_id}'"
    )
    assert not ws_channel.startswith("ws:"), (
        f"Canal ws:* está ELIMINADO, pero se encontró: '{ws_channel}'"
    )

    # Canal organización: debe ser exactamente "org:{organization_id}"
    assert org_channel == f"org:{organization_id}", (
        f"Canal organización incorrecto: '{org_channel}' != 'org:{organization_id}'"
    )

    # Canal command response: debe ser "worker:{originator_worker_id}"
    assert cmd_channel == f"worker:{originator_worker_id}", (
        f"Canal cmd_response incorrecto: '{cmd_channel}' != 'worker:{originator_worker_id}'"
    )
    assert not cmd_channel.startswith("cmd_response:"), (
        f"Canal cmd_response:* está ELIMINADO, pero se encontró: '{cmd_channel}'"
    )
