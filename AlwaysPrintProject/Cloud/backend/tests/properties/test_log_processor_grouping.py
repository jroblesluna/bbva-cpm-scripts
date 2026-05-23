"""
Property tests para agrupación de patrones y línea de tiempo del log_processor.

Verifica las propiedades fundamentales de group_patterns, identify_first_occurrences
y build_condensed_timeline:
- Property 7: Consistencia de conteos en agrupación de patrones
- Property 10: Primera ocurrencia tiene el menor line_number
- Property 11: Ordenación de ocurrencias críticas
- Property 12: Granularidad de timeline según span temporal
- Property 13: Consistencia de conteos en timeline

**Validates: Requirements 7.7, 8.1, 8.3, 8.4, 8.6, 8.7, 8.8**
"""

from datetime import datetime, timedelta

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.services.log_processor import (
    MatchInfo,
    build_condensed_timeline,
    group_patterns,
    identify_first_occurrences,
)


# === ESTRATEGIAS DE GENERACIÓN ===


@st.composite
def match_info_list(
    draw,
    min_size: int = 2,
    max_size: int = 30,
    min_patterns: int = 1,
    max_patterns: int = 5,
    with_timestamps: bool = False,
    without_timestamps: bool = False,
):
    """
    Genera una lista de MatchInfo con textos normalizados controlados.

    Crea entre min_patterns y max_patterns textos normalizados distintos,
    y distribuye los matches entre ellos. Garantiza al menos un patrón
    con count >= 2 para que group_patterns produzca resultados.

    Parámetros:
        with_timestamps: Si True, todos los matches tienen timestamp
        without_timestamps: Si True, ningún match tiene timestamp
    """
    num_patterns = draw(st.integers(min_value=min_patterns, max_value=max_patterns))
    pattern_names = [f"error tipo {i} en [IP]" for i in range(num_patterns)]

    # Generar al menos 2 matches para el primer patrón (garantizar recurrencia)
    total = draw(st.integers(min_value=max(min_size, num_patterns + 1), max_value=max_size))

    matches = []
    line_numbers_used: set[int] = set()

    # Base timestamp para generar timestamps secuenciales
    base_dt = datetime(2024, 1, 15, 10, 0, 0)

    for i in range(total):
        # Asignar patrón: primeros matches van al primer patrón para garantizar >= 2
        if i < 2:
            pattern_idx = 0
        else:
            pattern_idx = draw(st.integers(min_value=0, max_value=num_patterns - 1))

        # Generar line_number único
        line_num = draw(st.integers(min_value=1, max_value=5000).filter(
            lambda x: x not in line_numbers_used
        ))
        line_numbers_used.add(line_num)

        # Generar timestamp según configuración
        if without_timestamps:
            timestamp = None
        elif with_timestamps:
            offset_seconds = draw(st.integers(min_value=0, max_value=3600))
            dt = base_dt + timedelta(seconds=offset_seconds)
            timestamp = dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            # Mezcla: algunos con timestamp, algunos sin
            has_ts = draw(st.booleans())
            if has_ts:
                offset_seconds = draw(st.integers(min_value=0, max_value=7200))
                dt = base_dt + timedelta(seconds=offset_seconds)
                timestamp = dt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                timestamp = None

        normalized = pattern_names[pattern_idx]
        content = f"Línea {line_num}: {normalized} detalle {i}"

        matches.append(MatchInfo(
            line_number=line_num,
            timestamp=timestamp,
            content=content,
            normalized=normalized,
        ))

    return matches


@st.composite
def timed_match_list_short_span(draw, min_size: int = 2, max_size: int = 20):
    """
    Genera matches con timestamps dentro de un span ≤ 1 hora.

    Todos los matches tienen timestamps parseables dentro de una ventana
    de máximo 60 minutos.
    """
    count = draw(st.integers(min_value=min_size, max_value=max_size))
    base_dt = datetime(2024, 3, 10, 14, 0, 0)

    matches = []
    line_numbers_used: set[int] = set()

    for i in range(count):
        # Offset máximo de 3600 segundos (1 hora)
        offset = draw(st.integers(min_value=0, max_value=3600))
        dt = base_dt + timedelta(seconds=offset)
        timestamp = dt.strftime("%Y-%m-%d %H:%M:%S")

        line_num = draw(st.integers(min_value=1, max_value=5000).filter(
            lambda x: x not in line_numbers_used
        ))
        line_numbers_used.add(line_num)

        normalized = f"evento tipo {i % 3}"
        matches.append(MatchInfo(
            line_number=line_num,
            timestamp=timestamp,
            content=f"contenido {i}",
            normalized=normalized,
        ))

    return matches


