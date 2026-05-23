"""
Tests unitarios para funciones de agrupación y timeline del log_processor.

Valida: group_patterns, identify_first_occurrences, build_condensed_timeline.
Requirements: 7.7, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9
"""

import pytest

from app.services.log_processor import (
    MatchInfo,
    RecurringPattern,
    TimelineEntry,
    build_condensed_timeline,
    group_patterns,
    identify_first_occurrences,
)


# === Tests para group_patterns ===


class TestGroupPatterns:
    """Tests para la función group_patterns."""

    def test_agrupa_por_texto_normalizado(self) -> None:
        """Agrupa matches con el mismo texto normalizado."""
        matches = [
            MatchInfo(1, "2024-01-01 10:00:00", "Error en 192.168.1.1", "Error en [IP]"),
            MatchInfo(5, "2024-01-01 10:01:00", "Error en 10.0.0.1", "Error en [IP]"),
            MatchInfo(10, "2024-01-01 10:02:00", "Error en 172.16.0.1", "Error en [IP]"),
        ]
        patterns = group_patterns(matches)
        assert len(patterns) == 1
        assert patterns[0].normalized_text == "Error en [IP]"
        assert patterns[0].count == 3

    def test_solo_incluye_patrones_con_count_mayor_o_igual_2(self) -> None:
        """Solo clasifica como RecurringPattern si count >= 2."""
        matches = [
            MatchInfo(1, None, "Error A", "Error [IP]"),
            MatchInfo(2, None, "Error B", "Error [IP]"),
            MatchInfo(3, None, "Unico", "Unico"),
        ]
        patterns = group_patterns(matches)
        assert len(patterns) == 1
        assert patterns[0].normalized_text == "Error [IP]"

    def test_ordena_por_count_descendente(self) -> None:
        """Resultado ordenado por count descendente."""
        matches = [
            MatchInfo(1, None, "a", "patron_A"),
            MatchInfo(2, None, "a", "patron_A"),
            MatchInfo(3, None, "b", "patron_B"),
            MatchInfo(4, None, "b", "patron_B"),
            MatchInfo(5, None, "b", "patron_B"),
            MatchInfo(6, None, "b", "patron_B"),
        ]
        patterns = group_patterns(matches)
        assert len(patterns) == 2
        assert patterns[0].count == 4  # patron_B
        assert patterns[1].count == 2  # patron_A

    def test_first_line_es_menor_line_number(self) -> None:
        """first_line corresponde al menor line_number del grupo."""
        matches = [
            MatchInfo(10, "2024-01-01 10:05:00", "err", "err [NUMBER]"),
            MatchInfo(3, "2024-01-01 10:01:00", "err", "err [NUMBER]"),
            MatchInfo(7, "2024-01-01 10:03:00", "err", "err [NUMBER]"),
        ]
        patterns = group_patterns(matches)
        assert patterns[0].first_line == 3
        assert patterns[0].first_timestamp == "2024-01-01 10:01:00"

    def test_raw_example_truncado_a_500_chars(self) -> None:
        """raw_example se trunca a 500 caracteres."""
        long_content = "x" * 600
        matches = [
            MatchInfo(1, None, long_content, "norm"),
            MatchInfo(2, None, "short", "norm"),
        ]
        patterns = group_patterns(matches)
        assert len(patterns[0].raw_example) == 500

    def test_lista_vacia_retorna_vacia(self) -> None:
        """Lista vacía de matches retorna lista vacía de patrones."""
        assert group_patterns([]) == []

    def test_sin_patrones_recurrentes(self) -> None:
        """Si ningún patrón se repite, retorna lista vacía."""
        matches = [
            MatchInfo(1, None, "a", "unico_a"),
            MatchInfo(2, None, "b", "unico_b"),
            MatchInfo(3, None, "c", "unico_c"),
        ]
        assert group_patterns(matches) == []


# === Tests para identify_first_occurrences ===


