"""
Integration tests de los endpoints de la Política de Reciclaje (recycle-policy-config, task 8.3).

Cubren el comportamiento de negocio de `app/api/v1/endpoints/recycle_policy.py` (Req 8.1, 8.2,
17.1, 17.2, 17.4, 17.5):

Global_Default (GET/PUT `/billing/recycle-policy/global`):
1. PUT con Superadmin + body válido → 200; la salida trae `rule=="+1/-2/-3"`,
   `effective_from=="2000-01"` (formato "AAAA-MM", Req 17.4) y `scope=="global"`.
2. GET con Superadmin → 200 y la política recién creada aparece en la lista.

Org_Override (GET/PUT `/billing/recycle-policy/org/{organization_id}`):
3. PUT con Superadmin + body válido → 200; `scope=="org"`, `organization_id` seteado,
   regla formateada y `effective_from` "AAAA-MM" (Req 17.4).
4. GET con Superadmin → 200 y lista con el override creado.
5. Org inexistente en GET/PUT org → 404.

Permisos (Req 8.2/17.2): un operador (no superadmin) recibe 403 en los cuatro endpoints.

Validación (Req 17.5):
6. Body que pasa el formato del schema pero VIOLA la semántica del servicio (p. ej. "+1/+2/+3",
   que rompe el orden `cutoff > cut1 >= cut2` y el rango de offsets) → 422 con
   `detail.errors` = LISTA de `{rule, message}`, una entrada por regla violada.
7. Body con formato inválido a nivel schema (p. ej. "1/-2/-3" sin signo explícito) → 422
   (rechazo de Pydantic antes de llegar al servicio).

Convenciones (siguiendo `tests/unit/test_billing_closures_endpoints.py`): sesión SQLite
in-memory con el esquema completo, app FastAPI aislada con `dependency_overrides` de
`get_db`/`get_current_user`. El superadmin es `UserRole.ADMIN` (organization_id = None); el
operador es `UserRole.OPERATOR` ligado a una org. El admin se persiste en la BD para satisfacer
la FK `created_by_id` (actor_id del upsert de la política).

_Requirements: 8.1, 8.2, 17.1, 17.2, 17.4, 17.5_
"""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import get_current_user
import app.models  # noqa: F401 — registra todas las tablas en metadata
from app.models.billing import BillingRecyclePolicy
from app.models.organization import Organization
from app.models.user import User, UserRole
from app.api.v1.endpoints.recycle_policy import router as recycle_policy_router


# ── Fixtures y helpers ──────────────────────────────────────────────────────


def _make_session():
    """
    Crea una sesión SQLite in-memory con el esquema completo.

    No se siembran planes de tarifa: la Recycle_Policy no los necesita (a diferencia de los
    cierres). El esquema completo basta para cubrir la tabla `billing_recycle_policies`, las
    FKs a `organizations`/`users` y el registro de auditoría del upsert.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    return session, engine


@pytest.fixture
def db():
    """Sesión con una org en UTC (el scope Org_Override apunta a ella)."""
    session, engine = _make_session()
    org = Organization(
        id=uuid.uuid4(),
        name="Org Recycle Test",
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
    Monta el router de recycle-policy en una FastAPI aislada con overrides de auth + get_db.

    Persiste al `current_user` en la BD SOLO para superadmins: `upsert_policy` graba
    `created_by_id` con FK a `users`, así que el admin debe existir. Los operadores nunca
    persisten políticas (solo reciben 403) y en algunos tests apuntan a orgs ajenas, por lo que
    no se persisten (evita violar la FK `users.organization_id`). Es un detalle de infra del
    test, no del comportamiento probado.
    """
    if (
        current_user.role == UserRole.ADMIN
        and db.query(User).filter(User.id == current_user.id).first() is None
    ):
        db.add(current_user)
        db.commit()
    app = FastAPI()
    app.include_router(recycle_policy_router, prefix="/billing")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: current_user
    return TestClient(app)


