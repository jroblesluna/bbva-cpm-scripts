"""
Property tests para detección de keywords y normalización de líneas.

Verifica las propiedades fundamentales de detect_keywords y normalize_line:
- Property 5: Corrección de detección de keywords (case-insensitive)
- Property 6: El orden de normalización preserva patrones específicos

**Validates: Requirements 5.2, 5.3, 7.1-7.6**
"""

import re

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.services.log_processor import (
    DEFAULT_KEYWORDS,
    detect_keywords,
    normalize_line,
)


# === ESTRATEGIAS DE GENERACIÓN ===

# Texto genérico que NO contiene ningún keyword por defecto
_safe_alphabet = st.characters(
    whitelist_categories=("L",),
    whitelist_characters=" ",
)

# Estrategia para generar texto que garantizadamente NO contiene keywords
@st.composite
def text_without_keywords(draw):
    """
    Genera una línea de texto que no contiene ningún keyword de DEFAULT_KEYWORDS.

    Usa un alfabeto restringido (solo letras y espacios) y verifica
    que ningún substring coincida con los keywords.
    """
    # Generar texto base con caracteres seguros
    base = draw(st.text(alphabet="abcdfghijkmnopquvxyz ", min_size=1, max_size=200))
    # Verificar que no contiene ningún keyword (case-insensitive)
    lower_base = base.lower()
    for kw in DEFAULT_KEYWORDS:
        assume(kw.lower() not in lower_base)
    return base


# Estrategia para seleccionar un keyword de la lista por defecto
_keyword_from_default = st.sampled_from(DEFAULT_KEYWORDS)


# Estrategia para generar variaciones de case de un string
@st.composite
def randomize_case(draw, text_str: str):
    """Genera una variación aleatoria de mayúsculas/minúsculas del texto dado."""
    result = []
    for char in text_str:
        if draw(st.booleans()):
            result.append(char.upper())
        else:
            result.append(char.lower())
    return "".join(result)


# Estrategia para generar texto de relleno (sin keywords)
_filler_text = st.text(
    alphabet="abcdfghijkmnopquvxyz0123456789 .,;:()[]{}",
    min_size=0,
    max_size=100,
)


# Estrategia para generar timestamps válidos
@st.composite
def valid_timestamp(draw):
    """
    Genera un timestamp en formato YYYY-MM-DD HH:MM:SS con valores realistas.
    """
    year = draw(st.integers(min_value=2020, max_value=2030))
    month = draw(st.integers(min_value=1, max_value=12))
    day = draw(st.integers(min_value=1, max_value=28))
    hour = draw(st.integers(min_value=0, max_value=23))
    minute = draw(st.integers(min_value=0, max_value=59))
    second = draw(st.integers(min_value=0, max_value=59))
    return f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}"


# Estrategia para generar UUIDs válidos
@st.composite
def valid_uuid(draw):
    """
    Genera un UUID en formato xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.
    """
    hex_chars = "0123456789abcdef"
    parts = [
        draw(st.text(alphabet=hex_chars, min_size=8, max_size=8)),
        draw(st.text(alphabet=hex_chars, min_size=4, max_size=4)),
        draw(st.text(alphabet=hex_chars, min_size=4, max_size=4)),
        draw(st.text(alphabet=hex_chars, min_size=4, max_size=4)),
        draw(st.text(alphabet=hex_chars, min_size=12, max_size=12)),
    ]
    return "-".join(parts)


# Estrategia para generar IPs válidas
@st.composite
def valid_ipv4(draw):
    """
    Genera una dirección IPv4 válida (cada octeto entre 0 y 255).
    """
    octets = [draw(st.integers(min_value=0, max_value=255)) for _ in range(4)]
    return ".".join(str(o) for o in octets)


