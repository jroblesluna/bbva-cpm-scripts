# Feature: recycle-policy-config, Property 6: Un cambio de política que afectaría periodos ya cerrados se rechaza y no se persiste
"""
Property test de la Property 6 (conflicto con cierres existentes).

*For any* `Effective_From_Period` propuesto (identificado por su `effective_key`) cuyo scope
(Org_Override o Global_Default) contenga al menos un periodo `M` con `period_key(M) >=
effective_key` que YA tiene un `BillingClosure` afectado,
`RecyclePolicyService.assert_no_closed_periods_affected(db, org_id_or_None, effective_key)`
DEBE:

    1. Lanzar `ClosedPeriodConflictError` (fail-closed, Req 5.3).
    2. NO persistir/mutar el estado de la BD (ni cierres ni políticas cambian tras el raise).

Y en el caso negativo (`effective_key` estrictamente mayor que TODOS los `period_key` de los
cierres del scope), NO debe lanzar y tampoco mutar estado.

Semántica por scope (ver `assert_no_closed_periods_affected` y design "Conflicto con cierres
existentes", Req 5.3):

    - Override (`org_id` seteado): conflictúan los cierres de ESA organización con
      `period_key >= effective_key`.
    - Global (`org_id` None): conflictúan los cierres de organizaciones que NO tienen un
      Org_Override PROPIO vigente (`effective_key_override <= period_key`) en ese periodo. Una
      org con override propio vigente resuelve por su override y NO se ve afectada por el
      cambio global.

Este test SÍ toca la base de datos (SQLite in-memory, tipo GUID compat) porque el método
consulta `billing_closures` y `billing_recycle_policies` persistidos; cada iteración de
Hypothesis usa una sesión aislada (engine nuevo con StaticPool) para independencia total.

**Validates: Requirements 5.3**
"""

from contextlib import contextmanager
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base

# Importar todos los modelos para que Base.metadata.create_all() cree TODAS las tablas
# (FKs de billing_recycle_policies/billing_closures -> organizations/users).
import app.models  # noqa: F401 - Registra todas las tablas en metadata
from app.models.billing import BillingClosure, BillingRecyclePolicy
from app.models.organization import Organization
from app.services.recycle_policy_service import (
    ClosedPeriodConflictError,
    recycle_policy_service,
)


# === HELPER: SESIÓN DE BASE DE DATOS EN MEMORIA ===

