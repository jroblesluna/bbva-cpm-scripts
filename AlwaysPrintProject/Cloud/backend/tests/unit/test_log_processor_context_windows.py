"""
Tests unitarios para funciones de ventanas de contexto del log_processor.

Valida extract_context_windows, merge_windows y select_blocks.
"""

import pytest

from app.services.log_processor import (
    ContextBlock,
    MatchInfo,
    RecurringPattern,
    extract_context_windows,
    merge_windows,
    select_blocks,
)


# === HELPERS ===


def make_match(line_number: int, content: str = "error occurred") -> MatchInfo:
    """Crea un MatchInfo de prueba."""
    return MatchInfo(
        line_number=line_number,
        timestamp=None,
        content=content,
        normalized=f"normalized: {content}",
    )


def make_lines(n: int) -> list[str]:
    """Genera N líneas de prueba (0-indexed internamente)."""
    return [f"Línea {i + 1} del log" for i in range(n)]


def make_pattern(
    normalized_text: str, count: int, first_line: int
) -> RecurringPattern:
    """Crea un RecurringPattern de prueba."""
    return RecurringPattern(
        normalized_text=normalized_text,
        count=count,
        first_line=first_line,
        first_timestamp=None,
        raw_example=f"ejemplo: {normalized_text}",
    )


# === TESTS DE merge_windows ===


class TestMergeWindows:
    """Tests para la función merge_windows."""

    def test_lista_vacia(self) -> None:
        """Lista vacía retorna lista vacía."""
        assert merge_windows([]) == []

    def test_ventana_unica(self) -> None:
        """Una sola ventana se retorna sin cambios."""
        windows = [(5, 25, {15})]
        result = merge_windows(windows)
        assert len(result) == 1
        assert result[0] == (5, 25, {15})

    def test_ventanas_no_solapantes(self) -> None:
        """Ventanas separadas no se fusionan."""
        windows = [(1, 10, {5}), (20, 30, {25})]
        result = merge_windows(windows)
        assert len(result) == 2
        assert result[0] == (1, 10, {5})
        assert result[1] == (20, 30, {25})

    def test_ventanas_solapantes(self) -> None:
        """Ventanas que se solapan se fusionan en una."""
        windows = [(1, 15, {5}), (10, 25, {20})]
        result = merge_windows(windows)
        assert len(result) == 1
        assert result[0][0] == 1
        assert result[0][1] == 25
        assert result[0][2] == {5, 20}

    def test_ventanas_adyacentes(self) -> None:
        """Ventanas adyacentes (separadas por 0 líneas) se fusionan."""
        # end de primera = 10, start de segunda = 11 → adyacentes
        windows = [(1, 10, {5}), (11, 20, {15})]
        result = merge_windows(windows)
        assert len(result) == 1
        assert result[0] == (1, 20, {5, 15})

    def test_ventanas_con_gap_de_1(self) -> None:
        """Ventanas con gap de 1 línea NO se fusionan."""
        # end de primera = 10, start de segunda = 12 → gap de 1
        windows = [(1, 10, {5}), (12, 20, {15})]
        result = merge_windows(windows)
        assert len(result) == 2

    def test_multiples_fusiones_en_cadena(self) -> None:
        """Múltiples ventanas solapantes se fusionan en cadena."""
        windows = [(1, 10, {5}), (8, 18, {12}), (15, 25, {20})]
        result = merge_windows(windows)
        assert len(result) == 1
        assert result[0][0] == 1
        assert result[0][1] == 25
        assert result[0][2] == {5, 12, 20}

    def test_preserva_match_lines_en_fusion(self) -> None:
        """La fusión preserva todas las match_lines de ambas ventanas."""
        windows = [(1, 20, {5, 10}), (15, 30, {20, 25})]
        result = merge_windows(windows)
        assert result[0][2] == {5, 10, 20, 25}

    def test_ventanas_desordenadas_se_ordenan(self) -> None:
        """Ventanas desordenadas se ordenan por start antes de fusionar."""
        windows = [(20, 30, {25}), (1, 10, {5})]
        result = merge_windows(windows)
        assert len(result) == 2
        assert result[0][0] == 1
        assert result[1][0] == 20


# === TESTS DE extract_context_windows ===


