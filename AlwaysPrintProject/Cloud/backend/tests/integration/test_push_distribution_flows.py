"""
Tests de integración del flujo push-based distribution.

Verifica los flujos completos de:
1. Admin activa config → state map update → Redis publish → push to WS
2. Registro WS → registration enrichment con datos correctos
3. Multi-worker: cambio en worker 1 visible en worker 2 vía Redis
4. Fallback: legacy endpoints siguen funcionando durante transición

Todos los tests mockean dependencias externas (Redis, DB, WebSocket)
pero validan la integración entre componentes internos.

**Validates: Requirements 2.1, 5.1, 8.1, 7.4**
"""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.state_map_service import (
    StateMapService,
    OrgDistributionState,
    VlanConfigState,
    WsConfigState,
)
from app.services.push_distribution_service import PushDistributionService


# === FIXTURES ===


@pytest.fixture
def org_id():
    """UUID de organización para los tests."""
    return str(uuid.uuid4())


@pytest.fixture
def ws_id():
    """UUID de workstation para los tests."""
    return str(uuid.uuid4())


@pytest.fixture
def vlan_id():
    """UUID de VLAN para los tests."""
    return str(uuid.uuid4())


@pytest.fixture
def state_map_service():
    """StateMapService sin Redis (modo single-worker para tests)."""
    return StateMapService(redis_url=None)


@pytest.fixture
def mock_connection_manager(org_id, ws_id):
    """ConnectionManager mock con una workstation online."""
    cm = MagicMock()
    cm.org_ids = {ws_id: org_id}
    cm.workstation_connections = {ws_id: MagicMock()}
    cm.is_workstation_online = MagicMock(return_value=True)
    cm.send_to_workstation = AsyncMock(return_value=True)
    return cm


@pytest.fixture
def push_service(state_map_service, mock_connection_manager):
    """PushDistributionService con dependencias mockeadas."""
    return PushDistributionService(
        connection_manager=mock_connection_manager,
        state_map_service=state_map_service,
    )


# === TEST 1: FLUJO COMPLETO ADMIN → STATE MAP → REDIS → PUSH WS ===


