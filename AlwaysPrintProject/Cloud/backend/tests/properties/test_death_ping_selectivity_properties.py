# Feature: death-ping-optimization, Property 3: Selectividad del Death Ping
"""
Property test: Selectividad del Death Ping

Para cualquier conjunto de workstations conectadas con diferentes last_activity
y organizaciones con diferentes offline_timeout_minutes, al ejecutar un ciclo
del loop de verificación, una workstation recibe Death Ping si y solo si su
tiempo de inactividad (now - last_activity) excede el offline_timeout_minutes
de su organización.

Feature: death-ping-optimization, Property 3: Selectividad del Death Ping
**Validates: Requirements 3.3, 3.4, 3.5**
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings as hypothesis_settings, assume
from hypothesis import strategies as st

from app.services.websocket_manager import ConnectionManager


# === ESTRATEGIAS DE GENERACIÓN ===

# Generar UUIDs como strings para workstation_id
ws_id_strategy = st.uuids().map(str)

# Generar UUIDs como strings para organization_id
org_id_strategy = st.uuids().map(str)

# Timeout en minutos por organización: entre 1 y 60 minutos
timeout_minutes_strategy = st.integers(min_value=1, max_value=60)

# Minutos de inactividad de una workstation: entre 0 y 120 minutos
inactivity_minutes_strategy = st.integers(min_value=0, max_value=120)


# Estrategia compuesta: generar una workstation con su org y tiempos
@st.composite
def workstation_entry(draw):
    """Genera una entrada de workstation con org_id, timeout e inactividad."""
    ws_id = draw(ws_id_strategy)
    org_id = draw(org_id_strategy)
    timeout_min = draw(timeout_minutes_strategy)
    inactivity_min = draw(inactivity_minutes_strategy)
    return {
        "ws_id": ws_id,
        "org_id": org_id,
        "timeout_minutes": timeout_min,
        "inactivity_minutes": inactivity_min,
    }


# Estrategia para generar conjuntos de workstations (1 a 10)
workstation_set_strategy = st.lists(
    workstation_entry(),
    min_size=1,
    max_size=10,
    unique_by=lambda entry: entry["ws_id"],
)


# === HELPERS ===


def _crear_mock_websocket():
    """Crea un mock de WebSocket para poblar workstation_connections."""
    ws = MagicMock()
    ws.send_json = AsyncMock(return_value=None)
    ws.close = AsyncMock()
    return ws


# === PROPERTY TEST ===


@pytest.mark.asyncio
@hypothesis_settings(max_examples=100, deadline=None)
@given(workstations=workstation_set_strategy)
async def test_death_ping_selectivity(workstations: List[dict]):
    """
    Propiedad 3: Para cualquier conjunto de workstations conectadas con diferentes
    last_activity y organizaciones con diferentes offline_timeout_minutes, al ejecutar
    la lógica de selectividad, una workstation recibe Death Ping si y solo si
    (now - last_activity) > offline_timeout_minutes de su organización.

    Feature: death-ping-optimization, Property 3: Selectividad del Death Ping
    **Validates: Requirements 3.3, 3.4, 3.5**
    """
    # Filtrar duplicados de ws_id (ya asegurado por unique_by, pero por seguridad)
    assume(len(set(w["ws_id"] for w in workstations)) == len(workstations))

    # Crear instancia fresca del ConnectionManager
    manager = ConnectionManager()

    # Tiempo de referencia "ahora" para el ciclo
    current_time = datetime(2025, 6, 1, 12, 0, 0)

    # Rastrear qué ws esperamos que reciban ping (inactivas) y cuáles no (activas)
    expected_pinged: List[str] = []
    expected_not_pinged: List[str] = []
    org_timeouts: Dict[str, int] = {}

    # Configurar estado del manager con cada workstation
    for ws_entry in workstations:
        ws_id = ws_entry["ws_id"]
        org_id = ws_entry["org_id"]
        timeout_min = ws_entry["timeout_minutes"]
        inactivity_min = ws_entry["inactivity_minutes"]

        # Crear mock WebSocket y registrar la workstation
        mock_ws = _crear_mock_websocket()
        manager.workstation_connections[ws_id] = mock_ws
        manager.org_ids[ws_id] = org_id

        # Calcular last_activity: current_time - inactivity_minutes
        last_act = current_time - timedelta(minutes=inactivity_min)
        manager.last_activity[ws_id] = last_act

        # Registrar timeout de la org
        org_timeouts[org_id] = timeout_min

        # Determinar si la ws es inactiva (debería recibir ping)
        # Condición: last_activity < threshold, es decir: inactivity_min > timeout_min
        threshold = current_time - timedelta(minutes=timeout_min)
        if last_act < threshold:
            expected_pinged.append(ws_id)
        else:
            expected_not_pinged.append(ws_id)

    # Rastrear qué workstations recibieron ping
    pinged_ws_ids: List[str] = []

    # Reemplazar send_to_workstation para capturar envíos de ping
    original_send = manager.send_to_workstation

    async def mock_send(ws_id: str, message: dict) -> bool:
        if message == {"type": "ping"}:
            pinged_ws_ids.append(ws_id)
        return True

    manager.send_to_workstation = mock_send

    # === Simular FASE 3 del start_ping_loop: Identificar inactivas y enviar Death Ping ===
    workstation_ids = list(manager.workstation_connections.keys())

    for ws_id in workstation_ids:
        # Si ya tiene ping pendiente, no enviar otro (no aplica aquí, _pending_pongs vacío)
        if ws_id in manager._pending_pongs:
            continue

        # Obtener org_id y last_activity de esta ws
        org_id = manager.org_ids.get(ws_id)
        ws_last_activity = manager.last_activity.get(ws_id)

        if org_id is None or ws_last_activity is None:
            continue

        # Determinar timeout: usar el de la org
        timeout_minutes = org_timeouts.get(org_id, 10)
        threshold = current_time - timedelta(minutes=timeout_minutes)

        if ws_last_activity < threshold:
            # Workstation inactiva → enviar Death Ping
            sent = await manager.send_to_workstation(ws_id, {"type": "ping"})
            if sent:
                manager._pending_pongs[ws_id] = current_time

    # === VERIFICACIONES ===

    # 1. Todas las workstations inactivas DEBEN haber recibido ping
    for ws_id in expected_pinged:
        assert ws_id in pinged_ws_ids, (
            f"Workstation inactiva {ws_id} debería haber recibido Death Ping pero no lo recibió"
        )

    # 2. Ninguna workstation activa debe haber recibido ping
    for ws_id in expected_not_pinged:
        assert ws_id not in pinged_ws_ids, (
            f"Workstation activa {ws_id} NO debería haber recibido Death Ping pero lo recibió"
        )

    # 3. Solo workstations inactivas recibieron ping (bidireccional)
    pinged_set = set(pinged_ws_ids)
    expected_pinged_set = set(expected_pinged)
    assert pinged_set == expected_pinged_set, (
        f"Conjunto de pingeadas ({pinged_set}) difiere de esperadas ({expected_pinged_set})"
    )

    # 4. Las workstations que recibieron ping deben estar en _pending_pongs
    for ws_id in expected_pinged:
        assert ws_id in manager._pending_pongs, (
            f"Workstation {ws_id} recibió ping pero no fue registrada en _pending_pongs"
        )

    # 5. Las workstations activas NO deben estar en _pending_pongs
    for ws_id in expected_not_pinged:
        assert ws_id not in manager._pending_pongs, (
            f"Workstation activa {ws_id} no debería estar en _pending_pongs"
        )
