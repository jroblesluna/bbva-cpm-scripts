"""
Property test para verificar que un cache hit elimina queries a la base de datos.

# Feature: websocket-scaling-redis, Property 5: Cache Hit Eliminates Database Query

Para cualquier tipo de dato cacheable (organization data, VLAN data, effective config,
forced contingency state) y cualquier identificador válido, si los datos existen en Redis
con TTL no expirado, RegistrationCache SHALL retornar los datos cacheados sin ejecutar
ninguna query a PostgreSQL.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**
"""

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

import fakeredis.aioredis

from app.services.registration_cache import RegistrationCache


# === ESTRATEGIAS DE GENERACIÓN ===


@st.composite
def organization_data_strategy(draw):
    """
    Genera datos aleatorios de organización válidos para cachear.

    Produce un dict con la estructura que retorna _fetch_organization_data.
    """
    org_id = str(uuid.uuid4())
    name = draw(st.text(min_size=1, max_size=50, alphabet=st.characters(
        whitelist_categories=("L", "N", "Zs"),
        whitelist_characters="_-"
    )))
    assume(name.strip() != "")

    # Generar entre 0 y 3 IPs públicas
    num_ips = draw(st.integers(min_value=0, max_value=3))
    public_ips = []
    for _ in range(num_ips):
        ip_parts = [draw(st.integers(min_value=1, max_value=254)) for _ in range(4)]
        public_ips.append({
            "id": str(uuid.uuid4()),
            "ip_address": ".".join(str(p) for p in ip_parts),
            "description": draw(st.text(min_size=0, max_size=30)),
        })

    return org_id, {
        "id": org_id,
        "name": name,
        "is_active": draw(st.booleans()),
        "timezone": draw(st.sampled_from(["America/Lima", "Europe/Madrid", "UTC"])),
        "language": draw(st.sampled_from(["es", "en", "pt"])),
        "auto_update_enabled": draw(st.booleans()),
        "target_version": draw(st.none() | st.text(min_size=3, max_size=10)),
        "auto_reregister_enabled": draw(st.booleans()),
        "forced_contingency": draw(st.booleans()),
        "offline_timeout_minutes": draw(st.integers(min_value=1, max_value=120)),
        "jitter_window_seconds": draw(st.integers(min_value=5, max_value=300)),
        "public_ips": public_ips,
    }


@st.composite
def vlan_data_strategy(draw):
    """
    Genera datos aleatorios de VLAN válidos para cachear.

    Produce un dict con la estructura que retorna _fetch_vlan_data.
    """
    vlan_id = str(uuid.uuid4())
    org_id = str(uuid.uuid4())

    # Generar CIDR válido
    octets = [draw(st.integers(min_value=0, max_value=255)) for _ in range(4)]
    prefix = draw(st.integers(min_value=8, max_value=30))
    cidr = f"{octets[0]}.{octets[1]}.{octets[2]}.{octets[3]}/{prefix}"

    return vlan_id, {
        "id": vlan_id,
        "organization_id": org_id,
        "name": draw(st.text(min_size=1, max_size=30, alphabet=st.characters(
            whitelist_categories=("L", "N"), whitelist_characters="_-"
        ))),
        "description": draw(st.text(min_size=0, max_size=50)),
        "cidr_ranges": [cidr],
        "forced_contingency": draw(st.booleans()),
        "contingency_inherited": draw(st.booleans()),
        "default_device_id": draw(st.none() | st.just(str(uuid.uuid4()))),
        "vlan_metadata": draw(st.none() | st.just({"key": "value"})),
    }