@contextmanager
def create_test_session():
    """
    Crea una sesión SQLite in-memory aislada con el esquema completo.

    Cada invocación crea un engine nuevo con todas las tablas (StaticPool para compartir la
    misma conexión in-memory dentro de la sesión), garantizando aislamiento total entre
    iteraciones de Hypothesis. Mismo setup que test_recycle_duplicate_effective_period.py.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _period_from_key(period_key: int) -> tuple:
    """Reconstruye (año, mes) desde `period_key = year*12 + (month-1)`."""
    year = period_key // 12
    month = (period_key % 12) + 1
    return year, month


def _make_closure(org_id, period_year, period_month) -> BillingClosure:
    """
    Construye un `BillingClosure` mínimo válido (todas las columnas NOT NULL) para un periodo.

    Los valores de totales/monto/tiers son irrelevantes para el conflicto (que solo mira el
    periodo y el scope), pero deben satisfacer las restricciones NOT NULL del modelo.
    """
    from datetime import datetime

    return BillingClosure(
        organization_id=org_id,
        period_year=period_year,
        period_month=period_month,
        cutoff_at=datetime(period_year, period_month, 1),
        mode="monthly",
        timezone="UTC",
        total_billable=0,
        total_recycled=0,
        total_archived=0,
        amount=Decimal("0.00"),
        tiers_applied={},
        recycle_policy_applied={
            "cutoff": 1,
            "cut1": -2,
            "cut2": -3,
            "ephemeral_hours": 24,
        },
    )


def _snapshot_closures(db) -> list:
    """Estado observable de `billing_closures` como lista ordenada de tuplas."""
    rows = db.query(BillingClosure).all()
    snap = [
        (
            str(r.id),
            str(r.organization_id),
            r.period_year,
            r.period_month,
        )
        for r in rows
    ]
    snap.sort()
    return snap


def _snapshot_policies(db) -> list:
    """Estado observable de `billing_recycle_policies` como lista ordenada de tuplas."""
    rows = db.query(BillingRecyclePolicy).all()
    snap = [
        (
            str(r.id),
            None if r.organization_id is None else str(r.organization_id),
            r.effective_key,
        )
        for r in rows
    ]
    snap.sort()
    return snap


# === ESTRATEGIAS ===

# Periodo efectivo propuesto: se ancla a una effective_key base y los cierres se colocan
# relativos a ella (por encima => conflicto; por debajo => sin conflicto).
_years = st.integers(min_value=2100, max_value=2800)
_months = st.integers(min_value=1, max_value=12)

# Cuántos periodos POR ENCIMA (o igual) de effective_key colocar cierres afectados.
_num_affected = st.integers(min_value=1, max_value=4)
# Distancia por encima de effective_key (>=0 => afectado por la semántica period_key >= eff).
_above_delta = st.integers(min_value=0, max_value=48)
# Distancia estrictamente por debajo de effective_key (no afectado).
_below_delta = st.integers(min_value=1, max_value=48)


# =============================================================================
# CASO OVERRIDE (org_id seteado)
# =============================================================================

@settings(max_examples=100)
@given(
    eff_year=_years,
    eff_month=_months,
    # unique=True: distintos period_keys evitan colisionar con el UniqueConstraint
    # (organization_id, period_year, period_month) del BillingClosure.
    above_deltas=st.lists(_above_delta, min_size=1, max_size=4, unique=True),
)
def test_override_change_affecting_closed_period_is_rejected(
    eff_year, eff_month, above_deltas
):
    """
    Override: al menos un cierre de ESA org con period_key >= effective_key => rechazo sin mutar.
    """
    effective_key = recycle_policy_service.period_key(eff_year, eff_month)

    with create_test_session() as db:
        org = Organization(name="Org-Override", timezone="UTC")
        db.add(org)
        db.commit()
        db.refresh(org)

        for delta in above_deltas:
            pk = effective_key + delta
            year, month = _period_from_key(pk)
            db.add(_make_closure(org.id, year, month))
        db.commit()

        before_closures = _snapshot_closures(db)
        before_policies = _snapshot_policies(db)

        try:
            recycle_policy_service.assert_no_closed_periods_affected(
                db, org.id, effective_key
            )
            raised = False
        except ClosedPeriodConflictError:
            raised = True

        assert raised, (
            "assert_no_closed_periods_affected debió lanzar ClosedPeriodConflictError: existe "
            f"al menos un cierre de la org con period_key >= effective_key={effective_key}."
        )

        db.expire_all()
        assert _snapshot_closures(db) == before_closures, (
            "El estado de billing_closures cambió tras el rechazo (fail-closed, Req 5.3)."
        )
        assert _snapshot_policies(db) == before_policies, (
            "El estado de billing_recycle_policies cambió tras el rechazo (fail-closed, Req 5.3)."
        )


@settings(max_examples=100)
@given(
    eff_year=_years,
    eff_month=_months,
    below_deltas=st.lists(_below_delta, min_size=1, max_size=4, unique=True),
)
def test_override_change_not_affecting_closed_periods_is_accepted(
    eff_year, eff_month, below_deltas
):
    """
    Override negativo: TODOS los cierres de la org tienen period_key < effective_key => no lanza
    y no muta estado.
    """
    effective_key = recycle_policy_service.period_key(eff_year, eff_month)

    with create_test_session() as db:
        org = Organization(name="Org-Override-OK", timezone="UTC")
        db.add(org)
        db.commit()
        db.refresh(org)

        for delta in below_deltas:
            pk = effective_key - delta
            if pk < 0:
                continue
            year, month = _period_from_key(pk)
            db.add(_make_closure(org.id, year, month))
        db.commit()

        before_closures = _snapshot_closures(db)
        before_policies = _snapshot_policies(db)

        # No debe lanzar: ningún cierre en period_key >= effective_key.
        recycle_policy_service.assert_no_closed_periods_affected(
            db, org.id, effective_key
        )

        db.expire_all()
        assert _snapshot_closures(db) == before_closures, (
            "billing_closures no debe mutar en el caso negativo (Req 5.3)."
        )
        assert _snapshot_policies(db) == before_policies, (
            "billing_recycle_policies no debe mutar en el caso negativo (Req 5.3)."
        )


# =============================================================================
# CASO GLOBAL (org_id None)
# =============================================================================

@settings(max_examples=100)
@given(
    eff_year=_years,
    eff_month=_months,
    above_deltas=st.lists(_above_delta, min_size=1, max_size=4, unique=True),
)
def test_global_change_affecting_org_without_override_is_rejected(
    eff_year, eff_month, above_deltas
):
    """
    Global: cierre de una org SIN override propio vigente con period_key >= effective_key =>
    rechazo sin mutar.
    """
    effective_key = recycle_policy_service.period_key(eff_year, eff_month)

    with create_test_session() as db:
        org = Organization(name="Org-Sin-Override", timezone="UTC")
        db.add(org)
        db.commit()
        db.refresh(org)

        for delta in above_deltas:
            pk = effective_key + delta
            year, month = _period_from_key(pk)
            db.add(_make_closure(org.id, year, month))
        db.commit()

        before_closures = _snapshot_closures(db)
        before_policies = _snapshot_policies(db)

        try:
            recycle_policy_service.assert_no_closed_periods_affected(
                db, None, effective_key
            )
            raised = False
        except ClosedPeriodConflictError:
            raised = True

        assert raised, (
            "assert_no_closed_periods_affected (global) debió lanzar ClosedPeriodConflictError: "
            "existe un cierre de una org sin override propio vigente con "
            f"period_key >= effective_key={effective_key}."
        )

        db.expire_all()
        assert _snapshot_closures(db) == before_closures, (
            "billing_closures cambió tras el rechazo global (fail-closed, Req 5.3)."
        )
        assert _snapshot_policies(db) == before_policies, (
            "billing_recycle_policies cambió tras el rechazo global (fail-closed, Req 5.3)."
        )


@settings(max_examples=100)
@given(
    eff_year=_years,
    eff_month=_months,
    above_delta=_above_delta,
    override_below_delta=st.integers(min_value=0, max_value=48),
)
def test_global_change_ignores_org_with_own_override(
    eff_year, eff_month, above_delta, override_below_delta
):
    """
    Global: una org CON override propio vigente (effective_key_override <= period_key del
    cierre) NO se ve afectada por el cambio global => ese cierre NO cuenta como conflicto.

    Se aíslan dos orgs:
      - orgA: cierre en period_key >= effective_key PERO con override propio vigente en ese
        periodo => NO debe marcar conflicto.
      - orgB (control): NINGÚN cierre => sin conflicto.

    Como orgA queda "cubierta" por su override, el chequeo global NO debe lanzar.
    """
    effective_key = recycle_policy_service.period_key(eff_year, eff_month)

    with create_test_session() as db:
        org_a = Organization(name="Org-Con-Override", timezone="UTC")
        db.add(org_a)
        db.commit()
        db.refresh(org_a)

        # Cierre de orgA en un periodo M >= effective_key.
        closure_pk = effective_key + above_delta
        c_year, c_month = _period_from_key(closure_pk)
        db.add(_make_closure(org_a.id, c_year, c_month))

        # Override propio de orgA vigente en ese periodo M: effective_key_override <= closure_pk.
        override_pk = closure_pk - override_below_delta
        if override_pk < 0:
            override_pk = 0
        o_year, o_month = _period_from_key(override_pk)
        db.add(
            BillingRecyclePolicy(
                organization_id=org_a.id,
                cutoff_offset=1,
                cut1_offset=0,
                cut2_offset=-1,
                ephemeral_hours=24,
                effective_from_year=o_year,
                effective_from_month=o_month,
                effective_key=override_pk,
            )
        )
        db.commit()

        before_closures = _snapshot_closures(db)
        before_policies = _snapshot_policies(db)

        # orgA está cubierta por su propio override vigente => el cambio global NO la afecta.
        recycle_policy_service.assert_no_closed_periods_affected(
            db, None, effective_key
        )

        db.expire_all()
        assert _snapshot_closures(db) == before_closures, (
            "billing_closures no debe mutar cuando la org tiene override propio (Req 5.3)."
        )
        assert _snapshot_policies(db) == before_policies, (
            "billing_recycle_policies no debe mutar cuando la org tiene override propio (Req 5.3)."
        )
