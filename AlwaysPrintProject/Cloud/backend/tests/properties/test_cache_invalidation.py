"""
Property tests para invalidación de cache en RegistrationCache.

# Feature: websocket-scaling-redis, Property 7: Cache Invalidation on Modification

Verifica que tras llamar invalidate_organization o invalidate_vlan,
todas las keys de cache relacionadas se eliminan de Redis.

**Validates: Requirements 3.8**
"""

import json
import uuid

import pytest
import fakeredis.aioredis
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.services.registration_cache import RegistrationCache


# === ESTRATEGIAS DE GENERACIÓN ===

# Estrategia para generar UUIDs como strings
uuid_strategy = st.uuids().map(str)


@st.composite
def org_with_keys_strategy(draw):
    """
    Genera un org_id junto con un conjunto de keys de cache relacionadas.

    Produce: (org_id, lista de vlan_ids, lista de workstation_ids)
    para pre-popular Redis con datos de una organización.
    """
    org_id = draw(st.uuids().map(str))
    num_vlans = draw(st.integers(min_value=1, max_value=5))
    num_workstations = draw(st.integers(min_value=1, max_value=5))

    vlan_ids = [draw(st.uuids().map(str)) for _ in range(num_vlans)]
    workstation_ids = [draw(st.uuids().map(str)) for _ in range(num_workstations)]

    return org_id, vlan_ids, workstation_ids


@st.composite
def vlan_invalidation_strategy(draw):
    """
    Genera datos para el escenario de invalidación de VLAN.

    Produce: (vlan_id, org_id, lista de workstation_ids)
    """
    vlan_id = draw(st.uuids().map(str))
    org_id = draw(st.uuids().map(str))
    num_workstations = draw(st.integers(min_value=1, max_value=5))
    workstation_ids = [draw(st.uuids().map(str)) for _ in range(num_workstations)]

    return vlan_id, org_id, workstation_ids


# === HELPERS ===


async def _populate_cache_keys(redis_client, org_id, vlan_ids, workstation_ids):
    """
    Pre-popula Redis con keys de cache típicas de una organización.

    Crea keys de datos de organización, IPs públicas, VLANs,
    configuraciones efectivas y estados de contingencia.

    Args:
        redis_client: Cliente fakeredis.
        org_id: UUID de la organización.
        vlan_ids: Lista de UUIDs de VLANs.
        workstation_ids: Lista de UUIDs de workstations.
    """
    # Keys directas de organización
    await redis_client.setex(
        f"cache:org:{org_id}:data",
        300,
        json.dumps({"id": org_id, "name": "TestOrg"}),
    )
    await redis_client.setex(
        f"cache:org:{org_id}:public_ips",
        300,
        json.dumps([{"ip": "1.2.3.4"}]),
    )

    # Keys de VLANs
    for vlan_id in vlan_ids:
        await redis_client.setex(
            f"cache:vlan:{vlan_id}:data",
            300,
            json.dumps({"id": vlan_id, "org": org_id}),
        )

    # Keys de configuración efectiva por workstation
    for ws_id in workstation_ids:
        await redis_client.setex(
            f"cache:config:{ws_id}:effective",
            300,
            json.dumps({"ws_id": ws_id, "config": "test"}),
        )
        await redis_client.setex(
            f"cache:contingency:{ws_id}:state",
            300,
            json.dumps({"enabled": False, "source": "sync"}),
        )


async def _get_all_cache_keys(redis_client):
    """
    Obtiene todas las keys de cache existentes en Redis.

    Returns:
        Set de strings con las keys que empiezan con 'cache:'.
    """
    keys = set()
    async for key in redis_client.scan_iter(match="cache:*", count=200):
        key_str = key.decode("utf-8") if isinstance(key, bytes) else key
        keys.add(key_str)
    return keys


# === PROPERTY 7: CACHE INVALIDATION ON MODIFICATION ===


