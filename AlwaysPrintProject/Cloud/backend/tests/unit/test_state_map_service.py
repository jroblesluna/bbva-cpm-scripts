"""
Tests unitarios para StateMapService - data models y resolución de scope.

Verifica:
- Instanciación correcta de dataclasses y StateMapService
- get_state retorna None para org inexistente
- get_state retorna estado correcto para org existente
- resolve_workstation_state aplica herencia org < vlan < workstation
"""

import pytest

from app.services.state_map_service import (
    OrgDistributionState,
    StateMapService,
    StateMapUpdate,
    VlanConfigState,
    WsConfigState,
)


class TestDataModels:
    """Verificación de instanciación y defaults de dataclasses."""

    def test_vlan_config_state(self):
        """VlanConfigState almacena hash y url correctamente."""
        state = VlanConfigState(config_hash="abc123", config_s3_url="https://s3/config.signed")
        assert state.config_hash == "abc123"
        assert state.config_s3_url == "https://s3/config.signed"

    def test_ws_config_state(self):
        """WsConfigState almacena hash y url correctamente."""
        state = WsConfigState(config_hash="def456", config_s3_url="https://s3/ws_config.signed")
        assert state.config_hash == "def456"
        assert state.config_s3_url == "https://s3/ws_config.signed"

    def test_org_distribution_state_defaults(self):
        """OrgDistributionState se inicializa con defaults correctos."""
        state = OrgDistributionState()
        assert state.config_hash is None
        assert state.config_s3_url is None
        assert state.cert_version == 0
        assert state.cert_url is None
        assert state.msi_version is None
        assert state.msi_url is None
        assert state.msi_url_expires_at == 0.0
        assert state.vlan_configs == {}
        assert state.ws_configs == {}

    def test_org_distribution_state_with_values(self):
        """OrgDistributionState acepta valores específicos."""
        state = OrgDistributionState(
            config_hash="a1b2c3d4",
            config_s3_url="https://s3/org_config.signed",
            cert_version=3,
            cert_url="https://s3/certs/v3.cer",
            msi_version="2.1.0",
            msi_url="https://s3/versions/2.1.0/AlwaysPrint.msi",
            msi_url_expires_at=1700000000.0,
            vlan_configs={"vlan-1": VlanConfigState("v1hash", "https://s3/v1.signed")},
            ws_configs={"ws-1": WsConfigState("w1hash", "https://s3/w1.signed")},
        )
        assert state.config_hash == "a1b2c3d4"
        assert state.cert_version == 3
        assert state.msi_version == "2.1.0"
        assert "vlan-1" in state.vlan_configs
        assert "ws-1" in state.ws_configs

    def test_state_map_update(self):
        """StateMapUpdate almacena payload de sincronización Redis."""
        update = StateMapUpdate(
            origin_worker_id="worker_12345",
            org_id="org-uuid",
            update_type="config",
            data={"config_hash": "newhash", "config_s3_url": "https://s3/new.signed"},
        )
        assert update.origin_worker_id == "worker_12345"
        assert update.org_id == "org-uuid"
        assert update.update_type == "config"
        assert update.data["config_hash"] == "newhash"


class TestStateMapServiceInit:
    """Verificación de inicialización del servicio."""

    def test_init_sin_redis(self):
        """Se puede crear sin redis_url (modo single-worker)."""
        svc = StateMapService()
        assert svc._state == {}
        assert svc._redis_url is None
        assert svc._redis is None

    def test_init_con_redis_url(self):
        """Almacena redis_url para uso posterior (Task 1.4)."""
        svc = StateMapService(redis_url="redis://localhost:6379/0")
        assert svc._redis_url == "redis://localhost:6379/0"
        assert svc._state == {}


class TestGetState:
    """Verificación de get_state (O(1) lookup)."""

    @pytest.mark.asyncio
    async def test_get_state_org_inexistente(self):
        """Retorna None para org que no existe en el mapa."""
        svc = StateMapService()
        result = await svc.get_state("org-no-existe")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_state_org_existente(self):
        """Retorna OrgDistributionState correcto para org existente."""
        svc = StateMapService()
        expected = OrgDistributionState(config_hash="abc123", cert_version=2)
        svc._state["org-1"] = expected

        result = await svc.get_state("org-1")
        assert result is expected
        assert result.config_hash == "abc123"
        assert result.cert_version == 2


