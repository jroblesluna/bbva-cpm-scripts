"""
Wrapper Python que replica la lógica de JitterCalculator (C#).

Esta clase permite testear con Hypothesis las propiedades del calculador
de jitter sin depender del runtime .NET. La lógica es idéntica a
AlwaysPrint.Shared/Configuration/JitterCalculator.cs

Feature: reconnection-jitter
"""

import random
from datetime import datetime, timedelta
from typing import Optional, Tuple


# Constantes equivalentes a las del C#
DEFAULT_JITTER_WINDOW_SECONDS = 30
MIN_JITTER_WINDOW = 5
MAX_JITTER_WINDOW = 300
RECENT_THRESHOLD_SECONDS = 60


def normalize_jitter_window(raw_value: int) -> int:
    """
    Normaliza el valor de la ventana de jitter.
    Si está fuera del rango [5, 300], retorna el valor por defecto (30).
    """
    if raw_value < MIN_JITTER_WINDOW or raw_value > MAX_JITTER_WINDOW:
        return DEFAULT_JITTER_WINDOW_SECONDS
    return raw_value


def is_timestamp_recent(utc_now: datetime, timestamp: Optional[datetime]) -> bool:
    """
    Determina si un timestamp es "reciente" (< 60 segundos de antigüedad).
    Un timestamp NO es reciente si:
    - Es None (ausente)
    - Es futuro respecto a utc_now (inválido)
    - Tiene 60 o más segundos de antigüedad
    """
    if timestamp is None:
        return False

    # Timestamp futuro → inválido
    if timestamp > utc_now:
        return False

    # Calcular diferencia en segundos
    diff_seconds = (utc_now - timestamp).total_seconds()

    # Reciente solo si la diferencia es menor al umbral (60s)
    return diff_seconds < RECENT_THRESHOLD_SECONDS


def compute_startup_delay(
    utc_now: datetime,
    last_update_timestamp: Optional[datetime],
    last_restart_timestamp: Optional[datetime],
    jitter_window_seconds: int,
    rng: Optional[random.Random] = None,
) -> Tuple[int, Optional[str]]:
    """
    Calcula el delay en milisegundos antes de conectar al WebSocket durante el arranque.
    Retorna 0 si no se requiere jitter (timestamp ausente, inválido, futuro o antiguo).
    Si ambos timestamps son recientes, usa el más cercano a utcNow y aplica jitter una sola vez.

    Retorna: (delay_ms, reason)
    """
    # Normalizar la ventana de jitter al rango válido
    normalized_window = normalize_jitter_window(jitter_window_seconds)

    # Evaluar si los timestamps son recientes y válidos
    update_is_recent = is_timestamp_recent(utc_now, last_update_timestamp)
    restart_is_recent = is_timestamp_recent(utc_now, last_restart_timestamp)

    # Si ningún timestamp es reciente, no aplicar jitter
    if not update_is_recent and not restart_is_recent:
        return (0, None)

    if update_is_recent and restart_is_recent:
        # Ambos son recientes: usar el más cercano a utcNow (menor diferencia)
        update_diff = (utc_now - last_update_timestamp).total_seconds()
        restart_diff = (utc_now - last_restart_timestamp).total_seconds()

        # El más cercano tiene menor diferencia temporal
        reason = "post-restart" if restart_diff <= update_diff else "post-update"
    elif update_is_recent:
        reason = "post-update"
    else:
        reason = "post-restart"

    # Calcular delay aleatorio uniforme en [0, normalized_window * 1000) ms
    r = rng if rng is not None else random.Random()
    delay_ms = r.randint(0, normalized_window * 1000 - 1)

    return (delay_ms, reason)


def compute_reconnection_delay(
    jitter_window_seconds: int,
    rng: Optional[random.Random] = None,
) -> int:
    """
    Calcula el delay para el primer intento de reconexión tras una desconexión WebSocket.
    Siempre aplica jitter con distribución uniforme U(0, W*1000).
    """
    # Normalizar la ventana de jitter al rango válido
    normalized_window = normalize_jitter_window(jitter_window_seconds)

    # Calcular delay aleatorio uniforme en [0, normalized_window * 1000) ms
    r = rng if rng is not None else random.Random()
    return r.randint(0, normalized_window * 1000 - 1)


def compute_frontend_rate(jitter_window_seconds: int, workstation_count: int) -> float:
    """
    Calcula la tasa de conexiones por segundo para mostrar en el frontend.
    Fórmula: N/X redondeado a 1 decimal.

    Parámetros:
        jitter_window_seconds: Ventana de jitter X ∈ [5, 300]
        workstation_count: Número de workstations activas N > 0

    Retorna:
        Tasa de conexiones por segundo (N/X) redondeada a 1 decimal.
    """
    rate = workstation_count / jitter_window_seconds
    return round(rate, 1)


def format_frontend_calculation_text(
    jitter_window_seconds: int, workstation_count: int
) -> str:
    """
    Genera el texto que muestra el frontend con el cálculo de tasa.
    Formato: "Con X segundos de ventana y N workstations activas,
    aproximadamente {rate} conexiones por segundo durante eventos masivos"

    Parámetros:
        jitter_window_seconds: Ventana de jitter X ∈ [5, 300]
        workstation_count: Número de workstations activas N > 0

    Retorna:
        Texto formateado con la tasa calculada.
    """
    rate = compute_frontend_rate(jitter_window_seconds, workstation_count)
    return (
        f"Con {jitter_window_seconds} segundos de ventana y "
        f"{workstation_count} workstations activas, aproximadamente "
        f"{rate} conexiones por segundo durante eventos masivos"
    )
