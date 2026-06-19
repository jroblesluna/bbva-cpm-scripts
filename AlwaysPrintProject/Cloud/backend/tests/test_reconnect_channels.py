"""
Property tests para Tasks 8.2 y 8.3: Reconnect channel set y re-register workstations.

**Validates: Requirements 7.3, 7.4, 10.1, 10.2**

Property 12: Reconnect subscribes exact channel set
Para cualquier estado de workstations conectadas localmente al momento de la reconexión
Redis, el conjunto de canales suscritos SHALL ser exactamente:
  {worker:{self._worker_id}, global:broadcast} ∪ {org:{org_id} for org_id con count > 0}
El número de operaciones SUBSCRIBE SHALL ser 2 + len(active_orgs), independiente del
número de workstations conectadas.

Property 13: Reconnect re-registers all local workstations
Para cualquier estado de workstations conectadas localmente al momento de la reconexión
Redis, TODAS las workstation_ids en workstation_connections.keys() SHALL ser
re-registradas en WorkerRegistry via SADD.
"""
import asyncio
from typing import Dict, List, Optional, Set
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings as hypothesis_settings, assume
from hypothesis import strategies as st

from app.services.redis_connection_manager import RedisConnectionManager


# === ESTRATEGIAS DE GENERACIÓN ===

# IDs tipo UUID
uuid_strategy = st.uuids().map(str)

# Estrategia para org_id (2-5 orgs distintas para variedad)
org_id_pool_strategy = st.lists(
    uuid_strategy, min_size=1, max_size=5, unique=True
)


@st.composite
def workstation_state_strategy(draw):
    """
    Genera un estado arbitrario de workstations conectadas localmente.

    Cada workstation tiene:
    - ws_id: UUID único
    - org_id: organización a la que pertenece
    - vlan_id: VLAN (puede ser None)

    Retorna una lista de dicts y el mapeo org_id → count esperado.
    """
    # Generar pool de orgs (1-4 distintas)
    num_orgs = draw(st.integers(min_value=1, max_value=4))
    org_ids = [draw(uuid_strategy) for _ in range(num_orgs)]

    # Generar entre 1 y 15 workstations
    num_ws = draw(st.integers(min_value=1, max_value=15))

    workstations = []
    ws_id_set: Set[str] = set()

    for _ in range(num_ws):
        ws_id = draw(uuid_strategy)
        assume(ws_id not in ws_id_set)
        ws_id_set.add(ws_id)

        org_id = draw(st.sampled_from(org_ids))
        vlan_id = draw(st.one_of(st.none(), uuid_strategy))

        workstations.append({
            "ws_id": ws_id,
            "org_id": org_id,
            "vlan_id": vlan_id,
        })

    return workstations


@st.composite
def mixed_org_state_strategy(draw):
    """
    Genera estado con orgs que tienen count > 0 y orgs que ya llegaron a 0.

    Útil para verificar que solo las orgs con count > 0 se re-suscriben.
    Incluye orgs "vacías" (count=0) en _org_ws_count para probar filtrado.
    """
    # Orgs activas (con workstations conectadas)
    active_orgs = draw(st.lists(uuid_strategy, min_size=1, max_size=4, unique=True))

    # Orgs inactivas (count=0, residuales en el dict)
    inactive_orgs = draw(st.lists(uuid_strategy, min_size=0, max_size=3, unique=True))
    # Asegurar que no hay overlap
    inactive_orgs = [o for o in inactive_orgs if o not in active_orgs]

    # Generar workstations solo para orgs activas
    workstations = []
    ws_id_set: Set[str] = set()

    for org_id in active_orgs:
        # Al menos 1 workstation por org activa
        num_ws = draw(st.integers(min_value=1, max_value=5))
        for _ in range(num_ws):
            ws_id = draw(uuid_strategy)
            assume(ws_id not in ws_id_set)
            ws_id_set.add(ws_id)
            workstations.append({
                "ws_id": ws_id,
                "org_id": org_id,
                "vlan_id": draw(st.one_of(st.none(), uuid_strategy)),
            })

    return {
        "workstations": workstations,
        "active_orgs": active_orgs,
        "inactive_orgs": inactive_orgs,
    }


