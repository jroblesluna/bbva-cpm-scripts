"""
Property tests para los límites del delay de jitter ante eventos recientes.

Verifica que JitterCalculator.ComputeStartupDelay produce un delay
dentro del rango [0, W*1000) milisegundos cuando el timestamp del evento
tiene una antigüedad menor a 60 segundos.

Se usa un wrapper Python que replica la lógica de JitterCalculator.cs
para validar la propiedad con Hypothesis.

**Validates: Requirements 3.1, 4.1**

Feature: reconnection-jitter, Property 3: Jitter delay bounds for recent trigger events
"""

import random
from datetime import datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st


# === CONSTANTES (réplica de JitterCalculator.cs) ===

# Valor por defecto de la ventana de jitter (segundos)
DEFAULT_JITTER_WINDOW_SECONDS = 30

# Rango válido para la ventana de jitter
MIN_JITTER_WINDOW = 5
MAX_JITTER_WINDOW = 300

# Umbral en segundos para considerar un timestamp como "reciente"
RECENT_THRESHOLD_SECONDS = 60


# === PYTHON WRAPPER DE JitterCalculator ===


def normalize_jitter_window(raw_value: int) -> int:
    """
    Normaliza el valor de la ventana de jitter.
    Si está fuera del rango [5, 300], retorna el valor por defecto (30).
    Replica: JitterCalculator.NormalizeJitterWindow(int rawValue)
    """
    if raw_value < MIN_JITTER_WINDOW or raw_value > MAX_JITTER_WINDOW:
        return DEFAULT_JITTER_WINDOW_SECONDS
    return raw_value


def is_timestamp_recent(utc_now: datetime, timestamp: datetime | None) -> bool:
    """
    Determina si un timestamp es "reciente" (< 60 segundos de antigüedad).
    Un timestamp NO es reciente si:
    - Es None (ausente)
    - Es futuro respecto a utc_now (inválido)
    - Tiene 60 o más segundos de antigüedad
    Replica: JitterCalculator.IsTimestampRecent(DateTime, DateTime?)
    """
    if timestamp is None:
        return False
    if timestamp > utc_now:
        return False
    diff_seconds = (utc_now - timestamp).total_seconds()
    return diff_seconds < RECENT_THRESHOLD_SECONDS


def compute_startup_delay(
    utc_now: datetime,
    last_update_timestamp: datetime | None,
    last_restart_timestamp: datetime | None,
    jitter_window_seconds: int,
    rng: random.Random | None = None,
) -> tuple[int, str | None]:
    """
    Calcula el delay en milisegundos antes de conectar al WebSocket durante el arranque.
    Retorna 0 si no se requiere jitter.
    Si ambos timestamps son recientes, usa el más cercano a utc_now y aplica jitter una sola vez.
    Replica: JitterCalculator.ComputeStartupDelay(...)
    """
    # Normalizar la ventana de jitter al rango válido
    normalized_window = normalize_jitter_window(jitter_window_seconds)

    # Evaluar si cada timestamp es reciente
    update_is_recent = is_timestamp_recent(utc_now, last_update_timestamp)
    restart_is_recent = is_timestamp_recent(utc_now, last_restart_timestamp)

    # Si ningún timestamp es reciente, no aplicar jitter
    if not update_is_recent and not restart_is_recent:
        return (0, None)

    # Determinar la razón del jitter
    if update_is_recent and restart_is_recent:
        # Ambos son recientes: usar el más cercano a utc_now (menor diferencia)
        update_diff = (utc_now - last_update_timestamp).total_seconds()  # type: ignore
        restart_diff = (utc_now - last_restart_timestamp).total_seconds()  # type: ignore
        reason = "post-restart" if restart_diff <= update_diff else "post-update"
    elif update_is_recent:
        reason = "post-update"
    else:
        reason = "post-restart"

    # Calcular delay aleatorio uniforme en [0, normalized_window * 1000) ms
    r = rng if rng is not None else random.Random()
    delay_ms = r.randrange(0, normalized_window * 1000)

    return (delay_ms, reason)


# === ESTRATEGIAS DE GENERACIÓN ===

# Ventana de jitter válida: entero en [5, 300]
_jitter_window = st.integers(min_value=MIN_JITTER_WINDOW, max_value=MAX_JITTER_WINDOW)

# Diferencia temporal en segundos para un timestamp reciente: [0, 59.9]
# Usamos milisegundos para más granularidad, pero el Δt debe ser < 60s
_recent_delta_seconds = st.floats(min_value=0.0, max_value=59.9, allow_nan=False, allow_infinity=False)

# Semilla para el generador aleatorio (testing determinístico)
_seed = st.integers(min_value=0, max_value=2**31 - 1)


# === PROPERTY 3: JITTER DELAY BOUNDS FOR RECENT TRIGGER EVENTS ===


