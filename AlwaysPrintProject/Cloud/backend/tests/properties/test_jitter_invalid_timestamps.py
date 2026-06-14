"""
Property test: Invalid or future timestamps are treated as absent.

Verifica que cuando un timestamp es futuro (mayor a utc_now) o es None
(representando un timestamp inválido/no-ISO-8601 tras el parsing en C#),
el delay calculado es 0 milisegundos.

En la implementación C#, los strings no-ISO-8601 se parsean a null antes
de llegar al JitterCalculator. En Python testeamos el equivalente pasando
None (resultado de un parsing fallido) y timestamps futuros.

**Validates: Requirements 3.4, 4.5**

Feature: reconnection-jitter, Property 6: Invalid or future timestamps are treated as absent
"""

from datetime import datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from tests.properties.jitter_calculator import (
    compute_startup_delay,
    MIN_JITTER_WINDOW,
    MAX_JITTER_WINDOW,
)


# === ESTRATEGIAS DE GENERACIÓN ===

# Ventana de jitter válida: enteros en [5, 300]
_jitter_window = st.integers(min_value=MIN_JITTER_WINDOW, max_value=MAX_JITTER_WINDOW)

# Delta positivo en segundos para generar timestamps futuros (1 segundo hasta 1 año)
_future_delta_seconds = st.integers(min_value=1, max_value=365 * 24 * 3600)


# === PROPERTY 6: INVALID OR FUTURE TIMESTAMPS ARE TREATED AS ABSENT ===