@st.composite
def timed_match_list_long_span(draw, min_size: int = 2, max_size: int = 20):
    """
    Genera matches con timestamps con span > 1 hora.

    Garantiza que la diferencia entre el primer y último timestamp
    sea estrictamente mayor a 1 hora.
    """
    count = draw(st.integers(min_value=min_size, max_value=max_size))
    base_dt = datetime(2024, 3, 10, 8, 0, 0)

    # Garantizar span > 1 hora: primer match en base, último al menos 3601s después
    max_offset = draw(st.integers(min_value=3601, max_value=28800))  # 1h+1s a 8h

    matches = []
    line_numbers_used: set[int] = set()

    for i in range(count):
        if i == 0:
            offset = 0  # Primer match en base
        elif i == count - 1:
            offset = max_offset  # Último match garantiza span > 1h
        else:
            offset = draw(st.integers(min_value=0, max_value=max_offset))

        dt = base_dt + timedelta(seconds=offset)
        timestamp = dt.strftime("%Y-%m-%d %H:%M:%S")

        line_num = draw(st.integers(min_value=1, max_value=5000).filter(
            lambda x: x not in line_numbers_used
        ))
        line_numbers_used.add(line_num)

        normalized = f"evento tipo {i % 4}"
        matches.append(MatchInfo(
            line_number=line_num,
            timestamp=timestamp,
            content=f"contenido {i}",
            normalized=normalized,
        ))

    return matches


# === PROPERTY 7: PATTERN GROUPING COUNT CONSISTENCY ===


class TestPatternGroupingCountConsistency:
    """
    Property 7: Pattern grouping count consistency.

    La suma de todos los conteos de patrones es igual al número de matches
    que pertenecen a patrones recurrentes (count >= 2).

    **Validates: Requirements 7.7**
    """

    @given(matches=match_info_list(min_size=4, max_size=30))
    @settings(max_examples=100, deadline=None)
    def test_sum_of_counts_equals_recurring_matches(
        self, matches: list[MatchInfo]
    ):
        """
        La suma de pattern.count para todos los patrones retornados es igual
        al número total de matches cuyo texto normalizado aparece 2+ veces.

        **Validates: Requirements 7.7**
        """
        patterns = group_patterns(matches)

        # Calcular suma de conteos de patrones
        sum_pattern_counts = sum(p.count for p in patterns)

        # Calcular manualmente cuántos matches pertenecen a grupos con count >= 2
        from collections import Counter
        normalized_counts = Counter(m.normalized for m in matches)
        expected_recurring = sum(
            count for count in normalized_counts.values() if count >= 2
        )

        assert sum_pattern_counts == expected_recurring, (
            f"Inconsistencia de conteos: suma de pattern.count={sum_pattern_counts}, "
            f"matches en patrones recurrentes={expected_recurring}. "
            f"Distribución: {dict(normalized_counts)}"
        )

    @given(matches=match_info_list(min_size=4, max_size=30))
    @settings(max_examples=100, deadline=None)
    def test_each_pattern_count_matches_group_size(
        self, matches: list[MatchInfo]
    ):
        """
        Cada pattern.count es igual al número de matches cuyo normalized
        coincide con pattern.normalized_text.

        **Validates: Requirements 7.7**
        """
        patterns = group_patterns(matches)

        for pattern in patterns:
            actual_count = sum(
                1 for m in matches if m.normalized == pattern.normalized_text
            )
            assert pattern.count == actual_count, (
                f"Patrón '{pattern.normalized_text}': count={pattern.count}, "
                f"pero hay {actual_count} matches con ese texto normalizado."
            )

    @given(matches=match_info_list(min_size=4, max_size=30))
    @settings(max_examples=100, deadline=None)
    def test_all_patterns_have_count_at_least_2(
        self, matches: list[MatchInfo]
    ):
        """
        Todos los patrones retornados tienen count >= 2.

        **Validates: Requirements 7.7**
        """
        patterns = group_patterns(matches)

        for pattern in patterns:
            assert pattern.count >= 2, (
                f"Patrón '{pattern.normalized_text}' tiene count={pattern.count}, "
                f"pero solo se incluyen patrones con count >= 2."
            )


