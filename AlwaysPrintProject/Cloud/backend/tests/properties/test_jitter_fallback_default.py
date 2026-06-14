"""
Property test: Invalid JitterWindowSeconds falls back to default.

Verifica que cuando el valor de JitterWindowSeconds está fuera del rango
válido [5, 300], el sistema usa el valor por defecto (30) para todos los
cálculos de delay.

**Validates: Requirements 3.5, 5.4**

Feature: reconnection-jitter, Property 7: Invalid JitterWindowSeconds falls back to default
"""

import random
from datetime import datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from tests.properties.jitter_calculator import (
    normalize_jitter_window,
    compute_startup_delay,
    compute_reconnection_delay,
    DEFAULT_JITTER_WINDOW_SECONDS,
    MIN_JITTER_WINDOW,
    MAX_JITTER_WINDOW,
)


# === ESTRATEGIAS DE GENERACIÓN ===

# Valores de jitter window INVÁLIDOS: fuera de [5, 300]
# Incluye valores por debajo del mínimo y por encima del máximo
_invalid_window_below = st.integers(min_value=-10000, max_value=MIN_JITTER_WINDOW - 1)
_invalid_window_above = st.integers(min_value=MAX_JITTER_WINDOW + 1, max_value=10000)
_invalid_jitter_window = st.one_of(_invalid_window_below, _invalid_window_above)

# Diferencia temporal en segundos para un timestamp reciente: [0, 59.9]
_recent_delta_seconds = st.floats(
    min_value=0.0, max_value=59.9, allow_nan=False, allow_infinity=False
)

# Semilla para el generador aleatorio (testing determinístico)
_seed = st.integers(min_value=0, max_value=2**31 - 1)


# === PROPERTY 7: INVALID JITTER WINDOW FALLS BACK TO DEFAULT ===


class TestInvalidJitterWindowFallsBackToDefault:
    """
    Property 7: Invalid JitterWindowSeconds falls back to default.

    Para cualquier valor de JitterWindowSeconds fuera del rango [5, 300]
    (incluyendo cuando la clave está ausente), el sistema SHALL usar 30
    como ventana de jitter efectiva para todos los cálculos de delay.

    **Validates: Requirements 3.5, 5.4**
    """

    @given(invalid_window=_invalid_jitter_window)
    @settings(max_examples=100, deadline=None)
    def test_normalize_retorna_default_para_valor_invalido(
        self, invalid_window: int
    ):
        """
        Cuando el jitter window está fuera de [5, 300], normalize_jitter_window
        retorna el valor por defecto (30).

        **Validates: Requirements 3.5, 5.4**
        """
        # Normalizar el valor inválido
        effective = normalize_jitter_window(invalid_window)

        # Verificar que se usa el valor por defecto
        assert effective == DEFAULT_JITTER_WINDOW_SECONDS, (
            f"Se esperaba effective={DEFAULT_JITTER_WINDOW_SECONDS} para "
            f"invalid_window={invalid_window}, pero se obtuvo effective={effective}"
        )

    @given(
        invalid_window=_invalid_jitter_window,
        delta_seconds=_recent_delta_seconds,
        seed=_seed,
    )
    @settings(max_examples=100, deadline=None)
    def test_startup_delay_usa_default_con_window_invalido(
        self, invalid_window: int, delta_seconds: float, seed: int
    ):
        """
        Cuando el jitter window es inválido y hay un timestamp reciente,
        compute_startup_delay produce un delay en [0, 30000) ms
        (usa el default 30 como ventana efectiva).

        **Validates: Requirements 3.5, 5.4**
        """
        # Escenario: timestamp reciente con window inválido
        utc_now = datetime(2026, 6, 15, 12, 0, 0)
        last_update = utc_now - timedelta(seconds=delta_seconds)

        rng = random.Random(seed)

        delay_ms, reason = compute_startup_delay(
            utc_now=utc_now,
            last_update_timestamp=last_update,
            last_restart_timestamp=None,
            jitter_window_seconds=invalid_window,
            rng=rng,
        )

        # El delay debe estar en [0, DEFAULT*1000) = [0, 30000)
        max_delay = DEFAULT_JITTER_WINDOW_SECONDS * 1000
        assert 0 <= delay_ms < max_delay, (
            f"delay_ms={delay_ms} fuera de [0, {max_delay}) "
            f"con invalid_window={invalid_window}, delta={delta_seconds}s. "
            f"Se esperaba uso del default={DEFAULT_JITTER_WINDOW_SECONDS}"
        )

        # Verificar que se aplicó jitter (timestamp reciente presente)
        assert reason is not None, (
            f"Se esperaba reason no-None con timestamp reciente "
            f"(delta={delta_seconds}s), pero se obtuvo reason=None"
        )

    @given(
        invalid_window=_invalid_jitter_window,
        seed=_seed,
    )
    @settings(max_examples=100, deadline=None)
    def test_reconnection_delay_usa_default_con_window_invalido(
        self, invalid_window: int, seed: int
    ):
        """
        Cuando el jitter window es inválido, compute_reconnection_delay
        produce un delay en [0, 30000) ms (usa el default 30).

        **Validates: Requirements 3.5, 5.4**
        """
        rng = random.Random(seed)

        delay_ms = compute_reconnection_delay(
            jitter_window_seconds=invalid_window,
            rng=rng,
        )

        # El delay debe estar en [0, DEFAULT*1000) = [0, 30000)
        max_delay = DEFAULT_JITTER_WINDOW_SECONDS * 1000
        assert 0 <= delay_ms < max_delay, (
            f"delay_ms={delay_ms} fuera de [0, {max_delay}) "
            f"con invalid_window={invalid_window}. "
            f"Se esperaba uso del default={DEFAULT_JITTER_WINDOW_SECONDS}"
        )