def _create_manager_with_state(
    workstations: list,
    inactive_orgs: Optional[List[str]] = None,
    worker_id: str = "worker_12345",
) -> RedisConnectionManager:
    """
    Crea un RedisConnectionManager con estado pre-poblado simulando
    un estado antes de una desconexión Redis.

    Args:
        workstations: Lista de dicts con ws_id, org_id, vlan_id
        inactive_orgs: Orgs con count=0 residuales en _org_ws_count
        worker_id: ID del worker

    Returns:
        Manager con estado local configurado y _redis_available=False
    """
    manager = RedisConnectionManager(redis_url="redis://fake:6379/0")
    manager._worker_id = worker_id
    manager._redis_available = False

    # Poblar estado local
    for ws_info in workstations:
        ws_id = ws_info["ws_id"]
        org_id = ws_info["org_id"]
        vlan_id = ws_info["vlan_id"]

        # Mock WebSocket
        mock_ws = AsyncMock()
        mock_ws.send_json = AsyncMock()
        manager.workstation_connections[ws_id] = mock_ws
        manager.org_ids[ws_id] = org_id
        manager._ws_vlan_ids[ws_id] = vlan_id

        # Actualizar org count
        manager._org_ws_count[org_id] = manager._org_ws_count.get(org_id, 0) + 1

    # Agregar orgs inactivas (count=0) si se proporcionan
    if inactive_orgs:
        for org_id in inactive_orgs:
            if org_id not in manager._org_ws_count:
                manager._org_ws_count[org_id] = 0

    return manager


async def _simulate_reconnect(manager: RedisConnectionManager) -> dict:
    """
    Simula una reconexión Redis exitosa, capturando las operaciones realizadas.

    Monkeypatchea:
    - asyncio.sleep → coroutine inmediata (no esperar)
    - redis.ping → éxito inmediato
    - pubsub.subscribe → captura canales suscritos
    - WorkerRegistry.register_workstation → captura ws_ids registrados

    Returns:
        Dict con:
        - subscribed_channels: Set de canales suscritos
        - registered_workstations: Lista de ws_ids re-registrados
        - subscribe_call_count: Número total de llamadas a subscribe
    """
    subscribed_channels: Set[str] = set()
    registered_workstations: List[str] = []
    subscribe_call_count = 0

    # Mock de PubSub que captura subscribe
    mock_pubsub = AsyncMock()

    async def mock_subscribe(*channels, **kwargs):
        nonlocal subscribe_call_count
        for ch in channels:
            subscribed_channels.add(ch)
            subscribe_call_count += 1

    mock_pubsub.subscribe = mock_subscribe

    # Mock de Redis que responde a ping exitosamente
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

    # Mock de WorkerRegistry que captura register_workstation
    mock_registry = AsyncMock()

    async def mock_register_ws(ws_id: str):
        registered_workstations.append(ws_id)

    mock_registry.register_workstation = mock_register_ws

    # Configurar el manager para reconexión
    manager._redis = mock_redis

    # Coroutine no-op para reemplazar asyncio.sleep
    async def noop_sleep(delay):
        return

    # Mock de _redis_listener que es una coroutine simple
    async def noop_listener():
        return

    # Patchear asyncio.sleep en el módulo que lo usa
    # Patchear WorkerRegistry para capturar register_workstation
    with patch(
        "app.services.redis_connection_manager.asyncio.sleep",
        side_effect=noop_sleep,
    ), patch(
        "app.services.redis_connection_manager.WorkerRegistry",
        return_value=mock_registry,
    ):
        # Mock de _redis_listener para que create_task no lance un loop infinito
        manager._redis_listener = noop_listener
        await manager._handle_redis_reconnect()

    return {
        "subscribed_channels": subscribed_channels,
        "registered_workstations": registered_workstations,
        "subscribe_call_count": subscribe_call_count,
    }