# === PROPERTY 10: FIRST OCCURRENCE HAS MINIMUM LINE NUMBER ===


class TestFirstOccurrenceMinimumLineNumber:
    """
    Property 10: First occurrence has minimum line number.

    Para cada patrón, la primera ocurrencia identificada tiene el menor
    line_number entre todos los matches con ese texto normalizado.

    **Validates: Requirements 8.1**
    """

    @given(matches=match_info_list(min_size=4, max_size=30, min_patterns=2))
    @settings(max_examples=100, deadline=None)
    def test_first_occurrence_has_min_line_number(
        self, matches: list[MatchInfo]
    ):
        """
        Para cada patrón recurrente, la primera ocurrencia retornada por
        identify_first_occurrences tiene line_number <= todos los demás
        matches con el mismo texto normalizado.

        **Validates: Requirements 8.1**
        """
        patterns = group_patterns(matches)
        assume(len(patterns) > 0)

        first_occurrences = identify_first_occurrences(patterns, matches)

        for first_occ in first_occurrences:
            # Encontrar todos los matches con el mismo normalized
            same_pattern_matches = [
                m for m in matches if m.normalized == first_occ.normalized
            ]

            min_line = min(m.line_number for m in same_pattern_matches)

            assert first_occ.line_number == min_line, (
                f"Para patrón '{first_occ.normalized}': primera ocurrencia tiene "
                f"line_number={first_occ.line_number}, pero el mínimo es {min_line}. "
                f"Líneas del grupo: {[m.line_number for m in same_pattern_matches]}"
            )

    @given(matches=match_info_list(min_size=4, max_size=30, min_patterns=2))
    @settings(max_examples=100, deadline=None)
    def test_one_first_occurrence_per_pattern(
        self, matches: list[MatchInfo]
    ):
        """
        identify_first_occurrences retorna exactamente una entrada por cada
        patrón recurrente.

        **Validates: Requirements 8.1**
        """
        patterns = group_patterns(matches)
        assume(len(patterns) > 0)

        first_occurrences = identify_first_occurrences(patterns, matches)

        assert len(first_occurrences) == len(patterns), (
            f"Se esperaban {len(patterns)} primeras ocurrencias, "
            f"pero se obtuvieron {len(first_occurrences)}."
        )


# === PROPERTY 11: CRITICAL OCCURRENCES SORTING ===


