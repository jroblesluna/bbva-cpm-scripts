# Feature: recycle-policy-config, Property 5: Reproducibilidad e inmutabilidad del recálculo con política congelada
"""
Property test de `BillingCloseService.close_month` (task 4.3).

Verifica la Property 5 del diseño (recycle-policy-config): el recálculo mensual del cierre es
REPRODUCIBLE e INMUTABLE cuando la política está congelada (frozen policy).

Estrategia (siguiendo `design.md`, "Reproducibilidad (Property 5)"):

    1. Se genera un escenario: una `Organization` (tz UTC), un conjunto de workstations con
       `created_at`/`billing_cycle_started_at`/`last_seen` coherentes, y una política de
       reciclaje congelada. La política proviene de una fila `BillingRecyclePolicy` sembrada
       (Global_Default u Org_Override) o, si no se siembra ninguna, del fallback
       `LEGACY_POLICY` (`+1/-2/-3` + 24h). En ambos casos la misma política se aplica en las
       dos corridas (determinismo con política congelada, Req 10.2).
    2. Se corre el cierre mes a mes (secuencial desde el primer mes cerrable de la org) sobre
       SQLite en memoria; se captura, por periodo: el `amount` de cabecera, un snapshot
       CANÓNICO de cada `BillingClosure` (+ sus ítems) y el `billing_status` vivo por ws.
    3. Se borran TODOS los cierres (cabecera + ítems), se resetea `billing_status='new'` de
       cada ws y se restaura su `billing_cycle_started_at` original (el cierre no lo muta, pero
       el reset del estado vivo debe partir de las mismas condiciones que la primera corrida).
    4. Se re-corren los MISMOS cierres con la MISMA política congelada.
    5. Se asertan IDÉNTICOS entre corridas: el `billing_status` vivo resultante por ws, el
       `amount` de cada periodo, y el snapshot canónico byte-idéntico de cada cierre (mismo
       freeze `recycle_policy_applied`, mismos totales, mismos ítems).

El snapshot CANÓNICO excluye los campos NO deterministas por diseño (`id`, `created_at`,
`created_by_id` de la cabecera; `id`/`closure_id` de los ítems), que cambian entre corridas
por ser identificadores/marcas de tiempo de inserción, no parte del sustento recalculable.
Todo lo demás (política congelada, cortes, totales, montos, estado histórico por IP y aporte
por tramo) debe ser byte-idéntico.

Se usa la sesión SQLite in-memory y el seed de planes por defecto del patrón de
`tests/unit/test_billing_close_service.py` (`_make_session` + `seed_default_rate_plans`).

Nota de rendimiento: `close_month` es pesado (queries + flush + commit por periodo), así que
se acota `max_examples=25` con `deadline=None` (el diseño lo permite: "el costo se acota
usando pocos meses por caso"). Cada caso ejecuta 2 corridas × (2..4) meses de cierre real,
lo que ya ejercita el camino completo de resolución → freeze → recálculo miles de veces
agregando los ítems generados. La cota es un compromiso deliberado entre cobertura y tiempo
de ejecución del cierre real sobre BD.

**Validates: Requirements 4.1, 4.3, 5.1, 5.2, 10.2**
"""

import json
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
import app.models  # noqa: F401 — registra todas las tablas en metadata
from app.models.billing import (
    BillingClosure,
    BillingClosureItem,
    BillingRecyclePolicy,
)
from app.models.organization import Organization
from app.models.workstation import Workstation
from app.services.billing_close_service import billing_close_service
from app.services.billing_seed import seed_default_rate_plans
from app.services.recycle_policy_service import RecyclePolicyService


# === SESIÓN SQLITE IN-MEMORY (patrón de tests/unit/test_billing_close_service.py) ===