# === PROPERTY TESTS: RECONNECT SUBSCRIBES EXACT CHANNEL SET (Property 12) ===


class TestReconnectSubscribesExactChannelSet:
    """
    Property 12: Reconnect subscribes exact channel set.

    Tras reconexión, los canales suscritos = {worker:{id}, global:broadcast}
    ∪ {org:{org_id} for org_id con count > 0}.
    Número de operaciones SUBSCRIBE = 2 + len(active_orgs).

    **Validates: Requirements 7.3, 10.1, 10.2**
    """

    @hypothesis_settings(max_examples=150, deadline=None)
    @given(workstations=workstation_state_strategy())
    @pytest.mark.asyncio
    async def test_reconnect_subscribes_fixed_channels(self, workstations: list):
        """
        Propiedad: La reconexión SIEMPRE suscribe worker:{id} y global:broadcast.

        Independientemente del estado de workstations, estos 2 canales fijos
        siempre se suscriben.

        **Validates: Requirements 7.3, 10.1, 10.2**
        """
        worker_id = "worker_99999"
        manager = _create_manager_with_state(workstations, worker_id=worker_id)

        result = await _simulate_reconnect(manager)

        # Canales fijos SIEMPRE presentes
        assert f"worker:{worker_id}" in result["subscribed_channels"], (
            f"Canal worker:{worker_id} debe suscribirse tras reconexión. "
            f"Canales suscritos: {result['subscribed_channels']}"
        )
        assert "global:broadcast" in result["subscribed_channels"], (
            f"Canal global:broadcast debe suscribirse tras reconexión. "
            f"Canales suscritos: {result['subscribed_channels']}"
        )

    @hypothesis_settings(max_examples=150, deadline=None)
    @given(state=mixed_org_state_strategy())
    @pytest.mark.asyncio
    async def test_reconnect_subscribes_only_active_org_channels(self, state: dict):
        """
        Propiedad: Solo se suscriben canales org:{id} para organizaciones con count > 0.

        Orgs con count=0 (residuales en el dict) NO deben generar SUBSCRIBE.

        **Validates: Requirements 7.3, 10.1, 10.2**
        """
        worker_id = "worker_77777"
        manager = _create_manager_with_state(
            state["workstations"],
            inactive_orgs=state["inactive_orgs"],
            worker_id=worker_id,
        )

        result = await _simulate_reconnect(manager)

        # Verificar que orgs activas SÍ tienen sus canales suscritos
        for org_id in state["active_orgs"]:
            expected_channel = f"org:{org_id}"
            assert expected_channel in result["subscribed_channels"], (
                f"Canal {expected_channel} debería suscribirse (org tiene workstations activas). "
                f"Canales suscritos: {result['subscribed_channels']}"
            )

        # Verificar que orgs inactivas NO tienen canales suscritos
        for org_id in state["inactive_orgs"]:
            unexpected_channel = f"org:{org_id}"
            assert unexpected_channel not in result["subscribed_channels"], (
                f"Canal {unexpected_channel} NO debería suscribirse (org count=0). "
                f"Canales suscritos: {result['subscribed_channels']}"
            )

    @hypothesis_settings(max_examples=150, deadline=None)
    @given(workstations=workstation_state_strategy())
    @pytest.mark.asyncio
    async def test_reconnect_channel_set_is_exact(self, workstations: list):
        """
        Propiedad: El conjunto de canales suscritos es EXACTAMENTE el esperado.

        No hay canales extra ni canales faltantes. El set completo es:
        {worker:{id}, global:broadcast} ∪ {org:{org_id} for org_id con count > 0}

        **Validates: Requirements 7.3, 10.1, 10.2**
        """
        worker_id = "worker_55555"
        manager = _create_manager_with_state(workstations, worker_id=worker_id)

        result = await _simulate_reconnect(manager)

        # Calcular el set esperado
        active_orgs = {
            org_id for org_id, count in manager._org_ws_count.items() if count > 0
        }
        expected_channels = {f"worker:{worker_id}", "global:broadcast"}
        expected_channels |= {f"org:{org_id}" for org_id in active_orgs}

        assert result["subscribed_channels"] == expected_channels, (
            f"El conjunto de canales suscritos no coincide con el esperado.\n"
            f"Esperado: {expected_channels}\n"
            f"Obtenido: {result['subscribed_channels']}\n"
            f"Diferencia (faltantes): {expected_channels - result['subscribed_channels']}\n"
            f"Diferencia (sobrantes): {result['subscribed_channels'] - expected_channels}"
        )

    @hypothesis_settings(max_examples=150, deadline=None)
    @given(workstations=workstation_state_strategy())
    @pytest.mark.asyncio
    async def test_reconnect_subscribe_count_independent_of_workstations(
        self, workstations: list
    ):
        """
        Propiedad: El número de operaciones SUBSCRIBE = 2 + len(active_orgs),
        independiente del número de workstations conectadas.

        Esto garantiza O(1 + N_orgs_activas) y no O(N_workstations).

        **Validates: Requirements 7.3, 10.1, 10.2**
        """
        worker_id = "worker_33333"
        manager = _create_manager_with_state(workstations, worker_id=worker_id)

        result = await _simulate_reconnect(manager)

        # Contar orgs activas
        active_orgs_count = sum(
            1 for count in manager._org_ws_count.values() if count > 0
        )

        # El número de subscribe ops debe ser 2 (fijos) + N_orgs_activas
        expected_subscribe_count = 2 + active_orgs_count
        assert result["subscribe_call_count"] == expected_subscribe_count, (
            f"Número de SUBSCRIBE ops debería ser 2 + {active_orgs_count} = "
            f"{expected_subscribe_count}, pero fue {result['subscribe_call_count']}. "
            f"Workstations conectadas: {len(workstations)}. "
            f"Las suscripciones NO deben escalar con el número de workstations."
        )

    @hypothesis_settings(max_examples=100, deadline=None)
    @given(workstations=workstation_state_strategy())
    @pytest.mark.asyncio
    async def test_reconnect_no_per_workstation_subscribe(self, workstations: list):
        """
        Propiedad: La reconexión NO genera suscripciones per-workstation.

        Ningún canal suscrito debe coincidir con el patrón ws:{workstation_id}.

        **Validates: Requirements 7.3, 10.1, 10.2**
        """
        worker_id = "worker_11111"
        manager = _create_manager_with_state(workstations, worker_id=worker_id)

        result = await _simulate_reconnect(manager)

        # Verificar que ningún canal tiene prefijo ws:
        ws_channels = {
            ch for ch in result["subscribed_channels"] if ch.startswith("ws:")
        }
        assert len(ws_channels) == 0, (
            f"La reconexión NO debe suscribir canales per-workstation. "
            f"Canales ws: encontrados: {ws_channels}"
        )

        # Verificar que ningún canal tiene prefijo cmd_response:
        cmd_channels = {
            ch for ch in result["subscribed_channels"]
            if ch.startswith("cmd_response:")
        }
        assert len(cmd_channels) == 0, (
            f"La reconexión NO debe suscribir canales per-command. "
            f"Canales cmd_response: encontrados: {cmd_channels}"
        )


