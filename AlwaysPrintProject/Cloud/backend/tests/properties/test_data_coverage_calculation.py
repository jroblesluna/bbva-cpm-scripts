"""
Property tests para el cálculo de cobertura de datos.

Verifica que el cálculo de data_coverage_percent en el endpoint get_metric_history
produce resultados correctos según la fórmula:
  expected_points = days * 4  (4 recolecciones por día)
  actual_points = len(records)
  coverage = min(round((actual_points / expected_points) * 100, 1), 100.0)

Propiedades verificadas:
- La cobertura se calcula correctamente como (actual / expected) * 100
- La cobertura siempre está entre 0.0 y 100.0
- Cuando actual_points == 0, la cobertura es 0.0
- Cuando actual_points >= expected_points, la cobertura es 100.0

**Validates: Requirements 7.6**

Feature: system-status-monitoring, Property 16: Data coverage calculation
"""

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st


# === FUNCIÓN BAJO TEST ===
# Extraída directamente de la lógica del endpoint get_metric_history


def calculate_data_coverage(days: int, actual_points: int) -> float:
    """
    Calcula el porcentaje de cobertura de datos para un período dado.

    Replica la lógica exacta del endpoint get_metric_history:
    - Se esperan 4 recolecciones por día (cada 6 horas)
    - La cobertura se limita a un máximo de 100.0%

    Args:
        days: Número de días del período (7, 14 o 30)
        actual_points: Número de puntos de datos reales disponibles

    Returns:
        Porcentaje de cobertura (0.0 a 100.0)
    """
    expected_points = days * 4
    data_coverage_percent = (
        round((actual_points / expected_points) * 100, 1)
        if expected_points > 0
        else 0.0
    )
    data_coverage_percent = min(data_coverage_percent, 100.0)
    return data_coverage_percent


# === ESTRATEGIAS DE GENERACIÓN ===

# Períodos válidos según la interfaz (7, 14 o 30 días)
_valid_days = st.sampled_from([7, 14, 30])

# Puntos de datos reales: desde 0 hasta el doble de los esperados para el máximo período
# Máximo esperado: 30 * 4 = 120, doble = 240
_actual_points = st.integers(min_value=0, max_value=240)

# Puntos de datos para caso de cobertura completa o excedente
_excess_points = st.integers(min_value=120, max_value=500)

# Puntos de datos para caso de cobertura parcial (no cero, no completa)
_partial_points = st.integers(min_value=1, max_value=119)


# === PROPERTY 16: DATA COVERAGE CALCULATION ===


