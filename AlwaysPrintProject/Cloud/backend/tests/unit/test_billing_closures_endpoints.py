"""
Tests de los endpoints de cierres mensuales (task 27) del módulo Usage and Billing.

Cubren el comportamiento de negocio de `app/api/v1/endpoints/billing_closures.py` (Req 7.2,
7.3, 7.4, 7.5, 10.3, 11.2, 11.3):

Servicio (`BillingCloseService.next_pending_period`):
1. Mes pendiente más antiguo = primer mes finalizado sin cierre desde el primer mes cerrable.
2. Tras cerrar ese mes, `next_pending_period` avanza al siguiente (uno por uno, Req 7.3).
3. Sin IPs → None; todos los meses cerrados → None; mes en curso excluido (Req 7.2).

Endpoint retroactivo (POST .../closures/retroactive):
4. Cierra el mes pendiente más antiguo y devuelve la cabecera (Req 7.2, 7.3).
5. Llamadas sucesivas cierran mayo→junio→julio… en orden (secuencialidad por construcción).
6. Sin meses pendientes → 200 con `closed = False` (idempotente, no error).
7. Solo superadmin (`require_admin`): un operador recibe 403.
8. Org inexistente → 404.
9. Capping de `last_seen` en el snapshot (Req 7.5): un `last_seen` posterior al corte queda
   capado en el ítem.

Endpoints de lectura (GET closures / items):
10. Listado de cabeceras ordenado desc; tenant isolation (operador ajeno → 403).
11. Detalle por IP paginado; cierre inexistente → 404.

Convenciones (siguiendo `tests/unit/test_billing_deletion.py`): sesión SQLite in-memory con el
esquema completo + planes por defecto sembrados, workstations a mano, y app FastAPI aislada
con `dependency_overrides` de `get_db`/`get_current_user`. El superadmin es `UserRole.ADMIN`
(organization_id = None); el operador es `UserRole.OPERATOR` ligado a una org.

_Requirements: 7.2, 7.3, 7.4, 7.5, 10.3, 11.2, 11.3_
"""

import uuid
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import get_current_user
import app.models  # noqa: F401 — registra todas las tablas en metadata
from app.models.billing import BillingClosure, BillingClosureItem
from app.models.organization import Organization
from app.models.user import User, UserRole
from app.models.workstation import Workstation
from app.api.v1.endpoints.billing_closures import router as closures_router
from app.services.billing_close_service import billing_close_service
from app.services.billing_seed import seed_default_rate_plans


# ── Fixtures y helpers ──────────────────────────────────────────────────────


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
    seed_default_rate_plans(session.connection())
    session.commit()
    return session, engine