class TestFlujoCompletoActivacionConfig:
    """
    Test de integración del flujo completo de activación de config.

    Simula: admin activa config → state map update → Redis publish → push to WS.
    Validates: Requirement 2.1
    """

    @pytest.mark.asyncio
    async def test_flujo_completo_config_activation(
        self, state_map_service, push_service, mock_connection_manager, org_id, ws_id
    ):
        """
        WHEN un admin activa una configuración,
        THEN el state map se actualiza, Redis publica, y se envía push a WS online.
        """
        config_hash = "a1b2c3d4"
        config_s3_url = f"https://bucket.s3.us-east-1.amazonaws.com/configs/{org_id}/{config_hash}.signed"

        # 1. Actualizar state map (simula lo que hace _push_config_activation)
        await state_map_service.update_config(
            org_id=org_id,
            config_hash=config_hash,
            config_s3_url=config_s3_url,
            scope="org",
            scope_id=None,
        )

        # Verificar que el state map se actualizó correctamente
        org_state = await state_map_service.get_state(org_id)
        assert org_state is not None
        assert org_state.config_hash == config_hash
        assert org_state.config_s3_url == config_s3_url

        # 2. Push a workstations online
        enviados = await push_service.push_config_change(
            org_id=org_id,
            config_hash=config_hash,
            download_url=config_s3_url,
            scope="org",
            scope_id=None,
        )

        # Verificar que se envió el mensaje a la workstation
        assert enviados == 1
        mock_connection_manager.send_to_workstation.assert_called_once()

        # Verificar contenido del mensaje enviado
        call_args = mock_connection_manager.send_to_workstation.call_args
        sent_ws_id = call_args[0][0]
        sent_message = call_args[0][1]

        assert sent_ws_id == ws_id
        assert sent_message["type"] == "action_config_changed"
        assert sent_message["config_hash"] == config_hash
        assert sent_message["download_url"] == config_s3_url

    @pytest.mark.asyncio
    async def test_flujo_completo_con_redis_publish(self, org_id, ws_id):
        """
        WHEN un admin activa una config con Redis disponible,
        THEN se publica el cambio en el canal state_map:update.
        """
        # Crear StateMapService con Redis mockeado
        state_map = StateMapService(redis_url="redis://fake:6379/0")
        state_map._redis = AsyncMock()
        state_map._redis.ping = AsyncMock()
        state_map._redis.publish = AsyncMock(return_value=1)
        state_map._redis_available = True

        config_hash = "dead1234"
        config_s3_url = f"https://bucket.s3.us-east-1.amazonaws.com/configs/{org_id}/{config_hash}.signed"

        # Ejecutar actualización (esto publica a Redis internamente)
        await state_map.update_config(
            org_id=org_id,
            config_hash=config_hash,
            config_s3_url=config_s3_url,
            scope="org",
            scope_id=None,
        )

        # Verificar que se publicó en Redis
        state_map._redis.publish.assert_called_once()
        call_args = state_map._redis.publish.call_args[0]
        canal = call_args[0]
        payload_json = call_args[1]

        assert canal == "state_map:update"

        # Verificar payload publicado
        payload = json.loads(payload_json)
        assert payload["org_id"] == org_id
        assert payload["update_type"] == "config"
        assert payload["data"]["config_hash"] == config_hash
        assert payload["data"]["config_s3_url"] == config_s3_url
        assert payload["data"]["scope"] == "org"
        assert payload["data"]["scope_id"] is None
        assert "origin_worker_id" in payload

    @pytest.mark.asyncio
    async def test_flujo_completo_multiple_workstations(self, org_id):
        """
        WHEN hay 3 workstations online y se activa una config a nivel org,
        THEN las 3 reciben el push message.
        """
        ws_ids = [str(uuid.uuid4()) for _ in range(3)]

        # ConnectionManager con 3 workstations online de la misma org
        cm = MagicMock()
        cm.org_ids = {ws_id: org_id for ws_id in ws_ids}
        cm.workstation_connections = {ws_id: MagicMock() for ws_id in ws_ids}
        cm.send_to_workstation = AsyncMock(return_value=True)

        state_map = StateMapService(redis_url=None)
        push_service = PushDistributionService(cm, state_map)

        config_hash = "multi123"
        config_url = f"https://bucket.s3.us-east-1.amazonaws.com/configs/{org_id}/{config_hash}.signed"

        # Actualizar state map + push
        await state_map.update_config(org_id, config_hash, config_url, "org", None)
        enviados = await push_service.push_config_change(
            org_id, config_hash, config_url, "org", None
        )

        assert enviados == 3
        assert cm.send_to_workstation.call_count == 3


# === TEST 2: FLUJO DE REGISTRO WS → ENRICHMENT ===


