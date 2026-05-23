"""
Property tests para output estructurado y ensamblaje de payload del log_processor.

Verifica las propiedades fundamentales de generate_structured_output y assemble_direct_payload:
- Property 14: Structured output sections in fixed order
- Property 15: Context block formatting marks only match lines
- Property 17: Direct path payload assembly

**Validates: Requirements 9.1, 9.5, 4.1, 4.2, 4.3**
"""

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.services.log_processor import (
    ContextBlock,
    MatchInfo,
    RecurringPattern,
    StructuralAnalysisResult,
    TimelineEntry,
    assemble_direct_payload,
    generate_structured_output,
)


# === ESTRATEGIAS DE GENERACIÓN ===


@st.composite
def recurring_pattern(draw):
    """Genera un RecurringPattern válido para testing."""
    count = draw(st.integers(min_value=2, max_value=100))
    first_line = draw(st.integers(min_value=1, max_value=5000))
    has_ts = draw(st.booleans())
    first_timestamp = (
        draw(st.from_regex(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", fullmatch=True))
        if has_ts
        else None
    )
    normalized_text = draw(st.text(min_size=5, max_size=80, alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        blacklist_characters="\x00",
    )))
    raw_example = draw(st.text(min_size=5, max_size=200, alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        blacklist_characters="\x00",
    )))
    return RecurringPattern(
        normalized_text=normalized_text,
        count=count,
        first_line=first_line,
        first_timestamp=first_timestamp,
        raw_example=raw_example,
    )


@st.composite
def match_info(draw):
    """Genera un MatchInfo válido para testing."""
    line_number = draw(st.integers(min_value=1, max_value=5000))
    has_ts = draw(st.booleans())
    timestamp = (
        draw(st.from_regex(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", fullmatch=True))
        if has_ts
        else None
    )
    content = draw(st.text(min_size=5, max_size=200, alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        blacklist_characters="\x00",
    )))
    normalized = draw(st.text(min_size=5, max_size=100, alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        blacklist_characters="\x00",
    )))
    return MatchInfo(
        line_number=line_number,
        timestamp=timestamp,
        content=content,
        normalized=normalized,
    )