class TestResolveWorkstationState:
    """Verificación de resolución jerárquica de scope (org < vlan < workstation)."""

    @pytest.mark.asyncio
    async def test_org_sin_datos(self):
        """Retorna dict con valores None/default si org no existe."""
        svc = StateMapService()
        result = await svc.resolve_workstation_state("org-x", "vlan-1", "ws-1")
        assert result == {
            "config_hash": None,
            "config_s3_url": None,
            "cert_version": 0,
            "cert_url": None,
            "msi_version": None,
            "msi_url": None,
        }

    @pytest.mark.asyncio
    async def test_solo_org_level(self):
        """Usa config a nivel org cuando no hay overrides."""
        svc = StateMapService()
        svc._state["org-1"] = OrgDistributionState(
            config_hash="org_hash",
            config_s3_url="https://s3/org.signed",
            cert_version=1,
            cert_url="https://s3/cert/v1.cer",
            msi_version="1.0.0",
            msi_url="https://s3/msi/1.0.0.msi",
            msi_url_expires_at=9999999999.0,  # Expiración lejana para evitar regeneración
        )

        result = await svc.resolve_workstation_state("org-1", "vlan-99", "ws-99")
        assert result["config_hash"] == "org_hash"
        assert result["config_s3_url"] == "https://s3/org.signed"
        assert result["cert_version"] == 1
        assert result["cert_url"] == "https://s3/cert/v1.cer"
        assert result["msi_version"] == "1.0.0"
        assert result["msi_url"] == "https://s3/msi/1.0.0.msi"

    @pytest.mark.asyncio
    async def test_vlan_override(self):
        """VLAN override tiene prioridad sobre org para config."""
        svc = StateMapService()
        svc._state["org-1"] = OrgDistributionState(
            config_hash="org_hash",
            config_s3_url="https://s3/org.signed",
            cert_version=2,
            cert_url="https://s3/cert/v2.cer",
            vlan_configs={
                "vlan-5": VlanConfigState("vlan_hash", "https://s3/vlan5.signed"),
            },
        )

        result = await svc.resolve_workstation_state("org-1", "vlan-5", "ws-99")
        # Config viene de VLAN
        assert result["config_hash"] == "vlan_hash"
        assert result["config_s3_url"] == "https://s3/vlan5.signed"
        # Cert/MSI siempre a nivel org
        assert result["cert_version"] == 2
        assert result["cert_url"] == "https://s3/cert/v2.cer"

    @pytest.mark.asyncio
    async def test_workstation_override(self):
        """Workstation override tiene la prioridad más alta para config."""
        svc = StateMapService()
        svc._state["org-1"] = OrgDistributionState(
            config_hash="org_hash",
            config_s3_url="https://s3/org.signed",
            cert_version=3,
            cert_url="https://s3/cert/v3.cer",
            vlan_configs={
                "vlan-5": VlanConfigState("vlan_hash", "https://s3/vlan5.signed"),
            },
            ws_configs={
                "ws-42": WsConfigState("ws_hash", "https://s3/ws42.signed"),
            },
        )

        result = await svc.resolve_workstation_state("org-1", "vlan-5", "ws-42")
        # Config viene de workstation (más específico)
        assert result["config_hash"] == "ws_hash"
        assert result["config_s3_url"] == "https://s3/ws42.signed"
        # Cert/MSI siempre a nivel org
        assert result["cert_version"] == 3

    @pytest.mark.asyncio
    async def test_workstation_override_sin_vlan(self):
        """WS override funciona aun cuando vlan_id es None."""
        svc = StateMapService()
        svc._state["org-1"] = OrgDistributionState(
            config_hash="org_hash",
            config_s3_url="https://s3/org.signed",
            ws_configs={
                "ws-10": WsConfigState("ws10_hash", "https://s3/ws10.signed"),
            },
        )

        result = await svc.resolve_workstation_state("org-1", None, "ws-10")
        assert result["config_hash"] == "ws10_hash"
        assert result["config_s3_url"] == "https://s3/ws10.signed"

    @pytest.mark.asyncio
    async def test_vlan_no_matchea(self):
        """Si la VLAN no tiene override, usa org level."""
        svc = StateMapService()
        svc._state["org-1"] = OrgDistributionState(
            config_hash="org_hash",
            config_s3_url="https://s3/org.signed",
            vlan_configs={
                "vlan-5": VlanConfigState("vlan5_hash", "https://s3/vlan5.signed"),
            },
        )

        # vlan-99 no tiene override
        result = await svc.resolve_workstation_state("org-1", "vlan-99", "ws-1")
        assert result["config_hash"] == "org_hash"
        assert result["config_s3_url"] == "https://s3/org.signed"


