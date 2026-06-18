# Feature: websocket-scaling-redis, Property 10: Worker Registry Lifecycle
"""
Property test: Worker Registry Lifecycle

Para cualquier secuencia de operaciones register/unregister sobre un WorkerRegistry,
se verifica que:
1. Después de register_workstation(ws_id), ws_id aparece en el SET Redis `workers:{worker_id}:workstations`
2. Después de unregister_workstation(ws_id), ws_id NO aparece en el SET
3. Después de cleanup_on_shutdown(), el SET está vacío (todas las workstations eliminadas)

Se generan workstation_ids aleatorios (UUIDs) y secuencias de operaciones
register/unregister para verificar la propiedad en todos los casos.

Feature: websocket-scaling-redis, Property 10: Worker Registry Lifecycle
**Validates: Requirements 2.2, 2.3**
"""

import asyncio
from typing import Dict, List, Set
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings as hypothesis_settings, assume
from hypothesis import strategies as st

from app.services.worker_registry import WorkerRegistry


# === ESTRATEGIAS DE GENERACIÓN ===

# Generar UUIDs como strings para workstation_id
ws_id_strategy = st.uuids().map(str)

# Generar worker_id como string
worker_id_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
    min_size=5,
    max_size=20,
).map(lambda s: f"worker_{s}")

# TTL entre 10 y 120 segundos
ttl_strategy = st.integers(min_value=10, max_value=120)


# === MOCK DE REDIS QUE SIMULA SETs ===


class MockRedisWithSets:
    """
    Mock de Redis que simula las operaciones de SET y pipeline
    para poder verificar el estado real del SET tras cada operación.
    """

    def __init__(self):
        # Almacenamiento interno: key -> set de valores
        self._sets: Dict[str, Set[str]] = {}
        # Almacenamiento de keys simples
        self._keys: Dict[str, str] = {}
        # TTLs registrados (para verificar que se configuran)
        self._ttls: Dict[str, int] = {}

    async def sadd(self, key: str, *values) -> int:
        """Agrega valores a un SET."""
        if key not in self._sets:
            self._sets[key] = set()
        added = 0
        for v in values:
            if v not in self._sets[key]:
                self._sets[key].add(v)
                added += 1
        return added

    async def srem(self, key: str, *values) -> int:
        """Remueve valores de un SET."""
        if key not in self._sets:
            return 0
        removed = 0
        for v in values:
            if v in self._sets[key]:
                self._sets[key].discard(v)
                removed += 1
        # Si el set queda vacío, eliminarlo (comportamiento Redis)
        if not self._sets[key]:
            del self._sets[key]
        return removed

    async def sismember(self, key: str, value: str) -> bool:
        """Verifica si un valor pertenece al SET."""
        return key in self._sets and value in self._sets[key]

    async def smembers(self, key: str) -> Set[str]:
        """Retorna todos los miembros del SET."""
        return self._sets.get(key, set()).copy()

    async def expire(self, key: str, seconds: int) -> bool:
        """Simula configuración de TTL."""
        self._ttls[key] = seconds
        return True

    async def set(self, key: str, value: str, ex: int = None) -> bool:
        """Simula SET con TTL opcional."""
        self._keys[key] = value
        if ex:
            self._ttls[key] = ex
        return True

    async def delete(self, *keys) -> int:
        """Elimina keys (tanto SETs como simples)."""
        deleted = 0
        for key in keys:
            if key in self._sets:
                del self._sets[key]
                deleted += 1
            if key in self._keys:
                del self._keys[key]
                deleted += 1
            if key in self._ttls:
                del self._ttls[key]
        return deleted

    def pipeline(self):
        """Retorna un pipeline mock que acumula y ejecuta comandos."""
        return MockPipeline(self)


