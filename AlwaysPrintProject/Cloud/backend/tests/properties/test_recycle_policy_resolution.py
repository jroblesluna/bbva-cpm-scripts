# Feature: recycle-policy-config, Property 2: Resolución selecciona el máximo effective_key aplicable con fallback
"""
Property test de `RecyclePolicyService.resolve_recycle_policy` (task 3.1).

Verifica el algoritmo de resolución de la política de reciclaje para un periodo de cierre
`M=(year, month)` sobre una base SQLite in-memory (con el tipo `GUID` compat SQLite/Postgres),
replicando el patrón de fixtures de `tests/unit/test_billing_service.py` (sesión con esquema
completo + una `Organization` real para las FK).

La propiedad bajo prueba (Property 2) es la cascada de resolución por PERIODO:

    1. Org_Override de la org con el MAYOR `effective_key <= M_key` (tenant isolation).
    2. Si ninguno aplica, Global_Default con el MAYOR `effective_key <= M_key`.
    3. Si tampoco hay, la `LEGACY_POLICY` base (`+1/-2/-3` + 24h, source="seed_base").

Casos borde cubiertos por la generación:
    - Override FUTURO (`effective_key > M_key`): no se selecciona, cae limpiamente al
      Global_Default vigente para M (Req 3.6).
    - Sin ninguna política `<= M_key`: fallback a `LEGACY_POLICY` (Req 3.5).
    - La resolución IGNORA la fecha de ejecución: solo depende de `(year, month)`, `org.id` y
      las filas persistidas (Req 3.4 — implícito: el test no pasa ninguna fecha de ejecución).

Se generan `effective_key` DISTINTOS por scope (global y override) para no tocar el path de
empate en el tope (`RecyclePolicyResolutionError`, Req 3.3), que se prueba en la task 3.4.

Se usa un oráculo de referencia (`_expected_source_and_offsets`) que implementa la cascada de
forma independiente, y se compara contra el resultado del servicio.

**Validates: Requirements 2.3, 2.4, 3.2, 3.5, 3.6**
"""

import uuid

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
import app.models  # noqa: F401 — registra todas las tablas en metadata
from app.models.billing import BillingRecyclePolicy
from app.models.organization import Organization
from app.services.recycle_policy_service import (
    LEGACY_POLICY,
    RecyclePolicyService,
    recycle_policy_service,
)


# === SESIÓN SQLITE IN-MEMORY (patrón de tests/unit/test_billing_service.py) ===