class TestUpdateConfig:
    """Verificación de update_config con los 3 scopes."""

    @pytest.mark.asyncio
    async def test_update_config_scope_org(self):
        """Scope 'org' actualiza config_hash y config_s3_url a nivel org."""
        svc = StateMapService()
        await svc.update_config(
            org_id="org-1",
            config_hash="hash123",
            config_s3_url="https://s3/configs/org-1/hash123.signed",
            scope="org",
            scope_id=None,
        )

        state = await svc.get_state("org-1")
        assert state is not None
        assert state.config_hash == "hash123"
        assert state.config_s3_url == "https://s3/configs/org-1/hash123.signed"

    @pytest.mark.asyncio
    async def test_update_config_scope_vlan(self):
        """Scope 'vlan' crea/actualiza entrada en vlan_configs."""
        svc = StateMapService()
        await svc.update_config(
            org_id="org-1",
            config_hash="vlan_hash",
            config_s3_url="https://s3/configs/org-1/vlan_hash.signed",
            scope="vlan",
            scope_id="vlan-5",
        )

        state = await svc.get_state("org-1")
        assert state is not None
        assert "vlan-5" in state.vlan_configs
        assert state.vlan_configs["vlan-5"].config_hash == "vlan_hash"
        assert state.vlan_configs["vlan-5"].config_s3_url == "https://s3/configs/org-1/vlan_hash.signed"

    @pytest.mark.asyncio
    async def test_update_config_scope_workstation(self):
        """Scope 'workstation' crea/actualiza entrada en ws_configs."""
        svc = StateMapService()
        await svc.update_config(
            org_id="org-1",
            config_hash="ws_hash",
            config_s3_url="https://s3/configs/org-1/ws_hash.signed",
            scope="workstation",
            scope_id="ws-42",
        )

        state = await svc.get_state("org-1")
        assert state is not None
        assert "ws-42" in state.ws_configs
        assert state.ws_configs["ws-42"].config_hash == "ws_hash"
        assert state.ws_configs["ws-42"].config_s3_url == "https://s3/configs/org-1/ws_hash.signed"

    @pytest.mark.asyncio
    async def test_update_config_crea_org_si_no_existe(self):
        """Si la org no existe en el mapa, la crea automáticamente."""
        svc = StateMapService()
        assert await svc.get_state("org-nueva") is None

        await svc.update_config(
            org_id="org-nueva",
            config_hash="new_hash",
            config_s3_url="https://s3/new.signed",
            scope="org",
            scope_id=None,
        )

        state = await svc.get_state("org-nueva")
        assert state is not None
        assert state.config_hash == "new_hash"

    @pytest.mark.asyncio
    async def test_update_config_sobreescribe_valor_anterior(self):
        """Actualizar config sobreescribe el valor previo."""
        svc = StateMapService()
        await svc.update_config("org-1", "hash_v1", "https://s3/v1.signed", "org", None)
        await svc.update_config("org-1", "hash_v2", "https://s3/v2.signed", "org", None)

        state = await svc.get_state("org-1")
        assert state.config_hash == "hash_v2"
        assert state.config_s3_url == "https://s3/v2.signed"

    @pytest.mark.asyncio
    async def test_update_config_scope_desconocido_no_falla(self):
        """Un scope desconocido loguea warning pero no lanza excepción."""
        svc = StateMapService()
        # No debe lanzar excepción
        await svc.update_config("org-1", "hash", "url", "unknown_scope", None)

        state = await svc.get_state("org-1")
        # Se creó la org pero no se actualizó config (scope inválido)
        assert state is not None
        assert state.config_hash is None


class TestUpdateCert:
    """Verificación de update_cert."""

    @pytest.mark.asyncio
    async def test_update_cert_basico(self):
        """Actualiza cert_version y cert_url correctamente."""
        svc = StateMapService()
        await svc.update_cert(
            org_id="org-1",
            cert_version=3,
            cert_url="https://s3/certs/org-1/v3.cer",
        )

        state = await svc.get_state("org-1")
        assert state is not None
        assert state.cert_version == 3
        assert state.cert_url == "https://s3/certs/org-1/v3.cer"

    @pytest.mark.asyncio
    async def test_update_cert_crea_org_si_no_existe(self):
        """Si la org no existe, la crea antes de actualizar cert."""
        svc = StateMapService()
        await svc.update_cert("org-nueva", 1, "https://s3/certs/v1.cer")

        state = await svc.get_state("org-nueva")
        assert state is not None
        assert state.cert_version == 1
        assert state.cert_url == "https://s3/certs/v1.cer"

    @pytest.mark.asyncio
    async def test_update_cert_sobreescribe_version_anterior(self):
        """Rotación de cert sobreescribe la versión anterior."""
        svc = StateMapService()
        await svc.update_cert("org-1", 1, "https://s3/certs/v1.cer")
        await svc.update_cert("org-1", 2, "https://s3/certs/v2.cer")

        state = await svc.get_state("org-1")
        assert state.cert_version == 2
        assert state.cert_url == "https://s3/certs/v2.cer"

    @pytest.mark.asyncio
    async def test_update_cert_no_afecta_config(self):
        """Actualizar cert no modifica los campos de config."""
        svc = StateMapService()
        await svc.update_config("org-1", "hash_cfg", "https://s3/cfg.signed", "org", None)
        await svc.update_cert("org-1", 5, "https://s3/certs/v5.cer")

        state = await svc.get_state("org-1")
        assert state.config_hash == "hash_cfg"
        assert state.cert_version == 5


