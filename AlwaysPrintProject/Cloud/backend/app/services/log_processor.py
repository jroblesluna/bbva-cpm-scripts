"""
Módulo de procesamiento estructural de logs.

Contiene funciones puras para análisis de logs de workstations AlwaysPrint.
Cada función es independiente y testable sin I/O externo.
"""

import io
import re
import zipfile
from dataclasses import dataclass, field
from typing import Optional


# === ESTRUCTURAS DE DATOS ===


@dataclass
class MatchInfo:
    """Información de una línea que coincide con un patrón de keyword."""

    line_number: int  # 1-based
    timestamp: Optional[str]  # "YYYY-MM-DD HH:MM:SS" o None
    content: str  # Contenido completo (max 10000 chars)
    normalized: str  # Versión normalizada para agrupación

    def __post_init__(self) -> None:
        """Trunca el contenido a 10000 caracteres si excede el límite."""
        if len(self.content) > 10000:
            self.content = self.content[:10000]


@dataclass
class ContextBlock:
    """Bloque de contexto alrededor de uno o más hallazgos."""

    start_line: int
    end_line: int
    lines: list[tuple[int, str]]  # [(line_number, content), ...]
    match_lines: set[int]  # Líneas que son matches (marcadas con >>)


@dataclass
class RecurringPattern:
    """Patrón normalizado con conteo de ocurrencias."""

    normalized_text: str
    count: int
    first_line: int
    first_timestamp: Optional[str]
    raw_example: str  # Truncado a 500 chars

    def __post_init__(self) -> None:
        """Trunca raw_example a 500 caracteres si excede el límite."""
        if len(self.raw_example) > 500:
            self.raw_example = self.raw_example[:500]


@dataclass
class TimelineEntry:
    """Entrada en la línea de tiempo condensada."""

    time_group: str  # "YYYY-MM-DD HH:MM" o "YYYY-MM-DD HH:00"
    total_count: int
    event_types: dict[str, int]


@dataclass
class StructuralAnalysisResult:
    """Resultado completo del análisis estructural."""

    source_name: str
    file_size_bytes: int
    total_lines: int
    earliest_timestamp: Optional[str]
    latest_timestamp: Optional[str]
    total_matches: int
    unique_patterns: int
    patterns: list[RecurringPattern]
    critical_occurrences: list[MatchInfo]
    context_blocks: list[ContextBlock]
    timeline: list[TimelineEntry]
    blocks_omitted: int = 0
    head_sample: list[str] = field(default_factory=list)
    tail_sample: list[str] = field(default_factory=list)
    no_matches: bool = False


# === EXTENSIONES VÁLIDAS PARA ARCHIVOS DE LOG ===

_VALID_EXTENSIONS = {".log", ".txt"}


# === FUNCIONES PRINCIPALES ===


def decompress_if_needed(
    payload: bytes, is_compressed: bool
) -> tuple[str, list[tuple[str, str]]]:
    """
    Descomprime payload ZIP si es necesario.

    Si is_compressed es False, decodifica el payload directamente como UTF-8.
    Si is_compressed es True, extrae archivos .log/.txt del ZIP, los concatena
    en orden alfabético con headers indicando el nombre de cada archivo fuente.

    Parámetros:
        payload: Bytes del payload recibido
        is_compressed: Flag indicando si viene comprimido

    Retorna:
        Tupla (contenido_concatenado, [(filename, content), ...])

    Raises:
        ValueError: Si ZIP corrupto o sin archivos .log/.txt válidos
    """
    if not is_compressed:
        # Decodificar directamente con tolerancia a caracteres malformados
        content = payload.decode("utf-8", errors="replace")
        return (content, [("raw", content)])

    # Intentar descomprimir como ZIP
    try:
        zip_buffer = io.BytesIO(payload)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            # Filtrar archivos con extensiones válidas
            valid_files: list[str] = []
            for name in zf.namelist():
                # Ignorar directorios
                if name.endswith("/"):
                    continue
                # Verificar extensión
                lower_name = name.lower()
                if any(lower_name.endswith(ext) for ext in _VALID_EXTENSIONS):
                    valid_files.append(name)

            if not valid_files:
                raise ValueError(
                    "El archivo ZIP no contiene archivos con extensión "
                    "válida (.log o .txt)"
                )

            # Ordenar alfabéticamente
            valid_files.sort()

            # Extraer y concatenar contenido
            file_contents: list[tuple[str, str]] = []
            for filename in valid_files:
                raw_bytes = zf.read(filename)
                file_content = raw_bytes.decode("utf-8", errors="replace")
                file_contents.append((filename, file_content))

            # Concatenar con headers si hay múltiples archivos
            if len(file_contents) == 1:
                concatenated = file_contents[0][1]
            else:
                parts: list[str] = []
                for filename, content in file_contents:
                    parts.append(f"=== Archivo: {filename} ===")
                    parts.append(content)
                concatenated = "\n".join(parts)

            return (concatenated, file_contents)

    except zipfile.BadZipFile as e:
        raise ValueError(
            f"El payload comprimido no es un archivo ZIP válido: {e}"
        ) from e


