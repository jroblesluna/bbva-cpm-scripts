"""
Property test para la corrección del cálculo del frontend de jitter.

Verifica que para cualquier ventana de jitter X ∈ [5, 300] y número de
workstations activas N > 0, el texto mostrado en el frontend indica
correctamente N/X conexiones por segundo (redondeado a 1 decimal).

Se usa el wrapper Python que replica la lógica de cálculo del frontend
para validar la propiedad con Hypothesis.

**Validates: Requirements 6.2**

Feature: reconnection-jitter, Property 9: Frontend calculation correctness
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from tests.properties.jitter_calculator import (
    compute_frontend_rate,
    format_frontend_calculation_text,
)


# === CONSTANTES ===

# Rango válido para la ventana de jitter (segundos)
MIN_JITTER_WINDOW = 5
MAX_JITTER_WINDOW = 300

# Rango razonable para número de workstations activas
MIN_WORKSTATIONS = 1
MAX_WORKSTATIONS = 10000


# === ESTRATEGIAS DE GENERACIÓN ===

# Ventana de jitter válida: entero en [5, 300]
_jitter_window = st.integers(min_value=MIN_JITTER_WINDOW, max_value=MAX_JITTER_WINDOW)

# Número de workstations activas: entero > 0
_workstation_count = st.integers(min_value=MIN_WORKSTATIONS, max_value=MAX_WORKSTATIONS)


# === PROPERTY 9: FRONTEND CALCULATION CORRECTNESS ===


class TestFrontendCalculationCorrectness:
    """
    Property 9: Frontend calculation correctness.

    Para cualquier ventana de jitter X ∈ [5, 300] y número de workstations
    activas N > 0, el cálculo mostrado en el frontend SHALL indicar
    aproximadamente N/X conexiones por segundo.

    **Validates: Requirements 6.2**
    """

    @given(
        jitter_window=_jitter_window,
        workstation_count=_workstation_count,
    )
    @settings(max_examples=100, deadline=None)
    def test_tasa_es_n_dividido_x_redondeado(
        self, jitter_window: int, workstation_count: int
    ):
        """
        La tasa calculada es N/X redondeada a 1 decimal para cualquier
        combinación válida de X ∈ [5, 300] y N > 0.

        **Validates: Requirements 6.2**
        """
        # Calcular la tasa usando la función del frontend
        rate = compute_frontend_rate(jitter_window, workstation_count)

        # Calcular el valor esperado: N/X redondeado a 1 decimal
        expected_rate = round(workstation_count / jitter_window, 1)

        assert rate == expected_rate, (
            f"rate={rate} != expected={expected_rate} "
            f"con X={jitter_window}s, N={workstation_count}"
        )

    @given(
        jitter_window=_jitter_window,
        workstation_count=_workstation_count,
    )
    @settings(max_examples=100, deadline=None)
    def test_texto_contiene_tasa_calculada(
        self, jitter_window: int, workstation_count: int
    ):
        """
        El texto del frontend contiene la tasa N/X correctamente formateada.

        **Validates: Requirements 6.2**
        """
        # Generar el texto del frontend
        text = format_frontend_calculation_text(jitter_window, workstation_count)

        # Calcular la tasa esperada
        expected_rate = round(workstation_count / jitter_window, 1)

        # Verificar que el texto contiene la tasa
        assert str(expected_rate) in text, (
            f"Tasa esperada '{expected_rate}' no encontrada en texto: '{text}' "
            f"con X={jitter_window}s, N={workstation_count}"
        )

    @given(
        jitter_window=_jitter_window,
        workstation_count=_workstation_count,
    )
    @settings(max_examples=100, deadline=None)
    def test_texto_muestra_valores_correctos(
        self, jitter_window: int, workstation_count: int
    ):
        """
        El texto del frontend muestra X (ventana) y N (workstations) correctamente.

        **Validates: Requirements 6.2**
        """
        # Generar el texto del frontend
        text = format_frontend_calculation_text(jitter_window, workstation_count)

        # Verificar que el texto contiene X y N
        assert str(jitter_window) in text, (
            f"Ventana '{jitter_window}' no encontrada en texto: '{text}'"
        )
        assert str(workstation_count) in text, (
            f"Workstation count '{workstation_count}' no encontrado en texto: '{text}'"
        )

    @given(
        jitter_window=_jitter_window,
        workstation_count=_workstation_count,
    )
    @settings(max_examples=100, deadline=None)
    def test_tasa_siempre_positiva(
        self, jitter_window: int, workstation_count: int
    ):
        """
        La tasa calculada siempre es positiva para N > 0 y X > 0.

        **Validates: Requirements 6.2**
        """
        rate = compute_frontend_rate(jitter_window, workstation_count)

        # Con N > 0 y X > 0, la tasa siempre debe ser >= 0
        # (puede ser 0.0 si N es muy pequeño relativo a X, ej: 1/300 = 0.003 → 0.0)
        assert rate >= 0.0, (
            f"rate={rate} es negativa con X={jitter_window}s, N={workstation_count}"
        )
