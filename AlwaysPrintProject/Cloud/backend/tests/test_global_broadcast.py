"""
Property test para Task 7.6: Global broadcast delivery (Property 11).

**Validates: Requirements 9.4**

Property 11: Para cualquier mensaje que llegue al canal `global:broadcast`,
el mensaje SHALL ser entregado a TODAS las workstations en `workstation_connections`
sin filtrado.

Verifica que:
1. TODAS las workstations conectadas reciben el broadcast (send_json llamado para cada una)
2. No hay filtrado por org_id (workstations de diferentes orgs reciben el mismo mensaje)
3. No hay filtrado por vlan_id (workstations de diferentes VLANs reciben el mismo mensaje)
4. El payload se entrega tal cual a cada WebSocket
"""
import asyncio
from typing import Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings as hypothesis_settings, assume
from hypothesis import strategies as st

from app.services.redis_connection_manager import RedisConnectionManager


# === ESTRATEGIAS DE GENERACIÓN ===

# IDs tipo UUID
uuid_strategy = st.uuids().map(str)

# Tipos de broadcast global
broadcast_type_strategy = st.sampled_from([
    "global_announcement", "maintenance", "system_update",
    "config_reload", "emergency_shutdown", "version_update",
])

# Payload adicional para broadcasts
broadcast_payload_strategy = st.dictionaries(
    keys=st.sampled_from(["message", "version", "timestamp", "severity", "details", "code"]),
    values=st.one_of(
        st.text(min_size=0, max_size=50, alphabet=st.characters(categories=("L", "N", "P"))),
        st.integers(min_value=0, max_value=10000),
        st.booleans(),
    ),
    min_size=0,
    max_size=4,
)


@st.composite
def workstation_set_strategy(draw):
    """
    Genera un conjunto de workstations con diferentes orgs y VLANs.

    Cada workstation tiene:
    - ws_id: UUID único
    - org_id: organización (varias distintas para probar que NO se filtra)
    - vlan_id: VLAN (puede ser None, varias distintas para probar que NO se filtra)
    """
    # Generar entre 1 y 10 workstations
    num_ws = draw(st.integers(min_value=1, max_value=10))

    # Generar 2-4 orgs distintas para distribuir workstations
    num_orgs = draw(st.integers(min_value=2, max_value=4))
    org_ids = [draw(uuid_strategy) for _ in range(num_orgs)]

    # Generar 2-3 VLANs distintas (más None)
    num_vlans = draw(st.integers(min_value=2, max_value=3))
    vlan_ids: List[Optional[str]] = [draw(uuid_strategy) for _ in range(num_vlans)]
    vlan_ids.append(None)  # Algunas workstations sin VLAN

    workstations = []
    ws_id_set = set()
    for _ in range(num_ws):
        ws_id = draw(uuid_strategy)
        assume(ws_id not in ws_id_set)
        ws_id_set.add(ws_id)

        org_id = draw(st.sampled_from(org_ids))
        vlan_id = draw(st.sampled_from(vlan_ids))

        workstations.append({
            "ws_id": ws_id,
            "org_id": org_id,
            "vlan_id": vlan_id,
        })

    return workstations


@st.composite
def global_broadcast_payload_strategy(draw):
    """
    Genera un payload de broadcast global válido.
    """
    broadcast_type = draw(broadcast_type_strategy)
    extra = draw(broadcast_payload_strategy)

    payload = {"type": broadcast_type, **extra}
    return payload


def _create_manager_with_workstations(workstations: list) -> tuple:
    """
    Crea un RedisConnectionManager con workstations pre-registradas.

    Returns:
        Tupla (manager, ws_mocks) donde ws_mocks es {ws_id: AsyncMock}
    """
    manager = RedisConnectionManager(redis_url=None)
    ws_mocks: Dict[str, AsyncMock] = {}

    for ws_info in workstations:
        ws_id = ws_info["ws_id"]
        org_id = ws_info["org_id"]
        vlan_id = ws_info["vlan_id"]

        mock_ws = AsyncMock()
        mock_ws.send_json = AsyncMock()

        manager.workstation_connections[ws_id] = mock_ws
        manager.org_ids[ws_id] = org_id
        manager._ws_vlan_ids[ws_id] = vlan_id
        ws_mocks[ws_id] = mock_ws

    return manager, ws_mocks


# === PROPERTY TESTS ===