class TestUpdateMsi:
    """Verificación de update_msi."""

    @pytest.mark.asyncio
    async def test_update_msi_basico(self):
        """Actualiza msi_version, msi_url y msi_url_expires_at."""
        svc = StateMapService()
        await svc.update_msi(
            org_id="org-1",
            msi_version="2.1.0",
            msi_url="https://s3/versions/2.1.0/AlwaysPrint.msi?X-Amz-Expires=3600",
            msi_url_expires_at=1700000000.0,
        )

        state = await svc.get_state("org-1")
        assert state is not None
        assert state.msi_version == "2.1.0"
        assert state.msi_url == "https://s3/versions/2.1.0/AlwaysPrint.msi?X-Amz-Expires=3600"
        assert state.msi_url_expires_at == 1700000000.0

    @pytest.mark.asyncio
    async def test_update_msi_expires_at_default(self):
        """msi_url_expires_at tiene default 0.0 si no se especifica."""
        svc = StateMapService()
        await svc.update_msi("org-1", "1.5.0", "https://s3/msi/1.5.0.msi")

        state = await svc.get_state("org-1")
        assert state.msi_url_expires_at == 0.0

    @pytest.mark.asyncio
    async def test_update_msi_crea_org_si_no_existe(self):
        """Si la org no existe, la crea antes de actualizar MSI."""
        svc = StateMapService()
        await svc.update_msi("org-nueva", "3.0.0", "https://s3/msi/3.0.0.msi", 1800000000.0)

        state = await svc.get_state("org-nueva")
        assert state is not None
        assert state.msi_version == "3.0.0"

    @pytest.mark.asyncio
    async def test_update_msi_sobreescribe_version_anterior(self):
        """Actualizar MSI sobreescribe valores previos."""
        svc = StateMapService()
        await svc.update_msi("org-1", "1.0.0", "https://s3/msi/1.0.0.msi", 1700000000.0)
        await svc.update_msi("org-1", "2.0.0", "https://s3/msi/2.0.0.msi", 1800000000.0)

        state = await svc.get_state("org-1")
        assert state.msi_version == "2.0.0"
        assert state.msi_url == "https://s3/msi/2.0.0.msi"
        assert state.msi_url_expires_at == 1800000000.0

    @pytest.mark.asyncio
    async def test_update_msi_no_afecta_config_ni_cert(self):
        """Actualizar MSI no modifica campos de config ni cert."""
        svc = StateMapService()
        await svc.update_config("org-1", "cfg_hash", "https://s3/cfg.signed", "org", None)
        await svc.update_cert("org-1", 3, "https://s3/certs/v3.cer")
        await svc.update_msi("org-1", "2.5.0", "https://s3/msi/2.5.0.msi", 1900000000.0)

        state = await svc.get_state("org-1")
        assert state.config_hash == "cfg_hash"
        assert state.cert_version == 3
        assert state.msi_version == "2.5.0"


# === Tests para initialize() y _load_org_state() (Task 1.2) ===

from unittest.mock import MagicMock, patch
from collections import namedtuple
import uuid


# Row simulada compatible con acceso por nombre de atributo
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


def _make_db_session_factory(rows):
    """Crea un mock de db_session_factory que retorna filas predefinidas."""
    mock_result = MagicMock()
    mock_result.fetchall.return_value = rows

    mock_session = MagicMock()
    mock_session.execute.return_value = mock_result

    factory = MagicMock(return_value=mock_session)
    return factory, mock_session