class TestIdentifyFirstOccurrences:
    """Tests para la función identify_first_occurrences."""

    def test_encuentra_primera_ocurrencia_por_line_number(self) -> None:
        """Para cada patrón, retorna el match con menor line_number."""
        matches = [
            MatchInfo(5, "2024-01-01 10:01:00", "err B", "err [IP]"),
            MatchInfo(1, "2024-01-01 10:00:00", "err A", "err [IP]"),
            MatchInfo(3, "2024-01-01 10:00:30", "warn X", "warn [NUMBER]"),
            MatchInfo(8, "2024-01-01 10:02:00", "warn Y", "warn [NUMBER]"),
        ]
        patterns = group_patterns(matches)
        first_occ = identify_first_occurrences(patterns, matches)
        # Verificar que se encontraron las primeras ocurrencias correctas
        normalized_to_line = {m.normalized: m.line_number for m in first_occ}
        assert normalized_to_line["err [IP]"] == 1
        assert normalized_to_line["warn [NUMBER]"] == 3

    def test_ordena_por_timestamp_si_todos_tienen(self) -> None:
        """Si todos tienen timestamp, ordena por timestamp ascendente."""
        matches = [
            MatchInfo(5, "2024-01-01 10:05:00", "err", "err [IP]"),
            MatchInfo(1, "2024-01-01 10:00:00", "err", "err [IP]"),
            MatchInfo(3, "2024-01-01 10:02:00", "warn", "warn [NUMBER]"),
            MatchInfo(8, "2024-01-01 10:08:00", "warn", "warn [NUMBER]"),
        ]
        patterns = group_patterns(matches)
        first_occ = identify_first_occurrences(patterns, matches)
        assert first_occ[0].timestamp == "2024-01-01 10:00:00"
        assert first_occ[1].timestamp == "2024-01-01 10:02:00"

    def test_ordena_por_line_number_si_no_hay_timestamps(self) -> None:
        """Si no hay timestamps, ordena por line_number ascendente."""
        matches = [
            MatchInfo(10, None, "err A", "err [NUMBER]"),
            MatchInfo(2, None, "err B", "err [NUMBER]"),
            MatchInfo(5, None, "warn X", "warn [NUMBER]"),
            MatchInfo(8, None, "warn Y", "warn [NUMBER]"),
        ]
        patterns = group_patterns(matches)
        first_occ = identify_first_occurrences(patterns, matches)
        assert first_occ[0].line_number == 2
        assert first_occ[1].line_number == 5

    def test_ordena_por_line_number_si_alguno_sin_timestamp(self) -> None:
        """Si alguno no tiene timestamp, ordena por line_number."""
        matches = [
            MatchInfo(5, "2024-01-01 10:01:00", "err", "err [IP]"),
            MatchInfo(1, "2024-01-01 10:00:00", "err", "err [IP]"),
            MatchInfo(3, None, "warn", "warn [NUMBER]"),
            MatchInfo(8, None, "warn", "warn [NUMBER]"),
        ]
        patterns = group_patterns(matches)
        first_occ = identify_first_occurrences(patterns, matches)
        assert first_occ[0].line_number == 1
        assert first_occ[1].line_number == 3

    def test_listas_vacias(self) -> None:
        """Listas vacías retornan lista vacía."""
        assert identify_first_occurrences([], []) == []

    def test_patterns_vacio_matches_no_vacio(self) -> None:
        """Si patterns está vacío, retorna lista vacía."""
        matches = [MatchInfo(1, None, "err", "err")]
        assert identify_first_occurrences([], matches) == []


# === Tests para build_condensed_timeline ===