class TestFlujoRegistroEnrichment:
    """
    Test de integración del flujo de registro enriquecido.

    Simula: WS conecta → registration enrichment con datos del state map.
    Validates: Requirement 5.1
    """

    @pytest.mark.asyncio
    async def test_enrichment_con_state_map_poblado(self, org_id, ws_id, vlan_id):
        """
        WHEN una WS se registra y el state map tiene datos de su org,
        THEN la respuesta incluye los 6 campos con valores correctos.
        """
        state_map = StateMapService(redis_url=None)

        # Pre-poblar state map con datos de la organización
        state_map._state[org_id] = OrgDistributionState(
            config_hash="cfg12345",
            config_s3_url=f"https://bucket.s3.us-east-1.amazonaws.com/configs/{org_id}/cfg12345.signed",
            cert_version=3,
            cert_url=f"https://bucket.s3.us-east-1.amazonaws.com/certs/{org_id}/v3.cer",
            msi_version="2.1.0",
            msi_url=f"https://bucket.s3.us-east-1.amazonaws.com/versions/2.1.0/AlwaysPrint.msi?presigned",
            msi_url_expires_at=9999999999.0,  # Muy en el futuro (no expira)
        )

        # Simular registration enrichment (lógica del WebSocket handler)
        ws_state = await state_map.resolve_workstation_state(
            org_id=org_id,
            vlan_id=None,
            ws_id=ws_id,
        )

        # Verificar que la respuesta incluye los 6 campos correctos
        assert ws_state is not None
        assert ws_state["config_hash"] == "cfg12345"
        assert ws_state["config_s3_url"] == f"https://bucket.s3.us-east-1.amazonaws.com/configs/{org_id}/cfg12345.signed"
        assert ws_state["cert_version"] == 3
        assert ws_state["cert_url"] == f"https://bucket.s3.us-east-1.amazonaws.com/certs/{org_id}/v3.cer"
        assert ws_state["msi_version"] == "2.1.0"
        assert ws_state["msi_url"] is not None

    @pytest.mark.asyncio
    async def test_enrichment_con_scope_vlan_override(self, org_id, ws_id, vlan_id):
        """
        WHEN una WS tiene VLAN override en el state map,
        THEN el enrichment retorna la config de la VLAN (no la de org).
        """
        state_map = StateMapService(redis_url=None)

        # Config org + override por VLAN
        state_map._state[org_id] = OrgDistributionState(
            config_hash="org_hash",
            config_s3_url="https://bucket.s3.us-east-1.amazonaws.com/configs/org_hash.signed",
            cert_version=2,
            cert_url="https://bucket.s3.us-east-1.amazonaws.com/certs/v2.cer",
            msi_version="1.5.0",
            msi_url="https://bucket.s3.us-east-1.amazonaws.com/versions/1.5.0/AlwaysPrint.msi",
            msi_url_expires_at=9999999999.0,
            vlan_configs={
                vlan_id: VlanConfigState(
                    config_hash="vlan_hash",
                    config_s3_url="https://bucket.s3.us-east-1.amazonaws.com/configs/vlan_hash.signed",
                ),
            },
        )

        # Resolver con VLAN
        ws_state = await state_map.resolve_workstation_state(
            org_id=org_id,
            vlan_id=vlan_id,
            ws_id=ws_id,
        )

        # Config debe ser la de VLAN, cert y MSI siguen siendo de org
        assert ws_state["config_hash"] == "vlan_hash"
        assert "vlan_hash" in ws_state["config_s3_url"]
        assert ws_state["cert_version"] == 2
        assert ws_state["msi_version"] == "1.5.0"

    @pytest.mark.asyncio
    async def test_enrichment_con_scope_workstation_override(self, org_id, ws_id, vlan_id):
        """
        WHEN una WS tiene un override específico para su workstation_id,
        THEN el enrichment retorna la config de workstation (más específica).
        """
        state_map = StateMapService(redis_url=None)

        # Config org + vlan + workstation override
        state_map._state[org_id] = OrgDistributionState(
            config_hash="org_hash",
            config_s3_url="https://bucket.s3.us-east-1.amazonaws.com/configs/org_hash.signed",
            cert_version=1,
            cert_url=None,
            msi_version=None,
            msi_url=None,
            msi_url_expires_at=0.0,
            vlan_configs={
                vlan_id: VlanConfigState(
                    config_hash="vlan_hash",
                    config_s3_url="https://bucket.s3.us-east-1.amazonaws.com/configs/vlan_hash.signed",
                ),
            },
            ws_configs={
                ws_id: WsConfigState(
                    config_hash="ws_hash",
                    config_s3_url="https://bucket.s3.us-east-1.amazonaws.com/configs/ws_hash.signed",
                ),
            },
        )

        # Resolver con VLAN + workstation override
        ws_state = await state_map.resolve_workstation_state(
            org_id=org_id,
            vlan_id=vlan_id,
            ws_id=ws_id,
        )

        # Config debe ser la de workstation (más específica gana)
        assert ws_state["config_hash"] == "ws_hash"
        assert "ws_hash" in ws_state["config_s3_url"]


# === TEST 3: MULTI-WORKER VÍA REDIS PUB/SUB ===


