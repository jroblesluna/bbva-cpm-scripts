"""
Tests de auditoría transaccional de `RecyclePolicyService.upsert_policy` (task 7.2).

Cubren el comportamiento de negocio del persist con auditoría descrito en `design.md`
("Fail-closed Behaviors" → Auditoría transaccional) y en el Requirement 9:

1. Contenido de la auditoría en un ALTA (insert):
   - Se crea UNA fila `AuditLog` de tipo `BILLING_RECYCLE_POLICY_CHANGE` (Req 9.1).
   - `old_values` es `None` (no había política previa para ese scope+periodo) y `new_values`
     contiene la política nueva (`rule`, `ephemeral_hours`, `effective_from`, `scope`) (Req 9.2).
   - Se registra la identidad del usuario que hizo el cambio (`user_id = actor_id`) (Req 9.4).
2. Scope de la auditoría (Req 9.3):
   - Org_Override: `organization_id` = la org afectada; `new_values.scope = "Org_Override"`.
   - Global_Default: `organization_id` = None; `new_values.scope = "Global_Default"`.
3. Contenido de la auditoría en una ACTUALIZACIÓN (update) del mismo (scope, effective_key):
   - `old_values` refleja la política previa y `new_values` la nueva (Req 9.2).
4. Fail-closed (Req 9.5): si el registro de auditoría falla, `upsert_policy` hace
   `db.rollback()` y NO persiste el cambio de política: no queda ni fila de política ni de
   auditoría (no hay cambio de política sin su rastro de auditoría).

Convenciones (siguiendo `tests/unit/test_billing_close_service.py` y
`tests/properties/test_recycle_policy_resolution.py`): sesión SQLite in-memory con el esquema
completo (tipo `GUID` compat SQLite/PostgreSQL) + una `Organization` y un `User` reales para
las FK (`organization_id`, `created_by_id`/`user_id` de la auditoría).

_Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_
"""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
import app.models  # noqa: F401 — registra todas las tablas en metadata
from app.models.audit import ActionType, AuditLog
from app.models.billing import BillingRecyclePolicy
from app.models.organization import Organization
from app.models.user import User, UserRole
from app.services import audit as audit_module
from app.services.recycle_policy_service import recycle_policy_service


# ── Fixtures y helpers ──────────────────────────────────────────────────────


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


def _make_org(db, name="BBVA"):
    """Crea y commitea una Organization real para las FK del override / auditoría."""
    org = Organization(id=uuid.uuid4(), name=name, timezone="UTC", billing_mode="monthly")
    db.add(org)
    db.commit()
    return org


def _make_user(db, org_id=None):
    """Crea y commitea un User real (Superadmin/actor) para el FK de la auditoría (Req 9.4)."""
    user = User(
        id=uuid.uuid4(),
        email=f"admin-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        full_name="Super Admin",
        role=UserRole.ADMIN,
        organization_id=org_id,
    )
    db.add(user)
    db.commit()
    return user


def _audit_rows(db):
    """Devuelve todas las filas de auditoría de tipo BILLING_RECYCLE_POLICY_CHANGE."""
    return (
        db.query(AuditLog)
        .filter(AuditLog.action_type == ActionType.BILLING_RECYCLE_POLICY_CHANGE)
        .all()
    )


# ── 1. Contenido old/new en un ALTA (insert) + identidad (Req 9.1/9.2/9.4) ──


def test_insert_org_override_registra_auditoria_con_old_none_y_new_values():
    """
    Req 9.1/9.2/9.4 — Un ALTA de Org_Override:
      - crea UNA fila AuditLog BILLING_RECYCLE_POLICY_CHANGE (9.1),
      - con old_values=None y new_values = política nueva (rule/ephemeral_hours/
        effective_from/scope) (9.2),
      - registra la identidad del actor (user_id = actor_id) (9.4).
    """
    db, engine = _make_session()
    try:
        org = _make_org(db)
        actor = _make_user(db, org_id=org.id)

        policy = recycle_policy_service.upsert_policy(
            db,
            organization_id=str(org.id),
            rule_or_offsets="+1/+0/-1",
            ephemeral_hours=24,
            eff_year=2026,
            eff_month=9,
            actor_id=str(actor.id),
        )

        # La política quedó persistida.
        assert db.query(BillingRecyclePolicy).count() == 1

        # Exactamente una acción de auditoría del tipo correcto (Req 9.1).
        rows = _audit_rows(db)
        assert len(rows) == 1
        log = rows[0]
        assert log.action_type == ActionType.BILLING_RECYCLE_POLICY_CHANGE
        assert log.entity_type == "BillingRecyclePolicy"
        assert log.entity_id == policy.id  # apunta a la fila creada

        # old_values None en un alta; new_values con la política nueva (Req 9.2).
        assert log.old_values is None
        assert log.new_values["rule"] == "+1/+0/-1"
        assert log.new_values["ephemeral_hours"] == 24
        assert log.new_values["effective_from"] == "2026-09"
        assert log.new_values["scope"] == "Org_Override"

        # Identidad del usuario que hizo el cambio (Req 9.4).
        assert str(log.user_id) == str(actor.id)
    finally:
        db.close()
        engine.dispose()