def route_by_size(content: str, threshold_bytes: int = 102400) -> str:
    """
    Determina la ruta de procesamiento según tamaño UTF-8 del contenido.

    Parámetros:
        content: Contenido del log como string
        threshold_bytes: Umbral en bytes (default 100KB = 102400 bytes)

    Retorna:
        "direct" si el tamaño en bytes es menor que threshold,
        "structural" si es igual o mayor que threshold
    """
    content_size = len(content.encode("utf-8"))
    if content_size < threshold_bytes:
        return "direct"
    return "structural"


# === KEYWORDS POR DEFECTO PARA DETECCIÓN ===

DEFAULT_KEYWORDS: list[str] = [
    "error", "exception", "failed", "failure", "timeout",
    "denied", "refused", "unreachable", "fatal",
    "warn", "warning", "access denied", "connection refused",
    "ssl", "tls", "certificate", "proxy",
    "authentication", "unauthorized", "forbidden",
    "service stopped", "service started", "crash",
    "retry", "reconnect",
]


# === REGEX COMPILADOS PARA NORMALIZACIÓN ===

# Orden fijo de aplicación: timestamps → UUIDs → IPv4 → temp paths → números
_RE_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}")
_RE_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_RE_IPV4 = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
)
_RE_TEMP_PATH = re.compile(
    r"(?:[A-Za-z]:\\|\\\\[^\\\s]+\\[^\\\s]+\\)"
    r"(?:[^\\\s]+\\)*(?:[Tt]emp|[Tt]mp)\\[^\s]*",
    re.IGNORECASE,
)
_RE_NUMBERS = re.compile(r"\d{2,}")

# Regex para extracción de timestamp
_RE_PARSE_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")


# === FUNCIONES DE DETECCIÓN Y NORMALIZACIÓN ===


def detect_keywords(
    line: str, keywords: list[str], case_insensitive: bool = True
) -> bool:
    """
    Determina si una línea contiene alguno de los keywords (substring match).

    Parámetros:
        line: Contenido de la línea
        keywords: Lista de patrones a buscar (substring match)
        case_insensitive: Si True, comparación case-insensitive

    Retorna:
        True si la línea contiene al menos un keyword.
    """
    if case_insensitive:
        line_lower = line.lower()
        return any(kw.lower() in line_lower for kw in keywords)
    return any(kw in line for kw in keywords)


def parse_timestamp(line: str) -> Optional[str]:
    """
    Extrae timestamp en formato YYYY-MM-DD HH:MM:SS de una línea.

    Busca el primer match del patrón de timestamp en la línea.

    Parámetros:
        line: Línea de log

    Retorna:
        String del timestamp encontrado o None si no se encuentra.
    """
    match = _RE_PARSE_TIMESTAMP.search(line)
    if match:
        return match.group(0)
    return None


