# Feature: recycle-policy-config, Property 4: Periodos efectivos duplicados en el mismo scope se rechazan sin mutar estado
"""
Property test de la Property 4 (periodos efectivos duplicados en el mismo scope).

*For any* par de filas `BillingRecyclePolicy` del MISMO scope (Global_Default u Org_Override)
que comparten idéntica `effective_key` en el tope aplicable (empate en el máximo `<= M_key`),
`RecyclePolicyService.resolve_recycle_policy(db, org, year, month)` DEBE:

    1. Lanzar `RecyclePolicyResolutionError` (fail-closed, Req 3.3).
    2. NO mutar el estado de la BD: ni el número de filas ni sus valores cambian tras el raise.

Modelado del empate en el tope:
    - Se insertan DOS filas con la MISMA `effective_key` (mismo año-mes efectivo), ambas
      `<= M_key`, dentro del mismo scope. Al ser el máximo `effective_key` aplicable y estar
      empatadas, la resolución es ambigua => se rechaza sin mutar estado.
    - Se puede añadir opcionalmente una tercera fila con `effective_key` estrictamente menor
      (misma scope) para asegurar que el empate ocurre en el TOPE y no en cualquier posición.

Alcance parametrizado:
    - scope="global": ambas filas con `organization_id IS NULL`.
    - scope="org": ambas filas con `organization_id == org.id`.

Este test SÍ toca la base de datos (SQLite in-memory, tipo GUID compat) porque
`resolve_recycle_policy` consulta filas persistidas; cada iteración de Hypothesis usa una
sesión aislada (engine nuevo con StaticPool) para garantizar independencia.

**Validates: Requirements 3.3**
"""

from contextlib import contextmanager

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base

# Importar todos los modelos para que Base.metadata.create_all() cree TODAS las tablas
# (FKs de billing_recycle_policies -> organizations/users).
import app.models  # noqa: F401 - Registra todas las tablas en metadata
from app.models.billing import BillingRecyclePolicy
from app.models.organization import Organization
from app.services.recycle_policy_service import (
    RecyclePolicyResolutionError,
    recycle_policy_service,
)


# === HELPER: SESIÓN DE BASE DE DATOS EN MEMORIA ===

