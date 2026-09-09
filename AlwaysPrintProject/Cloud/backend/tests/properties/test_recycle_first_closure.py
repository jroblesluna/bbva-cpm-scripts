# Feature: recycle-policy-config, Property 10: Facturación garantizada en el primer cierre
"""
Property test de la Property 10 (facturación garantizada en el primer cierre).

*For any* workstation nueva en su primer periodo de cierre `M`, el estado resultante del
cierre es `billable`; nunca es `recycled` en ese primer periodo. Es decir,
`decide_recycle(inputs, año, M)` DEBE devolver `False` cuando la workstation vio su primera
actividad dentro de `M`.

Modelado del "primer cierre" (ver AGENTS/design):
    - `created_at` cae dentro del periodo M (mes lógico M en la timezone de la organización).
    - `billing_cycle_started_at == created_at` (Property 11: al alta se inicializa igual).
    - `last_seen >= billing_cycle_started_at` y también dentro de M (la workstation solo ha
      tenido actividad en su primer periodo).

Por qué NO recicla en M:
    - `decide_recycle` recicla por Caso 2 (abandono) si `last_seen < cut2`, o por Caso 1
      (poco uso) si `last_seen < cut1`. Con la política de reciclaje real los offsets `cut1`
      y `cut2` son <= 0, de modo que `cut1` y `cut2` son el inicio (00:00 día 1) de un mes
      anterior o igual a M en la timezone de la org. Como `last_seen` está dentro de M
      (>= 00:00 día 1 de M local), se cumple `last_seen >= cut1 > cut2`, ninguna rama de
      reciclaje aplica y la decisión es `False` → `billable`.

Este test NO toca la base de datos ni el reloj de pared: ejercita la función pura
`decide_recycle` (Req 10.2/10.3), coherente con cómo el motor de cierre deriva los cortes.

**Validates: Requirements 15.1, 15.2**
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.billing_time import _local_month_start_utc_naive, _shift_month
from app.services.recycle_decision import RecycleInputs, decide_recycle


# === POLÍTICA CONGELADA (stub por duck typing) ===
#
# `ResolvedRecyclePolicy` (task 3.1) aún no existe; `decide_recycle` accede a la política por
# duck typing (`cut1`, `cut2`, `ephemeral_hours`). Un frozen dataclass mínimo con esos tres
# atributos es un doble fiel del contrato que consume la función pura.
@dataclass(frozen=True)
class _FrozenPolicy:
    cutoff: int
    cut1: int
    cut2: int
    ephemeral_hours: int


# Zonas IANA representativas: sin DST (Lima, UTC) y con DST (Madrid). Cubre el cálculo de
# cortes en distintas timezones de organización.
TIMEZONES = ["America/Lima", "Europe/Madrid", "UTC"]

# Políticas de reciclaje reales del sistema: legacy Global_Default (+1/-2/-3) y el override
# BBVA (+1/0/-1). Ambas tienen cut1 <= 0 y cut2 <= 0, condición necesaria para que un
# `last_seen` dentro de M nunca caiga antes de cut1/cut2.
POLICIES = [
    _FrozenPolicy(cutoff=1, cut1=-2, cut2=-3, ephemeral_hours=24),  # legacy
    _FrozenPolicy(cutoff=1, cut1=0, cut2=-1, ephemeral_hours=24),   # BBVA override
]


@settings(max_examples=100)
@given(
    year=st.integers(min_value=2024, max_value=2030),
    month=st.integers(min_value=1, max_value=12),
    timezone_name=st.sampled_from(TIMEZONES),
    policy=st.sampled_from(POLICIES),
    # Offset de created_at dentro del mes M (desde el inicio local del mes, en segundos).
    # Cota superior 27 días para no salir de M ni en meses de 28 días.
    created_offset_seconds=st.integers(min_value=0, max_value=27 * 24 * 3600),
    # Uso adicional (last_seen - billing_cycle_started_at) en segundos, dentro de M.
    usage_seconds=st.integers(min_value=0, max_value=24 * 3600),
)
def test_new_workstation_never_recycled_in_first_closure(
    year, month, timezone_name, policy, created_offset_seconds, usage_seconds
):
    """
    Una workstation cuya primera actividad ocurre dentro de M nunca se recicla al cerrar M.

    Se construyen timestamps coherentes con el primer cierre y se asserta que
    `decide_recycle(..., year, month)` devuelve `False` (billable).
    """
    # Inicio local (00:00 día 1) del periodo M, en UTC naive: mismo instante que usan los
    # cortes y con el que se comparan los timestamps de la workstation.
    m_start = _local_month_start_utc_naive(timezone_name, year, month)
    # Inicio local del mes siguiente (M+1): límite superior exclusivo del periodo M.
    next_year, next_month = _shift_month(year, month, 1)
    m_end = _local_month_start_utc_naive(timezone_name, next_year, next_month)

    # created_at dentro de M. billing_cycle_started_at = created_at (Property 11).
    created_at = m_start + timedelta(seconds=created_offset_seconds)
    billing_cycle_started_at = created_at

    # last_seen = created_at + uso, capado para permanecer dentro de M (primer cierre).
    last_seen = created_at + timedelta(seconds=usage_seconds)
    if last_seen >= m_end:
        last_seen = m_end - timedelta(seconds=1)

    # Coherencia del escenario "primer cierre": todo cae dentro de M y en orden.
    assert m_start <= created_at <= last_seen < m_end

    inputs = RecycleInputs(
        created_at=created_at,
        billing_cycle_started_at=billing_cycle_started_at,
        last_seen=last_seen,
        timezone=timezone_name,
        policy=policy,
    )

    # Property 10 (Req 15.1, 15.2): no se recicla en el primer cierre → billable.
    assert decide_recycle(inputs, year, month) is False
