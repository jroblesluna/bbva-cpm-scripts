"""
Property tests para re-asignación de VLAN cuando cambia el CIDR.

Verifica que cuando una workstation se re-registra con un CIDR diferente,
su vlan_id se actualiza para apuntar a la VLAN correspondiente al nuevo CIDR,
y el campo cidr almacenado refleja el nuevo valor.

- Property 8: VLAN Re-assignment on CIDR Change

**Validates: Requirements 2.5**
"""

import ipaddress
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.models.workstation import Workstation
from app.models.vlan import VLAN
from app.services.workstation import WorkstationService


# === ESTRATEGIAS DE GENERACIÓN ===

# Estrategia para generar octetos IPv4 válidos
_octet = st.integers(min_value=0, max_value=255)

# Estrategia para generar prefijos CIDR válidos (rango 8-30 según requisitos)
_prefix = st.integers(min_value=8, max_value=30)


@st.composite
def valid_cidr_strategy(draw):
    """
    Genera un CIDR IPv4 válido y normalizado.

    Produce strings en formato 'x.x.x.x/prefix' donde el network address
    tiene los host bits en cero (forma canónica).
    """
    o1 = draw(_octet)
    o2 = draw(_octet)
    o3 = draw(_octet)
    o4 = draw(_octet)
    prefix = draw(_prefix)

    raw_cidr = f"{o1}.{o2}.{o3}.{o4}/{prefix}"
    try:
        network = ipaddress.ip_network(raw_cidr, strict=False)
    except ValueError:
        assume(False)
        return None

    return str(network)


@st.composite
def two_distinct_cidrs_strategy(draw):
    """
    Genera dos CIDRs IPv4 válidos y distintos (normalizados).

    Útil para simular el cambio de CIDR en una workstation que se re-registra.
    """
    cidr1 = draw(valid_cidr_strategy())
    cidr2 = draw(valid_cidr_strategy())
    assume(cidr1 != cidr2)
    return cidr1, cidr2


@st.composite
def valid_ipv4_strategy(draw):
    """
    Genera una dirección IPv4 privada válida.

    Produce IPs en rangos privados (192.168.x.x, 10.x.x.x, 172.16-31.x.x).
    """
    rango = draw(st.sampled_from(["192.168", "10", "172"]))
    if rango == "192.168":
        o3 = draw(st.integers(min_value=0, max_value=255))
        o4 = draw(st.integers(min_value=1, max_value=254))
        return f"192.168.{o3}.{o4}"
    elif rango == "10":
        o2 = draw(st.integers(min_value=0, max_value=255))
        o3 = draw(st.integers(min_value=0, max_value=255))
        o4 = draw(st.integers(min_value=1, max_value=254))
        return f"10.{o2}.{o3}.{o4}"
    else:
        o2 = draw(st.integers(min_value=16, max_value=31))
        o3 = draw(st.integers(min_value=0, max_value=255))
        o4 = draw(st.integers(min_value=1, max_value=254))
        return f"172.{o2}.{o3}.{o4}"


def _crear_mock_vlan(vlan_id, cidr_ranges, organization_id):
    """
    Crea un mock de VLAN con los campos necesarios.

    Args:
        vlan_id: UUID de la VLAN
        cidr_ranges: Lista de CIDRs asignados a la VLAN
        organization_id: UUID de la organización

    Returns:
        Mock de VLAN configurado
    """
    mock_vlan = MagicMock(spec=VLAN)
    mock_vlan.id = vlan_id
    mock_vlan.cidr_ranges = cidr_ranges
    mock_vlan.organization_id = organization_id
    mock_vlan.name = f"VLAN_{cidr_ranges[0]}" if cidr_ranges else "VLAN_empty"
    return mock_vlan


