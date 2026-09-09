# Feature: recycle-policy-config, Property 9: Comportamiento del reciclaje por tipo de uso con +1/0/-1
"""
Property test de la decisión pura de reciclaje (`decide_recycle`) bajo la política `+1/0/-1`
con Ephemeral_Use_Threshold de 24 horas (el override acordado para BBVA).

`decide_recycle` es una función pura y determinista: dado un `RecycleInputs` (created_at,
billing_cycle_started_at, last_seen crudo, timezone y política congelada) y un periodo
`(year, month)`, devuelve si la workstation debe reciclarse en ESE cierre. No implementa por
sí sola ni la garantía de primer cierre (Req 15) ni la máquina de estados; esas viven en
`close_month`. Por eso el test **modela la secuencia de estados mes a mes** replicando la
orquestación del motor de cierre (`billing_close_service.close_month`) sobre la función pura:

    1. En el primer cierre la ws pasa `new → billable` ANTES de evaluar reciclaje, por lo que
       nunca recicla en su primer periodo (Req 15.1/15.2). El reciclaje solo aplica a `billable`.
    2. En cada cierre posterior, una ws `billable` recicla si `decide_recycle` devuelve True;
       una vez `recycled` permanece `recycled` mientras no haya nueva actividad.
    3. Nueva actividad en un periodo posterior reactiva la ws (`recycled → billable`) para ESE
       cierre y en adelante (Req 13.2/14.2).

Con la política `+1/0/-1` (cutoff=+1, cut1=0, cut2=-1) al cerrar el mes M:
    - cut1 = 00:00 del día 1 de M      (Caso 1, poco uso)
    - cut2 = 00:00 del día 1 de M-1    (Caso 2, abandono)

Se verifican las secuencias exigidas por los Requisitos 13 y 14, midiendo el uso efímero
contra `billing_cycle_started_at` (Req 18.4), no contra `created_at`:

    - Uso EFÍMERO en M (uso < 24h), sin actividad en M+1/M+2:  billable, recycled, recycled  (Req 13.1)
    - Uso NORMAL  en M (uso >= 24h), sin actividad en M+1/M+2: billable, billable, recycled   (Req 14.1)
    - Actividad en M+x con x>2 (efímero o normal):             billable en M+x                (Req 13.2/14.2)

**Validates: Requirements 13.1, 13.2, 14.1, 14.2, 18.4**
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.billing_time import _shift_month
from app.services.recycle_decision import RecycleInputs, decide_recycle


# === POLÍTICA CONGELADA `+1/0/-1` (duck typing sobre los offsets + umbral) ===

# `decide_recycle` accede a la política por duck typing (cutoff/cut1/cut2/ephemeral_hours),
# ya que `ResolvedRecyclePolicy` (task 3.1) aún no existe. Este stub congelado replica
# exactamente esa interfaz para el override BBVA `+1/0/-1` con 24h de umbral efímero.
@dataclass(frozen=True)
class _StubPolicy:
    cutoff: int = 1
    cut1: int = 0
    cut2: int = -1
    ephemeral_hours: int = 24


POLICY = _StubPolicy()
EPHEMERAL_THRESHOLD_SECONDS = POLICY.ephemeral_hours * 3600

# Timezone UTC para que "00:00 del día 1" coincida con el `datetime` naive-UTC del modelo
# y el aritmético de meses del test sea directo (America/Lima tampoco tiene DST, pero UTC
# elimina cualquier corrimiento y hace el generador de fechas trivialmente coherente).
TIMEZONE = "UTC"

# Estados del ciclo de vida relevantes para el modelo de secuencia.
BILLABLE = "billable"
RECYCLED = "recycled"
NEW = "new"


# === ESTRATEGIAS DE GENERACIÓN ===

# Año/mes del primer periodo de actividad M. Se acota a rangos que no rozan los límites de
# `datetime` al restar meses (M-1, M-3...) ni al sumar (M+x), garantizando fechas válidas.
year_strategy = st.integers(min_value=2024, max_value=2035)
month_strategy = st.integers(min_value=1, max_value=12)

# Hora del día en que arranca el ciclo dentro del día 1 de M (varía el instante de inicio).
hour_strategy = st.integers(min_value=0, max_value=23)

# Duración del uso EFÍMERO: estrictamente menor que el umbral (0 .. <24h). Con inicio de
# ciclo el día 1 de M, `last_seen` cae dentro de M (los escenarios 13.1/14.1 exigen "sin uso
# en M+1 ni M+2", así que `last_seen` DEBE quedar en M).
ephemeral_use_strategy = st.integers(min_value=0, max_value=EPHEMERAL_THRESHOLD_SECONDS - 1)

# Duración del uso NORMAL: >= umbral (24h) pero acotada para que `last_seen` no se salga de M.
# Todo mes tiene al menos 28 días; con inicio el día 1 a las 00:00, hasta 27 días completos
# mantienen `last_seen` dentro de M (no genera actividad en M+1/M+2). Cota inferior = 24h.
normal_use_strategy = st.integers(
    min_value=EPHEMERAL_THRESHOLD_SECONDS,
    max_value=27 * 24 * 3600,
)

# Offset x>2 (M+x) para el reingreso de actividad.
reentry_offset_strategy = st.integers(min_value=3, max_value=18)


# === HELPERS ===


def _month_start(year: int, month: int) -> datetime:
    """00:00 del día 1 de (year, month) como datetime naive-UTC (misma convención del modelo)."""
    return datetime(year, month, 1, 0, 0, 0)


def _decide(billing_cycle_started_at: datetime, last_seen: datetime, y: int, m: int) -> bool:
    """Envuelve `decide_recycle` con la política `+1/0/-1` para el cierre del mes (y, m)."""
    inputs = RecycleInputs(
        created_at=billing_cycle_started_at,  # created_at no interviene en la decisión
        billing_cycle_started_at=billing_cycle_started_at,
        last_seen=last_seen,
        timezone=TIMEZONE,
        policy=POLICY,
    )
    return decide_recycle(inputs, y, m)


def _simulate_sequence(
    created_at: datetime,
    billing_cycle_started_at: datetime,
    last_seen: datetime,
    start_year: int,
    start_month: int,
    num_closures: int,
):
    """
    Simula la secuencia de estados de facturación cerrando `num_closures` meses consecutivos
    a partir de (start_year, start_month), replicando la orquestación de `close_month`:

    - Primer cierre: la ws está `new` → pasa a `billable` y NO se evalúa reciclaje (Req 15).
    - Cierres siguientes: si está `billable` y `decide_recycle` devuelve True → `recycled`;
      si ya está `recycled`, permanece `recycled` (no hay nueva actividad en este escenario).

    Devuelve la lista de estados resultantes, uno por cierre.
    """
    estados = []
    estado = NEW
    y, m = start_year, start_month
    for i in range(num_closures):
        if estado == NEW:
            # Paso 1 del cierre: new → billable. No se recicla en el primer cierre (Req 15).
            estado = BILLABLE
        elif estado == BILLABLE:
            if _decide(billing_cycle_started_at, last_seen, y, m):
                estado = RECYCLED
        # Si ya está RECYCLED y no hay actividad nueva, se mantiene.
        estados.append(estado)
        y, m = _shift_month(y, m, +1)
    return estados


# === PROPERTY TESTS ===


@settings(max_examples=100, deadline=None)
@given(
    year=year_strategy,
    month=month_strategy,
    use_seconds=ephemeral_use_strategy,
)
def test_uso_efimero_secuencia_billable_recycled_recycled(
    year: int, month: int, use_seconds: int
):
    """
    Req 13.1 — Con `+1/0/-1` y umbral 24h, una workstation de uso EFÍMERO en M (intervalo
    `last_seen - billing_cycle_started_at` < 24h) y sin uso en M+1/M+2 produce la secuencia
    de estados `billable` (M), `recycled` (M+1), `recycled` (M+2).

    El uso efímero se mide contra `billing_cycle_started_at` (Req 18.4). El ciclo arranca el
    día 1 de M a las 00:00 para que `last_seen` (inicio + uso, < 24h) quede dentro de M.

    **Validates: Requirements 13.1, 18.4**
    """
    inicio_ciclo = _month_start(year, month)
    last_seen = inicio_ciclo + timedelta(seconds=use_seconds)  # uso < 24h ⇒ efímero
    created_at = inicio_ciclo

    secuencia = _simulate_sequence(
        created_at=created_at,
        billing_cycle_started_at=inicio_ciclo,
        last_seen=last_seen,
        start_year=year,
        start_month=month,
        num_closures=3,
    )

    assert secuencia == [BILLABLE, RECYCLED, RECYCLED], (
        f"Uso efímero en {year}-{month:02d} (uso={use_seconds}s) debería dar "
        f"[billable, recycled, recycled] en M, M+1, M+2; se obtuvo {secuencia}."
    )


@settings(max_examples=100, deadline=None)
@given(
    year=year_strategy,
    month=month_strategy,
    use_seconds=normal_use_strategy,
)
def test_uso_normal_secuencia_billable_billable_recycled(
    year: int, month: int, use_seconds: int
):
    """
    Req 14.1 — Con `+1/0/-1` y umbral 24h, una workstation de uso NORMAL en M (intervalo
    `last_seen - billing_cycle_started_at` >= 24h) y sin uso en M+1/M+2 produce la secuencia
    de estados `billable` (M), `billable` (M+1), `recycled` (M+2).

    En M+1 NO recicla (uso >= umbral ⇒ no es Caso 1) y `last_seen` aún es >= cut2(M+1)=inicio
    de M; en M+2 recicla por Caso 2 (abandono), pues `last_seen` (en M) < cut2(M+2)=inicio de M+1.
    El ciclo arranca el día 1 de M a las 00:00 y el uso se acota a <=27 días para que `last_seen`
    quede dentro de M (el escenario exige "sin uso en M+1 ni M+2").

    **Validates: Requirements 14.1, 18.4**
    """
    inicio_ciclo = _month_start(year, month)
    last_seen = inicio_ciclo + timedelta(seconds=use_seconds)  # uso >= 24h ⇒ normal
    created_at = inicio_ciclo

    secuencia = _simulate_sequence(
        created_at=created_at,
        billing_cycle_started_at=inicio_ciclo,
        last_seen=last_seen,
        start_year=year,
        start_month=month,
        num_closures=3,
    )

    assert secuencia == [BILLABLE, BILLABLE, RECYCLED], (
        f"Uso normal en {year}-{month:02d} (uso={use_seconds}s) debería dar "
        f"[billable, billable, recycled] en M, M+1, M+2; se obtuvo {secuencia}."
    )


@settings(max_examples=100, deadline=None)
@given(
    year=year_strategy,
    month=month_strategy,
    day=st.integers(min_value=1, max_value=28),
    hour=hour_strategy,
    ephemeral=st.booleans(),
    x=reentry_offset_strategy,
)
def test_actividad_en_M_mas_x_marca_billable(
    year: int, month: int, day: int, hour: int, ephemeral: bool, x: int
):
    """
    Req 13.2 / 14.2 — Con `+1/0/-1`, si una workstation (de uso efímero o normal en M) registra
    actividad en `M+x` con `x > 2`, el cierre de `M+x` la marca como `billable`.

    Modelo: la reactivación por actividad reinicia el ciclo (`billing_cycle_started_at = last_seen`
    de la nueva actividad, Req 18.3). Para el cierre de `M+x`, con ese `last_seen` situado en M+x,
    la decisión pura NO recicla: `last_seen >= cut1(M+x)=inicio de M+x` ⇒ no es Caso 1 ni Caso 2.
    Por tanto la ws (ya reactivada a `billable`) permanece `billable` en `M+x`.

    **Validates: Requirements 13.2, 14.2**
    """
    inicio_ciclo_original = datetime(year, month, day, hour, 0, 0)
    if ephemeral:
        last_seen_original = inicio_ciclo_original + timedelta(hours=1)  # efímero
    else:
        last_seen_original = inicio_ciclo_original + timedelta(days=10)  # normal

    # Nueva actividad en M+x (x>2): reinicia el ciclo y actualiza last_seen a ese instante.
    reentry_year, reentry_month = _shift_month(year, month, x)
    actividad_reingreso = datetime(reentry_year, reentry_month, min(day, 28), hour, 0, 0)

    # La decisión pura para el cierre de M+x con el ciclo reiniciado a la nueva actividad.
    reciclar = _decide(
        billing_cycle_started_at=actividad_reingreso,
        last_seen=actividad_reingreso,
        y=reentry_year,
        m=reentry_month,
    )

    assert reciclar is False, (
        f"Con actividad en M+{x} ({reentry_year}-{reentry_month:02d}), la decisión pura no "
        f"debería reciclar (permanece billable); pero devolvió reciclar=True. "
        f"(ephemeral={ephemeral})"
    )

    # Verificación complementaria del comportamiento anterior a la reactivación: sin nueva
    # actividad, la ws original (efímera o normal) SÍ estaría reciclada en M+x (x>2), lo que
    # confirma que es la actividad de M+x —y no el paso del tiempo— la que la vuelve billable.
    reciclar_sin_actividad = _decide(
        billing_cycle_started_at=inicio_ciclo_original,
        last_seen=last_seen_original,
        y=reentry_year,
        m=reentry_month,
    )
    assert reciclar_sin_actividad is True, (
        f"Sin nueva actividad, una ws de M debería estar reciclada en M+{x} (x>2); "
        f"la decisión pura devolvió reciclar=False. (ephemeral={ephemeral})"
    )
