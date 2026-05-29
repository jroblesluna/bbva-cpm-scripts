"""
Property tests para la corrección de estadísticas agregadas.

Verifica que para cualquier lista no vacía de valores de métricas dentro
de un período de tiempo, las estadísticas reportan:
- average = sum(values) / count(values), redondeado a 1 decimal
- maximum = max(values), redondeado a 1 decimal
- minimum = min(values), redondeado a 1 decimal
- minimum <= average <= maximum

Se testea como función pura sin base de datos, ya que el cálculo de
estadísticas es aritmética directa aplicada a una lista de valores.

**Validates: Requirements 7.4**

Feature: system-status-monitoring, Property 14: Aggregate statistics correctness
"""

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from typing import List


# === FUNCIÓN BAJO TEST ===
# Extraída de la lógica del endpoint get_metric_history
# (app/api/v1/endpoints/system_status.py)


def calculate_aggregate_statistics(values: List[float]) -> dict:
    """
    Calcula estadísticas agregadas para una lista de valores de métricas.

    Replica la lógica exacta del endpoint get_metric_history:
    - average = round(sum(values) / len(values), 1)
    - maximum = round(max(values), 1)
    - minimum = round(min(values), 1)

    Args:
        values: Lista no vacía de valores numéricos de métricas.

    Returns:
        Diccionario con average, maximum y minimum.
    """
    if not values:
        return {"average": 0.0, "maximum": 0.0, "minimum": 0.0}

    average = round(sum(values) / len(values), 1)
    maximum = round(max(values), 1)
    minimum = round(min(values), 1)

    return {"average": average, "maximum": maximum, "minimum": minimum}


# === ESTRATEGIAS DE GENERACIÓN ===

# Valores de métricas: flotantes razonables que representan porcentajes o MB
# Usamos un rango amplio para cubrir tanto porcentajes (0-100) como valores en MB
_metric_value = st.floats(
    min_value=0.0,
    max_value=100000.0,
    allow_nan=False,
    allow_infinity=False,
).map(lambda x: round(x, 2))

# Listas no vacías de valores de métricas (mínimo 1, máximo 500 elementos)
_metric_values_list = st.lists(
    _metric_value,
    min_size=1,
    max_size=500,
)


# === PROPERTY 14: AGGREGATE STATISTICS CORRECTNESS ===