def _valid_body(rule="+1/-2/-3", ephemeral_hours=24, year=2000, month=1) -> dict:
    """Body válido por defecto para PUT (regla legacy `+1/-2/-3`, `2000-01`)."""
    return {
        "rule": rule,
        "ephemeral_hours": ephemeral_hours,
        "effective_from_year": year,
        "effective_from_month": month,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. Global_Default (GET/PUT /billing/recycle-policy/global)
# ─────────────────────────────────────────────────────────────────────────────


class TestGlobalPolicyEndpoints:
    """PUT/GET del Global_Default con Superadmin (Req 8.1, 17.1, 17.4)."""

    def test_put_global_valido_devuelve_200_y_formato(self, db):
        """
        PUT con admin + body válido → 200; salida con `rule=="+1/-2/-3"`,
        `effective_from=="2000-01"` (AAAA-MM) y `scope=="global"` (Req 17.4).
        """
        client = _build_client(db, _admin_user())

        resp = client.put("/billing/recycle-policy/global", json=_valid_body())

        assert resp.status_code == 200
        body = resp.json()
        assert body["rule"] == "+1/-2/-3"
        assert body["effective_from"] == "2000-01"
        assert body["scope"] == "global"
        assert body["organization_id"] is None
        assert body["ephemeral_hours"] == 24
        # Se persistió exactamente una política global.
        rows = (
            db.query(BillingRecyclePolicy)
            .filter(BillingRecyclePolicy.organization_id.is_(None))
            .all()
        )
        assert len(rows) == 1

    def test_get_global_lista_la_politica_creada(self, db):
        """GET con admin → 200 y la política recién creada aparece en la lista (Req 8.1)."""
        client = _build_client(db, _admin_user())
        put = client.put("/billing/recycle-policy/global", json=_valid_body())
        assert put.status_code == 200
        created_id = put.json()["id"]

        resp = client.get("/billing/recycle-policy/global")

        assert resp.status_code == 200
        lista = resp.json()
        assert isinstance(lista, list)
        ids = [p["id"] for p in lista]
        assert created_id in ids
        creada = next(p for p in lista if p["id"] == created_id)
        assert creada["scope"] == "global"
        assert creada["rule"] == "+1/-2/-3"
        assert creada["effective_from"] == "2000-01"

    def test_operador_recibe_403_en_global(self, db):
        """El GET/PUT global es exclusivo de superadmin (Req 8.2/17.2)."""
        client = _build_client(db, _operator_user(db._org.id))

        get_resp = client.get("/billing/recycle-policy/global")
        put_resp = client.put("/billing/recycle-policy/global", json=_valid_body())

        assert get_resp.status_code == 403
        assert put_resp.status_code == 403
        # Nada se persistió.
        assert db.query(BillingRecyclePolicy).count() == 0


# ─────────────────────────────────────────────────────────────────────────────
# 2. Org_Override (GET/PUT /billing/recycle-policy/org/{organization_id})
# ─────────────────────────────────────────────────────────────────────────────


class TestOrgPolicyEndpoints:
    """PUT/GET del Org_Override con Superadmin y 404 por org inexistente (Req 8.1, 17.1, 17.4)."""

    def test_put_org_valido_devuelve_200_y_scope_org(self, db):
        """
        PUT con admin + body válido → 200; `scope=="org"`, `organization_id` seteado, regla
        formateada y `effective_from` "AAAA-MM" (Req 17.4).
        """
        client = _build_client(db, _admin_user())

        resp = client.put(
            f"/billing/recycle-policy/org/{db._org.id}",
            json=_valid_body(rule="+1/+0/-1", month=9, year=2026),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["scope"] == "org"
        assert body["organization_id"] == str(db._org.id)
        assert body["rule"] == "+1/+0/-1"  # signo explícito en los tres offsets
        assert body["effective_from"] == "2026-09"
        assert body["ephemeral_hours"] == 24

    def test_get_org_lista_el_override_creado(self, db):
        """GET con admin → 200 y lista con el override creado (Req 8.1)."""
        client = _build_client(db, _admin_user())
        put = client.put(
            f"/billing/recycle-policy/org/{db._org.id}",
            json=_valid_body(rule="+1/+0/-1", month=9, year=2026),
        )
        assert put.status_code == 200
        created_id = put.json()["id"]

        resp = client.get(f"/billing/recycle-policy/org/{db._org.id}")

        assert resp.status_code == 200
        lista = resp.json()
        assert isinstance(lista, list)
        assert [p["id"] for p in lista] == [created_id]
        assert lista[0]["scope"] == "org"
        assert lista[0]["organization_id"] == str(db._org.id)
        assert lista[0]["effective_from"] == "2026-09"

    def test_operador_recibe_403_en_org(self, db):
        """El GET/PUT org es exclusivo de superadmin (Req 8.2/17.2)."""
        client = _build_client(db, _operator_user(db._org.id))

        get_resp = client.get(f"/billing/recycle-policy/org/{db._org.id}")
        put_resp = client.put(
            f"/billing/recycle-policy/org/{db._org.id}", json=_valid_body()
        )

        assert get_resp.status_code == 403
        assert put_resp.status_code == 403
        assert db.query(BillingRecyclePolicy).count() == 0

    def test_get_org_inexistente_404(self, db):
        """GET sobre una org que no existe → 404."""
        client = _build_client(db, _admin_user())

        resp = client.get(f"/billing/recycle-policy/org/{uuid.uuid4()}")

        assert resp.status_code == 404

    def test_put_org_inexistente_404(self, db):
        """PUT sobre una org que no existe → 404 (no se persiste)."""
        client = _build_client(db, _admin_user())

        resp = client.put(
            f"/billing/recycle-policy/org/{uuid.uuid4()}", json=_valid_body()
        )

        assert resp.status_code == 404
        assert db.query(BillingRecyclePolicy).count() == 0


# ─────────────────────────────────────────────────────────────────────────────
# 3. Validación: errores por regla (Req 17.5) y formato de schema (Req 7.1)
# ─────────────────────────────────────────────────────────────────────────────


class TestPolicyValidationErrors:
    """La API devuelve una lista explícita de errores por regla violada (Req 17.5)."""

    def test_semantica_invalida_devuelve_422_con_lista_de_errores(self, db):
        """
        Body que pasa el FORMATO del schema pero viola la semántica del servicio ("+1/+2/+3":
        rompe el orden `cutoff > cut1 >= cut2` y el rango de offsets `[-24, +1]`) → 422 con
        `detail.errors` = LISTA de `{rule, message}`, una entrada por regla violada (Req 17.5).
        """
        client = _build_client(db, _admin_user())

        resp = client.put(
            "/billing/recycle-policy/global",
            json=_valid_body(rule="+1/+2/+3"),
        )

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert isinstance(detail, dict)
        assert isinstance(detail["errors"], list)
        # Cada entrada es {rule, message}.
        for err in detail["errors"]:
            assert set(err.keys()) == {"rule", "message"}
            assert isinstance(err["message"], str) and err["message"]
        reglas = {e["rule"] for e in detail["errors"]}
        # "+1/+2/+3" viola el orden y el rango de offsets (dos reglas distintas).
        assert "order" in reglas
        assert "offset_range" in reglas
        # No se persistió nada (fail-closed).
        assert db.query(BillingRecyclePolicy).count() == 0

    def test_una_sola_regla_violada_reporta_una_entrada(self, db):
        """
        "-1/-2/-3": formato válido, orden válido (`-1 > -2 >= -3`), offsets en rango, pero
        `cutoff < +1` → 422 con exactamente una entrada de regla `cutoff_min` (Req 17.5).
        """
        client = _build_client(db, _admin_user())

        resp = client.put(
            "/billing/recycle-policy/global",
            json=_valid_body(rule="-1/-2/-3"),
        )

        assert resp.status_code == 422
        errores = resp.json()["detail"]["errors"]
        assert [e["rule"] for e in errores] == ["cutoff_min"]
        assert db.query(BillingRecyclePolicy).count() == 0

    def test_formato_invalido_schema_devuelve_422(self, db):
        """
        Regla sin signo explícito ("1/-2/-3") es rechazada por el schema (Pydantic) antes de
        llegar al servicio → 422 (Req 7.1).
        """
        client = _build_client(db, _admin_user())

        resp = client.put(
            "/billing/recycle-policy/global",
            json=_valid_body(rule="1/-2/-3"),
        )

        assert resp.status_code == 422
        assert db.query(BillingRecyclePolicy).count() == 0