@st.composite
def effective_config_strategy(draw):
    """
    Genera configuración efectiva aleatoria válida para cachear.

    Produce un dict con la estructura que retorna _fetch_effective_config.
    """
    ws_id = str(uuid.uuid4())
    source_options = ["global", "vlan", "workstation"]

    config = {
        "corporate_queue_name": draw(st.text(min_size=1, max_size=20)),
        "search_targets": draw(st.lists(st.text(min_size=1, max_size=15), min_size=0, max_size=3)),
        "pending_task_polling_minutes": draw(st.integers(min_value=1, max_value=60)),
        "bootstrap_domains": draw(st.lists(st.text(min_size=3, max_size=30), min_size=1, max_size=3)),
        "connectivity_checks": draw(st.lists(st.text(min_size=3, max_size=30), min_size=0, max_size=3)),
        "locale": draw(st.sampled_from(["es-PE", "es-ES", "en-US"])),
        "telemetry_enabled": draw(st.booleans()),
        "telemetry_interval_seconds": draw(st.integers(min_value=10, max_value=3600)),
        "source": {
            "corporate_queue_name": draw(st.sampled_from(source_options)),
            "search_targets": draw(st.sampled_from(source_options)),
            "pending_task_polling_minutes": draw(st.sampled_from(source_options)),
            "bootstrap_domains": draw(st.sampled_from(source_options)),
            "connectivity_checks": draw(st.sampled_from(source_options)),
            "locale": draw(st.sampled_from(source_options)),
            "telemetry_enabled": draw(st.sampled_from(source_options)),
            "telemetry_interval_seconds": draw(st.sampled_from(source_options)),
        },
        "jitter_window_seconds": draw(st.integers(min_value=5, max_value=300)),
        "config_hash": draw(st.text(min_size=64, max_size=64, alphabet="0123456789abcdef")),
    }

    return ws_id, config


@st.composite
def contingency_state_strategy(draw):
    """
    Genera estado de contingencia forzada aleatorio válido para cachear.

    Produce un dict con la estructura que retorna _fetch_forced_contingency_state.
    """
    ws_id = str(uuid.uuid4())
    org_id = str(uuid.uuid4())
    vlan_id = draw(st.none() | st.just(str(uuid.uuid4())))

    enabled = draw(st.booleans())

    if enabled:
        source = draw(st.sampled_from(["organization", "vlan", "workstation"]))
        source_name = draw(st.text(min_size=1, max_size=30))
        # Generar IP de impresora
        ip_parts = [draw(st.integers(min_value=1, max_value=254)) for _ in range(4)]
        printer_ip = ".".join(str(p) for p in ip_parts)
    else:
        source = "sync"
        source_name = "normal"
        printer_ip = None

    state = {
        "enabled": enabled,
        "source": source,
        "source_name": source_name,
        "printer_ip": printer_ip,
    }

    return ws_id, org_id, vlan_id, state


# === PROPERTY 5: CACHE HIT ELIMINATES DATABASE QUERY ===