class TestBuildCondensedTimeline:
    """Tests para la función build_condensed_timeline."""

    def test_agrupa_por_minuto_si_span_menor_o_igual_1h(self) -> None:
        """Si span ≤ 1h, agrupa por minuto con formato YYYY-MM-DD HH:MM."""
        matches = [
            MatchInfo(1, "2024-01-01 10:00:00", "err", "err"),
            MatchInfo(2, "2024-01-01 10:00:30", "err", "err"),
            MatchInfo(3, "2024-01-01 10:01:00", "warn", "warn"),
            MatchInfo(4, "2024-01-01 10:30:00", "err", "err"),
        ]
        timeline = build_condensed_timeline(matches)
        assert len(timeline) == 3
        assert timeline[0].time_group == "2024-01-01 10:00"
        assert timeline[0].total_count == 2
        assert timeline[1].time_group == "2024-01-01 10:01"
        assert timeline[2].time_group == "2024-01-01 10:30"

    def test_agrupa_por_hora_si_span_mayor_1h(self) -> None:
        """Si span > 1h, agrupa por hora con formato YYYY-MM-DD HH:00."""
        matches = [
            MatchInfo(1, "2024-01-01 08:00:00", "err", "err"),
            MatchInfo(2, "2024-01-01 08:30:00", "err", "err"),
            MatchInfo(3, "2024-01-01 10:15:00", "warn", "warn"),
            MatchInfo(4, "2024-01-01 12:00:00", "err", "err"),
        ]
        timeline = build_condensed_timeline(matches)
        assert len(timeline) == 3
        assert timeline[0].time_group == "2024-01-01 08:00"
        assert timeline[0].total_count == 2
        assert timeline[1].time_group == "2024-01-01 10:00"
        assert timeline[1].total_count == 1
        assert timeline[2].time_group == "2024-01-01 12:00"
        assert timeline[2].total_count == 1

    def test_span_exactamente_1h_agrupa_por_minuto(self) -> None:
        """Span exactamente 1h (≤ 1h) agrupa por minuto."""
        matches = [
            MatchInfo(1, "2024-01-01 10:00:00", "err", "err"),
            MatchInfo(2, "2024-01-01 11:00:00", "err", "err"),
        ]
        timeline = build_condensed_timeline(matches)
        # Span = 1h exacto, ≤ 1h → por minuto
        assert timeline[0].time_group == "2024-01-01 10:00"
        assert timeline[1].time_group == "2024-01-01 11:00"

    def test_retorna_vacio_sin_timestamps(self) -> None:
        """Retorna lista vacía si no hay timestamps parseables."""
        matches = [
            MatchInfo(1, None, "err", "err"),
            MatchInfo(2, None, "warn", "warn"),
        ]
        assert build_condensed_timeline(matches) == []

    def test_retorna_vacio_lista_vacia(self) -> None:
        """Retorna lista vacía para lista vacía de matches."""
        assert build_condensed_timeline([]) == []

    def test_event_types_contiene_conteos_correctos(self) -> None:
        """Cada entry tiene event_types con conteos por tipo."""
        matches = [
            MatchInfo(1, "2024-01-01 10:00:00", "err A", "error [IP]"),
            MatchInfo(2, "2024-01-01 10:00:30", "err B", "error [IP]"),
            MatchInfo(3, "2024-01-01 10:00:45", "warn X", "warning [NUMBER]"),
        ]
        timeline = build_condensed_timeline(matches)
        assert len(timeline) == 1
        entry = timeline[0]
        assert entry.total_count == 3
        assert entry.event_types["error [IP]"] == 2
        assert entry.event_types["warning [NUMBER]"] == 1

    def test_ignora_matches_sin_timestamp(self) -> None:
        """Matches sin timestamp se ignoran en la timeline."""
        matches = [
            MatchInfo(1, "2024-01-01 10:00:00", "err", "err"),
            MatchInfo(2, None, "warn", "warn"),
            MatchInfo(3, "2024-01-01 10:01:00", "err", "err"),
        ]
        timeline = build_condensed_timeline(matches)
        # Solo 2 matches con timestamp
        total = sum(e.total_count for e in timeline)
        assert total == 2

    def test_orden_cronologico(self) -> None:
        """Entries ordenadas cronológicamente por time_group."""
        matches = [
            MatchInfo(1, "2024-01-01 10:05:00", "err", "err"),
            MatchInfo(2, "2024-01-01 10:00:00", "err", "err"),
            MatchInfo(3, "2024-01-01 10:02:00", "err", "err"),
        ]
        timeline = build_condensed_timeline(matches)
        groups = [e.time_group for e in timeline]
        assert groups == sorted(groups)

    def test_un_solo_match_con_timestamp(self) -> None:
        """Un solo match con timestamp genera una entrada."""
        matches = [
            MatchInfo(1, "2024-01-01 10:00:00", "err", "err"),
        ]
        timeline = build_condensed_timeline(matches)
        assert len(timeline) == 1
        assert timeline[0].time_group == "2024-01-01 10:00"
        assert timeline[0].total_count == 1