class TestMultiWorkerRedisSync:
    """
    Test de integración de sincronización multi-worker.

    Simula: cambio en worker 1 → publica JSON → worker 2 recibe y sincroniza.
    Validates: Requirement 8.1
    """

    @pytest.mark.asyncio
    async def test_cambio_en_worker1_visible_en_worker2(self, org_id):
        """
        WHEN worker 1 hace update_config y publica a Redis,
        THEN worker 2 procesa el mensaje y tiene el mismo estado.
        """
        # Crear 2 instancias de StateMapService (simulando 2 workers)
        worker1 = StateMapService(redis_url=None)
        worker2 = StateMapService(redis_url=None)

        # Asegurar worker_ids diferentes
        worker1._worker_id = "worker_1_test"
        worker2._worker_id = "worker_2_test"

        config_hash = "sync1234"
        config_s3_url = f"https://bucket.s3.us-east-1.amazonaws.com/configs/{org_id}/{config_hash}.signed"

        # Worker 1 hace update_config (sin Redis real, capturar el payload)
        await worker1.update_config(
            org_id=org_id,
            config_hash=config_hash,
            config_s3_url=config_s3_url,
            scope="org",
            scope_id=None,
        )

        # Construir el mensaje Redis que worker 1 habría publicado
        redis_message = {
            "type": "message",
            "data": json.dumps({
                "origin_worker_id": worker1._worker_id,
                "org_id": org_id,
                "update_type": "config",
                "data": {
                    "config_hash": config_hash,
                    "config_s3_url": config_s3_url,
                    "scope": "org",
                    "scope_id": None,
                },
            }),
        }

        # Worker 2 procesa el mensaje (simula recepción vía Redis pub/sub)
        await worker2._on_redis_message(redis_message)

        # Verificar que worker 2 tiene el mismo estado que worker 1
        state_w1 = await worker1.get_state(org_id)
        state_w2 = await worker2.get_state(org_id)

        assert state_w1 is not None
        assert state_w2 is not None
        assert state_w1.config_hash == state_w2.config_hash
        assert state_w1.config_s3_url == state_w2.config_s3_url

    @pytest.mark.asyncio
    async def test_sync_cert_rotation_entre_workers(self, org_id):
        """
        WHEN worker 1 rota un certificado,
        THEN worker 2 recibe y sincroniza cert_version y cert_url.
        """
        worker1 = StateMapService(redis_url=None)
        worker2 = StateMapService(redis_url=None)
        worker1._worker_id = "worker_1_cert"
        worker2._worker_id = "worker_2_cert"

        cert_version = 5
        cert_url = f"https://bucket.s3.us-east-1.amazonaws.com/certs/{org_id}/v5.cer"

        # Worker 1 actualiza cert
        await worker1.update_cert(
            org_id=org_id,
            cert_version=cert_version,
            cert_url=cert_url,
        )

        # Simular mensaje Redis de worker 1 → worker 2
        redis_message = {
            "type": "message",
            "data": json.dumps({
                "origin_worker_id": worker1._worker_id,
                "org_id": org_id,
                "update_type": "cert",
                "data": {
                    "cert_version": cert_version,
                    "cert_url": cert_url,
                },
            }),
        }

        await worker2._on_redis_message(redis_message)

        # Verificar sincronización
        state_w2 = await worker2.get_state(org_id)
        assert state_w2 is not None
        assert state_w2.cert_version == cert_version
        assert state_w2.cert_url == cert_url

    @pytest.mark.asyncio
    async def test_sync_msi_update_entre_workers(self, org_id):
        """
        WHEN worker 1 actualiza MSI version,
        THEN worker 2 recibe y sincroniza msi_version y msi_url.
        """
        worker1 = StateMapService(redis_url=None)
        worker2 = StateMapService(redis_url=None)
        worker1._worker_id = "worker_1_msi"
        worker2._worker_id = "worker_2_msi"

        msi_version = "3.0.0"
        msi_url = "https://bucket.s3.us-east-1.amazonaws.com/versions/3.0.0/AlwaysPrint.msi?presigned"
        msi_url_expires_at = 9999999999.0

        # Worker 1 actualiza MSI
        await worker1.update_msi(
            org_id=org_id,
            msi_version=msi_version,
            msi_url=msi_url,
            msi_url_expires_at=msi_url_expires_at,
        )

        # Simular mensaje Redis
        redis_message = {
            "type": "message",
            "data": json.dumps({
                "origin_worker_id": worker1._worker_id,
                "org_id": org_id,
                "update_type": "msi",
                "data": {
                    "msi_version": msi_version,
                    "msi_url": msi_url,
                    "msi_url_expires_at": msi_url_expires_at,
                },
            }),
        }

        await worker2._on_redis_message(redis_message)

        # Verificar sincronización
        state_w2 = await worker2.get_state(org_id)
        assert state_w2 is not None
        assert state_w2.msi_version == msi_version
        assert state_w2.msi_url == msi_url
        assert state_w2.msi_url_expires_at == msi_url_expires_at

    @pytest.mark.asyncio
    async def test_mensaje_propio_ignorado(self, org_id):
        """
        WHEN un worker recibe un mensaje con su propio origin_worker_id,
        THEN lo ignora (no procesa el cambio de nuevo).
        """
        worker = StateMapService(redis_url=None)
        worker._worker_id = "worker_self"

        # Mensaje con el mismo origin_worker_id
        redis_message = {
            "type": "message",
            "data": json.dumps({
                "origin_worker_id": "worker_self",
                "org_id": org_id,
                "update_type": "config",
                "data": {
                    "config_hash": "should_not_apply",
                    "config_s3_url": "https://should.not.apply",
                    "scope": "org",
                    "scope_id": None,
                },
            }),
        }

        await worker._on_redis_message(redis_message)

        # El estado no debe existir (el mensaje fue ignorado)
        state = await worker.get_state(org_id)
        assert state is None


