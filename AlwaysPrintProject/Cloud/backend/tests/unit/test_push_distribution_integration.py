"""
Tests unitarios de integración para push-based distribution.

Cubre escenarios de integración entre StateMapService, PushDistributionService
y el flujo de registration enrichment:

1. Registration enrichment con state map vacío (fallback a BD)
2. Registration enrichment con state map poblado (zero queries)
3. Redis desconectado durante publish (graceful fallback)
4. Presigned URL refresh cuando está por expirar
5. Scope resolution: org < vlan < workstation priority

Requirements: 5.3, 8.3, 1.6
"""

import time
import uuid
from collections import namedtuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.state_map_service import (
    OrgDistributionState,
    StateMapService,
    VlanConfigState,
    WsConfigState,
)


# Row simulada para queries de BD (misma estructura que _load_org_state)
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


# ============================================================================
# TEST 1: Registration enrichment con state map vacío (fallback a BD)
# ============================================================================


class TestRegistrationEnrichmentEmptyStateMap:
    """
    Verifica que cuando el state map no tiene datos para una org,
    se carga desde BD (1 sola query) y luego resolve_workstation_state
    retorna los datos correctos.

    Requirement: 5.3, 9.3
    """

    @pytest.mark.asyncio
    async def test_fallback_a_bd_con_state_map_vacio(self):
        """
        State map vacío para una org → _load_org_state se invoca (mock BD)
        → después resolve_workstation_state retorna datos correctos.
        Verifica que solo se hace 1 query a BD.
        """
        org_id = str(uuid.uuid4())
        # Simular filas de BD para la org
        rows = [
            _OrgRow(
                org_id=org_id,
                cert_version=3,
                cert_s3_key="certs/org/v3.cer",
                msi_version="2.0.0",
                auto_update_enabled=True,
                config_hash="abc12345",
                config_s3_key="configs/org/abc12345.signed",
                scope="org",
                vlan_id=None,
                workstation_id=None,
            )
        ]
        factory, mock_session = _make_db_session_factory(rows)

        svc = StateMapService()
        svc._db_session_factory = factory

        # Verificar que el state map está vacío
        state = await svc.get_state(org_id)
        assert state is None

        # Simular el flujo de registration enrichment: cargar desde BD
        loaded = await svc._load_org_state(org_id=org_id)
        assert loaded is not None

        # Ahora resolve_workstation_state retorna datos correctos
        result = await svc.resolve_workstation_state(org_id, None, "ws-1")
        assert result["config_hash"] == "abc12345"
        assert result["cert_version"] == 3
        assert result["msi_version"] == "2.0.0"
        assert "configs/org/abc12345.signed" in result["config_s3_url"]
        assert "certs/org/v3.cer" in result["cert_url"]

        # Verificar que solo se hizo 1 query a BD
        assert mock_session.execute.call_count == 1
        mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_segunda_ws_misma_org_no_hace_query(self):
        """
        Después del primer load, una segunda workstation de la misma org
        NO hace query a BD (los datos ya están en el state map).
        """
        org_id = str(uuid.uuid4())
        rows = [
            _OrgRow(
                org_id=org_id,
                cert_version=2,
                cert_s3_key="certs/org/v2.cer",
                msi_version="1.5.0",
                auto_update_enabled=True,
                config_hash="hash_org",
                config_s3_key="configs/org/hash_org.signed",
                scope="org",
                vlan_id=None,
                workstation_id=None,
            )
        ]
        factory, mock_session = _make_db_session_factory(rows)

        svc = StateMapService()
        svc._db_session_factory = factory

        # Primera WS carga desde BD
        await svc._load_org_state(org_id=org_id)
        assert mock_session.execute.call_count == 1

        # Segunda WS ya tiene datos en el mapa (0 queries adicionales)
        state = await svc.get_state(org_id)
        assert state is not None
        result = await svc.resolve_workstation_state(org_id, None, "ws-2")
        assert result["config_hash"] == "hash_org"

        # Sigue siendo solo 1 query total
        assert mock_session.execute.call_count == 1


# ============================================================================
# TEST 2: Registration enrichment con state map poblado (zero queries)
# ============================================================================


