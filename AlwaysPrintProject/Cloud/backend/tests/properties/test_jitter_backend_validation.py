"""
Property tests para la validación backend del campo jitter_window_seconds.

Verifica que el schema Pydantic OrganizationUpdate:
- Acepta valores enteros en el rango [5, 300]
- Rechaza valores fuera del rango [5, 300] o valores no-enteros

La validación de Pydantic es el mecanismo que genera HTTP 422 en los
endpoints PATCH/PUT de organización.

**Validates: Requirements 1.2, 1.3**

Feature: reconnection-jitter, Property 1: Backend validation accepts valid values and rejects invalid values
"""

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from app.schemas.organization import OrganizationUpdate


# === CONSTANTES ===

# Rango válido para jitter_window_seconds según Requirements 1.2, 1.3
MIN_JITTER_WINDOW = 5
MAX_JITTER_WINDOW = 300


# === ESTRATEGIAS DE GENERACIÓN ===

# Valores enteros válidos: [5, 300]
_valid_jitter_values = st.integers(min_value=MIN_JITTER_WINDOW, max_value=MAX_JITTER_WINDOW)

# Valores enteros inválidos: menores a 5 o mayores a 300
_invalid_low_values = st.integers(max_value=MIN_JITTER_WINDOW - 1)
_invalid_high_values = st.integers(min_value=MAX_JITTER_WINDOW + 1)
_invalid_int_values = st.one_of(_invalid_low_values, _invalid_high_values)

# Valores flotantes (no-enteros) — siempre deben ser rechazados
# Excluimos NaN e infinitos para que sean floats válidos pero no enteros
_float_values = st.floats(
    allow_nan=False,
    allow_infinity=False,
    min_value=-1000.0,
    max_value=1000.0,
).filter(lambda x: not x.is_integer())

# Strings no-numéricos — siempre deben ser rechazados
# Pydantic v2 coerce strings numéricos a int, así que filtramos strings que
# representan enteros válidos en el rango [5, 300]
def _is_coercible_to_valid_int(s: str) -> bool:
    """Retorna True si Pydantic puede coercer el string a un int válido en [5, 300]."""
    try:
        val = int(s.strip())
        return MIN_JITTER_WINDOW <= val <= MAX_JITTER_WINDOW
    except (ValueError, TypeError):
        return False


_string_values = st.text(min_size=1, max_size=50).filter(
    lambda s: not _is_coercible_to_valid_int(s)
)


# === PROPERTY 1: BACKEND VALIDATION ACCEPTS VALID VALUES AND REJECTS INVALID ===


class TestJitterBackendValidation:
    """
    Property 1: Backend validation accepts valid values and rejects invalid values.

    Para cualquier entero V en [5, 300], una request con jitter_window_seconds=V
    SHALL ser aceptada (validación exitosa). Para cualquier valor fuera de [5, 300]
    o no-entero, la request SHALL ser rechazada con error de validación (HTTP 422).

    **Validates: Requirements 1.2, 1.3**
    """

    @given(value=_valid_jitter_values)
    @settings(max_examples=100, deadline=None)
    def test_valores_validos_son_aceptados(self, value: int):
        """
        Enteros en [5, 300] pasan la validación de Pydantic exitosamente
        y el valor queda persistido en el schema.

        **Validates: Requirements 1.2, 1.3**
        """
        # Crear el schema con un valor válido — no debe lanzar excepción
        schema = OrganizationUpdate(jitter_window_seconds=value)

        # Verificar que el valor se persiste correctamente
        assert schema.jitter_window_seconds == value, (
            f"Se esperaba jitter_window_seconds={value}, "
            f"obtenido={schema.jitter_window_seconds}"
        )

    @given(value=_invalid_int_values)
    @settings(max_examples=100, deadline=None)
    def test_enteros_fuera_de_rango_son_rechazados(self, value: int):
        """
        Enteros fuera de [5, 300] (< 5 o > 300) son rechazados por
        la validación de Pydantic con ValidationError.

        **Validates: Requirements 1.2, 1.3**
        """
        with pytest.raises(ValidationError) as exc_info:
            OrganizationUpdate(jitter_window_seconds=value)

        # Verificar que el error menciona jitter_window_seconds
        errors = exc_info.value.errors()
        field_names = [e["loc"][-1] for e in errors]
        assert "jitter_window_seconds" in field_names, (
            f"Se esperaba error en 'jitter_window_seconds' con value={value}, "
            f"errores encontrados: {errors}"
        )

    @given(value=_float_values)
    @settings(max_examples=100, deadline=None)
    def test_flotantes_no_enteros_son_rechazados(self, value: float):
        """
        Valores flotantes no-enteros son rechazados por la validación de Pydantic.
        El campo espera int, no float.

        **Validates: Requirements 1.2, 1.3**
        """
        with pytest.raises(ValidationError) as exc_info:
            OrganizationUpdate(jitter_window_seconds=value)

        # Verificar que el error menciona jitter_window_seconds
        errors = exc_info.value.errors()
        field_names = [e["loc"][-1] for e in errors]
        assert "jitter_window_seconds" in field_names, (
            f"Se esperaba error en 'jitter_window_seconds' con value={value}, "
            f"errores encontrados: {errors}"
        )

    @given(value=_string_values)
    @settings(max_examples=100, deadline=None)
    def test_strings_son_rechazados(self, value: str):
        """
        Valores tipo string son rechazados por la validación de Pydantic.
        El campo espera int, no str.

        **Validates: Requirements 1.2, 1.3**
        """
        with pytest.raises(ValidationError) as exc_info:
            OrganizationUpdate(jitter_window_seconds=value)

        # Verificar que el error menciona jitter_window_seconds
        errors = exc_info.value.errors()
        field_names = [e["loc"][-1] for e in errors]
        assert "jitter_window_seconds" in field_names, (
            f"Se esperaba error en 'jitter_window_seconds' con value={value!r}, "
            f"errores encontrados: {errors}"
        )

    @given(value=_valid_jitter_values)
    @settings(max_examples=100, deadline=None)
    def test_campo_omitido_preserva_none(self, value: int):
        """
        Cuando jitter_window_seconds no se incluye en el request body,
        el schema lo preserva como None (sin cambio al valor existente).
        Esto valida que PATCH sin el campo no modifica el valor almacenado.

        **Validates: Requirements 1.2, 1.3**
        """
        # Schema sin jitter_window_seconds — simula request body sin el campo
        schema = OrganizationUpdate(name="Test Org")
        assert schema.jitter_window_seconds is None, (
            "jitter_window_seconds debería ser None cuando no se incluye en el request"
        )
