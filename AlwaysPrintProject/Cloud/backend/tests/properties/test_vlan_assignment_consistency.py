"""
Property tests para detect_or_create_vlan_for_cidr.

Verifica las propiedades de consistencia en la asignación de VLANs por CIDR:
- Property 4: VLAN Assignment Consistency
- Property 5: Registration Idempotence

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**
"""

import ipaddress
import uuid
from unittest.mock import MagicMock, PropertyMock

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
    
    # Construir IP y normalizar a forma canónica (host bits a cero)
    raw_cidr = f"{o1}.{o2}.{o3}.{o4}/{prefix}"
    try:
        network = ipaddress.ip_network(raw_cidr, strict=False)
    except ValueError:
        assume(False)
        return None
    
    return str(network)


@st.composite
def valid_cidr_with_host_bits_strategy(draw):
    """
    Genera un CIDR IPv4 que puede tener host bits encendidos (no normalizado).
    
    Útil para verificar que la normalización funciona correctamente.
    """
    o1 = draw(_octet)
    o2 = draw(_octet)
    o3 = draw(_octet)
    o4 = draw(_octet)
    prefix = draw(_prefix)
    
    raw_cidr = f"{o1}.{o2}.{o3}.{o4}/{prefix}"
    # Verificar que es parseable
    try:
        ipaddress.ip_network(raw_cidr, strict=False)
    except ValueError:
        assume(False)
        return None
    
    return raw_cidr


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


def _crear_mock_db_con_vlans(vlans_existentes):
    """
    Crea un mock de sesión de BD que retorna las VLANs indicadas.
    
    Args:
        vlans_existentes: Lista de mocks de VLAN a retornar en queries
        
    Returns:
        Mock de sesión SQLAlchemy configurado
    """
    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_query.all.return_value = vlans_existentes
    mock_db.query.return_value.filter_by.return_value = mock_query
    return mock_db


