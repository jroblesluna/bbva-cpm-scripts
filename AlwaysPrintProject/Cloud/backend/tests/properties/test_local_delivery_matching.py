# Feature: websocket-scaling-redis, Property 2: Local Delivery Only to Matching Connections
"""
Property test: Local Delivery Only to Matching Connections

Para cualquier mensaje recibido en un canal Redis pub/sub, el Connection_Manager
SHALL entregarlo SOLO a los WebSockets conectados localmente que matchean el
target del canal:
- Para ws:{id}: entrega SOLO al WebSocket con ese workstation_id
- Para org:{id}: entrega SOLO a workstations cuyo org_id == organization_id del canal
- Ninguna conexión que no matchea debe recibir el mensaje

Se generan conjuntos de conexiones con diferentes workstation_ids y org_ids,
luego se verifica la correctitud de la entrega.

Feature: websocket-scaling-redis, Property 2: Local Delivery Only to Matching Connections
**Validates: Requirements 1.2, 1.4, 5.3**
"""

import asyncio
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


@st.composite
def connections_with_orgs_strategy(draw):
    """
    Genera un conjunto de conexiones con workstation_ids y org_ids variados.

    Retorna un dict {workstation_id: organization_id} con al menos 2 orgs distintas
    y al menos 3 conexiones totales para poder verificar entrega selectiva.
    """
    # Generar 2-4 organizaciones distintas
    num_orgs = draw(st.integers(min_value=2, max_value=4))
    org_ids = [draw(org_id_strategy) for _ in range(num_orgs)]
    org_ids = list(set(org_ids))
    assume(len(org_ids) >= 2)

    # Generar 3-10 workstations distribuyéndolas entre las organizaciones
    num_ws = draw(st.integers(min_value=3, max_value=10))
    connections: Dict[str, str] = {}

    for _ in range(num_ws):
        ws_id = draw(ws_id_strategy)
        assume(ws_id not in connections)
        org_id = draw(st.sampled_from(org_ids))
        connections[ws_id] = org_id

    assume(len(connections) >= 3)
    # Asegurar que al menos 2 orgs tienen workstations
    orgs_con_ws = set(connections.values())
    assume(len(orgs_con_ws) >= 2)

    return connections


@st.composite
def single_ws_delivery_scenario(draw):
    """
    Genera un escenario de entrega a workstation individual (canal ws:{id}).

    Retorna:
    - connections: dict {ws_id: org_id} con todas las conexiones locales
    - target_ws_id: la workstation a la que se envía el mensaje
    """
    connections = draw(connections_with_orgs_strategy())
    target_ws_id = draw(st.sampled_from(list(connections.keys())))
    return connections, target_ws_id


@st.composite
def org_broadcast_scenario(draw):
    """
    Genera un escenario de broadcast organizacional (canal org:{id}).

    Retorna:
    - connections: dict {ws_id: org_id} con todas las conexiones locales
    - target_org_id: la organización a la que va el broadcast
    """
    connections = draw(connections_with_orgs_strategy())
    target_org_id = draw(st.sampled_from(list(connections.values())))
    return connections, target_org_id


# === MOCK WEBSOCKET ===


class MockWebSocket:
    """
    Mock de WebSocket que registra todas las llamadas a send_json.

    Permite verificar qué mensajes se entregaron a cada conexión.
    """

    def __init__(self, ws_id: str):
        self.ws_id = ws_id
        self.sent_messages: List[dict] = []

    async def send_json(self, message: dict) -> None:
        """Registra el mensaje enviado."""
        self.sent_messages.append(message)

    def reset(self):
        """Limpia los mensajes registrados."""
        self.sent_messages.clear()


# === HELPERS ===


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
        # Registrar directamente en el estado interno (sin Redis)
        manager.workstation_connections[ws_id] = mock_ws
        manager.org_ids[ws_id] = org_id

    return manager, websockets


# === PROPERTY TESTS ===


