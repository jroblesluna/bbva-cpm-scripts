"""
Tests de integración del endpoint `GET /workstations/stale` — ordenamiento server-side
y preservación de filtros/tenant isolation (task 2.3 del spec
stale-stations-report-improvements).

Objetivo (Req 8.1-8.4, 8.9, 8.10, 9.1-9.4): tras añadir `sort_by`/`sort_dir` al endpoint,
el ordenamiento debe:
- Producir el orden esperado por cada columna (`ip`, `hostname`, `current_user`,
  `organizacion`, `created_at`, `last_seen`, `dias_inactiva`) en `asc` y `desc`.
- Sin params → default `last_seen` ascendente.
- Aplicarse ANTES de paginar (páginas consecutivas coherentes y sin solaparse).
- Preservar el tenant isolation (operador ve solo su org; admin puede filtrar) y los
  filtros `days`/`min_hours` bajo cualquier ordenamiento.

Patrón (idéntico a `tests/integration/test_stale_last_seen_response.py`):
- Router de workstations montado en una `FastAPI` aislada con `dependency_overrides` de
  `get_db` y `get_current_user`.
- Sesión SQLite real in-memory con el esquema completo.
- Shim de compilación `@compiles(Extract, "sqlite")` para reproducir la semántica de
  `func.extract("epoch", ...)` de PostgreSQL sobre SQLite (sin tocar producción).

El endpoint `list_stale_workstations` es síncrono, así que se usa `TestClient`.

_Requirements: 8.1, 8.2, 8.3, 8.4, 8.9, 8.10, 9.1, 9.2, 9.3, 9.4_
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
# construcción específica de PostgreSQL. En SQLite no existe el tipo interval y esa
# expresión rinde un valor sin sentido, por lo que el filtro nunca haría match.
# Registramos una extensión de compilación SÓLO para SQLite que reproduce la semántica
# de PostgreSQL (segundos de diferencia entre dos timestamps) usando `julianday`.
# Esto NO modifica el código de producción ni debilita el filtro.
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


def _admin_user() -> User:
    """Admin sin org: puede ver todas las orgs o filtrar por organization_id."""
    return User(
        id=uuid.uuid4(),
        email=f"admin_{uuid.uuid4().hex}@bbva.com",
        password_hash="x",
        full_name="Admin",
        role=UserRole.ADMIN,
        organization_id=None,
    )


def _make_stale_ws(
    db,
    org,
    *,
    ip_private: str,
    dias_inactiva: int,
    hostname: str = None,
    current_user: str = None,
    created_offset_days: int = 30,
) -> Workstation:
    """
    Crea una estación que cumple los filtros de inactividad por defecto del endpoint
    (`days=90`, `min_hours=24`):
    - `last_seen` = ahora - `dias_inactiva` (con dias_inactiva > 90).
    - `created_at` = `last_seen` - `created_offset_days` (>> 24h de actividad real).
    """
    now = datetime.utcnow()
    last_seen = now - timedelta(days=dias_inactiva)
    created_at = last_seen - timedelta(days=created_offset_days)
    ws = Workstation(
        id=uuid.uuid4(),
        organization_id=org.id,
        ip_private=ip_private,
        hostname=hostname,
        current_user=current_user,
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


def _ips(body) -> list:
    """Extrae la secuencia de IPs de los items en el orden devuelto."""
    return [item["ip_private"] for item in body["items"]]


# ── Tests: orden por cada columna (asc/desc) ─────────────────────────────────


class TestStaleOrdenPorColumna:
    """Req 8.1, 8.2, 8.9: ordenar por cada columna en asc/desc da el orden esperado."""

    def test_orden_por_ip_asc_y_desc(self):
        db, engine = _make_session()
        try:
            org = _make_org(db)
            # IPs deliberadamente no insertadas en orden.
            _make_stale_ws(db, org, ip_private="10.0.0.3", dias_inactiva=120)
            _make_stale_ws(db, org, ip_private="10.0.0.1", dias_inactiva=130)
            _make_stale_ws(db, org, ip_private="10.0.0.2", dias_inactiva=140)

            app = _build_app(db, _operator_user(org.id))
            client = TestClient(app)

            asc = client.get("/workstations/stale?sort_by=ip&sort_dir=asc")
            assert asc.status_code == 200, asc.text
            assert _ips(asc.json()) == ["10.0.0.1", "10.0.0.2", "10.0.0.3"]

            desc = client.get("/workstations/stale?sort_by=ip&sort_dir=desc")
            assert desc.status_code == 200, desc.text
            assert _ips(desc.json()) == ["10.0.0.3", "10.0.0.2", "10.0.0.1"]

            app.dependency_overrides.clear()
        finally:
            db.close()
            engine.dispose()

    def test_orden_por_hostname_asc_y_desc(self):
        db, engine = _make_session()
        try:
            org = _make_org(db)
            _make_stale_ws(db, org, ip_private="10.0.0.1", dias_inactiva=120, hostname="charlie")
            _make_stale_ws(db, org, ip_private="10.0.0.2", dias_inactiva=130, hostname="alpha")
            _make_stale_ws(db, org, ip_private="10.0.0.3", dias_inactiva=140, hostname="bravo")

            app = _build_app(db, _operator_user(org.id))
            client = TestClient(app)

            asc = client.get("/workstations/stale?sort_by=hostname&sort_dir=asc")
            assert asc.status_code == 200, asc.text
            hostnames_asc = [i["hostname"] for i in asc.json()["items"]]
            assert hostnames_asc == ["alpha", "bravo", "charlie"]

            desc = client.get("/workstations/stale?sort_by=hostname&sort_dir=desc")
            assert desc.status_code == 200, desc.text
            hostnames_desc = [i["hostname"] for i in desc.json()["items"]]
            assert hostnames_desc == ["charlie", "bravo", "alpha"]

            app.dependency_overrides.clear()
        finally:
            db.close()
            engine.dispose()

    def test_orden_por_current_user_asc_y_desc(self):
        db, engine = _make_session()
        try:
            org = _make_org(db)
            _make_stale_ws(db, org, ip_private="10.0.0.1", dias_inactiva=120, current_user="zeta")
            _make_stale_ws(db, org, ip_private="10.0.0.2", dias_inactiva=130, current_user="delta")
            _make_stale_ws(db, org, ip_private="10.0.0.3", dias_inactiva=140, current_user="omega")

            app = _build_app(db, _operator_user(org.id))
            client = TestClient(app)

            asc = client.get("/workstations/stale?sort_by=current_user&sort_dir=asc")
            assert asc.status_code == 200, asc.text
            users_asc = [i["current_user"] for i in asc.json()["items"]]
            assert users_asc == ["delta", "omega", "zeta"]

            desc = client.get("/workstations/stale?sort_by=current_user&sort_dir=desc")
            assert desc.status_code == 200, desc.text
            users_desc = [i["current_user"] for i in desc.json()["items"]]
            assert users_desc == ["zeta", "omega", "delta"]

            app.dependency_overrides.clear()
        finally:
            db.close()
            engine.dispose()

    def test_orden_por_organizacion_asc_y_desc(self):
        """Ordenar por nombre de organización (requiere outerjoin a Organization)."""
        db, engine = _make_session()
        try:
            org_b = _make_org(db, name="Banco Beta")
            org_a = _make_org(db, name="Banco Alfa")
            org_c = _make_org(db, name="Banco Gamma")
            _make_stale_ws(db, org_b, ip_private="10.0.0.1", dias_inactiva=120)
            _make_stale_ws(db, org_a, ip_private="10.0.0.2", dias_inactiva=130)
            _make_stale_ws(db, org_c, ip_private="10.0.0.3", dias_inactiva=140)

            # Admin ve todas las orgs → puede ordenar por nombre de org.
            app = _build_app(db, _admin_user())
            client = TestClient(app)

            asc = client.get("/workstations/stale?sort_by=organizacion&sort_dir=asc")
            assert asc.status_code == 200, asc.text
            orgs_asc = [i["organization"]["name"] for i in asc.json()["items"]]
            assert orgs_asc == ["Banco Alfa", "Banco Beta", "Banco Gamma"]

            desc = client.get("/workstations/stale?sort_by=organizacion&sort_dir=desc")
            assert desc.status_code == 200, desc.text
            orgs_desc = [i["organization"]["name"] for i in desc.json()["items"]]
            assert orgs_desc == ["Banco Gamma", "Banco Beta", "Banco Alfa"]

            app.dependency_overrides.clear()
        finally:
            db.close()
            engine.dispose()

    def test_orden_por_created_at_asc_y_desc(self):
        db, engine = _make_session()
        try:
            org = _make_org(db)
            # created_at controlado vía created_offset_days (mayor offset = created_at más antiguo).
            _make_stale_ws(db, org, ip_private="10.0.0.1", dias_inactiva=120, created_offset_days=10)
            _make_stale_ws(db, org, ip_private="10.0.0.2", dias_inactiva=120, created_offset_days=50)
            _make_stale_ws(db, org, ip_private="10.0.0.3", dias_inactiva=120, created_offset_days=30)
            # created_at = (ahora-120d) - offset → offset mayor ⇒ created_at más antiguo.
            # ASC (más antiguo primero): offset 50 (.2), 30 (.3), 10 (.1)
            app = _build_app(db, _operator_user(org.id))
            client = TestClient(app)

            asc = client.get("/workstations/stale?sort_by=created_at&sort_dir=asc")
            assert asc.status_code == 200, asc.text
            assert _ips(asc.json()) == ["10.0.0.2", "10.0.0.3", "10.0.0.1"]

            desc = client.get("/workstations/stale?sort_by=created_at&sort_dir=desc")
            assert desc.status_code == 200, desc.text
            assert _ips(desc.json()) == ["10.0.0.1", "10.0.0.3", "10.0.0.2"]

            app.dependency_overrides.clear()
        finally:
            db.close()
            engine.dispose()

    def test_orden_por_last_seen_asc_y_desc(self):
        db, engine = _make_session()
        try:
            org = _make_org(db)
            # Mayor dias_inactiva ⇒ last_seen más antiguo (menor).
            _make_stale_ws(db, org, ip_private="10.0.0.1", dias_inactiva=120)  # last_seen más reciente
            _make_stale_ws(db, org, ip_private="10.0.0.2", dias_inactiva=200)
            _make_stale_ws(db, org, ip_private="10.0.0.3", dias_inactiva=365)  # last_seen más antiguo
            app = _build_app(db, _operator_user(org.id))
            client = TestClient(app)

            # ASC en last_seen: más antiguo primero → 365, 200, 120 días.
            asc = client.get("/workstations/stale?sort_by=last_seen&sort_dir=asc")
            assert asc.status_code == 200, asc.text
            assert _ips(asc.json()) == ["10.0.0.3", "10.0.0.2", "10.0.0.1"]

            desc = client.get("/workstations/stale?sort_by=last_seen&sort_dir=desc")
            assert desc.status_code == 200, desc.text
            assert _ips(desc.json()) == ["10.0.0.1", "10.0.0.2", "10.0.0.3"]

            app.dependency_overrides.clear()
        finally:
            db.close()
            engine.dispose()

    def test_orden_por_dias_inactiva_es_inverso_de_last_seen(self):
        """
        Req 8.11: `dias_inactiva` no tiene columna física; a más días inactiva, más
        antiguo `last_seen`. Por eso `dias_inactiva DESC` ≡ `last_seen ASC`.
        """
        db, engine = _make_session()
        try:
            org = _make_org(db)
            _make_stale_ws(db, org, ip_private="10.0.0.1", dias_inactiva=120)
            _make_stale_ws(db, org, ip_private="10.0.0.2", dias_inactiva=200)
            _make_stale_ws(db, org, ip_private="10.0.0.3", dias_inactiva=365)
            app = _build_app(db, _operator_user(org.id))
            client = TestClient(app)

            # dias_inactiva DESC: más días inactiva primero → 365, 200, 120.
            desc = client.get("/workstations/stale?sort_by=dias_inactiva&sort_dir=desc")
            assert desc.status_code == 200, desc.text
            assert _ips(desc.json()) == ["10.0.0.3", "10.0.0.2", "10.0.0.1"]

            # Debe coincidir con last_seen ASC.
            ls_asc = client.get("/workstations/stale?sort_by=last_seen&sort_dir=asc")
            assert _ips(desc.json()) == _ips(ls_asc.json())

            # dias_inactiva ASC: menos días inactiva primero → 120, 200, 365.
            asc = client.get("/workstations/stale?sort_by=dias_inactiva&sort_dir=asc")
            assert asc.status_code == 200, asc.text
            assert _ips(asc.json()) == ["10.0.0.1", "10.0.0.2", "10.0.0.3"]

            # Debe coincidir con last_seen DESC.
            ls_desc = client.get("/workstations/stale?sort_by=last_seen&sort_dir=desc")
            assert _ips(asc.json()) == _ips(ls_desc.json())

            app.dependency_overrides.clear()
        finally:
            db.close()
            engine.dispose()


# ── Test: default sin params ─────────────────────────────────────────────────


class TestStaleDefaultSinParams:
    """Req 8.9: sin `sort_by`/`sort_dir` → orden `last_seen` ascendente (más antiguo primero)."""

    def test_default_es_last_seen_ascendente(self):
        db, engine = _make_session()
        try:
            org = _make_org(db)
            _make_stale_ws(db, org, ip_private="10.0.0.1", dias_inactiva=120)
            _make_stale_ws(db, org, ip_private="10.0.0.2", dias_inactiva=200)
            _make_stale_ws(db, org, ip_private="10.0.0.3", dias_inactiva=365)
            app = _build_app(db, _operator_user(org.id))
            client = TestClient(app)

            default = client.get("/workstations/stale")
            assert default.status_code == 200, default.text

            explicit = client.get("/workstations/stale?sort_by=last_seen&sort_dir=asc")
            assert _ips(default.json()) == _ips(explicit.json())
            # last_seen ASC → más antiguo (365 días) primero.
            assert _ips(default.json()) == ["10.0.0.3", "10.0.0.2", "10.0.0.1"]

            app.dependency_overrides.clear()
        finally:
            db.close()
            engine.dispose()


# ── Test: el ordenamiento se aplica antes de paginar ─────────────────────────


class TestStaleOrdenAntesDePaginar:
    """Req 8.10, 9.3: order_by va ANTES de offset/limit; páginas coherentes y sin solaparse."""

    def test_paginas_consecutivas_coherentes_y_sin_solaparse(self):
        db, engine = _make_session()
        try:
            org = _make_org(db)
            # 5 estaciones con last_seen decreciente (más días inactiva = más antiguo).
            dias = [100, 150, 200, 250, 300]
            for idx, d in enumerate(dias, start=1):
                _make_stale_ws(db, org, ip_private=f"10.0.0.{idx}", dias_inactiva=d)

            app = _build_app(db, _operator_user(org.id))
            client = TestClient(app)

            # Orden last_seen ASC (más antiguo primero): 300, 250, 200, 150, 100 días
            # → IPs 5, 4, 3, 2, 1.
            esperado = ["10.0.0.5", "10.0.0.4", "10.0.0.3", "10.0.0.2", "10.0.0.1"]

            p1 = client.get("/workstations/stale?sort_by=last_seen&sort_dir=asc&page=1&page_size=2")
            p2 = client.get("/workstations/stale?sort_by=last_seen&sort_dir=asc&page=2&page_size=2")
            p3 = client.get("/workstations/stale?sort_by=last_seen&sort_dir=asc&page=3&page_size=2")
            assert p1.status_code == p2.status_code == p3.status_code == 200

            ips_p1, ips_p2, ips_p3 = _ips(p1.json()), _ips(p2.json()), _ips(p3.json())

            # Cada página respeta el tamaño y el total es global.
            assert len(ips_p1) == 2 and len(ips_p2) == 2 and len(ips_p3) == 1
            assert p1.json()["total"] == 5

            # Sin solapamiento entre páginas.
            assert set(ips_p1).isdisjoint(ips_p2)
            assert set(ips_p2).isdisjoint(ips_p3)
            assert set(ips_p1).isdisjoint(ips_p3)

            # La concatenación reproduce el orden global (sort aplicado antes de paginar).
            assert ips_p1 + ips_p2 + ips_p3 == esperado

            app.dependency_overrides.clear()
        finally:
            db.close()
            engine.dispose()


# ── Tests: tenant isolation y filtros preservados bajo cualquier sort ────────


class TestStaleTenantIsolationBajoSort:
    """Req 9.1, 9.2, 9.4: aislamiento por inquilino preservado bajo cualquier ordenamiento."""

    def test_operador_solo_ve_su_org_bajo_cualquier_sort(self):
        db, engine = _make_session()
        try:
            org_propia = _make_org(db, name="Org Propia")
            org_ajena = _make_org(db, name="Org Ajena")
            _make_stale_ws(db, org_propia, ip_private="10.0.0.1", dias_inactiva=120)
            _make_stale_ws(db, org_propia, ip_private="10.0.0.2", dias_inactiva=200)
            # Estación de otra org: NUNCA debe aparecer para el operador.
            _make_stale_ws(db, org_ajena, ip_private="10.9.9.9", dias_inactiva=300)

            app = _build_app(db, _operator_user(org_propia.id))
            client = TestClient(app)

            # Probar bajo varias columnas y direcciones; en todas debe filtrar por org.
            for sort_by in ["ip", "hostname", "current_user", "created_at", "last_seen", "dias_inactiva"]:
                for sort_dir in ["asc", "desc"]:
                    resp = client.get(
                        f"/workstations/stale?sort_by={sort_by}&sort_dir={sort_dir}"
                    )
                    assert resp.status_code == 200, resp.text
                    body = resp.json()
                    assert body["total"] == 2, (sort_by, sort_dir, body)
                    ips = set(_ips(body))
                    assert ips == {"10.0.0.1", "10.0.0.2"}, (sort_by, sort_dir, ips)
                    assert "10.9.9.9" not in ips

            app.dependency_overrides.clear()
        finally:
            db.close()
            engine.dispose()

    def test_admin_filtrado_por_organization_id_bajo_cualquier_sort(self):
        db, engine = _make_session()
        try:
            org_a = _make_org(db, name="Org A")
            org_b = _make_org(db, name="Org B")
            _make_stale_ws(db, org_a, ip_private="10.0.0.1", dias_inactiva=120)
            _make_stale_ws(db, org_a, ip_private="10.0.0.2", dias_inactiva=200)
            _make_stale_ws(db, org_b, ip_private="10.1.0.1", dias_inactiva=300)

            app = _build_app(db, _admin_user())
            client = TestClient(app)

            # Sin filtro, admin ve ambas orgs (3 estaciones).
            todas = client.get("/workstations/stale?sort_by=last_seen&sort_dir=asc")
            assert todas.status_code == 200, todas.text
            assert todas.json()["total"] == 3

            # Filtrando por org_a, solo sus 2 estaciones bajo cualquier sort.
            for sort_by in ["ip", "created_at", "last_seen", "dias_inactiva"]:
                for sort_dir in ["asc", "desc"]:
                    resp = client.get(
                        f"/workstations/stale?organization_id={org_a.id}"
                        f"&sort_by={sort_by}&sort_dir={sort_dir}"
                    )
                    assert resp.status_code == 200, resp.text
                    body = resp.json()
                    assert body["total"] == 2, (sort_by, sort_dir, body)
                    assert set(_ips(body)) == {"10.0.0.1", "10.0.0.2"}

            app.dependency_overrides.clear()
        finally:
            db.close()
            engine.dispose()


class TestStaleFiltrosPreservadosBajoSort:
    """Req 8.4, 9.4: filtros `days`/`min_hours` intactos independientemente del sort."""

    def test_filtro_days_intacto_bajo_sort(self):
        """Estaciones con inactividad < days quedan excluidas bajo cualquier orden."""
        db, engine = _make_session()
        try:
            org = _make_org(db)
            # Inactivas (>90 días): entran.
            _make_stale_ws(db, org, ip_private="10.0.0.1", dias_inactiva=120)
            _make_stale_ws(db, org, ip_private="10.0.0.2", dias_inactiva=200)
            # Reciente (10 días < 90): NO debe entrar.
            _make_stale_ws(db, org, ip_private="10.0.0.9", dias_inactiva=10)

            app = _build_app(db, _operator_user(org.id))
            client = TestClient(app)

            for sort_dir in ["asc", "desc"]:
                resp = client.get(f"/workstations/stale?sort_by=ip&sort_dir={sort_dir}")
                assert resp.status_code == 200, resp.text
                body = resp.json()
                assert body["total"] == 2, (sort_dir, body)
                assert "10.0.0.9" not in set(_ips(body))

            # Bajar days a 5 debe incluir la reciente también.
            resp = client.get("/workstations/stale?days=5&sort_by=ip&sort_dir=asc")
            assert resp.json()["total"] == 3

            app.dependency_overrides.clear()
        finally:
            db.close()
            engine.dispose()

    def test_filtro_min_hours_intacto_bajo_sort(self):
        """Estaciones sin actividad real suficiente (last_seen-created_at) se excluyen."""
        db, engine = _make_session()
        try:
            org = _make_org(db)
            # Actividad real amplia (30 días entre created_at y last_seen): entra.
            _make_stale_ws(
                db, org, ip_private="10.0.0.1", dias_inactiva=120, created_offset_days=30
            )
            # Actividad real casi nula: created_at ~ last_seen (segundos) → NO entra con min_hours=24.
            now = datetime.utcnow()
            last_seen = now - timedelta(days=150)
            created_at = last_seen - timedelta(seconds=60)  # solo 1 min de actividad
            ws_corta = Workstation(
                id=uuid.uuid4(),
                organization_id=org.id,
                ip_private="10.0.0.8",
                is_online=False,
                last_seen=last_seen,
                created_at=created_at,
                first_seen=created_at,
                billing_status="billable",
            )
            db.add(ws_corta)
            db.commit()

            app = _build_app(db, _operator_user(org.id))
            client = TestClient(app)

            for sort_dir in ["asc", "desc"]:
                resp = client.get(f"/workstations/stale?sort_by=ip&sort_dir={sort_dir}")
                assert resp.status_code == 200, resp.text
                body = resp.json()
                assert body["total"] == 1, (sort_dir, body)
                assert set(_ips(body)) == {"10.0.0.1"}
                assert "10.0.0.8" not in set(_ips(body))

            app.dependency_overrides.clear()
        finally:
            db.close()
            engine.dispose()
