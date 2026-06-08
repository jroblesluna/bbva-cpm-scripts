# Feature: death-ping-optimization, Property 1: Actualización de last_activity
"""
Property test: Actualización de last_activity por mensaje recibido

Para cualquier workstation conectada, al invocar update_last_activity(ws_id),
el campo last_activity[ws_id] debe actualizarse a un timestamp >= al momento
previo a la llamada. Si la workstation NO está en workstation_connections,
update_last_activity NO debe agregarla a last_activity.

Feature: death-ping-optimization, Property 1: Actualización de last_activity
**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6**
"""

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock

import pytest
from hypothesis import given, settings as hypothesis_settings
from hypothesis import strategies as st

from app.services.websocket_manager import ConnectionManager


# === ESTRATEGIAS DE GENERACIÓN ===

# Generar workstation IDs realistas (UUID-like strings)
ws_id_strategy = st.text(
    alphabet=st.sampled_from("abcdef0123456789-"),
    min_size=8,
    max_size=36,
).filter(lambda s: len(s.strip("-")) > 0)

# Tipos de mensaje válidos que disparan update_last_activity
message_types = st.sampled_from([
    "register", "telemetry", "pong", "status_update", "connectivity_result"
])


# === PROPERTY TESTS ===


@pytest.mark.asyncio
@hypothesis_settings(max_examples=100, deadline=None)
@given(ws_id=ws_id_strategy, msg_type=message_types)
async def test_last_activity_updated_on_message(ws_id: str, msg_type: str):
    """
    Propiedad 1 (caso conectado): Para cualquier workstation conectada y
    cualquier tipo de mensaje válido, al recibir ese mensaje, last_activity
    se actualiza a un timestamp >= al momento previo a la llamada.

    Feature: death-ping-optimization, Property 1: Actualización de last_activity
    **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6**
    """
    # Crear instancia limpia del ConnectionManager
    manager = ConnectionManager()

    # Simular que la workstation ya está conectada
    mock_ws = AsyncMock()
    manager.workstation_connections[ws_id] = mock_ws
    # Inicializar last_activity con un timestamp antiguo
    old_time = datetime(2020, 1, 1, 0, 0, 0)
    manager.last_activity[ws_id] = old_time

    # Capturar timestamp antes de la llamada
    before_call = datetime.now(timezone.utc).replace(tzinfo=None)

    # Ejecutar update_last_activity (simula recibir un mensaje del tipo dado)
    await manager.update_last_activity(ws_id)

    # Verificar que last_activity se actualizó a un timestamp >= before_call
    updated_time = manager.last_activity[ws_id]
    assert updated_time >= before_call, (
        f"last_activity ({updated_time}) debería ser >= timestamp antes de la llamada "
        f"({before_call}) para ws_id='{ws_id}', msg_type='{msg_type}'"
    )
    # Verificar que el timestamp antiguo fue reemplazado
    assert updated_time > old_time, (
        f"last_activity ({updated_time}) debería ser > al timestamp antiguo "
        f"({old_time}) para ws_id='{ws_id}'"
    )


@pytest.mark.asyncio
@hypothesis_settings(max_examples=100, deadline=None)
@given(ws_id=ws_id_strategy)
async def test_last_activity_not_added_for_disconnected_ws(ws_id: str):
    """
    Propiedad 1 (caso no conectado): Si la workstation NO está en
    workstation_connections, update_last_activity NO debe agregarla
    a last_activity.

    Feature: death-ping-optimization, Property 1: Actualización de last_activity
    **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6**
    """
    # Crear instancia limpia del ConnectionManager
    manager = ConnectionManager()

    # NO registrar la workstation en workstation_connections
    # (el dict está vacío)

    # Ejecutar update_last_activity
    await manager.update_last_activity(ws_id)

    # Verificar que la workstation NO fue agregada a last_activity
    assert ws_id not in manager.last_activity, (
        f"ws_id='{ws_id}' no debería estar en last_activity porque no está conectada"
    )
    # Verificar que last_activity sigue vacío
    assert len(manager.last_activity) == 0, (
        "last_activity debería estar vacío para workstations no conectadas"
    )