class TestCriticalOccurrencesSorting:
    """
    Property 11: Critical occurrences sorting.

    Si todas las primeras ocurrencias tienen timestamps, se ordenan por
    timestamp ascendente. Si no todas tienen timestamps, se ordenan por
    line_number ascendente.

    **Validates: Requirements 8.3, 8.4**
    """

    @given(matches=match_info_list(
        min_size=6, max_size=30, min_patterns=2, max_patterns=5,
        with_timestamps=True,
    ))
    @settings(max_examples=100, deadline=None)
    def test_sorted_by_timestamp_when_all_have_timestamps(
        self, matches: list[MatchInfo]
    ):
        """
        Cuando todas las primeras ocurrencias tienen timestamp, el resultado
        está ordenado por timestamp ascendente.

        **Validates: Requirements 8.3**
        """
        patterns = group_patterns(matches)
        assume(len(patterns) >= 2)

        first_occurrences = identify_first_occurrences(patterns, matches)
        assume(len(first_occurrences) >= 2)

        # Verificar que todos tienen timestamp
        all_have_ts = all(m.timestamp is not None for m in first_occurrences)
        assume(all_have_ts)

        # Verificar orden por timestamp ascendente
        for i in range(len(first_occurrences) - 1):
            ts_current = first_occurrences[i].timestamp
            ts_next = first_occurrences[i + 1].timestamp
            assert ts_current <= ts_next, (
                f"Ocurrencias no ordenadas por timestamp: "
                f"[{i}].timestamp='{ts_current}' > [{i+1}].timestamp='{ts_next}'"
            )

    @given(matches=match_info_list(
        min_size=6, max_size=30, min_patterns=2, max_patterns=5,
        without_timestamps=True,
    ))
    @settings(max_examples=100, deadline=None)
    def test_sorted_by_line_number_when_no_timestamps(
        self, matches: list[MatchInfo]
    ):
        """
        Cuando ninguna primera ocurrencia tiene timestamp, el resultado
        está ordenado por line_number ascendente.

        **Validates: Requirements 8.4**
        """
        patterns = group_patterns(matches)
        assume(len(patterns) >= 2)

        first_occurrences = identify_first_occurrences(patterns, matches)
        assume(len(first_occurrences) >= 2)

        # Verificar orden por line_number ascendente
        for i in range(len(first_occurrences) - 1):
            ln_current = first_occurrences[i].line_number
            ln_next = first_occurrences[i + 1].line_number
            assert ln_current <= ln_next, (
                f"Ocurrencias no ordenadas por line_number: "
                f"[{i}].line_number={ln_current} > [{i+1}].line_number={ln_next}"
            )

    @given(matches=match_info_list(
        min_size=6, max_size=30, min_patterns=2, max_patterns=5,
    ))
    @settings(max_examples=100, deadline=None)
    def test_sorted_by_line_number_when_mixed_timestamps(
        self, matches: list[MatchInfo]
    ):
        """
        Cuando hay mezcla de timestamps (algunos None), el resultado
        se ordena por line_number ascendente.

        **Validates: Requirements 8.3, 8.4**
        """
        patterns = group_patterns(matches)
        assume(len(patterns) >= 2)

        first_occurrences = identify_first_occurrences(patterns, matches)
        assume(len(first_occurrences) >= 2)

        # Solo verificar si hay mezcla (no todos tienen timestamp)
        has_some_ts = any(m.timestamp is not None for m in first_occurrences)
        has_some_none = any(m.timestamp is None for m in first_occurrences)
        assume(has_some_ts and has_some_none)

        # Cuando hay mezcla, se ordena por line_number
        for i in range(len(first_occurrences) - 1):
            ln_current = first_occurrences[i].line_number
            ln_next = first_occurrences[i + 1].line_number
            assert ln_current <= ln_next, (
                f"Con timestamps mixtos, debería ordenar por line_number: "
                f"[{i}].line_number={ln_current} > [{i+1}].line_number={ln_next}"
            )


# === PROPERTY 12: TIMELINE GRANULARITY MATCHES TIME SPAN ===


