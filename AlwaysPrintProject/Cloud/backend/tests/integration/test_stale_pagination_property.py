"""
Property test del endpoint `GET /workstations/stale` — consistencia de `total`
y de la paginación con el conjunto filtrado (task 2.6 del spec
stale-stations-report-improvements).

Property 3: `total` y la paginación son consistentes con el filtro e independientes del sort.

    *Para todo* conjunto filtrado y *para toda* combinación de `sort_by`/`sort_dir`
    y tamaño de página, el `total` devuelto es igual al número de elementos filtrados
    y la concatenación de todas las páginas (en orden) no repite ni omite ningún
    elemento.

Tag: `Feature: stale-stations-report-improvements, Property 3: total y paginacion consistentes con el filtro`

**Validates: Requirements 8.10**

Estrategia (idéntica a `tests/integration/test_stale_last_seen_response.py`):
- Shim `@compiles(Extract, "sqlite")` que reproduce la semántica de `extract('epoch', ...)`
  de PostgreSQL sobre SQLite usando `julianday` (NO toca código de producción ni debilita
  el filtro; sólo lo ejerce fielmente en las pruebas).
- Sesión SQLite real in-memory con el esquema completo.
- Router de workstations montado en una `FastAPI` aislada con `dependency_overrides`
  de `get_db` y `get_current_user`.
- Hypothesis genera conjuntos de estaciones (inactivas y no inactivas), la combinación
  `sort_by`/`sort_dir` y el tamaño de página; con `max_examples >= 100`.
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
from app.api.v1.endpoints.workstations import (
    StaleSortBy,
    StaleSortDir,
    router as workstations_router,
)


# ── Compatibilidad de dialecto SQLite para el filtro `extract('epoch', ...)` ──
#
# El endpoint filtra actividad real con `func.extract("epoch", last_seen - created_at)`,
# construcción específica de PostgreSQL. En SQLite no existe el tipo interval y esa
# expresión no haría match. Registramos una extensión de compilación SÓLO para SQLite
# que reproduce la semántica de PostgreSQL (segundos de diferencia entre dos timestamps)
# usando `julianday`. NO modifica producción ni debilita el filtro.
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


# ── Fixtures y helpers ──────────────────────────────────────────────────────


def _make_session():
    """Sesión SQLite in-memory con el esquema completo (aislada por ejemplo)."""
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


def _build_app(db, current_user) -> FastAPI:
    """Monta el router de workstations en una FastAPI aislada con overrides de auth + get_db."""
    app = FastAPI()
    app.include_router(workstations_router, prefix="/workstations")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: current_user
    return app


# ── Estrategia de generación ─────────────────────────────────────────────────
#
# Cada estación se describe por (dias_inactiva, activa_real). Con los filtros por
# defecto del endpoint (days=90, min_hours=24):
#   - Es "inactiva" (pertenece al conjunto filtrado) SÓLO si dias_inactiva > 90
#     Y tuvo actividad real (last_seen - created_at > 24h).
# Generamos deliberadamente estaciones que NO cumplen los filtros (dias pequeños o
# sin actividad real) para verificar que `total` refleja el conjunto filtrado, no el total.

_ws_strategy = st.fixed_dictionaries({
    # Días desde la última conexión. Mezcla de valores por debajo y por encima del
    # umbral de 90 días para poblar tanto el conjunto filtrado como su complemento.
    #
    # Evitamos deliberadamente el rango [80, 100] (justo alrededor del umbral de
    # 90 días). El endpoint recalcula `now` unos milisegundos después que el test,
    # así que en el borde EXACTO (`dias_inactiva == 90`) la comparación
    # `last_seen < now - 90d` puede diferir del predicado del test por clock skew.
    # No es un bug del código: la pertenencia al conjunto es estable lejos del borde,
    # que es lo que la propiedad busca verificar.
    "dias_inactiva": st.one_of(
        st.integers(min_value=1, max_value=80),
        st.integers(min_value=100, max_value=800),
    ),
    # Si tuvo actividad real suficiente (created_at bastante anterior a last_seen).
    # False => (last_seen - created_at) < 24h => queda fuera del filtro min_hours.
    "activa_real": st.booleans(),
})


def _seed_workstations(db, org, specs):
    """
    Crea estaciones en la BD según `specs` y devuelve el conjunto de IPs que
    DEBEN pertenecer al conjunto filtrado (inactiva > 90 días Y actividad real > 24h).
    """
    now = datetime.utcnow()
    esperadas = set()
    for i, spec in enumerate(specs):
        ip = f"10.0.{i // 256}.{i % 256}"
        last_seen = now - timedelta(days=spec["dias_inactiva"])
        if spec["activa_real"]:
            # Actividad real holgada (>> 24h): created_at 30 días antes de last_seen.
            created_at = last_seen - timedelta(days=30)
        else:
            # Sin actividad real suficiente: created_at sólo 1h antes de last_seen.
            created_at = last_seen - timedelta(hours=1)

        ws = Workstation(
            id=uuid.uuid4(),
            organization_id=org.id,
            ip_private=ip,
            is_online=False,
            last_seen=last_seen,
            created_at=created_at,
            first_seen=created_at,
            billing_status="billable",
        )
        db.add(ws)

        # Réplica en Python de los filtros del endpoint (days=90, min_hours=24).
        cumple_dias = spec["dias_inactiva"] > 90
        cumple_actividad = (last_seen - created_at).total_seconds() > 24 * 3600
        if cumple_dias and cumple_actividad:
            esperadas.add(ip)

    db.commit()
    return esperadas


# ── Property test ─────────────────────────────────────────────────────────────


class TestStalePaginacionConsistente:
    """
    Property 3: `total` = |conjunto filtrado| y la concatenación de páginas
    no repite ni omite elementos, para cualquier tamaño de página e independiente
    del sort.

    **Validates: Requirements 8.10**
    """

    @settings(
        max_examples=120,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(
        specs=st.lists(_ws_strategy, min_size=0, max_size=25),
        page_size=st.integers(min_value=1, max_value=30),
        sort_by=st.sampled_from(list(StaleSortBy)),
        sort_dir=st.sampled_from(list(StaleSortDir)),
    )
    def test_total_y_paginacion_consistentes_con_el_filtro(
        self, specs, page_size, sort_by, sort_dir
    ):
        db, engine = _make_session()
        try:
            org = _make_org(db)
            esperadas = _seed_workstations(db, org, specs)

            app = _build_app(db, _operator_user(org.id))
            client = TestClient(app)

            # 1) total = |conjunto filtrado|, medido con la primera página.
            first = client.get(
                "/workstations/stale",
                params={
                    "page": 1,
                    "page_size": page_size,
                    "sort_by": sort_by.value,
                    "sort_dir": sort_dir.value,
                },
            )
            assert first.status_code == 200, first.text
            total = first.json()["total"]
            assert total == len(esperadas), (
                f"total={total} != |filtrado|={len(esperadas)}"
            )

            # 2) Concatenar TODAS las páginas y verificar cobertura exacta:
            #    ni repite ni omite ningún elemento del conjunto filtrado.
            vistas = []  # lista (preserva orden y repeticiones para detectar duplicados)
            page = 1
            # Número de páginas necesarias para recorrer el total.
            num_paginas = (total + page_size - 1) // page_size if total else 0
            while page <= num_paginas:
                resp = client.get(
                    "/workstations/stale",
                    params={
                        "page": page,
                        "page_size": page_size,
                        "sort_by": sort_by.value,
                        "sort_dir": sort_dir.value,
                    },
                )
                assert resp.status_code == 200, resp.text
                body = resp.json()
                # El total no debe variar entre páginas ni con el sort.
                assert body["total"] == total
                items = body["items"]
                # Cada página intermedia está llena; la última puede ser parcial.
                if page < num_paginas:
                    assert len(items) == page_size, (
                        f"página {page} incompleta: {len(items)} != {page_size}"
                    )
                vistas.extend(item["ip_private"] for item in items)
                page += 1

            # Sin duplicados en la concatenación de páginas.
            assert len(vistas) == len(set(vistas)), "Hay elementos repetidos entre páginas"
            # Cobertura exacta: el conjunto de páginas == conjunto filtrado.
            assert set(vistas) == esperadas, "La unión de páginas != conjunto filtrado"
            # La cardinalidad concatenada coincide con total.
            assert len(vistas) == total

            app.dependency_overrides.clear()
        finally:
            db.close()
            engine.dispose()
