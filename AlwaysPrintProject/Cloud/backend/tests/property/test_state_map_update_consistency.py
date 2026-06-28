"""
Property test para la consistencia de actualizaciones locales del State Map.

Verifica que para cualquier secuencia aleatoria de cambios (config, cert, MSI),
después de aplicar cada actualización, el mapa en memoria refleja SOLO el último
estado — los valores previos se sobrescriben correctamente.

Feature: push-based-distribution, Property 2: State map local update consistency

**Validates: Requirements 1.2, 1.3, 1.4**
"""

import asyncio
import hashlib
import random
from dataclasses import dataclass

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.services.state_map_service import (
    OrgDistributionState,
    StateMapService,
    VlanConfigState,
    WsConfigState,
)


# === Modelos para representar operaciones de actualización ===


@dataclass
class ConfigUpdate:
    """Representa una actualización de configuración."""

    org_id: str
    config_hash: str
    config_s3_url: str
    scope: str  # "org" | "vlan" | "workstation"
    scope_id: str | None


@dataclass
class CertUpdate:
    """Representa una actualización de certificado ECDSA."""

    org_id: str
    cert_version: int
    cert_url: str


@dataclass
class MsiUpdate:
    """Representa una actualización de MSI."""

    org_id: str
    msi_version: str
    msi_url: str


# === Estrategias de generación de datos ===


def _generate_update_sequence(seed: int, num_updates: int) -> list:
    """
    Genera una secuencia determinística de actualizaciones mezcladas
    (config, cert, MSI) para una organización.

    Cada tipo de actualización sobrescribe el estado anterior del mismo tipo.
    Para configs en el mismo scope, la última actualización gana.
    """
    rng = random.Random(seed)
    org_id = f"org-{seed:08x}"

    # Scopes fijos para generar variabilidad controlada
    vlan_ids = [f"vlan-{i:04d}" for i in range(3)]
    ws_ids = [f"ws-{i:04d}" for i in range(3)]

    updates = []

    for i in range(num_updates):
        update_type = rng.choice(["config", "cert", "msi"])

        if update_type == "config":
            scope = rng.choice(["org", "vlan", "workstation"])
            scope_id = None
            if scope == "vlan":
                scope_id = rng.choice(vlan_ids)
            elif scope == "workstation":
                scope_id = rng.choice(ws_ids)

            config_hash = hashlib.sha256(
                f"{org_id}-config-{i}-{seed}".encode()
            ).hexdigest()[:8]
            config_s3_url = f"https://bucket.s3.us-east-1.amazonaws.com/configs/{org_id}/{config_hash}.signed"

            updates.append(ConfigUpdate(
                org_id=org_id,
                config_hash=config_hash,
                config_s3_url=config_s3_url,
                scope=scope,
                scope_id=scope_id,
            ))

        elif update_type == "cert":
            cert_version = rng.randint(1, 100)
            cert_url = f"https://bucket.s3.us-east-1.amazonaws.com/certs/{org_id}/v{cert_version}.cer"

            updates.append(CertUpdate(
                org_id=org_id,
                cert_version=cert_version,
                cert_url=cert_url,
            ))

        elif update_type == "msi":
            msi_version = f"{rng.randint(1, 9)}.{rng.randint(0, 9)}.{rng.randint(0, 9)}"
            msi_url = f"https://bucket.s3.us-east-1.amazonaws.com/versions/{msi_version}/AlwaysPrint.msi?presigned"

            updates.append(MsiUpdate(
                org_id=org_id,
                msi_version=msi_version,
                msi_url=msi_url,
            ))

    return updates


# Estrategia: secuencia de actualizaciones derivada de seed + longitud
_update_sequences = st.builds(
    _generate_update_sequence,
    seed=st.integers(min_value=0, max_value=2**32 - 1),
    num_updates=st.integers(min_value=1, max_value=30),
)


def _apply_updates_sync(updates: list) -> StateMapService:
    """
    Aplica una secuencia de actualizaciones al StateMapService de forma síncrona.

    Usa asyncio.run para ejecutar los métodos async de update_config/update_cert/update_msi.
    Desactiva Redis para evitar llamadas de pub/sub durante testing.
    """
    service = StateMapService(redis_url=None)
    # Desactivar Redis para evitar publish calls
    service._redis_available = False

    loop = asyncio.new_event_loop()
    try:
        for update in updates:
            if isinstance(update, ConfigUpdate):
                loop.run_until_complete(
                    service.update_config(
                        org_id=update.org_id,
                        config_hash=update.config_hash,
                        config_s3_url=update.config_s3_url,
                        scope=update.scope,
                        scope_id=update.scope_id,
                    )
                )
            elif isinstance(update, CertUpdate):
                loop.run_until_complete(
                    service.update_cert(
                        org_id=update.org_id,
                        cert_version=update.cert_version,
                        cert_url=update.cert_url,
                    )
                )
            elif isinstance(update, MsiUpdate):
                loop.run_until_complete(
                    service.update_msi(
                        org_id=update.org_id,
                        msi_version=update.msi_version,
                        msi_url=update.msi_url,
                    )
                )
    finally:
        loop.close()

    return service


