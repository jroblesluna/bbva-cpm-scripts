"""
Property test para cache miss round-trip en RegistrationCache.

# Feature: websocket-scaling-redis, Property 6: Cache Miss Round-Trip

Verifica que tras un cache miss:
1. Se consulta la base de datos (PostgreSQL)
2. Se almacena el resultado en Redis con el TTL configurado
3. La siguiente llamada para los mismos datos es un cache hit (sin query a BD)

**Validates: Requirements 3.5**
"""

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

import fakeredis.aioredis

from app.services.registration_cache import RegistrationCache


# === ESTRATEGIAS DE GENERACIÓN ===


@st.composite
def organization_data_strategy(draw):
    """
    Genera datos aleatorios de organización para simular respuestas de BD.

    Produce un dict con la estructura que retorna _fetch_organization_data.
    """
    org_id = str(uuid.uuid4())
    name = draw(st.text(min_size=1, max_size=50, alphabet=st.characters(
        whitelist_categories=("L", "N", "Z"),
        whitelist_characters="_-"
    )))
    # Asegurar que el nombre no está vacío después de strip
    assume(name.strip() != "")

    is_active = draw(st.booleans())
    timezone = draw(st.sampled_from(["America/Lima", "America/New_York", "Europe/Madrid", "UTC"]))
    language = draw(st.sampled_from(["es", "en", "pt"]))
    auto_update_enabled = draw(st.booleans())
    target_version = draw(st.from_regex(r"[0-9]+\.[0-9]+\.[0-9]+", fullmatch=True))
    auto_reregister_enabled = draw(st.booleans())
    forced_contingency = draw(st.booleans())
    offline_timeout_minutes = draw(st.integers(min_value=1, max_value=1440))
    jitter_window_seconds = draw(st.integers(min_value=5, max_value=300))

    # Generar entre 0 y 3 IPs públicas
    num_ips = draw(st.integers(min_value=0, max_value=3))
    public_ips = []
    for _ in range(num_ips):
        public_ips.append({
            "id": str(uuid.uuid4()),
            "ip_address": draw(st.from_regex(
                r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}",
                fullmatch=True
            )),
            "description": draw(st.text(min_size=0, max_size=20, alphabet=st.characters(
                whitelist_categories=("L", "N", "Z")
            ))),
        })

    return {
        "org_id": org_id,
        "data": {
            "id": org_id,
            "name": name,
            "is_active": is_active,
            "timezone": timezone,
            "language": language,
            "auto_update_enabled": auto_update_enabled,
            "target_version": target_version,
            "auto_reregister_enabled": auto_reregister_enabled,
            "forced_contingency": forced_contingency,
            "offline_timeout_minutes": offline_timeout_minutes,
            "jitter_window_seconds": jitter_window_seconds,
            "public_ips": public_ips,
        },
    }


@st.composite
def vlan_data_strategy(draw):
    """
    Genera datos aleatorios de VLAN para simular respuestas de BD.
    """
    vlan_id = str(uuid.uuid4())
    org_id = str(uuid.uuid4())
    name = draw(st.text(min_size=1, max_size=30, alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="_-"
    )))
    assume(name.strip() != "")

    description = draw(st.text(min_size=0, max_size=50, alphabet=st.characters(
        whitelist_categories=("L", "N", "Z")
    )))
    forced_contingency = draw(st.booleans())
    contingency_inherited = draw(st.booleans())

    return {
        "vlan_id": vlan_id,
        "org_id": org_id,
        "data": {
            "id": vlan_id,
            "organization_id": org_id,
            "name": name,
            "description": description,
            "cidr_ranges": [draw(st.from_regex(
                r"10\.[0-9]{1,3}\.[0-9]{1,3}\.0/24",
                fullmatch=True
            ))],
            "forced_contingency": forced_contingency,
            "contingency_inherited": contingency_inherited,
            "default_device_id": None,
            "vlan_metadata": None,
        },
    }


# === PROPERTY 6: CACHE MISS ROUND-TRIP ===