class TestInitialize:
    """Verificación de carga inicial desde BD."""

    @pytest.mark.asyncio
    async def test_initialize_sin_orgs(self):
        """Con BD vacía (sin orgs activas), el mapa queda vacío."""
        factory, _ = _make_db_session_factory([])
        svc = StateMapService()

        await svc.initialize(factory)

        assert svc._state == {}
        assert svc._db_session_factory is factory

    @pytest.mark.asyncio
    async def test_initialize_org_sin_action_config(self):
        """Org activa sin action_configs (LEFT JOIN retorna NULLs para ac)."""
        org_id = uuid.uuid4()
        rows = [
            _OrgRow(
                org_id=org_id,
                cert_version=2,
                cert_s3_key="certs/org1/v2.cer",
                msi_version="1.5.0",
                auto_update_enabled=True,
                config_hash=None,
                config_s3_key=None,
                scope=None,
                vlan_id=None,
                workstation_id=None,
            )
        ]
        factory, mock_session = _make_db_session_factory(rows)
        svc = StateMapService()

        await svc.initialize(factory)

        state = svc._state[str(org_id)]
        assert state.cert_version == 2
        assert "certs/org1/v2.cer" in state.cert_url
        assert state.msi_version == "1.5.0"
        assert state.config_hash is None
        assert state.config_s3_url is None
        mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_org_con_config_scope_org(self):
        """Org con una config activa a nivel org."""
        org_id = uuid.uuid4()
        rows = [
            _OrgRow(
                org_id=org_id,
                cert_version=1,
                cert_s3_key=None,
                msi_version=None,
                auto_update_enabled=False,
                config_hash="abc12345",
                config_s3_key="configs/org1/abc12345.signed",
                scope="org",
                vlan_id=None,
                workstation_id=None,
            )
        ]
        factory, _ = _make_db_session_factory(rows)
        svc = StateMapService()

        await svc.initialize(factory)

        state = svc._state[str(org_id)]
        assert state.config_hash == "abc12345"
        assert "configs/org1/abc12345.signed" in state.config_s3_url
        assert state.cert_version == 1
        assert state.cert_url is None  # Sin cert_s3_key

    @pytest.mark.asyncio
    async def test_initialize_multiples_scopes(self):
        """Org con configs en scope org, vlan y workstation."""
        org_id = uuid.uuid4()
        vlan_id = uuid.uuid4()
        ws_id = uuid.uuid4()
        rows = [
            _OrgRow(
                org_id=org_id,
                cert_version=3,
                cert_s3_key="certs/org1/v3.cer",
                msi_version="2.0.0",
                auto_update_enabled=True,
                config_hash="org_hash",
                config_s3_key="configs/org1/org_hash.signed",
                scope="org",
                vlan_id=None,
                workstation_id=None,
            ),
            _OrgRow(
                org_id=org_id,
                cert_version=3,
                cert_s3_key="certs/org1/v3.cer",
                msi_version="2.0.0",
                auto_update_enabled=True,
                config_hash="vlan_hash",
                config_s3_key="configs/org1/vlan_hash.signed",
                scope="vlan",
                vlan_id=vlan_id,
                workstation_id=None,
            ),
            _OrgRow(
                org_id=org_id,
                cert_version=3,
                cert_s3_key="certs/org1/v3.cer",
                msi_version="2.0.0",
                auto_update_enabled=True,
                config_hash="ws_hash",
                config_s3_key="configs/org1/ws_hash.signed",
                scope="workstation",
                vlan_id=None,
                workstation_id=ws_id,
            ),
        ]
        factory, _ = _make_db_session_factory(rows)
        svc = StateMapService()

        await svc.initialize(factory)

        state = svc._state[str(org_id)]
        # Config org level
        assert state.config_hash == "org_hash"
        # VLAN override
        assert str(vlan_id) in state.vlan_configs
        assert state.vlan_configs[str(vlan_id)].config_hash == "vlan_hash"
        # WS override
        assert str(ws_id) in state.ws_configs
        assert state.ws_configs[str(ws_id)].config_hash == "ws_hash"
        # Cert y MSI
        assert state.cert_version == 3
        assert state.msi_version == "2.0.0"

    @pytest.mark.asyncio
    async def test_initialize_multiples_orgs(self):
        """Múltiples orgs activas se cargan correctamente."""
        org1 = uuid.uuid4()
        org2 = uuid.uuid4()
        rows = [
            _OrgRow(
                org_id=org1,
                cert_version=1,
                cert_s3_key="certs/o1/v1.cer",
                msi_version="1.0.0",
                auto_update_enabled=False,
                config_hash="h1",
                config_s3_key="configs/o1/h1.signed",
                scope="org",
                vlan_id=None,
                workstation_id=None,
            ),
            _OrgRow(
                org_id=org2,
                cert_version=5,
                cert_s3_key="certs/o2/v5.cer",
                msi_version="3.0.0",
                auto_update_enabled=True,
                config_hash="h2",
                config_s3_key="configs/o2/h2.signed",
                scope="org",
                vlan_id=None,
                workstation_id=None,
            ),
        ]
        factory, _ = _make_db_session_factory(rows)
        svc = StateMapService()

        await svc.initialize(factory)

        assert len(svc._state) == 2
        assert svc._state[str(org1)].config_hash == "h1"
        assert svc._state[str(org2)].config_hash == "h2"
        assert svc._state[str(org2)].cert_version == 5