def _make_session():
    """Crea una sesión SQLite in-memory con el esquema completo (tipo GUID compat)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return Session(), engine


@pytest.fixture
def db():
    """Sesión aislada con una `Organization` real (BBVA) para las FK del override."""
    session, engine = _make_session()
    org = Organization(
        id=uuid.uuid4(),
        name="BBVA",
        timezone="UTC",
        billing_mode="monthly",
    )
    session.add(org)
    session.commit()
    session._org = org
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


# === HELPERS ===

_PERIOD_KEY = RecyclePolicyService.period_key


def _year_month_from_key(key: int):
    """Inverso de period_key: key -> (year, month) con month en 1..12."""
    return key // 12, (key % 12) + 1


def _insert_policy(db, organization_id, effective_key, cutoff, cut1, cut2, ephemeral_hours):
    """Inserta una fila BillingRecyclePolicy en el scope dado (org o global si es None)."""
    year, month = _year_month_from_key(effective_key)
    row = BillingRecyclePolicy(
        id=uuid.uuid4(),
        organization_id=organization_id,
        cutoff_offset=cutoff,
        cut1_offset=cut1,
        cut2_offset=cut2,
        ephemeral_hours=ephemeral_hours,
        effective_from_year=year,
        effective_from_month=month,
        effective_key=effective_key,
    )
    db.add(row)
    return row


def _expected(m_key, org_specs, global_specs):
    """
    Oráculo de referencia de la cascada de resolución.

    `org_specs`/`global_specs` son listas de dicts con al menos `effective_key`, `cutoff`,
    `cut1`, `cut2`, `ephemeral_hours`.

    Devuelve una tupla `(source, cutoff, cut1, cut2, ephemeral_hours)` esperada.
    """
    applicable_org = [s for s in org_specs if s["effective_key"] <= m_key]
    if applicable_org:
        top = max(applicable_org, key=lambda s: s["effective_key"])
        return ("org", top["cutoff"], top["cut1"], top["cut2"], top["ephemeral_hours"])

    applicable_global = [s for s in global_specs if s["effective_key"] <= m_key]
    if applicable_global:
        top = max(applicable_global, key=lambda s: s["effective_key"])
        return ("default", top["cutoff"], top["cut1"], top["cut2"], top["ephemeral_hours"])

    return (
        "seed_base",
        LEGACY_POLICY.cutoff,
        LEGACY_POLICY.cut1,
        LEGACY_POLICY.cut2,
        LEGACY_POLICY.ephemeral_hours,
    )


# === ESTRATEGIAS ===

# Periodos acotados a rangos válidos del modelo (año 2000..2999, mes 1..12) y cómodos para
# convertir key <-> (year, month). Se usa 2000..2100 para mantener las fechas razonables.
_MIN_KEY = _PERIOD_KEY(2000, 1)
_MAX_KEY = _PERIOD_KEY(2100, 12)

key_strategy = st.integers(min_value=_MIN_KEY, max_value=_MAX_KEY)

# Offsets con signo válidos (no se validan aquí; solo deben viajar íntegros por la resolución).
offset_strategy = st.integers(min_value=-24, max_value=1)
ephemeral_strategy = st.integers(min_value=1, max_value=168)


@st.composite
def _scope_specs(draw, max_rows):
    """
    Genera hasta `max_rows` políticas de un scope con `effective_key` DISTINTOS (para no
    tocar el path de empate en el tope, que se prueba aparte). Cada política lleva sus
    offsets y umbral, de modo que el test también verifica que la fila del tope es la que
    se devuelve (no otra del mismo scope).
    """
    keys = draw(
        st.lists(key_strategy, min_size=0, max_size=max_rows, unique=True)
    )
    specs = []
    for k in keys:
        specs.append(
            {
                "effective_key": k,
                "cutoff": draw(offset_strategy),
                "cut1": draw(offset_strategy),
                "cut2": draw(offset_strategy),
                "ephemeral_hours": draw(ephemeral_strategy),
            }
        )
    return specs


# === PROPERTY TEST ===


@settings(max_examples=100, deadline=None)
@given(
    m_key=key_strategy,
    org_specs=_scope_specs(max_rows=4),
    global_specs=_scope_specs(max_rows=4),
)
def test_resolucion_selecciona_maximo_effective_key_con_fallback(m_key, org_specs, global_specs):
    """
    Property 2 — Para cualquier conjunto de Global_Default y Org_Override (con effective_key
    distintos por scope) y cualquier periodo M, `resolve_recycle_policy` devuelve:

        - el Org_Override con el mayor `effective_key <= M_key` si existe (source="org"), o
        - el Global_Default con el mayor `effective_key <= M_key` si no (source="default"), o
        - la LEGACY_POLICY base si ninguna aplica (source="seed_base").

    Cubre el fallback por override futuro (Req 3.6): si todos los overrides tienen
    `effective_key > M_key`, la resolución cae al Global_Default vigente para M.

    **Validates: Requirements 2.3, 2.4, 3.2, 3.5, 3.6**
    """
    session, engine = _make_session()
    org = Organization(id=uuid.uuid4(), name="BBVA", timezone="UTC", billing_mode="monthly")
    session.add(org)
    session.commit()
    try:
        for s in org_specs:
            _insert_policy(
                session, org.id, s["effective_key"], s["cutoff"], s["cut1"], s["cut2"],
                s["ephemeral_hours"],
            )
        for s in global_specs:
            _insert_policy(
                session, None, s["effective_key"], s["cutoff"], s["cut1"], s["cut2"],
                s["ephemeral_hours"],
            )
        session.commit()

        year, month = _year_month_from_key(m_key)
        resolved = recycle_policy_service.resolve_recycle_policy(session, org, year, month)

        exp_source, exp_cutoff, exp_cut1, exp_cut2, exp_eph = _expected(
            m_key, org_specs, global_specs
        )

        assert resolved.source == exp_source, (
            f"M_key={m_key} ({year}-{month:02d}): source esperado {exp_source}, "
            f"obtenido {resolved.source}."
        )
        assert (resolved.cutoff, resolved.cut1, resolved.cut2, resolved.ephemeral_hours) == (
            exp_cutoff,
            exp_cut1,
            exp_cut2,
            exp_eph,
        ), (
            f"M_key={m_key}: offsets/umbral esperados "
            f"({exp_cutoff},{exp_cut1},{exp_cut2},{exp_eph}); "
            f"obtenidos ({resolved.cutoff},{resolved.cut1},{resolved.cut2},"
            f"{resolved.ephemeral_hours})."
        )
    finally:
        session.close()
        engine.dispose()


# === EJEMPLOS DIRIGIDOS (fallback puntual, complementan la property) ===


def test_override_futuro_cae_a_global(db):
    """
    Req 3.6 — Un Org_Override con effective_key > M_key (futuro) NO se selecciona; la
    resolución cae al Global_Default vigente para M.
    """
    m_key = _PERIOD_KEY(2026, 6)
    # Global vigente en 2026-01.
    _insert_policy(db, None, _PERIOD_KEY(2026, 1), 1, -2, -3, 24)
    # Override futuro (2026-09) — no aplica a 2026-06.
    _insert_policy(db, db._org.id, _PERIOD_KEY(2026, 9), 1, 0, -1, 24)
    db.commit()

    resolved = recycle_policy_service.resolve_recycle_policy(db, db._org, 2026, 6)
    assert resolved.source == "default"
    assert (resolved.cutoff, resolved.cut1, resolved.cut2) == (1, -2, -3)


def test_sin_politica_usa_legacy(db):
    """Req 3.5 — Sin ninguna política <= M_key, se devuelve la LEGACY_POLICY base."""
    resolved = recycle_policy_service.resolve_recycle_policy(db, db._org, 2026, 6)
    assert resolved.source == "seed_base"
    assert (resolved.cutoff, resolved.cut1, resolved.cut2, resolved.ephemeral_hours) == (
        1,
        -2,
        -3,
        24,
    )


def test_override_vigente_tiene_prioridad_sobre_global(db):
    """Req 2.3/3.7 — Con override vigente para M, se usa el override (no el global)."""
    _insert_policy(db, None, _PERIOD_KEY(2000, 1), 1, -2, -3, 24)
    _insert_policy(db, db._org.id, _PERIOD_KEY(2026, 9), 1, 0, -1, 24)
    db.commit()

    resolved = recycle_policy_service.resolve_recycle_policy(db, db._org, 2026, 9)
    assert resolved.source == "org"
    assert (resolved.cutoff, resolved.cut1, resolved.cut2) == (1, 0, -1)