def _compute_expected_state(updates: list) -> dict:
    """
    Calcula el estado esperado aplicando la semántica "last writer wins"
    a cada campo independiente.

    Para configs: cada (scope, scope_id) tiene su propio último valor.
    Para cert: cert_version y cert_url se sobrescriben con el último update.
    Para MSI: msi_version y msi_url se sobrescriben con el último update.
    """
    # Estado esperado a nivel org
    expected = {
        "config_hash": None,
        "config_s3_url": None,
        "cert_version": 0,
        "cert_url": None,
        "msi_version": None,
        "msi_url": None,
        "vlan_configs": {},  # vlan_id → (hash, url)
        "ws_configs": {},  # ws_id → (hash, url)
    }

    for update in updates:
        if isinstance(update, ConfigUpdate):
            if update.scope == "org":
                expected["config_hash"] = update.config_hash
                expected["config_s3_url"] = update.config_s3_url
            elif update.scope == "vlan":
                expected["vlan_configs"][update.scope_id] = (
                    update.config_hash,
                    update.config_s3_url,
                )
            elif update.scope == "workstation":
                expected["ws_configs"][update.scope_id] = (
                    update.config_hash,
                    update.config_s3_url,
                )

        elif isinstance(update, CertUpdate):
            expected["cert_version"] = update.cert_version
            expected["cert_url"] = update.cert_url

        elif isinstance(update, MsiUpdate):
            expected["msi_version"] = update.msi_version
            expected["msi_url"] = update.msi_url

    return expected


# === PROPERTY TESTS ===


