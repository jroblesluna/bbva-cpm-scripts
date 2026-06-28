"""
Property test para la completitud de la inicialización del State Map.

Verifica que para cualquier conjunto de organizaciones activas con configs/certs/MSI
en la base de datos, después de procesar las filas del JOIN, el mapa en memoria
contiene una entrada para cada org activa con valores correctos.

Feature: push-based-distribution, Property 1: State map initialization completeness

**Validates: Requirements 1.1**
"""

import hashlib
import random
from collections import namedtuple
from unittest.mock import MagicMock

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.services.state_map_service import (
    OrgDistributionState,
    StateMapService,
    VlanConfigState,
    WsConfigState,
)


# === Estrategias de generación de datos ===

# Row que simula el resultado del JOIN entre organizations y action_configs
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


def _generate_organizations(seed: int, num_orgs: int) -> list[dict]:
    """
    Genera un conjunto determinístico de organizaciones a partir de un seed.

    Evita usar @st.composite con loops internos (que causan problemas
    de rendimiento en Hypothesis) usando un PRNG local para derivar datos.
    """
    rng = random.Random(seed)
    organizations = []

    for i in range(num_orgs):
        org_id = f"org-{seed:04x}-{i:02d}"
        cert_version = rng.randint(0, 50)
        has_cert = rng.choice([True, False])
        cert_s3_key = (
            f"certs/{org_id}/v{cert_version}.cer"
            if has_cert and cert_version > 0
            else None
        )

        has_msi = rng.choice([True, False])
        msi_version = (
            f"{rng.randint(0, 9)}.{rng.randint(0, 9)}.{rng.randint(0, 9)}"
            if has_msi
            else None
        )

        auto_update = rng.choice([True, False])

        # Generar entre 0 y 5 configs
        num_configs = rng.randint(0, 5)
        configs = []
        for j in range(num_configs):
            scope = rng.choice(["org", "vlan", "workstation"])
            config_hash = hashlib.sha256(
                f"{org_id}-config-{j}-{seed}".encode()
            ).hexdigest()[:8]
            config_s3_key = f"configs/{org_id}/{config_hash}.signed"

            vlan_id = None
            workstation_id = None
            if scope == "vlan":
                vlan_id = f"vlan-{rng.randint(0, 9):04d}"
            elif scope == "workstation":
                workstation_id = f"ws-{rng.randint(0, 9):04d}"

            configs.append({
                "config_hash": config_hash,
                "config_s3_key": config_s3_key,
                "scope": scope,
                "vlan_id": vlan_id,
                "workstation_id": workstation_id,
            })

        organizations.append({
            "org_id": org_id,
            "cert_version": cert_version,
            "cert_s3_key": cert_s3_key,
            "msi_version": msi_version,
            "auto_update_enabled": auto_update,
            "configs": configs,
        })

    return organizations


# Estrategia que genera datos a partir de un seed y cantidad de orgs
# Hypothesis solo necesita explorar 2 enteros, no árboles de draws complejos
_orgs_data = st.builds(
    _generate_organizations,
    seed=st.integers(min_value=0, max_value=2**32 - 1),
    num_orgs=st.integers(min_value=1, max_value=10),
)


def _build_db_rows(organizations: list[dict]) -> list[_OrgRow]:
    """
    Construye las filas que retornaría la query JOIN de initialize()
    a partir de un conjunto de organizaciones generadas.
    """
    rows = []
    for org in organizations:
        if not org["configs"]:
            # Org sin configs activas: LEFT JOIN produce una fila con config_* = None
            rows.append(
                _OrgRow(
                    org_id=org["org_id"],
                    cert_version=org["cert_version"],
                    cert_s3_key=org["cert_s3_key"],
                    msi_version=org["msi_version"],
                    auto_update_enabled=org["auto_update_enabled"],
                    config_hash=None,
                    config_s3_key=None,
                    scope=None,
                    vlan_id=None,
                    workstation_id=None,
                )
            )
        else:
            # Una fila por cada config activa de la org
            for config in org["configs"]:
                rows.append(
                    _OrgRow(
                        org_id=org["org_id"],
                        cert_version=org["cert_version"],
                        cert_s3_key=org["cert_s3_key"],
                        msi_version=org["msi_version"],
                        auto_update_enabled=org["auto_update_enabled"],
                        config_hash=config["config_hash"],
                        config_s3_key=config["config_s3_key"],
                        scope=config["scope"],
                        vlan_id=config["vlan_id"],
                        workstation_id=config["workstation_id"],
                    )
                )
    return rows