class TestExtractContextWindows:
    """Tests para la función extract_context_windows."""

    def test_lista_matches_vacia(self) -> None:
        """Sin matches retorna lista vacía."""
        lines = make_lines(100)
        result = extract_context_windows([], lines, context_size=20)
        assert result == []

    def test_lista_lines_vacia(self) -> None:
        """Sin líneas retorna lista vacía."""
        matches = [make_match(1)]
        result = extract_context_windows(matches, [], context_size=20)
        assert result == []

    def test_match_en_medio_del_archivo(self) -> None:
        """Match en medio extrae N líneas antes y después."""
        lines = make_lines(100)
        matches = [make_match(50)]
        result = extract_context_windows(matches, lines, context_size=5)

        assert len(result) == 1
        block = result[0]
        assert block.start_line == 45  # 50 - 5
        assert block.end_line == 55  # 50 + 5
        assert 50 in block.match_lines
        assert len(block.lines) == 11  # 45 a 55 inclusive

    def test_match_cerca_del_inicio(self) -> None:
        """Match cerca del inicio extrae hasta el límite del archivo."""
        lines = make_lines(100)
        matches = [make_match(3)]
        result = extract_context_windows(matches, lines, context_size=10)

        assert len(result) == 1
        block = result[0]
        assert block.start_line == 1  # No puede ir más atrás
        assert block.end_line == 13  # 3 + 10
        assert 3 in block.match_lines

    def test_match_cerca_del_final(self) -> None:
        """Match cerca del final extrae hasta el límite del archivo."""
        lines = make_lines(50)
        matches = [make_match(48)]
        result = extract_context_windows(matches, lines, context_size=10)

        assert len(result) == 1
        block = result[0]
        assert block.start_line == 38  # 48 - 10
        assert block.end_line == 50  # No puede ir más allá
        assert 48 in block.match_lines

    def test_matches_solapantes_se_fusionan(self) -> None:
        """Matches cercanos producen un solo bloque fusionado."""
        lines = make_lines(100)
        matches = [make_match(20), make_match(25)]
        result = extract_context_windows(matches, lines, context_size=5)

        # 20-5=15 a 20+5=25, 25-5=20 a 25+5=30 → solapan → fusión
        assert len(result) == 1
        block = result[0]
        assert block.start_line == 15
        assert block.end_line == 30
        assert 20 in block.match_lines
        assert 25 in block.match_lines

    def test_matches_separados_producen_bloques_distintos(self) -> None:
        """Matches lejanos producen bloques separados."""
        lines = make_lines(200)
        matches = [make_match(20), make_match(100)]
        result = extract_context_windows(matches, lines, context_size=5)

        # 20±5 = [15,25], 100±5 = [95,105] → no solapan
        assert len(result) == 2
        assert result[0].start_line == 15
        assert result[1].start_line == 95

    def test_context_size_cero(self) -> None:
        """Con context_size=0, solo se incluye la línea del match."""
        lines = make_lines(100)
        matches = [make_match(50)]
        result = extract_context_windows(matches, lines, context_size=0)

        assert len(result) == 1
        block = result[0]
        assert block.start_line == 50
        assert block.end_line == 50
        assert len(block.lines) == 1
        assert block.lines[0][0] == 50

    def test_contenido_de_lineas_correcto(self) -> None:
        """Las líneas extraídas tienen el contenido correcto."""
        lines = ["primera", "segunda", "tercera", "cuarta", "quinta"]
        matches = [make_match(3)]
        result = extract_context_windows(matches, lines, context_size=1)

        block = result[0]
        assert block.lines == [(2, "segunda"), (3, "tercera"), (4, "cuarta")]

    def test_match_en_primera_linea(self) -> None:
        """Match en la primera línea del archivo."""
        lines = make_lines(50)
        matches = [make_match(1)]
        result = extract_context_windows(matches, lines, context_size=5)

        block = result[0]
        assert block.start_line == 1
        assert block.end_line == 6  # 1 + 5
        assert 1 in block.match_lines

    def test_match_en_ultima_linea(self) -> None:
        """Match en la última línea del archivo."""
        lines = make_lines(50)
        matches = [make_match(50)]
        result = extract_context_windows(matches, lines, context_size=5)

        block = result[0]
        assert block.start_line == 45  # 50 - 5
        assert block.end_line == 50
        assert 50 in block.match_lines


# === TESTS DE select_blocks ===


