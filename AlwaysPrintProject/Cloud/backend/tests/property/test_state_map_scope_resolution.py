"""
Property test: State map scope structure.

Verifica que para cualquier organización con múltiples configs activas a
diferentes scopes, `resolve_workstation_state()` retorna la config del scope
más específico aplicando la jerarquía: workstation > vlan > org.

Adicionalmente verifica que cert_version, msi_version y msi_url SIEMPRE
provienen del nivel org, independientemente del scope de config seleccionado.

Feature: push-based-distribution, Property 4: State map scope structure

**Validates: Requirements 1.6**
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.state_map_service import (
    OrgDistributionState,
    StateMapService,
    VlanConfigState,
    WsConfigState,
)


# === ESTRATEGIAS DE GENERACIÓN ===

# UUIDs aleatorios como strings
uuid_strategy = st.uuids().map(str)

# Hashes SHA256 cortos (8 chars hex)
hash_strategy = st.text(
    alphabet="0123456789abcdef",
    min_size=8,
    max_size=8,
)

# URLs S3 públicas aleatorias
s3_url_strategy = st.builds(
    lambda key: f"https://test-bucket.s3.us-east-1.amazonaws.com/{key}",
    key=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz0123456789/-.",
        min_size=10,
        max_size=60,
    ),
)

# Versiones de certificado (1-100)
cert_version_strategy = st.integers(min_value=1, max_value=100)

# Versiones de MSI (formato semver simplificado)
msi_version_strategy = st.builds(
    lambda major, minor, patch: f"{major}.{minor}.{patch}",
    major=st.integers(min_value=1, max_value=10),
    minor=st.integers(min_value=0, max_value=99),
    patch=st.integers(min_value=0, max_value=99),
)

# Estrategia para un par (hash, url) de config
config_pair_strategy = st.tuples(hash_strategy, s3_url_strategy)


# === ESTRATEGIA COMPUESTA: ESCENARIO DE RESOLUCIÓN DE SCOPE ===

@st.composite
def scope_resolution_scenario(draw):
    """
    Genera un escenario completo con:
    - org_id: organización objetivo
    - org_config: par (hash, url) para config a nivel org (siempre presente)
    - vlan_configs: dict de vlan_id → (hash, url) para 0-N VLANs
    - ws_configs: dict de ws_id → (hash, url) para 0-N workstations
    - target_ws_id: la workstation que queremos resolver
    - target_vlan_id: la VLAN de la workstation objetivo
    - cert_version y cert_url: datos de certificado a nivel org
    - msi_version y msi_url: datos de MSI a nivel org
    """
    org_id = draw(uuid_strategy)

    # Config a nivel org (siempre presente como fallback)
    org_config_hash = draw(hash_strategy)
    org_config_url = draw(s3_url_strategy)

    # Workstation objetivo y su VLAN
    target_ws_id = draw(uuid_strategy)
    target_vlan_id = draw(uuid_strategy)

    # Generar 0-5 configs a nivel VLAN (puede incluir la VLAN del target o no)
    num_vlan_configs = draw(st.integers(min_value=0, max_value=5))
    vlan_configs = {}
    for _ in range(num_vlan_configs):
        vlan_id = draw(uuid_strategy)
        vlan_hash = draw(hash_strategy)
        vlan_url = draw(s3_url_strategy)
        vlan_configs[vlan_id] = (vlan_hash, vlan_url)

    # Decidir si la VLAN del target tiene config
    has_target_vlan_config = draw(st.booleans())
    if has_target_vlan_config:
        target_vlan_hash = draw(hash_strategy)
        target_vlan_url = draw(s3_url_strategy)
        vlan_configs[target_vlan_id] = (target_vlan_hash, target_vlan_url)

    # Generar 0-5 configs a nivel workstation (puede incluir target o no)
    num_ws_configs = draw(st.integers(min_value=0, max_value=5))
    ws_configs = {}
    for _ in range(num_ws_configs):
        ws_id = draw(uuid_strategy)
        ws_hash = draw(hash_strategy)
        ws_url = draw(s3_url_strategy)
        ws_configs[ws_id] = (ws_hash, ws_url)

    # Decidir si la workstation target tiene config propia
    has_target_ws_config = draw(st.booleans())
    if has_target_ws_config:
        target_ws_hash = draw(hash_strategy)
        target_ws_url = draw(s3_url_strategy)
        ws_configs[target_ws_id] = (target_ws_hash, target_ws_url)

    # Datos de cert y MSI a nivel org
    cert_version = draw(cert_version_strategy)
    cert_url = draw(s3_url_strategy)
    msi_version = draw(msi_version_strategy)
    msi_url = draw(s3_url_strategy)

    return {
        "org_id": org_id,
        "org_config_hash": org_config_hash,
        "org_config_url": org_config_url,
        "vlan_configs": vlan_configs,
        "ws_configs": ws_configs,
        "target_ws_id": target_ws_id,
        "target_vlan_id": target_vlan_id,
        "has_target_vlan_config": has_target_vlan_config,
        "has_target_ws_config": has_target_ws_config,
        "cert_version": cert_version,
        "cert_url": cert_url,
        "msi_version": msi_version,
        "msi_url": msi_url,
    }


def _create_state_map_service() -> StateMapService:
    """
    Crea una instancia de StateMapService para testing sin Redis.

    Configura msi_url_expires_at muy en el futuro para evitar que
    _check_msi_url_expiration intente regenerar la URL.
    """
    service = StateMapService(redis_url=None)
    service._redis_available = False
    return service


def _populate_state_map(service: StateMapService, scenario: dict) -> None:
    """
    Puebla el state map directamente con los datos del escenario generado.

    Configura msi_url_expires_at en el futuro lejano para evitar
    regeneración de presigned URL durante el test.
    """
    org_id = scenario["org_id"]

    # Construir VlanConfigState dict
    vlan_states = {}
    for vlan_id, (vlan_hash, vlan_url) in scenario["vlan_configs"].items():
        vlan_states[vlan_id] = VlanConfigState(
            config_hash=vlan_hash,
            config_s3_url=vlan_url,
        )

    # Construir WsConfigState dict
    ws_states = {}
    for ws_id, (ws_hash, ws_url) in scenario["ws_configs"].items():
        ws_states[ws_id] = WsConfigState(
            config_hash=ws_hash,
            config_s3_url=ws_url,
        )

    # Crear el OrgDistributionState completo
    org_state = OrgDistributionState(
        config_hash=scenario["org_config_hash"],
        config_s3_url=scenario["org_config_url"],
        cert_version=scenario["cert_version"],
        cert_url=scenario["cert_url"],
        msi_version=scenario["msi_version"],
        msi_url=scenario["msi_url"],
        # Expiración muy en el futuro para evitar regeneración de URL
        msi_url_expires_at=time.time() + 99999,
        vlan_configs=vlan_states,
        ws_configs=ws_states,
    )

    # Insertar directamente en el mapa interno
    service._state[org_id] = org_state


class TestStateMapScopeResolution:
    """
    Property 4: State map scope structure.

    Para cualquier organización con múltiples configs activas a diferentes
    scopes (org, vlan, workstation), el state map mantiene la config org-level
    como default Y preserva overrides por scope en sub-estructuras (vlan_configs,
    ws_configs), y `resolve_workstation_state()` retorna la config del scope
    más específico.

    **Validates: Requirements 1.6**
    """

    @given(scenario=scope_resolution_scenario())
    @settings(max_examples=100, deadline=None)
    def test_scope_resolution_returns_most_specific_config(self, scenario: dict):
        """
        Para cualquier workstation con configs a múltiples scopes,
        resolve_workstation_state() retorna la config del scope más específico:
        workstation > vlan > org.

        **Validates: Requirements 1.6**
        """
        asyncio.run(self._run_scope_resolution(scenario))

    async def _run_scope_resolution(self, scenario: dict):
        """Ejecuta la resolución de scope y verifica el resultado."""
        service = _create_state_map_service()
        _populate_state_map(service, scenario)

        # Llamar resolve_workstation_state con la WS y VLAN target
        result = await service.resolve_workstation_state(
            org_id=scenario["org_id"],
            vlan_id=scenario["target_vlan_id"],
            ws_id=scenario["target_ws_id"],
        )

        # Determinar el config_hash y config_s3_url esperado según jerarquía
        expected_hash = scenario["org_config_hash"]
        expected_url = scenario["org_config_url"]

        # Override por VLAN (si la VLAN del target tiene config)
        if scenario["has_target_vlan_config"]:
            vlan_config = scenario["vlan_configs"][scenario["target_vlan_id"]]
            expected_hash = vlan_config[0]
            expected_url = vlan_config[1]

        # Override por workstation (más específico, siempre gana)
        if scenario["has_target_ws_config"]:
            ws_config = scenario["ws_configs"][scenario["target_ws_id"]]
            expected_hash = ws_config[0]
            expected_url = ws_config[1]

        # Verificar que se retorna la config del scope más específico
        assert result["config_hash"] == expected_hash, (
            f"config_hash incorrecto. "
            f"Esperado={expected_hash}, Obtenido={result['config_hash']}. "
            f"has_ws_config={scenario['has_target_ws_config']}, "
            f"has_vlan_config={scenario['has_target_vlan_config']}"
        )
        assert result["config_s3_url"] == expected_url, (
            f"config_s3_url incorrecto. "
            f"Esperado={expected_url}, Obtenido={result['config_s3_url']}. "
            f"has_ws_config={scenario['has_target_ws_config']}, "
            f"has_vlan_config={scenario['has_target_vlan_config']}"
        )

    @given(scenario=scope_resolution_scenario())
    @settings(max_examples=100, deadline=None)
    def test_cert_and_msi_always_from_org_level(self, scenario: dict):
        """
        Para cualquier workstation, cert_version, msi_version y msi_url
        SIEMPRE provienen del nivel org, independientemente del scope de
        config seleccionado.

        **Validates: Requirements 1.6**
        """
        asyncio.run(self._run_cert_msi_from_org(scenario))

    async def _run_cert_msi_from_org(self, scenario: dict):
        """Verifica que cert y MSI siempre vienen de org level."""
        service = _create_state_map_service()
        _populate_state_map(service, scenario)

        result = await service.resolve_workstation_state(
            org_id=scenario["org_id"],
            vlan_id=scenario["target_vlan_id"],
            ws_id=scenario["target_ws_id"],
        )

        # cert_version SIEMPRE del org level
        assert result["cert_version"] == scenario["cert_version"], (
            f"cert_version debe venir del org level. "
            f"Esperado={scenario['cert_version']}, Obtenido={result['cert_version']}"
        )

        # cert_url SIEMPRE del org level
        assert result["cert_url"] == scenario["cert_url"], (
            f"cert_url debe venir del org level. "
            f"Esperado={scenario['cert_url']}, Obtenido={result['cert_url']}"
        )

        # msi_version SIEMPRE del org level
        assert result["msi_version"] == scenario["msi_version"], (
            f"msi_version debe venir del org level. "
            f"Esperado={scenario['msi_version']}, Obtenido={result['msi_version']}"
        )

        # msi_url SIEMPRE del org level (puede haber regeneración,
        # pero como expires_at está en el futuro, debe ser el mismo)
        assert result["msi_url"] == scenario["msi_url"], (
            f"msi_url debe venir del org level. "
            f"Esperado={scenario['msi_url']}, Obtenido={result['msi_url']}"
        )

    @given(scenario=scope_resolution_scenario())
    @settings(max_examples=100, deadline=None)
    def test_workstation_scope_overrides_vlan_and_org(self, scenario: dict):
        """
        Si target WS tiene una workstation-level config, esa config se retorna
        incluso si también existe una config a nivel VLAN y org.

        **Validates: Requirements 1.6**
        """
        asyncio.run(self._run_ws_overrides_all(scenario))

    async def _run_ws_overrides_all(self, scenario: dict):
        """Verifica que ws-level siempre gana sobre vlan y org."""
        service = _create_state_map_service()
        _populate_state_map(service, scenario)

        result = await service.resolve_workstation_state(
            org_id=scenario["org_id"],
            vlan_id=scenario["target_vlan_id"],
            ws_id=scenario["target_ws_id"],
        )

        if scenario["has_target_ws_config"]:
            # Si hay config a nivel workstation, ESA debe ser la que se retorna
            ws_config = scenario["ws_configs"][scenario["target_ws_id"]]
            expected_hash = ws_config[0]
            expected_url = ws_config[1]

            assert result["config_hash"] == expected_hash, (
                f"Con ws-level config, debe retornar la config de workstation. "
                f"Esperado={expected_hash}, Obtenido={result['config_hash']}"
            )
            assert result["config_s3_url"] == expected_url, (
                f"Con ws-level config, debe retornar la URL de workstation. "
                f"Esperado={expected_url}, Obtenido={result['config_s3_url']}"
            )

    @given(scenario=scope_resolution_scenario())
    @settings(max_examples=100, deadline=None)
    def test_vlan_scope_overrides_org_when_no_ws_config(self, scenario: dict):
        """
        Si target WS NO tiene workstation-level config pero su VLAN sí
        tiene config, se retorna la config de la VLAN.

        **Validates: Requirements 1.6**
        """
        asyncio.run(self._run_vlan_overrides_org(scenario))

    async def _run_vlan_overrides_org(self, scenario: dict):
        """Verifica que vlan-level gana sobre org cuando no hay ws-level."""
        service = _create_state_map_service()
        _populate_state_map(service, scenario)

        result = await service.resolve_workstation_state(
            org_id=scenario["org_id"],
            vlan_id=scenario["target_vlan_id"],
            ws_id=scenario["target_ws_id"],
        )

        if not scenario["has_target_ws_config"] and scenario["has_target_vlan_config"]:
            # Sin ws config pero con vlan config → vlan gana sobre org
            vlan_config = scenario["vlan_configs"][scenario["target_vlan_id"]]
            expected_hash = vlan_config[0]
            expected_url = vlan_config[1]

            assert result["config_hash"] == expected_hash, (
                f"Sin ws-config, con vlan-config, debe retornar config VLAN. "
                f"Esperado={expected_hash}, Obtenido={result['config_hash']}"
            )
            assert result["config_s3_url"] == expected_url, (
                f"Sin ws-config, con vlan-config, debe retornar URL VLAN. "
                f"Esperado={expected_url}, Obtenido={result['config_s3_url']}"
            )

    @given(scenario=scope_resolution_scenario())
    @settings(max_examples=100, deadline=None)
    def test_org_scope_used_when_no_vlan_or_ws_config(self, scenario: dict):
        """
        Si target WS NO tiene workstation-level config NI su VLAN tiene config,
        se retorna la config a nivel org (default).

        **Validates: Requirements 1.6**
        """
        asyncio.run(self._run_org_fallback(scenario))

    async def _run_org_fallback(self, scenario: dict):
        """Verifica que org-level es el fallback cuando no hay overrides."""
        service = _create_state_map_service()
        _populate_state_map(service, scenario)

        result = await service.resolve_workstation_state(
            org_id=scenario["org_id"],
            vlan_id=scenario["target_vlan_id"],
            ws_id=scenario["target_ws_id"],
        )

        if not scenario["has_target_ws_config"] and not scenario["has_target_vlan_config"]:
            # Sin overrides → org-level config
            assert result["config_hash"] == scenario["org_config_hash"], (
                f"Sin overrides, debe retornar config org-level. "
                f"Esperado={scenario['org_config_hash']}, Obtenido={result['config_hash']}"
            )
            assert result["config_s3_url"] == scenario["org_config_url"], (
                f"Sin overrides, debe retornar URL org-level. "
                f"Esperado={scenario['org_config_url']}, Obtenido={result['config_s3_url']}"
            )