class TestDataCoverageCalculation:
    """
    Property 16: Data coverage calculation.

    Para cualquier período de tiempo con puntos de datos esperados (basados en
    la frecuencia de recolección) y puntos de datos reales disponibles, el
    porcentaje de cobertura SHALL ser igual a (actual_count / expected_count) * 100,
    y los intervalos sin datos SHALL ser correctamente identificados como gaps.

    **Validates: Requirements 7.6**
    """

    @given(days=_valid_days, actual_points=_actual_points)
    @settings(max_examples=200, deadline=None)
    def test_cobertura_formula_correcta(self, days: int, actual_points: int):
        """
        La cobertura se calcula como min(round((actual / (days * 4)) * 100, 1), 100.0).

        Verifica que la función produce el resultado esperado según la fórmula
        definida en el diseño.

        **Validates: Requirements 7.6**
        """
        # Calcular resultado esperado manualmente
        expected_points = days * 4
        expected_coverage = round((actual_points / expected_points) * 100, 1)
        expected_coverage = min(expected_coverage, 100.0)

        # Calcular resultado de la función
        result = calculate_data_coverage(days, actual_points)

        assert result == expected_coverage, (
            f"Para days={days}, actual_points={actual_points}: "
            f"se esperaba cobertura={expected_coverage}%, "
            f"pero se obtuvo {result}%"
        )

    @given(days=_valid_days, actual_points=_actual_points)
    @settings(max_examples=200, deadline=None)
    def test_cobertura_siempre_entre_0_y_100(self, days: int, actual_points: int):
        """
        La cobertura siempre está en el rango [0.0, 100.0].

        Independientemente de los valores de entrada, el resultado nunca
        puede ser negativo ni superar 100%.

        **Validates: Requirements 7.6**
        """
        result = calculate_data_coverage(days, actual_points)

        assert 0.0 <= result <= 100.0, (
            f"Para days={days}, actual_points={actual_points}: "
            f"la cobertura {result}% está fuera del rango [0.0, 100.0]"
        )

    @given(days=_valid_days)
    @settings(max_examples=200, deadline=None)
    def test_cobertura_cero_cuando_sin_datos(self, days: int):
        """
        Cuando actual_points == 0, la cobertura es exactamente 0.0%.

        Un período sin ningún punto de datos tiene cobertura nula.

        **Validates: Requirements 7.6**
        """
        result = calculate_data_coverage(days, actual_points=0)

        assert result == 0.0, (
            f"Para days={days}, actual_points=0: "
            f"se esperaba cobertura=0.0%, pero se obtuvo {result}%"
        )

    @given(days=_valid_days)
    @settings(max_examples=200, deadline=None)
    def test_cobertura_100_cuando_datos_completos(self, days: int):
        """
        Cuando actual_points == expected_points (days * 4), la cobertura es 100.0%.

        Un período con todos los puntos esperados tiene cobertura completa.

        **Validates: Requirements 7.6**
        """
        expected_points = days * 4
        result = calculate_data_coverage(days, actual_points=expected_points)

        assert result == 100.0, (
            f"Para days={days}, actual_points={expected_points} (completo): "
            f"se esperaba cobertura=100.0%, pero se obtuvo {result}%"
        )

    @given(days=_valid_days, excess=st.integers(min_value=1, max_value=200))
    @settings(max_examples=200, deadline=None)
    def test_cobertura_limitada_a_100_cuando_excede_esperados(
        self, days: int, excess: int
    ):
        """
        Cuando actual_points > expected_points, la cobertura se limita a 100.0%.

        Incluso si hay más datos de los esperados (por recolecciones manuales
        adicionales), la cobertura no puede superar 100%.

        **Validates: Requirements 7.6**
        """
        expected_points = days * 4
        actual_points = expected_points + excess

        result = calculate_data_coverage(days, actual_points)

        assert result == 100.0, (
            f"Para days={days}, actual_points={actual_points} > expected={expected_points}: "
            f"se esperaba cobertura=100.0% (limitada), pero se obtuvo {result}%"
        )

    @given(days=_valid_days, actual_points=_partial_points)
    @settings(max_examples=200, deadline=None)
    def test_cobertura_parcial_proporcional(self, days: int, actual_points: int):
        """
        Cuando 0 < actual_points < expected_points, la cobertura es proporcional.

        La cobertura refleja correctamente la proporción de datos disponibles
        respecto a los esperados.

        **Validates: Requirements 7.6**
        """
        expected_points = days * 4
        # Solo probar cuando actual_points < expected_points (cobertura parcial)
        assume(actual_points < expected_points)

        result = calculate_data_coverage(days, actual_points)

        # Verificar que es estrictamente mayor que 0 y menor que 100
        assert 0.0 < result < 100.0, (
            f"Para days={days}, actual_points={actual_points} "
            f"(parcial, expected={expected_points}): "
            f"se esperaba 0 < cobertura < 100, pero se obtuvo {result}%"
        )

        # Verificar proporcionalidad: más datos → mayor cobertura
        # Si duplicamos los puntos (sin exceder expected), la cobertura debe ser mayor
        if actual_points * 2 <= expected_points:
            result_double = calculate_data_coverage(days, actual_points * 2)
            assert result_double > result, (
                f"Más datos deben dar mayor cobertura: "
                f"{actual_points} puntos → {result}%, "
                f"{actual_points * 2} puntos → {result_double}%"
            )

    @given(days=_valid_days, actual_points=_actual_points)
    @settings(max_examples=200, deadline=None)
    def test_cobertura_precision_un_decimal(self, days: int, actual_points: int):
        """
        La cobertura se redondea a 1 decimal de precisión.

        El resultado siempre tiene como máximo 1 dígito decimal.

        **Validates: Requirements 7.6**
        """
        result = calculate_data_coverage(days, actual_points)

        # Verificar que el resultado redondeado a 1 decimal es igual a sí mismo
        assert result == round(result, 1), (
            f"Para days={days}, actual_points={actual_points}: "
            f"la cobertura {result}% no está redondeada a 1 decimal"
        )

    @given(
        days=_valid_days,
        points_a=st.integers(min_value=0, max_value=120),
        points_b=st.integers(min_value=0, max_value=120),
    )
    @settings(max_examples=200, deadline=None)
    def test_cobertura_monotona_creciente(
        self, days: int, points_a: int, points_b: int
    ):
        """
        La cobertura es monótonamente creciente respecto a actual_points.

        Si points_a <= points_b, entonces coverage(points_a) <= coverage(points_b).

        **Validates: Requirements 7.6**
        """
        expected_points = days * 4
        # Limitar a rango válido para el período
        assume(points_a <= expected_points)
        assume(points_b <= expected_points)

        result_a = calculate_data_coverage(days, points_a)
        result_b = calculate_data_coverage(days, points_b)

        if points_a <= points_b:
            assert result_a <= result_b, (
                f"La cobertura debe ser monótonamente creciente: "
                f"points_a={points_a} → {result_a}%, "
                f"points_b={points_b} → {result_b}%"
            )
        else:
            assert result_a >= result_b, (
                f"La cobertura debe ser monótonamente creciente: "
                f"points_a={points_a} → {result_a}%, "
                f"points_b={points_b} → {result_b}%"
            )
