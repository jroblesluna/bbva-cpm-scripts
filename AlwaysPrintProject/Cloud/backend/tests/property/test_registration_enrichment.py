"""
Property test: Registration enrichment completeness.

Verifica que para cualquier registro exitoso de workstation donde el
StateMapService tiene datos de la organización, la respuesta del método
`resolve_workstation_state()` incluye los 6 campos (config_hash,
config_s3_url, cert_version, cert_url, msi_version, msi_url) con valores
correctos del state map resuelto por scope.

La resolución de scope aplica la jerarquía: workstation > vlan > org
para config_hash y config_s3_url. Los campos cert_version, cert_url,
msi_version y msi_url SIEMPRE provienen del nivel org.

Feature: push-based-distribution, Property 7: Registration enrichment completeness

**Validates: Requirements 5.1**
"""

import asyncio
import time

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

# Versiones de certificado (1-100, siempre > 0 porque estamos en estado poblado)
cert_version_strategy = st.integers(min_value=1, max_value=100)

# Versiones de MSI (formato semver simplificado)
msi_version_strategy = st.builds(
    lambda major, minor, patch: f"{major}.{minor}.{patch}",
    major=st.integers(min_value=1, max_value=10),
    minor=st.integers(min_value=0, max_value=99),
    patch=st.integers(min_value=0, max_value=99),
)


# === ESTRATEGIA COMPUESTA: ESCENARIO DE ENRICHMENT ===


@st.composite
def enrichment_scenario(draw):
    """
    Genera un escenario completo de registro enriquecido con state map poblado.

    Siempre genera un state map con datos válidos (todos los 6 campos poblados)
    para verificar que resolve_workstation_state() retorna la información completa.

    Incluye escenarios con y sin overrides de VLAN y workstation.
    """
    org_id = draw(uuid_strategy)

    # Config a nivel org (siempre presente como base)
    org_config_hash = draw(hash_strategy)
    org_config_url = draw(s3_url_strategy)

    # Certificado ECDSA (siempre desde org level)
    cert_version = draw(cert_version_strategy)
    cert_url = draw(s3_url_strategy)

    # MSI (siempre desde org level)
    msi_version = draw(msi_version_strategy)
    msi_url = draw(s3_url_strategy)

    # Workstation objetivo y su VLAN
    target_ws_id = draw(uuid_strategy)
    target_vlan_id = draw(uuid_strategy)

    # Generar configs VLAN adicionales (0-3 VLANs extra)
    num_extra_vlans = draw(st.integers(min_value=0, max_value=3))
    vlan_configs = {}
    for _ in range(num_extra_vlans):
        vlan_id = draw(uuid_strategy)
        vlan_configs[vlan_id] = (draw(hash_strategy), draw(s3_url_strategy))

    # Decidir si la VLAN del target tiene config override
    has_target_vlan_config = draw(st.booleans())
    target_vlan_hash = None
    target_vlan_url = None
    if has_target_vlan_config:
        target_vlan_hash = draw(hash_strategy)
        target_vlan_url = draw(s3_url_strategy)
        vlan_configs[target_vlan_id] = (target_vlan_hash, target_vlan_url)

    # Generar configs workstation adicionales (0-3 WS extra)
    num_extra_ws = draw(st.integers(min_value=0, max_value=3))
    ws_configs = {}
    for _ in range(num_extra_ws):
        ws_id = draw(uuid_strategy)
        ws_configs[ws_id] = (draw(hash_strategy), draw(s3_url_strategy))

    # Decidir si la workstation target tiene config override
    has_target_ws_config = draw(st.booleans())
    target_ws_hash = None
    target_ws_url = None
    if has_target_ws_config:
        target_ws_hash = draw(hash_strategy)
        target_ws_url = draw(s3_url_strategy)
        ws_configs[target_ws_id] = (target_ws_hash, target_ws_url)

    return {
        "org_id": org_id,
        "org_config_hash": org_config_hash,
        "org_config_url": org_config_url,
        "cert_version": cert_version,
        "cert_url": cert_url,
        "msi_version": msi_version,
        "msi_url": msi_url,
        "target_ws_id": target_ws_id,
        "target_vlan_id": target_vlan_id,
        "vlan_configs": vlan_configs,
        "ws_configs": ws_configs,
        "has_target_vlan_config": has_target_vlan_config,
        "has_target_ws_config": has_target_ws_config,
        "target_vlan_hash": target_vlan_hash,
        "target_vlan_url": target_vlan_url,
        "target_ws_hash": target_ws_hash,
        "target_ws_url": target_ws_url,
    }


# === HELPERS ===


def _create_state_map_service() -> StateMapService:
    """Crea una instancia de StateMapService para testing sin Redis."""
    service = StateMapService(redis_url=None)
    service._redis_available = False
    return service