# === TEST 4: FALLBACK — LEGACY ENDPOINTS SIGUEN FUNCIONANDO ===


class TestLegacyEndpointsFallback:
    """
    Test de integración de compatibilidad con endpoints legacy.

    Verifica que los endpoints /config/info y /config/download están
    registrados en el router y responden (el backend los mantiene durante
    el periodo de transición).
    Validates: Requirement 7.4
    """

    def test_legacy_config_info_endpoint_registrado(self):
        """
        WHEN se verifica el router de action_config,
        THEN el endpoint /workstations/{id}/config/info está registrado.
        """
        from app.api.v1.endpoints.action_config import router

        # Buscar la ruta en las rutas registradas del router
        rutas = [route.path for route in router.routes]
        assert "/workstations/{workstation_id}/config/info" in rutas

    def test_legacy_config_download_endpoint_registrado(self):
        """
        WHEN se verifica el router de action_config,
        THEN el endpoint /workstations/{id}/config/download está registrado.
        """
        from app.api.v1.endpoints.action_config import router

        rutas = [route.path for route in router.routes]
        assert "/workstations/{workstation_id}/config/download" in rutas

    def test_legacy_endpoints_metodo_get(self):
        """
        WHEN se verifican los legacy endpoints,
        THEN ambos aceptan método GET.
        """
        from app.api.v1.endpoints.action_config import router

        for route in router.routes:
            if hasattr(route, "path") and hasattr(route, "methods"):
                if route.path == "/workstations/{workstation_id}/config/info":
                    assert "GET" in route.methods
                elif route.path == "/workstations/{workstation_id}/config/download":
                    assert "GET" in route.methods

    def test_legacy_endpoints_coexisten_con_push_services(self):
        """
        WHEN se importan los servicios push-based,
        THEN los legacy endpoints siguen disponibles en el router (no fueron eliminados).
        """
        from app.api.v1.endpoints.action_config import router
        from app.services.push_distribution_service import PushDistributionService
        from app.services.state_map_service import StateMapService

        # Los servicios push existen y son importables
        assert PushDistributionService is not None
        assert StateMapService is not None

        # Los legacy endpoints siguen registrados
        rutas = [route.path for route in router.routes]
        legacy_info = "/workstations/{workstation_id}/config/info"
        legacy_download = "/workstations/{workstation_id}/config/download"

        assert legacy_info in rutas, (
            f"Endpoint legacy {legacy_info} eliminado prematuramente"
        )
        assert legacy_download in rutas, (
            f"Endpoint legacy {legacy_download} eliminado prematuramente"
        )