def normalize_line(line: str) -> str:
    """
    Aplica normalizaciones en orden fijo para agrupar patrones repetidos.

    Orden de aplicación (de más específico a más general):
    1. Timestamps (YYYY-MM-DD HH:MM:SS) → [TIMESTAMP]
    2. UUIDs (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx) → [UUID]
    3. IPv4 (N.N.N.N) → [IP]
    4. Rutas temporales Windows (contienen \\Temp\\ o \\tmp\\) → [TEMP_PATH]
    5. Secuencias numéricas (2+ dígitos) → [NUMBER]

    El orden garantiza que dígitos dentro de timestamps, UUIDs, IPs y rutas
    temporales no sean reemplazados prematuramente por [NUMBER].

    Parámetros:
        line: Línea original

    Retorna:
        Línea normalizada con placeholders genéricos.
    """
    # 1. Reemplazar timestamps
    result = _RE_TIMESTAMP.sub("[TIMESTAMP]", line)
    # 2. Reemplazar UUIDs
    result = _RE_UUID.sub("[UUID]", result)
    # 3. Reemplazar IPv4
    result = _RE_IPV4.sub("[IP]", result)
    # 4. Reemplazar rutas temporales Windows
    result = _RE_TEMP_PATH.sub("[TEMP_PATH]", result)
    # 5. Reemplazar secuencias numéricas (2+ dígitos) — último para no afectar anteriores
    result = _RE_NUMBERS.sub("[NUMBER]", result)
    return result


# === FUNCIONES DE VENTANAS DE CONTEXTO ===


def extract_context_windows(
    matches: list[MatchInfo],
    lines: list[str],
    context_size: int = 20,
) -> list[ContextBlock]:
    """
    Extrae ventanas de contexto alrededor de cada match y fusiona solapamientos.

    Para cada match, calcula una ventana de N líneas antes y N líneas después.
    Cuando el match está cerca del inicio o final del archivo, extrae todas las
    líneas disponibles hasta el límite. Las ventanas solapantes o adyacentes se
    fusionan en un solo bloque contiguo.

    Parámetros:
        matches: Lista de matches encontrados (line_number es 1-based)
        lines: Todas las líneas del archivo (indexadas desde 0)
        context_size: Líneas antes/después de cada match (default 20)

    Retorna:
        Lista de ContextBlocks fusionados, ordenados por start_line.
    """
    if not matches or not lines:
        return []

    total_lines = len(lines)

    # Construir ventanas crudas: (start, end, match_lines)
    # start y end son 1-based inclusive
    windows: list[tuple[int, int, set[int]]] = []
    for match in matches:
        line_num = match.line_number  # 1-based
        # Calcular inicio y fin de la ventana (1-based)
        start = max(1, line_num - context_size)
        end = min(total_lines, line_num + context_size)
        windows.append((start, end, {line_num}))

    # Ordenar por start
    windows.sort(key=lambda w: w[0])

    # Fusionar ventanas solapantes o adyacentes
    merged = merge_windows(windows)

    # Construir ContextBlocks a partir de ventanas fusionadas
    blocks: list[ContextBlock] = []
    for start, end, match_lines in merged:
        # Extraer líneas (convertir de 1-based a 0-based para indexar)
        block_lines: list[tuple[int, str]] = []
        for line_num in range(start, end + 1):
            idx = line_num - 1  # Convertir a 0-based
            if 0 <= idx < total_lines:
                block_lines.append((line_num, lines[idx]))

        block = ContextBlock(
            start_line=start,
            end_line=end,
            lines=block_lines,
            match_lines=match_lines,
        )
        blocks.append(block)

    return blocks


def merge_windows(
    windows: list[tuple[int, int, set[int]]]
) -> list[tuple[int, int, set[int]]]:
    """
    Fusiona ventanas solapantes o adyacentes en bloques contiguos.

    Dos ventanas se fusionan si se solapan (comparten líneas) o son adyacentes
    (separadas por 0 líneas, es decir, end de una == start de la siguiente - 1).

    Parámetros:
        windows: Lista de (start, end, match_lines) ordenada por start.
                 start y end son 1-based inclusive.

    Retorna:
        Lista fusionada sin solapamientos, ordenada por start.
    """
    if not windows:
        return []

    # Asegurar orden por start
    sorted_windows = sorted(windows, key=lambda w: w[0])

    merged: list[tuple[int, int, set[int]]] = []
    current_start, current_end, current_matches = sorted_windows[0]
    current_matches = set(current_matches)  # Copia para no mutar original

    for start, end, match_lines in sorted_windows[1:]:
        # Fusionar si solapan o son adyacentes (start <= current_end + 1)
        if start <= current_end + 1:
            current_end = max(current_end, end)
            current_matches = current_matches | match_lines
        else:
            merged.append((current_start, current_end, current_matches))
            current_start = start
            current_end = end
            current_matches = set(match_lines)

    # Agregar la última ventana
    merged.append((current_start, current_end, current_matches))

    return merged


