# Feature: recycle-policy-config, Property 12: Reset condicional de billing_cycle_started_at solo en reactivación
"""
Property test del reset condicional de `billing_cycle_started_at` (Req 18.3).

`mark_activity(db, ws, ts)` (vía `_reactivate_if_needed`) reinicia
`billing_cycle_started_at = ts` ÚNICAMENTE en la transición `recycled`/`archived → billable`
por actividad. Para cualquier otra actividad (workstation ya `billable`, o `new` que no
reactiva) el campo NO se modifica.

El test trabaja con instancias ORM en memoria (sin sesión de BD, `db=None`), igual que
`tests/unit/test_last_seen_tracker.py`, porque `mark_activity` no hace commit ni consulta la
BD: solo muta atributos del objeto y consulta la máquina de estados (pura). Se generan estados
iniciales, un `billing_cycle_started_at` previo y un timestamp de actividad `ts` coherentes con
Hypothesis, y se verifica:

- Estados reactivables (`recycled`, `archived`): tras `mark_activity`, `billing_status` pasa a
  `billable` y `billing_cycle_started_at == ts` (se reinició).
- Estados NO reactivables (`billable`, `new`): tras `mark_activity`, `billing_cycle_started_at`
  conserva su valor previo (no se tocó).

**Validates: Requirements 18.3**
"""

from datetime import datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from app.models.workstation import Workstation
from app.services.last_seen_tracker import mark_activity


# Estados que reactivan a `billable` ante actividad (y por tanto reinician el ciclo).
REACTIVATABLE_STATES = ["recycled", "archived"]
# Estados que NO reactivan (no deben tocar `billing_cycle_started_at`).
NON_REACTIVATABLE_STATES = ["billable", "new"]


# === ESTRATEGIAS DE GENERACIÓN ===

# Timestamp base para el `billing_cycle_started_at` previo (naive UTC, como el modelo).
base_datetime_strategy = st.datetimes(
    min_value=datetime(2024, 1, 1, 0, 0, 0),
    max_value=datetime(2030, 12, 31, 23, 59, 59),
)

# Desplazamiento (en segundos) del ts de la actividad respecto al inicio previo del ciclo.
# Se permite tanto posterior como anterior/igual para no asumir monotonicidad: el reset
# debe fijar `ts` sea cual sea su relación con el valor previo.
offset_seconds_strategy = st.integers(min_value=-10_000_000, max_value=10_000_000)


@settings(max_examples=100, deadline=None)
@given(
    estado_inicial=st.sampled_from(REACTIVATABLE_STATES),
    inicio_ciclo_previo=base_datetime_strategy,
    offset=offset_seconds_strategy,
)
def test_reactivacion_reinicia_billing_cycle_started_at(
    estado_inicial: str, inicio_ciclo_previo: datetime, offset: int
):
    """
    Req 18.3 — En la transición `recycled`/`archived → billable` por actividad,
    `billing_cycle_started_at` se reinicia al timestamp de esa actividad (`ts`).

    **Validates: Requirements 18.3**
    """
    ts = inicio_ciclo_previo + timedelta(seconds=offset)

    ws = Workstation(
        ip_private="10.0.0.1",
        billing_status=estado_inicial,
        billing_cycle_started_at=inicio_ciclo_previo,
    )

    mark_activity(db=None, ws=ws, ts=ts)

    assert ws.billing_status == "billable", (
        f"Un estado reactivable ({estado_inicial}) debe pasar a 'billable' con actividad."
    )
    assert ws.billing_cycle_started_at == ts, (
        f"En la reactivación desde {estado_inicial}, billing_cycle_started_at debe reiniciarse "
        f"al ts de la actividad ({ts!r}); se obtuvo {ws.billing_cycle_started_at!r} "
        f"(previo era {inicio_ciclo_previo!r})."
    )


@settings(max_examples=100, deadline=None)
@given(
    estado_inicial=st.sampled_from(NON_REACTIVATABLE_STATES),
    inicio_ciclo_previo=base_datetime_strategy,
    offset=offset_seconds_strategy,
)
def test_actividad_normal_no_toca_billing_cycle_started_at(
    estado_inicial: str, inicio_ciclo_previo: datetime, offset: int
):
    """
    Req 18.3 (cláusula negativa) — La actividad que NO corresponde a una transición
    `recycled`/`archived → billable` (estados `billable`/`new`) NO modifica
    `billing_cycle_started_at`.

    **Validates: Requirements 18.3**
    """
    ts = inicio_ciclo_previo + timedelta(seconds=offset)

    ws = Workstation(
        ip_private="10.0.0.1",
        billing_status=estado_inicial,
        billing_cycle_started_at=inicio_ciclo_previo,
    )

    mark_activity(db=None, ws=ws, ts=ts)

    assert ws.billing_cycle_started_at == inicio_ciclo_previo, (
        f"La actividad normal en estado {estado_inicial} NO debe tocar "
        f"billing_cycle_started_at; se esperaba {inicio_ciclo_previo!r} pero quedó "
        f"{ws.billing_cycle_started_at!r}."
    )