class TestCacheInvalidationOnModification:
    """
    Property 7: Cache Invalidation on Modification.

    Para cualquier modificación de datos de organización o VLAN,
    todas las keys de cache relacionadas (datos de org, IPs públicas,
    configuración efectiva, estado de contingencia) SHALL ser eliminadas de Redis.

    **Validates: Requirements 3.8**
    """

    @given(data=org_with_keys_strategy())
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_invalidate_organization_elimina_keys_org_data(self, data):
        """
        Tras invalidate_organization(org_id), las keys cache:org:{org_id}:data
        y cache:org:{org_id}:public_ips se eliminan de Redis.

        **Validates: Requirements 3.8**
        """
        org_id, vlan_ids, workstation_ids = data

        # Crear instancia de fakeredis para aislamiento por test
        redis_client = fakeredis.aioredis.FakeRedis()
        cache = RegistrationCache(redis=redis_client, ttl_seconds=300)

        # Pre-popular keys de cache
        await _populate_cache_keys(redis_client, org_id, vlan_ids, workstation_ids)

        # Verificar que las keys existen antes de invalidar
        org_data_key = f"cache:org:{org_id}:data"
        org_ips_key = f"cache:org:{org_id}:public_ips"
        assert await redis_client.exists(org_data_key) == 1, (
            f"Key {org_data_key} no existía antes de invalidar"
        )
        assert await redis_client.exists(org_ips_key) == 1, (
            f"Key {org_ips_key} no existía antes de invalidar"
        )

        # Ejecutar invalidación
        await cache.invalidate_organization(org_id)

        # Verificar que las keys de organización se eliminaron
        assert await redis_client.exists(org_data_key) == 0, (
            f"Key {org_data_key} NO fue eliminada tras invalidate_organization. "
            f"org_id: {org_id}"
        )
        assert await redis_client.exists(org_ips_key) == 0, (
            f"Key {org_ips_key} NO fue eliminada tras invalidate_organization. "
            f"org_id: {org_id}"
        )

        await redis_client.aclose()

    @given(data=org_with_keys_strategy())
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_invalidate_organization_elimina_keys_config_contingency(self, data):
        """
        Tras invalidate_organization(org_id), las keys cache:config:*:effective
        y cache:contingency:*:state se eliminan de Redis.

        **Validates: Requirements 3.8**
        """
        org_id, vlan_ids, workstation_ids = data

        redis_client = fakeredis.aioredis.FakeRedis()
        cache = RegistrationCache(redis=redis_client, ttl_seconds=300)

        # Pre-popular keys
        await _populate_cache_keys(redis_client, org_id, vlan_ids, workstation_ids)

        # Verificar que existen keys de config/contingency antes de invalidar
        for ws_id in workstation_ids:
            config_key = f"cache:config:{ws_id}:effective"
            contingency_key = f"cache:contingency:{ws_id}:state"
            assert await redis_client.exists(config_key) == 1
            assert await redis_client.exists(contingency_key) == 1

        # Ejecutar invalidación
        await cache.invalidate_organization(org_id)

        # Verificar que las keys de config y contingencia se eliminaron
        for ws_id in workstation_ids:
            config_key = f"cache:config:{ws_id}:effective"
            contingency_key = f"cache:contingency:{ws_id}:state"
            assert await redis_client.exists(config_key) == 0, (
                f"Key {config_key} NO fue eliminada tras invalidate_organization. "
                f"org_id: {org_id}, ws_id: {ws_id}"
            )
            assert await redis_client.exists(contingency_key) == 0, (
                f"Key {contingency_key} NO fue eliminada tras invalidate_organization. "
                f"org_id: {org_id}, ws_id: {ws_id}"
            )

        await redis_client.aclose()

    @given(data=org_with_keys_strategy())
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_invalidate_organization_elimina_keys_vlan(self, data):
        """
        Tras invalidate_organization(org_id), las keys cache:vlan:*:data
        relacionadas se eliminan de Redis (invalidación conservadora).

        **Validates: Requirements 3.8**
        """
        org_id, vlan_ids, workstation_ids = data

        redis_client = fakeredis.aioredis.FakeRedis()
        cache = RegistrationCache(redis=redis_client, ttl_seconds=300)

        # Pre-popular keys
        await _populate_cache_keys(redis_client, org_id, vlan_ids, workstation_ids)

        # Verificar que existen keys de VLAN antes de invalidar
        for vlan_id in vlan_ids:
            vlan_key = f"cache:vlan:{vlan_id}:data"
            assert await redis_client.exists(vlan_key) == 1

        # Ejecutar invalidación
        await cache.invalidate_organization(org_id)

        # Verificar que las keys de VLAN se eliminaron
        for vlan_id in vlan_ids:
            vlan_key = f"cache:vlan:{vlan_id}:data"
            assert await redis_client.exists(vlan_key) == 0, (
                f"Key {vlan_key} NO fue eliminada tras invalidate_organization. "
                f"org_id: {org_id}, vlan_id: {vlan_id}"
            )

        await redis_client.aclose()

    @given(data=org_with_keys_strategy())
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_invalidate_organization_no_deja_keys_residuales(self, data):
        """
        Tras invalidate_organization(org_id), no quedan keys de cache
        (prefijo 'cache:') en Redis.

        Verifica la propiedad de manera exhaustiva: TODAS las keys de cache
        deben ser eliminadas tras la invalidación de organización.

        **Validates: Requirements 3.8**
        """
        org_id, vlan_ids, workstation_ids = data

        redis_client = fakeredis.aioredis.FakeRedis()
        cache = RegistrationCache(redis=redis_client, ttl_seconds=300)

        # Pre-popular keys
        await _populate_cache_keys(redis_client, org_id, vlan_ids, workstation_ids)

        # Ejecutar invalidación
        await cache.invalidate_organization(org_id)

        # Verificar que NO quedan keys de cache
        remaining_keys = await _get_all_cache_keys(redis_client)
        assert len(remaining_keys) == 0, (
            f"Quedan {len(remaining_keys)} keys residuales tras invalidate_organization. "
            f"org_id: {org_id}. Keys: {remaining_keys}"
        )

        await redis_client.aclose()

    @given(data=vlan_invalidation_strategy())
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_invalidate_vlan_elimina_key_vlan_data(self, data):
        """
        Tras invalidate_vlan(vlan_id, org_id), la key cache:vlan:{vlan_id}:data
        se elimina de Redis.

        **Validates: Requirements 3.8**
        """
        vlan_id, org_id, workstation_ids = data

        redis_client = fakeredis.aioredis.FakeRedis()
        cache = RegistrationCache(redis=redis_client, ttl_seconds=300)

        # Pre-popular: key de VLAN + keys de workstations asociadas
        await redis_client.setex(
            f"cache:vlan:{vlan_id}:data",
            300,
            json.dumps({"id": vlan_id, "org": org_id}),
        )
        for ws_id in workstation_ids:
            await redis_client.setex(
                f"cache:config:{ws_id}:effective",
                300,
                json.dumps({"ws_id": ws_id}),
            )
            await redis_client.setex(
                f"cache:contingency:{ws_id}:state",
                300,
                json.dumps({"enabled": False}),
            )

        # Verificar existencia antes de invalidar
        vlan_key = f"cache:vlan:{vlan_id}:data"
        assert await redis_client.exists(vlan_key) == 1

        # Ejecutar invalidación
        await cache.invalidate_vlan(vlan_id, org_id)

        # Verificar que la key de VLAN se eliminó
        assert await redis_client.exists(vlan_key) == 0, (
            f"Key {vlan_key} NO fue eliminada tras invalidate_vlan. "
            f"vlan_id: {vlan_id}, org_id: {org_id}"
        )

        await redis_client.aclose()

    @given(data=vlan_invalidation_strategy())
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_invalidate_vlan_elimina_keys_config_contingency(self, data):
        """
        Tras invalidate_vlan(vlan_id, org_id), las keys cache:config:*:effective
        y cache:contingency:*:state se eliminan de Redis (invalidación conservadora).

        **Validates: Requirements 3.8**
        """
        vlan_id, org_id, workstation_ids = data

        redis_client = fakeredis.aioredis.FakeRedis()
        cache = RegistrationCache(redis=redis_client, ttl_seconds=300)

        # Pre-popular keys
        await redis_client.setex(
            f"cache:vlan:{vlan_id}:data",
            300,
            json.dumps({"id": vlan_id}),
        )
        for ws_id in workstation_ids:
            await redis_client.setex(
                f"cache:config:{ws_id}:effective",
                300,
                json.dumps({"ws_id": ws_id}),
            )
            await redis_client.setex(
                f"cache:contingency:{ws_id}:state",
                300,
                json.dumps({"enabled": False}),
            )

        # Ejecutar invalidación
        await cache.invalidate_vlan(vlan_id, org_id)

        # Verificar que las keys de config y contingencia se eliminaron
        for ws_id in workstation_ids:
            config_key = f"cache:config:{ws_id}:effective"
            contingency_key = f"cache:contingency:{ws_id}:state"
            assert await redis_client.exists(config_key) == 0, (
                f"Key {config_key} NO fue eliminada tras invalidate_vlan. "
                f"vlan_id: {vlan_id}, ws_id: {ws_id}"
            )
            assert await redis_client.exists(contingency_key) == 0, (
                f"Key {contingency_key} NO fue eliminada tras invalidate_vlan. "
                f"vlan_id: {vlan_id}, ws_id: {ws_id}"
            )

        await redis_client.aclose()

    @given(data=vlan_invalidation_strategy())
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_invalidate_vlan_no_deja_keys_residuales(self, data):
        """
        Tras invalidate_vlan(vlan_id, org_id), no quedan keys de cache
        en Redis (excluyendo keys de otras organizaciones no relacionadas).

        **Validates: Requirements 3.8**
        """
        vlan_id, org_id, workstation_ids = data

        redis_client = fakeredis.aioredis.FakeRedis()
        cache = RegistrationCache(redis=redis_client, ttl_seconds=300)

        # Pre-popular solo keys de esta VLAN y workstations asociadas
        await redis_client.setex(
            f"cache:vlan:{vlan_id}:data",
            300,
            json.dumps({"id": vlan_id}),
        )
        for ws_id in workstation_ids:
            await redis_client.setex(
                f"cache:config:{ws_id}:effective",
                300,
                json.dumps({"ws_id": ws_id}),
            )
            await redis_client.setex(
                f"cache:contingency:{ws_id}:state",
                300,
                json.dumps({"enabled": False}),
            )

        # Ejecutar invalidación
        await cache.invalidate_vlan(vlan_id, org_id)

        # Verificar que NO quedan keys de cache
        remaining_keys = await _get_all_cache_keys(redis_client)
        assert len(remaining_keys) == 0, (
            f"Quedan {len(remaining_keys)} keys residuales tras invalidate_vlan. "
            f"vlan_id: {vlan_id}, org_id: {org_id}. Keys: {remaining_keys}"
        )

        await redis_client.aclose()

    @given(
        org_id=uuid_strategy,
        vlan_id=uuid_strategy,
    )
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_invalidate_sin_redis_no_genera_error(self, org_id, vlan_id):
        """
        Cuando Redis no está disponible (redis=None), las funciones de invalidación
        completan sin error (no-op graceful).

        **Validates: Requirements 3.8**
        """
        # Cache sin Redis — debe ser un no-op sin excepciones
        cache = RegistrationCache(redis=None, ttl_seconds=300)

        # No debe lanzar excepciones
        await cache.invalidate_organization(org_id)
        await cache.invalidate_vlan(vlan_id, org_id)