def select_blocks(
    blocks: list[ContextBlock],
    patterns: list[RecurringPattern],
    max_blocks: int = 30,
) -> tuple[list[ContextBlock], int]:
    """
    Selecciona bloques respetando max_blocks.
    Prioriza bloques con primera ocurrencia de cada patrón distinto.

    Estrategia de selección:
    1. Identificar bloques que contienen la primera ocurrencia de cada patrón
    2. Retener esos bloques prioritarios (hasta max_blocks)
    3. Rellenar con bloques restantes en orden cronológico hasta el límite
    4. Descartar el resto y contar bloques omitidos

    Parámetros:
        blocks: Todos los bloques candidatos (ordenados por start_line)
        patterns: Patrones para identificar primeras ocurrencias
        max_blocks: Límite máximo de bloques a retornar

    Retorna:
        Tupla (bloques_seleccionados, bloques_omitidos).
    """
    if not blocks:
        return ([], 0)

    if len(blocks) <= max_blocks:
        return (blocks, 0)

    # Obtener líneas de primera ocurrencia de cada patrón
    first_occurrence_lines: set[int] = set()
    for pattern in patterns:
        first_occurrence_lines.add(pattern.first_line)

    # Clasificar bloques: prioritarios (contienen primera ocurrencia) vs resto
    priority_blocks: list[ContextBlock] = []
    other_blocks: list[ContextBlock] = []

    for block in blocks:
        # Un bloque es prioritario si contiene alguna línea de primera ocurrencia
        if block.match_lines & first_occurrence_lines:
            priority_blocks.append(block)
        else:
            other_blocks.append(block)

    # Seleccionar: primero los prioritarios, luego los demás
    selected: list[ContextBlock] = []

    # Agregar prioritarios (hasta max_blocks)
    for block in priority_blocks:
        if len(selected) >= max_blocks:
            break
        selected.append(block)

    # Rellenar con bloques restantes en orden cronológico
    for block in other_blocks:
        if len(selected) >= max_blocks:
            break
        selected.append(block)

    # Ordenar seleccionados por start_line para mantener orden cronológico
    selected.sort(key=lambda b: b.start_line)

    omitted = len(blocks) - len(selected)
    return (selected, omitted)


# === FUNCIONES DE AGRUPACIÓN Y TIMELINE ===


def group_patterns(matches: list[MatchInfo]) -> list[RecurringPattern]:
    """
    Agrupa matches por forma normalizada y cuenta ocurrencias.

    Para cada grupo con 2 o más ocurrencias, crea un RecurringPattern con:
    - normalized_text: la forma normalizada compartida
    - count: número de ocurrencias
    - first_line: número de línea de la primera ocurrencia
    - first_timestamp: timestamp de la primera ocurrencia (o None)
    - raw_example: contenido crudo de la primera ocurrencia (truncado a 500 chars)

    Parámetros:
        matches: Lista de matches con campo normalized

    Retorna:
        Lista de RecurringPattern ordenada por count descendente.
        Solo incluye patrones con count >= 2.
    """
    if not matches:
        return []

    # Agrupar por texto normalizado
    groups: dict[str, list[MatchInfo]] = {}
    for match in matches:
        key = match.normalized
        if key not in groups:
            groups[key] = []
        groups[key].append(match)

    # Crear RecurringPattern para grupos con 2+ ocurrencias
    patterns: list[RecurringPattern] = []
    for normalized_text, group_matches in groups.items():
        if len(group_matches) < 2:
            continue

        # Encontrar la primera ocurrencia (menor line_number)
        first_match = min(group_matches, key=lambda m: m.line_number)

        pattern = RecurringPattern(
            normalized_text=normalized_text,
            count=len(group_matches),
            first_line=first_match.line_number,
            first_timestamp=first_match.timestamp,
            raw_example=first_match.content,  # __post_init__ trunca a 500
        )
        patterns.append(pattern)

    # Ordenar por count descendente
    patterns.sort(key=lambda p: p.count, reverse=True)

    return patterns