class MockPipeline:
    """Pipeline mock que acumula operaciones y las ejecuta en batch."""

    def __init__(self, redis: MockRedisWithSets):
        self._redis = redis
        self._commands: List = []

    def sadd(self, key: str, *values):
        """Encola operación sadd."""
        self._commands.append(("sadd", key, values))
        return self

    def srem(self, key: str, *values):
        """Encola operación srem."""
        self._commands.append(("srem", key, values))
        return self

    def expire(self, key: str, seconds: int):
        """Encola operación expire."""
        self._commands.append(("expire", key, seconds))
        return self

    def set(self, key: str, value: str, ex: int = None):
        """Encola operación set."""
        self._commands.append(("set", key, value, ex))
        return self

    def delete(self, *keys):
        """Encola operación delete."""
        self._commands.append(("delete", keys))
        return self

    async def execute(self) -> List:
        """Ejecuta todas las operaciones encoladas en orden."""
        results = []
        for cmd in self._commands:
            if cmd[0] == "sadd":
                result = await self._redis.sadd(cmd[1], *cmd[2])
                results.append(result)
            elif cmd[0] == "srem":
                result = await self._redis.srem(cmd[1], *cmd[2])
                results.append(result)
            elif cmd[0] == "expire":
                result = await self._redis.expire(cmd[1], cmd[2])
                results.append(result)
            elif cmd[0] == "set":
                result = await self._redis.set(cmd[1], cmd[2], ex=cmd[3])
                results.append(result)
            elif cmd[0] == "delete":
                result = await self._redis.delete(*cmd[1])
                results.append(result)
        self._commands.clear()
        return results


# === OPERACIONES PARA STATEFUL TESTING ===

# Estrategia: secuencia de operaciones (register o unregister) sobre un pool de ws_ids
@st.composite
def operation_sequence(draw):
    """
    Genera una secuencia de operaciones register/unregister sobre
    un conjunto de workstation_ids generados aleatoriamente.
    """
    # Generar pool de workstation_ids disponibles (2 a 8)
    num_ws = draw(st.integers(min_value=2, max_value=8))
    ws_ids = [draw(ws_id_strategy) for _ in range(num_ws)]
    # Asegurar que son únicos
    ws_ids = list(set(ws_ids))
    assume(len(ws_ids) >= 2)

    # Generar secuencia de operaciones (3 a 15)
    num_ops = draw(st.integers(min_value=3, max_value=15))
    operations = []
    for _ in range(num_ops):
        op_type = draw(st.sampled_from(["register", "unregister"]))
        ws_id = draw(st.sampled_from(ws_ids))
        operations.append((op_type, ws_id))

    return ws_ids, operations


# === PROPERTY TESTS ===


@hypothesis_settings(max_examples=100, deadline=None)
@given(ws_ids=st.lists(ws_id_strategy, min_size=1, max_size=10, unique=True))
async def test_register_makes_workstation_visible_in_set(ws_ids: List[str]):
    """
    Propiedad: Después de register_workstation(ws_id), ws_id DEBE aparecer
    en el SET Redis `workers:{worker_id}:workstations`.

    Feature: websocket-scaling-redis, Property 10: Worker Registry Lifecycle
    **Validates: Requirements 2.2, 2.3**
    """
    # Preparar mock Redis y WorkerRegistry
    mock_redis = MockRedisWithSets()
    worker_id = "worker_test_12345"

    with patch("app.services.worker_registry.settings") as mock_settings:
        mock_settings.WORKER_REGISTRY_TTL = 60
        registry = WorkerRegistry(redis=mock_redis, worker_id=worker_id, ttl=60)

    # Registrar cada workstation y verificar que aparece en el SET
    for ws_id in ws_ids:
        await registry.register_workstation(ws_id)

        # Verificar que ws_id está en el SET
        is_member = await mock_redis.sismember(registry._workstations_key, ws_id)
        assert is_member, (
            f"Después de register_workstation('{ws_id}'), el ws_id debería "
            f"aparecer en el SET '{registry._workstations_key}' pero no aparece"
        )

    # Verificar que TODOS los ws_ids registrados están presentes
    members = await mock_redis.smembers(registry._workstations_key)
    assert set(ws_ids) == members, (
        f"El SET debería contener exactamente {set(ws_ids)} "
        f"pero contiene {members}"
    )


@hypothesis_settings(max_examples=100, deadline=None)
@given(ws_ids=st.lists(ws_id_strategy, min_size=1, max_size=10, unique=True))
async def test_unregister_removes_workstation_from_set(ws_ids: List[str]):
    """
    Propiedad: Después de unregister_workstation(ws_id), ws_id NO DEBE
    aparecer en el SET Redis `workers:{worker_id}:workstations`.

    Feature: websocket-scaling-redis, Property 10: Worker Registry Lifecycle
    **Validates: Requirements 2.2, 2.3**
    """
    # Preparar mock Redis y WorkerRegistry
    mock_redis = MockRedisWithSets()
    worker_id = "worker_test_67890"

    with patch("app.services.worker_registry.settings") as mock_settings:
        mock_settings.WORKER_REGISTRY_TTL = 60
        registry = WorkerRegistry(redis=mock_redis, worker_id=worker_id, ttl=60)

    # Primero registrar todas las workstations
    for ws_id in ws_ids:
        await registry.register_workstation(ws_id)

    # Desregistrar cada una y verificar que desaparece
    for ws_id in ws_ids:
        await registry.unregister_workstation(ws_id)

        # Verificar que ws_id ya NO está en el SET
        is_member = await mock_redis.sismember(registry._workstations_key, ws_id)
        assert not is_member, (
            f"Después de unregister_workstation('{ws_id}'), el ws_id NO debería "
            f"aparecer en el SET '{registry._workstations_key}' pero sigue presente"
        )