@pytest.mark.asyncio
class TestCacheMissRoundTrip:
    """
    Property 6: Cache Miss Round-Trip.

    Para cualquier cache miss (dato no presente en Redis o TTL expirado),
    RegistrationCache SHALL consultar PostgreSQL, almacenar el resultado en
    Redis con el TTL configurado, y retornar los datos. Tras esta operación,
    una solicitud subsecuente inmediata para los mismos datos SHALL ser
    servida desde cache (Property 5).

    **Validates: Requirements 3.5**
    """

    @given(org_payload=organization_data_strategy())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_cache_miss_fetches_from_db_stores_in_redis_then_cache_hit(
        self, org_payload: dict
    ):
        """
        Tras un cache miss de organization_data:
        - Se consulta la BD (mock)
        - Se almacena el resultado en Redis
        - La siguiente llamada es un cache hit sin tocar la BD

        **Validates: Requirements 3.5**
        """
        # Preparar: Redis vacío (fakeredis), mock de BD que retorna datos
        fake_redis = fakeredis.aioredis.FakeRedis()
        ttl = 300
        cache = RegistrationCache(redis=fake_redis, ttl_seconds=ttl)

        org_id = org_payload["org_id"]
        expected_data = org_payload["data"]

        # Mock de la sesión de BD
        mock_db = MagicMock()

        # Parchear el método _fetch_organization_data para simular la BD
        with patch.object(
            cache, "_fetch_organization_data", return_value=expected_data
        ) as mock_fetch:
            # Primera llamada: cache miss → debe consultar BD
            result_first = await cache.get_organization_data(org_id, mock_db)

            # Verificar que se consultó la BD
            assert mock_fetch.call_count == 1, (
                f"Cache miss no consultó la BD. "
                f"Llamadas a _fetch_organization_data: {mock_fetch.call_count}"
            )

            # Verificar que el resultado es correcto
            assert result_first == expected_data, (
                f"El resultado del cache miss no coincide con los datos de BD. "
                f"Esperado keys: {set(expected_data.keys())}, "
                f"Obtenido keys: {set(result_first.keys()) if result_first else 'None'}"
            )

            # Verificar que se almacenó en Redis
            cache_key = f"cache:org:{org_id}:data"
            stored = await fake_redis.get(cache_key)
            assert stored is not None, (
                f"Tras cache miss, el dato NO se almacenó en Redis. "
                f"Key: {cache_key}"
            )

            # Verificar que lo almacenado coincide con lo retornado
            stored_data = json.loads(stored)
            assert stored_data == expected_data, (
                f"Los datos almacenados en Redis no coinciden con los de BD. "
                f"Diferencias detectadas en el contenido."
            )

            # Segunda llamada: cache hit → NO debe consultar BD
            result_second = await cache.get_organization_data(org_id, mock_db)

            # Verificar que NO se volvió a consultar la BD
            assert mock_fetch.call_count == 1, (
                f"Cache hit volvió a consultar la BD. "
                f"Llamadas a _fetch_organization_data: {mock_fetch.call_count} (esperado: 1)"
            )

            # Verificar que el resultado del cache hit es idéntico
            assert result_second == expected_data, (
                f"El resultado del cache hit difiere del cache miss. "
                f"Esperado: {expected_data}, Obtenido: {result_second}"
            )

        # Limpieza
        await fake_redis.aclose()

    @given(vlan_payload=vlan_data_strategy())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_vlan_cache_miss_round_trip(self, vlan_payload: dict):
        """
        Tras un cache miss de vlan_data:
        - Se consulta la BD
        - Se almacena en Redis
        - La siguiente llamada es cache hit

        **Validates: Requirements 3.5**
        """
        fake_redis = fakeredis.aioredis.FakeRedis()
        ttl = 300
        cache = RegistrationCache(redis=fake_redis, ttl_seconds=ttl)

        vlan_id = vlan_payload["vlan_id"]
        expected_data = vlan_payload["data"]

        mock_db = MagicMock()

        with patch.object(
            cache, "_fetch_vlan_data", return_value=expected_data
        ) as mock_fetch:
            # Primera llamada: cache miss
            result_first = await cache.get_vlan_data(vlan_id, mock_db)

            # Verificar consulta a BD
            assert mock_fetch.call_count == 1, (
                f"Cache miss de VLAN no consultó la BD. "
                f"Llamadas: {mock_fetch.call_count}"
            )

            # Verificar resultado correcto
            assert result_first == expected_data, (
                f"Resultado de cache miss de VLAN incorrecto."
            )

            # Verificar almacenamiento en Redis
            cache_key = f"cache:vlan:{vlan_id}:data"
            stored = await fake_redis.get(cache_key)
            assert stored is not None, (
                f"Dato de VLAN no almacenado en Redis tras cache miss. "
                f"Key: {cache_key}"
            )

            # Verificar datos almacenados
            stored_data = json.loads(stored)
            assert stored_data == expected_data, (
                f"Datos de VLAN en Redis no coinciden con BD."
            )

            # Segunda llamada: cache hit
            result_second = await cache.get_vlan_data(vlan_id, mock_db)

            # Verificar que NO se consultó BD de nuevo
            assert mock_fetch.call_count == 1, (
                f"Cache hit de VLAN volvió a consultar BD. "
                f"Llamadas: {mock_fetch.call_count} (esperado: 1)"
            )

            # Verificar resultado idéntico
            assert result_second == expected_data, (
                f"Resultado de cache hit de VLAN difiere del original."
            )

        await fake_redis.aclose()

    @given(org_payload=organization_data_strategy())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_stored_data_matches_db_response_exactly(self, org_payload: dict):
        """
        Los datos almacenados en Redis tras un cache miss son exactamente
        los mismos que retornó la consulta a BD (serialización correcta).

        **Validates: Requirements 3.5**
        """
        fake_redis = fakeredis.aioredis.FakeRedis()
        cache = RegistrationCache(redis=fake_redis, ttl_seconds=300)

        org_id = org_payload["org_id"]
        expected_data = org_payload["data"]

        mock_db = MagicMock()

        with patch.object(
            cache, "_fetch_organization_data", return_value=expected_data
        ):
            # Provocar cache miss para almacenar en Redis
            await cache.get_organization_data(org_id, mock_db)

            # Leer directamente de Redis y comparar
            cache_key = f"cache:org:{org_id}:data"
            raw_stored = await fake_redis.get(cache_key)
            stored_data = json.loads(raw_stored)

            # Propiedad: los datos en Redis son idénticos a los de BD
            assert stored_data == expected_data, (
                f"Datos en Redis difieren de los datos originales de BD. "
                f"Esto indica un problema de serialización/deserialización. "
                f"Tipo expected: {type(expected_data)}, Tipo stored: {type(stored_data)}"
            )

        await fake_redis.aclose()

    @given(org_payload=organization_data_strategy())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_redis_ttl_is_set_after_cache_miss(self, org_payload: dict):
        """
        Tras un cache miss, la key almacenada en Redis tiene un TTL activo
        (no es persistente indefinidamente).

        **Validates: Requirements 3.5**
        """
        fake_redis = fakeredis.aioredis.FakeRedis()
        configured_ttl = 300
        cache = RegistrationCache(redis=fake_redis, ttl_seconds=configured_ttl)

        org_id = org_payload["org_id"]
        expected_data = org_payload["data"]

        mock_db = MagicMock()

        with patch.object(
            cache, "_fetch_organization_data", return_value=expected_data
        ):
            await cache.get_organization_data(org_id, mock_db)

            # Verificar que el TTL está configurado
            cache_key = f"cache:org:{org_id}:data"
            remaining_ttl = await fake_redis.ttl(cache_key)

            # TTL debe ser positivo y no mayor al configurado
            assert remaining_ttl > 0, (
                f"La key en Redis no tiene TTL activo. "
                f"TTL retornado: {remaining_ttl} (esperado: >0)"
            )
            assert remaining_ttl <= configured_ttl, (
                f"El TTL en Redis excede el configurado. "
                f"TTL actual: {remaining_ttl}, Configurado: {configured_ttl}"
            )

        await fake_redis.aclose()
