"""
Property test del endpoint `GET /workstations/stale` — el ordenamiento no altera el
conjunto filtrado (task 2.4 del spec stale-stations-report-improvements).

Feature: stale-stations-report-improvements, Property 1: El ordenamiento no altera el conjunto filtrado

Objetivo (Req 8.10, 8.12, 9.3, 9.4): para cualquier conjunto de estaciones que cumplan
los filtros de inactividad y para cualquier `sort_by`/`sort_dir`, la unión de todas las
páginas (tratada como CONJUNTO de IDs) debe ser exactamente igual al conjunto filtrado.
Es decir, ordenar solo reordena; no agrega, no omite ni duplica elementos, y `total`
refleja el tamaño del conjunto filtrado independientemente del sort.

Patrón de setup idéntico a `tests/integration/test_stale_last_seen_response.py`:
- Shim `@compiles(Extract, "sqlite")` para reproducir `extract('epoch', ...)` de PostgreSQL.
- Sesión SQLite real in-memory con el esquema completo.
- Router de workstations en una `FastAPI` aislada con `dependency_overrides` de
  `get_db` y `get_current_user`.

Se usa Hypothesis (max_examples >= 100) para explorar múltiples combinaciones de tamaño
del conjunto filtrado, page_size y (sort_by, sort_dir).

_Requirements: 8.10, 8.12, 9.3, 9.4_
"""

import uuid
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
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
# Reproduce la semántica de PostgreSQL (segundos de diferencia entre dos timestamps)
# usando `julianday`, SÓLO para SQLite. No modifica el código de producción ni debilita
# el filtro: sólo permite ejercerlo fielmente sobre SQLite en las pruebas.
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


# ── Helpers de setup (mismo patrón que el test de referencia) ────────────────


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


def _make_stale_ws(db, org, *, idx: int, dias_inactiva: int) -> Workstation:
    """
    Crea una estación que cumple los filtros de inactividad por defecto del endpoint
    (`days=90`, `min_hours=24`): con `dias_inactiva > 90` y `created_at` muy anterior
    a `last_seen` para superar con holgura las 24h de actividad real.
    """
    now = datetime.utcnow()
    last_seen = now - timedelta(days=dias_inactiva)
    created_at = last_seen - timedelta(days=30)  # >> 24h de actividad real
    ws = Workstation(
        id=uuid.uuid4(),
        organization_id=org.id,
        # IPs y hostnames variados para que el ordenamiento por distintas columnas
        # tenga contenido real que reordenar.
        ip_private=f"10.0.{idx // 256}.{idx % 256}",
        hostname=f"host-{(idx * 7) % 1000:03d}",
        current_user=f"user-{(idx * 3) % 100:02d}",
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


def _collect_all_ids(client: TestClient, *, sort_by: str, sort_dir: str, page_size: int):
    """
    Pagina TODO el reporte con el sort dado y devuelve (lista_de_ids, total_declarado).
    Recorre páginas hasta agotar los items, con un tope de seguridad contra bucles.
    """
    collected: list[str] = []
    page = 1
    total = None
    max_pages = 1000  # tope de seguridad: nunca debería alcanzarse
    while page <= max_pages:
        resp = client.get(
            "/workstations/stale",
            params={
                "sort_by": sort_by,
                "sort_dir": sort_dir,
                "page": page,
                "page_size": page_size,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        total = body["total"]
        items = body["items"]
        collected.extend(item["id"] for item in items)
        if len(items) < page_size:
            break
        page += 1
    return collected, total


# ── Property test ────────────────────────────────────────────────────────────


class TestStaleSortSetInvarianceProperty:
    """Property 1: El ordenamiento no altera el conjunto filtrado (Req 8.10, 8.12, 9.3, 9.4)."""

    # Se comparte UNA sola sesión SQLite + app FastAPI para todos los ejemplos de
    # Hypothesis del test (el setup por-ejemplo se limita a limpiar/repoblar la tabla
    # de workstations). Esto mantiene >=100 iteraciones sin pagar el coste de crear un
    # engine y el esquema completo en cada ejemplo.
    @settings(
        max_examples=120,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    )
    @given(
        # Conjunto filtrado de tamaño variable (todas cumplen el filtro por construcción).
        dias_list=st.lists(
            st.integers(min_value=91, max_value=3650),
            min_size=1,
            max_size=25,
        ),
        page_size=st.integers(min_value=1, max_value=30),
        sort_by=st.sampled_from(
            ["ip", "hostname", "current_user", "organizacion", "created_at", "last_seen", "dias_inactiva"]
        ),
        sort_dir=st.sampled_from(["asc", "desc"]),
    )
    def test_union_de_paginas_igual_al_conjunto_filtrado(
        self, dias_list, page_size, sort_by, sort_dir
    ):
        """
        Feature: stale-stations-report-improvements, Property 1: El ordenamiento no altera el conjunto filtrado

        Para cualquier conjunto filtrado y cualquier (sort_by, sort_dir):
        - La unión de todas las páginas (como CONJUNTO de IDs) es exactamente el
          conjunto filtrado esperado.
        - No hay duplicados entre páginas (la lista concatenada no repite IDs).
        - `total` coincide con el tamaño del conjunto filtrado (independiente del sort).
        """
        db = self._db
        # Cada ejemplo parte de un conjunto limpio de estaciones.
        db.query(Workstation).delete()
        db.commit()

        # IDs esperados: TODAS las estaciones creadas cumplen el filtro por
        # construcción (dias_inactiva > 90 y actividad real >> 24h).
        expected_ids = set()
        for idx, dias in enumerate(dias_list):
            ws = _make_stale_ws(db, self._org, idx=idx, dias_inactiva=dias)
            expected_ids.add(str(ws.id))

        collected, total = _collect_all_ids(
            self._client, sort_by=sort_by, sort_dir=sort_dir, page_size=page_size
        )

        # 1) La unión de páginas (como conjunto) es igual al conjunto filtrado.
        assert set(collected) == expected_ids
        # 2) No hay duplicados entre páginas: reordenar no repite elementos.
        assert len(collected) == len(expected_ids)
        # 3) total refleja el tamaño del conjunto filtrado, independiente del sort.
        assert total == len(expected_ids)

    # ── Ciclo de vida compartido (una vez por método de test) ────────────────

    def setup_method(self, method):
        """Crea la sesión SQLite, la organización y el TestClient una sola vez."""
        self._db, self._engine = _make_session()
        self._org = _make_org(self._db)
        self._app = _build_app(self._db, _operator_user(self._org.id))
        self._client = TestClient(self._app)

    def teardown_method(self, method):
        """Libera recursos compartidos."""
        try:
            self._app.dependency_overrides.clear()
        finally:
            self._db.close()
            self._engine.dispose()
