"""
Property tests para validación de configuración del Log Analyzer.

Verifica que para cualquier valor de configuración fuera de su rango válido,
el validador de Settings aplica el valor por defecto y emite un warning.
El valor resultante siempre está dentro del rango válido.

- Property 18: Configuration validation fallback

**Validates: Requirements 13.2**
"""

import logging
from unittest.mock import patch

from hypothesis import given, settings as hypothesis_settings, assume
from hypothesis import strategies as st

from app.core.config import Settings


# === DEFINICIÓN DE RANGOS DE CONFIGURACIÓN ===

# Cada entrada: (nombre_campo, min_val, max_val, default_val)
CONFIG_RANGES: list[tuple[str, int, int, int]] = [
    ("LOG_ANALYZER_COMPRESSION_THRESHOLD", 1024, 10485760, 51200),
    ("LOG_ANALYZER_PROCESSING_THRESHOLD", 1024, 52428800, 102400),
    ("LOG_ANALYZER_CONTEXT_WINDOW_SIZE", 0, 500, 20),
    ("LOG_ANALYZER_MAX_CONTEXT_BLOCKS", 1, 1000, 30),
    ("LOG_ANALYZER_TOP_PATTERNS", 1, 500, 50),
    ("LOG_ANALYZER_LLM_MAX_TOKENS", 100, 16384, 4096),
    ("LOG_ANALYZER_MAX_UPLOAD_SIZE", 1048576, 209715200, 52428800),
    ("LOG_ANALYZER_COMMAND_TIMEOUT", 5, 300, 30),
]


# === ESTRATEGIAS DE GENERACIÓN ===


@st.composite
def out_of_range_value(draw, min_val: int, max_val: int):
    """
    Genera un valor entero fuera del rango [min_val, max_val].

    Produce valores por debajo del mínimo o por encima del máximo,
    garantizando que el valor generado está fuera del rango válido.
    """
    # Decidir si generar por debajo del mínimo o por encima del máximo
    below = draw(st.booleans())
    if below:
        # Generar valor por debajo del mínimo
        return draw(st.integers(max_value=min_val - 1))
    else:
        # Generar valor por encima del máximo
        return draw(st.integers(min_value=max_val + 1))


@st.composite
def in_range_value(draw, min_val: int, max_val: int):
    """
    Genera un valor entero dentro del rango [min_val, max_val].

    Útil para verificar que valores válidos no se modifican.
    """
    return draw(st.integers(min_value=min_val, max_value=max_val))


@st.composite
def config_field_index(draw):
    """
    Genera un índice válido para seleccionar un campo de CONFIG_RANGES.
    """
    return draw(st.integers(min_value=0, max_value=len(CONFIG_RANGES) - 1))


# === PROPERTY 18: CONFIGURATION VALIDATION FALLBACK ===