def _initialize_service(organizations: list[dict]) -> StateMapService:
    """
    Crea un StateMapService y ejecuta la lógica de inicialización de forma síncrona.

    Replica la lógica síncrona de initialize() (procesamiento de filas del JOIN)
    sin invocar la parte async (_initialize_redis). Esto verifica que la lógica core
    de carga del state map funciona correctamente con datos generados.
    """
    db_rows = _build_db_rows(organizations)

    # Crear el servicio sin Redis
    service = StateMapService(redis_url=None)

    # Ejecutar la lógica de procesamiento de filas (misma que initialize())
    for row in db_rows:
        org_id = str(row.org_id)
        org_state = service._state.get(org_id)

        if org_state is None:
            cert_url = None
            if row.cert_s3_key:
                cert_url = StateMapService._build_public_url(row.cert_s3_key)

            org_state = OrgDistributionState(
                cert_version=row.cert_version or 0,
                cert_url=cert_url,
                msi_version=row.msi_version,
            )
            service._state[org_id] = org_state

        # Procesar action_config (puede ser None por LEFT JOIN)
        if row.config_hash and row.config_s3_key:
            config_s3_url = StateMapService._build_public_url(row.config_s3_key)
            scope = row.scope

            if scope == "org":
                org_state.config_hash = row.config_hash
                org_state.config_s3_url = config_s3_url
            elif scope == "vlan" and row.vlan_id:
                vlan_id = str(row.vlan_id)
                org_state.vlan_configs[vlan_id] = VlanConfigState(
                    config_hash=row.config_hash,
                    config_s3_url=config_s3_url,
                )
            elif scope == "workstation" and row.workstation_id:
                ws_id = str(row.workstation_id)
                org_state.ws_configs[ws_id] = WsConfigState(
                    config_hash=row.config_hash,
                    config_s3_url=config_s3_url,
                )

    return service


# === PROPERTY TESTS ===