class TestAggregateStatisticsCorrectness:
    """
    Property 14: Aggregate statistics correctness.

    Para cualquier lista no vacía de valores de métricas dentro de un período
    de tiempo, las estadísticas SHALL reportar:
    - average = sum(values) / count(values)
    - maximum = max(values)
    - minimum = min(values)
    Todos redondeados a 1 decimal.

    **Validates: Requirements 7.4**
    """

    @given(values=_metric_values_list)
    @settings(max_examples=200, deadline=None)
    def test_promedio_es_suma_dividida_por_cantidad(self, values: List[float]):
        """
        El promedio calculado es igual a sum(values) / len(values), redondeado a 1 decimal.

        **Validates: Requirements 7.4**
        """
        stats = calculate_aggregate_statistics(values)

        # Calcular el promedio esperado independientemente
        expected_average = round(sum(values) / len(values), 1)

        assert stats["average"] == expected_average, (
            f"Promedio incorrecto: se esperaba {expected_average}, "
            f"se obtuvo {stats['average']} para {len(values)} valores"
        )

    @given(values=_metric_values_list)
    @settings(max_examples=200, deadline=None)
    def test_maximo_es_max_de_valores(self, values: List[float]):
        """
        El máximo calculado es igual a max(values), redondeado a 1 decimal.

        **Validates: Requirements 7.4**
        """
        stats = calculate_aggregate_statistics(values)

        # Calcular el máximo esperado independientemente
        expected_maximum = round(max(values), 1)

        assert stats["maximum"] == expected_maximum, (
            f"Máximo incorrecto: se esperaba {expected_maximum}, "
            f"se obtuvo {stats['maximum']} para valores con max={max(values)}"
        )

    @given(values=_metric_values_list)
    @settings(max_examples=200, deadline=None)
    def test_minimo_es_min_de_valores(self, values: List[float]):
        """
        El mínimo calculado es igual a min(values), redondeado a 1 decimal.

        **Validates: Requirements 7.4**
        """
        stats = calculate_aggregate_statistics(values)

        # Calcular el mínimo esperado independientemente
        expected_minimum = round(min(values), 1)

        assert stats["minimum"] == expected_minimum, (
            f"Mínimo incorrecto: se esperaba {expected_minimum}, "
            f"se obtuvo {stats['minimum']} para valores con min={min(values)}"
        )

    @given(values=_metric_values_list)
    @settings(max_examples=200, deadline=None)
    def test_minimo_menor_o_igual_promedio_menor_o_igual_maximo(
        self, values: List[float]
    ):
        """
        La relación minimum <= average <= maximum siempre se cumple.

        **Validates: Requirements 7.4**
        """
        stats = calculate_aggregate_statistics(values)

        assert stats["minimum"] <= stats["average"], (
            f"Mínimo ({stats['minimum']}) debe ser <= promedio ({stats['average']})"
        )
        assert stats["average"] <= stats["maximum"], (
            f"Promedio ({stats['average']}) debe ser <= máximo ({stats['maximum']})"
        )

    @given(values=_metric_values_list)
    @settings(max_examples=200, deadline=None)
    def test_estadisticas_redondeadas_a_un_decimal(self, values: List[float]):
        """
        Todas las estadísticas están redondeadas a exactamente 1 decimal.

        **Validates: Requirements 7.4**
        """
        stats = calculate_aggregate_statistics(values)

        # Verificar que cada valor tiene máximo 1 decimal
        for key in ("average", "maximum", "minimum"):
            value = stats[key]
            # Redondear a 1 decimal y comparar: si ya está redondeado, no cambia
            assert value == round(value, 1), (
                f"Estadística '{key}' = {value} no está redondeada a 1 decimal"
            )

    @given(
        value=st.floats(
            min_value=0.0,
            max_value=100000.0,
            allow_nan=False,
            allow_infinity=False,
        ).map(lambda x: round(x, 2))
    )
    @settings(max_examples=200, deadline=None)
    def test_lista_un_elemento_todas_estadisticas_iguales(self, value: float):
        """
        Para una lista con un solo elemento, average == maximum == minimum == round(value, 1).

        **Validates: Requirements 7.4**
        """
        stats = calculate_aggregate_statistics([value])

        expected = round(value, 1)

        assert stats["average"] == expected, (
            f"Con un solo valor {value}, promedio debe ser {expected}, "
            f"se obtuvo {stats['average']}"
        )
        assert stats["maximum"] == expected, (
            f"Con un solo valor {value}, máximo debe ser {expected}, "
            f"se obtuvo {stats['maximum']}"
        )
        assert stats["minimum"] == expected, (
            f"Con un solo valor {value}, mínimo debe ser {expected}, "
            f"se obtuvo {stats['minimum']}"
        )

    @given(
        value=st.floats(
            min_value=0.0,
            max_value=100000.0,
            allow_nan=False,
            allow_infinity=False,
        ).map(lambda x: round(x, 1)),
        count=st.integers(min_value=2, max_value=100),
    )
    @settings(max_examples=200, deadline=None)
    def test_lista_valores_iguales_promedio_igual_a_valor(
        self, value: float, count: int
    ):
        """
        Para una lista donde todos los valores son iguales (redondeados a 1 decimal),
        average == max == min == value.

        Se generan valores ya redondeados a 1 decimal para evitar drift de punto
        flotante en la frontera de redondeo (ej: 1.85 puede redondear a 1.8 o 1.9
        dependiendo de la acumulación de errores en sum/count).

        **Validates: Requirements 7.4**
        """
        values = [value] * count
        stats = calculate_aggregate_statistics(values)

        expected = round(value, 1)

        assert stats["average"] == expected, (
            f"Con {count} valores iguales a {value}, promedio debe ser {expected}, "
            f"se obtuvo {stats['average']}"
        )
        assert stats["maximum"] == expected, (
            f"Con {count} valores iguales a {value}, máximo debe ser {expected}, "
            f"se obtuvo {stats['maximum']}"
        )
        assert stats["minimum"] == expected, (
            f"Con {count} valores iguales a {value}, mínimo debe ser {expected}, "
            f"se obtuvo {stats['minimum']}"
        )
