"""
Tests unitarios para sincronización Redis pub/sub del StateMapService (Task 1.4).

Verifica:
- _publish_update serializa y publica correctamente en Redis
- _on_redis_message actualiza el state map local con mensajes de otros workers
- _on_redis_message ignora mensajes propios (origin_worker_id)
- _on_redis_message maneja los tres update_types: config, cert, msi
- _on_redis_message soporta config con scope org, vlan y workstation
- update_config/update_cert/update_msi llaman a _publish_update
- initialize() conecta a Redis y suscribe al canal state_map:update
- Worker ID se genera con formato correcto
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.state_map_service import (
    OrgDistributionState,
    StateMapService,
    StateMapUpdate,
    VlanConfigState,
    WsConfigState,
)


class TestWorkerIdGeneration:
    """Verificación del formato de worker_id."""

    def test_worker_id_formato(self):
        """Worker ID sigue formato worker_{pid}_{uuid_hex8}."""
        svc = StateMapService(redis_url="redis://localhost:6379/0")
        parts = svc._worker_id.split("_")
        # Formato: worker_{pid}_{uuid_hex8}
        assert parts[0] == "worker"
        # El PID es un número
        assert parts[1].isdigit()
        # El sufijo UUID tiene 8 caracteres hex
        assert len(parts[2]) == 8
        assert all(c in "0123456789abcdef" for c in parts[2])

    def test_worker_id_unico_entre_instancias(self):
        """Dos instancias del servicio tienen worker_ids diferentes."""
        svc1 = StateMapService(redis_url="redis://localhost:6379/0")
        svc2 = StateMapService(redis_url="redis://localhost:6379/0")
        # Mismo PID pero diferente UUID suffix
        assert svc1._worker_id != svc2._worker_id


class TestPublishUpdate:
    """Verificación de _publish_update."""

    @pytest.mark.asyncio
    async def test_publish_sin_redis_loguea_warning(self):
        """Sin Redis disponible, loguea warning y no lanza excepción."""
        svc = StateMapService()
        # _redis es None por defecto (sin redis_url)
        # No debe lanzar excepción
        await svc._publish_update("org-1", "config", {"config_hash": "abc"})

    @pytest.mark.asyncio
    async def test_publish_con_redis_disponible(self):
        """Con Redis, publica JSON en canal state_map:update."""
        svc = StateMapService(redis_url="redis://localhost:6379/0")
        svc._redis = AsyncMock()
        svc._redis_available = True

        await svc._publish_update("org-1", "config", {
            "config_hash": "abc123",
            "config_s3_url": "https://s3/abc.signed",
            "scope": "org",
            "scope_id": None,
        })

        # Verificar que se llamó publish con canal y payload correcto
        svc._redis.publish.assert_called_once()
        call_args = svc._redis.publish.call_args
        channel = call_args[0][0]
        payload_json = call_args[0][1]

        assert channel == "state_map:update"
        payload = json.loads(payload_json)
        assert payload["origin_worker_id"] == svc._worker_id
        assert payload["org_id"] == "org-1"
        assert payload["update_type"] == "config"
        assert payload["data"]["config_hash"] == "abc123"
        assert payload["data"]["scope"] == "org"

    @pytest.mark.asyncio
    async def test_publish_error_redis_no_lanza_excepcion(self):
        """Si Redis falla al publicar, loguea y continúa sin excepción."""
        import redis.asyncio as aioredis

        svc = StateMapService(redis_url="redis://localhost:6379/0")
        svc._redis = AsyncMock()
        svc._redis_available = True
        svc._redis.publish.side_effect = aioredis.ConnectionError("Connection lost")

        # No debe lanzar excepción
        await svc._publish_update("org-1", "cert", {
            "cert_version": 3,
            "cert_url": "https://s3/v3.cer",
        })

    @pytest.mark.asyncio
    async def test_publish_redis_no_disponible_flag(self):
        """Si _redis_available es False, no intenta publicar."""
        svc = StateMapService(redis_url="redis://localhost:6379/0")
        svc._redis = AsyncMock()
        svc._redis_available = False  # Redis caído

        await svc._publish_update("org-1", "msi", {"msi_version": "2.0"})

        # No se debe llamar a publish
        svc._redis.publish.assert_not_called()


class TestOnRedisMessage:
    """Verificación de _on_redis_message."""

    @pytest.mark.asyncio
    async def test_ignora_mensajes_propios(self):
        """Mensajes con origin_worker_id igual al propio son ignorados."""
        svc = StateMapService()
        own_message = {
            "type": "message",
            "channel": "state_map:update",
            "data": json.dumps({
                "origin_worker_id": svc._worker_id,
                "org_id": "org-1",
                "update_type": "config",
                "data": {
                    "config_hash": "should_not_apply",
                    "config_s3_url": "https://s3/no.signed",
                    "scope": "org",
                    "scope_id": None,
                },
            }),
        }
        await svc._on_redis_message(own_message)
        # No se creó la org (mensaje ignorado)
        assert "org-1" not in svc._state

    @pytest.mark.asyncio
    async def test_config_update_scope_org(self):
        """Mensaje de config update con scope org actualiza correctamente."""
        svc = StateMapService()
        message = {
            "type": "message",
            "channel": "state_map:update",
            "data": json.dumps({
                "origin_worker_id": "worker_other_123",
                "org_id": "org-1",
                "update_type": "config",
                "data": {
                    "config_hash": "remotehash",
                    "config_s3_url": "https://s3/remote.signed",
                    "scope": "org",
                    "scope_id": None,
                },
            }),
        }
        await svc._on_redis_message(message)

        state = svc._state.get("org-1")
        assert state is not None
        assert state.config_hash == "remotehash"
        assert state.config_s3_url == "https://s3/remote.signed"

    @pytest.mark.asyncio
    async def test_config_update_scope_vlan(self):
        """Mensaje de config update con scope vlan crea entrada en vlan_configs."""
        svc = StateMapService()
        message = {
            "type": "message",
            "channel": "state_map:update",
            "data": json.dumps({
                "origin_worker_id": "worker_other_456",
                "org_id": "org-2",
                "update_type": "config",
                "data": {
                    "config_hash": "vlanhash",
                    "config_s3_url": "https://s3/vlan.signed",
                    "scope": "vlan",
                    "scope_id": "vlan-10",
                },
            }),
        }
        await svc._on_redis_message(message)

        state = svc._state.get("org-2")
        assert state is not None
        assert "vlan-10" in state.vlan_configs
        assert state.vlan_configs["vlan-10"].config_hash == "vlanhash"

    @pytest.mark.asyncio
    async def test_config_update_scope_workstation(self):
        """Mensaje de config update con scope workstation crea entrada en ws_configs."""
        svc = StateMapService()
        message = {
            "type": "message",
            "channel": "state_map:update",
            "data": json.dumps({
                "origin_worker_id": "worker_other_789",
                "org_id": "org-3",
                "update_type": "config",
                "data": {
                    "config_hash": "wshash",
                    "config_s3_url": "https://s3/ws.signed",
                    "scope": "workstation",
                    "scope_id": "ws-99",
                },
            }),
        }
        await svc._on_redis_message(message)

        state = svc._state.get("org-3")
        assert state is not None
        assert "ws-99" in state.ws_configs
        assert state.ws_configs["ws-99"].config_hash == "wshash"

    @pytest.mark.asyncio
    async def test_cert_update(self):
        """Mensaje de cert update actualiza cert_version y cert_url."""
        svc = StateMapService()
        message = {
            "type": "message",
            "channel": "state_map:update",
            "data": json.dumps({
                "origin_worker_id": "worker_other_abc",
                "org_id": "org-1",
                "update_type": "cert",
                "data": {
                    "cert_version": 7,
                    "cert_url": "https://s3/certs/v7.cer",
                },
            }),
        }
        await svc._on_redis_message(message)

        state = svc._state.get("org-1")
        assert state is not None
        assert state.cert_version == 7
        assert state.cert_url == "https://s3/certs/v7.cer"

    @pytest.mark.asyncio
    async def test_msi_update(self):
        """Mensaje de MSI update actualiza msi_version, msi_url y expires_at."""
        svc = StateMapService()
        message = {
            "type": "message",
            "channel": "state_map:update",
            "data": json.dumps({
                "origin_worker_id": "worker_other_def",
                "org_id": "org-1",
                "update_type": "msi",
                "data": {
                    "msi_version": "4.0.0",
                    "msi_url": "https://s3/msi/4.0.0.msi?signed",
                    "msi_url_expires_at": 1800000000.0,
                },
            }),
        }
        await svc._on_redis_message(message)

        state = svc._state.get("org-1")
        assert state is not None
        assert state.msi_version == "4.0.0"
        assert state.msi_url == "https://s3/msi/4.0.0.msi?signed"
        assert state.msi_url_expires_at == 1800000000.0

    @pytest.mark.asyncio
    async def test_mensaje_json_invalido(self):
        """JSON inválido se ignora sin excepción."""
        svc = StateMapService()
        message = {
            "type": "message",
            "channel": "state_map:update",
            "data": "not-valid-json{{{",
        }
        # No debe lanzar excepción
        await svc._on_redis_message(message)
        assert len(svc._state) == 0

    @pytest.mark.asyncio
    async def test_mensaje_incompleto(self):
        """Mensaje sin org_id o update_type se ignora."""
        svc = StateMapService()
        message = {
            "type": "message",
            "channel": "state_map:update",
            "data": json.dumps({
                "origin_worker_id": "worker_other",
                # Falta org_id y update_type
            }),
        }
        await svc._on_redis_message(message)
        assert len(svc._state) == 0

    @pytest.mark.asyncio
    async def test_update_type_desconocido(self):
        """update_type desconocido se ignora sin crashear."""
        svc = StateMapService()
        message = {
            "type": "message",
            "channel": "state_map:update",
            "data": json.dumps({
                "origin_worker_id": "worker_other",
                "org_id": "org-1",
                "update_type": "unknown_type",
                "data": {},
            }),
        }
        await svc._on_redis_message(message)
        # Se creó la org pero no se actualizó nada sustancial
        state = svc._state.get("org-1")
        assert state is not None
        assert state.config_hash is None

    @pytest.mark.asyncio
    async def test_multiples_updates_secuenciales(self):
        """Múltiples updates del mismo org se aplican correctamente."""
        svc = StateMapService()

        # Primer update: config
        msg1 = {
            "type": "message",
            "channel": "state_map:update",
            "data": json.dumps({
                "origin_worker_id": "worker_A",
                "org_id": "org-1",
                "update_type": "config",
                "data": {
                    "config_hash": "hash_v1",
                    "config_s3_url": "https://s3/v1.signed",
                    "scope": "org",
                    "scope_id": None,
                },
            }),
        }
        await svc._on_redis_message(msg1)

        # Segundo update: cert
        msg2 = {
            "type": "message",
            "channel": "state_map:update",
            "data": json.dumps({
                "origin_worker_id": "worker_B",
                "org_id": "org-1",
                "update_type": "cert",
                "data": {
                    "cert_version": 2,
                    "cert_url": "https://s3/certs/v2.cer",
                },
            }),
        }
        await svc._on_redis_message(msg2)

        # Tercer update: config sobreescribe
        msg3 = {
            "type": "message",
            "channel": "state_map:update",
            "data": json.dumps({
                "origin_worker_id": "worker_A",
                "org_id": "org-1",
                "update_type": "config",
                "data": {
                    "config_hash": "hash_v2",
                    "config_s3_url": "https://s3/v2.signed",
                    "scope": "org",
                    "scope_id": None,
                },
            }),
        }
        await svc._on_redis_message(msg3)

        state = svc._state["org-1"]
        assert state.config_hash == "hash_v2"
        assert state.cert_version == 2
        assert state.cert_url == "https://s3/certs/v2.cer"


class TestUpdateMethodsPublish:
    """Verificación de que update_config/cert/msi llaman a _publish_update."""

    @pytest.mark.asyncio
    async def test_update_config_publica(self):
        """update_config llama a _publish_update con datos correctos."""
        svc = StateMapService(redis_url="redis://localhost:6379/0")
        svc._redis = AsyncMock()
        svc._redis_available = True

        await svc.update_config(
            org_id="org-1",
            config_hash="newhash",
            config_s3_url="https://s3/new.signed",
            scope="org",
            scope_id=None,
        )

        # Verificar que se publicó
        svc._redis.publish.assert_called_once()
        payload = json.loads(svc._redis.publish.call_args[0][1])
        assert payload["org_id"] == "org-1"
        assert payload["update_type"] == "config"
        assert payload["data"]["config_hash"] == "newhash"
        assert payload["data"]["scope"] == "org"

    @pytest.mark.asyncio
    async def test_update_config_vlan_publica_scope_id(self):
        """update_config con scope vlan incluye scope_id en el publish."""
        svc = StateMapService(redis_url="redis://localhost:6379/0")
        svc._redis = AsyncMock()
        svc._redis_available = True

        await svc.update_config(
            org_id="org-1",
            config_hash="vlanhash",
            config_s3_url="https://s3/vlan.signed",
            scope="vlan",
            scope_id="vlan-42",
        )

        payload = json.loads(svc._redis.publish.call_args[0][1])
        assert payload["data"]["scope"] == "vlan"
        assert payload["data"]["scope_id"] == "vlan-42"

    @pytest.mark.asyncio
    async def test_update_cert_publica(self):
        """update_cert llama a _publish_update con cert_version y cert_url."""
        svc = StateMapService(redis_url="redis://localhost:6379/0")
        svc._redis = AsyncMock()
        svc._redis_available = True

        await svc.update_cert("org-1", 5, "https://s3/certs/v5.cer")

        svc._redis.publish.assert_called_once()
        payload = json.loads(svc._redis.publish.call_args[0][1])
        assert payload["org_id"] == "org-1"
        assert payload["update_type"] == "cert"
        assert payload["data"]["cert_version"] == 5
        assert payload["data"]["cert_url"] == "https://s3/certs/v5.cer"

    @pytest.mark.asyncio
    async def test_update_msi_publica(self):
        """update_msi llama a _publish_update con msi_version, url y expires_at."""
        svc = StateMapService(redis_url="redis://localhost:6379/0")
        svc._redis = AsyncMock()
        svc._redis_available = True

        await svc.update_msi("org-1", "3.0.0", "https://s3/msi.msi", 1900000000.0)

        svc._redis.publish.assert_called_once()
        payload = json.loads(svc._redis.publish.call_args[0][1])
        assert payload["org_id"] == "org-1"
        assert payload["update_type"] == "msi"
        assert payload["data"]["msi_version"] == "3.0.0"
        assert payload["data"]["msi_url"] == "https://s3/msi.msi"
        assert payload["data"]["msi_url_expires_at"] == 1900000000.0

    @pytest.mark.asyncio
    async def test_update_config_scope_desconocido_no_publica(self):
        """update_config con scope desconocido NO publica a Redis."""
        svc = StateMapService(redis_url="redis://localhost:6379/0")
        svc._redis = AsyncMock()
        svc._redis_available = True

        await svc.update_config("org-1", "hash", "url", "invalid_scope", None)

        # No se publicó porque el scope es inválido
        svc._redis.publish.assert_not_called()


class TestInitializeRedis:
    """Verificación de _initialize_redis."""

    @pytest.mark.asyncio
    async def test_sin_redis_url_no_conecta(self):
        """Sin redis_url, _initialize_redis no intenta conectar."""
        svc = StateMapService()  # Sin redis_url
        await svc._initialize_redis()
        assert svc._redis is None
        assert svc._pubsub is None
        assert svc._listener_task is None

    @pytest.mark.asyncio
    async def test_redis_disponible_conecta_y_suscribe(self):
        """Con Redis disponible, conecta, suscribe y lanza listener."""
        svc = StateMapService(redis_url="redis://localhost:6379/0")

        mock_redis = AsyncMock()
        mock_pubsub = AsyncMock()
        # pubsub() es un método síncrono que retorna el objeto PubSub
        mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            await svc._initialize_redis()

        assert svc._redis is mock_redis
        assert svc._redis_available is True
        mock_redis.ping.assert_called_once()
        mock_pubsub.subscribe.assert_called_once_with("state_map:update")
        assert svc._listener_task is not None
        # Limpiar task
        svc._listener_task.cancel()
        try:
            await svc._listener_task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_redis_no_disponible_opera_sin_sync(self):
        """Si Redis no está disponible al iniciar, opera sin sincronización."""
        import redis.asyncio as aioredis

        svc = StateMapService(redis_url="redis://localhost:6379/0")

        mock_redis = AsyncMock()
        mock_redis.ping.side_effect = aioredis.ConnectionError("Connection refused")

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            await svc._initialize_redis()

        # Redis marcado como no disponible
        assert svc._redis_available is False


class TestRoundTrip:
    """Verificación de flujo completo publish → receive."""

    @pytest.mark.asyncio
    async def test_round_trip_config(self):
        """Worker A publica config → Worker B recibe y actualiza."""
        # Simular Worker A
        worker_a = StateMapService(redis_url="redis://localhost:6379/0")
        worker_a._redis = AsyncMock()
        worker_a._redis_available = True

        # Worker A actualiza config (publica a Redis)
        await worker_a.update_config(
            "org-1", "hash_abc", "https://s3/abc.signed", "org", None
        )

        # Capturar el payload publicado
        published_json = worker_a._redis.publish.call_args[0][1]

        # Simular Worker B recibiendo el mensaje
        worker_b = StateMapService(redis_url="redis://localhost:6379/0")
        message = {
            "type": "message",
            "channel": "state_map:update",
            "data": published_json,
        }
        await worker_b._on_redis_message(message)

        # Worker B tiene el mismo estado que Worker A
        state_a = await worker_a.get_state("org-1")
        state_b = await worker_b.get_state("org-1")
        assert state_b is not None
        assert state_b.config_hash == state_a.config_hash
        assert state_b.config_s3_url == state_a.config_s3_url

    @pytest.mark.asyncio
    async def test_round_trip_cert(self):
        """Worker A publica cert rotation → Worker B recibe y actualiza."""
        worker_a = StateMapService(redis_url="redis://localhost:6379/0")
        worker_a._redis = AsyncMock()
        worker_a._redis_available = True

        await worker_a.update_cert("org-1", 10, "https://s3/certs/v10.cer")

        published_json = worker_a._redis.publish.call_args[0][1]

        worker_b = StateMapService(redis_url="redis://localhost:6379/0")
        message = {
            "type": "message",
            "channel": "state_map:update",
            "data": published_json,
        }
        await worker_b._on_redis_message(message)

        state_b = await worker_b.get_state("org-1")
        assert state_b.cert_version == 10
        assert state_b.cert_url == "https://s3/certs/v10.cer"

    @pytest.mark.asyncio
    async def test_round_trip_msi(self):
        """Worker A publica MSI update → Worker B recibe y actualiza."""
        worker_a = StateMapService(redis_url="redis://localhost:6379/0")
        worker_a._redis = AsyncMock()
        worker_a._redis_available = True

        await worker_a.update_msi("org-1", "5.0.0", "https://s3/msi/5.msi", 2000000000.0)

        published_json = worker_a._redis.publish.call_args[0][1]

        worker_b = StateMapService(redis_url="redis://localhost:6379/0")
        message = {
            "type": "message",
            "channel": "state_map:update",
            "data": published_json,
        }
        await worker_b._on_redis_message(message)

        state_b = await worker_b.get_state("org-1")
        assert state_b.msi_version == "5.0.0"
        assert state_b.msi_url == "https://s3/msi/5.msi"
        assert state_b.msi_url_expires_at == 2000000000.0