class TestStateMapLocalUpdateConsistency:
    """
    Property 2: State map local update consistency.

    Para cualquier evento de cambio de estado (activación de config, rotación
    de certificado, o cambio de versión MSI), después de que el worker local
    procesa el cambio, la entrada del In_Memory_State_Map para esa organización
    refleja los nuevos valores y los valores anteriores se sobrescriben.

    Feature: push-based-distribution, Property 2: State map local update consistency

    **Validates: Requirements 1.2, 1.3, 1.4**
    """

    @given(updates=_update_sequences)
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_config_org_scope_refleja_ultimo_valor(self, updates: list):
        """
        Para configs de scope "org", el state map refleja SOLO el último
        config_hash y config_s3_url asignado.

        **Validates: Requirements 1.2**
        """
        service = _apply_updates_sync(updates)
        expected = _compute_expected_state(updates)

        # Obtener org_id del primer update (todos tienen el mismo org_id)
        org_id = updates[0].org_id
        org_state = service._state.get(org_id)

        assert org_state is not None, (
            f"Org {org_id} no encontrada en state map después de {len(updates)} updates"
        )

        assert org_state.config_hash == expected["config_hash"], (
            f"config_hash no refleja el último valor. "
            f"Esperado: {expected['config_hash']}, "
            f"Obtenido: {org_state.config_hash}"
        )
        assert org_state.config_s3_url == expected["config_s3_url"], (
            f"config_s3_url no refleja el último valor. "
            f"Esperado: {expected['config_s3_url']}, "
            f"Obtenido: {org_state.config_s3_url}"
        )

    @given(updates=_update_sequences)
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_cert_refleja_ultimo_valor(self, updates: list):
        """
        Después de una secuencia de actualizaciones, el state map refleja SOLO
        el último cert_version y cert_url asignado.

        **Validates: Requirements 1.3**
        """
        service = _apply_updates_sync(updates)
        expected = _compute_expected_state(updates)

        org_id = updates[0].org_id
        org_state = service._state.get(org_id)

        assert org_state is not None, (
            f"Org {org_id} no encontrada en state map después de {len(updates)} updates"
        )

        assert org_state.cert_version == expected["cert_version"], (
            f"cert_version no refleja el último valor. "
            f"Esperado: {expected['cert_version']}, "
            f"Obtenido: {org_state.cert_version}"
        )
        assert org_state.cert_url == expected["cert_url"], (
            f"cert_url no refleja el último valor. "
            f"Esperado: {expected['cert_url']}, "
            f"Obtenido: {org_state.cert_url}"
        )

    @given(updates=_update_sequences)
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_msi_refleja_ultimo_valor(self, updates: list):
        """
        Después de una secuencia de actualizaciones, el state map refleja SOLO
        el último msi_version y msi_url asignado.

        **Validates: Requirements 1.4**
        """
        service = _apply_updates_sync(updates)
        expected = _compute_expected_state(updates)

        org_id = updates[0].org_id
        org_state = service._state.get(org_id)

        assert org_state is not None, (
            f"Org {org_id} no encontrada en state map después de {len(updates)} updates"
        )

        assert org_state.msi_version == expected["msi_version"], (
            f"msi_version no refleja el último valor. "
            f"Esperado: {expected['msi_version']}, "
            f"Obtenido: {org_state.msi_version}"
        )
        assert org_state.msi_url == expected["msi_url"], (
            f"msi_url no refleja el último valor. "
            f"Esperado: {expected['msi_url']}, "
            f"Obtenido: {org_state.msi_url}"
        )

    @given(updates=_update_sequences)
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_vlan_configs_independientes_por_scope_id(self, updates: list):
        """
        Diferentes scopes (vlan IDs distintos) mantienen estado independiente.
        Solo se sobrescribe la entrada del scope_id específico.

        **Validates: Requirements 1.2**
        """
        service = _apply_updates_sync(updates)
        expected = _compute_expected_state(updates)

        org_id = updates[0].org_id
        org_state = service._state.get(org_id)

        assert org_state is not None

        # Verificar cada vlan esperada
        for vlan_id, (exp_hash, exp_url) in expected["vlan_configs"].items():
            assert vlan_id in org_state.vlan_configs, (
                f"VLAN {vlan_id} no encontrada en vlan_configs. "
                f"VLANs presentes: {list(org_state.vlan_configs.keys())}"
            )
            actual = org_state.vlan_configs[vlan_id]
            assert actual.config_hash == exp_hash, (
                f"config_hash incorrecto para VLAN {vlan_id}. "
                f"Esperado: {exp_hash}, Obtenido: {actual.config_hash}"
            )
            assert actual.config_s3_url == exp_url, (
                f"config_s3_url incorrecto para VLAN {vlan_id}. "
                f"Esperado: {exp_url}, Obtenido: {actual.config_s3_url}"
            )

    @given(updates=_update_sequences)
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_ws_configs_independientes_por_scope_id(self, updates: list):
        """
        Diferentes scopes (workstation IDs distintos) mantienen estado independiente.
        Solo se sobrescribe la entrada del scope_id específico.

        **Validates: Requirements 1.2**
        """
        service = _apply_updates_sync(updates)
        expected = _compute_expected_state(updates)

        org_id = updates[0].org_id
        org_state = service._state.get(org_id)

        assert org_state is not None

        # Verificar cada workstation esperada
        for ws_id, (exp_hash, exp_url) in expected["ws_configs"].items():
            assert ws_id in org_state.ws_configs, (
                f"WS {ws_id} no encontrada en ws_configs. "
                f"WSs presentes: {list(org_state.ws_configs.keys())}"
            )
            actual = org_state.ws_configs[ws_id]
            assert actual.config_hash == exp_hash, (
                f"config_hash incorrecto para WS {ws_id}. "
                f"Esperado: {exp_hash}, Obtenido: {actual.config_hash}"
            )
            assert actual.config_s3_url == exp_url, (
                f"config_s3_url incorrecto para WS {ws_id}. "
                f"Esperado: {exp_url}, Obtenido: {actual.config_s3_url}"
            )

    @given(updates=_update_sequences)
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_scopes_no_interfieren_entre_si(self, updates: list):
        """
        Un update a un scope no modifica otro scope.
        Config org, vlan y workstation son independientes entre sí.
        Cert y MSI también son independientes de config.

        **Validates: Requirements 1.2, 1.3, 1.4**
        """
        service = _apply_updates_sync(updates)
        expected = _compute_expected_state(updates)

        org_id = updates[0].org_id
        org_state = service._state.get(org_id)

        assert org_state is not None

        # Verificar que el total de vlan_configs es exactamente el esperado
        # (no hay entradas espurias creadas por updates de otros scopes)
        assert set(org_state.vlan_configs.keys()) == set(expected["vlan_configs"].keys()), (
            f"vlan_configs tiene entradas inesperadas. "
            f"Esperadas: {set(expected['vlan_configs'].keys())}, "
            f"Obtenidas: {set(org_state.vlan_configs.keys())}"
        )

        # Verificar que el total de ws_configs es exactamente el esperado
        assert set(org_state.ws_configs.keys()) == set(expected["ws_configs"].keys()), (
            f"ws_configs tiene entradas inesperadas. "
            f"Esperadas: {set(expected['ws_configs'].keys())}, "
            f"Obtenidas: {set(org_state.ws_configs.keys())}"
        )