# Estrategia para generar rutas temporales Windows
@st.composite
def valid_temp_path(draw):
    """
    Genera una ruta temporal Windows con \\Temp\\ o \\tmp\\.
    """
    drive = draw(st.sampled_from(["C", "D", "E"]))
    temp_variant = draw(st.sampled_from(["Temp", "temp", "TMP", "tmp"]))
    filename = draw(st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_", min_size=3, max_size=15))
    ext = draw(st.sampled_from([".tmp", ".log", ".dat", ".txt"]))
    return f"{drive}:\\Users\\admin\\AppData\\Local\\{temp_variant}\\{filename}{ext}"


# === PROPERTY 5: KEYWORD DETECTION CORRECTNESS ===


class TestKeywordDetectionCorrectness:
    """
    Property 5: Keyword detection correctness.

    Para cualquier línea que contenga un keyword (case-insensitive),
    detect_keywords debe retornar True. Para cualquier línea que NO
    contenga ningún keyword, debe retornar False.

    **Validates: Requirements 5.2, 5.3**
    """

    @given(
        keyword=_keyword_from_default,
        prefix=_filler_text,
        suffix=_filler_text,
        data=st.data(),
    )
    @settings(max_examples=200, deadline=None)
    def test_line_containing_keyword_returns_true(
        self, keyword: str, prefix: str, suffix: str, data
    ):
        """
        Si una línea contiene un keyword (en cualquier variación de case),
        detect_keywords con case_insensitive=True retorna True.

        **Validates: Requirements 5.2, 5.3**
        """
        # Generar variación de case del keyword
        case_variant = data.draw(randomize_case(keyword))

        # Construir línea con el keyword embebido
        line = f"{prefix}{case_variant}{suffix}"

        # Propiedad: detect_keywords debe retornar True
        result = detect_keywords(line, DEFAULT_KEYWORDS, case_insensitive=True)
        assert result is True, (
            f"detect_keywords debería retornar True para línea que contiene "
            f"keyword '{keyword}' (variante: '{case_variant}'). "
            f"Línea: '{line[:100]}...'"
        )

    @given(line=text_without_keywords())
    @settings(max_examples=200, deadline=None)
    def test_line_without_keywords_returns_false(self, line: str):
        """
        Si una línea NO contiene ningún keyword de la lista (en ninguna
        variación de case), detect_keywords retorna False.

        **Validates: Requirements 5.2, 5.3**
        """
        result = detect_keywords(line, DEFAULT_KEYWORDS, case_insensitive=True)
        assert result is False, (
            f"detect_keywords debería retornar False para línea sin keywords. "
            f"Línea: '{line[:100]}...'"
        )

    @given(
        keyword=_keyword_from_default,
        prefix=_filler_text,
        suffix=_filler_text,
    )
    @settings(max_examples=100, deadline=None)
    def test_case_insensitive_detects_uppercase_keyword(
        self, keyword: str, prefix: str, suffix: str
    ):
        """
        detect_keywords con case_insensitive=True detecta keywords
        en mayúsculas completas.

        **Validates: Requirements 5.3**
        """
        line = f"{prefix}{keyword.upper()}{suffix}"
        result = detect_keywords(line, DEFAULT_KEYWORDS, case_insensitive=True)
        assert result is True, (
            f"detect_keywords debería detectar keyword '{keyword}' en mayúsculas "
            f"('{keyword.upper()}'). Línea: '{line[:100]}...'"
        )


# === PROPERTY 6: NORMALIZATION ORDER PRESERVES SPECIFIC PATTERNS ===


class TestNormalizationOrderPreservesPatterns:
    """
    Property 6: Normalization order preserves specific patterns.

    Timestamps, UUIDs, IPs y rutas temporales se reemplazan ANTES que
    las secuencias numéricas, de modo que sus dígitos internos no son
    reemplazados por [NUMBER].

    **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6**
    """

    @given(
        timestamp=valid_timestamp(),
        extra_number=st.integers(min_value=10, max_value=9999),
        prefix=st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", min_size=0, max_size=30),
    )
    @settings(max_examples=200, deadline=None)
    def test_timestamp_replaced_before_numbers(
        self, timestamp: str, extra_number: int, prefix: str
    ):
        """
        Una línea con un timestamp produce [TIMESTAMP] y no
        [NUMBER]-[NUMBER]-[NUMBER] [NUMBER]:[NUMBER]:[NUMBER].

        **Validates: Requirements 7.1, 7.6**
        """
        line = f"{prefix}[{timestamp}] Event {extra_number}: something happened"
        result = normalize_line(line)

        # Propiedad: el timestamp se reemplaza como [TIMESTAMP]
        assert "[TIMESTAMP]" in result, (
            f"normalize_line debe producir [TIMESTAMP] para línea con timestamp. "
            f"Línea: '{line}', Resultado: '{result}'"
        )

        # Propiedad: los dígitos del timestamp original no aparecen como fragmentos
        # (el año, mes, día, hora, minuto, segundo no deben quedar sueltos)
        year_str = timestamp[:4]
        assert year_str not in result, (
            f"Los dígitos del timestamp ({year_str}) no deben quedar en el resultado. "
            f"Línea: '{line}', Resultado: '{result}'"
        )

    @given(
        uuid_str=valid_uuid(),
        extra_number=st.integers(min_value=10, max_value=9999),
        prefix=st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", min_size=0, max_size=30),
    )
    @settings(max_examples=200, deadline=None)
    def test_uuid_replaced_before_numbers(
        self, uuid_str: str, extra_number: int, prefix: str
    ):
        """
        Una línea con un UUID produce [UUID] y no fragmentos de [NUMBER]
        separados por guiones.

        **Validates: Requirements 7.2, 7.6**
        """
        line = f"{prefix}request {uuid_str} count {extra_number}"
        result = normalize_line(line)

        # Propiedad: el UUID se reemplaza como [UUID]
        assert "[UUID]" in result, (
            f"normalize_line debe producir [UUID] para línea con UUID. "
            f"Línea: '{line}', Resultado: '{result}'"
        )

        # Propiedad: el UUID original no aparece en el resultado
        assert uuid_str not in result, (
            f"El UUID original no debe quedar en el resultado. "
            f"UUID: '{uuid_str}', Resultado: '{result}'"
        )

    @given(
        ip=valid_ipv4(),
        extra_number=st.integers(min_value=10, max_value=9999),
        prefix=st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", min_size=0, max_size=30),
    )
    @settings(max_examples=200, deadline=None)
    def test_ip_replaced_before_numbers(
        self, ip: str, extra_number: int, prefix: str
    ):
        """
        Una línea con una IP produce [IP] y no [NUMBER].[NUMBER].[NUMBER].[NUMBER].

        **Validates: Requirements 7.3, 7.6**
        """
        line = f"{prefix}connection to {ip} port {extra_number}"
        result = normalize_line(line)

        # Propiedad: la IP se reemplaza como [IP]
        assert "[IP]" in result, (
            f"normalize_line debe producir [IP] para línea con IPv4. "
            f"Línea: '{line}', Resultado: '{result}'"
        )

        # Propiedad: la IP original no aparece en el resultado
        assert ip not in result, (
            f"La IP original no debe quedar en el resultado. "
            f"IP: '{ip}', Resultado: '{result}'"
        )

    @given(
        temp_path=valid_temp_path(),
        extra_number=st.integers(min_value=10, max_value=9999),
        prefix=st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", min_size=0, max_size=30),
    )
    @settings(max_examples=200, deadline=None)
    def test_temp_path_replaced_before_numbers(
        self, temp_path: str, extra_number: int, prefix: str
    ):
        """
        Una línea con una ruta temporal Windows produce [TEMP_PATH] y no
        fragmentos con [NUMBER] dentro de la ruta.

        **Validates: Requirements 7.4, 7.6**
        """
        line = f"{prefix}writing to {temp_path} size {extra_number}"
        result = normalize_line(line)

        # Propiedad: la ruta temporal se reemplaza como [TEMP_PATH]
        assert "[TEMP_PATH]" in result, (
            f"normalize_line debe producir [TEMP_PATH] para línea con ruta temporal. "
            f"Línea: '{line}', Resultado: '{result}'"
        )

        # Propiedad: la ruta original no aparece en el resultado
        assert temp_path not in result, (
            f"La ruta temporal original no debe quedar en el resultado. "
            f"Ruta: '{temp_path}', Resultado: '{result}'"
        )

    @given(
        extra_number=st.integers(min_value=10, max_value=99999),
        prefix=st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", min_size=1, max_size=30),
    )
    @settings(max_examples=100, deadline=None)
    def test_standalone_numbers_replaced_last(
        self, extra_number: int, prefix: str
    ):
        """
        Secuencias numéricas de 2+ dígitos que no forman parte de un
        patrón específico se reemplazan por [NUMBER].

        **Validates: Requirements 7.5, 7.6**
        """
        line = f"{prefix}code {extra_number} at step {extra_number + 1}"
        result = normalize_line(line)

        # Propiedad: los números se reemplazan como [NUMBER]
        assert "[NUMBER]" in result, (
            f"normalize_line debe producir [NUMBER] para secuencias numéricas. "
            f"Línea: '{line}', Resultado: '{result}'"
        )

        # Propiedad: el número original no aparece en el resultado
        assert str(extra_number) not in result, (
            f"El número original ({extra_number}) no debe quedar en el resultado. "
            f"Línea: '{line}', Resultado: '{result}'"
        )

    @given(
        timestamp=valid_timestamp(),
        uuid_str=valid_uuid(),
        ip=valid_ipv4(),
        extra_number=st.integers(min_value=10, max_value=9999),
    )
    @settings(max_examples=100, deadline=None)
    def test_all_patterns_coexist_without_number_interference(
        self, timestamp: str, uuid_str: str, ip: str, extra_number: int
    ):
        """
        Cuando una línea contiene timestamp, UUID, IP y números sueltos,
        cada patrón se reemplaza por su placeholder correcto sin interferencia.

        **Validates: Requirements 7.1, 7.2, 7.3, 7.5, 7.6**
        """
        line = (
            f"[{timestamp}] host {ip} request {uuid_str} "
            f"retry {extra_number}"
        )
        result = normalize_line(line)

        # Propiedad: todos los placeholders específicos están presentes
        assert "[TIMESTAMP]" in result, (
            f"Debe contener [TIMESTAMP]. Resultado: '{result}'"
        )
        assert "[IP]" in result, (
            f"Debe contener [IP]. Resultado: '{result}'"
        )
        assert "[UUID]" in result, (
            f"Debe contener [UUID]. Resultado: '{result}'"
        )
        assert "[NUMBER]" in result, (
            f"Debe contener [NUMBER] para el número suelto. Resultado: '{result}'"
        )

        # Propiedad: los valores originales no aparecen
        assert timestamp not in result, (
            f"El timestamp original no debe quedar. Resultado: '{result}'"
        )
        assert uuid_str not in result, (
            f"El UUID original no debe quedar. Resultado: '{result}'"
        )
        assert ip not in result, (
            f"La IP original no debe quedar. Resultado: '{result}'"
        )