def identify_first_occurrences(
    patterns: list[RecurringPattern], matches: list[MatchInfo]
) -> list[MatchInfo]:
    """
    Identifica primera ocurrencia de cada patrón recurrente.

    Para cada RecurringPattern, busca en matches el que tenga el menor
    line_number con el mismo texto normalizado. Luego ordena los resultados
    por timestamp ascendente (si todos tienen timestamp) o por line_number
    ascendente (si alguno no tiene timestamp).

    Parámetros:
        patterns: Patrones agrupados (resultado de group_patterns)
        matches: Todos los matches originales

    Retorna:
        Lista de primeras ocurrencias ordenada cronológicamente.
    """
    if not patterns or not matches:
        return []

    # Construir índice de matches por texto normalizado
    matches_by_normalized: dict[str, list[MatchInfo]] = {}
    for match in matches:
        key = match.normalized
        if key not in matches_by_normalized:
            matches_by_normalized[key] = []
        matches_by_normalized[key].append(match)

    # Para cada patrón, encontrar la primera ocurrencia (menor line_number)
    first_occurrences: list[MatchInfo] = []
    for pattern in patterns:
        group = matches_by_normalized.get(pattern.normalized_text, [])
        if group:
            first_match = min(group, key=lambda m: m.line_number)
            first_occurrences.append(first_match)

    # Determinar criterio de ordenación:
    # Si todos tienen timestamp → ordenar por timestamp ascendente
    # Si alguno no tiene timestamp → ordenar por line_number ascendente
    all_have_timestamps = all(
        m.timestamp is not None for m in first_occurrences
    )

    if all_have_timestamps and first_occurrences:
        first_occurrences.sort(key=lambda m: m.timestamp)  # type: ignore[arg-type]
    else:
        first_occurrences.sort(key=lambda m: m.line_number)

    return first_occurrences


def build_condensed_timeline(
    matches: list[MatchInfo],
) -> list[TimelineEntry]:
    """
    Construye línea de tiempo condensada.

    Parsea timestamps de los matches, determina el span temporal total.
    Si span ≤ 1 hora, agrupa por minuto (formato "YYYY-MM-DD HH:MM").
    Si span > 1 hora, agrupa por hora (formato "YYYY-MM-DD HH:00").
    Cada entrada incluye total_count y event_types (dict de tipo→conteo).

    Retorna lista vacía si no hay timestamps parseables.
    Ordena cronológicamente por time_group.

    Parámetros:
        matches: Lista de matches con timestamps opcionales

    Retorna:
        Lista de TimelineEntry ordenada cronológicamente.
        Lista vacía si no hay timestamps parseables.
    """
    from datetime import datetime, timedelta

    if not matches:
        return []

    # Filtrar matches con timestamps parseables
    timed_matches: list[tuple[datetime, MatchInfo]] = []
    for match in matches:
        if match.timestamp:
            try:
                dt = datetime.strptime(match.timestamp, "%Y-%m-%d %H:%M:%S")
                timed_matches.append((dt, match))
            except ValueError:
                continue

    if not timed_matches:
        return []

    # Determinar span temporal
    timestamps_only = [dt for dt, _ in timed_matches]
    earliest = min(timestamps_only)
    latest = max(timestamps_only)
    span = latest - earliest

    # Decidir granularidad: por minuto si span ≤ 1h, por hora si > 1h
    group_by_minute = span <= timedelta(hours=1)

    # Agrupar matches por time_group
    groups: dict[str, list[MatchInfo]] = {}
    for dt, match in timed_matches:
        if group_by_minute:
            # Formato "YYYY-MM-DD HH:MM"
            time_group = dt.strftime("%Y-%m-%d %H:%M")
        else:
            # Formato "YYYY-MM-DD HH:00"
            time_group = dt.strftime("%Y-%m-%d %H:00")

        if time_group not in groups:
            groups[time_group] = []
        groups[time_group].append(match)

    # Construir TimelineEntries
    timeline: list[TimelineEntry] = []
    for time_group, group_matches in groups.items():
        # Contar tipos de eventos (usar texto normalizado como tipo)
        event_types: dict[str, int] = {}
        for match in group_matches:
            event_type = match.normalized
            if event_type not in event_types:
                event_types[event_type] = 0
            event_types[event_type] += 1

        entry = TimelineEntry(
            time_group=time_group,
            total_count=len(group_matches),
            event_types=event_types,
        )
        timeline.append(entry)

    # Ordenar cronológicamente
    timeline.sort(key=lambda e: e.time_group)

    return timeline