class TestLoadOrgState:
    """Verificación de _load_org_state (cache miss individual)."""

    @pytest.mark.asyncio
    async def test_load_org_sin_factory(self):
        """Sin factory configurado retorna None."""
        svc = StateMapService()
        result = await svc._load_org_state(db=None, org_id="org-x")
        assert result is None

    @pytest.mark.asyncio
    async def test_load_org_no_encontrada(self):
        """Org no existe en BD (query retorna vacío)."""
        factory, _ = _make_db_session_factory([])
        svc = StateMapService()
        svc._db_session_factory = factory

        result = await svc._load_org_state(org_id="org-no-existe")
        assert result is None
        # No se almacena en el mapa
        assert "org-no-existe" not in svc._state

    @pytest.mark.asyncio
    async def test_load_org_con_datos(self):
        """Carga org individual correctamente y la almacena en el mapa."""
        org_id = uuid.uuid4()
        rows = [
            _OrgRow(
                org_id=org_id,
                cert_version=4,
                cert_s3_key="certs/org-x/v4.cer",
                msi_version="2.5.0",
                auto_update_enabled=True,
                config_hash="cfg_hash",
                config_s3_key="configs/org-x/cfg_hash.signed",
                scope="org",
                vlan_id=None,
                workstation_id=None,
            )
        ]
        factory, mock_session = _make_db_session_factory(rows)
        svc = StateMapService()
        svc._db_session_factory = factory

        result = await svc._load_org_state(org_id=str(org_id))

        assert result is not None
        assert result.config_hash == "cfg_hash"
        assert result.cert_version == 4
        assert result.msi_version == "2.5.0"
        # Se almacenó en el mapa
        assert str(org_id) in svc._state
        assert svc._state[str(org_id)] is result
        mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_load_org_con_db_proporcionado(self):
        """Usa la sesión proporcionada sin cerrarla (no es su responsabilidad)."""
        org_id = uuid.uuid4()
        rows = [
            _OrgRow(
                org_id=org_id,
                cert_version=1,
                cert_s3_key=None,
                msi_version=None,
                auto_update_enabled=False,
                config_hash=None,
                config_s3_key=None,
                scope=None,
                vlan_id=None,
                workstation_id=None,
            )
        ]
        mock_result = MagicMock()
        mock_result.fetchall.return_value = rows
        mock_db = MagicMock()
        mock_db.execute.return_value = mock_result

        svc = StateMapService()

        result = await svc._load_org_state(db=mock_db, org_id=str(org_id))

        assert result is not None
        assert result.cert_version == 1
        # NO se cierra la sesión proporcionada
        mock_db.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_load_org_con_multiples_scopes(self):
        """Carga org con configs en múltiples scopes."""
        org_id = uuid.uuid4()
        vlan_id = uuid.uuid4()
        rows = [
            _OrgRow(
                org_id=org_id,
                cert_version=2,
                cert_s3_key="certs/org/v2.cer",
                msi_version="1.0.0",
                auto_update_enabled=False,
                config_hash="org_h",
                config_s3_key="configs/org/org_h.signed",
                scope="org",
                vlan_id=None,
                workstation_id=None,
            ),
            _OrgRow(
                org_id=org_id,
                cert_version=2,
                cert_s3_key="certs/org/v2.cer",
                msi_version="1.0.0",
                auto_update_enabled=False,
                config_hash="vlan_h",
                config_s3_key="configs/org/vlan_h.signed",
                scope="vlan",
                vlan_id=vlan_id,
                workstation_id=None,
            ),
        ]
        factory, _ = _make_db_session_factory(rows)
        svc = StateMapService()
        svc._db_session_factory = factory

        result = await svc._load_org_state(org_id=str(org_id))

        assert result.config_hash == "org_h"
        assert str(vlan_id) in result.vlan_configs
        assert result.vlan_configs[str(vlan_id)].config_hash == "vlan_h"


class TestBuildPublicUrl:
    """Verificación de _build_public_url."""

    def test_construye_url_correcta(self):
        """URL sigue el patrón https://{bucket}.s3.{region}.amazonaws.com/{key}."""
        url = StateMapService._build_public_url("configs/org-1/hash.signed")
        assert url.startswith("https://")
        assert ".s3." in url
        assert ".amazonaws.com/" in url
        assert url.endswith("configs/org-1/hash.signed")


# === Tests para Task 1.5: Manejo de errores y resiliencia Redis ===

import json
import time
from unittest.mock import AsyncMock, patch


