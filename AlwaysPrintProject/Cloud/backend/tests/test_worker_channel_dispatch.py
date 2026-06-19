"""
Property test para Task 7.3: Worker channel dispatch correctness (Property 4).

**Validates: Requirements 2.3, 2.4, 9.1**

Property 4: Para cualquier mensaje que llega al canal `worker:{worker_id}` con campo
`target_workstation_id`, SI la workstation está conectada localmente ENTONCES el
mensaje SE ENTREGA a su WebSocket, SI NO el mensaje SE DESCARTA sin error.
"""
import asyncio
from typing import Dict, List, Optional, Set
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings as hypothesis_settings, assume
from hypothesis import strategies as st

from app.services.redis_connection_manager import RedisConnectionManager


# === Estrategias de generación ===

# IDs tipo UUID (eficiente, sin regex)
uuid_strategy = st.uuids().map(str)

# Tipos de mensaje válidos (distintos de cmd_response)
message_type_strategy = st.sampled_from([
    "command", "status_request", "config_update", "ping", "data_sync",
    "action_execute", "health_check", "firmware_update",
])

# Payload extra (campos adicionales del mensaje)
extra_payload_strategy = st.dictionaries(
    keys=st.sampled_from(["data", "payload", "version", "timestamp", "flag", "count"]),
    values=st.one_of(
        st.text(min_size=0, max_size=20, alphabet=st.characters(categories=("L", "N"))),
        st.integers(min_value=-1000, max_value=1000),
        st.booleans(),
    ),
    min_size=0,
    max_size=3,
)


@st.composite
def local_workstations_strategy(draw):
    """
    Genera un conjunto de workstations conectadas localmente con sus org_ids.

    Retorna: Dict[workstation_id, organization_id] con 1-8 workstations.
    """
    num_ws = draw(st.integers(min_value=1, max_value=8))
    num_orgs = draw(st.integers(min_value=1, max_value=3))
    org_ids = [draw(uuid_strategy) for _ in range(num_orgs)]
    org_ids = list(set(org_ids))
    assume(len(org_ids) >= 1)

    connections: Dict[str, str] = {}
    for _ in range(num_ws):
        ws_id = draw(uuid_strategy)
        assume(ws_id not in connections)
        org_id = draw(st.sampled_from(org_ids))
        connections[ws_id] = org_id

    assume(len(connections) >= 1)
    return connections


@st.composite
def dispatch_scenario_delivered(draw):
    """
    Genera un escenario donde el target_workstation_id ESTÁ en las conexiones locales.

    Retorna:
    - local_connections: Dict[ws_id, org_id]
    - target_ws_id: workstation destino (está conectada localmente)
    - org_id: organization_id que coincide con la workstation destino
    - message_type: tipo de mensaje
    - extra_fields: campos extra del payload
    """
    local_connections = draw(local_workstations_strategy())
    target_ws_id = draw(st.sampled_from(list(local_connections.keys())))
    org_id = local_connections[target_ws_id]
    message_type = draw(message_type_strategy)
    extra_fields = draw(extra_payload_strategy)

    # Evitar colisión con campos reservados
    assume("target_workstation_id" not in extra_fields)
    assume("organization_id" not in extra_fields)
    assume("type" not in extra_fields)

    return local_connections, target_ws_id, org_id, message_type, extra_fields


@st.composite
def dispatch_scenario_discarded(draw):
    """
    Genera un escenario donde el target_workstation_id NO está en las conexiones locales.

    Retorna:
    - local_connections: Dict[ws_id, org_id]
    - target_ws_id: workstation destino (NO conectada localmente)
    - org_id: organization_id del mensaje
    - message_type: tipo de mensaje
    - extra_fields: campos extra del payload
    """
    local_connections = draw(local_workstations_strategy())
    target_ws_id = draw(uuid_strategy)
    assume(target_ws_id not in local_connections)
    org_id = draw(uuid_strategy)
    message_type = draw(message_type_strategy)
    extra_fields = draw(extra_payload_strategy)

    # Evitar colisión con campos reservados
    assume("target_workstation_id" not in extra_fields)
    assume("organization_id" not in extra_fields)
    assume("type" not in extra_fields)

    return local_connections, target_ws_id, org_id, message_type, extra_fields


# === Mock WebSocket ===

class MockWebSocket:
    """Mock de WebSocket que registra llamadas a send_json."""

    def __init__(self, ws_id: str):
        self.ws_id = ws_id
        self.sent_messages: List[dict] = []

    async def send_json(self, message: dict) -> None:
        """Registra el mensaje enviado."""
        self.sent_messages.append(message)