class TestSelectBlocks:
    """Tests para la función select_blocks."""

    def test_lista_vacia(self) -> None:
        """Sin bloques retorna lista vacía y 0 omitidos."""
        result, omitted = select_blocks([], [], max_blocks=30)
        assert result == []
        assert omitted == 0

    def test_bloques_dentro_del_limite(self) -> None:
        """Si hay menos bloques que el límite, se retornan todos."""
        blocks = [
            ContextBlock(start_line=1, end_line=10, lines=[], match_lines={5}),
            ContextBlock(start_line=20, end_line=30, lines=[], match_lines={25}),
        ]
        result, omitted = select_blocks(blocks, [], max_blocks=30)
        assert len(result) == 2
        assert omitted == 0

    def test_bloques_exceden_limite(self) -> None:
        """Si hay más bloques que el límite, se recortan."""
        blocks = [
            ContextBlock(
                start_line=i * 50,
                end_line=i * 50 + 40,
                lines=[],
                match_lines={i * 50 + 20},
            )
            for i in range(10)
        ]
        result, omitted = select_blocks(blocks, [], max_blocks=5)
        assert len(result) == 5
        assert omitted == 5

    def test_prioriza_primera_ocurrencia_de_patron(self) -> None:
        """Bloques con primera ocurrencia de un patrón se priorizan."""
        # Patrón con primera ocurrencia en línea 150
        patterns = [make_pattern("error [NUMBER]", count=5, first_line=150)]

        # Bloque que contiene la primera ocurrencia (línea 150)
        priority_block = ContextBlock(
            start_line=140, end_line=160, lines=[], match_lines={150}
        )
        # Bloques normales (sin primera ocurrencia)
        other_blocks = [
            ContextBlock(
                start_line=i * 50,
                end_line=i * 50 + 40,
                lines=[],
                match_lines={i * 50 + 20},
            )
            for i in range(5)
        ]

        # El bloque prioritario está al final de la lista
        all_blocks = other_blocks + [priority_block]

        result, omitted = select_blocks(all_blocks, patterns, max_blocks=3)

        # El bloque con primera ocurrencia debe estar incluido
        assert any(150 in b.match_lines for b in result)
        assert len(result) == 3
        assert omitted == 3

    def test_resultado_ordenado_por_start_line(self) -> None:
        """Los bloques seleccionados se retornan ordenados por start_line."""
        patterns = [make_pattern("error", count=3, first_line=200)]

        blocks = [
            ContextBlock(start_line=100, end_line=120, lines=[], match_lines={110}),
            ContextBlock(start_line=190, end_line=210, lines=[], match_lines={200}),
            ContextBlock(start_line=50, end_line=70, lines=[], match_lines={60}),
            ContextBlock(start_line=300, end_line=320, lines=[], match_lines={310}),
        ]

        result, omitted = select_blocks(blocks, patterns, max_blocks=3)

        # Verificar orden ascendente por start_line
        for i in range(len(result) - 1):
            assert result[i].start_line < result[i + 1].start_line

    def test_omitidos_se_cuentan_correctamente(self) -> None:
        """El conteo de bloques omitidos es correcto."""
        blocks = [
            ContextBlock(
                start_line=i * 100,
                end_line=i * 100 + 40,
                lines=[],
                match_lines={i * 100 + 20},
            )
            for i in range(50)
        ]
        result, omitted = select_blocks(blocks, [], max_blocks=30)
        assert len(result) + omitted == 50
        assert omitted == 20

    def test_max_blocks_uno(self) -> None:
        """Con max_blocks=1, solo se retorna un bloque."""
        blocks = [
            ContextBlock(start_line=1, end_line=10, lines=[], match_lines={5}),
            ContextBlock(start_line=20, end_line=30, lines=[], match_lines={25}),
            ContextBlock(start_line=40, end_line=50, lines=[], match_lines={45}),
        ]
        result, omitted = select_blocks(blocks, [], max_blocks=1)
        assert len(result) == 1
        assert omitted == 2

    def test_multiples_patrones_priorizados(self) -> None:
        """Múltiples patrones con primeras ocurrencias se priorizan."""
        patterns = [
            make_pattern("error A", count=10, first_line=50),
            make_pattern("error B", count=5, first_line=150),
        ]

        blocks = [
            ContextBlock(start_line=1, end_line=20, lines=[], match_lines={10}),
            ContextBlock(start_line=40, end_line=60, lines=[], match_lines={50}),
            ContextBlock(start_line=80, end_line=100, lines=[], match_lines={90}),
            ContextBlock(start_line=140, end_line=160, lines=[], match_lines={150}),
            ContextBlock(start_line=200, end_line=220, lines=[], match_lines={210}),
        ]

        result, omitted = select_blocks(blocks, patterns, max_blocks=3)

        # Ambos bloques prioritarios (con líneas 50 y 150) deben estar
        match_lines_in_result = set()
        for b in result:
            match_lines_in_result.update(b.match_lines)

        assert 50 in match_lines_in_result
        assert 150 in match_lines_in_result
        assert len(result) == 3
        assert omitted == 2
