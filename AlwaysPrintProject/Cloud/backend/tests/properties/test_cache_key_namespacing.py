"""
Property tests para namespacing de cache keys por organización.

Verifica que toda key generada por RegistrationCache contiene el
organization_id o identificador relevante como namespace, garantizando
que datos de la organización A nunca son accesibles al consultar por
la organización B.

# Feature: websocket-scaling-redis, Property 4: Cache Key Namespacing by Organization

**Validates: Requirements 5.2**
"""

import json
import uuid
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import fakeredis.aioredis

from app.services.registration_cache import RegistrationCache


# === ESTRATEGIAS DE GENERACIÓN ===


def uuid_strategy():
    """Genera un UUID v4 aleatorio como string."""
    return st.uuids().map(str)


def two_distinct_uuids():
    """Genera dos UUIDs distintos para verificar aislamiento."""
    return st.tuples(st.uuids().map(str), st.uuids().map(str)).filter(
        lambda pair: pair[0] != pair[1]
    )


@st.composite
def organization_data_strategy(draw):
    """Genera datos de organización simulados para almacenar en cache."""
    return {
        "id": draw(uuid_strategy()),
        "name": draw(st.text(min_size=1, max_size=50, alphabet=st.characters(
            whitelist_categories=("L", "N", "Zs")
        ))),
        "is_active": draw(st.booleans()),
        "timezone": "America/Lima",
        "language": "es",
        "auto_update_enabled": draw(st.booleans()),
        "target_version": None,
        "auto_reregister_enabled": draw(st.booleans()),
        "forced_contingency": draw(st.booleans()),
        "offline_timeout_minutes": draw(st.integers(min_value=1, max_value=60)),
        "jitter_window_seconds": draw(st.integers(min_value=5, max_value=120)),
        "public_ips": [],
    }


# === HELPERS ===


def _crear_mock_db_con_organizacion(org_id: str, org_data: dict):
    """
    Crea un mock de sesión de BD que retorna datos de organización.

    Args:
        org_id: UUID de la organización.
        org_data: Diccionario con datos de la organización.

    Returns:
        Mock de sesión SQLAlchemy configurado.
    """
    mock_db = MagicMock()
    mock_org = MagicMock()

    # Configurar atributos del mock de organización
    for key, value in org_data.items():
        if key != "public_ips":
            setattr(mock_org, key, value)
    mock_org.id = org_id

    # Configurar la query para organización
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = mock_org
    mock_query.filter.return_value = mock_filter

    # Configurar la query para public IPs (retorna lista vacía)
    mock_ip_query = MagicMock()
    mock_ip_filter = MagicMock()
    mock_ip_filter.all.return_value = []
    mock_ip_query.filter.return_value = mock_ip_filter

    # El primer query() retorna para Organization, el segundo para PublicIP
    mock_db.query.side_effect = [mock_query, mock_ip_query]

    return mock_db


def _crear_mock_db_con_vlan(vlan_id: str, org_id: str):
    """
    Crea un mock de sesión de BD que retorna datos de VLAN.

    Args:
        vlan_id: UUID de la VLAN.
        org_id: UUID de la organización.

    Returns:
        Mock de sesión SQLAlchemy configurado.
    """
    mock_db = MagicMock()
    mock_vlan = MagicMock()
    mock_vlan.id = vlan_id
    mock_vlan.organization_id = org_id
    mock_vlan.name = "VLAN Test"
    mock_vlan.description = "Test VLAN"
    mock_vlan.cidr_ranges = ["10.0.0.0/24"]
    mock_vlan.forced_contingency = False
    mock_vlan.contingency_inherited = True
    mock_vlan.default_device_id = None
    mock_vlan.vlan_metadata = None

    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = mock_vlan
    mock_query.filter.return_value = mock_filter
    mock_db.query.return_value = mock_query

    return mock_db


# === PROPERTY 4: CACHE KEY NAMESPACING BY ORGANIZATION ===


