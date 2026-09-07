"""
Tests de integración del endpoint `GET /workstations/stale` — presencia de `last_seen`
en la respuesta (task 1.2 del spec stale-stations-report-improvements).

Objetivo (Req 1.1, 1.2): tras exponer `last_seen` de forma aditiva en `WorkstationResponse`,
cada item devuelto por el endpoint de estaciones inactivas debe incluir el campo `last_seen`
con un valor no nulo, poblado desde la columna real de actividad `Workstation.last_seen`
(migración 036), y NO derivado de `updated_at`.

Patrón (idéntico a `tests/integration/test_closure_report_endpoints.py`):
- Router de workstations montado en una `FastAPI` aislada con `dependency_overrides` de
  `get_db` y `get_current_user` (basta sobreescribir la identidad para fijar el rol).
- Sesión SQLite real in-memory con el esquema completo, para ejercer de verdad la query,
  los filtros de inactividad y la serialización de `WorkstationResponse`.

El endpoint `list_stale_workstations` es síncrono, así que se usa `TestClient`.

_Requirements: 1.1, 1.2_
"""

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
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


# ── Fixtures y helpers ──────────────────────────────────────────────────────


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
        is_online=False,
        last_seen=last_seen,
        created_at=created_at,
        first_seen=created_at,
        billing_status="billable",
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws


def _build_app(db, current_user) -> FastAPI:
    """Monta el router de workstations en una FastAPI aislada con overrides de auth + get_db."""
    app = FastAPI()
    app.include_router(workstations_router, prefix="/workstations")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: current_user
    return app


# ── Tests ───────────────────────────────────────────────────────────────────


class TestStaleLastSeenPresente:
    """Req 1.1, 1.2: cada item de `/workstations/stale` incluye `last_seen` no nulo."""

    def test_cada_item_incluye_last_seen_no_nulo(self):
        """Con varias estaciones inactivas, todos los items traen `last_seen` poblado."""
        db, engine = _make_session()
        try:
            org = _make_org(db)
            ws1 = _make_stale_ws(db, org, ip_private="10.0.0.1", dias_inactiva=120)
            ws2 = _make_stale_ws(db, org, ip_private="10.0.0.2", dias_inactiva=200)
            ws3 = _make_stale_ws(db, org, ip_private="10.0.0.3", dias_inactiva=365)
            esperado_por_ip = {
                w.ip_private: w.last_seen for w in (ws1, ws2, ws3)
            }

            app = _build_app(db, _operator_user(org.id))
            client = TestClient(app)
            resp = client.get("/workstations/stale")

            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["total"] == 3
            items = body["items"]
            assert len(items) == 3

            for item in items:
                # El campo debe estar presente y no ser nulo (Req 1.1).
                assert "last_seen" in item, f"Falta 'last_seen' en el item: {item}"
                assert item["last_seen"] is not None

                # El valor debe corresponder a la columna real Workstation.last_seen,
                # no a updated_at (Req 1.2).
                esperado = esperado_por_ip[item["ip_private"]]
                assert datetime.fromisoformat(item["last_seen"]) == esperado
                assert item["last_seen"] != item["updated_at"]

            app.dependency_overrides.clear()
        finally:
            db.close()
            engine.dispose()

    def test_respuesta_vacia_sigue_siendo_valida(self):
        """Sin estaciones inactivas, la respuesta es válida (total=0, items=[])."""
        db, engine = _make_session()
        try:
            org = _make_org(db)
            app = _build_app(db, _operator_user(org.id))
            client = TestClient(app)
            resp = client.get("/workstations/stale")

            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["total"] == 0
            assert body["items"] == []

            app.dependency_overrides.clear()
        finally:
            db.close()
            engine.dispose()
