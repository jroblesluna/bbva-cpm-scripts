"""
Property test para Task 4.2: Cross-worker message routing (Property 5).

**Validates: Requirements 2.2**

Property 5: Para cualquier mensaje enviado a una workstation no conectada localmente,
SI WorkerRegistry resuelve la workstation a un worker_id, ENTONCES el mensaje
SE PUBLICA en `worker:{resolved_worker_id}` con el payload original incluyendo
`target_workstation_id`.
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings as hypothesis_settings, assume
from hypothesis import strategies as st

from app.services.redis_connection_manager import RedisConnectionManager


# === Estrategias de generación ===

# IDs tipo UUID (eficiente, sin regex)
uuid_strategy = st.uuids().map(str)

# Worker IDs con formato worker_{pid}
worker_id_strategy = st.integers(min_value=1, max_value=999999).map(lambda pid: f"worker_{pid}")

# Tipos de mensaje válidos
message_type_strategy = st.sampled_from([
    "command", "status_request", "config_update", "ping", "data_sync",
    "action_execute", "health_check", "firmware_update",
])

# Payload adicional (campos extra del mensaje)
extra_payload_strategy = st.dictionaries(
    keys=st.sampled_from(["data", "payload", "version", "timestamp", "flag", "count", "label"]),
    values=st.one_of(
        st.text(min_size=0, max_size=30, alphabet=st.characters(categories=("L", "N", "P"))),
        st.integers(min_value=-1000, max_value=1000),
        st.booleans(),
        st.none(),
    ),
    min_size=0,
    max_size=4,
)


@pytest.mark.asyncio
@hypothesis_settings(max_examples=100, deadline=None)
@given(
    workstation_id=uuid_strategy,
    resolved_worker_id=worker_id_strategy,
    organization_id=uuid_strategy,
    message_type=message_type_strategy,
    extra_fields=extra_payload_strategy,
)
async def test_cross_worker_publish_targets_resolved_worker_channel(
    workstation_id: str,
    resolved_worker_id: str,
    organization_id: str,
    message_type: str,
    extra_fields: dict,
):
    """
    **Validates: Requirements 2.2**

    Para cualquier workstation no conectada localmente, si WorkerRegistry resuelve
    a un worker_id, el PUBLISH se dirige a `worker:{resolved_worker_id}`.
    """
    # Evitar colisión con campos reservados del payload
    assume("target_workstation_id" not in extra_fields)
    assume("organization_id" not in extra_fields)
    assume("type" not in extra_fields)

    # Configurar manager con Redis disponible pero SIN la workstation local
    manager = RedisConnectionManager(redis_url="redis://localhost:6379/0")
    manager._redis_available = True
    manager._redis = AsyncMock()
    manager._redis.publish = AsyncMock(return_value=1)

    # Mock WorkerRegistry que resuelve al worker generado
    registry = AsyncMock()
    registry.find_worker_for_workstation = AsyncMock(return_value=resolved_worker_id)
    manager._worker_registry = registry

    # Asegurar que la workstation NO está en conexiones locales
    assert workstation_id not in manager.workstation_connections

    # Construir mensaje con los campos generados
    message = {
        "type": message_type,
        "organization_id": organization_id,
        **extra_fields,
    }

    # Ejecutar send_to_workstation
    result = await manager.send_to_workstation(workstation_id, message)

    # === Verificaciones de Property 5 ===

    # 1. El PUBLISH se dirigió al canal correcto: worker:{resolved_worker_id}
    manager._redis.publish.assert_called_once()
    call_args = manager._redis.publish.call_args[0]
    published_channel = call_args[0]
    assert published_channel == f"worker:{resolved_worker_id}", (
        f"El canal de publish debe ser 'worker:{resolved_worker_id}', "
        f"pero fue '{published_channel}'"
    )

    # 2. El payload contiene target_workstation_id igual al workstation_id original
    published_payload = json.loads(call_args[1])
    assert published_payload["target_workstation_id"] == workstation_id, (
        f"target_workstation_id debe ser '{workstation_id}', "
        f"pero fue '{published_payload.get('target_workstation_id')}'"
    )

    # 3. El payload contiene todos los campos originales del mensaje
    assert published_payload["type"] == message_type, (
        f"type debe ser '{message_type}', pero fue '{published_payload.get('type')}'"
    )
    assert published_payload["organization_id"] == organization_id, (
        f"organization_id debe ser '{organization_id}', "
        f"pero fue '{published_payload.get('organization_id')}'"
    )

    # 4. Los campos extra del mensaje original están presentes en el payload publicado
    for key, value in extra_fields.items():
        assert key in published_payload, (
            f"Campo '{key}' del mensaje original no está en el payload publicado"
        )
        # Comparar como JSON para manejar serialización de None → null
        assert json.dumps(published_payload[key], default=str) == json.dumps(value, default=str), (
            f"Campo '{key}': esperado {value!r}, obtenido {published_payload[key]!r}"
        )

    # 5. No se usaron canales con prefijo ws:
    assert not published_channel.startswith("ws:"), (
        f"No debe publicar a canales ws:*, pero publicó a '{published_channel}'"
    )


@pytest.mark.asyncio
@hypothesis_settings(max_examples=100, deadline=None)
@given(
    workstation_id=uuid_strategy,
    resolved_worker_id=worker_id_strategy,
    organization_id=uuid_strategy,
    message_type=message_type_strategy,
)
async def test_cross_worker_no_publish_to_ws_channel(
    workstation_id: str,
    resolved_worker_id: str,
    organization_id: str,
    message_type: str,
):
    """
    **Validates: Requirements 2.2**

    Para cualquier envío cross-worker, nunca se publica al canal ws:{workstation_id}
    (patrón antiguo eliminado).
    """
    manager = RedisConnectionManager(redis_url="redis://localhost:6379/0")
    manager._redis_available = True
    manager._redis = AsyncMock()
    manager._redis.publish = AsyncMock(return_value=1)

    registry = AsyncMock()
    registry.find_worker_for_workstation = AsyncMock(return_value=resolved_worker_id)
    manager._worker_registry = registry

    # La workstation NO está local
    assert workstation_id not in manager.workstation_connections

    message = {"type": message_type, "organization_id": organization_id}
    await manager.send_to_workstation(workstation_id, message)

    # Verificar que el canal NO es ws:{workstation_id}
    call_args = manager._redis.publish.call_args[0]
    published_channel = call_args[0]
    assert not published_channel.startswith("ws:"), (
        f"No debe publicar a canales ws:*, pero publicó a '{published_channel}'"
    )
    # Verificar que siempre usa el patrón worker:{id}
    assert published_channel.startswith("worker:"), (
        f"Debe publicar a canales worker:*, pero publicó a '{published_channel}'"
    )


@pytest.mark.asyncio
@hypothesis_settings(max_examples=50, deadline=None)
@given(
    workstation_id=uuid_strategy,
    resolved_worker_id=worker_id_strategy,
    message_type=message_type_strategy,
)
async def test_cross_worker_org_id_fallback_from_local_state(
    workstation_id: str,
    resolved_worker_id: str,
    message_type: str,
):
    """
    **Validates: Requirements 2.2**

    Si el mensaje no incluye organization_id, el sistema usa el org_ids local
    como fallback para enriquecer el payload con organization_id.
    """
    manager = RedisConnectionManager(redis_url="redis://localhost:6379/0")
    manager._redis_available = True
    manager._redis = AsyncMock()
    manager._redis.publish = AsyncMock(return_value=1)

    # Simular que hay org_id en estado local para esta workstation
    fallback_org_id = "org-fallback-12345"
    manager.org_ids[workstation_id] = fallback_org_id

    registry = AsyncMock()
    registry.find_worker_for_workstation = AsyncMock(return_value=resolved_worker_id)
    manager._worker_registry = registry

    # Mensaje SIN organization_id
    message = {"type": message_type}
    await manager.send_to_workstation(workstation_id, message)

    # Verificar que el payload publicado incluye el org_id del fallback
    call_args = manager._redis.publish.call_args[0]
    published_payload = json.loads(call_args[1])
    assert published_payload.get("organization_id") == fallback_org_id, (
        f"organization_id fallback debe ser '{fallback_org_id}', "
        f"pero fue '{published_payload.get('organization_id')}'"
    )
    # target_workstation_id siempre presente
    assert published_payload["target_workstation_id"] == workstation_id