# === Helpers ===

def _crear_manager_con_conexiones(connections: Dict[str, str]) -> tuple:
    """
    Crea un RedisConnectionManager con conexiones mock pre-registradas.

    Args:
        connections: dict {workstation_id: organization_id}

    Returns:
        Tupla (manager, websockets_por_id) donde websockets_por_id es
        {workstation_id: MockWebSocket}
    """
    manager = RedisConnectionManager(redis_url=None)
    websockets: Dict[str, MockWebSocket] = {}

    for ws_id, org_id in connections.items():
        mock_ws = MockWebSocket(ws_id)
        websockets[ws_id] = mock_ws
        manager.workstation_connections[ws_id] = mock_ws
        manager.org_ids[ws_id] = org_id

    return manager, websockets


# === PROPERTY TESTS ===

class TestWorkerChannelDispatchCorrectness:
    """
    Property 4: Worker channel dispatch correctness.

    Para cualquier mensaje que llega al canal worker:{worker_id} con campo
    target_workstation_id:
    - Si la workstation está conectada localmente → se entrega a su WebSocket
    - Si la workstation NO está conectada localmente → se descarta sin error

    **Validates: Requirements 2.3, 2.4, 9.1**
    """

    @given(data=dispatch_scenario_delivered())
    @hypothesis_settings(max_examples=150, deadline=None)
    async def test_message_delivered_when_workstation_is_local(self, data):
        """
        **Validates: Requirements 2.3, 9.1**

        Cuando un mensaje llega por worker:{worker_id} con target_workstation_id
        que está conectada localmente, el mensaje SE ENTREGA a su WebSocket.
        """
        local_connections, target_ws_id, org_id, message_type, extra_fields = data

        manager, websockets = _crear_manager_con_conexiones(local_connections)

        # Construir payload como llegaría desde el listener Redis
        payload = {
            "type": message_type,
            "target_workstation_id": target_ws_id,
            "organization_id": org_id,
            **extra_fields,
        }

        # Llamar a _deliver_to_local_workstation (lo que el listener invoca)
        await manager._deliver_to_local_workstation(target_ws_id, payload)

        # Propiedad: la workstation target RECIBIÓ el mensaje
        target_ws = websockets[target_ws_id]
        assert len(target_ws.sent_messages) == 1, (
            f"La workstation '{target_ws_id}' debería haber recibido exactamente "
            f"1 mensaje pero recibió {len(target_ws.sent_messages)}"
        )
        assert target_ws.sent_messages[0] == payload, (
            f"El mensaje entregado no coincide con el payload. "
            f"Esperado: {payload}, Recibido: {target_ws.sent_messages[0]}"
        )

    @given(data=dispatch_scenario_delivered())
    @hypothesis_settings(max_examples=150, deadline=None)
    async def test_only_target_workstation_receives_message(self, data):
        """
        **Validates: Requirements 2.3, 9.1**

        Cuando un mensaje se entrega a una workstation local, NINGUNA otra
        workstation conectada en el mismo worker recibe el mensaje.
        """
        local_connections, target_ws_id, org_id, message_type, extra_fields = data

        manager, websockets = _crear_manager_con_conexiones(local_connections)

        payload = {
            "type": message_type,
            "target_workstation_id": target_ws_id,
            "organization_id": org_id,
            **extra_fields,
        }

        await manager._deliver_to_local_workstation(target_ws_id, payload)

        # Propiedad: solo la target recibe, las demás NO
        for ws_id, mock_ws in websockets.items():
            if ws_id != target_ws_id:
                assert len(mock_ws.sent_messages) == 0, (
                    f"La workstation '{ws_id}' NO debería haber recibido el mensaje "
                    f"dirigido a '{target_ws_id}', pero recibió "
                    f"{len(mock_ws.sent_messages)}: {mock_ws.sent_messages}"
                )

    @given(data=dispatch_scenario_discarded())
    @hypothesis_settings(max_examples=150, deadline=None)
    async def test_message_discarded_when_workstation_not_local(self, data):
        """
        **Validates: Requirements 2.4, 9.1**

        Cuando un mensaje llega por worker:{worker_id} con target_workstation_id
        que NO está conectada localmente, el mensaje SE DESCARTA sin error y
        ninguna otra workstation lo recibe.
        """
        local_connections, target_ws_id, org_id, message_type, extra_fields = data

        manager, websockets = _crear_manager_con_conexiones(local_connections)

        payload = {
            "type": message_type,
            "target_workstation_id": target_ws_id,
            "organization_id": org_id,
            **extra_fields,
        }

        # Debe completar sin lanzar excepción
        await manager._deliver_to_local_workstation(target_ws_id, payload)

        # Propiedad: NINGUNA workstation local recibe el mensaje
        for ws_id, mock_ws in websockets.items():
            assert len(mock_ws.sent_messages) == 0, (
                f"La workstation '{ws_id}' recibió un mensaje dirigido a "
                f"'{target_ws_id}' (no conectada localmente). "
                f"Mensajes recibidos: {mock_ws.sent_messages}"
            )

    @given(data=dispatch_scenario_discarded())
    @hypothesis_settings(max_examples=100, deadline=None)
    async def test_discard_raises_no_exception(self, data):
        """
        **Validates: Requirements 2.4**

        El descarte de mensajes para workstations no locales NUNCA lanza
        excepción, independientemente del contenido del payload.
        """
        local_connections, target_ws_id, org_id, message_type, extra_fields = data

        manager, websockets = _crear_manager_con_conexiones(local_connections)

        payload = {
            "type": message_type,
            "target_workstation_id": target_ws_id,
            "organization_id": org_id,
            **extra_fields,
        }

        # No debe lanzar excepción de ningún tipo
        try:
            await manager._deliver_to_local_workstation(target_ws_id, payload)
        except Exception as e:
            pytest.fail(
                f"_deliver_to_local_workstation lanzó excepción para workstation "
                f"no conectada '{target_ws_id}': {type(e).__name__}: {e}"
            )

    @given(
        local_connections=local_workstations_strategy(),
        message_type=message_type_strategy,
    )
    @hypothesis_settings(max_examples=100, deadline=None)
    async def test_tenant_validation_allows_matching_org(self, local_connections, message_type):
        """
        **Validates: Requirements 2.3, 9.1**

        Cuando el organization_id del mensaje coincide con el registrado para la
        workstation destino, la entrega procede correctamente (tenant validation pasa).
        """
        target_ws_id = list(local_connections.keys())[0]
        matching_org_id = local_connections[target_ws_id]

        manager, websockets = _crear_manager_con_conexiones(local_connections)

        # Payload con org_id que COINCIDE con la workstation
        payload = {
            "type": message_type,
            "target_workstation_id": target_ws_id,
            "organization_id": matching_org_id,
        }

        await manager._deliver_to_local_workstation(target_ws_id, payload)

        # Propiedad: mensaje entregado porque tenant validation pasa
        target_ws = websockets[target_ws_id]
        assert len(target_ws.sent_messages) == 1, (
            f"Con org_id coincidente ({matching_org_id}), la workstation "
            f"'{target_ws_id}' debería recibir el mensaje pero no lo recibió"
        )

    @given(
        local_connections=local_workstations_strategy(),
        mismatched_org_id=uuid_strategy,
        message_type=message_type_strategy,
    )
    @hypothesis_settings(max_examples=100, deadline=None)
    async def test_tenant_validation_rejects_mismatched_org(
        self, local_connections, mismatched_org_id, message_type
    ):
        """
        **Validates: Requirements 2.3, 9.1**

        Cuando el organization_id del mensaje NO coincide con el registrado para la
        workstation destino, el mensaje se descarta (tenant validation falla).
        """
        target_ws_id = list(local_connections.keys())[0]
        ws_org_id = local_connections[target_ws_id]

        # Asegurar que el org_id del mensaje es diferente al de la workstation
        assume(mismatched_org_id != ws_org_id)

        manager, websockets = _crear_manager_con_conexiones(local_connections)

        # Payload con org_id que NO coincide con la workstation
        payload = {
            "type": message_type,
            "target_workstation_id": target_ws_id,
            "organization_id": mismatched_org_id,
        }

        await manager._deliver_to_local_workstation(target_ws_id, payload)

        # Propiedad: mensaje descartado por validación de tenant
        target_ws = websockets[target_ws_id]
        assert len(target_ws.sent_messages) == 0, (
            f"Con org_id no coincidente (mensaje: {mismatched_org_id}, "
            f"workstation: {ws_org_id}), la workstation '{target_ws_id}' "
            f"NO debería recibir el mensaje pero lo recibió: "
            f"{target_ws.sent_messages}"
        )
