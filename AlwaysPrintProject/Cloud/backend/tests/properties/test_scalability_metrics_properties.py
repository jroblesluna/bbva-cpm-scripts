"""
Property tests para la corrección del cálculo de porcentajes en métricas de escalabilidad.

Verifica que la función calculate_percent produce resultados correctos:
- Para cualquier numerador no negativo y denominador positivo,
  el resultado es round(numerator / denominator * 100, decimals).

**Validates: Requirements 4.3, 6.3**

Feature: system-status-metrics, Property 5: Percentage calculation correctness
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.scalability_metrics import calculate_percent


# === ESTRATEGIAS DE GENERACIÓN ===

# Numerador: entero no negativo (0 a 100000)
_numerator = st.integers(min_value=0, max_value=100000)

# Denominador: entero positivo (1 a 100000)
_denominator = st.integers(min_value=1, max_value=100000)

# Decimales: valores típicos usados en el sistema (1 para FD% y pool%, 2 para otros)
_decimals = st.integers(min_value=0, max_value=10)


# === PROPERTY 5: PERCENTAGE CALCULATION CORRECTNESS ===


class TestPercentageCalculationCorrectness:
    """
    Property 5: Percentage calculation correctness.

    Para cualquier entero no negativo `numerator` y entero positivo `denominator`,
    la función calculate_percent(numerator, denominator, decimals) SHALL retornar
    round(numerator / denominator * 100, decimals).

    Esta propiedad valida la lógica de cálculo de porcentaje usada por:
    - File descriptors: usage_percent = round(open_count / limit * 100, 1)
    - Pool de BD: usage_percent = round(checked_out / pool_size * 100, 1)

    **Validates: Requirements 4.3, 6.3**
    """

    @given(
        numerator=_numerator,
        denominator=_denominator,
        decimals=_decimals,
    )
    @settings(max_examples=100, deadline=None)
    def test_porcentaje_es_round_numerador_sobre_denominador_por_100(
        self, numerator: int, denominator: int, decimals: int
    ):
        """
        El resultado de calculate_percent(numerator, denominator, decimals)
        es exactamente round(numerator / denominator * 100, decimals).

        **Validates: Requirements 4.3, 6.3**
        """
        # Ejecutar la función bajo test
        resultado = calculate_percent(numerator, denominator, decimals)

        # Calcular el valor esperado directamente
        esperado = round(numerator / denominator * 100, decimals)

        assert resultado == esperado, (
            f"calculate_percent({numerator}, {denominator}, {decimals}) = {resultado}, "
            f"esperado: {esperado}"
        )

    @given(
        numerator=_numerator,
        denominator=_denominator,
    )
    @settings(max_examples=100, deadline=None)
    def test_porcentaje_con_un_decimal_por_defecto(
        self, numerator: int, denominator: int
    ):
        """
        Cuando no se especifica decimals, calculate_percent usa 1 decimal
        por defecto, consistente con el patrón del colector de file descriptors.

        **Validates: Requirements 4.3, 6.3**
        """
        # Ejecutar la función con el valor por defecto de decimals
        resultado = calculate_percent(numerator, denominator)

        # El valor por defecto es decimals=1
        esperado = round(numerator / denominator * 100, 1)

        assert resultado == esperado, (
            f"calculate_percent({numerator}, {denominator}) = {resultado}, "
            f"esperado con 1 decimal: {esperado}"
        )

    @given(
        numerator=_numerator,
        denominator=_denominator,
        decimals=_decimals,
    )
    @settings(max_examples=100, deadline=None)
    def test_porcentaje_es_no_negativo_para_entradas_no_negativas(
        self, numerator: int, denominator: int, decimals: int
    ):
        """
        Para cualquier numerador >= 0 y denominador > 0, el porcentaje
        calculado siempre es >= 0.

        **Validates: Requirements 4.3, 6.3**
        """
        resultado = calculate_percent(numerator, denominator, decimals)

        assert resultado >= 0, (
            f"calculate_percent({numerator}, {denominator}, {decimals}) = {resultado}, "
            f"pero se esperaba un valor no negativo"
        )