class TestRegistrationEnrichmentPopulatedStateMap:
    """
    Verifica que cuando el state map ya tiene datos de la org,
    resolve_workstation_state retorna los datos sin hacer ninguna query a BD.

    Requirement: 9.2
    """

    @pytest.mark.asyncio
    async def test_zero_queries_con_state_map_poblado(self):
        """
        Pre-poblar state map con datos → resolve_workstation_state retorna
        datos correctos sin invocar BD.
        """
        org_id = str(uuid.uuid4())

        svc = StateMapService()
        # Pre-poblar el state map directamente (simula initialize() exitoso)
        svc._state[org_id] = OrgDistributionState(
            config_hash="prepopulated_hash",
            config_s3_url="https://s3/configs/prepopulated.signed",
            cert_version=5,
            cert_url="https://s3/certs/v5.cer",
            msi_version="3.0.0",
            msi_url="https://s3/msi/3.0.0.msi?presigned",
            msi_url_expires_at=time.time() + 3600,  # 1 hora de margen
        )

        # Configurar factory que NUNCA debería ser llamado
        mock_factory = MagicMock()
        svc._db_session_factory = mock_factory

        # Resolver estado de workstation
        result = await svc.resolve_workstation_state(org_id, None, "ws-any")

        # Datos correctos del state map
        assert result["config_hash"] == "prepopulated_hash"
        assert result["config_s3_url"] == "https://s3/configs/prepopulated.signed"
        assert result["cert_version"] == 5
        assert result["cert_url"] == "https://s3/certs/v5.cer"
        assert result["msi_version"] == "3.0.0"
        assert result["msi_url"] == "https://s3/msi/3.0.0.msi?presigned"

        # Verificar 0 queries a BD
        mock_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_zero_queries_multiples_workstations(self):
        """
        Múltiples workstations consultan resolve_workstation_state
        para la misma org sin generar queries a BD.
        """
        org_id = str(uuid.uuid4())

        svc = StateMapService()
        svc._state[org_id] = OrgDistributionState(
            config_hash="shared_hash",
            config_s3_url="https://s3/shared.signed",
            cert_version=2,
            cert_url="https://s3/certs/v2.cer",
            msi_version="1.0.0",
            msi_url="https://s3/msi/1.0.msi?signed",
            msi_url_expires_at=time.time() + 3600,
        )

        mock_factory = MagicMock()
        svc._db_session_factory = mock_factory

        # 10 workstations consultan sin hacer queries
        for i in range(10):
            result = await svc.resolve_workstation_state(org_id, None, f"ws-{i}")
            assert result["config_hash"] == "shared_hash"

        # 0 queries a BD en total
        mock_factory.assert_not_called()


# ============================================================================
# TEST 3: Redis desconectado durante publish (graceful fallback)
# ============================================================================


class TestRedisDisconnectedGracefulFallback:
    """
    Verifica que cuando Redis no está disponible, las operaciones de
    actualización del state map continúan sin excepción y el estado
    local queda correcto.

    Requirement: 8.3
    """

    @pytest.mark.asyncio
    async def test_update_config_con_redis_no_disponible(self):
        """
        _redis_available = False → update_config actualiza el state map local
        sin excepción y sin intentar publicar.
        """
        svc = StateMapService(redis_url="redis://localhost:6379/0")
        svc._redis = AsyncMock()
        svc._redis_available = False  # Redis caído

        # update_config no debe lanzar excepción
        await svc.update_config(
            org_id="org-1",
            config_hash="new_hash",
            config_s3_url="https://s3/new.signed",
            scope="org",
            scope_id=None,
        )

        # Estado local actualizado correctamente
        state = await svc.get_state("org-1")
        assert state is not None
        assert state.config_hash == "new_hash"
        assert state.config_s3_url == "https://s3/new.signed"

        # No se intentó publicar a Redis
        svc._redis.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_cert_con_redis_connection_error(self):
        """
        Redis.publish lanza ConnectionError → update_cert no falla,
        estado local queda correcto, se loguea warning.
        """
        import redis.asyncio as aioredis

        svc = StateMapService(redis_url="redis://localhost:6379/0")
        svc._redis = AsyncMock()
        svc._redis_available = True
        svc._redis.publish.side_effect = aioredis.ConnectionError("Conexión perdida")

        # No debe lanzar excepción
        await svc.update_cert(
            org_id="org-1",
            cert_version=7,
            cert_url="https://s3/certs/v7.cer",
        )

        # Estado local correcto a pesar del error Redis
        state = await svc.get_state("org-1")
        assert state is not None
        assert state.cert_version == 7
        assert state.cert_url == "https://s3/certs/v7.cer"

    @pytest.mark.asyncio
    async def test_update_msi_con_redis_timeout(self):
        """
        Redis.publish lanza TimeoutError → update_msi no falla,
        estado local queda correcto.
        """
        import redis.asyncio as aioredis

        svc = StateMapService(redis_url="redis://localhost:6379/0")
        svc._redis = AsyncMock()
        svc._redis_available = True
        svc._redis.publish.side_effect = aioredis.TimeoutError("Timeout")

        # No debe lanzar excepción
        await svc.update_msi(
            org_id="org-1",
            msi_version="4.0.0",
            msi_url="https://s3/msi/4.0.msi?signed",
            msi_url_expires_at=1900000000.0,
        )

        # Estado local correcto
        state = await svc.get_state("org-1")
        assert state.msi_version == "4.0.0"
        assert state.msi_url == "https://s3/msi/4.0.msi?signed"
        assert state.msi_url_expires_at == 1900000000.0

    @pytest.mark.asyncio
    async def test_multiples_updates_con_redis_caido(self):
        """
        Secuencia de updates (config + cert + MSI) con Redis caído:
        todos se aplican localmente sin excepción.
        """
        svc = StateMapService(redis_url="redis://localhost:6379/0")
        svc._redis = AsyncMock()
        svc._redis_available = False

        await svc.update_config("org-1", "h1", "https://s3/h1.signed", "org", None)
        await svc.update_cert("org-1", 3, "https://s3/certs/v3.cer")
        await svc.update_msi("org-1", "2.0.0", "https://s3/msi/2.0.msi", 1800000000.0)

        state = await svc.get_state("org-1")
        assert state.config_hash == "h1"
        assert state.cert_version == 3
        assert state.msi_version == "2.0.0"

        # Ningún intento de publicar
        svc._redis.publish.assert_not_called()