def _populate_state_map(service: StateMapService, scenario: dict) -> None:
    """
    Puebla el state map directamente con los datos del escenario generado.

    Simula que el state map ya tiene datos cargados (post-initialize o
    post-_load_org_state). Configura msi_url_expires_at en el futuro
    para evitar regeneración de presigned URL durante el test.
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

    # Crear el OrgDistributionState completo con todos los 6 campos poblados
    org_state = OrgDistributionState(
        config_hash=scenario["org_config_hash"],
        config_s3_url=scenario["org_config_url"],
        cert_version=scenario["cert_version"],
        cert_url=scenario["cert_url"],
        msi_version=scenario["msi_version"],
        msi_url=scenario["msi_url"],
        # Expiración muy en el futuro para evitar regeneración de presigned URL
        msi_url_expires_at=time.time() + 99999,
        vlan_configs=vlan_states,
        ws_configs=ws_states,
    )

    # Insertar directamente en el mapa interno
    service._state[org_id] = org_state


def _compute_expected_state(scenario: dict) -> dict:
    """
    Calcula el estado esperado aplicando resolución de scope.

    Jerarquía: workstation > vlan > org para config.
    cert y msi siempre desde org level.
    """
    # Config: scope resolution (ws > vlan > org)
    expected_config_hash = scenario["org_config_hash"]
    expected_config_url = scenario["org_config_url"]

    if scenario["has_target_vlan_config"]:
        expected_config_hash = scenario["target_vlan_hash"]
        expected_config_url = scenario["target_vlan_url"]

    if scenario["has_target_ws_config"]:
        expected_config_hash = scenario["target_ws_hash"]
        expected_config_url = scenario["target_ws_url"]

    return {
        "config_hash": expected_config_hash,
        "config_s3_url": expected_config_url,
        "cert_version": scenario["cert_version"],
        "cert_url": scenario["cert_url"],
        "msi_version": scenario["msi_version"],
        "msi_url": scenario["msi_url"],
    }


# === TESTS ===


class TestRegistrationEnrichmentCompleteness:
    """
    Property 7: Registration enrichment completeness.

    Para cualquier registro exitoso con state map poblado, verificar que la
    respuesta incluye los 6 campos con valores correctos del state map
    resuelto por scope.

    **Validates: Requirements 5.1**
    """

    @given(scenario=enrichment_scenario())
    @settings(max_examples=100, deadline=None)
    def test_enrichment_returns_all_six_fields(self, scenario: dict):
        """
        Para cualquier registro exitoso con state map poblado,
        resolve_workstation_state() retorna un dict con exactamente
        los 6 campos requeridos: config_hash, config_s3_url, cert_version,
        cert_url, msi_version, msi_url.

        **Validates: Requirements 5.1**
        """
        asyncio.run(self._run_all_fields_present(scenario))

    async def _run_all_fields_present(self, scenario: dict):
        """Verifica que los 6 campos están presentes en la respuesta."""
        service = _create_state_map_service()
        _populate_state_map(service, scenario)

        result = await service.resolve_workstation_state(
            org_id=scenario["org_id"],
            vlan_id=scenario["target_vlan_id"],
            ws_id=scenario["target_ws_id"],
        )

        # Los 6 campos requeridos deben estar presentes como claves
        required_fields = [
            "config_hash",
            "config_s3_url",
            "cert_version",
            "cert_url",
            "msi_version",
            "msi_url",
        ]

        for field in required_fields:
            assert field in result, (
                f"Campo '{field}' ausente en la respuesta de enrichment. "
                f"Campos presentes: {list(result.keys())}"
            )

    @given(scenario=enrichment_scenario())
    @settings(max_examples=100, deadline=None)
    def test_enrichment_values_match_state_map_resolved_by_scope(
        self, scenario: dict
    ):
        """
        Para cualquier registro exitoso con state map poblado, los valores
        retornados por resolve_workstation_state() coinciden con los valores
        esperados aplicando resolución de scope (ws > vlan > org para config,
        org level para cert y msi).

        **Validates: Requirements 5.1**
        """
        asyncio.run(self._run_values_match(scenario))

    async def _run_values_match(self, scenario: dict):
        """Verifica que los valores coinciden con la resolución de scope esperada."""
        service = _create_state_map_service()
        _populate_state_map(service, scenario)

        result = await service.resolve_workstation_state(
            org_id=scenario["org_id"],
            vlan_id=scenario["target_vlan_id"],
            ws_id=scenario["target_ws_id"],
        )

        expected = _compute_expected_state(scenario)

        # Verificar config_hash (scope resolution: ws > vlan > org)
        assert result["config_hash"] == expected["config_hash"], (
            f"config_hash incorrecto. "
            f"Esperado={expected['config_hash']}, Obtenido={result['config_hash']}. "
            f"has_ws_config={scenario['has_target_ws_config']}, "
            f"has_vlan_config={scenario['has_target_vlan_config']}"
        )

        # Verificar config_s3_url (scope resolution: ws > vlan > org)
        assert result["config_s3_url"] == expected["config_s3_url"], (
            f"config_s3_url incorrecto. "
            f"Esperado={expected['config_s3_url']}, Obtenido={result['config_s3_url']}. "
            f"has_ws_config={scenario['has_target_ws_config']}, "
            f"has_vlan_config={scenario['has_target_vlan_config']}"
        )

        # Verificar cert_version (siempre desde org level)
        assert result["cert_version"] == expected["cert_version"], (
            f"cert_version incorrecto. "
            f"Esperado={expected['cert_version']}, Obtenido={result['cert_version']}"
        )

        # Verificar cert_url (siempre desde org level)
        assert result["cert_url"] == expected["cert_url"], (
            f"cert_url incorrecto. "
            f"Esperado={expected['cert_url']}, Obtenido={result['cert_url']}"
        )

        # Verificar msi_version (siempre desde org level)
        assert result["msi_version"] == expected["msi_version"], (
            f"msi_version incorrecto. "
            f"Esperado={expected['msi_version']}, Obtenido={result['msi_version']}"
        )

        # Verificar msi_url (siempre desde org level)
        assert result["msi_url"] == expected["msi_url"], (
            f"msi_url incorrecto. "
            f"Esperado={expected['msi_url']}, Obtenido={result['msi_url']}"
        )

    @given(scenario=enrichment_scenario())
    @settings(max_examples=100, deadline=None)
    def test_enrichment_config_scope_ws_overrides_vlan_and_org(
        self, scenario: dict
    ):
        """
        Si la workstation tiene una config override a nivel workstation,
        config_hash y config_s3_url del enrichment provienen de ese override,
        no del nivel VLAN ni org.

        **Validates: Requirements 5.1**
        """
        asyncio.run(self._run_ws_scope_override(scenario))

    async def _run_ws_scope_override(self, scenario: dict):
        """Verifica override de workstation sobre VLAN y org en enrichment."""
        service = _create_state_map_service()
        _populate_state_map(service, scenario)

        result = await service.resolve_workstation_state(
            org_id=scenario["org_id"],
            vlan_id=scenario["target_vlan_id"],
            ws_id=scenario["target_ws_id"],
        )

        if scenario["has_target_ws_config"]:
            # Workstation override debe ganar
            assert result["config_hash"] == scenario["target_ws_hash"], (
                f"Con ws-level override, config_hash debe ser el de workstation. "
                f"Esperado={scenario['target_ws_hash']}, Obtenido={result['config_hash']}"
            )
            assert result["config_s3_url"] == scenario["target_ws_url"], (
                f"Con ws-level override, config_s3_url debe ser el de workstation. "
                f"Esperado={scenario['target_ws_url']}, Obtenido={result['config_s3_url']}"
            )

    @given(scenario=enrichment_scenario())
    @settings(max_examples=100, deadline=None)
    def test_enrichment_cert_and_msi_always_from_org_regardless_of_config_scope(
        self, scenario: dict
    ):
        """
        Independientemente del scope de config resuelto (org, vlan, ws),
        cert_version, cert_url, msi_version y msi_url SIEMPRE provienen
        del nivel org en el enrichment de registro.

        **Validates: Requirements 5.1**
        """
        asyncio.run(self._run_cert_msi_always_org(scenario))

    async def _run_cert_msi_always_org(self, scenario: dict):
        """Verifica que cert y MSI siempre vienen de org level en enrichment."""
        service = _create_state_map_service()
        _populate_state_map(service, scenario)

        result = await service.resolve_workstation_state(
            org_id=scenario["org_id"],
            vlan_id=scenario["target_vlan_id"],
            ws_id=scenario["target_ws_id"],
        )

        # cert_version SIEMPRE del org level
        assert result["cert_version"] == scenario["cert_version"], (
            f"cert_version SIEMPRE debe venir del org level en enrichment. "
            f"Esperado={scenario['cert_version']}, Obtenido={result['cert_version']}"
        )

        # cert_url SIEMPRE del org level
        assert result["cert_url"] == scenario["cert_url"], (
            f"cert_url SIEMPRE debe venir del org level en enrichment. "
            f"Esperado={scenario['cert_url']}, Obtenido={result['cert_url']}"
        )

        # msi_version SIEMPRE del org level
        assert result["msi_version"] == scenario["msi_version"], (
            f"msi_version SIEMPRE debe venir del org level en enrichment. "
            f"Esperado={scenario['msi_version']}, Obtenido={result['msi_version']}"
        )

        # msi_url SIEMPRE del org level (no regenera porque expires_at está en el futuro)
        assert result["msi_url"] == scenario["msi_url"], (
            f"msi_url SIEMPRE debe venir del org level en enrichment. "
            f"Esperado={scenario['msi_url']}, Obtenido={result['msi_url']}"
        )
