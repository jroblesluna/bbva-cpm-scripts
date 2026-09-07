"""
Property test del endpoint `GET /workstations/stale` — aislamiento por inquilino
bajo cualquier ordenamiento (task 2.7 del spec stale-stations-report-improvements).

Feature: stale-stations-report-improvements, Property 4: aislamiento por inquilino bajo cualquier orden

Objetivo (Req 9.1, 9.2): para toda combinación de `sort_by`/`sort_dir`, el tenant
isolation se preserva:
- Operador → solo ve estaciones de SU organización.
- Administrador que filtra por una organización → solo ve estaciones de esa organización.

El ordenamiento server-side (añadido en task 2.2) nunca debe ampliar el alcance de
datos visibles: cambia el orden, jamás la pertenencia por organización.

Patrón (idéntico a `tests/integration/test_stale_last_seen_response.py`):
- Shim `@compiles(Extract, "sqlite")` que reproduce la semántica de PostgreSQL para
  `func.extract("epoch", last_seen - created_at)` sobre SQLite (motor de estos tests).
- Sesión SQLite real in-memory con el esquema completo, para ejercer de verdad la
  query, los filtros de inactividad y el tenant isolation.
- Router de workstations montado en una FastAPI aislada con `dependency_overrides` de
  `get_db` y `get_current_user` (fija la identidad/rol/organización del solicitante).

Se usa Hypothesis (>=100 iteraciones) para explorar múltiples organizaciones,
estaciones repartidas entre ellas y cualquier combinación de sort. NO se implementa
PBT desde cero: se reutiliza la librería Hypothesis.

_Requirements: 9.1, 9.2_
"""

import uuid
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import given, settings, strategies as st
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql.elements import BinaryExpression, Extract

from app.core.database import Base, get_db
from app.core.security import get_current_user
import app.models  # noqa: F401 — registra todas las tablas en metadata
from app.models.organization import Organization
from app.models.user import User, UserRole
from app.models.workstation import Workstation
from app.api.v1.endpoints.workstations import router as workstations_router


# ── Compatibilidad de dialecto SQLite para el filtro `extract('epoch', ...)` ──
#
# El endpoint filtra actividad real con `func.extract("epoch", last_seen - created_at)`,
# una construcción específica de PostgreSQL. En SQLite (motor de estos tests) no existe
# el tipo interval y esa expresión rinde un valor sin sentido, por lo que el filtro nunca
# haría match. Registramos una extensión de compilación SÓLO para SQLite que reproduce la
# semántica de PostgreSQL (segundos de diferencia entre dos timestamps) usando `julianday`.
# Esto NO modifica el código de producción ni debilita el filtro: sólo permite ejercerlo
# fielmente sobre SQLite en las pruebas.
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


# ── Valores de ordenamiento admitidos por el endpoint (Req 8.7, 8.8) ──────────
SORT_BY_VALUES = [
    "ip",
    "hostname",
    "current_user",
    "organizacion",
    "created_at",
    "last_seen",
    "dias_inactiva",
]
SORT_DIR_VALUES = ["asc", "desc"]


# ── Fixtures y helpers ────────────────────────────────────────────────────────


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


def _make_org(db, name) -> Organization:
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


def _admin_user() -> User:
    """Admin de acceso global (organization_id = None); filtra vía query param."""
    return User(
        id=uuid.uuid4(),
        email=f"admin_{uuid.uuid4().hex}@bbva.com",
        password_hash="x",
        full_name="Administrador",
        role=UserRole.ADMIN,
        organization_id=None,
    )


def _make_stale_ws(db, org, *, ip_private, hostname, dias_inactiva) -> Workstation:
    """
    Crea una estación que cumple los filtros de inactividad por defecto del endpoint
    (`days=90`, `min_hours=24`):
    - `last_seen` = ahora - `dias_inactiva` (con dias_inactiva > 90).
    - `created_at` muy anterior a `last_seen` (para que `last_seen - created_at` supere
      con holgura las 24h mínimas de actividad real).
    """
    now = datetime.utcnow()
    last_seen = now - timedelta(days=dias_inactiva)
    created_at = last_seen - timedelta(days=30)  # >> 24h de actividad real
    ws = Workstation(
        id=uuid.uuid4(),
        organization_id=org.id,
        ip_private=ip_private,
        hostname=hostname,
        current_user=f"user_{ip_private}",
        is_online=False,
        last_seen=last_seen,
        created_at=created_at,
        first_seen=created_at,
        billing_status="billable",
    )
    db.add(ws)
    db.commit()
    return ws


def _build_app(db, current_user) -> FastAPI:
    """Monta el router de workstations en una FastAPI aislada con overrides de auth + get_db."""
    app = FastAPI()
    app.include_router(workstations_router, prefix="/workstations")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: current_user
    return app