class TestCacheHitEliminatesDbQuery:
    """
    Property 5: Cache Hit Eliminates Database Query.

    Para cualquier dato cacheable con TTL válido en Redis, RegistrationCache
    SHALL retornar los datos del cache sin ejecutar queries a PostgreSQL.

    **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
    """

    @given(data=organization_data_strategy())
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_organization_data_cache_hit_no_db_query(self, data):
        """
        Requirement 3.1: Si datos de organización existen en Redis con TTL válido,
        se retornan desde cache sin consultar PostgreSQL.

        Verifica que get_organization_data con datos pre-cargados en Redis
        NO invoca ningún método de la sesión de BD.

        **Validates: Requirements 3.1**
        """
        org_id, org_data = data

        # Crear instancia de fakeredis con datos pre-cargados
        fake_redis = fakeredis.aioredis.FakeRedis()
        cache_key = f"cache:org:{org_id}:data"
        await fake_redis.setex(cache_key, 300, json.dumps(org_data, default=str))

        # Crear cache con el fakeredis
        cache = RegistrationCache(redis=fake_redis, ttl_seconds=300)

        # Mock de la sesión de BD — NO debe ser invocada
        mock_db = MagicMock()

        # Ejecutar get_organization_data
        resultado = await cache.get_organization_data(org_id, mock_db)

        # Propiedad: el resultado es igual a los datos cacheados
        assert resultado == org_data, (
            f"get_organization_data no retornó los datos del cache. "
            f"Esperado: {org_data}, Obtenido: {resultado}"
        )

        # Propiedad: la BD NO fue consultada (cache hit elimina query)
        mock_db.query.assert_not_called()
        mock_db.execute.assert_not_called()

        # Limpiar
        await fake_redis.aclose()

    @given(data=vlan_data_strategy())
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_vlan_data_cache_hit_no_db_query(self, data):
        """
        Requirement 3.2: Si datos de VLAN existen en Redis con TTL válido,
        se retornan desde cache sin consultar PostgreSQL.

        Verifica que get_vlan_data con datos pre-cargados en Redis
        NO invoca ningún método de la sesión de BD.

        **Validates: Requirements 3.2**
        """
        vlan_id, vlan_data = data

        # Crear instancia de fakeredis con datos pre-cargados
        fake_redis = fakeredis.aioredis.FakeRedis()
        cache_key = f"cache:vlan:{vlan_id}:data"
        await fake_redis.setex(cache_key, 300, json.dumps(vlan_data, default=str))

        # Crear cache con el fakeredis
        cache = RegistrationCache(redis=fake_redis, ttl_seconds=300)

        # Mock de la sesión de BD — NO debe ser invocada
        mock_db = MagicMock()

        # Ejecutar get_vlan_data
        resultado = await cache.get_vlan_data(vlan_id, mock_db)

        # Propiedad: el resultado es igual a los datos cacheados
        assert resultado == vlan_data, (
            f"get_vlan_data no retornó los datos del cache. "
            f"Esperado: {vlan_data}, Obtenido: {resultado}"
        )

        # Propiedad: la BD NO fue consultada (cache hit elimina query)
        mock_db.query.assert_not_called()
        mock_db.execute.assert_not_called()

        # Limpiar
        await fake_redis.aclose()

    @given(data=effective_config_strategy())
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_effective_config_cache_hit_no_db_query(self, data):
        """
        Requirement 3.3: Si configuración efectiva existe en Redis con TTL válido,
        se retorna desde cache sin consultar PostgreSQL.

        Verifica que get_effective_config con datos pre-cargados en Redis
        NO invoca ningún método de la sesión de BD.

        **Validates: Requirements 3.3**
        """
        ws_id, config_data = data

        # Crear instancia de fakeredis con datos pre-cargados
        fake_redis = fakeredis.aioredis.FakeRedis()
        cache_key = f"cache:config:{ws_id}:effective"
        await fake_redis.setex(cache_key, 300, json.dumps(config_data, default=str))

        # Crear cache con el fakeredis
        cache = RegistrationCache(redis=fake_redis, ttl_seconds=300)

        # Mock de la sesión de BD — NO debe ser invocada
        mock_db = MagicMock()

        # Ejecutar get_effective_config
        resultado = await cache.get_effective_config(ws_id, mock_db)

        # Propiedad: el resultado es igual a los datos cacheados
        assert resultado == config_data, (
            f"get_effective_config no retornó los datos del cache. "
            f"Esperado: {config_data}, Obtenido: {resultado}"
        )

        # Propiedad: la BD NO fue consultada (cache hit elimina query)
        mock_db.query.assert_not_called()
        mock_db.execute.assert_not_called()

        # Limpiar
        await fake_redis.aclose()

    @given(data=contingency_state_strategy())
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_forced_contingency_state_cache_hit_no_db_query(self, data):
        """
        Requirement 3.4: Si estado de contingencia forzada existe en Redis con TTL válido,
        se retorna desde cache sin consultar PostgreSQL.

        Verifica que get_forced_contingency_state con datos pre-cargados en Redis
        NO invoca ningún método de la sesión de BD.

        **Validates: Requirements 3.4**
        """
        ws_id, org_id, vlan_id, state_data = data

        # Crear instancia de fakeredis con datos pre-cargados
        fake_redis = fakeredis.aioredis.FakeRedis()
        cache_key = f"cache:contingency:{ws_id}:state"
        await fake_redis.setex(cache_key, 300, json.dumps(state_data, default=str))

        # Crear cache con el fakeredis
        cache = RegistrationCache(redis=fake_redis, ttl_seconds=300)

        # Mock de la sesión de BD — NO debe ser invocada
        mock_db = MagicMock()

        # Ejecutar get_forced_contingency_state
        resultado = await cache.get_forced_contingency_state(
            ws_id, org_id, vlan_id, mock_db
        )

        # Propiedad: el resultado es igual a los datos cacheados
        assert resultado == state_data, (
            f"get_forced_contingency_state no retornó los datos del cache. "
            f"Esperado: {state_data}, Obtenido: {resultado}"
        )

        # Propiedad: la BD NO fue consultada (cache hit elimina query)
        mock_db.query.assert_not_called()
        mock_db.execute.assert_not_called()

        # Limpiar
        await fake_redis.aclose()