class TestDetectInconsistency:
    """Verificación de detección de inconsistencias entre workers."""

    def test_inconsistencia_config_org(self, caplog):
        """Loguea ERROR cuando config_hash local difiere del remoto."""
        svc = StateMapService()
        org_state = OrgDistributionState(config_hash="local_hash")

        import logging
        with caplog.at_level(logging.ERROR):
            svc._detect_inconsistency(
                org_id="org-1",
                update_type="config",
                data={"config_hash": "remote_hash", "scope": "org"},
                org_state=org_state,
                origin_worker_id="worker_other",
            )

        assert "inconsistencia_detectada" in caplog.text

    def test_sin_inconsistencia_cuando_local_es_none(self, caplog):
        """No reporta inconsistencia si local es None (primera vez)."""
        svc = StateMapService()
        org_state = OrgDistributionState()  # config_hash es None

        import logging
        with caplog.at_level(logging.ERROR):
            svc._detect_inconsistency(
                org_id="org-1",
                update_type="config",
                data={"config_hash": "remote_hash", "scope": "org"},
                org_state=org_state,
                origin_worker_id="worker_other",
            )

        assert "inconsistencia_detectada" not in caplog.text

    def test_sin_inconsistencia_cuando_valores_iguales(self, caplog):
        """No reporta inconsistencia si local == remoto."""
        svc = StateMapService()
        org_state = OrgDistributionState(config_hash="same_hash")

        import logging
        with caplog.at_level(logging.ERROR):
            svc._detect_inconsistency(
                org_id="org-1",
                update_type="config",
                data={"config_hash": "same_hash", "scope": "org"},
                org_state=org_state,
                origin_worker_id="worker_other",
            )

        assert "inconsistencia_detectada" not in caplog.text

    def test_inconsistencia_cert_version(self, caplog):
        """Loguea ERROR cuando cert_version local difiere del remoto."""
        svc = StateMapService()
        org_state = OrgDistributionState(cert_version=2)

        import logging
        with caplog.at_level(logging.ERROR):
            svc._detect_inconsistency(
                org_id="org-1",
                update_type="cert",
                data={"cert_version": 3, "cert_url": "https://s3/cert.cer"},
                org_state=org_state,
                origin_worker_id="worker_other",
            )

        assert "inconsistencia_detectada" in caplog.text

    def test_inconsistencia_msi_version(self, caplog):
        """Loguea ERROR cuando msi_version local difiere del remoto."""
        svc = StateMapService()
        org_state = OrgDistributionState(msi_version="1.0.0")

        import logging
        with caplog.at_level(logging.ERROR):
            svc._detect_inconsistency(
                org_id="org-1",
                update_type="msi",
                data={"msi_version": "2.0.0", "msi_url": "https://s3/msi.msi"},
                org_state=org_state,
                origin_worker_id="worker_other",
            )

        assert "inconsistencia_detectada" in caplog.text

    def test_inconsistencia_config_vlan(self, caplog):
        """Detecta inconsistencia a nivel VLAN."""
        svc = StateMapService()
        org_state = OrgDistributionState(
            vlan_configs={"vlan-1": VlanConfigState("local_vlan_hash", "https://s3/local.signed")}
        )

        import logging
        with caplog.at_level(logging.ERROR):
            svc._detect_inconsistency(
                org_id="org-1",
                update_type="config",
                data={"config_hash": "remote_vlan_hash", "scope": "vlan", "scope_id": "vlan-1"},
                org_state=org_state,
                origin_worker_id="worker_other",
            )

        assert "inconsistencia_detectada" in caplog.text


class TestPublishUpdateResilience:
    """Verificación de resiliencia en _publish_update."""

    @pytest.mark.asyncio
    async def test_publish_sin_redis_no_falla(self):
        """Si Redis es None, _publish_update retorna sin error."""
        svc = StateMapService()
        svc._redis = None
        svc._redis_available = False

        # No debe lanzar excepción
        await svc._publish_update("org-1", "config", {"config_hash": "abc"})

    @pytest.mark.asyncio
    async def test_publish_con_redis_disponible(self):
        """Si Redis está disponible, publica el mensaje correctamente."""
        svc = StateMapService()
        svc._redis = AsyncMock()
        svc._redis_available = True

        await svc._publish_update("org-1", "config", {"config_hash": "abc"})

        svc._redis.publish.assert_called_once()
        call_args = svc._redis.publish.call_args
        assert call_args[0][0] == "state_map:update"
        payload = json.loads(call_args[0][1])
        assert payload["org_id"] == "org-1"
        assert payload["update_type"] == "config"
        assert payload["data"]["config_hash"] == "abc"

    @pytest.mark.asyncio
    async def test_publish_connection_error_loguea_warning(self, caplog):
        """Si Redis lanza ConnectionError, loguea warning y no propaga."""
        import redis.asyncio as aioredis
        import logging

        svc = StateMapService()
        svc._redis = AsyncMock()
        svc._redis.publish.side_effect = aioredis.ConnectionError("Connection refused")
        svc._redis_available = True

        with caplog.at_level(logging.WARNING):
            await svc._publish_update("org-1", "config", {"config_hash": "abc"})

        assert "publish_fallido" in caplog.text


class TestOnRedisMessageWithInconsistency:
    """Verificación de _on_redis_message con detección de inconsistencias."""

    @pytest.mark.asyncio
    async def test_aplica_update_remoto_despues_de_detectar_inconsistencia(self, caplog):
        """El valor remoto se aplica incluso cuando hay inconsistencia."""
        import logging

        svc = StateMapService()
        svc._worker_id = "worker_local"
        svc._state["org-1"] = OrgDistributionState(config_hash="local_hash")

        message = {
            "type": "message",
            "data": json.dumps({
                "origin_worker_id": "worker_remote",
                "org_id": "org-1",
                "update_type": "config",
                "data": {
                    "config_hash": "remote_hash",
                    "config_s3_url": "https://s3/remote.signed",
                    "scope": "org",
                    "scope_id": None,
                },
            }),
        }

        with caplog.at_level(logging.ERROR):
            await svc._on_redis_message(message)

        # Inconsistencia detectada
        assert "inconsistencia_detectada" in caplog.text
        # Pero el valor remoto se aplicó (remote wins)
        assert svc._state["org-1"].config_hash == "remote_hash"
        assert svc._state["org-1"].config_s3_url == "https://s3/remote.signed"

    @pytest.mark.asyncio
    async def test_ignora_mensaje_propio(self):
        """No procesa mensajes del mismo worker."""
        svc = StateMapService()
        svc._worker_id = "worker_local"
        svc._state["org-1"] = OrgDistributionState(config_hash="original")

        message = {
            "type": "message",
            "data": json.dumps({
                "origin_worker_id": "worker_local",  # Mismo worker
                "org_id": "org-1",
                "update_type": "config",
                "data": {"config_hash": "should_not_apply", "scope": "org"},
            }),
        }

        await svc._on_redis_message(message)

        # No se modificó
        assert svc._state["org-1"].config_hash == "original"