class TestJitterDelayBoundsForRecentEvents:
    """
    Property 3: Jitter delay bounds for recent trigger events.

    Para cualquier ventana de jitter W en [5, 300] y cualquier timestamp
    de trigger (update o restart) que tenga menos de 60 segundos de antigüedad,
    el delay calculado SHALL ser >= 0 y < W*1000 milisegundos.

    **Validates: Requirements 3.1, 4.1**
    """

    @given(
        jitter_window=_jitter_window,
        delta_seconds=_recent_delta_seconds,
        seed=_seed,
    )
    @settings(max_examples=100, deadline=None)
    def test_delay_dentro_de_limites_con_update_timestamp_reciente(
        self, jitter_window: int, delta_seconds: float, seed: int
    ):
        """
        Con un LastUpdateTimestamp reciente (Δt < 60s), el delay
        está en [0, W*1000) milisegundos.

        **Validates: Requirements 3.1, 4.1**
        """
        # Construir el escenario: utc_now y un timestamp de actualización reciente
        utc_now = datetime(2026, 6, 15, 12, 0, 0)
        last_update = utc_now - timedelta(seconds=delta_seconds)

        # Usar un Random con seed fijo para determinismo
        rng = random.Random(seed)

        # Calcular el delay
        delay_ms, reason = compute_startup_delay(
            utc_now=utc_now,
            last_update_timestamp=last_update,
            last_restart_timestamp=None,
            jitter_window_seconds=jitter_window,
            rng=rng,
        )

        # Verificar que el delay está en el rango correcto [0, W*1000)
        max_delay = jitter_window * 1000
        assert 0 <= delay_ms < max_delay, (
            f"delay_ms={delay_ms} fuera de [0, {max_delay}) "
            f"con window={jitter_window}, delta={delta_seconds}s"
        )

        # Verificar que se aplicó jitter (reason no es None)
        assert reason is not None, (
            f"Se esperaba reason no-None con timestamp reciente "
            f"(delta={delta_seconds}s)"
        )

    @given(
        jitter_window=_jitter_window,
        delta_seconds=_recent_delta_seconds,
        seed=_seed,
    )
    @settings(max_examples=100, deadline=None)
    def test_delay_dentro_de_limites_con_restart_timestamp_reciente(
        self, jitter_window: int, delta_seconds: float, seed: int
    ):
        """
        Con un LastRestartTimestamp reciente (Δt < 60s), el delay
        está en [0, W*1000) milisegundos.

        **Validates: Requirements 3.1, 4.1**
        """
        # Construir el escenario: utc_now y un timestamp de reinicio reciente
        utc_now = datetime(2026, 6, 15, 12, 0, 0)
        last_restart = utc_now - timedelta(seconds=delta_seconds)

        # Usar un Random con seed fijo para determinismo
        rng = random.Random(seed)

        # Calcular el delay
        delay_ms, reason = compute_startup_delay(
            utc_now=utc_now,
            last_update_timestamp=None,
            last_restart_timestamp=last_restart,
            jitter_window_seconds=jitter_window,
            rng=rng,
        )

        # Verificar que el delay está en el rango correcto [0, W*1000)
        max_delay = jitter_window * 1000
        assert 0 <= delay_ms < max_delay, (
            f"delay_ms={delay_ms} fuera de [0, {max_delay}) "
            f"con window={jitter_window}, delta={delta_seconds}s"
        )

        # Verificar que se aplicó jitter (reason no es None)
        assert reason is not None, (
            f"Se esperaba reason no-None con timestamp reciente "
            f"(delta={delta_seconds}s)"
        )

    @given(
        jitter_window=_jitter_window,
        delta_seconds=_recent_delta_seconds,
        seed=_seed,
    )
    @settings(max_examples=100, deadline=None)
    def test_reason_es_post_update_cuando_solo_update_es_reciente(
        self, jitter_window: int, delta_seconds: float, seed: int
    ):
        """
        Cuando solo LastUpdateTimestamp es reciente, la razón del delay
        es "post-update".

        **Validates: Requirements 3.1, 4.1**
        """
        utc_now = datetime(2026, 6, 15, 12, 0, 0)
        last_update = utc_now - timedelta(seconds=delta_seconds)

        rng = random.Random(seed)

        delay_ms, reason = compute_startup_delay(
            utc_now=utc_now,
            last_update_timestamp=last_update,
            last_restart_timestamp=None,
            jitter_window_seconds=jitter_window,
            rng=rng,
        )

        assert reason == "post-update", (
            f"Se esperaba reason='post-update', obtenido='{reason}' "
            f"con solo update reciente (delta={delta_seconds}s)"
        )

    @given(
        jitter_window=_jitter_window,
        delta_seconds=_recent_delta_seconds,
        seed=_seed,
    )
    @settings(max_examples=100, deadline=None)
    def test_reason_es_post_restart_cuando_solo_restart_es_reciente(
        self, jitter_window: int, delta_seconds: float, seed: int
    ):
        """
        Cuando solo LastRestartTimestamp es reciente, la razón del delay
        es "post-restart".

        **Validates: Requirements 3.1, 4.1**
        """
        utc_now = datetime(2026, 6, 15, 12, 0, 0)
        last_restart = utc_now - timedelta(seconds=delta_seconds)

        rng = random.Random(seed)

        delay_ms, reason = compute_startup_delay(
            utc_now=utc_now,
            last_update_timestamp=None,
            last_restart_timestamp=last_restart,
            jitter_window_seconds=jitter_window,
            rng=rng,
        )

        assert reason == "post-restart", (
            f"Se esperaba reason='post-restart', obtenido='{reason}' "
            f"con solo restart reciente (delta={delta_seconds}s)"
        )
