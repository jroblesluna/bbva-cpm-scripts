"""
Property tests para descompresión de logs y enrutamiento por tamaño.

Verifica las propiedades fundamentales del módulo log_processor:
- Round-trip de compresión/descompresión ZIP
- Validación de extensiones de archivo en ZIP
- Concatenación alfabética de múltiples archivos en ZIP
- Decisión de enrutamiento basada en tamaño UTF-8

**Validates: Requirements 2.2, 2.3, 2.5, 2.6, 3.1, 3.2**
"""

import io
import zipfile

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.services.log_processor import decompress_if_needed, route_by_size


# === ESTRATEGIAS DE GENERACIÓN ===

# Estrategia para contenido de texto válido (simula contenido de log)
_text_content = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z", "S"),
        whitelist_characters="\n\r\t",
    ),
    min_size=1,
    max_size=5000,
)

# Estrategia para nombres de archivo con extensión válida (.log o .txt)
_valid_extensions = st.sampled_from([".log", ".txt"])

# Estrategia para nombres base de archivo (sin caracteres problemáticos para ZIP)
_filename_base = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
    ),
    min_size=1,
    max_size=20,
)


@st.composite
def valid_log_filename(draw):
    """
    Genera un nombre de archivo con extensión válida (.log o .txt).

    Produce nombres como 'archivo1.log' o 'datos.txt'.
    """
    base = draw(_filename_base)
    ext = draw(_valid_extensions)
    return base + ext


@st.composite
def invalid_extension_filename(draw):
    """
    Genera un nombre de archivo con extensión NO válida (ni .log ni .txt).

    Produce nombres como 'archivo.csv', 'datos.xml', etc.
    """
    base = draw(_filename_base)
    ext = draw(
        st.sampled_from([".csv", ".xml", ".json", ".dat", ".bin", ".pdf", ".doc"])
    )
    return base + ext


@st.composite
def multiple_valid_filenames(draw):
    """
    Genera una lista de 2 a 5 nombres de archivo con extensiones válidas,
    todos distintos entre sí.
    """
    count = draw(st.integers(min_value=2, max_value=5))
    filenames = set()
    while len(filenames) < count:
        name = draw(valid_log_filename())
        filenames.add(name)
    return sorted(filenames)


