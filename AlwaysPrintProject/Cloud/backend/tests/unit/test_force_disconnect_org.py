"""
Tests unitarios para force_disconnect_organization / _close_local_org_workstations.

Contexto: tras restaurar un backup de BD, las workstations que seguían
conectadas quedan registradas en Redis bajo el WorkstationId anterior al
restore. force_disconnect_organization cierra esas conexiones (solo las de
la organización indicada) para forzar reconexión y re-registro contra los
datos ya restaurados.
"""

from unittest.mock import AsyncMock

import pytest

from app.services.redis_connection_manager import RedisConnectionManager
from app.services.websocket_manager import ConnectionManager


def _make_manager_with_connections(manager, connections: dict):
    """
    connections: {ws_id: org_id}. Crea un mock WebSocket por cada ws_id y lo
    registra en workstation_connections/org_ids. Devuelve {ws_id: mock_ws}.
    """
    mocks = {}
    for ws_id, org_id in connections.items():
        mock_ws = AsyncMock()
        manager.workstation_connections[ws_id] = mock_ws
        manager.org_ids[ws_id] = org_id
        mocks[ws_id] = mock_ws
    return mocks


class TestRedisConnectionManagerForceDisconnect:
    """RedisConnectionManager: cierre local + intento de publish cross-worker."""

    @pytest.mark.asyncio
    async def test_closes_only_matching_org_connections(self):
        manager = RedisConnectionManager(redis_url=None)  # sin Redis real
        mocks = _make_manager_with_connections(manager, {
            "ws-1": "org-A",
            "ws-2": "org-A",
            "ws-3": "org-B",
        })

        closed = await manager.force_disconnect_organization("org-A", reason="test")

        assert closed == 2
        mocks["ws-1"].close.assert_awaited_once_with(code=1001, reason="test")
        mocks["ws-2"].close.assert_awaited_once_with(code=1001, reason="test")
        mocks["ws-3"].close.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_connections_for_org_closes_nothing(self):
        manager = RedisConnectionManager(redis_url=None)
        _make_manager_with_connections(manager, {"ws-1": "org-B"})

        closed = await manager.force_disconnect_organization("org-A", reason="test")

        assert closed == 0

    @pytest.mark.asyncio
    async def test_does_not_raise_if_redis_unavailable(self):
        """Sin Redis conectado (_redis_available=False por defecto), el cierre
        local debe funcionar igual y no debe intentar publicar."""
        manager = RedisConnectionManager(redis_url=None)
        assert manager._redis_available is False
        _make_manager_with_connections(manager, {"ws-1": "org-A"})

        closed = await manager.force_disconnect_organization("org-A")

        assert closed == 1


class TestConnectionManagerForceDisconnect:
    """ConnectionManager (modo single-worker, sin Redis)."""

    @pytest.mark.asyncio
    async def test_closes_only_matching_org_connections(self):
        manager = ConnectionManager()
        mocks = _make_manager_with_connections(manager, {
            "ws-1": "org-A",
            "ws-2": "org-B",
        })

        closed = await manager.force_disconnect_organization("org-A", reason="test")

        assert closed == 1
        mocks["ws-1"].close.assert_awaited_once_with(code=1001, reason="test")
        mocks["ws-2"].close.assert_not_awaited()


class TestForceDisconnectAll:
    """
    force_disconnect_all: usado al final de un restore de BD completo, donde
    se reemplazan TODAS las organizaciones — a diferencia de
    force_disconnect_organization, no filtra por org_id en absoluto, así que
    también alcanza a conexiones cuyo org_id en vivo ya no existe en la BD
    restaurada (el caso que force_disconnect_organization por sí solo no
    puede cubrir).
    """

    @pytest.mark.asyncio
    async def test_redis_manager_closes_every_connection_regardless_of_org(self):
        manager = RedisConnectionManager(redis_url=None)
        mocks = _make_manager_with_connections(manager, {
            "ws-1": "org-A",
            "ws-2": "org-B",
            "ws-3": "org-organizacion-que-ya-no-existe-tras-el-restore",
        })

        closed = await manager.force_disconnect_all(reason="test")

        assert closed == 3
        for mock_ws in mocks.values():
            mock_ws.close.assert_awaited_once_with(code=1001, reason="test")

    @pytest.mark.asyncio
    async def test_connection_manager_closes_every_connection_regardless_of_org(self):
        manager = ConnectionManager()
        mocks = _make_manager_with_connections(manager, {
            "ws-1": "org-A",
            "ws-2": "org-B",
        })

        closed = await manager.force_disconnect_all(reason="test")

        assert closed == 2
        for mock_ws in mocks.values():
            mock_ws.close.assert_awaited_once_with(code=1001, reason="test")

    @pytest.mark.asyncio
    async def test_no_connections_returns_zero(self):
        manager = RedisConnectionManager(redis_url=None)

        closed = await manager.force_disconnect_all()

        assert closed == 0
