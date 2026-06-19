"""
Property test para Task 7.4: VLAN filtering on org messages (Property 9).

**Validates: Requirements 5.1, 5.3**

Property 9: Para cualquier mensaje que llegue al canal `org:{organization_id}` con campo
`target_vlan_id`, el mensaje SHALL ser entregado solo a las workstations conectadas
localmente cuyo `vlan_id` almacenado sea igual a `target_vlan_id`. Workstations con un
`vlan_id` diferente o None NO deben recibir el mensaje.

Verifica que:
1. Con target_vlan_id en payload → solo WS con vlan_id coincidente reciben
2. Sin target_vlan_id → todas las WS de la organización reciben
3. WS con vlan_id=None son excluidas de mensajes dirigidos a una VLAN
"""
import asyncio
from typing import Dict, List, Optional
from unittest.mock import AsyncMock

import pytest
from hypothesis import given, settings as hypothesis_settings, assume
from hypothesis import strategies as st

from app.services.redis_connection_manager import RedisConnectionManager


# === ESTRATEGIAS DE GENERACIÓN ===

# IDs tipo UUID (eficiente, sin regex)
uuid_strategy = st.uuids().map(str)

# Tipos de mensaje organizacional
org_message_type_strategy = st.sampled_from([
    "org_broadcast", "config_change", "vlan_update",
    "status_notification", "policy_push", "firmware_check",
])

# Payload extra
extra_payload_strategy = st.dictionaries(
    keys=st.sampled_from(["data", "version", "timestamp", "severity", "details"]),
    values=st.one_of(
        st.text(min_size=0, max_size=20, alphabet=st.characters(categories=("L", "N"))),
        st.integers(min_value=0, max_value=5000),
        st.booleans(),
    ),
    min_size=0,
    max_size=3,
)


@st.composite
def org_workstations_with_vlans_strategy(draw):
    """
    Genera workstations de una misma organización con VLANs variadas.

    Garantiza:
    - Al menos 1 workstation con vlan_id asignado
    - Al menos 1 workstation con vlan_id=None (para probar exclusión)
    - Múltiples VLANs distintas cuando es posible

    Returns:
        Tupla (org_id, workstations) donde workstations es lista de
        {"ws_id": str, "vlan_id": Optional[str]}
    """
    org_id = draw(uuid_strategy)

    # Generar 2-4 VLANs distintas
    num_vlans = draw(st.integers(min_value=2, max_value=4))
    vlan_ids = list(set(draw(uuid_strategy) for _ in range(num_vlans)))
    assume(len(vlan_ids) >= 2)

    # Generar entre 3 y 10 workstations
    num_ws = draw(st.integers(min_value=3, max_value=10))

    workstations = []
    ws_id_set = set()

    # Garantizar al menos 1 con VLAN asignada
    ws_id_1 = draw(uuid_strategy)
    ws_id_set.add(ws_id_1)
    workstations.append({"ws_id": ws_id_1, "vlan_id": vlan_ids[0]})

    # Garantizar al menos 1 con vlan_id=None
    ws_id_2 = draw(uuid_strategy)
    assume(ws_id_2 not in ws_id_set)
    ws_id_set.add(ws_id_2)
    workstations.append({"ws_id": ws_id_2, "vlan_id": None})

    # Rellenar el resto con VLANs variadas (incluyendo None como opción)
    vlan_options: List[Optional[str]] = vlan_ids + [None]
    for _ in range(num_ws - 2):
        ws_id = draw(uuid_strategy)
        assume(ws_id not in ws_id_set)
        ws_id_set.add(ws_id)
        vlan_id = draw(st.sampled_from(vlan_options))
        workstations.append({"ws_id": ws_id, "vlan_id": vlan_id})

    return org_id, workstations, vlan_ids


def _create_manager_with_org_workstations(
    org_id: str, workstations: list
) -> tuple:
    """
    Crea un RedisConnectionManager con workstations pre-registradas para una org.

    Args:
        org_id: organization_id compartido por todas las workstations
        workstations: Lista de {"ws_id": str, "vlan_id": Optional[str]}

    Returns:
        Tupla (manager, ws_mocks) donde ws_mocks es {ws_id: AsyncMock}
    """
    manager = RedisConnectionManager(redis_url=None)
    ws_mocks: Dict[str, AsyncMock] = {}

    for ws_info in workstations:
        ws_id = ws_info["ws_id"]
        vlan_id = ws_info["vlan_id"]

        mock_ws = AsyncMock()
        mock_ws.send_json = AsyncMock()

        manager.workstation_connections[ws_id] = mock_ws
        manager.org_ids[ws_id] = org_id
        manager._ws_vlan_ids[ws_id] = vlan_id
        ws_mocks[ws_id] = mock_ws

    return manager, ws_mocks


# === PROPERTY TESTS ===