@st.composite
def context_block(draw, min_lines: int = 3, max_lines: int = 20):
    """
    Genera un ContextBlock válido con líneas y match_lines consistentes.

    Garantiza que match_lines es un subconjunto de los line_numbers en lines.
    """
    start_line = draw(st.integers(min_value=1, max_value=2000))
    num_lines = draw(st.integers(min_value=min_lines, max_value=max_lines))
    end_line = start_line + num_lines - 1

    lines = []
    for i in range(num_lines):
        line_num = start_line + i
        content = draw(st.text(min_size=1, max_size=80, alphabet=st.characters(
            whitelist_categories=("L", "N", "P", "Z"),
            blacklist_characters="\x00",
        )))
        lines.append((line_num, content))

    # Seleccionar al menos 1 match_line del rango
    all_line_nums = [ln for ln, _ in lines]
    num_matches = draw(st.integers(min_value=1, max_value=max(1, len(all_line_nums) // 3)))
    match_indices = draw(st.lists(
        st.integers(min_value=0, max_value=len(all_line_nums) - 1),
        min_size=num_matches,
        max_size=num_matches,
        unique=True,
    ))
    match_lines = {all_line_nums[idx] for idx in match_indices}

    return ContextBlock(
        start_line=start_line,
        end_line=end_line,
        lines=lines,
        match_lines=match_lines,
    )


@st.composite
def timeline_entry(draw):
    """Genera un TimelineEntry válido."""
    time_group = draw(st.from_regex(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", fullmatch=True
    ))
    total_count = draw(st.integers(min_value=1, max_value=50))
    num_types = draw(st.integers(min_value=1, max_value=5))
    event_types = {}
    remaining = total_count
    for i in range(num_types):
        type_name = draw(st.text(min_size=3, max_size=30, alphabet=st.characters(
            whitelist_categories=("L", "N"),
            blacklist_characters="\x00",
        )))
        if i == num_types - 1:
            event_types[type_name] = remaining
        else:
            count = draw(st.integers(min_value=1, max_value=max(1, remaining - (num_types - i - 1))))
            event_types[type_name] = count
            remaining -= count
    return TimelineEntry(
        time_group=time_group,
        total_count=total_count,
        event_types=event_types,
    )


@st.composite
def structural_analysis_result_with_matches(draw):
    """
    Genera un StructuralAnalysisResult con matches (no_matches=False).

    Incluye patrones, ocurrencias críticas, bloques de contexto y timeline.
    """
    source_name = draw(st.text(min_size=3, max_size=50, alphabet=st.characters(
        whitelist_categories=("L", "N", "P"),
        blacklist_characters="\x00",
    )))
    file_size_bytes = draw(st.integers(min_value=1000, max_value=10_000_000))
    total_lines = draw(st.integers(min_value=100, max_value=50000))
    total_matches = draw(st.integers(min_value=1, max_value=500))

    patterns = draw(st.lists(recurring_pattern(), min_size=1, max_size=5))
    critical_occurrences = draw(st.lists(match_info(), min_size=1, max_size=5))
    context_blocks_list = draw(st.lists(context_block(), min_size=1, max_size=3))
    timeline_list = draw(st.lists(timeline_entry(), min_size=1, max_size=5))

    has_ts = draw(st.booleans())
    earliest = "2024-01-01 08:00:00" if has_ts else None
    latest = "2024-01-01 17:00:00" if has_ts else None

    return StructuralAnalysisResult(
        source_name=source_name,
        file_size_bytes=file_size_bytes,
        total_lines=total_lines,
        earliest_timestamp=earliest,
        latest_timestamp=latest,
        total_matches=total_matches,
        unique_patterns=len(patterns),
        patterns=patterns,
        critical_occurrences=critical_occurrences,
        context_blocks=context_blocks_list,
        timeline=timeline_list,
        blocks_omitted=draw(st.integers(min_value=0, max_value=10)),
    )


# === PROPERTY 14: STRUCTURED OUTPUT SECTIONS IN FIXED ORDER ===


class TestStructuredOutputSectionsInFixedOrder:
    """
    Property 14: Structured output sections in fixed order.

    El Markdown generado siempre contiene las secciones en orden:
    Metadata, Patrones Recurrentes, Primeras Ocurrencias Críticas,
    Bloques de Contexto, Línea de Tiempo Condensada.
    La posición de cada header de sección es estrictamente creciente.

    **Validates: Requirements 9.1**
    """

    @given(result=structural_analysis_result_with_matches())
    @settings(max_examples=100, deadline=None)
    def test_sections_appear_in_fixed_order(
        self, result: StructuralAnalysisResult
    ):
        """
        Las secciones del output Markdown aparecen en el orden fijo definido:
        Metadata → Patrones Recurrentes → Primeras Ocurrencias Críticas →
        Bloques de Contexto → Línea de Tiempo Condensada.

        **Validates: Requirements 9.1**
        """
        output = generate_structured_output(result)

        # Buscar posiciones de cada sección
        section_headers = [
            "## Metadata",
            "## Patrones Recurrentes",
            "## Primeras Ocurrencias Críticas",
            "## Bloques de Contexto",
            "## Línea de Tiempo Condensada",
        ]

        positions = []
        for header in section_headers:
            pos = output.find(header)
            assert pos != -1, (
                f"Sección '{header}' no encontrada en el output. "
                f"Output generado (primeros 500 chars): {output[:500]}"
            )
            positions.append(pos)

        # Verificar que las posiciones son estrictamente crecientes
        for i in range(len(positions) - 1):
            assert positions[i] < positions[i + 1], (
                f"Orden de secciones incorrecto: "
                f"'{section_headers[i]}' (pos={positions[i]}) debería aparecer "
                f"antes de '{section_headers[i+1]}' (pos={positions[i+1]})"
            )

    @given(result=structural_analysis_result_with_matches())
    @settings(max_examples=100, deadline=None)
    def test_all_five_sections_present(
        self, result: StructuralAnalysisResult
    ):
        """
        El output siempre contiene exactamente las 5 secciones requeridas
        cuando hay matches.

        **Validates: Requirements 9.1**
        """
        output = generate_structured_output(result)

        expected_sections = [
            "## Metadata",
            "## Patrones Recurrentes",
            "## Primeras Ocurrencias Críticas",
            "## Bloques de Contexto",
            "## Línea de Tiempo Condensada",
        ]

        for section in expected_sections:
            assert section in output, (
                f"Sección requerida '{section}' no está presente en el output."
            )


# === PROPERTY 15: CONTEXT BLOCK FORMATTING MARKS ONLY MATCH LINES ===


class TestContextBlockFormattingMarksOnlyMatchLines:
    """
    Property 15: Context block formatting marks only match lines.

    En los bloques de contexto, solo las líneas cuyo line_number está en
    match_lines se prefijan con ">>". Todas las demás usan "   " como prefijo.

    **Validates: Requirements 9.5**
    """

    @given(block=context_block(min_lines=3, max_lines=20))
    @settings(max_examples=100, deadline=None)
    def test_only_match_lines_have_arrow_prefix(self, block: ContextBlock):
        """
        En el output de un bloque de contexto, solo las líneas con line_number
        en match_lines tienen el prefijo ">>". Las demás tienen "   ".

        **Validates: Requirements 9.5**
        """
        # Construir un resultado mínimo con un solo bloque
        result = StructuralAnalysisResult(
            source_name="test.log",
            file_size_bytes=200000,
            total_lines=5000,
            earliest_timestamp="2024-01-01 08:00:00",
            latest_timestamp="2024-01-01 17:00:00",
            total_matches=10,
            unique_patterns=2,
            patterns=[
                RecurringPattern(
                    normalized_text="error test",
                    count=5,
                    first_line=1,
                    first_timestamp=None,
                    raw_example="error test example",
                )
            ],
            critical_occurrences=[
                MatchInfo(
                    line_number=1,
                    timestamp=None,
                    content="error test",
                    normalized="error test",
                )
            ],
            context_blocks=[block],
            timeline=[],
        )

        output = generate_structured_output(result)

        # Extraer la sección de bloques de contexto
        blocks_start = output.find("## Bloques de Contexto")
        timeline_start = output.find("## Línea de Tiempo Condensada")
        assert blocks_start != -1, "Sección 'Bloques de Contexto' no encontrada"
        assert timeline_start != -1, "Sección 'Línea de Tiempo Condensada' no encontrada"

        blocks_section = output[blocks_start:timeline_start]

        # Verificar cada línea del bloque
        for line_num, content in block.lines:
            # Buscar la línea formateada en el output
            if line_num in block.match_lines:
                # Debe tener prefijo ">>"
                expected_prefix = f">> {line_num:>6}: {content}"
                assert expected_prefix in blocks_section, (
                    f"Línea {line_num} está en match_lines pero no tiene "
                    f"prefijo '>>'. Buscando: '{expected_prefix}' en sección de bloques."
                )
            else:
                # Debe tener prefijo "   "
                expected_prefix = f"   {line_num:>6}: {content}"
                assert expected_prefix in blocks_section, (
                    f"Línea {line_num} NO está en match_lines pero no tiene "
                    f"prefijo '   '. Buscando: '{expected_prefix}' en sección de bloques."
                )

    @given(block=context_block(min_lines=5, max_lines=15))
    @settings(max_examples=100, deadline=None)
    def test_non_match_lines_never_have_arrow_prefix(self, block: ContextBlock):
        """
        Las líneas que NO están en match_lines nunca aparecen con prefijo ">>".

        **Validates: Requirements 9.5**
        """
        result = StructuralAnalysisResult(
            source_name="test.log",
            file_size_bytes=200000,
            total_lines=5000,
            earliest_timestamp="2024-01-01 08:00:00",
            latest_timestamp="2024-01-01 17:00:00",
            total_matches=10,
            unique_patterns=2,
            patterns=[
                RecurringPattern(
                    normalized_text="error test",
                    count=5,
                    first_line=1,
                    first_timestamp=None,
                    raw_example="error test example",
                )
            ],
            critical_occurrences=[
                MatchInfo(
                    line_number=1,
                    timestamp=None,
                    content="error test",
                    normalized="error test",
                )
            ],
            context_blocks=[block],
            timeline=[],
        )

        output = generate_structured_output(result)

        # Extraer sección de bloques
        blocks_start = output.find("## Bloques de Contexto")
        timeline_start = output.find("## Línea de Tiempo Condensada")
        blocks_section = output[blocks_start:timeline_start]

        # Verificar que ninguna línea no-match tiene ">>"
        for line_num, content in block.lines:
            if line_num not in block.match_lines:
                arrow_format = f">> {line_num:>6}: {content}"
                assert arrow_format not in blocks_section, (
                    f"Línea {line_num} NO está en match_lines pero aparece "
                    f"con prefijo '>>'. Esto viola la propiedad de marcado."
                )


# === PROPERTY 17: DIRECT PATH PAYLOAD ASSEMBLY ===


class TestDirectPathPayloadAssembly:
    """
    Property 17: Direct path payload assembly.

    assemble_direct_payload siempre produce output conteniendo el prompt,
    un separador "---", sección de metadata, y el contenido crudo del log
    en ese orden.

    **Validates: Requirements 4.1, 4.2, 4.3**
    """

    @given(
        log_content=st.text(min_size=10, max_size=500, alphabet=st.characters(
            whitelist_categories=("L", "N", "P", "Z"),
            blacklist_characters="\x00",
        )),
        prompt=st.text(min_size=10, max_size=200, alphabet=st.characters(
            whitelist_categories=("L", "N", "P", "Z"),
            blacklist_characters="\x00",
        )),
        workstation_id=st.uuids().map(str),
        filename=st.from_regex(r"[A-Za-z0-9_\-]{3,20}\.(log|txt)", fullmatch=True),
        file_size=st.integers(min_value=100, max_value=100000),
    )
    @settings(max_examples=100, deadline=None)
    def test_payload_contains_prompt_separator_metadata_and_content_in_order(
        self,
        log_content: str,
        prompt: str,
        workstation_id: str,
        filename: str,
        file_size: int,
    ):
        """
        El payload ensamblado contiene: prompt, separador "---", sección
        Metadata, y el contenido del log, en ese orden estricto.

        **Validates: Requirements 4.1, 4.2, 4.3**
        """
        payload = assemble_direct_payload(
            log_content=log_content,
            prompt=prompt,
            workstation_id=workstation_id,
            filename=filename,
            file_size=file_size,
        )

        # Verificar que el prompt aparece al inicio
        assert payload.startswith(prompt), (
            f"El payload no comienza con el prompt. "
            f"Inicio del payload: '{payload[:100]}'"
        )

        # Verificar que el separador "---" aparece después del prompt
        prompt_end = len(prompt)
        separator_pos = payload.find("---", prompt_end)
        assert separator_pos != -1, (
            "El separador '---' no se encontró después del prompt."
        )

        # Verificar que la sección Metadata aparece después del separador
        metadata_pos = payload.find("## Metadata", separator_pos)
        assert metadata_pos != -1, (
            "La sección '## Metadata' no se encontró después del separador."
        )

        # Verificar que el contenido del log aparece después de la metadata
        log_content_section_pos = payload.find("## Log Content", metadata_pos)
        assert log_content_section_pos != -1, (
            "La sección '## Log Content' no se encontró después de Metadata."
        )

        # Verificar que el contenido crudo del log está presente después de Log Content
        log_pos = payload.find(log_content, log_content_section_pos)
        assert log_pos != -1, (
            "El contenido crudo del log no se encontró después de '## Log Content'."
        )

    @given(
        log_content=st.text(min_size=10, max_size=300, alphabet=st.characters(
            whitelist_categories=("L", "N", "P", "Z"),
            blacklist_characters="\x00",
        )),
        prompt=st.text(min_size=10, max_size=100, alphabet=st.characters(
            whitelist_categories=("L", "N", "P", "Z"),
            blacklist_characters="\x00",
        )),
        workstation_id=st.uuids().map(str),
        filename=st.from_regex(r"[A-Za-z0-9_\-]{3,20}\.(log|txt)", fullmatch=True),
        file_size=st.integers(min_value=100, max_value=100000),
    )
    @settings(max_examples=100, deadline=None)
    def test_payload_metadata_contains_workstation_and_filename(
        self,
        log_content: str,
        prompt: str,
        workstation_id: str,
        filename: str,
        file_size: int,
    ):
        """
        La sección Metadata del payload incluye workstation_id, filename
        y file_size como parte del contexto enviado al LLM.

        **Validates: Requirements 4.3**
        """
        payload = assemble_direct_payload(
            log_content=log_content,
            prompt=prompt,
            workstation_id=workstation_id,
            filename=filename,
            file_size=file_size,
        )

        assert workstation_id in payload, (
            f"workstation_id '{workstation_id}' no encontrado en el payload."
        )
        assert filename in payload, (
            f"filename '{filename}' no encontrado en el payload."
        )
        assert str(file_size) in payload, (
            f"file_size '{file_size}' no encontrado en el payload."
        )

    @given(
        log_content=st.text(min_size=10, max_size=300, alphabet=st.characters(
            whitelist_categories=("L", "N", "P", "Z"),
            blacklist_characters="\x00",
        )),
        prompt=st.text(min_size=10, max_size=100, alphabet=st.characters(
            whitelist_categories=("L", "N", "P", "Z"),
            blacklist_characters="\x00",
        )),
        workstation_id=st.uuids().map(str),
        filename=st.from_regex(r"[A-Za-z0-9_\-]{3,20}\.(log|txt)", fullmatch=True),
        file_size=st.integers(min_value=100, max_value=100000),
    )
    @settings(max_examples=100, deadline=None)
    def test_payload_order_is_prompt_then_separator_then_metadata_then_log(
        self,
        log_content: str,
        prompt: str,
        workstation_id: str,
        filename: str,
        file_size: int,
    ):
        """
        El orden estricto de componentes es:
        pos(prompt) < pos(---) < pos(Metadata) < pos(log_content).

        **Validates: Requirements 4.1, 4.2**
        """
        payload = assemble_direct_payload(
            log_content=log_content,
            prompt=prompt,
            workstation_id=workstation_id,
            filename=filename,
            file_size=file_size,
        )

        pos_prompt = payload.find(prompt)
        pos_separator = payload.find("---", pos_prompt + len(prompt))
        pos_metadata = payload.find("## Metadata", pos_separator)
        pos_log_content = payload.find(log_content, pos_metadata)

        assert pos_prompt == 0, (
            f"El prompt no está al inicio (pos={pos_prompt})."
        )
        assert pos_separator > pos_prompt, (
            f"El separador (pos={pos_separator}) no está después del prompt (pos={pos_prompt})."
        )
        assert pos_metadata > pos_separator, (
            f"Metadata (pos={pos_metadata}) no está después del separador (pos={pos_separator})."
        )
        assert pos_log_content > pos_metadata, (
            f"Log content (pos={pos_log_content}) no está después de Metadata (pos={pos_metadata})."
        )
