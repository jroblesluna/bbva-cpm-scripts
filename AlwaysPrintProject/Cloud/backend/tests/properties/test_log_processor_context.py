"""
Property tests para ventanas de contexto del log_processor.

Verifica las propiedades fundamentales de merge_windows y select_blocks:
- Property 8: Merge de ventanas de contexto no produce solapamientos
- Property 9: Selección de bloques respeta límite y prioriza primeras ocurrencias

**Validates: Requirements 6.4, 6.5, 6.6**
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.log_processor import (
    ContextBlock,
    RecurringPattern,
    merge_windows,
    select_blocks,
)


# === ESTRATEGIAS DE GENERACIÓN ===


@st.composite
def window_list(draw, min_size: int = 1, max_size: int = 15):
    """
    Genera una lista de ventanas (start, end, match_lines) ordenadas por start.

    Cada ventana tiene un start entre 1 y 2000, un span entre 0 y 50,
    y entre 1 y 2 match_lines dentro del rango.
    """
    count = draw(st.integers(min_value=min_size, max_value=max_size))
    windows = []
    for _ in range(count):
        start = draw(st.integers(min_value=1, max_value=2000))
        span = draw(st.integers(min_value=0, max_value=50))
        end = start + span
        # Una match_line dentro del rango
        ml = draw(st.integers(min_value=start, max_value=end))
        windows.append((start, end, {ml}))
    windows.sort(key=lambda w: w[0])
    return windows


@st.composite
def block_list(draw, min_count: int = 2, max_count: int = 20):
    """
    Genera una lista de ContextBlocks no solapantes, ordenados por start_line.

    Cada bloque tiene un gap mínimo de 2 respecto al anterior para
    garantizar que no se solapan ni son adyacentes.
    """
    count = draw(st.integers(min_value=min_count, max_value=max_count))
    blocks = []
    pos = 1

    for _ in range(count):
        pos += draw(st.integers(min_value=2, max_value=10))
        span = draw(st.integers(min_value=1, max_value=20))
        start = pos
        end = pos + span
        ml = draw(st.integers(min_value=start, max_value=end))

        blocks.append(ContextBlock(
            start_line=start,
            end_line=end,
            lines=[],
            match_lines={ml},
        ))
        pos = end

    return blocks


# === PROPERTY 8: CONTEXT WINDOW MERGE PRODUCES NO OVERLAPS ===


class TestContextWindowMergeNoOverlaps:
    """
    Property 8: Context window merge produces no overlaps.

    Después de fusionar, ningún par de bloques consecutivos debe tener
    rangos de líneas solapantes. Para cualquier par de bloques consecutivos,
    block[i].end < block[i+1].start (separación estricta, no adyacentes).

    **Validates: Requirements 6.4**
    """

    @given(windows=window_list(min_size=1, max_size=15))
    @settings(max_examples=100, deadline=None)
    def test_merged_blocks_have_no_overlapping_ranges(
        self, windows: list[tuple[int, int, set[int]]]
    ):
        """
        Después de merge_windows, para cualquier par de bloques consecutivos
        (i, i+1), se cumple que block[i].end_line < block[i+1].start_line.

        **Validates: Requirements 6.4**
        """
        merged = merge_windows(windows)

        # Propiedad: bloques consecutivos no se solapan
        for i in range(len(merged) - 1):
            current_end = merged[i][1]
            next_start = merged[i + 1][0]
            assert current_end < next_start, (
                f"Solapamiento detectado entre bloques consecutivos: "
                f"bloque[{i}] end={current_end}, bloque[{i+1}] start={next_start}. "
                f"Se requiere end < start para no solapar. "
                f"Ventanas originales: {windows}"
            )

    @given(windows=window_list(min_size=2, max_size=15))
    @settings(max_examples=100, deadline=None)
    def test_merged_blocks_are_sorted_by_start(
        self, windows: list[tuple[int, int, set[int]]]
    ):
        """
        Los bloques fusionados están ordenados por start de forma ascendente.

        **Validates: Requirements 6.4**
        """
        merged = merge_windows(windows)

        for i in range(len(merged) - 1):
            assert merged[i][0] < merged[i + 1][0], (
                f"Bloques fusionados no están ordenados: "
                f"bloque[{i}].start={merged[i][0]} >= bloque[{i+1}].start={merged[i+1][0]}"
            )

    @given(windows=window_list(min_size=1, max_size=15))
    @settings(max_examples=100, deadline=None)
    def test_merged_preserves_all_match_lines(
        self, windows: list[tuple[int, int, set[int]]]
    ):
        """
        La fusión preserva todas las match_lines originales sin perder ninguna.

        **Validates: Requirements 6.4**
        """
        all_original_matches: set[int] = set()
        for _, _, match_lines in windows:
            all_original_matches.update(match_lines)

        merged = merge_windows(windows)

        all_merged_matches: set[int] = set()
        for _, _, match_lines in merged:
            all_merged_matches.update(match_lines)

        assert all_original_matches == all_merged_matches, (
            f"La fusión perdió o añadió match_lines. "
            f"Originales: {all_original_matches}, "
            f"Fusionadas: {all_merged_matches}"
        )

    @given(windows=window_list(min_size=1, max_size=15))
    @settings(max_examples=100, deadline=None)
    def test_merged_count_is_less_or_equal_to_original(
        self, windows: list[tuple[int, int, set[int]]]
    ):
        """
        La cantidad de bloques fusionados es menor o igual a la cantidad original.

        **Validates: Requirements 6.4**
        """
        merged = merge_windows(windows)

        assert len(merged) <= len(windows), (
            f"La fusión produjo más bloques ({len(merged)}) que los originales "
            f"({len(windows)}). Esto no debería ser posible."
        )


# === PROPERTY 9: BLOCK SELECTION RESPECTS LIMIT AND PRIORITIZES FIRST OCCURRENCES ===


class TestBlockSelectionRespectsLimitAndPriority:
    """
    Property 9: Block selection respects limit and prioritizes first occurrences.

    select_blocks nunca retorna más de max_blocks. Los bloques que contienen
    la primera línea (first_line) de algún patrón siempre se incluyen
    (si max_blocks lo permite).

    **Validates: Requirements 6.5, 6.6**
    """

    @given(
        blocks=block_list(min_count=2, max_count=20),
        max_blocks=st.integers(min_value=1, max_value=30),
    )
    @settings(max_examples=100, deadline=None)
    def test_never_exceeds_max_blocks(
        self, blocks: list[ContextBlock], max_blocks: int
    ):
        """
        select_blocks nunca retorna más bloques que max_blocks,
        independientemente de la cantidad de bloques de entrada.

        **Validates: Requirements 6.5**
        """
        result, omitted = select_blocks(blocks, [], max_blocks=max_blocks)

        assert len(result) <= max_blocks, (
            f"select_blocks retornó {len(result)} bloques, excediendo "
            f"max_blocks={max_blocks}. Entrada: {len(blocks)} bloques."
        )

    @given(
        blocks=block_list(min_count=2, max_count=20),
        max_blocks=st.integers(min_value=1, max_value=30),
    )
    @settings(max_examples=100, deadline=None)
    def test_selected_plus_omitted_equals_total(
        self, blocks: list[ContextBlock], max_blocks: int
    ):
        """
        La suma de bloques seleccionados y omitidos es igual al total de entrada.

        **Validates: Requirements 6.5**
        """
        result, omitted = select_blocks(blocks, [], max_blocks=max_blocks)

        assert len(result) + omitted == len(blocks), (
            f"Inconsistencia: seleccionados ({len(result)}) + omitidos ({omitted}) "
            f"!= total ({len(blocks)})"
        )

    @given(
        blocks=block_list(min_count=5, max_count=15),
        data=st.data(),
    )
    @settings(max_examples=100, deadline=None)
    def test_priority_blocks_included_when_limit_allows(
        self, blocks: list[ContextBlock], data
    ):
        """
        Los bloques que contienen first_line de algún patrón se incluyen
        siempre que max_blocks sea suficiente para acomodarlos.

        **Validates: Requirements 6.6**
        """
        # Seleccionar 1 o 2 bloques como "prioritarios"
        num_priority = data.draw(
            st.integers(min_value=1, max_value=min(2, len(blocks)))
        )
        priority_indices = sorted(data.draw(
            st.lists(
                st.integers(min_value=0, max_value=len(blocks) - 1),
                min_size=num_priority,
                max_size=num_priority,
                unique=True,
            )
        ))

        # Crear patrones cuyo first_line coincide con match_lines de bloques prioritarios
        patterns = []
        priority_match_lines: set[int] = set()
        for idx in priority_indices:
            first_line = min(blocks[idx].match_lines)
            priority_match_lines.add(first_line)
            patterns.append(RecurringPattern(
                normalized_text=f"patrón {idx}",
                count=5,
                first_line=first_line,
                first_timestamp=None,
                raw_example=f"ejemplo patrón {idx}",
            ))

        # max_blocks debe ser al menos la cantidad de bloques prioritarios
        max_blocks = data.draw(
            st.integers(min_value=num_priority, max_value=len(blocks))
        )

        result, omitted = select_blocks(blocks, patterns, max_blocks=max_blocks)

        # Propiedad: todos los bloques prioritarios deben estar en el resultado
        result_match_lines: set[int] = set()
        for block in result:
            result_match_lines.update(block.match_lines)

        for first_line in priority_match_lines:
            assert first_line in result_match_lines, (
                f"El bloque con first_line={first_line} debería estar incluido "
                f"(max_blocks={max_blocks} >= num_priority={num_priority}). "
                f"Match lines en resultado: {result_match_lines}"
            )

    @given(
        blocks=block_list(min_count=3, max_count=15),
        max_blocks=st.integers(min_value=1, max_value=20),
    )
    @settings(max_examples=100, deadline=None)
    def test_result_is_sorted_by_start_line(
        self, blocks: list[ContextBlock], max_blocks: int
    ):
        """
        Los bloques seleccionados se retornan ordenados por start_line
        para mantener el orden cronológico.

        **Validates: Requirements 6.5**
        """
        result, _ = select_blocks(blocks, [], max_blocks=max_blocks)

        for i in range(len(result) - 1):
            assert result[i].start_line <= result[i + 1].start_line, (
                f"Bloques seleccionados no están ordenados: "
                f"result[{i}].start_line={result[i].start_line} > "
                f"result[{i+1}].start_line={result[i+1].start_line}"
            )

    @given(blocks=block_list(min_count=2, max_count=10))
    @settings(max_examples=100, deadline=None)
    def test_all_blocks_returned_when_under_limit(
        self, blocks: list[ContextBlock]
    ):
        """
        Cuando la cantidad de bloques es menor o igual a max_blocks,
        se retornan todos sin omitir ninguno.

        **Validates: Requirements 6.5**
        """
        max_blocks = len(blocks) + 5  # Límite mayor que la cantidad

        result, omitted = select_blocks(blocks, [], max_blocks=max_blocks)

        assert len(result) == len(blocks), (
            f"Con max_blocks={max_blocks} y {len(blocks)} bloques de entrada, "
            f"se deberían retornar todos. Retornados: {len(result)}"
        )
        assert omitted == 0, (
            f"No debería haber bloques omitidos cuando hay espacio suficiente. "
            f"Omitidos: {omitted}"
        )
