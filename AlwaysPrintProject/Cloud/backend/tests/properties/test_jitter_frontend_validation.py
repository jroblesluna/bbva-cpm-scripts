"""
Property tests para la validación frontend del campo jitter_window_seconds.

Replica la lógica de validación client-side del frontend:
- Si el valor es < 5 o > 300, se muestra error de validación y NO se envía al backend
- Si el valor está en [5, 300], no hay error y se permite el envío

La validación frontend actúa como primera barrera antes de la validación backend,
evitando requests innecesarias con valores inválidos.

**Validates: Requirements 6.4**

Feature: reconnection-jitter, Property 10: Frontend validation rejects out-of-range values
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st


# === CONSTANTES ===

# Rango válido para jitter_window_seconds según la UI
MIN_JITTER_WINDOW = 5
MAX_JITTER_WINDOW = 300


# === LÓGICA DE VALIDACIÓN FRONTEND (réplica en Python) ===


def validate_jitter_window(value: int) -> tuple[bool, str]:
    """
    Replica la lógica de validación del frontend para jitter_window_seconds.

    Basada en handleJitterWindowChange y handleSaveJitter del componente
    de organización (my-organization/page.tsx):
    - Si value < 5 o value > 300 → error de validación, no se envía
    - Si value está en [5, 300] → sin error, se permite envío

    Retorna:
        (is_valid, error_message): tupla con estado de validación y mensaje de error
    """
    if value < MIN_JITTER_WINDOW or value > MAX_JITTER_WINDOW:
        return (False, "El valor debe estar entre 5 y 300 segundos")
    return (True, "")


def should_submit(value: int) -> bool:
    """
    Determina si el frontend enviaría el valor al backend.

    Replica la condición de handleSaveJitter:
    if (jitterWindowSeconds < 5 || jitterWindowSeconds > 300) { return; }

    Solo se envía si el valor está en [5, 300].
    """
    return MIN_JITTER_WINDOW <= value <= MAX_JITTER_WINDOW


# === ESTRATEGIAS DE GENERACIÓN ===

# Valores fuera de rango: menores a 5
_below_range_values = st.integers(max_value=MIN_JITTER_WINDOW - 1)

# Valores fuera de rango: mayores a 300
_above_range_values = st.integers(min_value=MAX_JITTER_WINDOW + 1)

# Valores fuera de rango combinados: < 5 o > 300
_out_of_range_values = st.one_of(_below_range_values, _above_range_values)

# Valores dentro de rango: [5, 300]
_in_range_values = st.integers(min_value=MIN_JITTER_WINDOW, max_value=MAX_JITTER_WINDOW)


# === PROPERTY 10: FRONTEND VALIDATION REJECTS OUT-OF-RANGE VALUES ===


class TestJitterFrontendValidation:
    """
    Property 10: Frontend validation rejects out-of-range values.

    Para cualquier valor numérico V donde V < 5 o V > 300, el frontend
    SHALL mostrar un error de validación y SHALL NOT enviar el valor al backend.

    Para cualquier valor V en [5, 300], el frontend SHALL aceptar el valor
    sin error y permitir el envío.

    **Validates: Requirements 6.4**
    """

    @given(value=_out_of_range_values)
    @settings(max_examples=100, deadline=None)
    def test_valores_fuera_de_rango_son_rechazados(self, value: int):
        """
        Para cualquier V < 5 o V > 300, la validación frontend debe rechazar
        el valor mostrando error y bloqueando el envío al backend.

        **Validates: Requirements 6.4**
        """
        # Validar que se detecta como inválido
        is_valid, error_message = validate_jitter_window(value)

        assert not is_valid, (
            f"Se esperaba que value={value} fuera rechazado por la validación frontend, "
            f"pero fue aceptado"
        )
        assert error_message != "", (
            f"Se esperaba mensaje de error para value={value}, "
            f"pero error_message está vacío"
        )

        # Verificar que NO se enviaría al backend
        assert not should_submit(value), (
            f"Se esperaba que value={value} NO se enviara al backend, "
            f"pero should_submit retornó True"
        )

    @given(value=_in_range_values)
    @settings(max_examples=100, deadline=None)
    def test_valores_en_rango_son_aceptados(self, value: int):
        """
        Para cualquier V en [5, 300], la validación frontend debe aceptar
        el valor sin error y permitir el envío al backend.

        **Validates: Requirements 6.4**
        """
        # Validar que se detecta como válido
        is_valid, error_message = validate_jitter_window(value)

        assert is_valid, (
            f"Se esperaba que value={value} fuera aceptado por la validación frontend, "
            f"pero fue rechazado con: {error_message}"
        )
        assert error_message == "", (
            f"Se esperaba sin mensaje de error para value={value}, "
            f"pero obtuvo: {error_message}"
        )

        # Verificar que SÍ se enviaría al backend
        assert should_submit(value), (
            f"Se esperaba que value={value} se enviara al backend, "
            f"pero should_submit retornó False"
        )

    @given(value=_below_range_values)
    @settings(max_examples=100, deadline=None)
    def test_valores_menores_a_minimo_son_rechazados(self, value: int):
        """
        Para cualquier V < 5, la validación frontend debe rechazar.
        Verifica específicamente el límite inferior.

        **Validates: Requirements 6.4**
        """
        is_valid, _ = validate_jitter_window(value)

        assert not is_valid, (
            f"Se esperaba que value={value} (< 5) fuera rechazado, pero fue aceptado"
        )
        assert not should_submit(value), (
            f"Se esperaba que value={value} (< 5) NO se enviara al backend"
        )

    @given(value=_above_range_values)
    @settings(max_examples=100, deadline=None)
    def test_valores_mayores_a_maximo_son_rechazados(self, value: int):
        """
        Para cualquier V > 300, la validación frontend debe rechazar.
        Verifica específicamente el límite superior.

        **Validates: Requirements 6.4**
        """
        is_valid, _ = validate_jitter_window(value)

        assert not is_valid, (
            f"Se esperaba que value={value} (> 300) fuera rechazado, pero fue aceptado"
        )
        assert not should_submit(value), (
            f"Se esperaba que value={value} (> 300) NO se enviara al backend"
        )

    def test_limite_inferior_exacto_es_aceptado(self):
        """
        El valor exacto 5 (límite inferior) debe ser aceptado.
        Test determinístico de boundary.

        **Validates: Requirements 6.4**
        """
        is_valid, error_message = validate_jitter_window(5)
        assert is_valid, "value=5 debería ser aceptado (límite inferior)"
        assert error_message == ""
        assert should_submit(5)

    def test_limite_superior_exacto_es_aceptado(self):
        """
        El valor exacto 300 (límite superior) debe ser aceptado.
        Test determinístico de boundary.

        **Validates: Requirements 6.4**
        """
        is_valid, error_message = validate_jitter_window(300)
        assert is_valid, "value=300 debería ser aceptado (límite superior)"
        assert error_message == ""
        assert should_submit(300)

    def test_justo_debajo_del_minimo_es_rechazado(self):
        """
        El valor 4 (justo debajo del mínimo) debe ser rechazado.
        Test determinístico de boundary.

        **Validates: Requirements 6.4**
        """
        is_valid, error_message = validate_jitter_window(4)
        assert not is_valid, "value=4 debería ser rechazado (por debajo del mínimo)"
        assert error_message != ""
        assert not should_submit(4)

    def test_justo_encima_del_maximo_es_rechazado(self):
        """
        El valor 301 (justo encima del máximo) debe ser rechazado.
        Test determinístico de boundary.

        **Validates: Requirements 6.4**
        """
        is_valid, error_message = validate_jitter_window(301)
        assert not is_valid, "value=301 debería ser rechazado (por encima del máximo)"
        assert error_message != ""
        assert not should_submit(301)
