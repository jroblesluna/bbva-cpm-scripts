"""
Property test para Task 7.5: Tenant isolation (Property 10).

**Validates: Requirements 8.1, 8.3**

Property 10: Para cualquier mensaje entregado a una workstation (vía worker channel
o org channel), el `organization_id` en el mensaje o canal SHALL coincidir con el
`organization_id` almacenado para esa workstation. Mensajes con organization_id
que no coincide SHALL ser descartados.

Verifica que:
1. `_deliver_to_local_workstation` con org_id que no coincide con la WS → no se entrega
2. `_deliver_to_local_workstation` con org_id coincidente → se entrega
3. `_deliver_to_local_org_workstations` con workstations mixtas → solo las WS con org_id
   coincidente reciben el mensaje
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

# Tipos de mensaje
message_type_strategy = st.sampled_from([
    "command", "status_request", "config_update",
    "org_broadcast", "config_change", "firmware_push",
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
def mismatched_org_strategy(draw):
    """
    Genera un ws_id, org_id de la workstation y un org_id diferente para el mensaje.

    Garantiza que ws_org_id != message_org_id.
    """
    ws_id = draw(uuid_strategy)
    ws_org_id = draw(uuid_strategy)
    message_org_id = draw(uuid_strategy)
    assume(ws_org_id != message_org_id)
    return ws_id, ws_org_id, message_org_id


@st.composite
def matching_org_strategy(draw):
    """
    Genera un ws_id con org_id coincidente para ws y mensaje.
    """
    ws_id = draw(uuid_strategy)
    org_id = draw(uuid_strategy)
    return ws_id, org_id


@st.composite
def mixed_org_workstations_strategy(draw):
    """
    Genera workstations de múltiples organizaciones para probar que
    _deliver_to_local_org_workstations solo entrega a la org correcta.

    Returns:
        Tupla (target_org_id, workstations) donde workstations es lista de
        {"ws_id": str, "org_id": str} con al menos 1 WS de target_org y 1 de otra org.
    """
    # Generar 2-4 organizaciones distintas
    num_orgs = draw(st.integers(min_value=2, max_value=4))
    org_ids = list(set(draw(uuid_strategy) for _ in range(num_orgs)))
    assume(len(org_ids) >= 2)

    target_org_id = org_ids[0]

    # Generar entre 4 y 10 workstations
    num_ws = draw(st.integers(min_value=4, max_value=10))

    workstations = []
    ws_id_set = set()

    # Garantizar al menos 1 WS de target_org
    ws_id_1 = draw(uuid_strategy)
    ws_id_set.add(ws_id_1)
    workstations.append({"ws_id": ws_id_1, "org_id": target_org_id})

    # Garantizar al menos 1 WS de otra org
    ws_id_2 = draw(uuid_strategy)
    assume(ws_id_2 not in ws_id_set)
    ws_id_set.add(ws_id_2)
    workstations.append({"ws_id": ws_id_2, "org_id": org_ids[1]})

    # Rellenar el resto con orgs variadas
    for _ in range(num_ws - 2):
        ws_id = draw(uuid_strategy)
        assume(ws_id not in ws_id_set)
        ws_id_set.add(ws_id)
        org_id = draw(st.sampled_from(org_ids))
        workstations.append({"ws_id": ws_id, "org_id": org_id})

    return target_org_id, workstations


def _create_manager_with_workstation(
    ws_id: str, org_id: str
) -> tuple:
    """
    Crea un RedisConnectionManager con una workstation pre-registrada.

    Returns:
        Tupla (manager, mock_ws)
    """
    manager = RedisConnectionManager(redis_url=None)
    mock_ws = AsyncMock()
    mock_ws.send_json = AsyncMock()

    manager.workstation_connections[ws_id] = mock_ws
    manager.org_ids[ws_id] = org_id
    manager._ws_vlan_ids[ws_id] = None

    return manager, mock_ws


def _create_manager_with_mixed_workstations(
    workstations: list,
) -> tuple:
    """
    Crea un RedisConnectionManager con workstations de múltiples orgs.

    Returns:
        Tupla (manager, ws_mocks) donde ws_mocks es {ws_id: AsyncMock}
    """
    manager = RedisConnectionManager(redis_url=None)
    ws_mocks: Dict[str, AsyncMock] = {}

    for ws_info in workstations:
        ws_id = ws_info["ws_id"]
        org_id = ws_info["org_id"]

        mock_ws = AsyncMock()
        mock_ws.send_json = AsyncMock()

        manager.workstation_connections[ws_id] = mock_ws
        manager.org_ids[ws_id] = org_id
        manager._ws_vlan_ids[ws_id] = None
        ws_mocks[ws_id] = mock_ws

    return manager, ws_mocks


# === PROPERTY TESTS ===


class TestTenantIsolation:
    """
    Property 10: Tenant isolation.

    Para cualquier mensaje entregado a una workstation, el organization_id del
    mensaje o canal SHALL coincidir con el organization_id almacenado para esa
    workstation. Mensajes con organization_id que no coincide SHALL ser descartados.

    **Validates: Requirements 8.1, 8.3**
    """

    @hypothesis_settings(max_examples=150, deadline=None)
    @given(data=mismatched_org_strategy(), msg_type=message_type_strategy, extra=extra_payload_strategy)
    @pytest.mark.asyncio
    async def test_mismatched_org_id_discards_message(
        self, data, msg_type, extra
    ):
        """
        **Validates: Requirements 8.1**

        _deliver_to_local_workstation con org_id que no coincide con el de la WS
        → el mensaje NO se entrega (se descarta por tenant isolation).
        """
        ws_id, ws_org_id, message_org_id = data

        manager, mock_ws = _create_manager_with_workstation(ws_id, ws_org_id)

        # Construir payload con organization_id que NO coincide con la workstation
        payload = {
            "type": msg_type,
            "organization_id": message_org_id,
            **extra,
        }

        # Ejecutar entrega dirigida
        await manager._deliver_to_local_workstation(ws_id, payload)

        # Propiedad: la workstation NO debe haber recibido el mensaje
        assert mock_ws.send_json.call_count == 0, (
            f"Workstation '{ws_id}' con org_id='{ws_org_id}' "
            f"NO debería haber recibido un mensaje con "
            f"organization_id='{message_org_id}' (mismatched). "
            f"Tenant isolation debe descartar mensajes con org_id diferente."
        )

    @hypothesis_settings(max_examples=150, deadline=None)
    @given(data=matching_org_strategy(), msg_type=message_type_strategy, extra=extra_payload_strategy)
    @pytest.mark.asyncio
    async def test_matching_org_id_delivers_message(
        self, data, msg_type, extra
    ):
        """
        **Validates: Requirements 8.1**

        _deliver_to_local_workstation con org_id que SÍ coincide con el de la WS
        → el mensaje se entrega correctamente.
        """
        ws_id, org_id = data

        manager, mock_ws = _create_manager_with_workstation(ws_id, org_id)

        # Construir payload con organization_id que coincide con la workstation
        payload = {
            "type": msg_type,
            "organization_id": org_id,
            **extra,
        }

        # Ejecutar entrega dirigida
        await manager._deliver_to_local_workstation(ws_id, payload)

        # Propiedad: la workstation DEBE haber recibido el mensaje
        assert mock_ws.send_json.call_count == 1, (
            f"Workstation '{ws_id}' con org_id='{org_id}' "
            f"debería haber recibido un mensaje con "
            f"organization_id='{org_id}' (matching) pero no lo recibió. "
            f"Mensajes con tenant isolation válida deben ser entregados."
        )

    @hypothesis_settings(max_examples=150, deadline=None)
    @given(data=mixed_org_workstations_strategy(), msg_type=message_type_strategy, extra=extra_payload_strategy)
    @pytest.mark.asyncio
    async def test_org_channel_only_delivers_to_matching_org_ws(
        self, data, msg_type, extra
    ):
        """
        **Validates: Requirements 8.3**

        _deliver_to_local_org_workstations con workstations de múltiples
        organizaciones → solo las workstations cuyo org_id coincide con el
        organization_id del canal reciben el mensaje.
        """
        target_org_id, workstations = data

        manager, ws_mocks = _create_manager_with_mixed_workstations(workstations)

        # Construir payload organizacional
        payload = {
            "type": msg_type,
            "organization_id": target_org_id,
            **extra,
        }

        # Ejecutar entrega organizacional para target_org_id
        await manager._deliver_to_local_org_workstations(target_org_id, payload)

        # Propiedad: solo WS con org_id == target_org_id recibieron el mensaje
        for ws_info in workstations:
            ws_id = ws_info["ws_id"]
            ws_org_id = ws_info["org_id"]
            mock_ws = ws_mocks[ws_id]

            if ws_org_id == target_org_id:
                # Debería haber recibido
                assert mock_ws.send_json.call_count == 1, (
                    f"Workstation '{ws_id}' con org_id='{ws_org_id}' "
                    f"(coincide con target_org_id='{target_org_id}') "
                    f"debería haber recibido el mensaje pero no lo recibió."
                )
            else:
                # NO debería haber recibido
                assert mock_ws.send_json.call_count == 0, (
                    f"Workstation '{ws_id}' con org_id='{ws_org_id}' "
                    f"NO debería haber recibido mensaje dirigido a "
                    f"org_id='{target_org_id}' (tenant isolation). "
                    f"Solo workstations de la misma organización deben recibir."
                )
