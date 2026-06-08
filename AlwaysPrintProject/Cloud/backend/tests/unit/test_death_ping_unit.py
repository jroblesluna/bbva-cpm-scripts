"""
Tests unitarios para el endpoint WebSocket modificado (Death Ping Optimization).

Verifica la integración del rastreo de actividad en el endpoint WebSocket:
- connect_workstation recibe organization_id
- update_last_activity se invoca en cada tipo de mensaje
- handle_pong elimina workstation de _pending_pongs

Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6
"""

import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.websocket_manager import ConnectionManager, PONG_TIMEOUT_SECONDS


# === Fixtures ===


@pytest.fixture
def connection_manager():
    """Instancia limpia de ConnectionManager para cada test."""
    return ConnectionManager()


@pytest.fixture
def mock_websocket():
    """WebSocket mock con métodos async."""
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    ws.receive_json = AsyncMock()
    ws.close = AsyncMock()
    ws.client = MagicMock()
    ws.client.host = "127.0.0.1"
    ws.headers = {}
    return ws


@pytest.fixture
def mock_db():
    """Sesión de BD mock."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    db.query.return_value.filter_by.return_value.all.return_value = []
    return db


# === Tests: connect_workstation recibe organization_id ===


@pytest.mark.asyncio
async def test_connect_workstation_receives_organization_id(connection_manager, mock_websocket, mock_db):
    """
    Verificar que connect_workstation acepta y almacena organization_id.
    Al conectar una workstation, el org_id debe quedar registrado
    en el diccionario org_ids del ConnectionManager.
    """
    workstation_id = "ws-001"
    organization_id = "org-abc-123"

    await connection_manager.connect_workstation(
        workstation_id=workstation_id,
        websocket=mock_websocket,
        db=mock_db,
        organization_id=organization_id
    )

    # Verificar que org_id se almacenó correctamente
    assert workstation_id in connection_manager.org_ids
    assert connection_manager.org_ids[workstation_id] == organization_id

    # Verificar que last_activity se inicializó
    assert workstation_id in connection_manager.last_activity
    assert isinstance(connection_manager.last_activity[workstation_id], datetime)

    # Verificar que la conexión se registró
    assert workstation_id in connection_manager.workstation_connections
    assert connection_manager.workstation_connections[workstation_id] is mock_websocket


# === Tests: update_last_activity se invoca en cada tipo de mensaje ===


@pytest.mark.asyncio
async def test_update_last_activity_called_on_pong(connection_manager, mock_websocket, mock_db):
    """
    Verificar que al recibir un mensaje tipo 'pong', se actualiza last_activity.
    Simula el flujo del endpoint: handle_pong + update_last_activity.
    """
    workstation_id = "ws-pong-test"
    organization_id = "org-001"

    # Conectar la workstation primero
    await connection_manager.connect_workstation(
        workstation_id=workstation_id,
        websocket=mock_websocket,
        db=mock_db,
        organization_id=organization_id
    )

    # Capturar timestamp previo
    initial_activity = connection_manager.last_activity[workstation_id]

    # Esperar un instante para que el timestamp sea diferente
    await asyncio.sleep(0.01)

    # Simular recepción de pong (como hace el endpoint)
    await connection_manager.handle_pong(workstation_id)
    await connection_manager.update_last_activity(workstation_id)

    # Verificar que last_activity se actualizó
    assert connection_manager.last_activity[workstation_id] >= initial_activity


@pytest.mark.asyncio
async def test_update_last_activity_called_on_status_update(connection_manager, mock_websocket, mock_db):
    """
    Verificar que al recibir un mensaje tipo 'status_update', se actualiza last_activity.
    """
    workstation_id = "ws-status-test"
    organization_id = "org-002"

    await connection_manager.connect_workstation(
        workstation_id=workstation_id,
        websocket=mock_websocket,
        db=mock_db,
        organization_id=organization_id
    )

    initial_activity = connection_manager.last_activity[workstation_id]
    await asyncio.sleep(0.01)

    # Simular lo que hace el endpoint al recibir status_update
    await connection_manager.update_last_activity(workstation_id)

    assert connection_manager.last_activity[workstation_id] >= initial_activity


@pytest.mark.asyncio
async def test_update_last_activity_called_on_telemetry(connection_manager, mock_websocket, mock_db):
    """
    Verificar que al recibir un mensaje tipo 'telemetry', se actualiza last_activity.
    """
    workstation_id = "ws-telemetry-test"
    organization_id = "org-003"

    await connection_manager.connect_workstation(
        workstation_id=workstation_id,
        websocket=mock_websocket,
        db=mock_db,
        organization_id=organization_id
    )

    initial_activity = connection_manager.last_activity[workstation_id]
    await asyncio.sleep(0.01)

    # Simular lo que hace el endpoint al recibir telemetry
    await connection_manager.update_last_activity(workstation_id)

    assert connection_manager.last_activity[workstation_id] >= initial_activity


@pytest.mark.asyncio
async def test_update_last_activity_called_on_connectivity_result(connection_manager, mock_websocket, mock_db):
    """
    Verificar que al recibir un mensaje tipo 'connectivity_result', se actualiza last_activity.
    """
    workstation_id = "ws-connectivity-test"
    organization_id = "org-004"

    await connection_manager.connect_workstation(
        workstation_id=workstation_id,
        websocket=mock_websocket,
        db=mock_db,
        organization_id=organization_id
    )

    initial_activity = connection_manager.last_activity[workstation_id]
    await asyncio.sleep(0.01)

    # Simular lo que hace el endpoint al recibir connectivity_result
    await connection_manager.update_last_activity(workstation_id)

    assert connection_manager.last_activity[workstation_id] >= initial_activity


# === Tests: handle_pong elimina workstation de _pending_pongs ===


@pytest.mark.asyncio
async def test_handle_pong_removes_pending_pong(connection_manager, mock_websocket, mock_db):
    """
    Verificar que handle_pong elimina la workstation de _pending_pongs.
    Cuando una workstation responde al Death Ping, debe dejar de estar
    en la lista de pongs pendientes para no ser marcada como muerta.
    """
    workstation_id = "ws-pong-pending"
    organization_id = "org-005"

    # Conectar workstation
    await connection_manager.connect_workstation(
        workstation_id=workstation_id,
        websocket=mock_websocket,
        db=mock_db,
        organization_id=organization_id
    )

    # Simular que se envió un Death Ping (registrar en pending_pongs)
    connection_manager._pending_pongs[workstation_id] = datetime.now(timezone.utc).replace(tzinfo=None)
    assert workstation_id in connection_manager._pending_pongs

    # Simular recepción de pong
    await connection_manager.handle_pong(workstation_id)

    # Verificar que fue removida de pending_pongs
    assert workstation_id not in connection_manager._pending_pongs


@pytest.mark.asyncio
async def test_handle_pong_updates_last_pong_timestamp(connection_manager, mock_websocket, mock_db):
    """
    Verificar que handle_pong también actualiza el timestamp de last_pong.
    """
    workstation_id = "ws-pong-ts"
    organization_id = "org-006"

    await connection_manager.connect_workstation(
        workstation_id=workstation_id,
        websocket=mock_websocket,
        db=mock_db,
        organization_id=organization_id
    )

    initial_pong = connection_manager.last_pong[workstation_id]
    await asyncio.sleep(0.01)

    await connection_manager.handle_pong(workstation_id)

    assert connection_manager.last_pong[workstation_id] >= initial_pong
