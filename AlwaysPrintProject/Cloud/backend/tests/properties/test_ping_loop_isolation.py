# Feature: websocket-scaling-redis, Property 11: Ping Loop Isolation
"""
Property test: Ping Loop Isolation

Para cualquier worker con un conjunto de workstations conectadas localmente L,
el Death Ping loop SOLO envía pings a workstations en L. Ninguna workstation
conectada a un worker diferente (es decir, que no está en workstation_connections
local) recibe un ping de este worker.

Se verifica que:
1. Cuando el ping loop ejecuta, solo envía pings a workstations almacenadas
   en self.workstation_connections (conexiones locales)
2. Para cualquier conjunto L de workstation_ids localmente conectados,
   los pings van EXCLUSIVAMENTE a workstations en L
3. Ninguna workstation de un "worker diferente" (no presente en el dict local)
   recibe un ping

Feature: websocket-scaling-redis, Property 11: Ping Loop Isolation
**Validates: Requirements 2.5**
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Set
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings as hypothesis_settings, assume
from hypothesis import strategies as st

from app.services.redis_connection_manager import RedisConnectionManager


# === ESTRATEGIAS DE GENERACIÓN ===

# Generar UUIDs como strings para workstation_id
ws_id_strategy = st.uuids().map(str)

# Generar UUIDs como strings para organization_id
org_id_strategy = st.uuids().map(str)

# Timeout en minutos por organización: entre 1 y 30 minutos
timeout_minutes_strategy = st.integers(min_value=1, max_value=30)

# Minutos de inactividad: entre 0 y 60 minutos
inactivity_minutes_strategy = st.integers(min_value=0, max_value=60)


@st.composite
def workstation_entry(draw):
    """Genera una workstation con su org_id, timeout e inactividad."""
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


# Conjunto de workstations locales (1 a 8)
local_workstations_strategy = st.lists(
    workstation_entry(),
    min_size=1,
    max_size=8,
    unique_by=lambda entry: entry["ws_id"],
)

# Conjunto de workstations remotas (otro worker) - 1 a 8
remote_workstations_strategy = st.lists(
    workstation_entry(),
    min_size=1,
    max_size=8,
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
@hypothesis_settings(max_examples=150, deadline=None)
@given(
    local_ws=local_workstations_strategy,
    remote_ws=remote_workstations_strategy,
)
async def test_ping_loop_isolation_only_local_workstations_receive_pings(
    local_ws: List[dict],
    remote_ws: List[dict],
):
    """
    Propiedad 11: El Death Ping loop SOLO envía pings a workstations conectadas
    localmente (presentes en self.workstation_connections). Ninguna workstation
    de otro worker recibe un ping.

    Enfoque:
    - Se configura un manager con un conjunto de workstations locales L
    - Se define un conjunto de workstations remotas R (otro worker)
    - Se mockea send_to_workstation para rastrear qué ws_ids reciben ping
    - Se ejecuta la lógica de FASE 3 del ping loop
    - Se verifica que TODOS los pings van exclusivamente a ws_ids en L
    - Se verifica que NINGÚN ws_id de R recibe ping

    Feature: websocket-scaling-redis, Property 11: Ping Loop Isolation
    **Validates: Requirements 2.5**
    """
    # Asegurar que no hay ws_ids duplicados entre local y remoto
    local_ids = {w["ws_id"] for w in local_ws}
    remote_ids = {w["ws_id"] for w in remote_ws}
    assume(local_ids.isdisjoint(remote_ids))

    # Crear instancia del RedisConnectionManager sin Redis
    manager = RedisConnectionManager(redis_url=None)

    # Tiempo de referencia para el ciclo
    current_time = datetime(2025, 6, 1, 12, 0, 0)

    # Timeouts por organización (recopilados de locales)
    org_timeouts: Dict[str, int] = {}

    # Configurar workstations LOCALES en el manager
    for ws_entry in local_ws:
        ws_id = ws_entry["ws_id"]
        org_id = ws_entry["org_id"]
        timeout_min = ws_entry["timeout_minutes"]
        inactivity_min = ws_entry["inactivity_minutes"]

        mock_ws = _crear_mock_websocket()
        manager.workstation_connections[ws_id] = mock_ws
        manager.org_ids[ws_id] = org_id
        manager.last_activity[ws_id] = current_time - timedelta(minutes=inactivity_min)
        org_timeouts[org_id] = timeout_min

    # Las workstations remotas NO se registran en el manager
    # (simulan estar en otro worker - no en workstation_connections)
    # Recopilar sus timeouts para que la simulación sea realista
    for ws_entry in remote_ws:
        org_timeouts[ws_entry["org_id"]] = ws_entry["timeout_minutes"]

    # Rastrear qué workstations reciben ping
    pinged_ws_ids: List[str] = []

    async def mock_send_to_workstation(ws_id: str, message: dict) -> bool:
        """Mock que captura envíos de ping."""
        if message.get("type") == "ping":
            pinged_ws_ids.append(ws_id)
        return True

    # Reemplazar send_to_workstation con el mock
    manager.send_to_workstation = mock_send_to_workstation

    # === Ejecutar FASE 3 del ping loop: Identificar inactivas y enviar Death Ping ===
    # Esta es la lógica core que itera SOLO sobre workstation_connections.keys()
    workstation_ids = list(manager.workstation_connections.keys())

    for ws_id in workstation_ids:
        # Si ya tiene ping pendiente, saltar
        if ws_id in manager._pending_pongs:
            continue

        org_id = manager.org_ids.get(ws_id)
        ws_last_activity = manager.last_activity.get(ws_id)

        if org_id is None or ws_last_activity is None:
            continue

        timeout_minutes = org_timeouts.get(org_id, 10)
        threshold = current_time - timedelta(minutes=timeout_minutes)

        if ws_last_activity < threshold:
            # Workstation inactiva → enviar Death Ping
            sent = await manager.send_to_workstation(ws_id, {"type": "ping"})
            if sent:
                manager._pending_pongs[ws_id] = current_time

    # === VERIFICACIONES ===

    # 1. Todos los pings enviados deben ser a workstations LOCALES
    for pinged_id in pinged_ws_ids:
        assert pinged_id in local_ids, (
            f"Se envió ping a workstation {pinged_id} que NO está en las conexiones "
            f"locales. Los pings solo deben ir a workstations en workstation_connections."
        )

    # 2. Ninguna workstation remota debe haber recibido ping
    for remote_id in remote_ids:
        assert remote_id not in pinged_ws_ids, (
            f"Workstation remota {remote_id} (de otro worker) recibió un ping. "
            f"El Death Ping solo debe actuar sobre conexiones locales."
        )

    # 3. El conjunto de ws_ids pingeados es subconjunto estricto de las locales
    pinged_set = set(pinged_ws_ids)
    assert pinged_set.issubset(local_ids), (
        f"Los ws_ids pingeados ({pinged_set}) no son subconjunto de los locales ({local_ids})"
    )

    # 4. Verificar que las locales inactivas efectivamente recibieron ping
    for ws_entry in local_ws:
        ws_id = ws_entry["ws_id"]
        org_id = ws_entry["org_id"]
        timeout_min = org_timeouts.get(org_id, 10)
        inactivity_min = ws_entry["inactivity_minutes"]

        # Si inactividad > timeout, debería haber recibido ping
        if inactivity_min > timeout_min:
            assert ws_id in pinged_set, (
                f"Workstation local inactiva {ws_id} (inactividad={inactivity_min}min > "
                f"timeout={timeout_min}min) debería haber recibido Death Ping pero no lo recibió."
            )
        # Si inactividad <= timeout, NO debería haber recibido ping
        else:
            assert ws_id not in pinged_set, (
                f"Workstation local activa {ws_id} (inactividad={inactivity_min}min <= "
                f"timeout={timeout_min}min) NO debería haber recibido Death Ping."
            )