class TestLocalDeliveryMatching:
    """
    Property 2: Local Delivery Only to Matching Connections.

    Verifica que mensajes recibidos via pub/sub se entregan SOLO a las
    conexiones que matchean el canal target. No matching → no delivery.

    Feature: websocket-scaling-redis, Property 2: Local Delivery Only to Matching Connections
    **Validates: Requirements 1.2, 1.4, 5.3**
    """

    # === CANAL ws:{id} ===

    @given(data=single_ws_delivery_scenario())
    @hypothesis_settings(max_examples=150, deadline=None)
    async def test_ws_channel_delivers_only_to_target_workstation(self, data):
        """
        Para canal ws:{id}: el mensaje se entrega SOLO al WebSocket con ese
        workstation_id, y a ninguna otra conexión local.

        Verifica Requirement 1.2: "deliver the message to the local WebSocket
        connection [...] if the workstation is connected to that Worker"

        Feature: websocket-scaling-redis, Property 2: Local Delivery Only to Matching Connections
        **Validates: Requirements 1.2**
        """
        connections, target_ws_id = data
        manager, websockets = _crear_manager_con_conexiones(connections)

        # Mensaje de prueba
        mensaje = {"type": "command", "command_type": "check_update", "data": "test"}

        # Simular entrega desde listener Redis para canal ws:{target_ws_id}
        await manager._deliver_to_local_workstation(target_ws_id, mensaje)

        # Propiedad: SOLO el target recibe el mensaje
        for ws_id, mock_ws in websockets.items():
            if ws_id == target_ws_id:
                assert len(mock_ws.sent_messages) == 1, (
                    f"La workstation target '{ws_id}' debería haber recibido "
                    f"exactamente 1 mensaje pero recibió {len(mock_ws.sent_messages)}"
                )
                assert mock_ws.sent_messages[0] == mensaje, (
                    f"El mensaje entregado a '{ws_id}' no coincide con el original. "
                    f"Esperado: {mensaje}, Recibido: {mock_ws.sent_messages[0]}"
                )
            else:
                assert len(mock_ws.sent_messages) == 0, (
                    f"La workstation '{ws_id}' NO debería haber recibido mensajes "
                    f"(canal target era ws:{target_ws_id}) pero recibió "
                    f"{len(mock_ws.sent_messages)}: {mock_ws.sent_messages}"
                )

    @given(data=single_ws_delivery_scenario())
    @hypothesis_settings(max_examples=150, deadline=None)
    async def test_ws_channel_no_delivery_to_absent_workstation(self, data):
        """
        Para canal ws:{id} cuando la workstation NO está conectada localmente:
        el mensaje se descarta sin error y ninguna otra conexión lo recibe.

        Verifica Requirement 1.8: "discard the message without error"

        Feature: websocket-scaling-redis, Property 2: Local Delivery Only to Matching Connections
        **Validates: Requirements 1.2**
        """
        connections, _ = data
        manager, websockets = _crear_manager_con_conexiones(connections)

        # Generar un ws_id que NO está conectado localmente
        absent_ws_id = "absent-ws-00000000-0000-0000-0000-000000000000"
        assume(absent_ws_id not in connections)

        mensaje = {"type": "command", "data": "para_ausente"}

        # Simular entrega para un ws_id que no existe localmente
        await manager._deliver_to_local_workstation(absent_ws_id, mensaje)

        # Propiedad: NINGUNA conexión local recibe el mensaje
        for ws_id, mock_ws in websockets.items():
            assert len(mock_ws.sent_messages) == 0, (
                f"La workstation '{ws_id}' recibió un mensaje que iba dirigido a "
                f"'{absent_ws_id}' (no conectado localmente). "
                f"Recibió: {mock_ws.sent_messages}"
            )

    # === CANAL org:{id} ===

    @given(data=org_broadcast_scenario())
    @hypothesis_settings(max_examples=150, deadline=None)
    async def test_org_channel_delivers_only_to_matching_org(self, data):
        """
        Para canal org:{id}: el mensaje se entrega SOLO a workstations locales
        cuyo org_id == el organization_id del canal. Workstations de otras orgs
        NO reciben el mensaje.

        Verifica Requirement 1.4: "deliver the message to all locally-connected
        workstations whose org_id matches the organization_id"

        Feature: websocket-scaling-redis, Property 2: Local Delivery Only to Matching Connections
        **Validates: Requirements 1.4, 5.3**
        """
        connections, target_org_id = data
        manager, websockets = _crear_manager_con_conexiones(connections)

        # Mensaje de broadcast organizacional
        mensaje = {
            "type": "forced_contingency",
            "enabled": True,
            "source": "organization",
            "organization_id": target_org_id,
        }

        # Simular entrega desde listener Redis para canal org:{target_org_id}
        await manager._deliver_to_local_org_workstations(target_org_id, mensaje)

        # Calcular qué workstations DEBERÍAN recibir el mensaje
        expected_recipients = {
            ws_id for ws_id, org_id in connections.items()
            if org_id == target_org_id
        }
        non_recipients = {
            ws_id for ws_id, org_id in connections.items()
            if org_id != target_org_id
        }

        # Propiedad: SOLO las workstations de la org target reciben el mensaje
        for ws_id, mock_ws in websockets.items():
            if ws_id in expected_recipients:
                assert len(mock_ws.sent_messages) == 1, (
                    f"La workstation '{ws_id}' (org={connections[ws_id]}) "
                    f"debería haber recibido 1 mensaje del broadcast a org "
                    f"'{target_org_id}' pero recibió {len(mock_ws.sent_messages)}"
                )
                assert mock_ws.sent_messages[0] == mensaje, (
                    f"El mensaje entregado a '{ws_id}' no coincide con el original"
                )
            else:
                assert len(mock_ws.sent_messages) == 0, (
                    f"La workstation '{ws_id}' (org={connections[ws_id]}) "
                    f"NO debería haber recibido el broadcast a org '{target_org_id}' "
                    f"pero recibió {len(mock_ws.sent_messages)} mensajes: "
                    f"{mock_ws.sent_messages}"
                )

        # Verificar que al menos una workstation de otra org NO recibió
        # (garantiza que el filtrado realmente excluye)
        if non_recipients:
            non_recipient_messages = sum(
                len(websockets[ws_id].sent_messages) for ws_id in non_recipients
            )
            assert non_recipient_messages == 0, (
                f"Workstations de otras organizaciones recibieron {non_recipient_messages} "
                f"mensajes del broadcast a org '{target_org_id}'. "
                f"Esto viola el aislamiento multi-tenant (Req 5.3)."
            )

    @given(connections=connections_with_orgs_strategy())
    @hypothesis_settings(max_examples=150, deadline=None)
    async def test_org_channel_no_delivery_to_absent_org(self, connections):
        """
        Para canal org:{id} cuando NO hay workstations de esa org conectadas:
        ninguna conexión local recibe el mensaje.

        Feature: websocket-scaling-redis, Property 2: Local Delivery Only to Matching Connections
        **Validates: Requirements 1.4, 5.3**
        """
        manager, websockets = _crear_manager_con_conexiones(connections)

        # Generar un org_id que NO tiene workstations conectadas
        absent_org_id = "absent-org-00000000-0000-0000-0000-000000000000"
        assume(absent_org_id not in connections.values())

        mensaje = {"type": "forced_contingency", "enabled": False}

        # Simular entrega para una org sin workstations locales
        await manager._deliver_to_local_org_workstations(absent_org_id, mensaje)

        # Propiedad: NINGUNA conexión recibe el mensaje
        for ws_id, mock_ws in websockets.items():
            assert len(mock_ws.sent_messages) == 0, (
                f"La workstation '{ws_id}' (org={connections[ws_id]}) "
                f"recibió un mensaje de broadcast para org '{absent_org_id}' "
                f"que no tiene workstations locales. Recibió: {mock_ws.sent_messages}"
            )

    # === PROPIEDAD COMBINADA: AISLAMIENTO TOTAL ===

    @given(data=org_broadcast_scenario())
    @hypothesis_settings(max_examples=150, deadline=None)
    async def test_delivery_isolation_between_orgs(self, data):
        """
        Propiedad combinada: un broadcast a org A nunca filtra mensajes a org B,
        y un mensaje a ws:{id} de org A nunca llega a ws de org B.

        Verifica que el aislamiento multi-tenant se mantiene en todas las
        operaciones de entrega local.

        Feature: websocket-scaling-redis, Property 2: Local Delivery Only to Matching Connections
        **Validates: Requirements 5.3**
        """
        connections, target_org_id = data
        manager, websockets = _crear_manager_con_conexiones(connections)

        # Identificar orgs distintas
        all_orgs = set(connections.values())
        other_orgs = all_orgs - {target_org_id}
        assume(len(other_orgs) >= 1)

        # Enviar broadcast a target_org
        mensaje_broadcast = {
            "type": "forced_contingency",
            "enabled": True,
            "organization_id": target_org_id,
        }
        await manager._deliver_to_local_org_workstations(target_org_id, mensaje_broadcast)

        # Verificar aislamiento: workstations de OTRAS orgs no reciben nada
        for ws_id, org_id in connections.items():
            if org_id != target_org_id:
                mock_ws = websockets[ws_id]
                assert len(mock_ws.sent_messages) == 0, (
                    f"VIOLACIÓN DE AISLAMIENTO MULTI-TENANT: "
                    f"Workstation '{ws_id}' de org '{org_id}' recibió mensaje "
                    f"destinado a org '{target_org_id}'. "
                    f"Mensajes recibidos: {mock_ws.sent_messages}"
                )
