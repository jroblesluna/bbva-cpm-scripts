"""
Property test para el delay de jitter en la primera reconexión WebSocket.

Verifica que JitterCalculator.ComputeReconnectionDelay produce un delay
dentro del rango [0, W*1000) milisegundos para cualquier ventana de jitter
válida en [5, 300].

Se usa el wrapper Python que replica la lógica de JitterCalculator.cs
para validar la propiedad con Hypothesis.

**Validates: Requirements 5.1**

Feature: reconnection-jitter, Property 8: First WebSocket reconnection uses jitter delay
"""

import random

from hypothesis import given, settings
from hypothesis import strategies as st

from tests.properties.jitter_calculator import compute_reconnection_delay


# === CONSTANTES ===

# Rango válido para la ventana de jitter
MIN_JITTER_WINDOW = 5
MAX_JITTER_WINDOW = 300


# === ESTRATEGIAS DE GENERACIÓN ===

# Ventana de jitter válida: entero en [5, 300]
_jitter_window = st.integers(min_value=MIN_JITTER_WINDOW, max_value=MAX_JITTER_WINDOW)

# Semilla para el generador aleatorio (testing determinístico)
_seed = st.integers(min_value=0, max_value=2**31 - 1)


# === PROPERTY 8: FIRST WEBSOCKET RECONNECTION USES JITTER DELAY ===


class TestFirstReconnectionUsesJitterDelay:
    """
    Property 8: First WebSocket reconnection uses jitter delay.

    Para cualquier ventana de jitter W válida en [5, 300], cuando ocurre
    una desconexión WebSocket durante runtime, el primer intento de
    reconexión SHALL tener un delay en [0, W*1000) milisegundos
    (distribución uniforme).

    **Validates: Requirements 5.1**
    """

    @given(
        jitter_window=_jitter_window,
        seed=_seed,
    )
    @settings(max_examples=100, deadline=None)
    def test_reconnection_delay_dentro_de_limites(
        self, jitter_window: int, seed: int
    ):
        """
        El delay de reconexión está en [0, W*1000) milisegundos
        para cualquier ventana válida W ∈ [5, 300].

        **Validates: Requirements 5.1**
        """
        # Usar un Random con seed fijo para determinismo
        rng = random.Random(seed)

        # Calcular el delay de reconexión
        delay_ms = compute_reconnection_delay(
            jitter_window_seconds=jitter_window,
            rng=rng,
        )

        # Verificar que el delay está en el rango correcto [0, W*1000)
        max_delay = jitter_window * 1000
        assert 0 <= delay_ms < max_delay, (
            f"delay_ms={delay_ms} fuera de [0, {max_delay}) "
            f"con window={jitter_window}s, seed={seed}"
        )

    @given(
        jitter_window=_jitter_window,
        seed=_seed,
    )
    @settings(max_examples=100, deadline=None)
    def test_reconnection_delay_es_entero(
        self, jitter_window: int, seed: int
    ):
        """
        El delay de reconexión siempre es un valor entero en milisegundos.

        **Validates: Requirements 5.1**
        """
        rng = random.Random(seed)

        delay_ms = compute_reconnection_delay(
            jitter_window_seconds=jitter_window,
            rng=rng,
        )

        # Verificar que el delay es un entero (milisegundos discretos)
        assert isinstance(delay_ms, int), (
            f"delay_ms={delay_ms} no es entero, tipo={type(delay_ms)} "
            f"con window={jitter_window}s"
        )

    @given(
        jitter_window=_jitter_window,
        seed=_seed,
    )
    @settings(max_examples=100, deadline=None)
    def test_reconnection_delay_no_negativo(
        self, jitter_window: int, seed: int
    ):
        """
        El delay de reconexión nunca es negativo.

        **Validates: Requirements 5.1**
        """
        rng = random.Random(seed)

        delay_ms = compute_reconnection_delay(
            jitter_window_seconds=jitter_window,
            rng=rng,
        )

        # Verificar que el delay nunca es negativo
        assert delay_ms >= 0, (
            f"delay_ms={delay_ms} es negativo con window={jitter_window}s, seed={seed}"
        )
