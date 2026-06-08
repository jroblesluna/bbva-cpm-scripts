# Feature: death-ping-optimization, Property 2: Validación de offline_timeout_minutes
"""
Property test: Validación de offline_timeout_minutes

Para cualquier valor entero, si el valor es >= 1 entonces la validación de
offline_timeout_minutes debe aceptarlo; si el valor es < 1 entonces la
validación debe rechazarlo con ValidationError.

Feature: death-ping-optimization, Property 2: Validación de offline_timeout_minutes
**Validates: Requirements 2.4, 7.2, 7.3**
"""

import pytest
from hypothesis import given, settings as hypothesis_settings
from hypothesis import strategies as st
from pydantic import ValidationError

from app.schemas.organization import OrganizationUpdate


# === PROPERTY TEST ===


@hypothesis_settings(max_examples=100, deadline=None)
@given(value=st.integers(min_value=1, max_value=100_000))
def test_offline_timeout_accepts_valid_values(value: int):
    """
    Propiedad 2 (caso válido): Para cualquier entero >= 1,
    OrganizationUpdate debe aceptar el valor sin error.

    Feature: death-ping-optimization, Property 2: Validación de offline_timeout_minutes
    **Validates: Requirements 2.4, 7.2, 7.3**
    """
    # Crear schema con valor válido — no debe lanzar excepción
    schema = OrganizationUpdate(offline_timeout_minutes=value)
    assert schema.offline_timeout_minutes == value


@hypothesis_settings(max_examples=100, deadline=None)
@given(value=st.integers(max_value=0))
def test_offline_timeout_rejects_invalid_values(value: int):
    """
    Propiedad 2 (caso inválido): Para cualquier entero < 1,
    OrganizationUpdate debe rechazar el valor con ValidationError.

    Feature: death-ping-optimization, Property 2: Validación de offline_timeout_minutes
    **Validates: Requirements 2.4, 7.2, 7.3**
    """
    # Intentar crear schema con valor inválido — debe lanzar ValidationError
    with pytest.raises(ValidationError) as exc_info:
        OrganizationUpdate(offline_timeout_minutes=value)

    # Verificar que el error es específicamente sobre offline_timeout_minutes
    errors = exc_info.value.errors()
    field_errors = [e for e in errors if "offline_timeout_minutes" in e["loc"]]
    assert len(field_errors) > 0, (
        f"Se esperaba error de validación en offline_timeout_minutes para valor={value}, "
        f"pero los errores fueron: {errors}"
    )