class TestInvalidOrFutureTimestampsTreatedAsAbsent:
    """
    Property 6: Invalid or future timestamps are treated as absent.

    Para cualquier timestamp que sea futuro respecto al reloj del sistema,
    o que sea None (representando un string no-ISO-8601 tras parsing),
    el sistema SHALL tratarlo como ausente y computar un delay de 0 ms.

    **Validates: Requirements 3.4, 4.5**
    """

    @given(
        jitter_window=_jitter_window,
        future_delta=_future_delta_seconds,
    )
    @settings(max_examples=100, deadline=None)
    def test_update_timestamp_futuro_produce_delay_cero(
        self, jitter_window: int, future_delta: int
    ):
        """
        Cuando LastUpdateTimestamp es futuro (timestamp > utc_now),
        se trata como ausente y el delay es 0.

        **Validates: Requirements 3.4, 4.5**
        """
        utc_now = datetime(2026, 6, 15, 12, 0, 0)
        # Timestamp futuro: utc_now + delta positivo
        future_update = utc_now + timedelta(seconds=future_delta)

        delay_ms, reason = compute_startup_delay(
            utc_now=utc_now,
            last_update_timestamp=future_update,
            last_restart_timestamp=None,
            jitter_window_seconds=jitter_window,
        )

        assert delay_ms == 0, (
            f"Se esperaba delay=0 para timestamp futuro "
            f"(utc_now + {future_delta}s), pero se obtuvo delay_ms={delay_ms}"
        )
        assert reason is None, (
            f"Se esperaba reason=None para timestamp futuro, "
            f"pero se obtuvo reason='{reason}'"
        )

    @given(
        jitter_window=_jitter_window,
        future_delta=_future_delta_seconds,
    )
    @settings(max_examples=100, deadline=None)
    def test_restart_timestamp_futuro_produce_delay_cero(
        self, jitter_window: int, future_delta: int
    ):
        """
        Cuando LastRestartTimestamp es futuro (timestamp > utc_now),
        se trata como ausente y el delay es 0.

        **Validates: Requirements 3.4, 4.5**
        """
        utc_now = datetime(2026, 6, 15, 12, 0, 0)
        # Timestamp futuro: utc_now + delta positivo
        future_restart = utc_now + timedelta(seconds=future_delta)

        delay_ms, reason = compute_startup_delay(
            utc_now=utc_now,
            last_update_timestamp=None,
            last_restart_timestamp=future_restart,
            jitter_window_seconds=jitter_window,
        )

        assert delay_ms == 0, (
            f"Se esperaba delay=0 para restart timestamp futuro "
            f"(utc_now + {future_delta}s), pero se obtuvo delay_ms={delay_ms}"
        )
        assert reason is None, (
            f"Se esperaba reason=None para restart timestamp futuro, "
            f"pero se obtuvo reason='{reason}'"
        )

    @given(
        jitter_window=_jitter_window,
        update_future_delta=_future_delta_seconds,
        restart_future_delta=_future_delta_seconds,
    )
    @settings(max_examples=100, deadline=None)
    def test_ambos_timestamps_futuros_producen_delay_cero(
        self, jitter_window: int, update_future_delta: int, restart_future_delta: int
    ):
        """
        Cuando ambos timestamps son futuros, el delay es 0.

        **Validates: Requirements 3.4, 4.5**
        """
        utc_now = datetime(2026, 6, 15, 12, 0, 0)
        future_update = utc_now + timedelta(seconds=update_future_delta)
        future_restart = utc_now + timedelta(seconds=restart_future_delta)

        delay_ms, reason = compute_startup_delay(
            utc_now=utc_now,
            last_update_timestamp=future_update,
            last_restart_timestamp=future_restart,
            jitter_window_seconds=jitter_window,
        )

        assert delay_ms == 0, (
            f"Se esperaba delay=0 para ambos timestamps futuros "
            f"(update +{update_future_delta}s, restart +{restart_future_delta}s), "
            f"pero se obtuvo delay_ms={delay_ms}"
        )
        assert reason is None, (
            f"Se esperaba reason=None para ambos timestamps futuros, "
            f"pero se obtuvo reason='{reason}'"
        )

    @given(jitter_window=_jitter_window)
    @settings(max_examples=100, deadline=None)
    def test_timestamp_none_update_produce_delay_cero(self, jitter_window: int):
        """
        Cuando LastUpdateTimestamp es None (representando un string no-ISO-8601
        que falló el parsing en C#), se trata como ausente y el delay es 0.

        **Validates: Requirements 3.4, 4.5**
        """
        utc_now = datetime(2026, 6, 15, 12, 0, 0)

        delay_ms, reason = compute_startup_delay(
            utc_now=utc_now,
            last_update_timestamp=None,
            last_restart_timestamp=None,
            jitter_window_seconds=jitter_window,
        )

        assert delay_ms == 0, (
            f"Se esperaba delay=0 para timestamp None (inválido), "
            f"pero se obtuvo delay_ms={delay_ms}"
        )
        assert reason is None, (
            f"Se esperaba reason=None para timestamp None, "
            f"pero se obtuvo reason='{reason}'"
        )

    @given(
        jitter_window=_jitter_window,
        future_delta=_future_delta_seconds,
    )
    @settings(max_examples=100, deadline=None)
    def test_un_timestamp_futuro_y_otro_none_producen_delay_cero(
        self, jitter_window: int, future_delta: int
    ):
        """
        Combinación: un timestamp futuro y otro None. Ambos son inválidos,
        así que el delay es 0.

        **Validates: Requirements 3.4, 4.5**
        """
        utc_now = datetime(2026, 6, 15, 12, 0, 0)
        future_update = utc_now + timedelta(seconds=future_delta)

        delay_ms, reason = compute_startup_delay(
            utc_now=utc_now,
            last_update_timestamp=future_update,
            last_restart_timestamp=None,
            jitter_window_seconds=jitter_window,
        )

        assert delay_ms == 0, (
            f"Se esperaba delay=0 para update futuro (+{future_delta}s) y restart None, "
            f"pero se obtuvo delay_ms={delay_ms}"
        )
        assert reason is None, (
            f"Se esperaba reason=None para timestamps inválidos, "
            f"pero se obtuvo reason='{reason}'"
        )
