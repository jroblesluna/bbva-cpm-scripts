"""
Tests de eliminación/archivado de workstations del módulo Usage and Billing (task 24).

Cubren la restricción de eliminación (Req 3.1–3.6) en dos niveles:

1. Servicio `app/services/billing_deletion_service.py`
   (`billing_deletion_service.delete_or_archive`):
   - `billing_status == 'new'`                 → outcome "deleted" (borrado físico) — Req 3.1.
   - `billing_status != 'new'` y OFFLINE       → outcome "archived" (soft-delete)   — Req 3.2.
   - `billing_status != 'new'` y ONLINE        → outcome "rejected", reason "online" — Req 3.2/3.3.
   - El servicio NO commitea: la transacción la controla el caller (Req 3.4/3.5).

2. Endpoints de `app/api/v1/endpoints/workstations.py`:
   - DELETE `/{workstation_id}` (borrado individual, usa el servicio) — Req 3.1–3.4.
     · 'new'            → 204 y la fila desaparece.
     · no-'new' offline → 204 y la fila queda archivada (billing_status='archived').
     · no-'new' online  → 409 y la fila queda intacta.
     · operador sobre ws de otra org → 403 (regla del endpoint individual).
   - POST `/bulk-delete` (borrado masivo con reporte) — Req 3.5, 3.6.
     · lote mixto (new + no-new offline + no-new online + id inexistente) → desglose completo.
     · aislamiento multi-tenant: el id de otra org cae en `not_found`.
     · transacción única: el estado final de la BD coincide con el reporte.

Convenciones (siguiendo `tests/unit/test_billing_service.py` y
`tests/unit/test_billing_annual_service.py`): sesión SQLite in-memory con el esquema completo,
filas `Workstation` a mano, y tests de endpoint sobre una `FastAPI` aislada con
`dependency_overrides` de `get_db`/`get_current_user`. El superadmin es `UserRole.ADMIN` con
`organization_id = None`; el operador es `UserRole.OPERATOR` ligado a una org.

_Requirements: 3.1–3.6_
"""

import uuid
from datetime import datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import get_current_user
import app.models  # noqa: F401 — registra todas las tablas en metadata (incluye audit_logs)
from app.models.organization import Organization
from app.models.user import User, UserRole
from app.models.workstation import Workstation
from app.api.v1.endpoints.workstations import router as workstations_router
from app.services.billing_deletion_service import (
    OUTCOME_ARCHIVED,
    OUTCOME_DELETED,
    OUTCOME_REJECTED,
    REASON_ONLINE,
    billing_deletion_service,
)


# ── Fixtures y helpers ──────────────────────────────────────────────────────