@contextmanager
def create_test_session():
    """
    Crea una sesión SQLite in-memory aislada con el esquema completo.

    Cada invocación crea un engine nuevo con todas las tablas (StaticPool para compartir la
    misma conexión in-memory dentro de la sesión), garantizando aislamiento total entre
    iteraciones de Hypothesis.
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


def _period_from_key(effective_key: int) -> tuple:
    """Reconstruye (año, mes) desde una `effective_key = year*12 + (month-1)`."""
    year = effective_key // 12
    month = (effective_key % 12) + 1
    return year, month


def _snapshot(db) -> list:
    """
    Captura el estado observable de `billing_recycle_policies` como lista ordenada y
    determinista de tuplas de valores, para comparar antes/después del raise.
    """
    rows = db.query(BillingRecyclePolicy).all()
    snap = [
        (
            str(r.id),
            None if r.organization_id is None else str(r.organization_id),
            r.cutoff_offset,
            r.cut1_offset,
            r.cut2_offset,
            r.ephemeral_hours,
            r.effective_from_year,
            r.effective_from_month,
            r.effective_key,
        )
        for r in rows
    ]
    snap.sort()
    return snap


# === ESTRATEGIAS ===

# Periodo del cierre M: años dentro del rango de negocio (2000..2999), mes 1..12.
_years = st.integers(min_value=2001, max_value=2900)
_months = st.integers(min_value=1, max_value=12)

# Offsets legacy plausibles (dentro de los rangos de validación del diseño).
_cutoff = st.integers(min_value=1, max_value=1)
_cut1 = st.integers(min_value=-12, max_value=0)
_cut2 = st.integers(min_value=-24, max_value=-1)
_ephemeral = st.integers(min_value=1, max_value=168)


@settings(max_examples=100)
@given(
    year=_years,
    month=_months,
    scope=st.sampled_from(["global", "org"]),
    # Distancia (en claves) del empate por debajo de M_key: 0 => empate exactamente en M.
    tie_delta=st.integers(min_value=0, max_value=60),
    # Si añadir una tercera fila estrictamente por debajo del empate (mismo scope), para
    # forzar que el empate ocurra en el TOPE aplicable y no en una posición inferior.
    add_lower_row=st.booleans(),
    lower_delta=st.integers(min_value=1, max_value=60),
    # Valores de las dos filas empatadas (distintos entre sí para que un "pick silencioso"
    # cualquiera sería incorrecto — la única respuesta válida es rechazar).
    cutoff_a=_cutoff,
    cut1_a=_cut1,
    cut2_a=_cut2,
    eph_a=_ephemeral,
    cut1_b=_cut1,
    cut2_b=_cut2,
    eph_b=_ephemeral,
)
def test_duplicate_effective_period_rejected_without_mutation(
    year,
    month,
    scope,
    tie_delta,
    add_lower_row,
    lower_delta,
    cutoff_a,
    cut1_a,
    cut2_a,
    eph_a,
    cut1_b,
    cut2_b,
    eph_b,
):
    """
    Dos filas con idéntica `effective_key` en el tope aplicable del mismo scope hacen que
    `resolve_recycle_policy` lance `RecyclePolicyResolutionError` sin mutar estado.
    """
    m_key = recycle_policy_service.period_key(year, month)

    # effective_key del empate: <= M_key. tie_delta las mantiene aplicables (<= M_key).
    tie_key = m_key - tie_delta
    tie_year, tie_month = _period_from_key(tie_key)

    with create_test_session() as db:
        org = Organization(name="Org-Test", timezone="UTC")
        db.add(org)
        db.commit()
        db.refresh(org)

        org_id_for_rows = None if scope == "global" else org.id

        # Dos filas empatadas en el tope (misma effective_key, mismo scope), con valores
        # DISTINTOS para que ninguna selección silenciosa sea "inofensiva".
        row_a = BillingRecyclePolicy(
            organization_id=org_id_for_rows,
            cutoff_offset=cutoff_a,
            cut1_offset=cut1_a,
            cut2_offset=cut2_a,
            ephemeral_hours=eph_a,
            effective_from_year=tie_year,
            effective_from_month=tie_month,
            effective_key=tie_key,
        )
        row_b = BillingRecyclePolicy(
            organization_id=org_id_for_rows,
            cutoff_offset=cutoff_a,
            cut1_offset=cut1_b,
            cut2_offset=cut2_b,
            ephemeral_hours=eph_b,
            effective_from_year=tie_year,
            effective_from_month=tie_month,
            effective_key=tie_key,
        )
        db.add_all([row_a, row_b])

        # Fila inferior opcional (mismo scope) con effective_key estrictamente menor: asegura
        # que el empate resuelto sea el del TOPE aplicable.
        if add_lower_row:
            lower_key = tie_key - lower_delta
            if lower_key >= 0:
                lower_year, lower_month = _period_from_key(lower_key)
                db.add(
                    BillingRecyclePolicy(
                        organization_id=org_id_for_rows,
                        cutoff_offset=1,
                        cut1_offset=-2,
                        cut2_offset=-3,
                        ephemeral_hours=24,
                        effective_from_year=lower_year,
                        effective_from_month=lower_month,
                        effective_key=lower_key,
                    )
                )
        db.commit()

        # Estado ANTES de resolver.
        before = _snapshot(db)

        # Property 4 (Req 3.3): empate en el tope => fail-closed.
        try:
            recycle_policy_service.resolve_recycle_policy(db, org, year, month)
            raised = False
        except RecyclePolicyResolutionError:
            raised = True

        assert raised, (
            "resolve_recycle_policy debió lanzar RecyclePolicyResolutionError ante periodos "
            f"efectivos duplicados en el tope (scope={scope}, effective_key={tie_key})."
        )

        # Estado DESPUÉS del raise: sin mutación (mismo número de filas y mismos valores).
        # Se expira la identity map para releer desde la BD (garantiza que no hay cambios
        # pendientes/persistidos ocultos).
        db.expire_all()
        after = _snapshot(db)

        assert after == before, (
            "El estado de billing_recycle_policies cambió tras el rechazo (debe ser inmutable "
            "en el fail-closed de Req 3.3)."
        )
