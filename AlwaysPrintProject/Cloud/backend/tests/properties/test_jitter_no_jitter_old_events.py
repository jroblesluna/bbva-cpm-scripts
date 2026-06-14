"""
Property test: No jitter for old trigger events.

Verifica que cuando un timestamp de evento (update o restart) tiene 60 o más
segundos de antigüedad respecto al momento actual, el delay calculado es 0.

**Validates: Requirements 3.2, 4.2**

Feature: reconnection-jitter, Property 4: No jitter for old trigger events
"""

from datetime import datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from tests.properties.jitter_calculator import (
    compute_startup_delay,
    MIN_JITTER_WINDOW,
    MAX_JITTER_WINDOW,
    RECENT_THRESHOLD_SECONDS,
)


# === ESTRATEGIAS DE GENERACIÓN ===

# Ventana de jitter válida: enteros en [5, 300]
_jitter_window = st.integers(min_value=MIN_JITTER_WINDOW, max_value=MAX_JITTER_WINDOW)

# Delta de tiempo >= 60 segundos (hasta 1 año para cubrir rango amplio)
_old_delta_seconds = st.integers(
    min_value=RECENT_THRESHOLD_SECONDS, max_value=365 * 24 * 3600
)


# === PROPERTY 4: NO JITTER FOR OLD TRIGGER EVENTS ===


class TestNoJitterForOldTriggerEvents:
    """
    Property 4: No jitter for old trigger events.

    Para cualquier timestamp de evento (update o restart) que tenga 60 o más
    segundos de antigüedad respecto al momento actual, el delay de arranque
    calculado SHALL ser 0 milisegundos.

    **Validates: Requirements 3.2, 4.2**
    """

    @given(
        jitter_window=_jitter_window,
        delta_seconds=_old_delta_seconds,
    )
    @settings(max_examples=100, deadline=None)
    def test_update_timestamp_antiguo_produce_delay_cero(
        self, jitter_window: int, delta_seconds: int
    ):
        """
        Cuando LastUpdateTimestamp tiene Δt >= 60s respecto a utcNow,
        el delay de startup es 0 independientemente del jitter window.

        **Validates: Requirements 3.2, 4.2**
        """
        utc_now = datetime(2026, 6, 15, 12, 0, 0)
        # Timestamp antiguo: utcNow - delta_seconds (donde delta >= 60)
        old_update = utc_now - timedelta(seconds=delta_seconds)

        delay_ms, reason = compute_startup_delay(
            utc_now=utc_now,
            last_update_timestamp=old_update,
            last_restart_timestamp=None,
            jitter_window_seconds=jitter_window,
        )

        assert delay_ms == 0, (
            f"Se esperaba delay=0 para timestamp con Δt={delta_seconds}s >= 60s, "
            f"pero se obtuvo delay_ms={delay_ms}"
        )
        assert reason is None, (
            f"Se esperaba reason=None para timestamp antiguo, "
            f"pero se obtuvo reason='{reason}'"
        )

    @given(
        jitter_window=_jitter_window,
        delta_seconds=_old_delta_seconds,
    )
    @settings(max_examples=100, deadline=None)
    def test_restart_timestamp_antiguo_produce_delay_cero(
        self, jitter_window: int, delta_seconds: int
    ):
        """
        Cuando LastRestartTimestamp tiene Δt >= 60s respecto a utcNow,
        el delay de startup es 0 independientemente del jitter window.

        **Validates: Requirements 3.2, 4.2**
        """
        utc_now = datetime(2026, 6, 15, 12, 0, 0)
        # Timestamp antiguo: utcNow - delta_seconds (donde delta >= 60)
        old_restart = utc_now - timedelta(seconds=delta_seconds)

        delay_ms, reason = compute_startup_delay(
            utc_now=utc_now,
            last_update_timestamp=None,
            last_restart_timestamp=old_restart,
            jitter_window_seconds=jitter_window,
        )

        assert delay_ms == 0, (
            f"Se esperaba delay=0 para restart timestamp con Δt={delta_seconds}s >= 60s, "
            f"pero se obtuvo delay_ms={delay_ms}"
        )
        assert reason is None, (
            f"Se esperaba reason=None para restart timestamp antiguo, "
            f"pero se obtuvo reason='{reason}'"
        )

    @given(
        jitter_window=_jitter_window,
        update_delta=_old_delta_seconds,
        restart_delta=_old_delta_seconds,
    )
    @settings(max_examples=100, deadline=None)
    def test_ambos_timestamps_antiguos_producen_delay_cero(
        self, jitter_window: int, update_delta: int, restart_delta: int
    ):
        """
        Cuando ambos timestamps (update y restart) tienen Δt >= 60s,
        el delay de startup es 0.

        **Validates: Requirements 3.2, 4.2**
        """
        utc_now = datetime(2026, 6, 15, 12, 0, 0)
        old_update = utc_now - timedelta(seconds=update_delta)
        old_restart = utc_now - timedelta(seconds=restart_delta)

        delay_ms, reason = compute_startup_delay(
            utc_now=utc_now,
            last_update_timestamp=old_update,
            last_restart_timestamp=old_restart,
            jitter_window_seconds=jitter_window,
        )

        assert delay_ms == 0, (
            f"Se esperaba delay=0 para ambos timestamps antiguos "
            f"(update Δt={update_delta}s, restart Δt={restart_delta}s), "
            f"pero se obtuvo delay_ms={delay_ms}"
        )
        assert reason is None, (
            f"Se esperaba reason=None para ambos timestamps antiguos, "
            f"pero se obtuvo reason='{reason}'"
        )
