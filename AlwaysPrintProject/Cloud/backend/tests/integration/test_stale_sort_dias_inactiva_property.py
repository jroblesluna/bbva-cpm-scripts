"""
Prueba basada en propiedades (Hypothesis) del endpoint `GET /workstations/stale`
— equivalencia entre ordenar por `dias_inactiva` y por `last_seen`
(task 2.5 del spec stale-stations-report-improvements).

Property 2: `dias_inactiva` descendente equivale a `last_seen` ascendente (y viceversa).

`dias_inactiva` no es una columna física: es una función monótona DECRECIENTE de
`last_seen` (a mayor tiempo inactiva, más antiguo el `last_seen`). Por tanto:
- ordenar por `sort_by=dias_inactiva`/`desc`  ≡  ordenar por `sort_by=last_seen`/`asc`
- ordenar por `sort_by=dias_inactiva`/`asc`   ≡  ordenar por `sort_by=last_seen`/`desc`

La prueba genera, con Hypothesis (≥100 iteraciones), conjuntos arbitrarios de
estaciones inactivas (que cumplen los filtros por defecto del endpoint), y verifica
que el orden de los items devueltos coincide entre ambos modos equivalentes.

Setup (idéntico a `tests/integration/test_stale_last_seen_response.py`):
- Shim `@compiles(Extract, "sqlite")` para reproducir `extract('epoch', ...)` de PostgreSQL.
- Sesión SQLite real in-memory con el esquema completo (misma factory `_make_session`).
- Mismos helpers de organización, usuario operador y estaciones inactivas.

Nota de transporte: en lugar de `TestClient`, esta property test invoca el endpoint
`list_stale_workstations` DIRECTAMENTE en proceso. Con ≥100 iteraciones de Hypothesis,
el `TestClient` de Starlette despacha el endpoint síncrono al thread pool de anyio
(40 hilos), que se satura y provoca un deadlock (event loop / thread pool starvation).
La llamada directa ejercita exactamente la misma lógica del endpoint —filtros,
mapeo de `sort_by`→columna, inversión de dirección para `dias_inactiva`, `order_by`
antes de paginar y serialización de `WorkstationResponse`— sin ese cuello de botella.

_Requirements: 8.11_
Tag: Feature: stale-stations-report-improvements, Property 2: dias_inactiva DESC equivale a last_seen ASC
"""

import uuid
from datetime import datetime, timedelta

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql.elements import BinaryExpression, Extract

from app.core.database import Base
import app.models  # noqa: F401 — registra todas las tablas en metadata
from app.models.organization import Organization
from app.models.user import User, UserRole
from app.models.workstation import Workstation
from app.api.v1.endpoints.workstations import (
    list_stale_workstations,
    StaleSortBy,
    StaleSortDir,
)


# ── Compatibilidad de dialecto SQLite para el filtro `extract('epoch', ...)` ──
#
# Idéntico al shim de test_stale_last_seen_response.py: el endpoint filtra actividad
# real con `func.extract("epoch", last_seen - created_at)`, construcción propia de
# PostgreSQL. En SQLite no existe el tipo interval, así que reproducimos la semántica
# (segundos entre dos timestamps) con `julianday`. NO altera el código de producción.
@compiles(Extract, "sqlite")
def _sqlite_extract_epoch(element, compiler, **kw):
    if str(element.field).lower() == "epoch":
        inner = element.expr
        if isinstance(inner, BinaryExpression):
            left = compiler.process(inner.left, **kw)
            right = compiler.process(inner.right, **kw)
            return f"((julianday({left}) - julianday({right})) * 86400.0)"
        return f"(julianday({compiler.process(inner, **kw)}) * 86400.0)"
    return compiler.visit_extract(element, **kw)


# ── Fixtures y helpers (mismo patrón que test_stale_last_seen_response.py) ────