# === GENERACIÓN DE OUTPUT ESTRUCTURADO ===


def _truncate(text: str, max_len: int = 500) -> str:
    """Trunca texto a max_len caracteres, añadiendo '...' si se excede."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def generate_structured_output(
    result: StructuralAnalysisResult,
    top_n: int = 50,
) -> str:
    """
    Genera texto Markdown estructurado con toda la evidencia.

    Secciones en orden fijo:
    1. Metadata
    2. Top Recurring Patterns (Patrones Recurrentes)
    3. First Critical Occurrences (Primeras Ocurrencias Críticas)
    4. Context Blocks (Bloques de Contexto)
    5. Condensed Timeline (Línea de Tiempo Condensada)

    Si no se encontraron matches (no_matches=True), incluye head_sample y
    tail_sample con una nota indicando que no se detectaron errores obvios.

    Parámetros:
        result: Resultado del análisis estructural
        top_n: Máximo de patrones a incluir en la sección de patrones

    Retorna:
        String Markdown con el análisis estructurado.
    """
    sections: list[str] = []

    # === Sección 1: Metadata ===
    sections.append("## Metadata\n")
    sections.append(f"- **Archivo fuente:** {result.source_name}")
    sections.append(f"- **Tamaño del archivo:** {result.file_size_bytes} bytes")
    sections.append(f"- **Total de líneas:** {result.total_lines}")
    ts_range = "N/A"
    if result.earliest_timestamp and result.latest_timestamp:
        ts_range = f"{result.earliest_timestamp} → {result.latest_timestamp}"
    elif result.earliest_timestamp:
        ts_range = result.earliest_timestamp
    sections.append(f"- **Rango de timestamps:** {ts_range}")
    sections.append(f"- **Total de coincidencias:** {result.total_matches}")
    sections.append(f"- **Patrones únicos:** {result.unique_patterns}")

    # Caso sin matches: incluir muestras de head/tail
    if result.no_matches:
        sections.append("")
        sections.append(
            "> **Nota:** No se detectaron errores obvios en el log. "
            "Se incluyen las primeras y últimas líneas como muestra."
        )
        if result.head_sample:
            sections.append("")
            sections.append("### Primeras líneas (muestra)")
            sections.append("```")
            for line in result.head_sample:
                sections.append(line)
            sections.append("```")
        if result.tail_sample:
            sections.append("")
            sections.append("### Últimas líneas (muestra)")
            sections.append("```")
            for line in result.tail_sample:
                sections.append(line)
            sections.append("```")

        return "\n".join(sections)

    # === Sección 2: Patrones Recurrentes ===
    sections.append("")
    sections.append("## Patrones Recurrentes\n")
    patterns_to_show = result.patterns[:top_n]
    if patterns_to_show:
        for i, pattern in enumerate(patterns_to_show, 1):
            raw_truncated = _truncate(pattern.raw_example, 500)
            sections.append(f"### Patrón {i} (×{pattern.count})")
            sections.append(f"- **Normalizado:** `{pattern.normalized_text}`")
            sections.append(f"- **Ejemplo:** {raw_truncated}")
            sections.append("")
    else:
        sections.append("_No se encontraron patrones recurrentes (≥2 ocurrencias)._")
        sections.append("")

    # === Sección 3: Primeras Ocurrencias Críticas ===
    sections.append("## Primeras Ocurrencias Críticas\n")
    if result.critical_occurrences:
        for occurrence in result.critical_occurrences:
            ts_display = occurrence.timestamp if occurrence.timestamp else "N/A"
            content_truncated = _truncate(occurrence.content, 500)
            sections.append(
                f"- **Línea {occurrence.line_number}** "
                f"[{ts_display}]: {content_truncated}"
            )
        sections.append("")
    else:
        sections.append("_No se identificaron primeras ocurrencias críticas._")
        sections.append("")

    # === Sección 4: Bloques de Contexto ===
    sections.append("## Bloques de Contexto\n")
    if result.context_blocks:
        for block_idx, block in enumerate(result.context_blocks, 1):
            sections.append(
                f"### Bloque {block_idx} "
                f"(líneas {block.start_line}-{block.end_line})"
            )
            sections.append("```")
            for line_num, content in block.lines:
                if line_num in block.match_lines:
                    sections.append(f">> {line_num:>6}: {content}")
                else:
                    sections.append(f"   {line_num:>6}: {content}")
            sections.append("```")
            sections.append("")

        if result.blocks_omitted > 0:
            sections.append(
                f"> **Nota:** Se omitieron {result.blocks_omitted} bloques "
                f"adicionales por límite de espacio."
            )
            sections.append("")
    else:
        sections.append("_No se generaron bloques de contexto._")
        sections.append("")

    # === Sección 5: Línea de Tiempo Condensada ===
    sections.append("## Línea de Tiempo Condensada\n")
    if result.timeline:
        for entry in result.timeline:
            # Listar tipos de eventos con sus conteos
            event_summary = ", ".join(
                f"`{etype}` (×{count})"
                for etype, count in sorted(
                    entry.event_types.items(), key=lambda x: x[1], reverse=True
                )
            )
            sections.append(
                f"- **{entry.time_group}** — "
                f"{entry.total_count} eventos: {event_summary}"
            )
        sections.append("")
    else:
        sections.append(
            "_No se detectaron timestamps parseables. "
            "No se puede generar línea de tiempo._"
        )
        sections.append("")

    return "\n".join(sections)


def run_structural_analysis(
    content: str,
    filename: str,
    keywords: list[str],
    context_size: int = 20,
    max_blocks: int = 30,
    top_n: int = 50,
) -> str:
    """
    Ejecuta el pipeline completo de análisis estructural.

    Orquesta todas las funciones de procesamiento en orden:
    1. Dividir contenido en líneas
    2. Detectar keywords en cada línea
    3. Parsear timestamps y normalizar líneas con matches
    4. Extraer ventanas de contexto y fusionar solapamientos
    5. Agrupar patrones recurrentes
    6. Seleccionar bloques respetando el límite
    7. Identificar primeras ocurrencias críticas
    8. Construir línea de tiempo condensada
    9. Generar output Markdown estructurado

    Maneja el caso sin matches: incluye primeras 50 y últimas 50 líneas.

    Parámetros:
        content: Contenido completo del log
        filename: Nombre del archivo fuente
        keywords: Lista de keywords para detección
        context_size: Líneas de contexto antes/después de cada match
        max_blocks: Máximo de bloques de contexto
        top_n: Top N patrones a incluir en el output

    Retorna:
        String Markdown con análisis estructurado listo para enviar al LLM.
    """
    # 1. Dividir en líneas
    lines = content.splitlines()
    total_lines = len(lines)
    file_size_bytes = len(content.encode("utf-8"))

    # 2. Detectar keywords y construir matches
    matches: list[MatchInfo] = []
    for idx, line in enumerate(lines):
        if detect_keywords(line, keywords):
            line_number = idx + 1  # 1-based
            timestamp = parse_timestamp(line)
            normalized = normalize_line(line)
            # Truncar contenido a 10000 chars (MatchInfo.__post_init__ lo hace)
            match_info = MatchInfo(
                line_number=line_number,
                timestamp=timestamp,
                content=line,
                normalized=normalized,
            )
            matches.append(match_info)

    # 3. Determinar rango de timestamps
    timestamps_found = [m.timestamp for m in matches if m.timestamp]
    earliest_timestamp: Optional[str] = None
    latest_timestamp: Optional[str] = None
    if timestamps_found:
        earliest_timestamp = min(timestamps_found)
        latest_timestamp = max(timestamps_found)

    # 4. Caso sin matches: incluir head/tail sample
    if not matches:
        head_sample = lines[:50]
        tail_sample = lines[-50:] if total_lines > 50 else []

        result = StructuralAnalysisResult(
            source_name=filename,
            file_size_bytes=file_size_bytes,
            total_lines=total_lines,
            earliest_timestamp=None,
            latest_timestamp=None,
            total_matches=0,
            unique_patterns=0,
            patterns=[],
            critical_occurrences=[],
            context_blocks=[],
            timeline=[],
            blocks_omitted=0,
            head_sample=head_sample,
            tail_sample=tail_sample,
            no_matches=True,
        )
        return generate_structured_output(result, top_n=top_n)

    # 5. Extraer ventanas de contexto
    context_blocks = extract_context_windows(matches, lines, context_size)

    # 6. Agrupar patrones recurrentes
    patterns = group_patterns(matches)

    # 7. Seleccionar bloques respetando límite
    selected_blocks, blocks_omitted = select_blocks(
        context_blocks, patterns, max_blocks
    )

    # 8. Identificar primeras ocurrencias críticas
    critical_occurrences = identify_first_occurrences(patterns, matches)

    # 9. Construir línea de tiempo condensada
    timeline = build_condensed_timeline(matches)

    # 10. Ensamblar resultado
    result = StructuralAnalysisResult(
        source_name=filename,
        file_size_bytes=file_size_bytes,
        total_lines=total_lines,
        earliest_timestamp=earliest_timestamp,
        latest_timestamp=latest_timestamp,
        total_matches=len(matches),
        unique_patterns=len(patterns),
        patterns=patterns,
        critical_occurrences=critical_occurrences,
        context_blocks=selected_blocks,
        timeline=timeline,
        blocks_omitted=blocks_omitted,
    )

    # 11. Generar output Markdown
    return generate_structured_output(result, top_n=top_n)


# === FUNCIONES DE ENSAMBLAJE DE PAYLOAD ===


def assemble_direct_payload(
    log_content: str,
    prompt: str,
    workstation_id: str,
    filename: str,
    file_size: int,
) -> str:
    """
    Ensambla el payload para la ruta directa (prompt + metadata + log crudo).

    Formato del payload:
    - Prompt del LLM
    - Separador "---"
    - Sección Metadata con workstation_id, filename, file_size, timestamp
    - Sección Log Content con el contenido crudo completo

    Parámetros:
        log_content: Contenido crudo del log
        prompt: LLM_Prompt pre-construido
        workstation_id: ID de la workstation
        filename: Nombre del archivo
        file_size: Tamaño en bytes del archivo original

    Retorna:
        String con prompt + delimiter + metadata + log content.
    """
    from datetime import datetime

    timestamp_now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    metadata_lines = [
        "## Metadata\n",
        f"- **Workstation ID:** {workstation_id}",
        f"- **Archivo:** {filename}",
        f"- **Tamaño:** {file_size} bytes",
        f"- **Timestamp de análisis:** {timestamp_now}",
    ]
    metadata_section = "\n".join(metadata_lines)

    payload = (
        f"{prompt}\n\n"
        f"---\n\n"
        f"{metadata_section}\n\n"
        f"## Log Content\n\n"
        f"{log_content}"
    )

    return payload


def assemble_structural_payload(
    structured_analysis: str,
    prompt: str,
) -> str:
    """
    Ensambla el payload para la ruta estructural (prompt + análisis).

    Formato del payload:
    - Prompt del LLM
    - Separador "---"
    - Análisis estructural completo en Markdown

    Parámetros:
        structured_analysis: Markdown del análisis estructural
        prompt: LLM_Prompt pre-construido

    Retorna:
        String con prompt + delimiter + structured analysis.
    """
    payload = f"{prompt}\n\n---\n\n{structured_analysis}"
    return payload