class TestGlobalBroadcastDelivery:
    """
    Property 11: Global broadcast delivery.

    Para cualquier mensaje que llegue al canal `global:broadcast`, el mensaje
    SHALL ser entregado a TODAS las workstations en `workstation_connections`
    sin filtrado.

    **Validates: Requirements 9.4**
    """

    @hypothesis_settings(max_examples=150, deadline=None)
    @given(
        workstations=workstation_set_strategy(),
        payload=global_broadcast_payload_strategy(),
    )
    @pytest.mark.asyncio
    async def test_all_workstations_receive_broadcast(
        self, workstations: list, payload: dict
    ):
        """
        Propiedad: TODAS las workstations conectadas reciben el broadcast global.

        Para cualquier conjunto de workstations (diferentes orgs, diferentes VLANs),
        _deliver_global_broadcast entrega el mensaje a cada una sin excepción.

        **Validates: Requirements 9.4**
        """
        manager, ws_mocks = _create_manager_with_workstations(workstations)

        # Ejecutar broadcast global
        await manager._deliver_global_broadcast(payload)

        # Propiedad: TODAS las workstations recibieron el mensaje
        for ws_info in workstations:
            ws_id = ws_info["ws_id"]
            mock_ws = ws_mocks[ws_id]
            mock_ws.send_json.assert_called_once_with(payload), (
                f"Workstation '{ws_id}' (org={ws_info['org_id']}, "
                f"vlan={ws_info['vlan_id']}) NO recibió el broadcast global. "
                f"El broadcast global debe entregarse a TODAS las workstations."
            )

    @hypothesis_settings(max_examples=150, deadline=None)
    @given(
        workstations=workstation_set_strategy(),
        payload=global_broadcast_payload_strategy(),
    )
    @pytest.mark.asyncio
    async def test_no_org_filtering_on_global_broadcast(
        self, workstations: list, payload: dict
    ):
        """
        Propiedad: No hay filtrado por organization_id en broadcasts globales.

        Incluso con workstations de organizaciones completamente diferentes,
        TODAS reciben el broadcast sin discriminación por org.

        **Validates: Requirements 9.4**
        """
        manager, ws_mocks = _create_manager_with_workstations(workstations)

        # Ejecutar broadcast global
        await manager._deliver_global_broadcast(payload)

        # Agrupar workstations por org y verificar que TODAS recibieron
        orgs_seen = set()
        for ws_info in workstations:
            ws_id = ws_info["ws_id"]
            org_id = ws_info["org_id"]
            orgs_seen.add(org_id)

            mock_ws = ws_mocks[ws_id]
            assert mock_ws.send_json.call_count == 1, (
                f"Workstation '{ws_id}' de org '{org_id}' debería haber recibido "
                f"exactamente 1 broadcast. Recibió: {mock_ws.send_json.call_count}. "
                f"El broadcast global NO debe filtrar por organización."
            )

        # Verificar que hubo múltiples orgs (confirma que el test es significativo)
        # (no es un assert obligatorio, pero ayuda a validar la diversidad del test)
        if len(workstations) > 1:
            assert len(orgs_seen) >= 1  # Al menos 1 org presente

    @hypothesis_settings(max_examples=150, deadline=None)
    @given(
        workstations=workstation_set_strategy(),
        payload=global_broadcast_payload_strategy(),
    )
    @pytest.mark.asyncio
    async def test_no_vlan_filtering_on_global_broadcast(
        self, workstations: list, payload: dict
    ):
        """
        Propiedad: No hay filtrado por vlan_id en broadcasts globales.

        Workstations con diferentes VLANs o sin VLAN (None) TODAS reciben
        el broadcast global.

        **Validates: Requirements 9.4**
        """
        manager, ws_mocks = _create_manager_with_workstations(workstations)

        # Ejecutar broadcast global
        await manager._deliver_global_broadcast(payload)

        # Verificar por VLAN que todas recibieron
        vlans_seen = set()
        for ws_info in workstations:
            ws_id = ws_info["ws_id"]
            vlan_id = ws_info["vlan_id"]
            vlans_seen.add(vlan_id)

            mock_ws = ws_mocks[ws_id]
            assert mock_ws.send_json.call_count == 1, (
                f"Workstation '{ws_id}' con vlan_id '{vlan_id}' debería haber "
                f"recibido el broadcast. Recibió: {mock_ws.send_json.call_count}. "
                f"El broadcast global NO debe filtrar por VLAN."
            )

    @hypothesis_settings(max_examples=150, deadline=None)
    @given(
        workstations=workstation_set_strategy(),
        payload=global_broadcast_payload_strategy(),
    )
    @pytest.mark.asyncio
    async def test_payload_delivered_as_is(
        self, workstations: list, payload: dict
    ):
        """
        Propiedad: El payload se entrega tal cual (as-is) a cada workstation.

        No se modifica, enriquece ni filtra ningún campo del payload original
        durante la entrega del broadcast global.

        **Validates: Requirements 9.4**
        """
        manager, ws_mocks = _create_manager_with_workstations(workstations)

        # Ejecutar broadcast global
        await manager._deliver_global_broadcast(payload)

        # Verificar que cada workstation recibió exactamente el mismo payload
        for ws_info in workstations:
            ws_id = ws_info["ws_id"]
            mock_ws = ws_mocks[ws_id]

            # Obtener el payload que se pasó a send_json
            call_args = mock_ws.send_json.call_args
            assert call_args is not None, (
                f"Workstation '{ws_id}' no recibió ninguna llamada a send_json."
            )

            delivered_payload = call_args[0][0]
            assert delivered_payload == payload, (
                f"El payload entregado a workstation '{ws_id}' difiere del original. "
                f"Original: {payload}, Entregado: {delivered_payload}. "
                f"El broadcast global debe entregar el payload sin modificaciones."
            )

    @hypothesis_settings(max_examples=100, deadline=None)
    @given(
        workstations=workstation_set_strategy(),
        payload=global_broadcast_payload_strategy(),
    )
    @pytest.mark.asyncio
    async def test_broadcast_count_equals_workstation_count(
        self, workstations: list, payload: dict
    ):
        """
        Propiedad: El número total de entregas es exactamente igual al número
        de workstations conectadas.

        Ni más (duplicados) ni menos (omisiones).

        **Validates: Requirements 9.4**
        """
        manager, ws_mocks = _create_manager_with_workstations(workstations)

        # Ejecutar broadcast global
        await manager._deliver_global_broadcast(payload)

        # Contar total de llamadas send_json
        total_deliveries = sum(
            mock_ws.send_json.call_count for mock_ws in ws_mocks.values()
        )

        assert total_deliveries == len(workstations), (
            f"El número de entregas ({total_deliveries}) no coincide con "
            f"el número de workstations ({len(workstations)}). "
            f"El broadcast global debe entregar exactamente una vez a cada WS."
        )
