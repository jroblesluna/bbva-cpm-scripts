# Feature: death-ping-optimization, Property 5: Limpieza completa en desconexión
"""
Property test: Limpieza completa en desconexión

Para cualquier workstation marcada como muerta, después de ejecutar disconnect_workstation,
esa workstation no debe existir en workstation_connections, last_activity, org_ids,
last_pong ni _pending_pongs.

Feature: death-ping-optimization, Property 5: Limpieza completa en desconexión
**Validates: Requirements 5.2, 5.3**
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from hypothesis import given, settings as hypothesis_settings
from hypothesis import strategies as st

from app.services.websocket_manager import ConnectionManager


# === ESTRATEGIAS DE GENERACIÓN ===

# Generar UUIDs como strings válidos para workstation_id
ws_id_strategy = st.uuids().map(str)

# Generar UUIDs como strings válidos para organization_id
org_id_strategy = st.uuids().map(str)


# === HELPERS ===


def _crear_mock_websocket():
    """Crea un mock de WebSocket para poblar workstation_connections."""
    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    return ws


def _crear_mock_db():
    """Crea un mock de sesión de BD para disconnect_workstation."""
    db = MagicMock()
    db.query = MagicMock(return_value=MagicMock())
    db.commit = MagicMock()
    db.rollback = MagicMock()
    return db


# === PROPERTY TEST ===


@hypothesis_settings(max_examples=100, deadline=None)
@given(
    ws_id=ws_id_strategy,
    org_id=org_id_strategy,
)
def test_disconnect_cleanup_removes_from_all_dicts(ws_id: str, org_id: str):
    """
    Propiedad 5: Para cualquier workstation que se desconecta, después de
    disconnect_workstation, el ws_id NO debe existir en ninguno de los dicts:
    workstation_connections, last_activity, org_ids, last_pong, _pending_pongs.

    Feature: death-ping-optimization, Property 5: Limpieza completa en desconexión
    **Validates: Requirements 5.2, 5.3**
    """
    # Crear instancia fresca del ConnectionManager
    manager = ConnectionManager()

    # Poblar TODOS los dicts con la workstation generada
    mock_ws = _crear_mock_websocket()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    manager.workstation_connections[ws_id] = mock_ws
    manager.last_pong[ws_id] = now
    manager.last_activity[ws_id] = now
    manager.org_ids[ws_id] = org_id
    manager._pending_pongs[ws_id] = now

    # Verificar que están presentes antes de desconectar
    assert ws_id in manager.workstation_connections
    assert ws_id in manager.last_pong
    assert ws_id in manager.last_activity
    assert ws_id in manager.org_ids
    assert ws_id in manager._pending_pongs

    # Ejecutar disconnect_workstation con mock de BD
    mock_db = _crear_mock_db()

    with patch(
        "app.services.websocket_manager.WorkstationService"
    ):
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(manager.disconnect_workstation(ws_id, mock_db))
        finally:
            loop.close()

    # Verificar limpieza completa — ws_id NO debe existir en ningún dict
    assert ws_id not in manager.workstation_connections, (
        f"workstation_connections aún contiene {ws_id} después de disconnect"
    )
    assert ws_id not in manager.last_pong, (
        f"last_pong aún contiene {ws_id} después de disconnect"
    )
    assert ws_id not in manager.last_activity, (
        f"last_activity aún contiene {ws_id} después de disconnect"
    )
    assert ws_id not in manager.org_ids, (
        f"org_ids aún contiene {ws_id} después de disconnect"
    )
    assert ws_id not in manager._pending_pongs, (
        f"_pending_pongs aún contiene {ws_id} después de disconnect"
    )
