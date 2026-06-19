"""
Property test para Task 12.1: Graceful fallback without Redis (Property 14).

**Validates: Requirements 7.1, 7.2**

Property 14: Para cualquier operación (send, connect, disconnect) ejecutada mientras
`_redis_available` es False, el RedisConnectionManager SHALL NO intentar ninguna
operación Redis (PUBLISH, SUBSCRIBE, UNSUBSCRIBE, SADD, SREM) y SHALL completar la
porción local de la operación sin error.

Verifica que:
1. `connect_workstation` con _redis_available=False → estado local se establece, sin llamadas Redis
2. `disconnect_workstation` con _redis_available=False → estado limpio, sin llamadas Redis
3. `send_to_workstation` a workstation no-local con _redis_available=False → return False, sin llamadas Redis
"""
import asyncio
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings as hypothesis_settings, assume, HealthCheck
from hypothesis import strategies as st

from app.services.redis_connection_manager import RedisConnectionManager


# === ESTRATEGIAS DE GENERACIÓN ===

# IDs tipo UUID (eficiente, sin regex)
uuid_strategy = st.uuids().map(str)

# Tipos de mensaje
message_type_strategy = st.sampled_from([
    "command", "status_request", "config_update",
    "org_broadcast", "firmware_push", "ping",
])

# Payload extra
extra_payload_strategy = st.dictionaries(
    keys=st.sampled_from(["data", "version", "timestamp", "severity", "details"]),
    values=st.one_of(
        st.text(min_size=0, max_size=20, alphabet=st.characters(categories=("L", "N"))),
        st.integers(min_value=0, max_value=5000),
        st.booleans(),
    ),
    min_size=0,
    max_size=3,
)

# VLAN ids opcionales
vlan_strategy = st.one_of(st.none(), uuid_strategy)


@st.composite
def connect_data_strategy(draw):
    """
    Genera datos para una operación connect_workstation.

    Returns:
        Tupla (workstation_id, organization_id, vlan_id)
    """
    ws_id = draw(uuid_strategy)
    org_id = draw(uuid_strategy)
    vlan_id = draw(vlan_strategy)
    return ws_id, org_id, vlan_id


@st.composite
def disconnect_data_strategy(draw):
    """
    Genera datos para una operación disconnect_workstation.

    Returns:
        Tupla (workstation_id, organization_id, vlan_id) de la WS pre-registrada
    """
    ws_id = draw(uuid_strategy)
    org_id = draw(uuid_strategy)
    vlan_id = draw(vlan_strategy)
    return ws_id, org_id, vlan_id


@st.composite
def send_to_remote_strategy(draw):
    """
    Genera datos para envío a workstation no-local.

    Returns:
        Tupla (target_ws_id, message) donde target_ws_id NO está conectada localmente
    """
    target_ws_id = draw(uuid_strategy)
    msg_type = draw(message_type_strategy)
    extra = draw(extra_payload_strategy)
    message = {"type": msg_type, **extra}
    return target_ws_id, message


def _create_manager_no_redis_with_tracking() -> tuple:
    """
    Crea un RedisConnectionManager con _redis_available=False y mocks de Redis
    que rastrean llamadas para verificar que NO se invocan.

    Returns:
        Tupla (manager, mock_redis, mock_pubsub, mock_registry)
    """
    manager = RedisConnectionManager(redis_url="redis://fake:6379/0")
    manager._redis_available = False

    # Mock Redis client — si se llama algún método, el test detectará la violación
    mock_redis = AsyncMock()
    manager._redis = mock_redis

    # Mock PubSub
    mock_pubsub = AsyncMock()
    manager._pubsub = mock_pubsub

    # Mock WorkerRegistry
    mock_registry = AsyncMock()
    manager._worker_registry = mock_registry

    return manager, mock_redis, mock_pubsub, mock_registry


# === PROPERTY TESTS ===


