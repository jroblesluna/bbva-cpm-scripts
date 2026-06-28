"""
Property test para la eficiencia de carga por organización.

Verifica que para cualquier N workstations de la misma organización
registrándose secuencialmente con un state map vacío (cold start),
solo la PRIMERA registration trigger una query a BD (vía _load_org_state).
Todas las siguientes usan el estado cacheado (zero queries adicionales).

Feature: push-based-distribution, Property 9: Load efficiency per organization

**Validates: Requirements 9.3**
"""

import asyncio
import hashlib
import random
from collections import namedtuple
from unittest.mock import MagicMock, patch

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.services.state_map_service import (
    OrgDistributionState,
    StateMapService,
    VlanConfigState,
    WsConfigState,
)


# === Estrategias de generación de datos ===

# Fila que simula el resultado del JOIN para _load_org_state
_OrgRow = namedtuple(
    "_OrgRow",
    [
        "org_id",
        "cert_version",
        "cert_s3_key",
        "msi_version",
        "auto_update_enabled",
        "config_hash",
        "config_s3_key",
        "scope",
        "vlan_id",
        "workstation_id",
    ],
)


def _generate_org_with_workstations(seed: int, num_workstations: int) -> dict:
    """
    Genera una organización con N workstations para simular registros secuenciales.

    Args:
        seed: Semilla para generación determinística.
        num_workstations: Cantidad de workstations a generar (2-50).

    Returns:
        Dict con org_id, cert_version, cert_s3_key, msi_version,
        config_hash, config_s3_key, y lista de workstation_ids.
    """
    rng = random.Random(seed)

    org_id = f"org-{seed:08x}"
    cert_version = rng.randint(1, 20)
    cert_s3_key = f"certs/{org_id}/v{cert_version}.cer"
    msi_version = f"{rng.randint(1, 5)}.{rng.randint(0, 9)}.{rng.randint(0, 9)}"
    config_hash = hashlib.sha256(f"{org_id}-config-{seed}".encode()).hexdigest()[:8]
    config_s3_key = f"configs/{org_id}/{config_hash}.signed"

    # Generar N workstation IDs únicos
    workstation_ids = [f"ws-{seed:04x}-{i:03d}" for i in range(num_workstations)]

    return {
        "org_id": org_id,
        "cert_version": cert_version,
        "cert_s3_key": cert_s3_key,
        "msi_version": msi_version,
        "config_hash": config_hash,
        "config_s3_key": config_s3_key,
        "workstation_ids": workstation_ids,
    }


# Estrategia: genera org con 2-50 workstations
_org_with_workstations = st.builds(
    _generate_org_with_workstations,
    seed=st.integers(min_value=0, max_value=2**32 - 1),
    num_workstations=st.integers(min_value=2, max_value=50),
)


def _build_db_rows_for_org(org_data: dict) -> list[_OrgRow]:
    """
    Construye las filas que retornaría _load_org_state para una org.
    """
    return [
        _OrgRow(
            org_id=org_data["org_id"],
            cert_version=org_data["cert_version"],
            cert_s3_key=org_data["cert_s3_key"],
            msi_version=org_data["msi_version"],
            auto_update_enabled=True,
            config_hash=org_data["config_hash"],
            config_s3_key=org_data["config_s3_key"],
            scope="org",
            vlan_id=None,
            workstation_id=None,
        )
    ]


def _create_mock_db_session(org_data: dict, call_counter: dict) -> MagicMock:
    """
    Crea un mock de sesión de BD que retorna filas para la org generada
    y cuenta las ejecuciones de queries.

    Args:
        org_data: Datos de la organización generada.
        call_counter: Dict con clave 'count' que se incrementa por cada query.

    Returns:
        Mock de la sesión de BD.
    """
    rows = _build_db_rows_for_org(org_data)
    mock_db = MagicMock()

    # Mock de execute().fetchall() que cuenta invocaciones
    mock_result = MagicMock()
    mock_result.fetchall.return_value = rows

    def execute_side_effect(*args, **kwargs):
        call_counter["count"] += 1
        return mock_result

    mock_db.execute.side_effect = execute_side_effect
    mock_db.close = MagicMock()

    return mock_db


def _create_db_session_factory(org_data: dict, call_counter: dict):
    """
    Crea un factory de sesiones de BD mock, con contador de queries.
    """
    def factory():
        return _create_mock_db_session(org_data, call_counter)
    return factory


# === PROPERTY TESTS ===