def _make_session():
    """Crea una sesión SQLite in-memory con el esquema completo."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    return session, engine


def _make_org(db, *, name: str) -> Organization:
    """Crea y persiste una organización mensual."""
    org = Organization(
        id=uuid.uuid4(),
        name=name,
        timezone="UTC",
        billing_mode="monthly",
    )
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


@pytest.fixture
def db():
    """Sesión con una organización principal para las workstations de prueba."""
    session, engine = _make_session()
    session._org = _make_org(session, name="Org Deletion Test")
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _add_ws(
    db,
    *,
    ip_private: str,
    billing_status: str,
    is_online: bool = False,
    organization_id=None,
) -> Workstation:
    """Inserta una workstation con los campos relevantes para la restricción de borrado."""
    now = datetime(2026, 1, 1, 12, 0, 0)
    ws = Workstation(
        id=uuid.uuid4(),
        organization_id=organization_id or db._org.id,
        ip_private=ip_private,
        hostname=f"host-{ip_private}",
        created_at=now,
        first_seen=now,
        last_seen=now,
        billing_status=billing_status,
        is_online=is_online,
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


def _build_app(db, current_user) -> FastAPI:
    """
    Monta el router de workstations en una FastAPI aislada con overrides de auth + get_db.

    Usa la sesión SQLite real `db` para ejercer de verdad la lógica de query del endpoint y
    del servicio de eliminación (patrón de `test_billing_service.py`).

    Persiste al `current_user` en la BD de prueba: los endpoints de borrado registran una
    entrada de auditoría (`audit_logs`) con FK a `users`; sin la fila del usuario, el
    `INSERT` fallaría por FOREIGN KEY. Es un detalle de infraestructura del test (la auth real
    ya garantiza que el usuario existe en producción), no parte del comportamiento bajo prueba.
    """
    if db.query(User).filter(User.id == current_user.id).first() is None:
        db.add(current_user)
        db.commit()
    app = FastAPI()
    app.include_router(workstations_router, prefix="/workstations")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: current_user
    return app


def _exists(db, ws_id) -> bool:
    """True si la fila de la workstation sigue existiendo en BD."""
    return (
        db.query(Workstation).filter(Workstation.id == ws_id).first() is not None
    )


def _status_of(db, ws_id):
    """Devuelve el billing_status persistido de una workstation (o None si no existe)."""
    ws = db.query(Workstation).filter(Workstation.id == ws_id).first()
    return ws.billing_status if ws else None


# ─────────────────────────────────────────────────────────────────────────────
# 1. Servicio delete_or_archive — los 3 casos + no-commit (Req 3.1–3.3)
# ─────────────────────────────────────────────────────────────────────────────


class TestDeleteOrArchiveServicio:
    """Los 3 caminos de la restricción y la garantía de que el servicio no commitea."""

    def test_new_se_elimina_fisicamente(self, db):
        """'new' → outcome 'deleted'; tras el commit del caller la fila desaparece (Req 3.1)."""
        ws = _add_ws(db, ip_private="10.0.0.1", billing_status="new", is_online=False)
        ws_id = ws.id

        result = billing_deletion_service.delete_or_archive(db, ws)

        assert result.outcome == OUTCOME_DELETED
        assert result.ip_private == "10.0.0.1"
        # El servicio no commitea; el caller confirma el borrado físico.
        db.commit()
        assert _exists(db, ws_id) is False

    def test_billable_offline_se_archiva(self, db):
        """'billable' + offline → outcome 'archived'; la fila persiste con billing_status='archived' (Req 3.2)."""
        ws = _add_ws(db, ip_private="10.0.0.2", billing_status="billable", is_online=False)
        ws_id = ws.id

        result = billing_deletion_service.delete_or_archive(db, ws)

        assert result.outcome == OUTCOME_ARCHIVED
        assert ws.billing_status == "archived"
        db.commit()
        # La fila sigue existiendo (soft-delete), ahora archivada.
        assert _exists(db, ws_id) is True
        assert _status_of(db, ws_id) == "archived"

    def test_recycled_offline_se_archiva(self, db):
        """'recycled' + offline → outcome 'archived' (transición recycled→archived válida, Req 3.2)."""
        ws = _add_ws(db, ip_private="10.0.0.3", billing_status="recycled", is_online=False)
        ws_id = ws.id

        result = billing_deletion_service.delete_or_archive(db, ws)

        assert result.outcome == OUTCOME_ARCHIVED
        assert ws.billing_status == "archived"
        db.commit()
        assert _status_of(db, ws_id) == "archived"

    def test_no_new_online_se_rechaza(self, db):
        """
        no-'new' + online → outcome 'rejected', reason 'online'; la ws queda intacta
        (mismo billing_status, sin archivar ni borrar) (Req 3.2, 3.3).
        """
        ws = _add_ws(db, ip_private="10.0.0.4", billing_status="billable", is_online=True)
        ws_id = ws.id

        result = billing_deletion_service.delete_or_archive(db, ws)

        assert result.outcome == OUTCOME_REJECTED
        assert result.reason == REASON_ONLINE
        # Sin cambios: sigue 'billable' y sigue existiendo.
        assert ws.billing_status == "billable"
        db.commit()
        assert _exists(db, ws_id) is True
        assert _status_of(db, ws_id) == "billable"

    def test_servicio_no_commitea_puede_revertirse(self, db):
        """
        El servicio NO commitea: el caller controla la transacción. Un rollback tras
        `delete_or_archive` debe deshacer la mutación (confirma que no hubo commit interno).
        """
        ws = _add_ws(db, ip_private="10.0.0.5", billing_status="billable", is_online=False)
        ws_id = ws.id

        result = billing_deletion_service.delete_or_archive(db, ws)
        assert result.outcome == OUTCOME_ARCHIVED

        # Sin commit del caller: se revierte el archivado.
        db.rollback()
        assert _status_of(db, ws_id) == "billable"

    def test_servicio_no_commitea_delete_reversible(self, db):
        """El borrado físico también queda pendiente hasta el commit del caller (rollback lo revierte)."""
        ws = _add_ws(db, ip_private="10.0.0.6", billing_status="new", is_online=False)
        ws_id = ws.id

        billing_deletion_service.delete_or_archive(db, ws)
        # Sin commit: la fila 'new' aún puede recuperarse con rollback.
        db.rollback()
        assert _exists(db, ws_id) is True


# ─────────────────────────────────────────────────────────────────────────────
# 2. Endpoint DELETE individual — 204 delete/archive, 409 online, 403 tenant
# ─────────────────────────────────────────────────────────────────────────────


class TestDeleteIndividualEndpoint:
    """DELETE /workstations/{id} usando el servicio de eliminación (Req 3.1–3.4)."""

    @pytest.mark.asyncio
    async def test_delete_new_204_y_fila_eliminada(self, db):
        """DELETE de una 'new' → 204 y la fila desaparece (Req 3.1)."""
        ws = _add_ws(db, ip_private="10.1.0.1", billing_status="new", is_online=False)
        ws_id = ws.id
        app = _build_app(db, _admin_user())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete(f"/workstations/{ws_id}")
        assert resp.status_code == 204
        assert _exists(db, ws_id) is False
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_delete_no_new_offline_204_y_archivada(self, db):
        """DELETE de una no-'new' offline → 204 y la fila queda archivada (Req 3.2)."""
        ws = _add_ws(db, ip_private="10.1.0.2", billing_status="billable", is_online=False)
        ws_id = ws.id
        app = _build_app(db, _admin_user())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete(f"/workstations/{ws_id}")
        assert resp.status_code == 204
        assert _exists(db, ws_id) is True
        assert _status_of(db, ws_id) == "archived"
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_delete_no_new_online_409_y_sin_cambios(self, db):
        """DELETE de una no-'new' online → 409 y la fila intacta (Req 3.3)."""
        ws = _add_ws(db, ip_private="10.1.0.3", billing_status="billable", is_online=True)
        ws_id = ws.id
        app = _build_app(db, _admin_user())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete(f"/workstations/{ws_id}")
        assert resp.status_code == 409
        # La fila no cambió: sigue existiendo y 'billable'.
        assert _exists(db, ws_id) is True
        assert _status_of(db, ws_id) == "billable"
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_operador_no_puede_borrar_ws_de_otra_org_403(self, db):
        """
        Un operador no puede borrar una workstation de otra organización: el endpoint
        individual responde 403 (regla de permisos vigente) y la fila queda intacta.
        """
        otra_org = _make_org(db, name="Otra Org")
        ws = _add_ws(
            db,
            ip_private="10.1.0.4",
            billing_status="new",
            is_online=False,
            organization_id=otra_org.id,
        )
        ws_id = ws.id
        # Operador de la org principal (db._org), NO de otra_org.
        app = _build_app(db, _operator_user(db._org.id))
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete(f"/workstations/{ws_id}")
        assert resp.status_code == 403
        # No se borró la ws ajena.
        assert _exists(db, ws_id) is True
        app.dependency_overrides.clear()


# ─────────────────────────────────────────────────────────────────────────────
# 3. Endpoint POST /bulk-delete — lote mixto, aislamiento y transacción única
# ─────────────────────────────────────────────────────────────────────────────


class TestBulkDeleteEndpoint:
    """POST /workstations/bulk-delete con reporte de desglose (Req 3.5, 3.6)."""

    @pytest.mark.asyncio
    async def test_lote_mixto_desglose_completo(self, db):
        """
        Lote mixto (Req 3.5): una 'new', una no-'new' offline, una no-'new' online y un id
        inexistente → el reporte clasifica cada una en su categoría.
        """
        ws_new = _add_ws(db, ip_private="10.2.0.1", billing_status="new", is_online=False)
        ws_off = _add_ws(db, ip_private="10.2.0.2", billing_status="billable", is_online=False)
        ws_on = _add_ws(db, ip_private="10.2.0.3", billing_status="recycled", is_online=True)
        bogus_id = uuid.uuid4()

        app = _build_app(db, _admin_user())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/workstations/bulk-delete",
                json={
                    "workstation_ids": [
                        str(ws_new.id),
                        str(ws_off.id),
                        str(ws_on.id),
                        str(bogus_id),
                    ]
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        # 'new' → deleted (por IP).
        assert body["deleted"] == ["10.2.0.1"]
        # no-'new' offline → archived.
        assert body["archived"] == ["10.2.0.2"]
        # no-'new' online → rejected con motivo 'online'.
        assert body["rejected"] == [{"ip": "10.2.0.3", "reason": REASON_ONLINE}]
        # id inexistente → not_found.
        assert body["not_found"] == [str(bogus_id)]
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_aislamiento_multitenant_id_de_otra_org_en_not_found(self, db):
        """
        Aislamiento (Req 3.4): la ws de otra organización NO se procesa; su id aparece en
        `not_found` (no revela su existencia ni la borra/archiva).
        """
        otra_org = _make_org(db, name="Otra Org Bulk")
        ws_ajena = _add_ws(
            db,
            ip_private="10.2.1.1",
            billing_status="new",
            is_online=False,
            organization_id=otra_org.id,
        )
        ws_propia = _add_ws(db, ip_private="10.2.1.2", billing_status="new", is_online=False)

        app = _build_app(db, _operator_user(db._org.id))
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/workstations/bulk-delete",
                json={"workstation_ids": [str(ws_ajena.id), str(ws_propia.id)]},
            )

        assert resp.status_code == 200
        body = resp.json()
        # La ws ajena no se procesó: aparece en not_found y sigue existiendo.
        assert str(ws_ajena.id) in body["not_found"]
        assert "10.2.1.1" not in body["deleted"]
        assert _exists(db, ws_ajena.id) is True
        # La ws propia sí se eliminó.
        assert body["deleted"] == ["10.2.1.2"]
        assert _exists(db, ws_propia.id) is False
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_transaccion_unica_estado_bd_coincide_con_reporte(self, db):
        """
        Transacción única (Req 3.5): tras el bulk-delete el estado de la BD coincide con el
        reporte — las 'deleted' desaparecen, las 'archived' tienen billing_status='archived',
        y las rejected/online quedan intactas.
        """
        ws_new = _add_ws(db, ip_private="10.2.2.1", billing_status="new", is_online=False)
        ws_off = _add_ws(db, ip_private="10.2.2.2", billing_status="billable", is_online=False)
        ws_on = _add_ws(db, ip_private="10.2.2.3", billing_status="billable", is_online=True)

        app = _build_app(db, _admin_user())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/workstations/bulk-delete",
                json={
                    "workstation_ids": [str(ws_new.id), str(ws_off.id), str(ws_on.id)]
                },
            )

        assert resp.status_code == 200
        body = resp.json()

        # Estado de BD coherente con el reporte.
        # deleted → fila eliminada.
        assert body["deleted"] == ["10.2.2.1"]
        assert _exists(db, ws_new.id) is False
        # archived → fila persiste con billing_status='archived'.
        assert body["archived"] == ["10.2.2.2"]
        assert _status_of(db, ws_off.id) == "archived"
        # rejected/online → fila intacta (sigue 'billable').
        assert body["rejected"] == [{"ip": "10.2.2.3", "reason": REASON_ONLINE}]
        assert _exists(db, ws_on.id) is True
        assert _status_of(db, ws_on.id) == "billable"
        app.dependency_overrides.clear()
