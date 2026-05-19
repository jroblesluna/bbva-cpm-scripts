"""
Property tests para aislamiento multi-tenant en VLANs.

Verifica que las VLANs auto-creadas respetan el aislamiento por organización:
- Las VLANs auto-creadas pertenecen exclusivamente a la organización de la workstation
- Las queries de VLANs filtran por organization_id
- El mismo CIDR puede existir en diferentes organizaciones sin conflicto

- Property 7: Tenant Isolation

**Validates: Requirements 5.1, 5.2, 5.3**
"""

import ipaddress
import uuid
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

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
def two_distinct_org_ids_strategy(draw):
    """
    Genera dos UUIDs de organización distintos.

    Útil para verificar aislamiento entre tenants.
    """
    org1 = str(uuid.uuid4())
    org2 = str(uuid.uuid4())
    assume(org1 != org2)
    return org1, org2


def _crear_mock_vlan(vlan_id, cidr_ranges, organization_id, name=None):
    """
    Crea un mock de VLAN con los campos necesarios.

    Args:
        vlan_id: UUID de la VLAN
        cidr_ranges: Lista de CIDRs asignados a la VLAN
        organization_id: UUID de la organización
        name: Nombre de la VLAN (opcional, se genera automáticamente)

    Returns:
        Mock de VLAN configurado
    """
    mock_vlan = MagicMock(spec=VLAN)
    mock_vlan.id = vlan_id
    mock_vlan.cidr_ranges = cidr_ranges
    mock_vlan.organization_id = organization_id
    mock_vlan.name = name or (f"VLAN_{cidr_ranges[0]}" if cidr_ranges else "VLAN_empty")
    return mock_vlan


def _crear_mock_db_por_organizacion(vlans_por_org):
    """
    Crea un mock de sesión de BD que retorna VLANs filtradas por organization_id.

    Simula el comportamiento real de filter_by(organization_id=X) retornando
    solo las VLANs de esa organización específica.

    Args:
        vlans_por_org: Diccionario {organization_id: [lista_de_vlans]}

    Returns:
        Mock de sesión SQLAlchemy configurado con filtrado por organización
    """
    mock_db = MagicMock()

    def filter_by_side_effect(**kwargs):
        """Simula filter_by retornando VLANs de la organización solicitada."""
        mock_result = MagicMock()
        org_id = kwargs.get("organization_id")
        if org_id and org_id in vlans_por_org:
            mock_result.all.return_value = vlans_por_org[org_id]
        else:
            mock_result.all.return_value = []
        return mock_result

    mock_db.query.return_value.filter_by.side_effect = filter_by_side_effect

    return mock_db


def _crear_mock_db_sin_vlans_para_org(org_id):
    """
    Crea un mock de sesión de BD sin VLANs para una organización específica.
    Simula la creación de VLAN asignando un UUID al hacer add().

    Args:
        org_id: UUID de la organización

    Returns:
        Tupla (mock_db, new_vlan_id) con el mock configurado y el UUID asignado
    """
    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_query.all.return_value = []
    mock_db.query.return_value.filter_by.return_value = mock_query

    # Simular que flush asigna un ID a la VLAN creada
    new_vlan_id = uuid.uuid4()

    def side_effect_add(vlan):
        vlan.id = new_vlan_id

    mock_db.add.side_effect = side_effect_add

    return mock_db, new_vlan_id


# === PROPERTY 7: TENANT ISOLATION ===