def _create_zip_bytes(file_contents: list[tuple[str, str]]) -> bytes:
    """
    Crea un archivo ZIP en memoria con los archivos especificados.

    Args:
        file_contents: Lista de tuplas (nombre_archivo, contenido_texto)

    Returns:
        Bytes del archivo ZIP generado
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, content in file_contents:
            zf.writestr(filename, content.encode("utf-8"))
    return buffer.getvalue()


# === PROPERTY 1: ZIP DECOMPRESSION ROUND-TRIP ===


class TestZipDecompressionRoundTrip:
    """
    Property 1: ZIP decompression round-trip.

    Cualquier contenido de texto válido comprimido a ZIP y descomprimido
    debe producir el contenido original sin pérdida de información.

    **Validates: Requirements 2.2, 2.3**
    """

    @given(content=_text_content, filename=valid_log_filename())
    @settings(max_examples=100, deadline=None)
    def test_single_file_roundtrip(self, content: str, filename: str):
        """
        Un archivo de texto comprimido a ZIP y descomprimido produce
        el contenido original idéntico.

        **Validates: Requirements 2.2**
        """
        # Comprimir contenido a ZIP
        zip_bytes = _create_zip_bytes([(filename, content)])

        # Descomprimir usando la función bajo test
        result_content, file_list = decompress_if_needed(zip_bytes, is_compressed=True)

        # Propiedad: el contenido descomprimido es idéntico al original
        assert result_content == content, (
            f"El contenido descomprimido no coincide con el original. "
            f"Archivo: '{filename}', Longitud original: {len(content)}, "
            f"Longitud resultado: {len(result_content)}"
        )

    @given(content=_text_content)
    @settings(max_examples=100, deadline=None)
    def test_uncompressed_payload_roundtrip(self, content: str):
        """
        Un payload no comprimido (is_compressed=False) se decodifica
        directamente como UTF-8 sin modificación.

        **Validates: Requirements 2.3**
        """
        # Codificar contenido como bytes UTF-8
        payload = content.encode("utf-8")

        # Pasar como no comprimido
        result_content, file_list = decompress_if_needed(payload, is_compressed=False)

        # Propiedad: el contenido es idéntico al original
        assert result_content == content, (
            f"El contenido no comprimido no se decodificó correctamente. "
            f"Longitud original: {len(content)}, "
            f"Longitud resultado: {len(result_content)}"
        )

        # Propiedad: file_list contiene una entrada "raw"
        assert len(file_list) == 1, (
            f"Se esperaba exactamente 1 entrada en file_list para payload no comprimido. "
            f"Obtenido: {len(file_list)}"
        )
        assert file_list[0][0] == "raw", (
            f"El nombre del archivo para payload no comprimido debe ser 'raw'. "
            f"Obtenido: '{file_list[0][0]}'"
        )


# === PROPERTY 2: ZIP FILE EXTENSION VALIDATION ===


class TestZipFileExtensionValidation:
    """
    Property 2: ZIP file extension validation.

    Archivos ZIP que contienen SOLO archivos sin extensión .log/.txt
    deben lanzar ValueError, ya que no hay contenido de log válido.

    **Validates: Requirements 2.5**
    """

    @given(
        filenames=st.lists(
            invalid_extension_filename(), min_size=1, max_size=5, unique=True
        ),
        content=_text_content,
    )
    @settings(max_examples=100, deadline=None)
    def test_zip_without_valid_extensions_raises_error(
        self, filenames: list[str], content: str
    ):
        """
        Un ZIP que solo contiene archivos con extensiones no válidas
        (.csv, .xml, etc.) debe lanzar ValueError.

        **Validates: Requirements 2.5**
        """
        # Crear ZIP con archivos de extensiones inválidas
        file_contents = [(name, content) for name in filenames]
        zip_bytes = _create_zip_bytes(file_contents)

        # Propiedad: debe lanzar ValueError
        import pytest

        with pytest.raises(ValueError) as exc_info:
            decompress_if_needed(zip_bytes, is_compressed=True)

        # Verificar que el mensaje menciona extensiones válidas
        assert ".log" in str(exc_info.value) or ".txt" in str(exc_info.value), (
            f"El mensaje de error debe mencionar las extensiones válidas. "
            f"Mensaje obtenido: '{exc_info.value}'"
        )

    @given(
        valid_filename=valid_log_filename(),
        invalid_filename=invalid_extension_filename(),
        content=_text_content,
    )
    @settings(max_examples=100, deadline=None)
    def test_zip_with_mixed_extensions_extracts_valid_only(
        self, valid_filename: str, invalid_filename: str, content: str
    ):
        """
        Un ZIP con mezcla de extensiones válidas e inválidas debe extraer
        solo los archivos con extensión válida, sin error.

        **Validates: Requirements 2.5**
        """
        assume(valid_filename != invalid_filename)

        # Crear ZIP con un archivo válido y uno inválido
        file_contents = [
            (valid_filename, content),
            (invalid_filename, "contenido ignorado"),
        ]
        zip_bytes = _create_zip_bytes(file_contents)

        # Propiedad: no lanza error y extrae solo el archivo válido
        result_content, file_list = decompress_if_needed(zip_bytes, is_compressed=True)

        # Solo debe haber un archivo en la lista (el válido)
        assert len(file_list) == 1, (
            f"Se esperaba 1 archivo válido extraído, obtenido: {len(file_list)}. "
            f"Archivos: {[f[0] for f in file_list]}"
        )
        assert file_list[0][0] == valid_filename, (
            f"El archivo extraído debe ser el de extensión válida. "
            f"Esperado: '{valid_filename}', Obtenido: '{file_list[0][0]}'"
        )
        assert result_content == content, (
            f"El contenido extraído debe ser el del archivo válido."
        )


# === PROPERTY 3: MULTI-FILE CONCATENATION PRESERVES ALPHABETICAL ORDER ===


class TestMultiFileConcatenation:
    """
    Property 3: Multi-file concatenation preserves alphabetical order.

    Cuando un ZIP contiene múltiples archivos válidos, deben concatenarse
    en orden alfabético por nombre de archivo.

    **Validates: Requirements 2.6**
    """

    @given(
        filenames=st.lists(
            valid_log_filename(), min_size=2, max_size=5, unique=True
        ),
        contents=st.lists(_text_content, min_size=5, max_size=5),
    )
    @settings(max_examples=100, deadline=None)
    def test_files_concatenated_in_alphabetical_order(
        self, filenames: list[str], contents: list[str]
    ):
        """
        Los archivos de un ZIP se concatenan en orden alfabético por nombre,
        con headers separadores indicando el nombre de cada archivo fuente.

        **Validates: Requirements 2.6**
        """
        # Usar solo tantos contenidos como filenames
        file_contents = list(zip(filenames, contents[: len(filenames)]))

        # Crear ZIP (el orden de inserción puede ser cualquiera)
        zip_bytes = _create_zip_bytes(file_contents)

        # Descomprimir
        result_content, file_list = decompress_if_needed(zip_bytes, is_compressed=True)

        # Propiedad: file_list está en orden alfabético
        extracted_names = [f[0] for f in file_list]
        assert extracted_names == sorted(extracted_names), (
            f"Los archivos no están en orden alfabético. "
            f"Obtenido: {extracted_names}, "
            f"Esperado: {sorted(extracted_names)}"
        )

        # Propiedad: el contenido concatenado contiene headers con nombres de archivo
        sorted_filenames = sorted(filenames)
        for fname in sorted_filenames:
            header = f"=== Archivo: {fname} ==="
            assert header in result_content, (
                f"El contenido concatenado debe incluir header para '{fname}'. "
                f"Header esperado: '{header}'"
            )

        # Propiedad: los headers aparecen en orden alfabético en el resultado
        header_positions = []
        for fname in sorted_filenames:
            header = f"=== Archivo: {fname} ==="
            pos = result_content.find(header)
            header_positions.append(pos)

        assert header_positions == sorted(header_positions), (
            f"Los headers no aparecen en orden alfabético en el resultado. "
            f"Posiciones: {list(zip(sorted_filenames, header_positions))}"
        )

    @given(content=_text_content, filename=valid_log_filename())
    @settings(max_examples=100, deadline=None)
    def test_single_file_no_header(self, content: str, filename: str):
        """
        Cuando el ZIP contiene un solo archivo válido, el resultado NO
        incluye headers de separación (se retorna el contenido directo).

        **Validates: Requirements 2.6**
        """
        zip_bytes = _create_zip_bytes([(filename, content)])

        result_content, file_list = decompress_if_needed(zip_bytes, is_compressed=True)

        # Propiedad: sin header para archivo único
        header = f"=== Archivo: {filename} ==="
        assert header not in result_content, (
            f"Un ZIP con un solo archivo no debe incluir header de separación. "
            f"Header encontrado: '{header}'"
        )

        # Propiedad: contenido es exactamente el del archivo
        assert result_content == content, (
            f"El contenido de un ZIP con un solo archivo debe ser idéntico al original."
        )


# === PROPERTY 4: ROUTING DECISION CORRECTNESS ===


class TestRoutingDecisionCorrectness:
    """
    Property 4: Routing decision correctness.

    route_by_size retorna "direct" para contenido cuyo tamaño UTF-8 es
    menor que el threshold, y "structural" para contenido cuyo tamaño
    es igual o mayor que el threshold.

    **Validates: Requirements 3.1, 3.2**
    """

    @given(
        content=_text_content,
        threshold=st.integers(min_value=1, max_value=1_000_000),
    )
    @settings(max_examples=200, deadline=None)
    def test_routing_decision_matches_utf8_size(
        self, content: str, threshold: int
    ):
        """
        La decisión de enrutamiento se basa estrictamente en el tamaño
        UTF-8 del contenido comparado con el threshold.

        **Validates: Requirements 3.1, 3.2**
        """
        content_size = len(content.encode("utf-8"))
        result = route_by_size(content, threshold_bytes=threshold)

        if content_size < threshold:
            assert result == "direct", (
                f"Contenido de {content_size} bytes (< threshold {threshold}) "
                f"debe enrutarse como 'direct', obtenido: '{result}'"
            )
        else:
            assert result == "structural", (
                f"Contenido de {content_size} bytes (>= threshold {threshold}) "
                f"debe enrutarse como 'structural', obtenido: '{result}'"
            )

    @given(threshold=st.integers(min_value=1, max_value=1_000_000))
    @settings(max_examples=100, deadline=None)
    def test_empty_content_always_direct(self, threshold: int):
        """
        Contenido vacío (0 bytes) siempre se enruta como 'direct'
        ya que 0 < cualquier threshold positivo.

        **Validates: Requirements 3.1**
        """
        result = route_by_size("", threshold_bytes=threshold)

        assert result == "direct", (
            f"Contenido vacío (0 bytes) debe ser 'direct' con threshold {threshold}. "
            f"Obtenido: '{result}'"
        )

    @given(
        char=st.characters(whitelist_categories=("L", "N")),
        threshold=st.integers(min_value=1, max_value=100),
    )
    @settings(max_examples=100, deadline=None)
    def test_boundary_at_threshold(self, char: str, threshold: int):
        """
        Contenido cuyo tamaño UTF-8 es exactamente igual al threshold
        se enruta como 'structural' (>= threshold).

        **Validates: Requirements 3.2**
        """
        # Generar contenido de exactamente threshold bytes
        char_bytes = len(char.encode("utf-8"))
        assume(char_bytes > 0)
        assume(threshold % char_bytes == 0)

        repeat_count = threshold // char_bytes
        content = char * repeat_count

        # Verificar que el tamaño es exactamente el threshold
        actual_size = len(content.encode("utf-8"))
        assume(actual_size == threshold)

        result = route_by_size(content, threshold_bytes=threshold)

        assert result == "structural", (
            f"Contenido de exactamente {threshold} bytes (== threshold) "
            f"debe enrutarse como 'structural', obtenido: '{result}'"
        )