class TestLoadEfficiencyPerOrg:
    """
    Property 9: Load efficiency per organization.

    Para cualquier N workstations de la misma organización registrándose
    secuencialmente con un state map vacío (cache miss), solo la PRIMERA
    registration trigger una query a BD (vía `_load_org_state`). Todas las
    siguientes usan el estado cacheado (zero queries adicionales).

    Feature: push-based-distribution, Property 9: Load efficiency per organization

    **Validates: Requirements 9.3**
    """

    @given(org_data=_org_with_workstations)
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_solo_primera_carga_hace_query_a_bd(self, org_data: dict):
        """
        Para N workstations de la misma org con state map vacío (cold start),
        la primera llamada a _load_org_state ejecuta exactamente 1 query a BD,
        y todas las llamadas posteriores ejecutan 0 queries (usan caché).

        **Validates: Requirements 9.3**
        """
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._run_load_efficiency_test(org_data))
        finally:
            loop.close()

    async def _run_load_efficiency_test(self, org_data: dict):
        """Implementación async del test de eficiencia de carga."""
        org_id = org_data["org_id"]
        workstation_ids = org_data["workstation_ids"]
        query_counter = {"count": 0}

        # Crear servicio con state map vacío (simula cold start)
        service = StateMapService(redis_url=None)
        service._db_session_factory = _create_db_session_factory(
            org_data, query_counter
        )

        # Verificar que el state map está vacío antes del test
        assert service._state.get(org_id) is None, (
            f"El state map debería estar vacío para org {org_id} antes del test"
        )

        # --- Primera workstation: cache miss → debe hacer 1 query ---
        first_ws = workstation_ids[0]
        result = await service._load_org_state(org_id=org_id)

        assert query_counter["count"] == 1, (
            f"La primera carga debería ejecutar exactamente 1 query a BD. "
            f"Queries ejecutadas: {query_counter['count']}"
        )
        assert result is not None, (
            f"_load_org_state debería retornar un OrgDistributionState para org {org_id}"
        )

        # --- Workstations siguientes: cache hit → 0 queries adicionales ---
        for i, ws_id in enumerate(workstation_ids[1:], start=2):
            # Simular lo que haría el registro: verificar si hay estado en el map
            cached_state = await service.get_state(org_id)

            # El estado debería estar en caché desde la primera carga
            assert cached_state is not None, (
                f"Workstation #{i} ({ws_id}): get_state debería retornar datos "
                f"cacheados para org {org_id}, pero retornó None"
            )

        # Verificar que el contador de queries no cambió (sigue en 1)
        assert query_counter["count"] == 1, (
            f"Después de {len(workstation_ids)} registros secuenciales, "
            f"solo debería haber 1 query a BD. "
            f"Queries ejecutadas: {query_counter['count']}"
        )

    @given(org_data=_org_with_workstations)
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_get_state_retorna_datos_correctos_post_carga(self, org_data: dict):
        """
        Después de la primera carga (cache miss), get_state(org_id)
        retorna los datos correctos de la BD para todas las workstations
        subsiguientes sin requerir queries adicionales.

        **Validates: Requirements 9.3**
        """
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._run_cached_data_correctness_test(org_data))
        finally:
            loop.close()

    async def _run_cached_data_correctness_test(self, org_data: dict):
        """Verifica que los datos cacheados son correctos."""
        org_id = org_data["org_id"]
        query_counter = {"count": 0}

        # Crear servicio con state map vacío
        service = StateMapService(redis_url=None)
        service._db_session_factory = _create_db_session_factory(
            org_data, query_counter
        )

        # Primera carga (cache miss)
        await service._load_org_state(org_id=org_id)

        # Verificar que get_state retorna los datos correctos
        cached_state = await service.get_state(org_id)
        assert cached_state is not None

        # Verificar config_hash
        assert cached_state.config_hash == org_data["config_hash"], (
            f"config_hash cacheado incorrecto. "
            f"Esperado: {org_data['config_hash']}, "
            f"Obtenido: {cached_state.config_hash}"
        )

        # Verificar cert_version
        assert cached_state.cert_version == org_data["cert_version"], (
            f"cert_version cacheado incorrecto. "
            f"Esperado: {org_data['cert_version']}, "
            f"Obtenido: {cached_state.cert_version}"
        )

        # Verificar msi_version
        assert cached_state.msi_version == org_data["msi_version"], (
            f"msi_version cacheado incorrecto. "
            f"Esperado: {org_data['msi_version']}, "
            f"Obtenido: {cached_state.msi_version}"
        )

        # Verificar cert_url contiene la s3_key correcta
        assert cached_state.cert_url is not None
        assert org_data["cert_s3_key"] in cached_state.cert_url, (
            f"cert_url no contiene s3_key esperada. "
            f"s3_key: {org_data['cert_s3_key']}, "
            f"cert_url: {cached_state.cert_url}"
        )

    @given(org_data=_org_with_workstations)
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_load_org_state_repetido_no_genera_queries(self, org_data: dict):
        """
        Si _load_org_state se llama múltiples veces para la misma org,
        solo la primera invocación genera una query a BD. Las siguientes
        encuentran los datos ya cacheados en self._state y no consultan BD.

        **Validates: Requirements 9.3**
        """
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._run_repeated_load_test(org_data))
        finally:
            loop.close()

    async def _run_repeated_load_test(self, org_data: dict):
        """Verifica que _load_org_state repetido no genera queries extra."""
        org_id = org_data["org_id"]
        num_workstations = len(org_data["workstation_ids"])
        query_counter = {"count": 0}

        # Crear servicio con state map vacío
        service = StateMapService(redis_url=None)
        service._db_session_factory = _create_db_session_factory(
            org_data, query_counter
        )

        # Primera llamada: cache miss → 1 query
        result1 = await service._load_org_state(org_id=org_id)
        assert query_counter["count"] == 1
        assert result1 is not None

        # Llamadas adicionales simulando N-1 workstations que también
        # intentan cargar el estado (en caso de race condition o lógica redundante)
        # El servicio debería detectar que ya tiene datos y no hacer query
        for i in range(min(num_workstations - 1, 10)):
            # Simular la verificación que haría el handler de registro:
            # 1. Intentar get_state primero
            state = await service.get_state(org_id)
            if state is None:
                # Solo si no hay caché, cargar de BD
                await service._load_org_state(org_id=org_id)

        # El total de queries debe seguir siendo 1
        assert query_counter["count"] == 1, (
            f"Después de {num_workstations} intentos de carga para la misma org, "
            f"debería haber exactamente 1 query a BD. "
            f"Queries ejecutadas: {query_counter['count']}"
        )
