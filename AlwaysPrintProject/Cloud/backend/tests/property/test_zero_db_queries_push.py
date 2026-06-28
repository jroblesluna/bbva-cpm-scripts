"""
Property test para verificar zero queries a BD en la ruta de distribución push.

Verifica que para cualquier número de workstations conectadas (1-100) y cualquier
operación push (push_config_change, push_msi_update, push_cert_rotation), el
backend NO ejecuta queries a la base de datos. También verifica que
resolve_workstation_state() con el state map poblado no toca la BD.

Feature: push-based-distribution, Property 8: Zero database queries in distribution hot path

**Validates: Requirements 9.1, 9.2**
"""

import asyncio
import random
import uuid
from unittest.mock import MagicMock

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.services.push_distribution_service import PushDistributionService
from app.services.state_map_service import (
    OrgDistributionState,
    StateMapService,
    VlanConfigState,
    WsConfigState,
)


# === Estrategias de generación de datos ===


def _generate_scenario(seed: int, num_workstations: int) -> dict:
    """
    Genera un escenario aleatorio de distribución push con N workstations.

    Produce un org_id, una lista de workstation_ids conectadas, un scope
    de push, y los datos necesarios para cada tipo de operación push.
    """
    rng = random.Random(seed)

    org_id = f"org-{uuid.UUID(int=seed % (2**128))}"
    workstation_ids = [f"ws-{uuid.UUID(int=(seed + i) % (2**128))}" for i in range(num_workstations)]

    # Asignar VLANs a las workstations (algunas pueden compartir VLAN)
    num_vlans = rng.randint(1, max(1, num_workstations // 3))
    vlan_ids = [f"vlan-{rng.randint(1000, 9999)}" for _ in range(num_vlans)]
    ws_vlan_map = {ws_id: rng.choice(vlan_ids) for ws_id in workstation_ids}

    # Datos de config push
    config_hash = uuid.UUID(int=rng.getrandbits(128)).hex[:8]
    config_s3_url = f"https://bucket.s3.us-east-1.amazonaws.com/configs/{org_id}/{config_hash}.signed"

    # Scope aleatorio
    scope = rng.choice(["org", "vlan", "workstation"])
    scope_id = None
    if scope == "vlan":
        scope_id = rng.choice(vlan_ids)
    elif scope == "workstation":
        scope_id = rng.choice(workstation_ids)

    # Datos de MSI push
    msi_version = f"{rng.randint(1, 5)}.{rng.randint(0, 9)}.{rng.randint(0, 9)}"
    msi_url = f"https://bucket.s3.us-east-1.amazonaws.com/versions/{msi_version}/AlwaysPrint.msi?presigned"
    msi_file_size = rng.randint(5_000_000, 30_000_000)

    # Datos de cert push
    cert_version = rng.randint(1, 100)
    cert_url = f"https://bucket.s3.us-east-1.amazonaws.com/certs/{org_id}/v{cert_version}.cer"

    # Datos del state map para enrichment (resolve_workstation_state)
    state_map_data = OrgDistributionState(
        config_hash=config_hash,
        config_s3_url=config_s3_url,
        cert_version=cert_version,
        cert_url=cert_url,
        msi_version=msi_version,
        msi_url=msi_url,
        msi_url_expires_at=9999999999.0,  # No expira durante el test
        vlan_configs={
            vlan_id: VlanConfigState(
                config_hash=uuid.UUID(int=rng.getrandbits(128)).hex[:8],
                config_s3_url=f"https://bucket.s3.us-east-1.amazonaws.com/configs/{org_id}/vlan-{vlan_id}.signed",
            )
            for vlan_id in vlan_ids
        },
        ws_configs={},
    )

    return {
        "org_id": org_id,
        "workstation_ids": workstation_ids,
        "ws_vlan_map": ws_vlan_map,
        "config_hash": config_hash,
        "config_s3_url": config_s3_url,
        "scope": scope,
        "scope_id": scope_id,
        "msi_version": msi_version,
        "msi_url": msi_url,
        "msi_file_size": msi_file_size,
        "cert_version": cert_version,
        "cert_url": cert_url,
        "state_map_data": state_map_data,
    }


# Estrategia Hypothesis: genera escenarios con seed + num_workstations
_push_scenario = st.builds(
    _generate_scenario,
    seed=st.integers(min_value=0, max_value=2**32 - 1),
    num_workstations=st.integers(min_value=1, max_value=100),
)


class _FakeConnectionManager:
    """
    Mock ligero del ConnectionManager para property tests.

    Evita usar AsyncMock que puede causar problemas con asyncio.run()
    en invocaciones repetidas de Hypothesis. Implementa solo la interfaz
    necesaria para PushDistributionService.
    """

    def __init__(self, org_id: str, workstation_ids: list[str], ws_vlan_map: dict[str, str]):
        self.org_ids = {ws_id: org_id for ws_id in workstation_ids}
        self.workstation_connections = {ws_id: True for ws_id in workstation_ids}
        self._ws_vlan_ids = ws_vlan_map
        self.send_count = 0

    def is_workstation_online(self, ws_id: str) -> bool:
        return ws_id in self.workstation_connections

    async def send_to_workstation(self, ws_id: str, message: dict) -> bool:
        self.send_count += 1
        return True


def _build_mock_connection_manager(
    org_id: str, workstation_ids: list[str], ws_vlan_map: dict[str, str]
) -> "_FakeConnectionManager":
    """
    Construye un fake ConnectionManager con N workstations conectadas.

    Implementa la interfaz mínima usada por PushDistributionService:
    - org_ids: {ws_id: org_id} para todas las workstations
    - workstation_connections: {ws_id: True} para indicar online
    - _ws_vlan_ids: {ws_id: vlan_id} para filtrado por VLAN
    - is_workstation_online(ws_id): True si ws_id está en workstation_connections
    - send_to_workstation(ws_id, msg): async, siempre retorna True
    """
    return _FakeConnectionManager(org_id, workstation_ids, ws_vlan_map)


def _build_db_query_counter() -> tuple[MagicMock, dict]:
    """
    Construye un mock de db_session_factory que cuenta queries ejecutadas.

    Retorna:
    - El mock de la factory (callable que retorna un mock de session)
    - Un dict con la key "count" para acceder al contador de queries
    """
    counter = {"count": 0}

    mock_session = MagicMock()

    def count_execute(*args, **kwargs):
        counter["count"] += 1
        # Retorna un mock de result con fetchall vacío
        result = MagicMock()
        result.fetchall.return_value = []
        return result

    mock_session.execute = MagicMock(side_effect=count_execute)
    mock_session.query = MagicMock(side_effect=lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("Se invocó session.query() — se hizo una query a BD en el hot path")
    ))
    mock_session.close = MagicMock()

    def factory():
        counter["count"] += 1  # Crear sesión ya indica intención de query
        return mock_session

    mock_factory = MagicMock(side_effect=factory)

    return mock_factory, counter


# === Funciones async ejecutadas via asyncio.run() ===


async def _run_push_config_test(scenario: dict) -> None:
    """Ejecuta push_config_change y verifica 0 queries a BD."""
    cm = _build_mock_connection_manager(
        scenario["org_id"],
        scenario["workstation_ids"],
        scenario["ws_vlan_map"],
    )
    db_factory, counter = _build_db_query_counter()

    state_map = StateMapService(redis_url=None)
    state_map._db_session_factory = db_factory
    push_service = PushDistributionService(cm, state_map)

    await push_service.push_config_change(
        org_id=scenario["org_id"],
        config_hash=scenario["config_hash"],
        download_url=scenario["config_s3_url"],
        scope=scenario["scope"],
        scope_id=scenario["scope_id"],
    )

    assert counter["count"] == 0, (
        f"push_config_change ejecutó {counter['count']} queries/sesiones a BD. "
        f"Esperado: 0. Escenario: {len(scenario['workstation_ids'])} workstations, "
        f"scope={scenario['scope']}, scope_id={scenario['scope_id']}"
    )


async def _run_push_msi_test(scenario: dict) -> None:
    """Ejecuta push_msi_update y verifica 0 queries a BD."""
    cm = _build_mock_connection_manager(
        scenario["org_id"],
        scenario["workstation_ids"],
        scenario["ws_vlan_map"],
    )
    db_factory, counter = _build_db_query_counter()

    state_map = StateMapService(redis_url=None)
    state_map._db_session_factory = db_factory
    push_service = PushDistributionService(cm, state_map)

    await push_service.push_msi_update(
        org_id=scenario["org_id"],
        msi_version=scenario["msi_version"],
        download_url=scenario["msi_url"],
        file_size=scenario["msi_file_size"],
    )

    assert counter["count"] == 0, (
        f"push_msi_update ejecutó {counter['count']} queries/sesiones a BD. "
        f"Esperado: 0. Escenario: {len(scenario['workstation_ids'])} workstations, "
        f"msi_version={scenario['msi_version']}"
    )


async def _run_push_cert_test(scenario: dict) -> None:
    """Ejecuta push_cert_rotation y verifica 0 queries a BD."""
    cm = _build_mock_connection_manager(
        scenario["org_id"],
        scenario["workstation_ids"],
        scenario["ws_vlan_map"],
    )
    db_factory, counter = _build_db_query_counter()

    state_map = StateMapService(redis_url=None)
    state_map._db_session_factory = db_factory
    push_service = PushDistributionService(cm, state_map)

    await push_service.push_cert_rotation(
        org_id=scenario["org_id"],
        cert_version=scenario["cert_version"],
        cert_url=scenario["cert_url"],
    )

    assert counter["count"] == 0, (
        f"push_cert_rotation ejecutó {counter['count']} queries/sesiones a BD. "
        f"Esperado: 0. Escenario: {len(scenario['workstation_ids'])} workstations, "
        f"cert_version={scenario['cert_version']}"
    )


async def _run_resolve_state_test(scenario: dict) -> None:
    """Ejecuta resolve_workstation_state con state map poblado y verifica 0 queries a BD."""
    db_factory, counter = _build_db_query_counter()

    state_map = StateMapService(redis_url=None)
    state_map._db_session_factory = db_factory
    state_map._state[scenario["org_id"]] = scenario["state_map_data"]

    ws_id = scenario["workstation_ids"][0]
    vlan_id = scenario["ws_vlan_map"].get(ws_id)

    result = await state_map.resolve_workstation_state(
        org_id=scenario["org_id"],
        vlan_id=vlan_id,
        ws_id=ws_id,
    )

    assert counter["count"] == 0, (
        f"resolve_workstation_state ejecutó {counter['count']} queries/sesiones a BD "
        f"con state map poblado. Esperado: 0. "
        f"org_id={scenario['org_id']}, ws_id={ws_id}, vlan_id={vlan_id}"
    )

    assert result["config_hash"] is not None or result["cert_version"] > 0, (
        f"resolve_workstation_state retornó estado vacío con state map poblado. "
        f"result={result}"
    )


async def _run_all_push_operations_test(scenario: dict) -> None:
    """Ejecuta las 3 operaciones push + enrichment y verifica 0 queries a BD total."""
    cm = _build_mock_connection_manager(
        scenario["org_id"],
        scenario["workstation_ids"],
        scenario["ws_vlan_map"],
    )
    db_factory, counter = _build_db_query_counter()

    state_map = StateMapService(redis_url=None)
    state_map._db_session_factory = db_factory
    state_map._state[scenario["org_id"]] = scenario["state_map_data"]

    push_service = PushDistributionService(cm, state_map)

    # 1. Push config
    await push_service.push_config_change(
        org_id=scenario["org_id"],
        config_hash=scenario["config_hash"],
        download_url=scenario["config_s3_url"],
        scope=scenario["scope"],
        scope_id=scenario["scope_id"],
    )

    # 2. Push MSI
    await push_service.push_msi_update(
        org_id=scenario["org_id"],
        msi_version=scenario["msi_version"],
        download_url=scenario["msi_url"],
        file_size=scenario["msi_file_size"],
    )

    # 3. Push cert
    await push_service.push_cert_rotation(
        org_id=scenario["org_id"],
        cert_version=scenario["cert_version"],
        cert_url=scenario["cert_url"],
    )

    # 4. Enrichment (resolve state)
    ws_id = scenario["workstation_ids"][0]
    vlan_id = scenario["ws_vlan_map"].get(ws_id)
    await state_map.resolve_workstation_state(
        org_id=scenario["org_id"],
        vlan_id=vlan_id,
        ws_id=ws_id,
    )

    assert counter["count"] == 0, (
        f"Las operaciones push + enrichment ejecutaron {counter['count']} "
        f"queries/sesiones a BD en total. Esperado: 0. "
        f"Escenario: {len(scenario['workstation_ids'])} workstations"
    )


# === PROPERTY TESTS ===


class TestZeroDbQueriesInPushDistribution:
    """
    Property 8: Zero database queries in distribution hot path.

    Para cualquier número de workstations conectadas (1-100) y cualquier
    push_config_change/push_msi_update/push_cert_rotation, el total de
    queries a BD ejecutadas SHALL ser exactamente 0.

    También verifica que resolve_workstation_state() con state map poblado
    no ejecuta queries a BD.

    Feature: push-based-distribution, Property 8: Zero database queries in distribution hot path

    **Validates: Requirements 9.1, 9.2**
    """

    @given(scenario=_push_scenario)
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_push_config_change_zero_db_queries(self, scenario: dict):
        """
        push_config_change() envía mensajes a N workstations sin ejecutar
        ninguna query a BD. Los datos provienen del caller y del connection_manager.

        **Validates: Requirements 9.1**
        """
        asyncio.run(_run_push_config_test(scenario))

    @given(scenario=_push_scenario)
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_push_msi_update_zero_db_queries(self, scenario: dict):
        """
        push_msi_update() envía mensajes a N workstations sin ejecutar
        ninguna query a BD. Los datos provienen del caller.

        **Validates: Requirements 9.1**
        """
        asyncio.run(_run_push_msi_test(scenario))

    @given(scenario=_push_scenario)
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_push_cert_rotation_zero_db_queries(self, scenario: dict):
        """
        push_cert_rotation() envía mensajes a N workstations sin ejecutar
        ninguna query a BD. Los datos provienen del caller.

        **Validates: Requirements 9.1**
        """
        asyncio.run(_run_push_cert_test(scenario))

    @given(scenario=_push_scenario)
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_resolve_workstation_state_zero_db_queries_when_populated(
        self, scenario: dict
    ):
        """
        resolve_workstation_state() con state map ya poblado para la org
        retorna datos sin ejecutar ninguna query a BD. El enrichment de
        registro es O(1) cuando los datos ya están en memoria.

        **Validates: Requirements 9.2**
        """
        asyncio.run(_run_resolve_state_test(scenario))

    @given(scenario=_push_scenario)
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_all_push_operations_combined_zero_db_queries(self, scenario: dict):
        """
        Ejecutar las 3 operaciones push en secuencia para N workstations
        resulta en 0 queries a BD en total. Verifica que no hay queries
        ocultas en ningún path del flujo de distribución.

        **Validates: Requirements 9.1, 9.2**
        """
        asyncio.run(_run_all_push_operations_test(scenario))