class TestTenantIsolation:
    """
    Property 7: Tenant Isolation.

    Para cualquier VLAN auto-creada, su organization_id SHALL coincidir con
    la organización de la workstation que la registra. Las queries de VLANs
    SHALL retornar solo resultados de la organización especificada. El mismo
    CIDR MAY existir en diferentes organizaciones sin conflicto.

    **Validates: Requirements 5.1, 5.2, 5.3**
    """

    def setup_method(self):
        """Configuración común para cada test."""
        self.service = WorkstationService()

    @given(cidr=valid_cidr_strategy())
    @settings(max_examples=100, deadline=None)
    def test_vlan_auto_creada_pertenece_a_organizacion_registrante(self, cidr: str):
        """
        Para cualquier VLAN auto-creada, su organization_id coincide con
        la organización de la workstation que la registra.

        Verifica que detect_or_create_vlan_for_cidr asigna correctamente
        el organization_id a la VLAN nueva.

        **Validates: Requirements 5.1**
        """
        org_id = str(uuid.uuid4())
        mock_db, _ = _crear_mock_db_sin_vlans_para_org(org_id)

        self.service.detect_or_create_vlan_for_cidr(mock_db, org_id, cidr)

        # Propiedad: la VLAN creada pertenece a la organización indicada
        mock_db.add.assert_called_once()
        vlan_creada = mock_db.add.call_args[0][0]
        assert vlan_creada.organization_id == org_id, (
            f"La VLAN auto-creada tiene organization_id incorrecto. "
            f"Esperado: '{org_id}', Obtenido: '{vlan_creada.organization_id}'. "
            f"CIDR: {cidr}"
        )

    @given(cidr=valid_cidr_strategy())
    @settings(max_examples=100, deadline=None)
    def test_query_vlans_filtra_por_organization_id(self, cidr: str):
        """
        Las queries de VLANs solo retornan resultados de la organización
        especificada, previniendo fuga de datos entre tenants.

        Verifica que _find_vlan_with_cidr usa filter_by(organization_id=...)
        para aislar los resultados por organización.

        **Validates: Requirements 5.2**
        """
        org_a = str(uuid.uuid4())
        org_b = str(uuid.uuid4())
        normalized_cidr = str(ipaddress.ip_network(cidr, strict=False))

        # VLAN del CIDR existe en org_b pero NO en org_a
        vlan_b_id = uuid.uuid4()
        mock_vlan_b = _crear_mock_vlan(vlan_b_id, [normalized_cidr], org_b)

        vlans_por_org = {
            org_a: [],  # org_a no tiene VLANs
            org_b: [mock_vlan_b],  # org_b tiene la VLAN con el CIDR
        }
        mock_db = _crear_mock_db_por_organizacion(vlans_por_org)

        # Buscar VLAN en org_a — no debe encontrar la VLAN de org_b
        resultado = self.service._find_vlan_with_cidr(mock_db, org_a, normalized_cidr)

        # Propiedad: no se retorna la VLAN de otra organización
        assert resultado is None, (
            f"_find_vlan_with_cidr retornó una VLAN de otra organización. "
            f"CIDR '{normalized_cidr}' existe en org_b pero se consultó org_a. "
            f"Resultado: {resultado}"
        )

    @given(cidr=valid_cidr_strategy())
    @settings(max_examples=100, deadline=None)
    def test_query_vlans_retorna_vlan_de_misma_organizacion(self, cidr: str):
        """
        Las queries de VLANs retornan correctamente las VLANs de la
        organización solicitada.

        Complemento del test anterior: verifica que sí se encuentran
        las VLANs propias de la organización.

        **Validates: Requirements 5.2**
        """
        org_id = str(uuid.uuid4())
        normalized_cidr = str(ipaddress.ip_network(cidr, strict=False))

        # VLAN existe en la organización consultada
        vlan_id = uuid.uuid4()
        mock_vlan = _crear_mock_vlan(vlan_id, [normalized_cidr], org_id)

        vlans_por_org = {
            org_id: [mock_vlan],
        }
        mock_db = _crear_mock_db_por_organizacion(vlans_por_org)

        # Buscar VLAN en la misma organización — debe encontrarla
        resultado = self.service._find_vlan_with_cidr(mock_db, org_id, normalized_cidr)

        # Propiedad: se retorna la VLAN de la misma organización
        assert resultado == str(vlan_id), (
            f"_find_vlan_with_cidr no encontró la VLAN de la misma organización. "
            f"CIDR: '{normalized_cidr}', org_id: '{org_id}'. "
            f"Esperado: {vlan_id}, Obtenido: {resultado}"
        )

    @given(cidr=valid_cidr_strategy())
    @settings(max_examples=100, deadline=None)
    def test_mismo_cidr_en_diferentes_organizaciones_sin_conflicto(self, cidr: str):
        """
        El mismo CIDR puede existir en diferentes organizaciones sin conflicto.

        Verifica que detect_or_create_vlan_for_cidr permite crear VLANs con
        el mismo CIDR en organizaciones distintas, ya que el aislamiento es
        por organización.

        **Validates: Requirements 5.3**
        """
        org_a = str(uuid.uuid4())
        org_b = str(uuid.uuid4())
        normalized_cidr = str(ipaddress.ip_network(cidr, strict=False))

        # org_a ya tiene una VLAN con el CIDR
        vlan_a_id = uuid.uuid4()
        mock_vlan_a = _crear_mock_vlan(vlan_a_id, [normalized_cidr], org_a)

        # org_b no tiene VLANs — debe poder crear una con el mismo CIDR
        new_vlan_b_id = uuid.uuid4()

        vlans_por_org = {
            org_a: [mock_vlan_a],
            org_b: [],  # org_b no tiene VLANs
        }
        mock_db = _crear_mock_db_por_organizacion(vlans_por_org)

        # Simular creación de VLAN en org_b
        def side_effect_add(vlan):
            vlan.id = new_vlan_b_id

        mock_db.add.side_effect = side_effect_add

        # Crear VLAN con el mismo CIDR en org_b
        resultado = self.service.detect_or_create_vlan_for_cidr(
            mock_db, org_b, cidr
        )

        # Propiedad: se puede crear VLAN con el mismo CIDR en otra organización
        assert resultado is not None, (
            f"detect_or_create_vlan_for_cidr rechazó la creación de VLAN con "
            f"CIDR '{normalized_cidr}' en org_b, aunque solo existe en org_a. "
            f"El aislamiento multi-tenant debe permitir CIDRs duplicados entre orgs."
        )
        assert resultado == str(new_vlan_b_id), (
            f"Se esperaba la VLAN nueva de org_b. "
            f"Esperado: {new_vlan_b_id}, Obtenido: {resultado}"
        )

    @given(cidr=valid_cidr_strategy())
    @settings(max_examples=100, deadline=None)
    def test_validate_cidr_uniqueness_no_cruza_organizaciones(self, cidr: str):
        """
        validate_cidr_uniqueness solo verifica unicidad dentro de la misma
        organización, no entre organizaciones diferentes.

        El mismo CIDR en otra organización no genera conflicto.

        **Validates: Requirements 5.3**
        """
        org_a = str(uuid.uuid4())
        org_b = str(uuid.uuid4())
        normalized_cidr = str(ipaddress.ip_network(cidr, strict=False))

        # org_a tiene una VLAN con el CIDR
        vlan_a_id = uuid.uuid4()
        mock_vlan_a = _crear_mock_vlan(vlan_a_id, [normalized_cidr], org_a)

        # Configurar mock para que al consultar org_b no retorne VLANs de org_a
        vlans_por_org = {
            org_a: [mock_vlan_a],
            org_b: [],  # org_b no tiene VLANs
        }
        mock_db = _crear_mock_db_por_organizacion(vlans_por_org)

        # Validar unicidad del CIDR en org_b — no debe haber conflicto
        resultado = self.service.validate_cidr_uniqueness(
            mock_db, org_b, [normalized_cidr]
        )

        # Propiedad: no hay conflicto cross-tenant
        assert resultado is None, (
            f"validate_cidr_uniqueness detectó conflicto cross-tenant. "
            f"CIDR '{normalized_cidr}' existe en org_a pero se validó en org_b. "
            f"El aislamiento multi-tenant debe prevenir conflictos entre orgs. "
            f"Resultado: {resultado}"
        )

    @given(cidr=valid_cidr_strategy())
    @settings(max_examples=100, deadline=None)
    def test_detect_or_create_no_reutiliza_vlan_de_otra_organizacion(self, cidr: str):
        """
        detect_or_create_vlan_for_cidr nunca reutiliza una VLAN de otra
        organización, incluso si tiene el mismo CIDR.

        Verifica que el filtrado por organization_id previene la asignación
        incorrecta de VLANs entre tenants.

        **Validates: Requirements 5.1, 5.2**
        """
        org_a = str(uuid.uuid4())
        org_b = str(uuid.uuid4())
        normalized_cidr = str(ipaddress.ip_network(cidr, strict=False))

        # org_a tiene una VLAN con el CIDR
        vlan_a_id = uuid.uuid4()
        mock_vlan_a = _crear_mock_vlan(vlan_a_id, [normalized_cidr], org_a)

        # org_b no tiene VLANs
        new_vlan_b_id = uuid.uuid4()

        vlans_por_org = {
            org_a: [mock_vlan_a],
            org_b: [],
        }
        mock_db = _crear_mock_db_por_organizacion(vlans_por_org)

        def side_effect_add(vlan):
            vlan.id = new_vlan_b_id

        mock_db.add.side_effect = side_effect_add

        # Buscar/crear VLAN para org_b con el mismo CIDR que org_a
        resultado = self.service.detect_or_create_vlan_for_cidr(
            mock_db, org_b, cidr
        )

        # Propiedad: NO se reutiliza la VLAN de org_a
        assert resultado != str(vlan_a_id), (
            f"detect_or_create_vlan_for_cidr reutilizó la VLAN de otra organización. "
            f"VLAN {vlan_a_id} pertenece a org_a pero fue retornada para org_b. "
            f"CIDR: {normalized_cidr}"
        )

        # Propiedad: se crea una VLAN nueva para org_b
        assert resultado == str(new_vlan_b_id), (
            f"Se esperaba una VLAN nueva para org_b. "
            f"Esperado: {new_vlan_b_id}, Obtenido: {resultado}"
        )

        # Propiedad: la VLAN creada pertenece a org_b
        mock_db.add.assert_called_once()
        vlan_creada = mock_db.add.call_args[0][0]
        assert vlan_creada.organization_id == org_b, (
            f"La VLAN creada tiene organization_id incorrecto. "
            f"Esperado: '{org_b}', Obtenido: '{vlan_creada.organization_id}'"
        )