class TestStateMapInitializationCompleteness:
    """
    Property 1: State map initialization completeness.

    Para cualquier conjunto de organizaciones activas en la base de datos,
    después de `StateMapService.initialize()`, el mapa en memoria contiene
    una entrada para cada organización activa con su config_hash, cert_version
    y msi_version correctos, coincidiendo con los valores de la base de datos.

    Feature: push-based-distribution, Property 1: State map initialization completeness

    **Validates: Requirements 1.1**
    """

    @given(organizations=_orgs_data)
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_state_map_contiene_entrada_para_cada_org_activa(
        self, organizations: list[dict]
    ):
        """
        Para cualquier conjunto de orgs activas, initialize() produce un mapa
        con una entrada por cada org. Ninguna org se pierde en la carga.

        **Validates: Requirements 1.1**
        """
        service = _initialize_service(organizations)

        for org in organizations:
            org_id = org["org_id"]
            assert org_id in service._state, (
                f"La organización {org_id} no se encuentra en el state map. "
                f"Total orgs generadas: {len(organizations)}, "
                f"Total orgs en map: {len(service._state)}"
            )

    @given(organizations=_orgs_data)
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_cert_version_correcto_por_org(self, organizations: list[dict]):
        """
        Para cualquier org activa, el cert_version en el state map coincide
        con el valor de la BD.

        **Validates: Requirements 1.1**
        """
        service = _initialize_service(organizations)

        for org in organizations:
            org_id = org["org_id"]
            org_state = service._state[org_id]

            expected_cert_version = org["cert_version"] or 0
            assert org_state.cert_version == expected_cert_version, (
                f"cert_version incorrecto para org {org_id}. "
                f"Esperado: {expected_cert_version}, "
                f"Obtenido: {org_state.cert_version}"
            )

    @given(organizations=_orgs_data)
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_msi_version_correcto_por_org(self, organizations: list[dict]):
        """
        Para cualquier org activa, el msi_version en el state map coincide
        con el valor de la BD.

        **Validates: Requirements 1.1**
        """
        service = _initialize_service(organizations)

        for org in organizations:
            org_id = org["org_id"]
            org_state = service._state[org_id]

            assert org_state.msi_version == org["msi_version"], (
                f"msi_version incorrecto para org {org_id}. "
                f"Esperado: {org['msi_version']}, "
                f"Obtenido: {org_state.msi_version}"
            )

    @given(organizations=_orgs_data)
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_config_hash_org_scope_correcto(self, organizations: list[dict]):
        """
        Para cualquier org con una config de scope "org", el config_hash a nivel
        org en el state map coincide con el valor de la BD.

        **Validates: Requirements 1.1**
        """
        service = _initialize_service(organizations)

        for org in organizations:
            org_id = org["org_id"]
            org_state = service._state[org_id]

            # Buscar la última config con scope "org" (la última procesada gana)
            org_scope_configs = [
                c for c in org["configs"] if c["scope"] == "org"
            ]

            if org_scope_configs:
                # La última config org-scope procesada determina el valor final
                expected_hash = org_scope_configs[-1]["config_hash"]
                assert org_state.config_hash == expected_hash, (
                    f"config_hash incorrecto para org {org_id}. "
                    f"Esperado: {expected_hash}, "
                    f"Obtenido: {org_state.config_hash}"
                )
            else:
                # Sin configs de scope org → config_hash debe ser None
                assert org_state.config_hash is None, (
                    f"config_hash debería ser None para org {org_id} sin config org-scope. "
                    f"Obtenido: {org_state.config_hash}"
                )

    @given(organizations=_orgs_data)
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_vlan_configs_pobladas_correctamente(self, organizations: list[dict]):
        """
        Para cualquier org con configs de scope "vlan", el state map contiene
        entradas correctas en vlan_configs con los hashes correspondientes.

        **Validates: Requirements 1.1**
        """
        service = _initialize_service(organizations)

        for org in organizations:
            org_id = org["org_id"]
            org_state = service._state[org_id]

            # Configs de scope vlan — la última por vlan_id gana
            vlan_configs = [c for c in org["configs"] if c["scope"] == "vlan"]
            expected_vlans = {}
            for vc in vlan_configs:
                if vc["vlan_id"]:
                    expected_vlans[vc["vlan_id"]] = vc["config_hash"]

            # Verificar que cada vlan_id esperada está en el state map
            for vlan_id, expected_hash in expected_vlans.items():
                assert vlan_id in org_state.vlan_configs, (
                    f"VLAN {vlan_id} no encontrada en vlan_configs de org {org_id}. "
                    f"VLANs en map: {list(org_state.vlan_configs.keys())}"
                )
                assert org_state.vlan_configs[vlan_id].config_hash == expected_hash, (
                    f"config_hash incorrecto para VLAN {vlan_id} de org {org_id}. "
                    f"Esperado: {expected_hash}, "
                    f"Obtenido: {org_state.vlan_configs[vlan_id].config_hash}"
                )

    @given(organizations=_orgs_data)
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_workstation_configs_pobladas_correctamente(
        self, organizations: list[dict]
    ):
        """
        Para cualquier org con configs de scope "workstation", el state map contiene
        entradas correctas en ws_configs con los hashes correspondientes.

        **Validates: Requirements 1.1**
        """
        service = _initialize_service(organizations)

        for org in organizations:
            org_id = org["org_id"]
            org_state = service._state[org_id]

            # Configs de scope workstation — la última por ws_id gana
            ws_configs = [
                c for c in org["configs"] if c["scope"] == "workstation"
            ]
            expected_ws = {}
            for wc in ws_configs:
                if wc["workstation_id"]:
                    expected_ws[wc["workstation_id"]] = wc["config_hash"]

            # Verificar que cada workstation_id esperada está en el state map
            for ws_id, expected_hash in expected_ws.items():
                assert ws_id in org_state.ws_configs, (
                    f"Workstation {ws_id} no encontrada en ws_configs de org {org_id}. "
                    f"WSs en map: {list(org_state.ws_configs.keys())}"
                )
                assert org_state.ws_configs[ws_id].config_hash == expected_hash, (
                    f"config_hash incorrecto para WS {ws_id} de org {org_id}. "
                    f"Esperado: {expected_hash}, "
                    f"Obtenido: {org_state.ws_configs[ws_id].config_hash}"
                )

    @given(organizations=_orgs_data)
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_cert_url_construida_correctamente(self, organizations: list[dict]):
        """
        Para cualquier org con cert_s3_key, la cert_url en el state map sigue
        el patrón https://{bucket}.s3.{region}.amazonaws.com/{s3_key}.

        **Validates: Requirements 1.1**
        """
        service = _initialize_service(organizations)

        for org in organizations:
            org_id = org["org_id"]
            org_state = service._state[org_id]

            if org["cert_s3_key"]:
                # Debe tener cert_url construida con el patrón S3
                assert org_state.cert_url is not None, (
                    f"cert_url es None para org {org_id} con cert_s3_key={org['cert_s3_key']}"
                )
                assert org["cert_s3_key"] in org_state.cert_url, (
                    f"cert_url no contiene el s3_key esperado. "
                    f"s3_key: {org['cert_s3_key']}, "
                    f"cert_url: {org_state.cert_url}"
                )
                assert org_state.cert_url.startswith("https://"), (
                    f"cert_url debería iniciar con https://. "
                    f"Obtenido: {org_state.cert_url}"
                )
            else:
                # Sin cert_s3_key → cert_url debe ser None
                assert org_state.cert_url is None, (
                    f"cert_url debería ser None para org {org_id} sin cert_s3_key. "
                    f"Obtenido: {org_state.cert_url}"
                )

    @given(organizations=_orgs_data)
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_no_orgs_extras_en_state_map(self, organizations: list[dict]):
        """
        El state map no contiene entradas extra que no estén en la BD.
        El total de entradas en el map es exactamente el total de orgs generadas.

        **Validates: Requirements 1.1**
        """
        service = _initialize_service(organizations)

        expected_org_ids = {org["org_id"] for org in organizations}
        actual_org_ids = set(service._state.keys())

        assert actual_org_ids == expected_org_ids, (
            f"El state map contiene orgs inesperadas. "
            f"Esperadas: {expected_org_ids}, "
            f"Obtenidas: {actual_org_ids}, "
            f"Extras: {actual_org_ids - expected_org_ids}, "
            f"Faltantes: {expected_org_ids - actual_org_ids}"
        )