class TestMsiUrlRefresh:
    """Verificación de regeneración de presigned URL de MSI."""

    @pytest.mark.asyncio
    async def test_url_valida_no_regenera(self):
        """Si la URL no está por expirar, no se regenera."""
        svc = StateMapService()
        org_state = OrgDistributionState(
            msi_version="1.0.0",
            msi_url="https://s3/original.msi",
            msi_url_expires_at=time.time() + 3600,  # 1 hora en el futuro
        )

        result = await svc._check_msi_url_expiration("org-1", org_state)
        assert result == "https://s3/original.msi"

    @pytest.mark.asyncio
    async def test_url_expirada_regenera(self):
        """Si la URL ya expiró, regenera usando S3UpdateService."""
        svc = StateMapService()
        org_state = OrgDistributionState(
            msi_version="1.0.0",
            msi_url="https://s3/expired.msi",
            msi_url_expires_at=time.time() - 100,  # Ya expirada
        )

        mock_s3_service = MagicMock()
        mock_s3_service.generate_download_url.return_value = "https://s3/new_presigned.msi"
        svc._s3_update_service = mock_s3_service

        result = await svc._check_msi_url_expiration("org-1", org_state)

        assert result == "https://s3/new_presigned.msi"
        assert org_state.msi_url == "https://s3/new_presigned.msi"
        assert org_state.msi_url_expires_at > time.time()
        mock_s3_service.generate_download_url.assert_called_once_with(
            key="versions/1.0.0/AlwaysPrint.msi",
            expires_in=3600,
        )

    @pytest.mark.asyncio
    async def test_url_cerca_de_expirar_regenera(self):
        """Si la URL expira en menos de 5 minutos, regenera."""
        svc = StateMapService()
        org_state = OrgDistributionState(
            msi_version="2.0.0",
            msi_url="https://s3/almost_expired.msi",
            msi_url_expires_at=time.time() + 200,  # Solo 200 segundos (< 300 threshold)
        )

        mock_s3_service = MagicMock()
        mock_s3_service.generate_download_url.return_value = "https://s3/refreshed.msi"
        svc._s3_update_service = mock_s3_service

        result = await svc._check_msi_url_expiration("org-1", org_state)

        assert result == "https://s3/refreshed.msi"

    @pytest.mark.asyncio
    async def test_regeneracion_falla_retorna_url_actual(self, caplog):
        """Si la regeneración falla, retorna la URL actual y loguea warning."""
        import logging

        svc = StateMapService()
        org_state = OrgDistributionState(
            msi_version="1.0.0",
            msi_url="https://s3/expired_but_only_option.msi",
            msi_url_expires_at=time.time() - 100,
        )

        mock_s3_service = MagicMock()
        mock_s3_service.generate_download_url.side_effect = Exception("S3 error")
        svc._s3_update_service = mock_s3_service

        with caplog.at_level(logging.WARNING):
            result = await svc._check_msi_url_expiration("org-1", org_state)

        assert result == "https://s3/expired_but_only_option.msi"
        assert "msi_url_regeneracion_fallida" in caplog.text

    @pytest.mark.asyncio
    async def test_sin_msi_url_retorna_none(self):
        """Si no hay msi_url, retorna None."""
        svc = StateMapService()
        org_state = OrgDistributionState(msi_version="1.0.0", msi_url=None)

        result = await svc._check_msi_url_expiration("org-1", org_state)
        assert result is None

    @pytest.mark.asyncio
    async def test_resolve_workstation_state_regenera_msi_url_expirada(self):
        """resolve_workstation_state regenera MSI URL si está por expirar."""
        svc = StateMapService()
        svc._state["org-1"] = OrgDistributionState(
            config_hash="hash",
            config_s3_url="https://s3/config.signed",
            cert_version=1,
            cert_url="https://s3/cert.cer",
            msi_version="1.0.0",
            msi_url="https://s3/expired.msi",
            msi_url_expires_at=time.time() - 100,  # Ya expirada
        )

        mock_s3_service = MagicMock()
        mock_s3_service.generate_download_url.return_value = "https://s3/regenerated.msi"
        svc._s3_update_service = mock_s3_service

        result = await svc.resolve_workstation_state("org-1", None, "ws-1")

        assert result["msi_url"] == "https://s3/regenerated.msi"
        assert result["config_hash"] == "hash"