class TestGracefulFallbackNoRedis:
    """
    Property 14: Graceful fallback without Redis.

    Para cualquier operación (send, connect, disconnect) ejecutada mientras
    `_redis_available` es False, el RedisConnectionManager SHALL NO intentar
    ninguna operación Redis y SHALL completar la porción local sin error.

    **Validates: Requirements 7.1, 7.2**
    """

    @hypothesis_settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(data=connect_data_strategy())
    @pytest.mark.asyncio
    async def test_connect_without_redis_completes_locally(self, data):
        """
        **Validates: Requirements 7.2**

        connect_workstation con _redis_available=False → el estado local
        (workstation_connections, org_ids, _ws_vlan_ids, last_pong, last_activity,
        _org_ws_count) se establece correctamente, sin ninguna llamada a Redis
        (publish, subscribe, unsubscribe).
        """
        ws_id, org_id, vlan_id = data

        manager, mock_redis, mock_pubsub, mock_registry = (
            _create_manager_no_redis_with_tracking()
        )

        # Mock WebSocket y DB session
        mock_ws = AsyncMock()
        mock_db = MagicMock()

        # Patch WorkstationService (se importa localmente en connect_workstation)
        with patch(
            "app.services.workstation.WorkstationService",
            return_value=MagicMock(update_workstation_status=MagicMock()),
        ):
            await manager.connect_workstation(
                workstation_id=ws_id,
                websocket=mock_ws,
                db=mock_db,
                organization_id=org_id,
                vlan_id=vlan_id,
            )
            # Permitir que fire-and-forget se ejecute
            await asyncio.sleep(0)

        # === Verificar estado local establecido correctamente ===
        assert ws_id in manager.workstation_connections, (
            f"Workstation '{ws_id}' debería estar en workstation_connections tras connect"
        )
        assert manager.workstation_connections[ws_id] is mock_ws, (
            "El WebSocket almacenado debería ser el mismo que se pasó"
        )
        assert manager.org_ids[ws_id] == org_id, (
            f"org_ids['{ws_id}'] debería ser '{org_id}'"
        )
        assert manager._ws_vlan_ids[ws_id] == vlan_id, (
            f"_ws_vlan_ids['{ws_id}'] debería ser '{vlan_id}'"
        )
        assert ws_id in manager.last_pong, (
            f"last_pong debería contener '{ws_id}'"
        )
        assert ws_id in manager.last_activity, (
            f"last_activity debería contener '{ws_id}'"
        )
        assert manager._org_ws_count.get(org_id, 0) >= 1, (
            f"_org_ws_count['{org_id}'] debería ser >= 1"
        )

        # === Verificar que NO se llamó a operaciones Redis críticas ===
        # publish no debería haberse invocado
        mock_redis.publish.assert_not_called()

        # subscribe/unsubscribe en pubsub no deberían haberse invocado
        mock_pubsub.subscribe.assert_not_called()
        mock_pubsub.unsubscribe.assert_not_called()

    @hypothesis_settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(data=disconnect_data_strategy())
    @pytest.mark.asyncio
    async def test_disconnect_without_redis_completes_locally(self, data):
        """
        **Validates: Requirements 7.2**

        disconnect_workstation con _redis_available=False → el estado local se
        limpia correctamente (workstation eliminada de todos los dicts), sin
        ninguna llamada a Redis (UNSUBSCRIBE, PUBLISH).
        """
        ws_id, org_id, vlan_id = data

        manager, mock_redis, mock_pubsub, mock_registry = (
            _create_manager_no_redis_with_tracking()
        )

        # Pre-registrar workstation en estado local (simular que ya estaba conectada)
        mock_ws = AsyncMock()
        manager.workstation_connections[ws_id] = mock_ws
        manager.org_ids[ws_id] = org_id
        manager._ws_vlan_ids[ws_id] = vlan_id
        manager.last_pong[ws_id] = datetime.now(timezone.utc).replace(tzinfo=None)
        manager.last_activity[ws_id] = datetime.now(timezone.utc).replace(tzinfo=None)
        manager._org_ws_count[org_id] = 1

        # Mock DB session
        mock_db = MagicMock()

        await manager.disconnect_workstation(
            workstation_id=ws_id,
            db=mock_db,
            websocket=mock_ws,
        )

        # Esperar fire-and-forget (si hubiera alguno)
        await asyncio.sleep(0)

        # === Verificar que el estado local fue limpiado ===
        assert ws_id not in manager.workstation_connections, (
            f"Workstation '{ws_id}' debería haberse eliminado de workstation_connections"
        )
        assert ws_id not in manager.org_ids, (
            f"'{ws_id}' debería haberse eliminado de org_ids"
        )
        assert ws_id not in manager._ws_vlan_ids, (
            f"'{ws_id}' debería haberse eliminado de _ws_vlan_ids"
        )
        assert ws_id not in manager.last_pong, (
            f"'{ws_id}' debería haberse eliminado de last_pong"
        )
        assert ws_id not in manager.last_activity, (
            f"'{ws_id}' debería haberse eliminado de last_activity"
        )

        # === Verificar que NO se llamó a operaciones Redis de pub/sub ===
        mock_redis.publish.assert_not_called()
        mock_pubsub.subscribe.assert_not_called()
        mock_pubsub.unsubscribe.assert_not_called()

    @hypothesis_settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(data=send_to_remote_strategy())
    @pytest.mark.asyncio
    async def test_send_without_redis_returns_false_for_remote(self, data):
        """
        **Validates: Requirements 7.1**

        send_to_workstation a workstation no-local cuando Redis no está disponible
        → retorna False sin intentar PUBLISH ni consultar WorkerRegistry.
        """
        target_ws_id, message = data

        manager, mock_redis, mock_pubsub, mock_registry = (
            _create_manager_no_redis_with_tracking()
        )

        # El target_ws_id NO está conectado localmente (workstation_connections vacío)
        # Por lo tanto, debería intentar la ruta Redis, pero como _redis_available=False
        # debería retornar False sin hacer PUBLISH

        result = await manager.send_to_workstation(target_ws_id, message)

        # === Propiedad: retorna False ===
        assert result is False, (
            f"send_to_workstation a workstation no-local con Redis no disponible "
            f"debería retornar False, pero retornó {result}"
        )

        # === Verificar que NO se llamó a ningún método Redis ===
        mock_redis.publish.assert_not_called()

        # WorkerRegistry no debería haber sido consultado
        mock_registry.find_worker_for_workstation.assert_not_called()

    @hypothesis_settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(data=connect_data_strategy())
    @pytest.mark.asyncio
    async def test_connect_fire_and_forget_no_subscribe_when_redis_unavailable(
        self, data
    ):
        """
        **Validates: Requirements 7.2**

        Cuando _redis_available=False y es la primera workstation de una org
        (triggering lazy subscribe), el fire-and-forget NO ejecuta SUBSCRIBE
        ya que verifica _redis_available antes.
        """
        ws_id, org_id, vlan_id = data

        manager, mock_redis, mock_pubsub, mock_registry = (
            _create_manager_no_redis_with_tracking()
        )

        # Verificar que no hay workstations de esta org (triggering lazy subscribe)
        assert manager._org_ws_count.get(org_id, 0) == 0

        # Mock WebSocket y DB
        mock_ws = AsyncMock()
        mock_db = MagicMock()

        with patch(
            "app.services.workstation.WorkstationService",
            return_value=MagicMock(update_workstation_status=MagicMock()),
        ):
            await manager.connect_workstation(
                workstation_id=ws_id,
                websocket=mock_ws,
                db=mock_db,
                organization_id=org_id,
                vlan_id=vlan_id,
            )
            # Permitir que fire-and-forget termine
            await asyncio.sleep(0)

        # Estado local correcto
        assert ws_id in manager.workstation_connections
        assert manager._org_ws_count[org_id] == 1

        # Aunque la condición de lazy subscribe se cumple (primera WS de la org),
        # como _redis_available=False, el fire-and-forget NO debe llamar subscribe
        mock_pubsub.subscribe.assert_not_called()
        mock_pubsub.unsubscribe.assert_not_called()
        mock_redis.publish.assert_not_called()

    @hypothesis_settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        ws_id=uuid_strategy,
        org_id=uuid_strategy,
        msg_type=message_type_strategy,
        extra=extra_payload_strategy,
    )
    @pytest.mark.asyncio
    async def test_send_to_local_workstation_succeeds_without_redis(
        self, ws_id, org_id, msg_type, extra
    ):
        """
        **Validates: Requirements 7.1**

        send_to_workstation a workstation LOCAL cuando Redis no está disponible
        → entrega directamente via WebSocket (retorna True), sin necesidad de Redis.
        Las operaciones locales completan sin error.
        """
        manager, mock_redis, mock_pubsub, mock_registry = (
            _create_manager_no_redis_with_tracking()
        )

        # Registrar workstation localmente
        mock_ws = AsyncMock()
        mock_ws.send_json = AsyncMock()
        manager.workstation_connections[ws_id] = mock_ws
        manager.org_ids[ws_id] = org_id

        message = {"type": msg_type, **extra}

        result = await manager.send_to_workstation(ws_id, message)

        # === Propiedad: retorna True (entrega local exitosa) ===
        assert result is True, (
            f"send_to_workstation a workstation LOCAL debería retornar True "
            f"incluso sin Redis, pero retornó {result}"
        )

        # === Verificar que el WebSocket recibió el mensaje ===
        mock_ws.send_json.assert_called_once_with(message)

        # === Verificar que NO se tocó Redis ===
        mock_redis.publish.assert_not_called()
        mock_registry.find_worker_for_workstation.assert_not_called()