class TestVlanFilteringOnOrgMessages:
    """
    Property 9: VLAN filtering on org messages.

    Para cualquier mensaje que llegue al canal org:{organization_id} con campo
    target_vlan_id, el mensaje solo se entrega a workstations cuyo vlan_id
    coincida con target_vlan_id. Workstations con vlan_id diferente o None
    NO reciben el mensaje.

    **Validates: Requirements 5.1, 5.3**
    """

    @hypothesis_settings(max_examples=150, deadline=None)
    @given(data=org_workstations_with_vlans_strategy(), extra=extra_payload_strategy)
    @pytest.mark.asyncio
    async def test_vlan_targeted_message_only_reaches_matching_ws(
        self, data, extra
    ):
        """
        **Validates: Requirements 5.1**

        Con target_vlan_id en el payload, solo las workstations cuyo vlan_id
        almacenado coincide con target_vlan_id reciben el mensaje.
        """
        org_id, workstations, vlan_ids = data

        # Elegir una VLAN target de las disponibles
        target_vlan_id = vlan_ids[0]

        manager, ws_mocks = _create_manager_with_org_workstations(org_id, workstations)

        # Construir payload con target_vlan_id
        payload = {
            "type": "org_broadcast",
            "organization_id": org_id,
            "target_vlan_id": target_vlan_id,
            **extra,
        }

        # Ejecutar entrega organizacional con filtrado VLAN
        await manager._deliver_to_local_org_workstations(org_id, payload)

        # Propiedad: solo WS con vlan_id == target_vlan_id recibieron el mensaje
        for ws_info in workstations:
            ws_id = ws_info["ws_id"]
            ws_vlan = ws_info["vlan_id"]
            mock_ws = ws_mocks[ws_id]

            if ws_vlan == target_vlan_id:
                # Debería haber recibido
                assert mock_ws.send_json.call_count == 1, (
                    f"Workstation '{ws_id}' con vlan_id='{ws_vlan}' "
                    f"(coincide con target_vlan_id='{target_vlan_id}') "
                    f"debería haber recibido el mensaje pero no lo recibió."
                )
            else:
                # NO debería haber recibido
                assert mock_ws.send_json.call_count == 0, (
                    f"Workstation '{ws_id}' con vlan_id='{ws_vlan}' "
                    f"NO debería haber recibido mensaje dirigido a "
                    f"target_vlan_id='{target_vlan_id}' pero lo recibió."
                )

    @hypothesis_settings(max_examples=150, deadline=None)
    @given(data=org_workstations_with_vlans_strategy(), extra=extra_payload_strategy)
    @pytest.mark.asyncio
    async def test_without_target_vlan_all_org_ws_receive(
        self, data, extra
    ):
        """
        **Validates: Requirements 5.1**

        Sin target_vlan_id en el payload, TODAS las workstations de la
        organización reciben el mensaje (sin filtrado por VLAN).
        """
        org_id, workstations, vlan_ids = data

        manager, ws_mocks = _create_manager_with_org_workstations(org_id, workstations)

        # Construir payload SIN target_vlan_id
        payload = {
            "type": "org_broadcast",
            "organization_id": org_id,
            **extra,
        }

        # Ejecutar entrega organizacional (sin filtrado VLAN)
        await manager._deliver_to_local_org_workstations(org_id, payload)

        # Propiedad: TODAS las workstations de la org reciben el mensaje
        for ws_info in workstations:
            ws_id = ws_info["ws_id"]
            ws_vlan = ws_info["vlan_id"]
            mock_ws = ws_mocks[ws_id]

            assert mock_ws.send_json.call_count == 1, (
                f"Workstation '{ws_id}' con vlan_id='{ws_vlan}' "
                f"debería haber recibido el broadcast organizacional "
                f"(sin target_vlan_id) pero no lo recibió. "
                f"Cuando no hay filtro VLAN, todas las WS de la org deben recibir."
            )

    @hypothesis_settings(max_examples=150, deadline=None)
    @given(data=org_workstations_with_vlans_strategy(), extra=extra_payload_strategy)
    @pytest.mark.asyncio
    async def test_ws_with_none_vlan_excluded_from_vlan_targeted(
        self, data, extra
    ):
        """
        **Validates: Requirements 5.1, 5.3**

        Workstations con vlan_id=None son explícitamente excluidas de
        mensajes dirigidos a una VLAN específica.
        """
        org_id, workstations, vlan_ids = data

        # Elegir cualquier target_vlan_id de las VLANs disponibles
        target_vlan_id = vlan_ids[0]

        manager, ws_mocks = _create_manager_with_org_workstations(org_id, workstations)

        # Construir payload con target_vlan_id
        payload = {
            "type": "config_change",
            "organization_id": org_id,
            "target_vlan_id": target_vlan_id,
            **extra,
        }

        # Ejecutar entrega con filtrado VLAN
        await manager._deliver_to_local_org_workstations(org_id, payload)

        # Propiedad: toda WS con vlan_id=None NO recibe el mensaje
        ws_none_vlan = [ws for ws in workstations if ws["vlan_id"] is None]
        assume(len(ws_none_vlan) >= 1)  # Garantizado por la estrategia

        for ws_info in ws_none_vlan:
            ws_id = ws_info["ws_id"]
            mock_ws = ws_mocks[ws_id]

            assert mock_ws.send_json.call_count == 0, (
                f"Workstation '{ws_id}' con vlan_id=None "
                f"NO debería recibir mensajes dirigidos a "
                f"target_vlan_id='{target_vlan_id}'. "
                f"Las WS sin VLAN deben ser excluidas de mensajes VLAN-targeted."
            )