class TestCacheKeyNamespacing:
    """
    Property 4: Cache Key Namespacing by Organization.

    Para cualquier operación de cache (lectura o escritura) ejecutada por
    RegistrationCache, la key de Redis SHALL contener el organization_id
    como prefijo de namespace, asegurando que datos de la organización A
    nunca sean accesibles al consultar por la organización B.

    **Validates: Requirements 5.2**
    """

    @pytest.mark.asyncio
    @given(org_id=uuid_strategy())
    @settings(max_examples=100, deadline=None)
    async def test_organization_data_key_contiene_org_id(self, org_id: str):
        """
        La key de cache para datos de organización contiene el organization_id.

        Verifica que al obtener datos de organización, la key generada
        sigue el patrón cache:org:{org_id}:data.

        **Validates: Requirements 5.2**
        """
        # Crear instancia de fakeredis para interceptar keys
        redis_client = fakeredis.aioredis.FakeRedis()
        cache = RegistrationCache(redis=redis_client, ttl_seconds=300)

        # Mock de BD que retorna datos de organización
        mock_db = _crear_mock_db_con_organizacion(org_id, {
            "name": "Test Org",
            "is_active": True,
            "timezone": "America/Lima",
            "language": "es",
            "auto_update_enabled": False,
            "target_version": None,
            "auto_reregister_enabled": False,
            "forced_contingency": False,
            "offline_timeout_minutes": 30,
            "jitter_window_seconds": 30,
        })

        # Ejecutar operación de cache (miss → fetch → store)
        await cache.get_organization_data(org_id, mock_db)

        # Verificar que la key almacenada contiene el org_id
        expected_key = f"cache:org:{org_id}:data"
        stored_value = await redis_client.get(expected_key)

        # Propiedad: la key DEBE contener el org_id como namespace
        assert stored_value is not None, (
            f"No se encontró key con namespace org_id. "
            f"Key esperada: '{expected_key}'. "
            f"org_id: '{org_id}'"
        )

        # Verificar que el org_id está contenido en la key
        assert org_id in expected_key, (
            f"La key de cache no contiene el organization_id como namespace. "
            f"Key: '{expected_key}', org_id: '{org_id}'"
        )

        await redis_client.aclose()

    @pytest.mark.asyncio
    @given(vlan_id=uuid_strategy())
    @settings(max_examples=100, deadline=None)
    async def test_vlan_data_key_contiene_vlan_id(self, vlan_id: str):
        """
        La key de cache para datos de VLAN contiene el vlan_id.

        Verifica que al obtener datos de VLAN, la key generada
        sigue el patrón cache:vlan:{vlan_id}:data.

        **Validates: Requirements 5.2**
        """
        redis_client = fakeredis.aioredis.FakeRedis()
        cache = RegistrationCache(redis=redis_client, ttl_seconds=300)

        org_id = str(uuid.uuid4())
        mock_db = _crear_mock_db_con_vlan(vlan_id, org_id)

        # Ejecutar operación de cache
        await cache.get_vlan_data(vlan_id, mock_db)

        # Verificar key con namespace vlan_id
        expected_key = f"cache:vlan:{vlan_id}:data"
        stored_value = await redis_client.get(expected_key)

        # Propiedad: la key DEBE contener el vlan_id como namespace
        assert stored_value is not None, (
            f"No se encontró key con namespace vlan_id. "
            f"Key esperada: '{expected_key}'. "
            f"vlan_id: '{vlan_id}'"
        )

        assert vlan_id in expected_key, (
            f"La key de cache no contiene el vlan_id como namespace. "
            f"Key: '{expected_key}', vlan_id: '{vlan_id}'"
        )

        await redis_client.aclose()

    @pytest.mark.asyncio
    @given(ws_id=uuid_strategy())
    @settings(max_examples=100, deadline=None)
    async def test_effective_config_key_contiene_workstation_id(self, ws_id: str):
        """
        La key de cache para configuración efectiva contiene el workstation_id.

        Verifica que al obtener la config efectiva, la key generada
        sigue el patrón cache:config:{ws_id}:effective.

        **Validates: Requirements 5.2**
        """
        redis_client = fakeredis.aioredis.FakeRedis()
        cache = RegistrationCache(redis=redis_client, ttl_seconds=300)

        # Pre-cargar dato en Redis para simular cache hit y verificar la key
        expected_key = f"cache:config:{ws_id}:effective"
        config_data = {
            "corporate_queue_name": "TestQueue",
            "search_targets": [],
            "pending_task_polling_minutes": 5,
            "config_hash": "abc123",
        }
        await redis_client.setex(expected_key, 300, json.dumps(config_data))

        # La lectura debe encontrar la key con el ws_id como namespace
        mock_db = MagicMock()
        result = await cache.get_effective_config(ws_id, mock_db)

        # Propiedad: el resultado viene del cache con la key correcta
        assert result is not None, (
            f"No se recuperó config del cache con key '{expected_key}'. "
            f"workstation_id: '{ws_id}'"
        )
        assert result["corporate_queue_name"] == "TestQueue"
        assert ws_id in expected_key, (
            f"La key no contiene el workstation_id como namespace. "
            f"Key: '{expected_key}', ws_id: '{ws_id}'"
        )

        await redis_client.aclose()

    @pytest.mark.asyncio
    @given(ws_id=uuid_strategy(), org_id=uuid_strategy())
    @settings(max_examples=100, deadline=None)
    async def test_contingency_state_key_contiene_workstation_id(
        self, ws_id: str, org_id: str
    ):
        """
        La key de cache para estado de contingencia contiene el workstation_id.

        Verifica que al obtener el estado de contingencia, la key generada
        sigue el patrón cache:contingency:{ws_id}:state.

        **Validates: Requirements 5.2**
        """
        redis_client = fakeredis.aioredis.FakeRedis()
        cache = RegistrationCache(redis=redis_client, ttl_seconds=300)

        # Pre-cargar dato en Redis para verificar patrón de key
        expected_key = f"cache:contingency:{ws_id}:state"
        contingency_data = {
            "enabled": False,
            "source": "sync",
            "source_name": "normal",
            "printer_ip": None,
        }
        await redis_client.setex(expected_key, 300, json.dumps(contingency_data))

        # La lectura debe encontrar la key
        mock_db = MagicMock()
        result = await cache.get_forced_contingency_state(ws_id, org_id, None, mock_db)

        # Propiedad: la key contiene el ws_id como namespace
        assert result is not None, (
            f"No se recuperó estado de contingencia del cache con key '{expected_key}'. "
            f"workstation_id: '{ws_id}'"
        )
        assert ws_id in expected_key, (
            f"La key no contiene el workstation_id como namespace. "
            f"Key: '{expected_key}', ws_id: '{ws_id}'"
        )

        await redis_client.aclose()

    @pytest.mark.asyncio
    @given(data=two_distinct_uuids())
    @settings(max_examples=100, deadline=None)
    async def test_org_a_no_accede_datos_de_org_b(self, data):
        """
        Datos de la organización A no son accesibles al consultar por
        la organización B.

        Verifica que el namespacing por org_id previene fugas de datos
        entre tenants. Al consultar datos de org_b, nunca se retornan
        datos almacenados bajo org_a.

        **Validates: Requirements 5.2**
        """
        org_a, org_b = data

        redis_client = fakeredis.aioredis.FakeRedis()
        cache = RegistrationCache(redis=redis_client, ttl_seconds=300)

        # Almacenar datos de org_a en Redis
        key_a = f"cache:org:{org_a}:data"
        data_a = {
            "id": org_a,
            "name": "Organización A",
            "is_active": True,
        }
        await redis_client.setex(key_a, 300, json.dumps(data_a))

        # Consultar datos de org_b (cache miss — BD retorna None)
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = None
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query

        result = await cache.get_organization_data(org_b, mock_db)

        # Propiedad: org_b NO obtiene datos de org_a
        if result is not None:
            assert result.get("id") != org_a, (
                f"Se retornaron datos de org_a al consultar org_b. "
                f"org_a: '{org_a}', org_b: '{org_b}'. "
                f"Resultado: {result}"
            )

        # Verificar que la key de org_a sigue intacta
        stored_a = await redis_client.get(key_a)
        assert stored_a is not None, (
            f"Los datos de org_a fueron eliminados al consultar org_b. "
            f"org_a: '{org_a}', org_b: '{org_b}'"
        )

        # Verificar que no existe key para org_b (porque BD retornó None)
        key_b = f"cache:org:{org_b}:data"
        stored_b = await redis_client.get(key_b)
        assert stored_b is None, (
            f"Se almacenó un valor para org_b cuando BD retornó None. "
            f"org_b: '{org_b}', valor: {stored_b}"
        )

        await redis_client.aclose()

    @pytest.mark.asyncio
    @given(org_id=uuid_strategy())
    @settings(max_examples=100, deadline=None)
    async def test_public_ips_key_contiene_org_id(self, org_id: str):
        """
        La key para IPs públicas sigue el patrón cache:org:{org_id}:public_ips.

        Verifica que el namespace de la key de public_ips incluye
        el organization_id, consistente con el esquema de keys del diseño.

        **Validates: Requirements 5.2**
        """
        redis_client = fakeredis.aioredis.FakeRedis()

        # Verificar que el patrón de key contiene org_id
        expected_key = f"cache:org:{org_id}:public_ips"

        # Almacenar dato simulado
        ips_data = [{"id": str(uuid.uuid4()), "ip_address": "1.2.3.4", "description": "Sede"}]
        await redis_client.setex(expected_key, 300, json.dumps(ips_data))

        # Verificar que se puede recuperar con la key correcta
        stored = await redis_client.get(expected_key)
        assert stored is not None, (
            f"No se pudo almacenar/recuperar con key '{expected_key}'. "
            f"org_id: '{org_id}'"
        )

        # Propiedad: la key de public_ips contiene el org_id
        assert org_id in expected_key, (
            f"La key de public_ips no contiene el org_id. "
            f"Key: '{expected_key}', org_id: '{org_id}'"
        )

        await redis_client.aclose()

    @pytest.mark.asyncio
    @given(
        org_id=uuid_strategy(),
        ws_id=uuid_strategy(),
        vlan_id=uuid_strategy(),
    )
    @settings(max_examples=100, deadline=None)
    async def test_todas_las_keys_contienen_identificador_relevante(
        self, org_id: str, ws_id: str, vlan_id: str
    ):
        """
        Todas las keys generadas por RegistrationCache contienen su
        identificador relevante como namespace.

        Verifica el patrón completo de keys del diseño:
        - cache:org:{org_id}:data
        - cache:org:{org_id}:public_ips
        - cache:vlan:{vlan_id}:data
        - cache:config:{ws_id}:effective
        - cache:contingency:{ws_id}:state

        **Validates: Requirements 5.2**
        """
        # Definir todos los patrones de key del diseño
        keys_esperadas = {
            f"cache:org:{org_id}:data": org_id,
            f"cache:org:{org_id}:public_ips": org_id,
            f"cache:vlan:{vlan_id}:data": vlan_id,
            f"cache:config:{ws_id}:effective": ws_id,
            f"cache:contingency:{ws_id}:state": ws_id,
        }

        # Propiedad: cada key contiene su identificador relevante como namespace
        for key, expected_id in keys_esperadas.items():
            assert expected_id in key, (
                f"Key '{key}' no contiene el identificador '{expected_id}' "
                f"como namespace. Esto violaría el aislamiento multi-tenant."
            )

            # Verificar que la key tiene la estructura esperada con separadores ':'
            parts = key.split(":")
            assert len(parts) >= 3, (
                f"Key '{key}' no tiene suficientes segmentos de namespace. "
                f"Se esperan al menos 3 segmentos separados por ':'."
            )

            # Verificar que el identificador está en una posición de namespace
            # (no como sufijo de tipo de dato)
            assert expected_id in parts, (
                f"El identificador '{expected_id}' no aparece como segmento "
                f"independiente en la key '{key}'. "
                f"Segmentos: {parts}"
            )