def _crear_workstation_existente(org_id, ip_private, cidr_actual, vlan_id_actual):
    """
    Crea un mock de Workstation existente con CIDR y VLAN asignados.

    Args:
        org_id: UUID de la organización
        ip_private: IP privada de la workstation
        cidr_actual: CIDR actualmente almacenado
        vlan_id_actual: UUID de la VLAN actualmente asignada

    Returns:
        Mock de Workstation configurado
    """
    mock_ws = MagicMock(spec=Workstation)
    mock_ws.id = uuid.uuid4()
    mock_ws.organization_id = org_id
    mock_ws.ip_private = ip_private
    mock_ws.cidr = cidr_actual
    mock_ws.vlan_id = vlan_id_actual
    mock_ws.hostname = "TEST-PC"
    mock_ws.os_serial = "XXXXX-XXXXX"
    mock_ws.current_user = "testuser"
    mock_ws.tray_version = "2.0.0"
    mock_ws.is_online = True
    mock_ws.last_connection = datetime.now(timezone.utc).replace(tzinfo=None)
    return mock_ws


# === PROPERTY 8: VLAN RE-ASSIGNMENT ON CIDR CHANGE ===


class TestVlanReassignmentOnCidrChange:
    """
    Property 8: VLAN Re-assignment on CIDR Change.

    Para cualquier workstation que se re-registra con un CIDR diferente,
    el vlan_id de la workstation SHALL ser actualizado para apuntar a la VLAN
    correspondiente al nuevo CIDR, y el cidr almacenado SHALL reflejar
    el nuevo valor.

    **Validates: Requirements 2.5**
    """

    def setup_method(self):
        """Configuración común para cada test."""
        self.service = WorkstationService()

    @given(data=two_distinct_cidrs_strategy())
    @settings(max_examples=100, deadline=None)
    def test_vlan_id_se_actualiza_al_cambiar_cidr(self, data):
        """
        Cuando una workstation se re-registra con un CIDR diferente,
        su vlan_id se actualiza para apuntar a la VLAN del nuevo CIDR.

        Simula el escenario donde una workstation cambia de segmento de red
        (por ejemplo, se mueve de una oficina a otra) y se re-registra.

        **Validates: Requirements 2.5**
        """
        cidr_anterior, cidr_nuevo = data
        org_id = str(uuid.uuid4())
        ip_private = "192.168.1.100"

        # VLAN anterior (asociada al CIDR anterior)
        vlan_anterior_id = uuid.uuid4()

        # VLAN nueva (asociada al nuevo CIDR) — ya existe
        vlan_nueva_id = uuid.uuid4()
        mock_vlan_nueva = _crear_mock_vlan(vlan_nueva_id, [cidr_nuevo], org_id)

        # Workstation existente con CIDR anterior
        mock_ws = _crear_workstation_existente(
            org_id, ip_private, cidr_anterior, str(vlan_anterior_id)
        )

        # Configurar mock de BD
        mock_db = MagicMock()

        # query(Workstation).filter_by(ip_private=...) retorna la workstation
        mock_ws_query = MagicMock()
        mock_ws_query.first.return_value = mock_ws

        # query(VLAN).filter_by(organization_id=...) retorna la VLAN nueva
        mock_vlan_query = MagicMock()
        mock_vlan_query.all.return_value = [mock_vlan_nueva]

        def query_side_effect(model):
            mock_q = MagicMock()
            if model == Workstation:
                mock_q.filter_by.return_value = mock_ws_query
            else:
                mock_q.filter_by.return_value = mock_vlan_query
            return mock_q

        mock_db.query.side_effect = query_side_effect

        # Ejecutar re-registro con nuevo CIDR
        resultado_ws, is_new, status = self.service.register_workstation(
            mock_db,
            ip_private=ip_private,
            public_ip="203.0.113.1",
            hostname="TEST-PC",
            cidr=cidr_nuevo,
            tray_version="2.1.0"
        )

        # Propiedad: vlan_id se actualizó a la VLAN del nuevo CIDR
        assert mock_ws.vlan_id == str(vlan_nueva_id), (
            f"vlan_id no se actualizó al cambiar CIDR. "
            f"CIDR anterior: {cidr_anterior}, CIDR nuevo: {cidr_nuevo}. "
            f"vlan_id esperado: {vlan_nueva_id}, "
            f"vlan_id obtenido: {mock_ws.vlan_id}"
        )

    @given(data=two_distinct_cidrs_strategy())
    @settings(max_examples=100, deadline=None)
    def test_cidr_almacenado_refleja_nuevo_valor(self, data):
        """
        Cuando una workstation se re-registra con un CIDR diferente,
        el campo cidr almacenado refleja el nuevo valor normalizado.

        **Validates: Requirements 2.5**
        """
        cidr_anterior, cidr_nuevo = data
        org_id = str(uuid.uuid4())
        ip_private = "10.0.1.50"

        # VLAN para el nuevo CIDR
        vlan_nueva_id = uuid.uuid4()
        mock_vlan_nueva = _crear_mock_vlan(vlan_nueva_id, [cidr_nuevo], org_id)

        # Workstation existente con CIDR anterior
        vlan_anterior_id = uuid.uuid4()
        mock_ws = _crear_workstation_existente(
            org_id, ip_private, cidr_anterior, str(vlan_anterior_id)
        )

        # Configurar mock de BD
        mock_db = MagicMock()

        mock_ws_query = MagicMock()
        mock_ws_query.first.return_value = mock_ws

        mock_vlan_query = MagicMock()
        mock_vlan_query.all.return_value = [mock_vlan_nueva]

        def query_side_effect(model):
            mock_q = MagicMock()
            if model == Workstation:
                mock_q.filter_by.return_value = mock_ws_query
            else:
                mock_q.filter_by.return_value = mock_vlan_query
            return mock_q

        mock_db.query.side_effect = query_side_effect

        # Ejecutar re-registro con nuevo CIDR
        self.service.register_workstation(
            mock_db,
            ip_private=ip_private,
            public_ip="203.0.113.1",
            cidr=cidr_nuevo,
            tray_version="2.1.0"
        )

        # Propiedad: el CIDR almacenado refleja el nuevo valor normalizado
        normalized_nuevo = str(ipaddress.ip_network(cidr_nuevo, strict=False))
        assert mock_ws.cidr == normalized_nuevo, (
            f"El CIDR almacenado no refleja el nuevo valor. "
            f"CIDR anterior: {cidr_anterior}, CIDR nuevo enviado: {cidr_nuevo}. "
            f"CIDR esperado (normalizado): {normalized_nuevo}, "
            f"CIDR almacenado: {mock_ws.cidr}"
        )

    @given(data=two_distinct_cidrs_strategy())
    @settings(max_examples=100, deadline=None)
    def test_vlan_nueva_se_crea_si_no_existe(self, data):
        """
        Cuando una workstation se re-registra con un CIDR que no tiene
        VLAN existente, se auto-crea una nueva VLAN y se asigna.

        Verifica que el mecanismo de auto-creación funciona correctamente
        durante la re-asignación.

        **Validates: Requirements 2.5**
        """
        cidr_anterior, cidr_nuevo = data
        org_id = str(uuid.uuid4())
        ip_private = "172.16.5.10"

        # VLAN anterior
        vlan_anterior_id = uuid.uuid4()

        # Workstation existente con CIDR anterior
        mock_ws = _crear_workstation_existente(
            org_id, ip_private, cidr_anterior, str(vlan_anterior_id)
        )

        # Configurar mock de BD — no hay VLAN para el nuevo CIDR
        mock_db = MagicMock()
        new_vlan_id = uuid.uuid4()

        mock_ws_query = MagicMock()
        mock_ws_query.first.return_value = mock_ws

        mock_vlan_query = MagicMock()
        mock_vlan_query.all.return_value = []  # No hay VLANs existentes

        def query_side_effect(model):
            mock_q = MagicMock()
            if model == Workstation:
                mock_q.filter_by.return_value = mock_ws_query
            else:
                mock_q.filter_by.return_value = mock_vlan_query
            return mock_q

        mock_db.query.side_effect = query_side_effect

        # Simular que flush asigna un ID a la VLAN creada
        def side_effect_add(vlan):
            vlan.id = new_vlan_id

        mock_db.add.side_effect = side_effect_add

        # Ejecutar re-registro con nuevo CIDR
        self.service.register_workstation(
            mock_db,
            ip_private=ip_private,
            public_ip="203.0.113.1",
            cidr=cidr_nuevo,
            tray_version="2.1.0"
        )

        # Propiedad: se creó una VLAN nueva y se asignó a la workstation
        assert mock_ws.vlan_id == str(new_vlan_id), (
            f"No se asignó la VLAN auto-creada a la workstation. "
            f"vlan_id esperado: {new_vlan_id}, "
            f"vlan_id obtenido: {mock_ws.vlan_id}"
        )

        # Propiedad: el CIDR almacenado refleja el nuevo valor
        normalized_nuevo = str(ipaddress.ip_network(cidr_nuevo, strict=False))
        assert mock_ws.cidr == normalized_nuevo, (
            f"El CIDR almacenado no se actualizó. "
            f"Esperado: {normalized_nuevo}, Obtenido: {mock_ws.cidr}"
        )

    @given(cidr=valid_cidr_strategy(), ip=valid_ipv4_strategy())
    @settings(max_examples=100, deadline=None)
    def test_re_registro_mismo_cidr_mantiene_vlan(self, cidr, ip):
        """
        Cuando una workstation se re-registra con el MISMO CIDR,
        su vlan_id no cambia (se mantiene la misma VLAN).

        Esto verifica que la re-asignación solo ocurre cuando el CIDR
        realmente cambia, no en cada re-registro.

        **Validates: Requirements 2.5**
        """
        org_id = str(uuid.uuid4())

        # VLAN actual (asociada al CIDR actual)
        vlan_actual_id = uuid.uuid4()
        mock_vlan = _crear_mock_vlan(vlan_actual_id, [cidr], org_id)

        # Workstation existente con el mismo CIDR
        mock_ws = _crear_workstation_existente(
            org_id, ip, cidr, str(vlan_actual_id)
        )

        # Configurar mock de BD
        mock_db = MagicMock()

        mock_ws_query = MagicMock()
        mock_ws_query.first.return_value = mock_ws

        mock_vlan_query = MagicMock()
        mock_vlan_query.all.return_value = [mock_vlan]

        def query_side_effect(model):
            mock_q = MagicMock()
            if model == Workstation:
                mock_q.filter_by.return_value = mock_ws_query
            else:
                mock_q.filter_by.return_value = mock_vlan_query
            return mock_q

        mock_db.query.side_effect = query_side_effect

        # Ejecutar re-registro con el MISMO CIDR
        self.service.register_workstation(
            mock_db,
            ip_private=ip,
            public_ip="203.0.113.1",
            cidr=cidr,
            tray_version="2.1.0"
        )

        # Propiedad: vlan_id se mantiene igual (misma VLAN)
        assert mock_ws.vlan_id == str(vlan_actual_id), (
            f"vlan_id cambió cuando el CIDR no cambió. "
            f"CIDR: {cidr}, vlan_id esperado: {vlan_actual_id}, "
            f"vlan_id obtenido: {mock_ws.vlan_id}"
        )

        # Propiedad: el CIDR almacenado sigue siendo el mismo
        assert mock_ws.cidr == cidr, (
            f"El CIDR almacenado cambió inesperadamente. "
            f"Esperado: {cidr}, Obtenido: {mock_ws.cidr}"
        )