def _crear_mock_db_sin_vlans():
    """
    Crea un mock de sesión de BD sin VLANs existentes.
    Simula la creación de VLAN asignando un UUID al hacer add().
    
    Returns:
        Mock de sesión SQLAlchemy configurado para auto-creación
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


# === PROPERTY 4: VLAN ASSIGNMENT CONSISTENCY ===


class TestVlanAssignmentConsistency:
    """
    Property 4: VLAN Assignment Consistency.
    
    Para cualquier CIDR válido y organización, llamar a detect_or_create_vlan_for_cidr
    SHALL retornar un UUID de VLAN no nulo, y el cidr_ranges de la VLAN retornada
    SHALL contener el CIDR normalizado. Si una VLAN existente ya contiene el CIDR,
    SHALL ser reutilizada; de lo contrario, una nueva VLAN con nombre VLAN_{CIDR}
    SHALL ser creada.
    
    **Validates: Requirements 3.1, 3.2, 3.3**
    """

    def setup_method(self):
        """Configuración común para cada test."""
        self.service = WorkstationService()

    @given(cidr=valid_cidr_strategy())
    @settings(max_examples=100, deadline=None)
    def test_siempre_retorna_uuid_no_nulo(self, cidr: str):
        """
        Para cualquier CIDR válido, detect_or_create_vlan_for_cidr siempre
        retorna un UUID no nulo (ya sea de VLAN existente o nueva).
        
        **Validates: Requirements 3.3**
        """
        org_id = str(uuid.uuid4())
        mock_db, _ = _crear_mock_db_sin_vlans()
        
        resultado = self.service.detect_or_create_vlan_for_cidr(
            mock_db, org_id, cidr
        )
        
        # Propiedad: siempre retorna un UUID válido (no None)
        assert resultado is not None, (
            f"detect_or_create_vlan_for_cidr retornó None para CIDR válido: {cidr}"
        )
        # Verificar que es un UUID válido
        try:
            uuid.UUID(resultado)
        except ValueError:
            pytest.fail(f"El resultado '{resultado}' no es un UUID válido")

    @given(cidr=valid_cidr_with_host_bits_strategy())
    @settings(max_examples=100, deadline=None)
    def test_vlan_existente_es_reutilizada(self, cidr: str):
        """
        Si una VLAN existente contiene el CIDR normalizado, esa VLAN es
        reutilizada (no se crea una nueva).
        
        **Validates: Requirements 3.1**
        """
        org_id = str(uuid.uuid4())
        normalized_cidr = str(ipaddress.ip_network(cidr, strict=False))
        
        # Crear VLAN existente que contiene el CIDR
        vlan_id = uuid.uuid4()
        mock_vlan = _crear_mock_vlan(vlan_id, [normalized_cidr], org_id)
        mock_db = _crear_mock_db_con_vlans([mock_vlan])
        
        resultado = self.service.detect_or_create_vlan_for_cidr(
            mock_db, org_id, cidr
        )
        
        # Propiedad: retorna la VLAN existente
        assert resultado == str(vlan_id), (
            f"No se reutilizó la VLAN existente. "
            f"Esperado: {vlan_id}, Obtenido: {resultado}"
        )
        # Propiedad: no se creó VLAN nueva
        mock_db.add.assert_not_called()

    @given(cidr=valid_cidr_strategy())
    @settings(max_examples=100, deadline=None)
    def test_nueva_vlan_tiene_nombre_correcto(self, cidr: str):
        """
        Cuando no existe VLAN con el CIDR, se crea una nueva con nombre
        VLAN_{CIDR_normalizado}.
        
        **Validates: Requirements 3.2**
        """
        org_id = str(uuid.uuid4())
        normalized_cidr = str(ipaddress.ip_network(cidr, strict=False))
        mock_db, _ = _crear_mock_db_sin_vlans()
        
        self.service.detect_or_create_vlan_for_cidr(mock_db, org_id, cidr)
        
        # Propiedad: la VLAN creada tiene el nombre correcto
        mock_db.add.assert_called_once()
        vlan_creada = mock_db.add.call_args[0][0]
        nombre_esperado = f"VLAN_{normalized_cidr}"
        assert vlan_creada.name == nombre_esperado, (
            f"Nombre incorrecto. Esperado: '{nombre_esperado}', "
            f"Obtenido: '{vlan_creada.name}'"
        )

    @given(cidr=valid_cidr_strategy())
    @settings(max_examples=100, deadline=None)
    def test_nueva_vlan_contiene_cidr_en_ranges(self, cidr: str):
        """
        Cuando se crea una VLAN nueva, su cidr_ranges contiene el CIDR normalizado.
        
        **Validates: Requirements 3.2**
        """
        org_id = str(uuid.uuid4())
        normalized_cidr = str(ipaddress.ip_network(cidr, strict=False))
        mock_db, _ = _crear_mock_db_sin_vlans()
        
        self.service.detect_or_create_vlan_for_cidr(mock_db, org_id, cidr)
        
        # Propiedad: cidr_ranges contiene el CIDR normalizado
        mock_db.add.assert_called_once()
        vlan_creada = mock_db.add.call_args[0][0]
        assert normalized_cidr in vlan_creada.cidr_ranges, (
            f"El CIDR '{normalized_cidr}' no está en cidr_ranges: "
            f"{vlan_creada.cidr_ranges}"
        )

    @given(cidr=valid_cidr_strategy())
    @settings(max_examples=100, deadline=None)
    def test_nueva_vlan_pertenece_a_organizacion(self, cidr: str):
        """
        Cuando se crea una VLAN nueva, pertenece a la organización indicada.
        
        **Validates: Requirements 3.2**
        """
        org_id = str(uuid.uuid4())
        mock_db, _ = _crear_mock_db_sin_vlans()
        
        self.service.detect_or_create_vlan_for_cidr(mock_db, org_id, cidr)
        
        # Propiedad: la VLAN pertenece a la organización correcta
        mock_db.add.assert_called_once()
        vlan_creada = mock_db.add.call_args[0][0]
        assert vlan_creada.organization_id == org_id, (
            f"organization_id incorrecto. Esperado: '{org_id}', "
            f"Obtenido: '{vlan_creada.organization_id}'"
        )


# === PROPERTY 5: REGISTRATION IDEMPOTENCE ===


class TestRegistrationIdempotence:
    """
    Property 5: Registration Idempotence.
    
    Para cualquier CIDR, registrar múltiples workstations con el mismo CIDR
    dentro de la misma organización SHALL resultar en todas las workstations
    apuntando a la misma VLAN, y exactamente una VLAN conteniendo ese CIDR
    SHALL existir.
    
    **Validates: Requirements 3.4**
    """

    def setup_method(self):
        """Configuración común para cada test."""
        self.service = WorkstationService()

    @given(
        cidr=valid_cidr_strategy(),
        num_registros=st.integers(min_value=2, max_value=10)
    )
    @settings(max_examples=50, deadline=None)
    def test_multiples_registros_mismo_cidr_misma_vlan(
        self, cidr: str, num_registros: int
    ):
        """
        Múltiples llamadas a detect_or_create_vlan_for_cidr con el mismo CIDR
        y organización retornan siempre el mismo UUID de VLAN.
        
        Simula el escenario donde la primera llamada crea la VLAN y las
        siguientes la encuentran existente.
        
        **Validates: Requirements 3.4**
        """
        org_id = str(uuid.uuid4())
        normalized_cidr = str(ipaddress.ip_network(cidr, strict=False))
        
        # Primera llamada: no hay VLANs, se crea una nueva
        vlan_id_creado = uuid.uuid4()
        mock_db_primera = MagicMock()
        mock_query_primera = MagicMock()
        mock_query_primera.all.return_value = []
        mock_db_primera.query.return_value.filter_by.return_value = mock_query_primera
        
        def side_effect_add(vlan):
            vlan.id = vlan_id_creado
        mock_db_primera.add.side_effect = side_effect_add
        
        primer_resultado = self.service.detect_or_create_vlan_for_cidr(
            mock_db_primera, org_id, cidr
        )
        
        # Llamadas subsiguientes: la VLAN ya existe
        mock_vlan_existente = _crear_mock_vlan(
            vlan_id_creado, [normalized_cidr], org_id
        )
        
        resultados = [primer_resultado]
        for _ in range(num_registros - 1):
            mock_db_siguiente = _crear_mock_db_con_vlans([mock_vlan_existente])
            resultado = self.service.detect_or_create_vlan_for_cidr(
                mock_db_siguiente, org_id, cidr
            )
            resultados.append(resultado)
        
        # Propiedad: todos los resultados son el mismo UUID
        assert all(r == primer_resultado for r in resultados), (
            f"No todos los registros retornaron la misma VLAN. "
            f"Resultados: {resultados}"
        )
        
        # Propiedad: el resultado es un UUID válido no nulo
        assert primer_resultado is not None
        uuid.UUID(primer_resultado)  # Valida formato UUID

    @given(cidr=valid_cidr_strategy())
    @settings(max_examples=100, deadline=None)
    def test_segunda_llamada_no_crea_vlan_duplicada(self, cidr: str):
        """
        La segunda llamada con el mismo CIDR no crea una VLAN nueva,
        sino que reutiliza la existente.
        
        **Validates: Requirements 3.4**
        """
        org_id = str(uuid.uuid4())
        normalized_cidr = str(ipaddress.ip_network(cidr, strict=False))
        
        # Simular que ya existe una VLAN con ese CIDR (creada por primera llamada)
        vlan_id = uuid.uuid4()
        mock_vlan = _crear_mock_vlan(vlan_id, [normalized_cidr], org_id)
        mock_db = _crear_mock_db_con_vlans([mock_vlan])
        
        resultado = self.service.detect_or_create_vlan_for_cidr(
            mock_db, org_id, cidr
        )
        
        # Propiedad: retorna la VLAN existente sin crear nueva
        assert resultado == str(vlan_id), (
            f"No se reutilizó la VLAN existente en segunda llamada. "
            f"Esperado: {vlan_id}, Obtenido: {resultado}"
        )
        mock_db.add.assert_not_called()

    @given(cidr=valid_cidr_with_host_bits_strategy())
    @settings(max_examples=100, deadline=None)
    def test_cidr_no_normalizado_encuentra_vlan_normalizada(self, cidr: str):
        """
        Incluso si el CIDR de entrada tiene host bits encendidos, la búsqueda
        encuentra la VLAN que contiene la forma normalizada.
        
        Esto garantiza que workstations con el mismo segmento de red pero
        diferentes IPs de host se asignan a la misma VLAN.
        
        **Validates: Requirements 3.4**
        """
        org_id = str(uuid.uuid4())
        normalized_cidr = str(ipaddress.ip_network(cidr, strict=False))
        
        # VLAN existente con CIDR normalizado
        vlan_id = uuid.uuid4()
        mock_vlan = _crear_mock_vlan(vlan_id, [normalized_cidr], org_id)
        mock_db = _crear_mock_db_con_vlans([mock_vlan])
        
        # Llamar con CIDR posiblemente no normalizado
        resultado = self.service.detect_or_create_vlan_for_cidr(
            mock_db, org_id, cidr
        )
        
        # Propiedad: encuentra la VLAN correcta independientemente de normalización
        assert resultado == str(vlan_id), (
            f"CIDR '{cidr}' (normalizado: '{normalized_cidr}') no encontró "
            f"la VLAN existente. Resultado: {resultado}"
        )