def _seed_multi_org(db, *, num_orgs, stations_per_org):
    """
    Siembra varias organizaciones, cada una con varias estaciones inactivas.
    Devuelve la lista de organizaciones creadas (con IPs/hostnames únicos globalmente).
    """
    orgs = []
    seq = 0
    for o in range(num_orgs):
        org = _make_org(db, name=f"Org-{o}-{uuid.uuid4().hex[:6]}")
        for s in range(stations_per_org):
            seq += 1
            _make_stale_ws(
                db,
                org,
                ip_private=f"10.{o}.{s}.{seq % 250}",
                hostname=f"w10{o:03d}0{s % 9}p{seq % 90:02d}",
                # días variados (>90) para que el ordenamiento tenga efecto real
                dias_inactiva=95 + (seq * 7) % 400,
            )
        orgs.append(org)
    return orgs


def _fetch_all_items(client, params):
    """
    Recupera TODOS los items paginando (page_size grande) para verificar el conjunto
    completo devuelto, no solo la primera página.
    """
    params = {**params, "page": 1, "page_size": 200}
    resp = client.get("/workstations/stale", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


# ── Property 4: aislamiento por inquilino bajo cualquier orden ────────────────


class TestPropertyTenantIsolationBajoCualquierOrden:
    """
    Feature: stale-stations-report-improvements,
    Property 4: aislamiento por inquilino bajo cualquier orden

    Validates: Requirements 9.1, 9.2
    """

    @settings(max_examples=120, deadline=None)
    @given(
        num_orgs=st.integers(min_value=2, max_value=4),
        stations_per_org=st.integers(min_value=1, max_value=5),
        sort_by=st.sampled_from(SORT_BY_VALUES),
        sort_dir=st.sampled_from(SORT_DIR_VALUES),
        target_org_index=st.integers(min_value=0, max_value=3),
    )
    def test_operador_solo_ve_su_organizacion(
        self, num_orgs, stations_per_org, sort_by, sort_dir, target_org_index
    ):
        """
        Req 9.1: bajo CUALQUIER sort_by/sort_dir, un Operador solo recibe estaciones
        de su propia organización. El ordenamiento nunca amplía el alcance.
        """
        db, engine = _make_session()
        try:
            orgs = _seed_multi_org(
                db, num_orgs=num_orgs, stations_per_org=stations_per_org
            )
            # La organización del operador se elige de forma acotada al nº de orgs.
            op_org = orgs[target_org_index % len(orgs)]

            app = _build_app(db, _operator_user(op_org.id))
            client = TestClient(app)

            items = _fetch_all_items(
                client, {"sort_by": sort_by, "sort_dir": sort_dir}
            )

            # Invariante de aislamiento: TODA estación devuelta es de la org del operador.
            for item in items:
                assert item["organization_id"] == str(op_org.id), (
                    f"Fuga de tenant: estación {item['ip_private']} de otra org "
                    f"con sort_by={sort_by}, sort_dir={sort_dir}"
                )

            # El operador ve exactamente sus estaciones (ni de más ni de menos).
            assert len(items) == stations_per_org

            app.dependency_overrides.clear()
        finally:
            db.close()
            engine.dispose()

    @settings(max_examples=120, deadline=None)
    @given(
        num_orgs=st.integers(min_value=2, max_value=4),
        stations_per_org=st.integers(min_value=1, max_value=5),
        sort_by=st.sampled_from(SORT_BY_VALUES),
        sort_dir=st.sampled_from(SORT_DIR_VALUES),
        target_org_index=st.integers(min_value=0, max_value=3),
    )
    def test_admin_filtrando_solo_ve_la_org_seleccionada(
        self, num_orgs, stations_per_org, sort_by, sort_dir, target_org_index
    ):
        """
        Req 9.2: bajo CUALQUIER sort_by/sort_dir, un Administrador que filtra por
        organization_id solo recibe estaciones de esa organización.
        """
        db, engine = _make_session()
        try:
            orgs = _seed_multi_org(
                db, num_orgs=num_orgs, stations_per_org=stations_per_org
            )
            target_org = orgs[target_org_index % len(orgs)]

            app = _build_app(db, _admin_user())
            client = TestClient(app)

            items = _fetch_all_items(
                client,
                {
                    "organization_id": str(target_org.id),
                    "sort_by": sort_by,
                    "sort_dir": sort_dir,
                },
            )

            # Invariante de aislamiento: TODA estación devuelta es de la org filtrada.
            for item in items:
                assert item["organization_id"] == str(target_org.id), (
                    f"Filtro de admin ignorado: estación {item['ip_private']} de otra "
                    f"org con sort_by={sort_by}, sort_dir={sort_dir}"
                )

            # El admin filtrado ve exactamente las estaciones de esa org.
            assert len(items) == stations_per_org

            app.dependency_overrides.clear()
        finally:
            db.close()
            engine.dispose()
