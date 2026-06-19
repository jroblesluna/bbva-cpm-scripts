"""
Test de verificación para Task 4.1:
send_to_workstation con resolución de worker y publish a worker:{target_worker_id}
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.redis_connection_manager import RedisConnectionManager


@pytest.mark.asyncio
async def test_local_delivery_unchanged():
    """Si workstation está local → envío directo via WebSocket (sin cambio)."""
    manager = RedisConnectionManager()
    ws = AsyncMock()
    manager.workstation_connections["ws-1"] = ws
    result = await manager.send_to_workstation("ws-1", {"type": "test"})
    assert result is True, "Local delivery should return True"
    ws.send_json.assert_called_once()


@pytest.mark.asyncio
async def test_redis_not_available_returns_false():
    """Si Redis no disponible → log, return False."""
    manager = RedisConnectionManager()
    manager._redis_available = False
    result = await manager.send_to_workstation("ws-2", {"type": "test"})
    assert result is False, "Should return False without Redis"


@pytest.mark.asyncio
async def test_worker_found_publishes_to_worker_channel():
    """Si worker encontrado → PUBLISH worker:{target_worker_id} con payload enriquecido."""
    manager = RedisConnectionManager(redis_url="redis://localhost:6379/0")
    manager._redis_available = True
    manager._redis = AsyncMock()
    registry = AsyncMock()
    registry.find_worker_for_workstation = AsyncMock(return_value="worker_999")
    manager._worker_registry = registry

    result = await manager.send_to_workstation(
        "ws-3", {"type": "command", "organization_id": "org-1"}
    )
    assert result is False, "Remote publish should return False"

    # Verificar que se publicó al canal correcto
    publish_call = manager._redis.publish.call_args
    assert publish_call[0][0] == "worker:worker_999"

    payload = json.loads(publish_call[0][1])
    assert payload["target_workstation_id"] == "ws-3"
    assert payload["organization_id"] == "org-1"
    assert payload["type"] == "command"


@pytest.mark.asyncio
async def test_worker_not_found_returns_false():
    """Si no encontrado → log warning, return False."""
    manager = RedisConnectionManager(redis_url="redis://localhost:6379/0")
    manager._redis_available = True
    manager._redis = AsyncMock()
    registry = AsyncMock()
    registry.find_worker_for_workstation = AsyncMock(return_value=None)
    manager._worker_registry = registry

    result = await manager.send_to_workstation("ws-4", {"type": "test"})
    assert result is False, "Worker not found should return False"
    manager._redis.publish.assert_not_called()


@pytest.mark.asyncio
async def test_no_worker_registry_returns_false():
    """Si _worker_registry es None (Redis fue disponible pero registry no) → return False."""
    manager = RedisConnectionManager(redis_url="redis://localhost:6379/0")
    manager._redis_available = True
    manager._redis = AsyncMock()
    manager._worker_registry = None

    result = await manager.send_to_workstation("ws-5", {"type": "test"})
    assert result is False, "No registry should return False"


@pytest.mark.asyncio
async def test_no_publish_to_ws_channel():
    """Eliminar cualquier PUBLISH ws:{workstation_id} existente — nunca se publica a ws:*."""
    manager = RedisConnectionManager(redis_url="redis://localhost:6379/0")
    manager._redis_available = True
    manager._redis = AsyncMock()
    registry = AsyncMock()
    registry.find_worker_for_workstation = AsyncMock(return_value="worker_X")
    manager._worker_registry = registry

    await manager.send_to_workstation("ws-6", {"type": "test"})

    # Verificar que el canal NO es ws:{workstation_id}
    publish_call = manager._redis.publish.call_args
    channel = publish_call[0][0]
    assert not channel.startswith("ws:"), (
        f"No debe publicar a ws:* channels, pero publicó a {channel}"
    )
    assert channel == "worker:worker_X"


@pytest.mark.asyncio
async def test_enriched_payload_includes_org_id_from_message():
    """El payload enriquecido incluye organization_id del mensaje."""
    manager = RedisConnectionManager(redis_url="redis://localhost:6379/0")
    manager._redis_available = True
    manager._redis = AsyncMock()
    registry = AsyncMock()
    registry.find_worker_for_workstation = AsyncMock(return_value="worker_B")
    manager._worker_registry = registry

    await manager.send_to_workstation(
        "ws-7",
        {"type": "config_update", "organization_id": "org-ABC", "data": "test"},
    )

    payload = json.loads(manager._redis.publish.call_args[0][1])
    assert payload["target_workstation_id"] == "ws-7"
    assert payload["organization_id"] == "org-ABC"
    assert payload["data"] == "test"
    assert payload["type"] == "config_update"


@pytest.mark.asyncio
async def test_enriched_payload_uses_org_ids_fallback():
    """Si message no tiene organization_id, usa self.org_ids como fallback."""
    manager = RedisConnectionManager(redis_url="redis://localhost:6379/0")
    manager._redis_available = True
    manager._redis = AsyncMock()
    manager.org_ids["ws-8"] = "org-FALLBACK"
    registry = AsyncMock()
    registry.find_worker_for_workstation = AsyncMock(return_value="worker_C")
    manager._worker_registry = registry

    await manager.send_to_workstation("ws-8", {"type": "ping"})

    payload = json.loads(manager._redis.publish.call_args[0][1])
    assert payload["target_workstation_id"] == "ws-8"
    assert payload["organization_id"] == "org-FALLBACK"


@pytest.mark.asyncio
async def test_redis_connection_error_returns_false():
    """Si Redis falla durante la operación → return False."""
    import redis.asyncio as aioredis

    manager = RedisConnectionManager(redis_url="redis://localhost:6379/0")
    manager._redis_available = True
    manager._redis = AsyncMock()
    registry = AsyncMock()
    registry.find_worker_for_workstation = AsyncMock(
        side_effect=aioredis.ConnectionError("Connection lost")
    )
    manager._worker_registry = registry

    result = await manager.send_to_workstation("ws-9", {"type": "test"})
    assert result is False, "Should return False on Redis connection error"
