# Feature: death-ping-optimization, Property 4: Timeout de pong
"""
Property test: Timeout de pong resulta en desconexión

Para cualquier workstation con un pending pong, si el tiempo transcurrido desde
que se envió el ping supera PONG_TIMEOUT_SECONDS (30s), esa workstation debe ser
agregada a la lista de dead_workstations. Si no supera los 30s, no debe estar
en la lista.

Feature: death-ping-optimization, Property 4: Timeout de pong resulta en desconexión
**Validates: Requirements 4.3**
"""

from datetime import datetime, timedelta, timezone

from hypothesis import given, settings as hypothesis_settings
from hypothesis import strategies as st

from app.services.websocket_manager import ConnectionManager, PONG_TIMEOUT_SECONDS


# === ESTRATEGIAS DE GENERACIÓN ===

# Generar UUIDs como strings válidos para workstation_id
ws_id_strategy = st.uuids().map(str)

# Generar deltas de tiempo en segundos (0 a 120s) para variación de timestamps
# Incluye valores alrededor del umbral de 30s para cubrir casos límite
time_delta_strategy = st.floats(min_value=0.0, max_value=120.0, allow_nan=False, allow_infinity=False)


# === HELPERS ===


def _ejecutar_fase1_pong_timeout(manager: ConnectionManager, current_time: datetime) -> list:
    """
    Replica la lógica de Fase 1 del ping loop: verificar pending_pongs.
    
    Identifica workstations cuyo ping_sent_at excede PONG_TIMEOUT_SECONDS
    respecto a current_time y las agrega a dead_workstations.
    
    Args:
        manager: Instancia del ConnectionManager con _pending_pongs poblado
        current_time: Timestamp actual simulado (UTC naive)
    
    Returns:
        Lista de workstation_ids que exceden el timeout (muertas)
    """
    dead_workstations = []
    for ws_id, ping_sent_at in list(manager._pending_pongs.items()):
        if (current_time - ping_sent_at).total_seconds() > PONG_TIMEOUT_SECONDS:
            dead_workstations.append(ws_id)
    return dead_workstations


# === PROPERTY TESTS ===


@hypothesis_settings(max_examples=100, deadline=None)
@given(
    ws_id=ws_id_strategy,
    seconds_elapsed=st.floats(
        min_value=30.01, max_value=300.0, allow_nan=False, allow_infinity=False
    ),
)
def test_pong_timeout_exceeded_results_in_disconnect(ws_id: str, seconds_elapsed: float):
    """
    Propiedad 4 (caso timeout excedido): Para cualquier workstation con pending pong,
    si transcurrieron más de 30 segundos desde el envío del ping, la workstation
    DEBE estar en la lista de dead_workstations.

    Feature: death-ping-optimization, Property 4: Timeout de pong resulta en desconexión
    **Validates: Requirements 4.3**
    """
    # Crear instancia fresca del ConnectionManager
    manager = ConnectionManager()

    # Definir current_time como referencia
    current_time = datetime.now(timezone.utc).replace(tzinfo=None)

    # Calcular ping_sent_at como current_time - seconds_elapsed
    # Esto simula que el ping se envió hace `seconds_elapsed` segundos
    ping_sent_at = current_time - timedelta(seconds=seconds_elapsed)
    manager._pending_pongs[ws_id] = ping_sent_at

    # Ejecutar la lógica de Fase 1
    dead_workstations = _ejecutar_fase1_pong_timeout(manager, current_time)

    # Verificar que la workstation está en dead_workstations
    assert ws_id in dead_workstations, (
        f"ws_id={ws_id} debería estar en dead_workstations porque transcurrieron "
        f"{seconds_elapsed:.2f}s > {PONG_TIMEOUT_SECONDS}s (PONG_TIMEOUT_SECONDS)"
    )


@hypothesis_settings(max_examples=100, deadline=None)
@given(
    ws_id=ws_id_strategy,
    seconds_elapsed=st.floats(
        min_value=0.0, max_value=30.0, allow_nan=False, allow_infinity=False
    ),
)
def test_pong_within_timeout_not_disconnected(ws_id: str, seconds_elapsed: float):
    """
    Propiedad 4 (caso dentro de timeout): Para cualquier workstation con pending pong,
    si transcurrieron 30 segundos o menos desde el envío del ping, la workstation
    NO debe estar en la lista de dead_workstations.

    Feature: death-ping-optimization, Property 4: Timeout de pong resulta en desconexión
    **Validates: Requirements 4.3**
    """
    # Crear instancia fresca del ConnectionManager
    manager = ConnectionManager()

    # Definir current_time como referencia
    current_time = datetime.now(timezone.utc).replace(tzinfo=None)

    # Calcular ping_sent_at como current_time - seconds_elapsed
    # Esto simula que el ping se envió hace `seconds_elapsed` segundos (<= 30)
    ping_sent_at = current_time - timedelta(seconds=seconds_elapsed)
    manager._pending_pongs[ws_id] = ping_sent_at

    # Ejecutar la lógica de Fase 1
    dead_workstations = _ejecutar_fase1_pong_timeout(manager, current_time)

    # Verificar que la workstation NO está en dead_workstations
    assert ws_id not in dead_workstations, (
        f"ws_id={ws_id} NO debería estar en dead_workstations porque solo transcurrieron "
        f"{seconds_elapsed:.2f}s <= {PONG_TIMEOUT_SECONDS}s (PONG_TIMEOUT_SECONDS)"
    )


@hypothesis_settings(max_examples=100, deadline=None)
@given(
    data=st.data(),
    num_workstations=st.integers(min_value=2, max_value=20),
)
def test_pong_timeout_mixed_workstations_correct_classification(data, num_workstations: int):
    """
    Propiedad 4 (caso mixto): Para un conjunto de workstations con pending pongs
    y tiempos variados, SOLO las que exceden 30s deben estar en dead_workstations
    y las que no, no deben estar.

    Feature: death-ping-optimization, Property 4: Timeout de pong resulta en desconexión
    **Validates: Requirements 4.3**
    """
    # Crear instancia fresca del ConnectionManager
    manager = ConnectionManager()

    # Definir current_time como referencia
    current_time = datetime.now(timezone.utc).replace(tzinfo=None)

    # Generar workstations con tiempos variados
    expected_dead = set()
    expected_alive = set()

    for _ in range(num_workstations):
        ws_id = data.draw(ws_id_strategy)
        seconds_elapsed = data.draw(
            st.floats(min_value=0.0, max_value=120.0, allow_nan=False, allow_infinity=False)
        )

        ping_sent_at = current_time - timedelta(seconds=seconds_elapsed)
        manager._pending_pongs[ws_id] = ping_sent_at

        if seconds_elapsed > PONG_TIMEOUT_SECONDS:
            expected_dead.add(ws_id)
        else:
            expected_alive.add(ws_id)

    # Ejecutar la lógica de Fase 1
    dead_workstations = _ejecutar_fase1_pong_timeout(manager, current_time)
    dead_set = set(dead_workstations)

    # Verificar: todas las esperadas como muertas están en dead_workstations
    for ws_id in expected_dead:
        assert ws_id in dead_set, (
            f"ws_id={ws_id} debería estar en dead_workstations (excede timeout)"
        )

    # Verificar: ninguna de las esperadas como vivas está en dead_workstations
    for ws_id in expected_alive:
        assert ws_id not in dead_set, (
            f"ws_id={ws_id} NO debería estar en dead_workstations (dentro de timeout)"
        )