@pytest.fixture
def db():
    """Sesión con una org en UTC (simplifica el cálculo de cortes)."""
    session, engine = _make_session()
    org = Organization(
        id=uuid.uuid4(),
        name="Org Closures Test",
        timezone="UTC",
        billing_mode="monthly",
    )
    session.add(org)
    session.commit()
    session.refresh(org)
    session._org = org
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _add_ws(
    db,
    *,
    ip_private: str,
    created_at: datetime,
    last_seen: datetime,
    billing_status: str = "new",
    organization_id=None,
) -> Workstation:
    """Inserta una workstation con los campos relevantes para el cierre."""
    ws = Workstation(
        id=uuid.uuid4(),
        organization_id=organization_id or db._org.id,
        ip_private=ip_private,
        created_at=created_at,
        first_seen=created_at,
        last_seen=last_seen,
        billing_status=billing_status,
        is_online=False,
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws


def _admin_user() -> User:
    """Superadmin: en este sistema es UserRole.ADMIN (organization_id = None)."""
    return User(
        id=uuid.uuid4(),
        email=f"admin_{uuid.uuid4().hex}@system.com",
        password_hash="x",
        full_name="Super Admin",
        role=UserRole.ADMIN,
        organization_id=None,
    )


def _operator_user(org_id) -> User:
    """Operador (no superadmin) ligado a una organización."""
    return User(
        id=uuid.uuid4(),
        email=f"op_{uuid.uuid4().hex}@bbva.com",
        password_hash="x",
        full_name="Operador",
        role=UserRole.OPERATOR,
        organization_id=org_id,
    )


def _build_client(db, current_user) -> TestClient:
    """
    Monta el router de cierres en una FastAPI aislada con overrides de auth + get_db.

    Persiste al `current_user` en la BD de prueba SOLO para superadmins: el cierre registra
    `created_by_id` con FK a `users`, así que el admin debe existir. Los operadores nunca
    crean cierres (solo lectura / 403), y además pueden apuntar a una org inexistente en los
    tests de tenant isolation, por lo que no se persisten (evita violar la FK
    `users.organization_id`). Es un detalle de infra del test, no del comportamiento probado.
    """
    if (
        current_user.role == UserRole.ADMIN
        and db.query(User).filter(User.id == current_user.id).first() is None
    ):
        db.add(current_user)
        db.commit()
    app = FastAPI()
    app.include_router(closures_router, prefix="/billing")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: current_user
    return TestClient(app)


def _freeze_current_period(monkeypatch, year: int, month: int):
    """Fija el mes en curso que ve el servicio (límite superior exclusivo de lo cerrable)."""
    monkeypatch.setattr(
        billing_close_service, "current_period", lambda org: (year, month)
    )


def _closures(db, org_id):
    """Cierres de la org ordenados por periodo asc."""
    return (
        db.query(BillingClosure)
        .filter(BillingClosure.organization_id == org_id)
        .order_by(BillingClosure.period_year.asc(), BillingClosure.period_month.asc())
        .all()
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Servicio: next_pending_period
# ─────────────────────────────────────────────────────────────────────────────


class TestNextPendingPeriod:
    """El mes pendiente más antiguo se determina desde el primer mes cerrable (Req 7.2, 7.3)."""

    def test_sin_ips_devuelve_none(self, db, monkeypatch):
        """Sin workstations no hay primer periodo cerrable → None."""
        _freeze_current_period(monkeypatch, 2026, 9)
        assert billing_close_service.next_pending_period(db, db._org) is None

    def test_primer_mes_pendiente_es_el_del_created_at_mas_antiguo(self, db, monkeypatch):
        """La IP más antigua es de mayo → el primer pendiente es mayo (Req 7.3)."""
        _add_ws(
            db,
            ip_private="10.0.0.1",
            created_at=datetime(2026, 5, 10, 12, 0),
            last_seen=datetime(2026, 5, 20, 12, 0),
        )
        _freeze_current_period(monkeypatch, 2026, 9)
        assert billing_close_service.next_pending_period(db, db._org) == (2026, 5)

    def test_avanza_uno_por_uno_tras_cerrar(self, db, monkeypatch):
        """Tras cerrar mayo, el siguiente pendiente es junio (Req 7.3)."""
        _add_ws(
            db,
            ip_private="10.0.0.1",
            created_at=datetime(2026, 5, 10, 12, 0),
            last_seen=datetime(2026, 5, 20, 12, 0),
        )
        _freeze_current_period(monkeypatch, 2026, 9)
        billing_close_service.close_month(db, db._org, 2026, 5, is_retroactive=True)
        assert billing_close_service.next_pending_period(db, db._org) == (2026, 6)

    def test_mes_en_curso_excluido(self, db, monkeypatch):
        """Con IP de septiembre y mes en curso septiembre, no hay meses finalizados (Req 7.2)."""
        _add_ws(
            db,
            ip_private="10.0.0.1",
            created_at=datetime(2026, 9, 5, 12, 0),
            last_seen=datetime(2026, 9, 6, 12, 0),
        )
        _freeze_current_period(monkeypatch, 2026, 9)
        assert billing_close_service.next_pending_period(db, db._org) is None

    def test_todos_cerrados_devuelve_none(self, db, monkeypatch):
        """Cerrados mayo..agosto y mes en curso septiembre → nada pendiente."""
        _add_ws(
            db,
            ip_private="10.0.0.1",
            created_at=datetime(2026, 5, 10, 12, 0),
            last_seen=datetime(2026, 5, 20, 12, 0),
        )
        _freeze_current_period(monkeypatch, 2026, 9)
        for m in (5, 6, 7, 8):
            billing_close_service.close_month(db, db._org, 2026, m, is_retroactive=True)
        assert billing_close_service.next_pending_period(db, db._org) is None


# ─────────────────────────────────────────────────────────────────────────────
# 2. Endpoint retroactivo (POST .../closures/retroactive)
# ─────────────────────────────────────────────────────────────────────────────


class TestRetroactiveEndpoint:
    """Cierre retroactivo: mes más antiguo, uno por uno, superadmin, capping (Req 7.2-7.5, 11.2)."""

    def test_cierra_el_mes_mas_antiguo(self, db, monkeypatch):
        """Primera llamada cierra mayo y devuelve la cabecera (Req 7.2, 7.3)."""
        _add_ws(
            db,
            ip_private="10.0.0.1",
            created_at=datetime(2026, 5, 10, 12, 0),
            last_seen=datetime(2026, 5, 20, 12, 0),
        )
        _freeze_current_period(monkeypatch, 2026, 9)
        client = _build_client(db, _admin_user())

        resp = client.post(f"/billing/organizations/{db._org.id}/closures/retroactive")

        assert resp.status_code == 200
        body = resp.json()
        assert body["closed"] is True
        assert body["closure"]["period_year"] == 2026
        assert body["closure"]["period_month"] == 5
        assert body["closure"]["is_retroactive"] is True
        assert body["closure"]["total_billable"] == 1
        # Se persistió exactamente un cierre para mayo.
        cierres = _closures(db, db._org.id)
        assert [(c.period_year, c.period_month) for c in cierres] == [(2026, 5)]

    def test_llamadas_sucesivas_cierran_en_orden(self, db, monkeypatch):
        """mayo → junio → julio: la secuencia se respeta uno por uno (Req 7.3, 7.4)."""
        _add_ws(
            db,
            ip_private="10.0.0.1",
            created_at=datetime(2026, 5, 10, 12, 0),
            last_seen=datetime(2026, 5, 20, 12, 0),
        )
        _freeze_current_period(monkeypatch, 2026, 9)
        client = _build_client(db, _admin_user())

        periodos = []
        for _ in range(3):
            resp = client.post(
                f"/billing/organizations/{db._org.id}/closures/retroactive"
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["closed"] is True
            periodos.append(
                (body["closure"]["period_year"], body["closure"]["period_month"])
            )

        assert periodos == [(2026, 5), (2026, 6), (2026, 7)]

    def test_sin_meses_pendientes_responde_closed_false(self, db, monkeypatch):
        """Sin IPs no hay nada que cerrar → 200 con closed=False (idempotente)."""
        _freeze_current_period(monkeypatch, 2026, 9)
        client = _build_client(db, _admin_user())

        resp = client.post(f"/billing/organizations/{db._org.id}/closures/retroactive")

        assert resp.status_code == 200
        body = resp.json()
        assert body["closed"] is False
        assert body["closure"] is None

    def test_operador_recibe_403(self, db, monkeypatch):
        """El retroactivo es exclusivo de superadmin (Req 11.2)."""
        _add_ws(
            db,
            ip_private="10.0.0.1",
            created_at=datetime(2026, 5, 10, 12, 0),
            last_seen=datetime(2026, 5, 20, 12, 0),
        )
        _freeze_current_period(monkeypatch, 2026, 9)
        client = _build_client(db, _operator_user(db._org.id))

        resp = client.post(f"/billing/organizations/{db._org.id}/closures/retroactive")

        assert resp.status_code == 403
        assert _closures(db, db._org.id) == []

    def test_org_inexistente_404(self, db, monkeypatch):
        """Org que no existe → 404."""
        _freeze_current_period(monkeypatch, 2026, 9)
        client = _build_client(db, _admin_user())

        resp = client.post(f"/billing/organizations/{uuid.uuid4()}/closures/retroactive")

        assert resp.status_code == 404

    def test_capping_last_seen_en_snapshot(self, db, monkeypatch):
        """
        Req 7.5: en el cierre de mayo, un last_seen posterior al corte (00:00 1-jun) queda
        capado a ese corte en el ítem del snapshot, sin tocar la columna cruda.
        """
        ws = _add_ws(
            db,
            ip_private="10.0.0.9",
            created_at=datetime(2026, 5, 10, 12, 0),
            # Actividad en agosto (posterior al mes de mayo que se cierra).
            last_seen=datetime(2026, 8, 15, 12, 0),
        )
        _freeze_current_period(monkeypatch, 2026, 9)
        client = _build_client(db, _admin_user())

        resp = client.post(f"/billing/organizations/{db._org.id}/closures/retroactive")
        assert resp.status_code == 200
        closure_id = resp.json()["closure"]["id"]

        item = (
            db.query(BillingClosureItem)
            .filter(
                BillingClosureItem.closure_id == closure_id,
                BillingClosureItem.ip_private == "10.0.0.9",
            )
            .one()
        )
        # Capado a 00:00 del 1 de junio (cutoff de mayo en UTC).
        assert item.last_seen_capped == datetime(2026, 6, 1, 0, 0)
        # La columna cruda no se modifica.
        db.refresh(ws)
        assert ws.last_seen == datetime(2026, 8, 15, 12, 0)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Endpoints de lectura (GET closures / items)
# ─────────────────────────────────────────────────────────────────────────────


class TestReadEndpoints:
    """Listado de cabeceras y detalle por IP con tenant isolation (Req 10.3, 11.3)."""

    def _seed_two_closures(self, db, monkeypatch):
        """Cierra mayo y junio para tener dos cabeceras con ítems."""
        _add_ws(
            db,
            ip_private="10.0.0.1",
            created_at=datetime(2026, 5, 10, 12, 0),
            last_seen=datetime(2026, 5, 20, 12, 0),
        )
        _add_ws(
            db,
            ip_private="10.0.0.2",
            created_at=datetime(2026, 5, 11, 12, 0),
            last_seen=datetime(2026, 6, 20, 12, 0),
        )
        _freeze_current_period(monkeypatch, 2026, 9)
        billing_close_service.close_month(db, db._org, 2026, 5, is_retroactive=True)
        return billing_close_service.close_month(
            db, db._org, 2026, 6, is_retroactive=True
        )

    def test_lista_cierres_ordenada_desc(self, db, monkeypatch):
        """Las cabeceras se listan del más reciente al más antiguo."""
        self._seed_two_closures(db, monkeypatch)
        client = _build_client(db, _admin_user())

        resp = client.get(f"/billing/organizations/{db._org.id}/closures")

        assert resp.status_code == 200
        periodos = [(c["period_year"], c["period_month"]) for c in resp.json()]
        assert periodos == [(2026, 6), (2026, 5)]

    def test_operador_ajeno_recibe_403(self, db, monkeypatch):
        """Un operador de otra org no puede listar cierres ajenos (Req 11.3)."""
        self._seed_two_closures(db, monkeypatch)
        otra_org_id = uuid.uuid4()
        client = _build_client(db, _operator_user(otra_org_id))

        resp = client.get(f"/billing/organizations/{db._org.id}/closures")

        assert resp.status_code == 403

    def test_operador_de_su_org_lista(self, db, monkeypatch):
        """Un operador de la propia org sí puede listar sus cierres (Req 11.3)."""
        self._seed_two_closures(db, monkeypatch)
        client = _build_client(db, _operator_user(db._org.id))

        resp = client.get(f"/billing/organizations/{db._org.id}/closures")

        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_detalle_items_paginado(self, db, monkeypatch):
        """El detalle por IP se pagina y reporta el total (Req 10.3)."""
        closure = self._seed_two_closures(db, monkeypatch)
        client = _build_client(db, _admin_user())

        resp = client.get(
            f"/billing/closures/{closure.id}/items",
            params={"page": 1, "page_size": 1},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert body["page"] == 1
        assert body["page_size"] == 1
        assert len(body["items"]) == 1

    def test_items_cierre_inexistente_404(self, db, monkeypatch):
        """Un cierre que no existe → 404."""
        _freeze_current_period(monkeypatch, 2026, 9)
        client = _build_client(db, _admin_user())

        resp = client.get(f"/billing/closures/{uuid.uuid4()}/items")

        assert resp.status_code == 404