# ── 2. Scope de la auditoría: org vs global (Req 9.3) ───────────────────────


def test_insert_org_override_registra_organization_id():
    """Req 9.3 — Un cambio de Org_Override registra el organization_id afectado."""
    db, engine = _make_session()
    try:
        org = _make_org(db)
        actor = _make_user(db, org_id=org.id)

        recycle_policy_service.upsert_policy(
            db,
            organization_id=str(org.id),
            rule_or_offsets="+1/+0/-1",
            ephemeral_hours=24,
            eff_year=2026,
            eff_month=9,
            actor_id=str(actor.id),
        )

        log = _audit_rows(db)[0]
        assert str(log.organization_id) == str(org.id)
        assert log.new_values["scope"] == "Org_Override"
    finally:
        db.close()
        engine.dispose()


def test_insert_global_default_registra_organization_id_none():
    """
    Req 9.3 — Un cambio del Global_Default registra la marca de global:
    organization_id = None y new_values.scope = "Global_Default".
    """
    db, engine = _make_session()
    try:
        actor = _make_user(db, org_id=None)  # Admin global (sin org)

        recycle_policy_service.upsert_policy(
            db,
            organization_id=None,  # Global_Default
            rule_or_offsets="+1/-2/-3",
            ephemeral_hours=24,
            eff_year=2000,
            eff_month=1,
            actor_id=str(actor.id),
        )

        assert db.query(BillingRecyclePolicy).count() == 1
        rows = _audit_rows(db)
        assert len(rows) == 1
        log = rows[0]
        assert log.organization_id is None
        assert log.new_values["scope"] == "Global_Default"
        assert log.new_values["rule"] == "+1/-2/-3"
        assert log.old_values is None
    finally:
        db.close()
        engine.dispose()


# ── 3. Contenido old/new en una ACTUALIZACIÓN (update) (Req 9.2) ────────────


def test_update_registra_old_values_previos_y_new_values_nuevos():
    """
    Req 9.2 — Reconfigurar el MISMO (scope, effective_key) ACTUALIZA la fila en sitio y la
    auditoría registra old_values = política previa y new_values = política nueva.
    """
    db, engine = _make_session()
    try:
        org = _make_org(db)
        actor = _make_user(db, org_id=org.id)

        # Alta inicial: +1/0/-1, 24h, 2026-09.
        first = recycle_policy_service.upsert_policy(
            db,
            organization_id=str(org.id),
            rule_or_offsets="+1/+0/-1",
            ephemeral_hours=24,
            eff_year=2026,
            eff_month=9,
            actor_id=str(actor.id),
        )
        first_id = first.id

        # Actualización del MISMO scope+periodo efectivo: -1/-2 y 48h.
        second = recycle_policy_service.upsert_policy(
            db,
            organization_id=str(org.id),
            rule_or_offsets="+1/-1/-2",
            ephemeral_hours=48,
            eff_year=2026,
            eff_month=9,
            actor_id=str(actor.id),
        )

        # UPDATE en sitio: misma fila (misma id), no una nueva.
        assert second.id == first_id
        assert db.query(BillingRecyclePolicy).count() == 1

        # Dos acciones de auditoría: la del alta y la de la actualización.
        rows = sorted(_audit_rows(db), key=lambda r: r.created_at)
        assert len(rows) == 2
        update_log = rows[-1]

        # old_values refleja la política PREVIA (+1/+0/-1, 24h, 2026-09).
        assert update_log.old_values is not None
        assert update_log.old_values["rule"] == "+1/+0/-1"
        assert update_log.old_values["ephemeral_hours"] == 24
        assert update_log.old_values["effective_from"] == "2026-09"

        # new_values refleja la política NUEVA (+1/-1/-2, 48h).
        assert update_log.new_values["rule"] == "+1/-1/-2"
        assert update_log.new_values["ephemeral_hours"] == 48
        assert update_log.new_values["effective_from"] == "2026-09"
        assert update_log.new_values["scope"] == "Org_Override"

        # La fila persistida quedó con los valores nuevos.
        row = db.query(BillingRecyclePolicy).one()
        assert (row.cutoff_offset, row.cut1_offset, row.cut2_offset) == (1, -1, -2)
        assert row.ephemeral_hours == 48
    finally:
        db.close()
        engine.dispose()


