# Feature: recycle-policy-config, Property 13: created_at es invariante ante reactivación
"""
Property test de la invariancia de `created_at` ante la reactivación (Req 18.5).

`created_at` conserva su semántica histórica: NUNCA se modifica durante la reactivación
`recycled`/`archived → billable` (ni en ninguna otra actividad). `mark_activity` solo puede
reiniciar `billing_cycle_started_at` (Req 18.3), pero deja `created_at` intacto.

El test usa instancias ORM en memoria (`db=None`), igual que `tests/unit/test_last_seen_tracker.py`.
Genera un `created_at`, un `billing_cycle_started_at` previo y un `ts` de actividad
independientes con Hypothesis, cubre TODOS los estados iniciales (reactivables y no) y verifica
que, ocurra o no la reactivación, `created_at` permanece exactamente igual al valor previo.
Se comprueba además que en los casos de reactivación efectivamente `billing_status` cambió a
`billable` (para no dar un "pase gratis" a un test que nunca ejercita la transición).

**Validates: Requirements 18.5**
"""

from datetime import datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from app.models.workstation import Workstation
from app.services.last_seen_tracker import mark_activity


ALL_STATES = ["new", "billable", "recycled", "archived"]
REACTIVATABLE_STATES = {"recycled", "archived"}


# === ESTRATEGIAS DE GENERACIÓN ===

datetime_strategy = st.datetimes(
    min_value=datetime(2020, 1, 1, 0, 0, 0),
    max_value=datetime(2032, 12, 31, 23, 59, 59),
)

offset_seconds_strategy = st.integers(min_value=-10_000_000, max_value=10_000_000)


@settings(max_examples=100, deadline=None)
@given(
    estado_inicial=st.sampled_from(ALL_STATES),
    created_at=datetime_strategy,
    ciclo_offset=offset_seconds_strategy,
    actividad_offset=offset_seconds_strategy,
)
def test_created_at_no_cambia_ante_actividad(
    estado_inicial: str,
    created_at: datetime,
    ciclo_offset: int,
    actividad_offset: int,
):
    """
    Req 18.5 — `created_at` es invariante ante la actividad/reactivación: `mark_activity`
    nunca lo modifica, sin importar el estado inicial ni si hubo reactivación.

    **Validates: Requirements 18.5**
    """
    inicio_ciclo_previo = created_at + timedelta(seconds=ciclo_offset)
    ts = created_at + timedelta(seconds=actividad_offset)

    ws = Workstation(
        ip_private="10.0.0.1",
        billing_status=estado_inicial,
        created_at=created_at,
        billing_cycle_started_at=inicio_ciclo_previo,
    )

    mark_activity(db=None, ws=ws, ts=ts)

    assert ws.created_at == created_at, (
        f"created_at NO debe modificarse durante la actividad/reactivación (Req 18.5); "
        f"estado inicial={estado_inicial}, se esperaba {created_at!r} pero quedó "
        f"{ws.created_at!r}."
    )

    # Verificación de que los casos reactivables SÍ ejercitan la transición (evita un test
    # que "pase" porque nunca reactiva). Solo recycled/archived reactivan a billable.
    if estado_inicial in REACTIVATABLE_STATES:
        assert ws.billing_status == "billable", (
            f"El estado reactivable {estado_inicial} debió transicionar a 'billable' con "
            f"actividad (confirma que la invariancia de created_at se probó justo en la "
            f"reactivación)."
        )