@hypothesis_settings(max_examples=100, deadline=None)
@given(ws_ids=st.lists(ws_id_strategy, min_size=1, max_size=10, unique=True))
async def test_cleanup_on_shutdown_empties_set(ws_ids: List[str]):
    """
    Propiedad: Después de cleanup_on_shutdown(), el SET `workers:{worker_id}:workstations`
    DEBE estar completamente vacío (todas las workstations eliminadas).

    Feature: websocket-scaling-redis, Property 10: Worker Registry Lifecycle
    **Validates: Requirements 2.2, 2.3**
    """
    # Preparar mock Redis y WorkerRegistry
    mock_redis = MockRedisWithSets()
    worker_id = "worker_shutdown_test"

    with patch("app.services.worker_registry.settings") as mock_settings:
        mock_settings.WORKER_REGISTRY_TTL = 60
        registry = WorkerRegistry(redis=mock_redis, worker_id=worker_id, ttl=60)

    # Registrar múltiples workstations
    for ws_id in ws_ids:
        await registry.register_workstation(ws_id)

    # Verificar que las workstations están registradas
    members_before = await mock_redis.smembers(registry._workstations_key)
    assert len(members_before) == len(ws_ids), (
        f"Antes de cleanup, el SET debería tener {len(ws_ids)} elementos "
        f"pero tiene {len(members_before)}"
    )

    # Ejecutar cleanup_on_shutdown
    await registry.cleanup_on_shutdown()

    # Verificar que el SET está vacío (key eliminada)
    members_after = await mock_redis.smembers(registry._workstations_key)
    assert len(members_after) == 0, (
        f"Después de cleanup_on_shutdown(), el SET debería estar vacío "
        f"pero contiene {members_after}"
    )


@hypothesis_settings(max_examples=100, deadline=None)
@given(data=operation_sequence())
async def test_lifecycle_sequence_consistency(data):
    """
    Propiedad: Para cualquier secuencia arbitraria de operaciones register/unregister,
    el estado del SET Redis siempre refleja correctamente qué workstations están
    activamente registradas.

    Después de toda la secuencia, cleanup_on_shutdown() SIEMPRE deja el SET vacío.

    Feature: websocket-scaling-redis, Property 10: Worker Registry Lifecycle
    **Validates: Requirements 2.2, 2.3**
    """
    ws_ids, operations = data

    # Preparar mock Redis y WorkerRegistry
    mock_redis = MockRedisWithSets()
    worker_id = "worker_lifecycle_test"

    with patch("app.services.worker_registry.settings") as mock_settings:
        mock_settings.WORKER_REGISTRY_TTL = 60
        registry = WorkerRegistry(redis=mock_redis, worker_id=worker_id, ttl=60)

    # Rastrear estado esperado localmente
    expected_registered: Set[str] = set()

    # Ejecutar secuencia de operaciones verificando invariantes
    for op_type, ws_id in operations:
        if op_type == "register":
            await registry.register_workstation(ws_id)
            expected_registered.add(ws_id)
        else:  # unregister
            await registry.unregister_workstation(ws_id)
            expected_registered.discard(ws_id)

        # Verificar invariante: el SET refleja el estado esperado
        actual_members = await mock_redis.smembers(registry._workstations_key)
        assert actual_members == expected_registered, (
            f"Después de {op_type}('{ws_id}'), el SET debería ser "
            f"{expected_registered} pero es {actual_members}"
        )

    # Verificar que cleanup_on_shutdown deja el SET vacío siempre
    await registry.cleanup_on_shutdown()
    final_members = await mock_redis.smembers(registry._workstations_key)
    assert len(final_members) == 0, (
        f"Después de cleanup_on_shutdown(), el SET debería estar vacío "
        f"pero contiene {final_members}"
    )