# ── 4. Fail-closed: fallo de auditoría → rollback del cambio (Req 9.5) ──────


def test_fallo_de_auditoria_revierte_el_cambio_de_politica(monkeypatch):
    """
    Req 9.5 — Si el registro de auditoría falla, el cambio de política se revierte
    (db.rollback) y NO queda persistido: ni fila de política ni fila de auditoría.

    Se simula el fallo de auditoría monkeypatcheando `AuditService.log_action` para que lance,
    imitando un error al registrar el rastro (p. ej. fallo del commit de la auditoría).
    """
    db, engine = _make_session()
    try:
        org = _make_org(db)
        actor = _make_user(db, org_id=org.id)

        def _boom(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            raise RuntimeError("fallo simulado del registro de auditoría")

        # upsert_policy importa AuditService dentro de la función (import diferido) desde
        # app.services.audit, por lo que parchear la clase en ese módulo intercepta la llamada.
        monkeypatch.setattr(audit_module.AuditService, "log_action", _boom)

        with pytest.raises(RuntimeError, match="fallo simulado"):
            recycle_policy_service.upsert_policy(
                db,
                organization_id=str(org.id),
                rule_or_offsets="+1/+0/-1",
                ephemeral_hours=24,
                eff_year=2026,
                eff_month=9,
                actor_id=str(actor.id),
            )

        # Fail-closed: ni política ni auditoría quedaron persistidas (Req 9.5).
        db.expire_all()
        assert db.query(BillingRecyclePolicy).count() == 0, (
            "El cambio de política NO debe persistir si la auditoría falla (fail-closed)."
        )
        assert len(_audit_rows(db)) == 0, (
            "No debe quedar rastro de auditoría del cambio revertido (fail-closed)."
        )
    finally:
        db.close()
        engine.dispose()


def test_fallo_de_auditoria_no_afecta_politica_previa_persistida(monkeypatch):
    """
    Req 9.5 + 7.9 — Si ya existe una política válida y una NUEVA actualización falla al
    auditar, el rollback deja intacta la política previamente persistida (no se corrompe ni
    se pierde el commit anterior).
    """
    db, engine = _make_session()
    try:
        org = _make_org(db)
        actor = _make_user(db, org_id=org.id)

        # Alta inicial exitosa (auditoría real).
        recycle_policy_service.upsert_policy(
            db,
            organization_id=str(org.id),
            rule_or_offsets="+1/+0/-1",
            ephemeral_hours=24,
            eff_year=2026,
            eff_month=9,
            actor_id=str(actor.id),
        )
        assert db.query(BillingRecyclePolicy).count() == 1

        # Ahora la auditoría falla en la actualización.
        def _boom(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            raise RuntimeError("fallo simulado del registro de auditoría")

        monkeypatch.setattr(audit_module.AuditService, "log_action", _boom)

        with pytest.raises(RuntimeError, match="fallo simulado"):
            recycle_policy_service.upsert_policy(
                db,
                organization_id=str(org.id),
                rule_or_offsets="+1/-1/-2",
                ephemeral_hours=48,
                eff_year=2026,
                eff_month=9,
                actor_id=str(actor.id),
            )

        # La política previa (+1/0/-1, 24h) sigue intacta; no se aplicó la actualización.
        db.expire_all()
        row = db.query(BillingRecyclePolicy).one()
        assert (row.cutoff_offset, row.cut1_offset, row.cut2_offset) == (1, 0, -1)
        assert row.ephemeral_hours == 24
        # Solo la auditoría del alta inicial (la de la actualización se revirtió).
        assert len(_audit_rows(db)) == 1
    finally:
        db.close()
        engine.dispose()