class TestConfigurationValidationFallback:
    """
    Property 18: Configuration validation fallback.

    Para cualquier valor de configuración fuera de su rango válido,
    el validador de Settings debe aplicar el valor por defecto y emitir
    un warning. El valor resultante siempre está dentro del rango válido.

    **Validates: Requirements 13.2**
    """

    @given(field_idx=config_field_index(), data=st.data())
    @hypothesis_settings(max_examples=100, deadline=None)
    def test_valor_fuera_de_rango_aplica_default(
        self, field_idx: int, data: st.DataObject
    ):
        """
        Para cualquier campo de configuración con un valor fuera de rango,
        el validador debe reemplazarlo por el valor por defecto.

        **Validates: Requirements 13.2**
        """
        field_name, min_val, max_val, default_val = CONFIG_RANGES[field_idx]
        invalid_value = data.draw(
            out_of_range_value(min_val=min_val, max_val=max_val),
            label=f"valor_invalido_para_{field_name}",
        )

        # Crear Settings con el valor fuera de rango usando env vars
        env_override = {field_name: str(invalid_value)}
        with patch.dict("os.environ", env_override, clear=False):
            instance = Settings(**{field_name: invalid_value})

        resultado = getattr(instance, field_name)

        assert resultado == default_val, (
            f"{field_name}={invalid_value} (fuera de rango [{min_val}, {max_val}]) "
            f"debería haber sido reemplazado por default={default_val}, "
            f"pero el valor resultante es {resultado}."
        )

    @given(field_idx=config_field_index(), data=st.data())
    @hypothesis_settings(max_examples=100, deadline=None)
    def test_valor_fuera_de_rango_emite_warning(
        self, field_idx: int, data: st.DataObject
    ):
        """
        Para cualquier campo de configuración con un valor fuera de rango,
        el validador debe emitir un warning en el log.

        **Validates: Requirements 13.2**
        """
        field_name, min_val, max_val, default_val = CONFIG_RANGES[field_idx]
        invalid_value = data.draw(
            out_of_range_value(min_val=min_val, max_val=max_val),
            label=f"valor_invalido_para_{field_name}",
        )

        # Capturar logs para verificar el warning
        with patch.dict("os.environ", {field_name: str(invalid_value)}, clear=False):
            with patch("app.core.config.logger") as mock_logger:
                Settings(**{field_name: invalid_value})

        # Verificar que se emitió al menos un warning
        mock_logger.warning.assert_called()
        # Verificar que el warning menciona el campo
        warning_calls = mock_logger.warning.call_args_list
        warning_texts = [
            str(call) for call in warning_calls
        ]
        field_mentioned = any(field_name in text for text in warning_texts)
        assert field_mentioned, (
            f"Se esperaba un warning mencionando '{field_name}' cuando el valor "
            f"{invalid_value} está fuera de rango [{min_val}, {max_val}], "
            f"pero no se encontró en los warnings emitidos: {warning_texts}"
        )

    @given(field_idx=config_field_index(), data=st.data())
    @hypothesis_settings(max_examples=100, deadline=None)
    def test_valor_resultante_siempre_dentro_de_rango(
        self, field_idx: int, data: st.DataObject
    ):
        """
        Independientemente del valor de entrada (válido o inválido),
        el valor resultante en Settings siempre está dentro del rango válido.

        **Validates: Requirements 13.2**
        """
        field_name, min_val, max_val, default_val = CONFIG_RANGES[field_idx]
        # Generar cualquier valor entero (puede estar dentro o fuera de rango)
        any_value = data.draw(
            st.integers(min_value=-1_000_000_000, max_value=1_000_000_000),
            label=f"cualquier_valor_para_{field_name}",
        )

        with patch.dict("os.environ", {field_name: str(any_value)}, clear=False):
            instance = Settings(**{field_name: any_value})

        resultado = getattr(instance, field_name)

        assert min_val <= resultado <= max_val, (
            f"{field_name}: valor de entrada={any_value}, valor resultante={resultado} "
            f"está fuera del rango válido [{min_val}, {max_val}]. "
            f"El validador debería garantizar que el resultado siempre está en rango."
        )

    @given(field_idx=config_field_index(), data=st.data())
    @hypothesis_settings(max_examples=100, deadline=None)
    def test_valor_dentro_de_rango_no_se_modifica(
        self, field_idx: int, data: st.DataObject
    ):
        """
        Para cualquier campo de configuración con un valor dentro del rango válido,
        el validador no debe modificar el valor.

        **Validates: Requirements 13.2**
        """
        field_name, min_val, max_val, default_val = CONFIG_RANGES[field_idx]
        valid_value = data.draw(
            in_range_value(min_val=min_val, max_val=max_val),
            label=f"valor_valido_para_{field_name}",
        )

        with patch.dict("os.environ", {field_name: str(valid_value)}, clear=False):
            instance = Settings(**{field_name: valid_value})

        resultado = getattr(instance, field_name)

        assert resultado == valid_value, (
            f"{field_name}={valid_value} (dentro de rango [{min_val}, {max_val}]) "
            f"no debería haber sido modificado, pero el valor resultante es {resultado}."
        )