class TestTimelineGranularityMatchesTimeSpan:
    """
    Property 12: Timeline granularity matches time span.

    Si el span temporal es ≤ 1h, los time_groups usan formato de minuto
    ("YYYY-MM-DD HH:MM"). Si es > 1h, usan formato de hora ("YYYY-MM-DD HH:00").

    **Validates: Requirements 8.6, 8.7**
    """

    @given(matches=timed_match_list_short_span(min_size=2, max_size=20))
    @settings(max_examples=100, deadline=None)
    def test_minute_granularity_when_span_lte_1h(
        self, matches: list[MatchInfo]
    ):
        """
        Cuando el span temporal es ≤ 1 hora, todos los time_groups tienen
        formato de minuto "YYYY-MM-DD HH:MM" (16 caracteres).

        **Validates: Requirements 8.6**
        """
        timeline = build_condensed_timeline(matches)
        assume(len(timeline) > 0)

        for entry in timeline:
            # Formato minuto: "YYYY-MM-DD HH:MM" = 16 chars
            assert len(entry.time_group) == 16, (
                f"Con span ≤ 1h, time_group debería tener formato minuto "
                f"(16 chars), pero tiene {len(entry.time_group)} chars: "
                f"'{entry.time_group}'"
            )
            # Verificar que NO termina en ":00" (formato hora)
            assert not entry.time_group.endswith(":00") or \
                entry.time_group[-5:-3] != entry.time_group[-2:], (
                f"Formato inesperado: '{entry.time_group}'"
            )

    @given(matches=timed_match_list_long_span(min_size=2, max_size=20))
    @settings(max_examples=100, deadline=None)
    def test_hour_granularity_when_span_gt_1h(
        self, matches: list[MatchInfo]
    ):
        """
        Cuando el span temporal es > 1 hora, todos los time_groups tienen
        formato de hora "YYYY-MM-DD HH:00" (16 chars, terminan en ":00").

        **Validates: Requirements 8.7**
        """
        timeline = build_condensed_timeline(matches)
        assume(len(timeline) > 0)

        for entry in timeline:
            # Formato hora: "YYYY-MM-DD HH:00" = 16 chars, termina en :00
            assert len(entry.time_group) == 16, (
                f"Con span > 1h, time_group debería tener 16 chars, "
                f"pero tiene {len(entry.time_group)}: '{entry.time_group}'"
            )
            assert entry.time_group.endswith(":00"), (
                f"Con span > 1h, time_group debería terminar en ':00', "
                f"pero es '{entry.time_group}'"
            )


# === PROPERTY 13: TIMELINE COUNT CONSISTENCY ===


class TestTimelineCountConsistency:
    """
    Property 13: Timeline count consistency.

    La suma de todos los total_count de la timeline es igual al número
    de matches con timestamps parseables. Además, para cada entry,
    total_count == sum(event_types.values()).

    **Validates: Requirements 8.8**
    """

    @given(matches=match_info_list(
        min_size=4, max_size=30, with_timestamps=True,
    ))
    @settings(max_examples=100, deadline=None)
    def test_total_counts_sum_equals_timed_matches(
        self, matches: list[MatchInfo]
    ):
        """
        La suma de total_count de todas las entries de la timeline es igual
        al número de matches con timestamps parseables.

        **Validates: Requirements 8.8**
        """
        timeline = build_condensed_timeline(matches)

        # Contar matches con timestamps parseables
        timed_count = sum(1 for m in matches if m.timestamp is not None)

        # Suma de total_count en timeline
        timeline_total = sum(entry.total_count for entry in timeline)

        assert timeline_total == timed_count, (
            f"Inconsistencia: suma de total_count={timeline_total}, "
            f"matches con timestamp={timed_count}."
        )

    @given(matches=match_info_list(
        min_size=4, max_size=30, with_timestamps=True,
    ))
    @settings(max_examples=100, deadline=None)
    def test_entry_total_count_equals_event_types_sum(
        self, matches: list[MatchInfo]
    ):
        """
        Para cada entry en la timeline, total_count es igual a la suma
        de todos los valores en event_types.

        **Validates: Requirements 8.8**
        """
        timeline = build_condensed_timeline(matches)

        for entry in timeline:
            event_types_sum = sum(entry.event_types.values())
            assert entry.total_count == event_types_sum, (
                f"Entry '{entry.time_group}': total_count={entry.total_count}, "
                f"pero sum(event_types)={event_types_sum}. "
                f"event_types={entry.event_types}"
            )

    @given(matches=match_info_list(min_size=4, max_size=30))
    @settings(max_examples=100, deadline=None)
    def test_matches_without_timestamp_excluded_from_timeline(
        self, matches: list[MatchInfo]
    ):
        """
        Los matches sin timestamp no se cuentan en la timeline.
        La suma de total_count solo refleja matches con timestamp parseable.

        **Validates: Requirements 8.8**
        """
        timeline = build_condensed_timeline(matches)

        # Contar solo matches con timestamp válido
        timed_count = sum(1 for m in matches if m.timestamp is not None)

        timeline_total = sum(entry.total_count for entry in timeline)

        assert timeline_total == timed_count, (
            f"Timeline incluye matches sin timestamp: "
            f"timeline_total={timeline_total}, timed_matches={timed_count}, "
            f"total_matches={len(matches)}"
        )