# ============================================================================
# TEST 4: Presigned URL refresh cuando está por expirar
# ============================================================================


class TestPresignedUrlRefresh:
    """
    Verifica que _check_msi_url_expiration regenera la presigned URL
    cuando está dentro del threshold de 5 minutos (300s).

    Requirement: 8.3 (resiliencia), implícito en flujo de distribución
    """

    @pytest.mark.asyncio
    async def test_url_por_expirar_se_regenera(self):
        """
        msi_url_expires_at = time.time() + 100 (< 300 threshold)
        → _check_msi_url_expiration genera nueva URL via S3UpdateService.
        """
        org_id = "org-1"
        svc = StateMapService()
        svc._state[org_id] = OrgDistributionState(
            msi_version="2.0.0",
            msi_url="https://s3/old-presigned-url?expired-soon",
            msi_url_expires_at=time.time() + 100,  # Menos de 300s → expirar
        )

        # Mock del S3UpdateService
        mock_s3_service = MagicMock()
        mock_s3_service.generate_download_url.return_value = (
            "https://s3/new-presigned-url?fresh"
        )
        svc._s3_update_service = mock_s3_service

        # Llamar resolve_workstation_state que invoca _check_msi_url_expiration
        result = await svc.resolve_workstation_state(org_id, None, "ws-1")

        # URL regenerada
        assert result["msi_url"] == "https://s3/new-presigned-url?fresh"
        # S3UpdateService fue invocado con la key correcta
        mock_s3_service.generate_download_url.assert_called_once_with(
            key="versions/2.0.0/AlwaysPrint.msi",
            expires_in=3600,
        )
        # El state map se actualizó con la nueva URL y expiración
        state = svc._state[org_id]
        assert state.msi_url == "https://s3/new-presigned-url?fresh"
        assert state.msi_url_expires_at > time.time() + 3500  # ~1 hora

    @pytest.mark.asyncio
    async def test_url_valida_no_se_regenera(self):
        """
        msi_url_expires_at = time.time() + 3600 (> 300 threshold)
        → no se regenera la URL, se retorna la existente.
        """
        org_id = "org-1"
        original_url = "https://s3/still-valid-url?not-expired"
        svc = StateMapService()
        svc._state[org_id] = OrgDistributionState(
            msi_version="2.0.0",
            msi_url=original_url,
            msi_url_expires_at=time.time() + 3600,  # Mucho margen
        )

        mock_s3_service = MagicMock()
        svc._s3_update_service = mock_s3_service

        result = await svc.resolve_workstation_state(org_id, None, "ws-1")

        # URL original sin cambios
        assert result["msi_url"] == original_url
        # S3UpdateService NO fue invocado
        mock_s3_service.generate_download_url.assert_not_called()

    @pytest.mark.asyncio
    async def test_regeneracion_fallida_retorna_url_actual(self):
        """
        Si la regeneración falla (S3 error), retorna la URL actual
        (posiblemente expirada) sin lanzar excepción.
        """
        org_id = "org-1"
        old_url = "https://s3/expired-url?old"
        svc = StateMapService()
        svc._state[org_id] = OrgDistributionState(
            msi_version="2.0.0",
            msi_url=old_url,
            msi_url_expires_at=time.time() + 50,  # Muy cerca de expirar
        )

        # S3UpdateService falla
        mock_s3_service = MagicMock()
        mock_s3_service.generate_download_url.side_effect = Exception(
            "S3 no disponible"
        )
        svc._s3_update_service = mock_s3_service

        # No debe lanzar excepción
        result = await svc.resolve_workstation_state(org_id, None, "ws-1")

        # Retorna la URL actual (fallback graceful)
        assert result["msi_url"] == old_url

    @pytest.mark.asyncio
    async def test_url_ya_expirada_intenta_regenerar(self):
        """
        msi_url_expires_at en el pasado → también intenta regenerar.
        """
        org_id = "org-1"
        svc = StateMapService()
        svc._state[org_id] = OrgDistributionState(
            msi_version="1.5.0",
            msi_url="https://s3/already-expired?old",
            msi_url_expires_at=time.time() - 600,  # Ya expiró hace 10 min
        )

        mock_s3_service = MagicMock()
        mock_s3_service.generate_download_url.return_value = (
            "https://s3/fresh-url?regenerated"
        )
        svc._s3_update_service = mock_s3_service

        result = await svc.resolve_workstation_state(org_id, None, "ws-1")

        assert result["msi_url"] == "https://s3/fresh-url?regenerated"
        mock_s3_service.generate_download_url.assert_called_once()


