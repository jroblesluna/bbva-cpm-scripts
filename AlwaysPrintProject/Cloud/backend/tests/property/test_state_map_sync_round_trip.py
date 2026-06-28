"""
Property test: Cross-worker state synchronization round-trip.

Verifica que cualquier actualización publicada por Worker A y recibida por Worker B
a través del canal Redis state_map:update resulta en un estado idéntico en ambos workers
para los campos afectados.

Feature: push-based-distribution, Property 3: Cross-worker state synchronization round-trip

**Validates: Requirements 1.5, 8.1, 8.2**
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

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
    lambda bucket, key: f"https://{bucket}.s3.us-east-1.amazonaws.com/{key}",
    bucket=st.just("test-bucket"),
    key=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz0123456789/-.",
        min_size=10,
        max_size=60,
    ),
)

# Scopes válidos para config
scope_strategy = st.sampled_from(["org", "vlan", "workstation"])

# Versiones de certificado (1-100)
cert_version_strategy = st.integers(min_value=1, max_value=100)

# Versiones de MSI (formato semver simplificado)
msi_version_strategy = st.builds(
    lambda major, minor, patch: f"{major}.{minor}.{patch}",
    major=st.integers(min_value=1, max_value=10),
    minor=st.integers(min_value=0, max_value=99),
    patch=st.integers(min_value=0, max_value=99),
)

# Timestamps de expiración (futuro cercano)
expires_at_strategy = st.floats(
    min_value=1_700_000_000.0,
    max_value=2_000_000_000.0,
    allow_nan=False,
    allow_infinity=False,
)


# === ESTRATEGIA COMPUESTA: GENERADOR DE UPDATES ALEATORIOS ===

# Update de config
config_update_strategy = st.fixed_dictionaries({
    "update_type": st.just("config"),
    "org_id": uuid_strategy,
    "config_hash": hash_strategy,
    "config_s3_url": s3_url_strategy,
    "scope": scope_strategy,
    "scope_id": uuid_strategy,  # Se usa solo si scope != "org"
})

# Update de certificado
cert_update_strategy = st.fixed_dictionaries({
    "update_type": st.just("cert"),
    "org_id": uuid_strategy,
    "cert_version": cert_version_strategy,
    "cert_url": s3_url_strategy,
})

# Update de MSI
msi_update_strategy = st.fixed_dictionaries({
    "update_type": st.just("msi"),
    "org_id": uuid_strategy,
    "msi_version": msi_version_strategy,
    "msi_url": s3_url_strategy,
    "msi_url_expires_at": expires_at_strategy,
})

# Cualquier tipo de update
any_update_strategy = st.one_of(
    config_update_strategy,
    cert_update_strategy,
    msi_update_strategy,
)


def _create_worker(worker_id: str) -> StateMapService:
    """
    Crea una instancia de StateMapService simulando un worker aislado.

    Se mockea Redis para capturar el payload publicado sin conexión real.
    """
    service = StateMapService(redis_url=None)
    service._worker_id = worker_id
    # Simular Redis disponible para publicar
    service._redis_available = True
    service._redis = MagicMock()
    # publish es async, retorna coroutine
    service._redis.publish = AsyncMock(return_value=1)
    return service


def _extract_published_payload(worker_a: StateMapService) -> dict | None:
    """
    Extrae el payload JSON que Worker A publicó a Redis.

    Parsea los argumentos del mock de redis.publish para obtener
    el mensaje que se habría enviado al canal state_map:update.
    """
    if not worker_a._redis.publish.called:
        return None
    # El último call a publish tiene (channel, json_payload)
    args = worker_a._redis.publish.call_args
    json_payload = args[0][1] if args[0] else args[1].get("message")
    return json.loads(json_payload)


def _simulate_redis_delivery(payload: dict) -> dict:
    """
    Simula el transporte Redis serializando/deserializando vía JSON.

    Esto es exactamente lo que ocurre en producción: el mensaje se
    serializa a JSON en el publisher y se deserializa en el subscriber.
    """
    # Simular round-trip JSON completo (serializar → deserializar)
    raw_json = json.dumps(payload)
    return {"type": "message", "data": raw_json}


class TestCrossWorkerStateSyncRoundTrip:
    """
    Property 3: Cross-worker state synchronization round-trip.

    Para cualquier state change publicado por Worker A al canal `state_map:update`
    de Redis, cuando Worker B recibe y procesa ese mensaje, el In_Memory_State_Map
    de Worker B SHALL contener valores idénticos para la organización afectada como
    el mapa de Worker A para los campos incluidos en la actualización.

    **Validates: Requirements 1.5, 8.1, 8.2**
    """

    @given(update=config_update_strategy)
    @settings(max_examples=100, deadline=None)
    def test_config_update_round_trip(self, update: dict):
        """
        Para cualquier update de config (org/vlan/workstation scope), Worker B
        reconstruye el mismo estado que Worker A tras recibir el mensaje Redis.

        **Validates: Requirements 1.5, 8.1, 8.2**
        """
        asyncio.run(self._run_config_round_trip(update))

    async def _run_config_round_trip(self, update: dict):
        """Ejecuta el round-trip de config update entre dos workers."""
        org_id = update["org_id"]
        config_hash = update["config_hash"]
        config_s3_url = update["config_s3_url"]
        scope = update["scope"]
        # scope_id solo se usa para vlan/workstation
        scope_id = update["scope_id"] if scope != "org" else None

        # Crear Worker A y aplicar update
        worker_a = _create_worker("worker_A_001")
        await worker_a.update_config(org_id, config_hash, config_s3_url, scope, scope_id)

        # Capturar payload publicado por Worker A
        payload = _extract_published_payload(worker_a)
        assert payload is not None, "Worker A no publicó payload a Redis"

        # Crear Worker B (instancia independiente, sin estado previo)
        worker_b = _create_worker("worker_B_002")

        # Simular recepción del mensaje en Worker B
        redis_message = _simulate_redis_delivery(payload)
        await worker_b._on_redis_message(redis_message)

        # Verificar que Worker B tiene el mismo estado que Worker A
        state_a = await worker_a.get_state(org_id)
        state_b = await worker_b.get_state(org_id)

        assert state_b is not None, (
            f"Worker B no tiene estado para org_id={org_id} tras recibir el mensaje"
        )

        # Verificar campos según scope
        if scope == "org":
            assert state_b.config_hash == state_a.config_hash, (
                f"config_hash no coincide. A={state_a.config_hash}, B={state_b.config_hash}"
            )
            assert state_b.config_s3_url == state_a.config_s3_url, (
                f"config_s3_url no coincide. A={state_a.config_s3_url}, B={state_b.config_s3_url}"
            )
        elif scope == "vlan":
            assert scope_id in state_b.vlan_configs, (
                f"Worker B no tiene vlan_config para scope_id={scope_id}"
            )
            vlan_a = state_a.vlan_configs[scope_id]
            vlan_b = state_b.vlan_configs[scope_id]
            assert vlan_b.config_hash == vlan_a.config_hash, (
                f"vlan config_hash no coincide. A={vlan_a.config_hash}, B={vlan_b.config_hash}"
            )
            assert vlan_b.config_s3_url == vlan_a.config_s3_url, (
                f"vlan config_s3_url no coincide. A={vlan_a.config_s3_url}, B={vlan_b.config_s3_url}"
            )
        elif scope == "workstation":
            assert scope_id in state_b.ws_configs, (
                f"Worker B no tiene ws_config para scope_id={scope_id}"
            )
            ws_a = state_a.ws_configs[scope_id]
            ws_b = state_b.ws_configs[scope_id]
            assert ws_b.config_hash == ws_a.config_hash, (
                f"ws config_hash no coincide. A={ws_a.config_hash}, B={ws_b.config_hash}"
            )
            assert ws_b.config_s3_url == ws_a.config_s3_url, (
                f"ws config_s3_url no coincide. A={ws_a.config_s3_url}, B={ws_b.config_s3_url}"
            )

    @given(update=cert_update_strategy)
    @settings(max_examples=100, deadline=None)
    def test_cert_update_round_trip(self, update: dict):
        """
        Para cualquier update de certificado, Worker B reconstruye el mismo
        cert_version y cert_url que Worker A tras recibir el mensaje Redis.

        **Validates: Requirements 1.5, 8.1, 8.2**
        """
        asyncio.run(self._run_cert_round_trip(update))

    async def _run_cert_round_trip(self, update: dict):
        """Ejecuta el round-trip de cert update entre dos workers."""
        org_id = update["org_id"]
        cert_version = update["cert_version"]
        cert_url = update["cert_url"]

        # Crear Worker A y aplicar update
        worker_a = _create_worker("worker_A_001")
        await worker_a.update_cert(org_id, cert_version, cert_url)

        # Capturar payload publicado por Worker A
        payload = _extract_published_payload(worker_a)
        assert payload is not None, "Worker A no publicó payload a Redis"

        # Crear Worker B (instancia independiente)
        worker_b = _create_worker("worker_B_002")

        # Simular recepción del mensaje
        redis_message = _simulate_redis_delivery(payload)
        await worker_b._on_redis_message(redis_message)

        # Verificar que Worker B tiene el mismo estado de cert
        state_a = await worker_a.get_state(org_id)
        state_b = await worker_b.get_state(org_id)

        assert state_b is not None, (
            f"Worker B no tiene estado para org_id={org_id} tras recibir cert update"
        )
        assert state_b.cert_version == state_a.cert_version, (
            f"cert_version no coincide. A={state_a.cert_version}, B={state_b.cert_version}"
        )
        assert state_b.cert_url == state_a.cert_url, (
            f"cert_url no coincide. A={state_a.cert_url}, B={state_b.cert_url}"
        )

    @given(update=msi_update_strategy)
    @settings(max_examples=100, deadline=None)
    def test_msi_update_round_trip(self, update: dict):
        """
        Para cualquier update de MSI, Worker B reconstruye el mismo
        msi_version, msi_url y msi_url_expires_at que Worker A.

        **Validates: Requirements 1.5, 8.1, 8.2**
        """
        asyncio.run(self._run_msi_round_trip(update))

    async def _run_msi_round_trip(self, update: dict):
        """Ejecuta el round-trip de MSI update entre dos workers."""
        org_id = update["org_id"]
        msi_version = update["msi_version"]
        msi_url = update["msi_url"]
        msi_url_expires_at = update["msi_url_expires_at"]

        # Crear Worker A y aplicar update
        worker_a = _create_worker("worker_A_001")
        await worker_a.update_msi(org_id, msi_version, msi_url, msi_url_expires_at)

        # Capturar payload publicado por Worker A
        payload = _extract_published_payload(worker_a)
        assert payload is not None, "Worker A no publicó payload a Redis"

        # Crear Worker B (instancia independiente)
        worker_b = _create_worker("worker_B_002")

        # Simular recepción del mensaje
        redis_message = _simulate_redis_delivery(payload)
        await worker_b._on_redis_message(redis_message)

        # Verificar que Worker B tiene el mismo estado de MSI
        state_a = await worker_a.get_state(org_id)
        state_b = await worker_b.get_state(org_id)

        assert state_b is not None, (
            f"Worker B no tiene estado para org_id={org_id} tras recibir MSI update"
        )
        assert state_b.msi_version == state_a.msi_version, (
            f"msi_version no coincide. A={state_a.msi_version}, B={state_b.msi_version}"
        )
        assert state_b.msi_url == state_a.msi_url, (
            f"msi_url no coincide. A={state_a.msi_url}, B={state_b.msi_url}"
        )
        assert state_b.msi_url_expires_at == state_a.msi_url_expires_at, (
            f"msi_url_expires_at no coincide. "
            f"A={state_a.msi_url_expires_at}, B={state_b.msi_url_expires_at}"
        )

    @given(updates=st.lists(any_update_strategy, min_size=2, max_size=10))
    @settings(max_examples=100, deadline=None)
    def test_multiple_updates_round_trip(self, updates: list):
        """
        Para cualquier secuencia de updates aleatorios, Worker B reconstruye
        el mismo estado final que Worker A cuando recibe todos los mensajes
        en el mismo orden.

        **Validates: Requirements 1.5, 8.1, 8.2**
        """
        asyncio.run(self._run_multiple_updates_round_trip(updates))

    async def _run_multiple_updates_round_trip(self, updates: list):
        """Ejecuta múltiples round-trips secuenciales entre dos workers."""
        worker_a = _create_worker("worker_A_001")
        worker_b = _create_worker("worker_B_002")

        for update in updates:
            update_type = update["update_type"]
            org_id = update["org_id"]

            # Reset mock para capturar solo el payload actual
            worker_a._redis.publish.reset_mock()

            # Aplicar update en Worker A según tipo
            if update_type == "config":
                scope = update["scope"]
                scope_id = update["scope_id"] if scope != "org" else None
                await worker_a.update_config(
                    org_id, update["config_hash"], update["config_s3_url"],
                    scope, scope_id,
                )
            elif update_type == "cert":
                await worker_a.update_cert(
                    org_id, update["cert_version"], update["cert_url"],
                )
            elif update_type == "msi":
                await worker_a.update_msi(
                    org_id, update["msi_version"], update["msi_url"],
                    update["msi_url_expires_at"],
                )

            # Capturar y entregar payload a Worker B
            payload = _extract_published_payload(worker_a)
            assert payload is not None, (
                f"Worker A no publicó payload para update_type={update_type}"
            )
            redis_message = _simulate_redis_delivery(payload)
            await worker_b._on_redis_message(redis_message)

        # Verificar que el estado final de Worker B coincide con Worker A
        # para todas las organizaciones que se actualizaron
        org_ids_updated = set(u["org_id"] for u in updates)
        for org_id in org_ids_updated:
            state_a = await worker_a.get_state(org_id)
            state_b = await worker_b.get_state(org_id)

            assert state_b is not None, (
                f"Worker B no tiene estado para org_id={org_id}"
            )

            # Verificar campos a nivel org
            assert state_b.config_hash == state_a.config_hash, (
                f"org {org_id}: config_hash no coincide. "
                f"A={state_a.config_hash}, B={state_b.config_hash}"
            )
            assert state_b.config_s3_url == state_a.config_s3_url, (
                f"org {org_id}: config_s3_url no coincide. "
                f"A={state_a.config_s3_url}, B={state_b.config_s3_url}"
            )
            assert state_b.cert_version == state_a.cert_version, (
                f"org {org_id}: cert_version no coincide. "
                f"A={state_a.cert_version}, B={state_b.cert_version}"
            )
            assert state_b.cert_url == state_a.cert_url, (
                f"org {org_id}: cert_url no coincide. "
                f"A={state_a.cert_url}, B={state_b.cert_url}"
            )
            assert state_b.msi_version == state_a.msi_version, (
                f"org {org_id}: msi_version no coincide. "
                f"A={state_a.msi_version}, B={state_b.msi_version}"
            )
            assert state_b.msi_url == state_a.msi_url, (
                f"org {org_id}: msi_url no coincide. "
                f"A={state_a.msi_url}, B={state_b.msi_url}"
            )
            assert state_b.msi_url_expires_at == state_a.msi_url_expires_at, (
                f"org {org_id}: msi_url_expires_at no coincide. "
                f"A={state_a.msi_url_expires_at}, B={state_b.msi_url_expires_at}"
            )

            # Verificar vlan_configs
            assert state_b.vlan_configs.keys() == state_a.vlan_configs.keys(), (
                f"org {org_id}: vlan_configs keys no coinciden. "
                f"A={set(state_a.vlan_configs.keys())}, B={set(state_b.vlan_configs.keys())}"
            )
            for vlan_id in state_a.vlan_configs:
                vlan_a = state_a.vlan_configs[vlan_id]
                vlan_b = state_b.vlan_configs[vlan_id]
                assert vlan_b.config_hash == vlan_a.config_hash, (
                    f"org {org_id}, vlan {vlan_id}: config_hash no coincide"
                )
                assert vlan_b.config_s3_url == vlan_a.config_s3_url, (
                    f"org {org_id}, vlan {vlan_id}: config_s3_url no coincide"
                )

            # Verificar ws_configs
            assert state_b.ws_configs.keys() == state_a.ws_configs.keys(), (
                f"org {org_id}: ws_configs keys no coinciden. "
                f"A={set(state_a.ws_configs.keys())}, B={set(state_b.ws_configs.keys())}"
            )
            for ws_id in state_a.ws_configs:
                ws_a = state_a.ws_configs[ws_id]
                ws_b = state_b.ws_configs[ws_id]
                assert ws_b.config_hash == ws_a.config_hash, (
                    f"org {org_id}, ws {ws_id}: config_hash no coincide"
                )
                assert ws_b.config_s3_url == ws_a.config_s3_url, (
                    f"org {org_id}, ws {ws_id}: config_s3_url no coincide"
                )