def _make_session():
    """Crea una sesión SQLite in-memory con el esquema completo y planes por defecto."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    # Los planes por defecto son necesarios para que resolve_plan calcule el monto mensual
    # (sin ellos close_month falla fail-closed con BillingRateResolutionError).
    seed_default_rate_plans(session.connection())
    session.commit()
    return session, engine


# === ESTRATEGIAS ===

# Mes base del escenario: se cierra un rango de meses consecutivos a partir de aquí. Se elige
# un año/mes cómodo (lejos de fronteras de año para simplificar la aritmética de offsets) pero
# el cierre real recalcula los cortes; la reproducibilidad no depende del mes concreto.
_BASE_YEAR = 2026

# Offsets legacy-compatibles y con signo válido (viajan íntegros por la política congelada).
# La generación mantiene el orden estricto cutoff > cut1 >= cut2 exigido por la semántica de
# cortes (no se valida aquí, pero valores incoherentes producirían cortes sin sentido).
_offset_cutoff = st.just(1)  # +1: alcance del recálculo (created_at < cutoff), legacy.
_cut1_strategy = st.integers(min_value=-2, max_value=0)
_cut2_strategy = st.integers(min_value=-4, max_value=-1)
_ephemeral_strategy = st.integers(min_value=1, max_value=72)


@st.composite
def _policy_strategy(draw):
    """
    Genera una política congelada coherente (`cutoff > cut1 >= cut2`) y decide si se siembra
    como fila `BillingRecyclePolicy` (scope global u override) o si se deja recaer en el
    fallback LEGACY. `seed_scope` ∈ {"legacy", "global", "org"}.
    """
    cutoff = draw(_offset_cutoff)
    cut1 = draw(_cut1_strategy)
    cut2 = draw(_cut2_strategy)
    # Forzar el orden estricto que exige la semántica de cortes: cutoff > cut1 >= cut2.
    if not (cutoff > cut1 >= cut2):
        cut1 = 0
        cut2 = -1
    ephemeral_hours = draw(_ephemeral_strategy)
    seed_scope = draw(st.sampled_from(["legacy", "global", "org"]))
    return {
        "cutoff": cutoff,
        "cut1": cut1,
        "cut2": cut2,
        "ephemeral_hours": ephemeral_hours,
        "seed_scope": seed_scope,
    }


@st.composite
def _workstations_strategy(draw):
    """
    Genera de 1 a 6 workstations con timestamps coherentes (naive UTC), abarcando los tres
    desenlaces posibles del recálculo (billable estable, Caso 1 poco uso, Caso 2 abandono).

    Cada ws se describe por offsets EN DÍAS relativos a un ancla temporal fija dentro del
    rango de meses que se cerrará, de modo que la generación cubre actividad reciente, uso
    corto y abandono. El cierre real deriva el estado; el test no lo predice, solo exige que
    sea el MISMO en ambas corridas.
    """
    n = draw(st.integers(min_value=1, max_value=6))
    specs = []
    for i in range(n):
        # created_at: entre ~120 y ~10 días antes del ancla (garantiza created_at < cutoff en
        # los meses cerrados y un primer periodo cerrable estable).
        created_days_before = draw(st.integers(min_value=10, max_value=120))
        # uso del ciclo (last_seen - billing_cycle_started_at) en horas: cubre uso corto
        # (<umbral, candidato Caso 1) y uso largo.
        use_hours = draw(st.integers(min_value=1, max_value=240))
        # inactividad: cuántos días antes del ancla quedó el last_seen (cubre abandono Caso 2
        # y actividad reciente).
        last_seen_days_before = draw(st.integers(min_value=0, max_value=115))
        specs.append(
            {
                "index": i,
                "created_days_before": created_days_before,
                "use_hours": use_hours,
                "last_seen_days_before": last_seen_days_before,
            }
        )
    return specs


# Número de meses consecutivos a cerrar (acotado: close_month es pesado).
_months_strategy = st.integers(min_value=2, max_value=4)


# === HELPERS DE ESCENARIO ===


def _anchor() -> datetime:
    """Ancla temporal fija: 1 de julio del año base, mediodía (lejos de medianoche/fronteras)."""
    return datetime(_BASE_YEAR, 7, 1, 12, 0, 0)


def _seed_scenario(session, org, ws_specs, policy_spec):
    """
    Siembra la política (según scope) y las workstations del escenario. Devuelve la lista de
    `Workstation` insertadas (con sus `billing_cycle_started_at` originales para el reset).
    """
    anchor = _anchor()

    # ── Política congelada: fila BillingRecyclePolicy (global/org) o fallback legacy ──
    if policy_spec["seed_scope"] != "legacy":
        organization_id = org.id if policy_spec["seed_scope"] == "org" else None
        # Vigente desde el año 2000 para cubrir todos los meses cerrados del escenario.
        eff_year, eff_month = 2000, 1
        session.add(
            BillingRecyclePolicy(
                id=uuid.uuid4(),
                organization_id=organization_id,
                cutoff_offset=policy_spec["cutoff"],
                cut1_offset=policy_spec["cut1"],
                cut2_offset=policy_spec["cut2"],
                ephemeral_hours=policy_spec["ephemeral_hours"],
                effective_from_year=eff_year,
                effective_from_month=eff_month,
                effective_key=RecyclePolicyService.period_key(eff_year, eff_month),
            )
        )

    # ── Workstations ──
    workstations = []
    for spec in ws_specs:
        created_at = anchor - timedelta(days=spec["created_days_before"])
        last_seen = anchor - timedelta(days=spec["last_seen_days_before"])
        # billing_cycle_started_at se posiciona `use_hours` antes del last_seen para fijar el
        # "uso del ciclo" de forma determinista; se acota a >= created_at (nunca antes del alta).
        cycle_start = last_seen - timedelta(hours=spec["use_hours"])
        if cycle_start < created_at:
            cycle_start = created_at
        ws = Workstation(
            id=uuid.uuid4(),
            organization_id=org.id,
            ip_private=f"10.200.{spec['index']}.1",
            created_at=created_at,
            first_seen=created_at,
            last_seen=last_seen,
            billing_status="new",
            is_online=False,
            billing_cycle_started_at=cycle_start,
        )
        session.add(ws)
        workstations.append(ws)

    session.commit()
    for ws in workstations:
        session.refresh(ws)
    return workstations


def _closable_range(session, org, num_months):
    """
    Devuelve la lista de `(year, month)` a cerrar: `num_months` meses consecutivos desde el
    primer mes cerrable de la org (el `created_at` más antiguo de una IP). Respeta la
    secuencialidad (Req 7.4) por construcción.
    """
    first = billing_close_service._org_first_period(session, org)
    assert first is not None, "la org debe tener al menos una IP para cerrar"
    idx = first[0] * 12 + (first[1] - 1)
    periods = []
    for _ in range(num_months):
        y, m0 = divmod(idx, 12)
        periods.append((y, m0 + 1))
        idx += 1
    return periods


def _canonical_closure(session, closure):
    """
    Serialización CANÓNICA de un cierre (cabecera + ítems) para comparación byte-a-byte.

    Excluye los campos NO deterministas por diseño (identificadores y marcas de inserción):
    `id`, `created_at`, `created_by_id` de la cabecera; `id`/`closure_id` de los ítems. Los
    ítems se ordenan por `ip_private` para independizar del orden de inserción. Los `Decimal`
    y `datetime` se normalizan a texto para una comparación estable.
    """
    items = (
        session.query(BillingClosureItem)
        .filter(BillingClosureItem.closure_id == closure.id)
        .all()
    )
    items_canon = sorted(
        (
            {
                "ip_private": it.ip_private,
                "created_at_ws": it.created_at_ws.isoformat(),
                "last_seen_capped": it.last_seen_capped.isoformat(),
                "billing_status": it.billing_status,
                "tier_index": it.tier_index,
                "amount": str(it.amount),
            }
            for it in items
        ),
        key=lambda d: d["ip_private"],
    )
    header = {
        "period_year": closure.period_year,
        "period_month": closure.period_month,
        "cutoff_at": closure.cutoff_at.isoformat(),
        "mode": closure.mode,
        "timezone": closure.timezone,
        "total_billable": closure.total_billable,
        "total_recycled": closure.total_recycled,
        "total_archived": closure.total_archived,
        "amount": str(closure.amount),
        "tiers_applied": closure.tiers_applied,
        "is_retroactive": closure.is_retroactive,
        "recycle_policy_applied": closure.recycle_policy_applied,
        "items": items_canon,
    }
    # json con sort_keys para obtener una representación byte-estable.
    return json.dumps(header, sort_keys=True)


def _run_all_closures(session, org, periods):
    """
    Cierra secuencialmente los `periods` y devuelve:
      - `amounts`: dict {(year, month): Decimal amount}
      - `snapshots`: dict {(year, month): str canonical}
    """
    amounts = {}
    snapshots = {}
    for year, month in periods:
        closure = billing_close_service.close_month(session, org, year, month)
        amounts[(year, month)] = closure.amount
        snapshots[(year, month)] = _canonical_closure(session, closure)
    return amounts, snapshots


def _live_states(session, org):
    """Devuelve {ip_private: billing_status vivo} de todas las ws de la org (orden estable)."""
    session.expire_all()
    rows = (
        session.query(Workstation)
        .filter(Workstation.organization_id == org.id)
        .all()
    )
    return {ws.ip_private: ws.billing_status for ws in rows}


def _reset_for_recompute(session, org, original_cycle_starts):
    """
    Prepara la segunda corrida: borra todos los cierres (cabecera + ítems) y resetea las ws a
    las condiciones iniciales (`billing_status='new'`, `billing_cycle_started_at` original).

    El cierre no muta `billing_cycle_started_at` (el reset del ciclo vive en
    `last_seen_tracker`, no en `close_month`), pero se restaura explícitamente para garantizar
    que la segunda corrida parte de un estado idéntico al de la primera.
    """
    # Borrar ítems primero (FK), luego cabeceras. Se filtra por closures de la org.
    closure_ids = [
        row.id
        for row in session.query(BillingClosure.id)
        .filter(BillingClosure.organization_id == org.id)
        .all()
    ]
    if closure_ids:
        session.query(BillingClosureItem).filter(
            BillingClosureItem.closure_id.in_(closure_ids)
        ).delete(synchronize_session=False)
        session.query(BillingClosure).filter(
            BillingClosure.organization_id == org.id
        ).delete(synchronize_session=False)

    for ws in (
        session.query(Workstation)
        .filter(Workstation.organization_id == org.id)
        .all()
    ):
        ws.billing_status = "new"
        ws.billing_cycle_started_at = original_cycle_starts[ws.ip_private]

    session.commit()


# === PROPERTY TEST ===


@settings(max_examples=25, deadline=None)
@given(
    ws_specs=_workstations_strategy(),
    policy_spec=_policy_strategy(),
    num_months=_months_strategy,
)
def test_recalculo_reproducible_e_inmutable_con_politica_congelada(
    ws_specs, policy_spec, num_months
):
    """
    Property 5 — Correr el cierre mes a mes, borrar los cierres, resetear `billing_status` a
    `new` y recalcular con la MISMA política congelada reproduce de forma idéntica:

        - el `billing_status` vivo resultante por workstation,
        - el `amount` de cada periodo, y
        - el `BillingClosure` completo (freeze + totales + ítems) byte-a-byte.

    Esto valida el determinismo del recálculo con la política congelada (Req 10.2) y la
    inmutabilidad del sustento (Req 4.1/4.3/5.1/5.2).

    **Validates: Requirements 4.1, 4.3, 5.1, 5.2, 10.2**
    """
    session, engine = _make_session()
    org = Organization(
        id=uuid.uuid4(),
        name="Org Reproducibilidad",
        timezone="UTC",
        billing_mode="monthly",
    )
    session.add(org)
    session.commit()

    try:
        workstations = _seed_scenario(session, org, ws_specs, policy_spec)
        original_cycle_starts = {
            ws.ip_private: ws.billing_cycle_started_at for ws in workstations
        }

        periods = _closable_range(session, org, num_months)

        # ── Corrida 1 ──
        amounts_1, snapshots_1 = _run_all_closures(session, org, periods)
        live_1 = _live_states(session, org)

        # ── Reset a condiciones iniciales ──
        _reset_for_recompute(session, org, original_cycle_starts)

        # ── Corrida 2 (misma política congelada) ──
        amounts_2, snapshots_2 = _run_all_closures(session, org, periods)
        live_2 = _live_states(session, org)

        # ── Aserciones de reproducibilidad ──
        assert live_1 == live_2, (
            "El billing_status vivo por workstation difiere entre corridas: "
            f"{live_1} vs {live_2}."
        )
        for period in periods:
            assert amounts_1[period] == amounts_2[period], (
                f"El amount del periodo {period} difiere entre corridas: "
                f"{amounts_1[period]} vs {amounts_2[period]}."
            )
            assert snapshots_1[period] == snapshots_2[period], (
                f"El snapshot canónico del cierre {period} no es byte-idéntico entre "
                f"corridas (freeze/totales/ítems)."
            )
    finally:
        session.close()
        engine.dispose()


# === EJEMPLO DIRIGIDO (complementa la property con un escenario concreto y legible) ===


def test_ejemplo_recalculo_reproducible_legacy():
    """
    Ejemplo concreto (política LEGACY `+1/-2/-3` + 24h): una ws activa que permanece billable
    y una ws abandonada que recicla (Caso 2). Se cierran 3 meses, se resetea y se recalcula;
    el estado vivo y los cierres deben ser idénticos.
    """
    session, engine = _make_session()
    org = Organization(
        id=uuid.uuid4(),
        name="Org Ejemplo",
        timezone="UTC",
        billing_mode="monthly",
    )
    session.add(org)
    session.commit()

    try:
        # ws activa: created_at en marzo, last_seen reciente en mayo → billable estable.
        ws_activa = Workstation(
            id=uuid.uuid4(),
            organization_id=org.id,
            ip_private="10.201.0.1",
            created_at=datetime(2026, 3, 5, 12, 0, 0),
            first_seen=datetime(2026, 3, 5, 12, 0, 0),
            last_seen=datetime(2026, 5, 20, 12, 0, 0),
            billing_status="new",
            is_online=False,
            billing_cycle_started_at=datetime(2026, 3, 5, 12, 0, 0),
        )
        # ws abandonada: created_at en marzo, last_seen muy antiguo (mediados de marzo) →
        # al cerrar mayo, last_seen < cut2 (feb? no; con legacy cut2 de mayo = 00:00 feb) —
        # se deja que el cierre lo derive; solo importa que sea reproducible.
        ws_abandonada = Workstation(
            id=uuid.uuid4(),
            organization_id=org.id,
            ip_private="10.201.0.2",
            created_at=datetime(2026, 3, 6, 12, 0, 0),
            first_seen=datetime(2026, 3, 6, 12, 0, 0),
            last_seen=datetime(2026, 3, 7, 6, 0, 0),  # uso ~18h, abandono temprano
            billing_status="new",
            is_online=False,
            billing_cycle_started_at=datetime(2026, 3, 6, 12, 0, 0),
        )
        session.add_all([ws_activa, ws_abandonada])
        session.commit()

        original = {
            "10.201.0.1": ws_activa.billing_cycle_started_at,
            "10.201.0.2": ws_abandonada.billing_cycle_started_at,
        }

        periods = _closable_range(session, org, 3)

        amounts_1, snapshots_1 = _run_all_closures(session, org, periods)
        live_1 = _live_states(session, org)

        _reset_for_recompute(session, org, original)

        amounts_2, snapshots_2 = _run_all_closures(session, org, periods)
        live_2 = _live_states(session, org)

        assert live_1 == live_2
        for period in periods:
            assert amounts_1[period] == amounts_2[period]
            assert snapshots_1[period] == snapshots_2[period]
    finally:
        session.close()
        engine.dispose()
