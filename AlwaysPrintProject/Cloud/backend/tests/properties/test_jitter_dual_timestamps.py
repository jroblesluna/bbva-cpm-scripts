"""
Property test: Dual recent timestamps produce single jitter using closest timestamp.

Verifica que cuando ambos timestamps (LastUpdateTimestamp y LastRestartTimestamp)
son recientes (< 60s), el sistema aplica jitter exactamente una vez usando
el timestamp más cercano al momento actual como fuente de jitter.

**Validates: Requirements 4.4**

Feature: reconnection-jitter, Property 5: Dual recent timestamps produce single jitter using closest timestamp
"""

import random
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

# Deltas recientes: ambos timestamps con Δt < 60s (en segundos, con granularidad decimal)
_recent_delta = st.floats(
    min_value=0.0, max_value=59.9, allow_nan=False, allow_infinity=False
)

# Semilla para el generador aleatorio (testing determinístico)
_seed = st.integers(min_value=0, max_value=2**31 - 1)


# === PROPERTY 5: DUAL RECENT TIMESTAMPS PRODUCE SINGLE JITTER USING CLOSEST TIMESTAMP ===


class TestDualRecentTimestampsSingleJitter:
    """
    Property 5: Dual recent timestamps produce single jitter using closest timestamp.

    Para cualquier par de timestamps (LastUpdateTimestamp y LastRestartTimestamp)
    ambos dentro de 60 segundos del momento actual, el sistema SHALL aplicar
    jitter exactamente una vez, seleccionando el timestamp más cercano al
    momento actual como fuente de jitter.

    **Validates: Requirements 4.4**
    """

    @given(
        jitter_window=_jitter_window,
        update_delta=_recent_delta,
        restart_delta=_recent_delta,
        seed=_seed,
    )
    @settings(max_examples=100, deadline=None)
    def test_ambos_recientes_producen_un_solo_delay(
        self,
        jitter_window: int,
        update_delta: float,
        restart_delta: float,
        seed: int,
    ):
        """
        Cuando ambos timestamps son recientes (< 60s), se produce un solo
        delay en el rango [0, W*1000) milisegundos — jitter se aplica una vez.

        **Validates: Requirements 4.4**
        """
        utc_now = datetime(2026, 6, 15, 12, 0, 0)
        last_update = utc_now - timedelta(seconds=update_delta)
        last_restart = utc_now - timedelta(seconds=restart_delta)

        rng = random.Random(seed)

        delay_ms, reason = compute_startup_delay(
            utc_now=utc_now,
            last_update_timestamp=last_update,
            last_restart_timestamp=last_restart,
            jitter_window_seconds=jitter_window,
            rng=rng,
        )

        # Debe haber exactamente un delay (no cero, no doble)
        max_delay = jitter_window * 1000
        assert 0 <= delay_ms < max_delay, (
            f"Se esperaba delay en [0, {max_delay}) ms, "
            f"pero se obtuvo delay_ms={delay_ms} "
            f"con window={jitter_window}, update_delta={update_delta}s, "
            f"restart_delta={restart_delta}s"
        )

        # Debe tener una razón (jitter fue aplicado)
        assert reason is not None, (
            f"Se esperaba reason no-None cuando ambos timestamps son recientes, "
            f"pero se obtuvo reason=None"
        )

    @given(
        jitter_window=_jitter_window,
        update_delta=_recent_delta,
        restart_delta=_recent_delta,
        seed=_seed,
    )
    @settings(max_examples=100, deadline=None)
    def test_reason_corresponde_al_timestamp_mas_cercano(
        self,
        jitter_window: int,
        update_delta: float,
        restart_delta: float,
        seed: int,
    ):
        """
        Cuando ambos timestamps son recientes, el reason refleja cuál
        timestamp es más cercano a utcNow:
        - Si restart_diff <= update_diff → reason = "post-restart"
        - Si update_diff < restart_diff → reason = "post-update"

        Se compara usando la diferencia real en timedelta (resolución microsegundos)
        para reflejar el comportamiento exacto de la implementación.

        **Validates: Requirements 4.4**
        """
        utc_now = datetime(2026, 6, 15, 12, 0, 0)
        last_update = utc_now - timedelta(seconds=update_delta)
        last_restart = utc_now - timedelta(seconds=restart_delta)

        rng = random.Random(seed)

        delay_ms, reason = compute_startup_delay(
            utc_now=utc_now,
            last_update_timestamp=last_update,
            last_restart_timestamp=last_restart,
            jitter_window_seconds=jitter_window,
            rng=rng,
        )

        # Calcular diferencias reales usando timedelta (resolución microsegundos)
        # Esto refleja exactamente lo que hace la implementación internamente
        actual_update_diff = (utc_now - last_update).total_seconds()
        actual_restart_diff = (utc_now - last_restart).total_seconds()

        # La implementación usa restart_diff <= update_diff para favorecer restart en empate
        if actual_restart_diff <= actual_update_diff:
            expected_reason = "post-restart"
        else:
            expected_reason = "post-update"

        assert reason == expected_reason, (
            f"Se esperaba reason='{expected_reason}' "
            f"(restart_diff={actual_restart_diff}s, update_diff={actual_update_diff}s), "
            f"pero se obtuvo reason='{reason}'"
        )

    @given(
        jitter_window=_jitter_window,
        update_delta=_recent_delta,
        restart_delta=_recent_delta,
        seed=_seed,
    )
    @settings(max_examples=100, deadline=None)
    def test_no_se_aplica_jitter_doble(
        self,
        jitter_window: int,
        update_delta: float,
        restart_delta: float,
        seed: int,
    ):
        """
        Verifica que el delay no excede el máximo de una sola aplicación
        de jitter (W*1000 - 1 ms). Esto confirma que el jitter se aplica
        una sola vez, no como suma de dos jitters independientes.

        **Validates: Requirements 4.4**
        """
        utc_now = datetime(2026, 6, 15, 12, 0, 0)
        last_update = utc_now - timedelta(seconds=update_delta)
        last_restart = utc_now - timedelta(seconds=restart_delta)

        rng = random.Random(seed)

        delay_ms, reason = compute_startup_delay(
            utc_now=utc_now,
            last_update_timestamp=last_update,
            last_restart_timestamp=last_restart,
            jitter_window_seconds=jitter_window,
            rng=rng,
        )

        # El delay máximo de una sola aplicación es W*1000 - 1
        # Si se aplicara doble jitter, podría llegar hasta 2*W*1000 - 2
        max_single_jitter = jitter_window * 1000
        assert delay_ms < max_single_jitter, (
            f"delay_ms={delay_ms} >= max_single_jitter={max_single_jitter}, "
            f"sugiere que se aplicó jitter más de una vez"
        )