# ============================================================================
# TEST 5: Scope resolution: org < vlan < workstation priority
# ============================================================================


class TestScopeResolutionPriority:
    """
    Verifica la resolución jerárquica completa de scope:
    - workstation override > vlan override > org default

    Requirement: 1.6
    """

    @pytest.mark.asyncio
    async def test_ws_matching_retorna_config_ws(self):
        """
        State map con configs en los 3 scopes → workstation que matchea
        ws_configs recibe la config de workstation (más específica).
        """
        org_id = str(uuid.uuid4())
        svc = StateMapService()
        svc._state[org_id] = OrgDistributionState(
            config_hash="org_hash",
            config_s3_url="https://s3/org.signed",
            cert_version=1,
            cert_url="https://s3/certs/v1.cer",
            msi_version="1.0.0",
            msi_url="https://s3/msi.msi?signed",
            msi_url_expires_at=time.time() + 3600,
            vlan_configs={
                "vlan-A": VlanConfigState("vlan_hash", "https://s3/vlan.signed"),
            },
            ws_configs={
                "ws-42": WsConfigState("ws_hash", "https://s3/ws42.signed"),
            },
        )

        # ws-42 matchea ws_configs → recibe config de workstation
        result = await svc.resolve_workstation_state(org_id, "vlan-A", "ws-42")
        assert result["config_hash"] == "ws_hash"
        assert result["config_s3_url"] == "https://s3/ws42.signed"
        # Cert y MSI siempre a nivel org
        assert result["cert_version"] == 1
        assert result["msi_version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_vlan_matching_sin_ws_override(self):
        """
        Workstation NO matchea ws_configs pero SÍ matchea vlan_configs
        → recibe config de VLAN.
        """
        org_id = str(uuid.uuid4())
        svc = StateMapService()
        svc._state[org_id] = OrgDistributionState(
            config_hash="org_hash",
            config_s3_url="https://s3/org.signed",
            cert_version=2,
            cert_url="https://s3/certs/v2.cer",
            msi_version="2.0.0",
            msi_url="https://s3/msi2.msi?signed",
            msi_url_expires_at=time.time() + 3600,
            vlan_configs={
                "vlan-A": VlanConfigState("vlan_hash", "https://s3/vlan.signed"),
                "vlan-B": VlanConfigState("vlan_b_hash", "https://s3/vlan_b.signed"),
            },
            ws_configs={
                "ws-42": WsConfigState("ws_hash", "https://s3/ws42.signed"),
            },
        )

        # ws-99 NO matchea ws_configs, pero está en vlan-A → recibe config vlan
        result = await svc.resolve_workstation_state(org_id, "vlan-A", "ws-99")
        assert result["config_hash"] == "vlan_hash"
        assert result["config_s3_url"] == "https://s3/vlan.signed"
        assert result["cert_version"] == 2
        assert result["msi_version"] == "2.0.0"

    @pytest.mark.asyncio
    async def test_sin_matches_retorna_org_config(self):
        """
        Workstation NO matchea ws_configs NI vlan_configs
        → recibe config a nivel org (default).
        """
        org_id = str(uuid.uuid4())
        svc = StateMapService()
        svc._state[org_id] = OrgDistributionState(
            config_hash="org_hash",
            config_s3_url="https://s3/org.signed",
            cert_version=3,
            cert_url="https://s3/certs/v3.cer",
            msi_version="3.0.0",
            msi_url="https://s3/msi3.msi?signed",
            msi_url_expires_at=time.time() + 3600,
            vlan_configs={
                "vlan-A": VlanConfigState("vlan_hash", "https://s3/vlan.signed"),
            },
            ws_configs={
                "ws-42": WsConfigState("ws_hash", "https://s3/ws42.signed"),
            },
        )

        # ws-100 en vlan-X → no matchea nada → config org
        result = await svc.resolve_workstation_state(org_id, "vlan-X", "ws-100")
        assert result["config_hash"] == "org_hash"
        assert result["config_s3_url"] == "https://s3/org.signed"
        assert result["cert_version"] == 3
        assert result["msi_version"] == "3.0.0"

    @pytest.mark.asyncio
    async def test_ws_override_prevalece_sobre_vlan(self):
        """
        Cuando ws_id matchea ws_configs Y vlan_id matchea vlan_configs,
        workstation gana (más específico).
        """
        org_id = str(uuid.uuid4())
        svc = StateMapService()
        svc._state[org_id] = OrgDistributionState(
            config_hash="org_hash",
            config_s3_url="https://s3/org.signed",
            cert_version=1,
            cert_url="https://s3/certs/v1.cer",
            vlan_configs={
                "vlan-A": VlanConfigState("vlan_hash", "https://s3/vlan.signed"),
            },
            ws_configs={
                "ws-1": WsConfigState("ws_specific", "https://s3/ws1.signed"),
            },
        )

        # ws-1 está en vlan-A pero tiene override de workstation
        result = await svc.resolve_workstation_state(org_id, "vlan-A", "ws-1")
        assert result["config_hash"] == "ws_specific"
        assert result["config_s3_url"] == "https://s3/ws1.signed"

    @pytest.mark.asyncio
    async def test_cert_y_msi_siempre_nivel_org(self):
        """
        Cert y MSI siempre se toman a nivel org, independientemente
        del scope de la config.
        """
        org_id = str(uuid.uuid4())
        svc = StateMapService()
        svc._state[org_id] = OrgDistributionState(
            config_hash="org_hash",
            config_s3_url="https://s3/org.signed",
            cert_version=10,
            cert_url="https://s3/certs/v10.cer",
            msi_version="5.0.0",
            msi_url="https://s3/msi5.msi?signed",
            msi_url_expires_at=time.time() + 3600,
            ws_configs={
                "ws-special": WsConfigState("ws_cfg", "https://s3/ws.signed"),
            },
        )

        # Aunque la config viene de ws, cert y MSI son de org
        result = await svc.resolve_workstation_state(org_id, None, "ws-special")
        assert result["config_hash"] == "ws_cfg"  # De workstation
        assert result["cert_version"] == 10  # De org
        assert result["cert_url"] == "https://s3/certs/v10.cer"  # De org
        assert result["msi_version"] == "5.0.0"  # De org

    @pytest.mark.asyncio
    async def test_vlan_none_no_aplica_override(self):
        """
        Si vlan_id es None, no se intenta resolver override de VLAN
        (solo org y workstation aplican).
        """
        org_id = str(uuid.uuid4())
        svc = StateMapService()
        svc._state[org_id] = OrgDistributionState(
            config_hash="org_hash",
            config_s3_url="https://s3/org.signed",
            cert_version=1,
            cert_url="https://s3/certs/v1.cer",
            vlan_configs={
                "vlan-A": VlanConfigState("vlan_hash", "https://s3/vlan.signed"),
            },
        )

        # vlan_id=None → no aplica override de VLAN → config org
        result = await svc.resolve_workstation_state(org_id, None, "ws-99")
        assert result["config_hash"] == "org_hash"