def _make_session():
    """Sesión SQLite in-memory con el esquema completo (aislada por test)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return Session(), engine


def _make_org(db, name="Org Stale") -> Organization:
    org = Organization(id=uuid.uuid4(), name=name, timezone="UTC")
    db.add(org)
    db.commit()
    return org


def _operator_user(org_id) -> User:
    return User(
        id=uuid.uuid4(),
        email=f"op_{uuid.uuid4().hex}@bbva.com",
        password_hash="x",
        full_name="Operador",
        role=UserRole.OPERATOR,
        organization_id=org_id,
    )


def _make_stale_ws(db, org, *, ip_private: str, dias_inactiva: int) -> Workstation:
    """
    Crea una estación que cumple los filtros por defecto del endpoint (`days=90`,
    `min_hours=24`): `last_seen` = ahora - dias_inactiva (>90) y `created_at` muy
    anterior a `last_seen` (>>24h de actividad real).
    """
    now = datetime.utcnow()
    last_seen = now - timedelta(days=dias_inactiva)
    created_at = last_seen - timedelta(days=30)  # >> 24h de actividad real
    ws = Workstation(
        id=uuid.uuid4(),
        organization_id=org.id,
        ip_private=ip_private,
        is_online=False,
        last_seen=last_seen,
        created_at=created_at,
        first_seen=created_at,
        billing_status="billable",
    )
    db.add(ws)
    db.commit()
    return ws


def _ids_ordenados(db, user, *, sort_by: StaleSortBy, sort_dir: StaleSortDir):
    """
    Invoca el endpoint directamente y devuelve la lista de ids (str) en el orden
    retornado. Se usa una página grande para observar el orden global del dataset.
    """
    resp = list_stale_workstations(
        days=90,
        min_hours=24,
        organization_id=None,
        page=1,
        page_size=200,
        sort_by=sort_by,
        sort_dir=sort_dir,
        current_user=user,
        db=db,
    )
    return [str(item.id) for item in resp.items]


# ── Estrategia: conjunto de días-inactiva (todos > 90 para pasar el filtro) ──
#
# Se generan días de inactividad DISTINTOS para que el orden sea determinista (sin
# empates que dependan de un desempate no especificado). Un conjunto no vacío de
# tamaño variable ejercita la equivalencia con distintas cardinalidades.
_dias_inactiva_set = st.lists(
    st.integers(min_value=91, max_value=4000),
    min_size=1,
    max_size=25,
    unique=True,
)


# ── Property 2 ────────────────────────────────────────────────────────────────


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(dias=_dias_inactiva_set)
def test_dias_inactiva_desc_equivale_last_seen_asc(dias):
    """
    Property 2: para cualquier conjunto de estaciones filtradas,
    `dias_inactiva`/`desc` ≡ `last_seen`/`asc`  y  `dias_inactiva`/`asc` ≡ `last_seen`/`desc`.

    Tag: Feature: stale-stations-report-improvements, Property 2: dias_inactiva DESC equivale a last_seen ASC
    """
    db, engine = _make_session()
    try:
        org = _make_org(db)
        for idx, d in enumerate(dias):
            # IP única e irrelevante para el orden por last_seen/dias_inactiva.
            _make_stale_ws(db, org, ip_private=f"10.0.{idx // 256}.{idx % 256}", dias_inactiva=d)

        user = _operator_user(org.id)

        # dias_inactiva DESC (más días inactiva primero) ≡ last_seen ASC (más antiguo primero).
        assert _ids_ordenados(db, user, sort_by=StaleSortBy.dias_inactiva, sort_dir=StaleSortDir.desc) == \
            _ids_ordenados(db, user, sort_by=StaleSortBy.last_seen, sort_dir=StaleSortDir.asc)

        # dias_inactiva ASC (menos días inactiva primero) ≡ last_seen DESC (más reciente primero).
        assert _ids_ordenados(db, user, sort_by=StaleSortBy.dias_inactiva, sort_dir=StaleSortDir.asc) == \
            _ids_ordenados(db, user, sort_by=StaleSortBy.last_seen, sort_dir=StaleSortDir.desc)
    finally:
        db.close()
        engine.dispose()