# === PROPERTY TESTS: RECONNECT RE-REGISTERS ALL WORKSTATIONS (Property 13) ===


class TestReconnectReregistersAllWorkstations:
    """
    Property 13: Reconnect re-registers all local workstations.

    Tras reconexión, TODAS las workstation_ids en workstation_connections
    son re-registradas en WorkerRegistry via SADD.

    **Validates: Requirements 7.4**
    """

    @hypothesis_settings(max_examples=150, deadline=None)
    @given(workstations=workstation_state_strategy())
    @pytest.mark.asyncio
    async def test_all_workstations_reregistered(self, workstations: list):
        """
        Propiedad: Tras reconexión, TODAS las workstations locales se re-registran.

        El número de llamadas a register_workstation debe ser exactamente
        igual al número de workstations en workstation_connections.

        **Validates: Requirements 7.4**
        """
        worker_id = "worker_22222"
        manager = _create_manager_with_state(workstations, worker_id=worker_id)

        result = await _simulate_reconnect(manager)

        # Verificar que se re-registraron TODAS las workstations
        expected_ws_ids = set(manager.workstation_connections.keys())
        registered_ws_ids = set(result["registered_workstations"])

        assert registered_ws_ids == expected_ws_ids, (
            f"No todas las workstations fueron re-registradas tras reconexión.\n"
            f"Esperadas: {expected_ws_ids}\n"
            f"Registradas: {registered_ws_ids}\n"
            f"Faltantes: {expected_ws_ids - registered_ws_ids}\n"
            f"Sobrantes: {registered_ws_ids - expected_ws_ids}"
        )

    @hypothesis_settings(max_examples=150, deadline=None)
    @given(workstations=workstation_state_strategy())
    @pytest.mark.asyncio
    async def test_register_count_equals_workstation_count(self, workstations: list):
        """
        Propiedad: El número de llamadas a register_workstation es exactamente
        igual al número de workstations conectadas localmente.

        No se registra de más (duplicados) ni de menos (omisiones).

        **Validates: Requirements 7.4**
        """
        worker_id = "worker_44444"
        manager = _create_manager_with_state(workstations, worker_id=worker_id)

        result = await _simulate_reconnect(manager)

        assert len(result["registered_workstations"]) == len(workstations), (
            f"Número de re-registros ({len(result['registered_workstations'])}) "
            f"no coincide con workstations conectadas ({len(workstations)}). "
            f"Cada workstation debe re-registrarse exactamente una vez."
        )

    @hypothesis_settings(max_examples=150, deadline=None)
    @given(workstations=workstation_state_strategy())
    @pytest.mark.asyncio
    async def test_each_workstation_registered_exactly_once(self, workstations: list):
        """
        Propiedad: Cada workstation se re-registra exactamente UNA vez.

        No hay duplicados en las llamadas a register_workstation.

        **Validates: Requirements 7.4**
        """
        worker_id = "worker_66666"
        manager = _create_manager_with_state(workstations, worker_id=worker_id)

        result = await _simulate_reconnect(manager)

        # Verificar que no hay duplicados
        registered_list = result["registered_workstations"]
        registered_set = set(registered_list)

        assert len(registered_list) == len(registered_set), (
            f"Hay workstations registradas más de una vez. "
            f"Total registros: {len(registered_list)}, "
            f"Únicos: {len(registered_set)}. "
            f"Duplicados: {[ws for ws in registered_list if registered_list.count(ws) > 1]}"
        )

    @hypothesis_settings(max_examples=100, deadline=None)
    @given(state=mixed_org_state_strategy())
    @pytest.mark.asyncio
    async def test_reregister_independent_of_org_state(self, state: dict):
        """
        Propiedad: La re-registración de workstations es independiente del
        estado de organizaciones (activas/inactivas).

        Incluso con orgs inactivas (count=0) residuales, todas las workstations
        de orgs activas se re-registran correctamente.

        **Validates: Requirements 7.4**
        """
        worker_id = "worker_88888"
        manager = _create_manager_with_state(
            state["workstations"],
            inactive_orgs=state["inactive_orgs"],
            worker_id=worker_id,
        )

        result = await _simulate_reconnect(manager)

        # Todas las workstations (solo de orgs activas, pues inactive no tienen ws)
        expected_ws_ids = {ws["ws_id"] for ws in state["workstations"]}
        registered_ws_ids = set(result["registered_workstations"])

        assert registered_ws_ids == expected_ws_ids, (
            f"Las workstations re-registradas no coinciden con las conectadas.\n"
            f"Orgs activas: {state['active_orgs']}\n"
            f"Orgs inactivas: {state['inactive_orgs']}\n"
            f"Faltantes: {expected_ws_ids - registered_ws_ids}"
        )
