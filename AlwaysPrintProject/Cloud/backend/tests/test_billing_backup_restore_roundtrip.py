"""
Test de round-trip backup→restore de las columnas y la tabla nuevas del feature
`recycle-policy-config`.

Complementa a `test_billing_backup_restore_tables.py` (que solo valida presencia y
orden de FK en `TABLE_MODEL_MAP`) ejerciendo el flujo REAL de export/import de datos:

    seed (BD origen) → BackupService._export_table → JSON dump/load → RestoreService
    ._restore_orm_table (BD destino limpia) → read-back y aserciones de igualdad

El `json.dumps`/`json.loads` intermedio reproduce fielmente el viaje por el ZIP del
backup (los servicios serializan a JSON antes de comprimir y lo re-parsean al
restaurar), incluyendo la conversión de tipos de ida (`_convert_value`: UUID/datetime→str,
JSON dict tal cual) y de vuelta (`_convert_record`: str→UUID/datetime, JSON dict tal cual).

Se verifica que un round-trip preserva:
- `workstations.billing_cycle_started_at` (columna nueva, distinta de created_at)
- `billing_closures.recycle_policy_applied` (freeze JSON de la política congelada)
- las filas de `billing_recycle_policies` (offsets, ephemeral_hours, periodo efectivo,
  effective_key y scope global/override)

Validates: Requirements 18.7, 4.4
"""

import json
import uuid
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
import app.models  # noqa: F401 — registra todas las tablas en metadata
from app.models.billing import BillingClosure, BillingRecyclePolicy
from app.models.organization import Organization
from app.models.user import User, UserRole
from app.models.workstation import Workstation
from app.services.backup_service import BackupService
from app.services.restore_service import RestoreService


# === SESIÓN SQLITE IN-MEMORY (patrón del resto de los tests del repo) ===


def _make_session():
    """Crea una sesión SQLite in-memory aislada con el esquema completo (tipo GUID compat)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return Session(), engine


# === SERVICIOS SIN BOTO3 ===
#
# BackupService/RestoreService.__init__ instancian clientes boto3/S3 que no queremos ni
# necesitamos para ejercer solo el export/import de tablas. Los creamos con __new__ para
# saltar el __init__ y usar únicamente los métodos puros de (de)serialización de filas.
_backup = BackupService.__new__(BackupService)
_restore = RestoreService.__new__(RestoreService)


def _export_json_roundtrip(db, model_class):
    """
    Exporta una tabla con el mismo método que usa el backup y la hace viajar por JSON,
    replicando lo que ocurre al escribir/leer el `.json` dentro del ZIP.
    """
    records = _backup._export_table(db, model_class)
    # dump + load: fuerza la serialización JSON real (str de UUID/datetime, dict JSON, etc.)
    return json.loads(json.dumps(records, ensure_ascii=False))


# === SEED ===


# Valores DISTINTOS entre sí para detectar cualquier confusión de columnas en el viaje.
_WS_CREATED_AT = datetime(2026, 1, 10, 8, 0, 0)
# billing_cycle_started_at intencionalmente != created_at (Req 18.3: se reinicia en
# reactivación), para probar que viaja como valor propio y no se colapsa a created_at.
_WS_BILLING_CYCLE_STARTED_AT = datetime(2026, 5, 20, 14, 30, 45)

# Freeze de la política aplicada al cierre (Req 4.4): debe preservarse íntegro como JSON.
_CLOSURE_FREEZE = {"cutoff": 1, "cut1": 0, "cut2": -1, "ephemeral_hours": 24}

_CUTOFF_AT = datetime(2026, 6, 1, 5, 0, 0)
_CLOSURE_CREATED_AT = datetime(2026, 6, 1, 6, 0, 0)


def _seed_source_db(db):
    """Puebla la BD origen con una org, un user, una workstation, un cierre y dos políticas."""
    org = Organization(
        id=uuid.uuid4(),
        name="BBVA",
        timezone="America/Lima",
        billing_mode="monthly",
    )
    db.add(org)

    user = User(
        id=uuid.uuid4(),
        email="admin@bbva.test",
        password_hash="x",
        full_name="Admin BBVA",
        role=UserRole.ADMIN,
        organization_id=org.id,
    )
    db.add(user)

    # Flush org + user antes de las filas que los referencian por FK cruda
    # (created_by_id no tiene relationship ORM, así que el unit-of-work no infiere
    # el orden de inserción; con FK enforcement activo en SQLite, insertar el cierre
    # antes que el user rompe la FK). El flush garantiza que existan primero.
    db.flush()

    ws = Workstation(
        id=uuid.uuid4(),
        organization_id=org.id,
        ip_private="10.0.0.5",
        billing_status="billable",
        created_at=_WS_CREATED_AT,
        first_seen=_WS_CREATED_AT,
        last_seen=_WS_BILLING_CYCLE_STARTED_AT,
        billing_cycle_started_at=_WS_BILLING_CYCLE_STARTED_AT,
    )
    db.add(ws)

    closure = BillingClosure(
        id=uuid.uuid4(),
        organization_id=org.id,
        period_year=2026,
        period_month=5,
        cutoff_at=_CUTOFF_AT,
        mode="monthly",
        timezone="America/Lima",
        total_billable=3,
        total_recycled=1,
        total_archived=0,
        amount=Decimal("12.50"),
        tiers_applied=[{"from": 1, "to": 100, "rate": 0.5, "count": 3}],
        is_retroactive=False,
        recycle_policy_applied=_CLOSURE_FREEZE,
        created_by_id=user.id,
        created_at=_CLOSURE_CREATED_AT,
    )
    db.add(closure)

    # Global_Default (organization_id NULL): legacy +1/-2/-3, 24h, efectivo 2000-01.
    global_policy = BillingRecyclePolicy(
        id=uuid.uuid4(),
        organization_id=None,
        cutoff_offset=1,
        cut1_offset=-2,
        cut2_offset=-3,
        ephemeral_hours=24,
        effective_from_year=2000,
        effective_from_month=1,
        effective_key=2000 * 12 + (1 - 1),
    )
    db.add(global_policy)

    # Org_Override de BBVA: +1/0/-1, 48h, efectivo 2026-09.
    org_policy = BillingRecyclePolicy(
        id=uuid.uuid4(),
        organization_id=org.id,
        cutoff_offset=1,
        cut1_offset=0,
        cut2_offset=-1,
        ephemeral_hours=48,
        effective_from_year=2026,
        effective_from_month=9,
        effective_key=2026 * 12 + (9 - 1),
        created_by_id=user.id,
    )
    db.add(org_policy)

    db.commit()
    return {
        "org": org,
        "user": user,
        "ws_id": ws.id,
        "closure_id": closure.id,
        "global_policy_id": global_policy.id,
        "org_policy_id": org_policy.id,
    }


@pytest.fixture
def roundtrip():
    """
    Ejecuta el round-trip completo y devuelve (source_db, dest_db, ids) para las aserciones.

    - source_db: BD origen ya poblada.
    - dest_db: BD destino con las tablas restauradas desde el export JSON del origen.
    """
    src_db, src_engine = _make_session()
    dst_db, dst_engine = _make_session()
    try:
        ids = _seed_source_db(src_db)

        # Orden de restore respetando FK: organizations → users → workstations →
        # billing_closures → billing_recycle_policies.
        _restore._restore_orm_table(
            dst_db, "organizations", Organization,
            _export_json_roundtrip(src_db, Organization),
        )
        _restore._restore_orm_table(
            dst_db, "users", User,
            _export_json_roundtrip(src_db, User),
        )
        _restore._restore_orm_table(
            dst_db, "workstations", Workstation,
            _export_json_roundtrip(src_db, Workstation),
        )
        _restore._restore_orm_table(
            dst_db, "billing_closures", BillingClosure,
            _export_json_roundtrip(src_db, BillingClosure),
        )
        _restore._restore_orm_table(
            dst_db, "billing_recycle_policies", BillingRecyclePolicy,
            _export_json_roundtrip(src_db, BillingRecyclePolicy),
        )
        dst_db.commit()

        yield src_db, dst_db, ids
    finally:
        src_db.close()
        dst_db.close()
        src_engine.dispose()
        dst_engine.dispose()


# === TESTS ===


def test_workstation_billing_cycle_started_at_preserved(roundtrip):
    """El round-trip preserva billing_cycle_started_at (distinto de created_at)."""
    _, dst_db, ids = roundtrip
    ws = dst_db.query(Workstation).filter_by(id=ids["ws_id"]).one()

    assert ws.billing_cycle_started_at == _WS_BILLING_CYCLE_STARTED_AT
    # created_at debe seguir siendo el suyo, NO colapsarse con billing_cycle_started_at.
    assert ws.created_at == _WS_CREATED_AT
    assert ws.billing_cycle_started_at != ws.created_at


def test_closure_recycle_policy_applied_preserved(roundtrip):
    """El round-trip preserva el freeze JSON recycle_policy_applied íntegro."""
    _, dst_db, ids = roundtrip
    closure = dst_db.query(BillingClosure).filter_by(id=ids["closure_id"]).one()

    assert closure.recycle_policy_applied == _CLOSURE_FREEZE
    # El freeze NO debe quedar vacío (un {} se trata como corrupto en fail-closed).
    assert closure.recycle_policy_applied != {}


def test_recycle_policies_rows_preserved(roundtrip):
    """El round-trip preserva ambas filas de billing_recycle_policies (global + override)."""
    _, dst_db, ids = roundtrip

    total = dst_db.query(BillingRecyclePolicy).count()
    assert total == 2

    # Global_Default: organization_id NULL, offsets legacy, efectivo 2000-01.
    global_policy = dst_db.query(BillingRecyclePolicy).filter_by(
        id=ids["global_policy_id"]
    ).one()
    assert global_policy.organization_id is None
    assert (global_policy.cutoff_offset, global_policy.cut1_offset, global_policy.cut2_offset) == (1, -2, -3)
    assert global_policy.ephemeral_hours == 24
    assert (global_policy.effective_from_year, global_policy.effective_from_month) == (2000, 1)
    assert global_policy.effective_key == 2000 * 12

    # Org_Override: organization_id de BBVA, offsets +1/0/-1, 48h, efectivo 2026-09.
    org_policy = dst_db.query(BillingRecyclePolicy).filter_by(
        id=ids["org_policy_id"]
    ).one()
    assert org_policy.organization_id == ids["org"].id
    assert (org_policy.cutoff_offset, org_policy.cut1_offset, org_policy.cut2_offset) == (1, 0, -1)
    assert org_policy.ephemeral_hours == 48
    assert (org_policy.effective_from_year, org_policy.effective_from_month) == (2026, 9)
    assert org_policy.effective_key == 2026 * 12 + 8
    assert org_policy.created_by_id == ids["user"].id


def test_recycle_policy_scope_distinguishable_after_restore(roundtrip):
    """
    Tras el restore, el scope sigue siendo distinguible: exactamente una fila global
    (organization_id NULL) y una fila override (organization_id no NULL).
    """
    _, dst_db, ids = roundtrip

    global_count = dst_db.query(BillingRecyclePolicy).filter(
        BillingRecyclePolicy.organization_id.is_(None)
    ).count()
    override_count = dst_db.query(BillingRecyclePolicy).filter(
        BillingRecyclePolicy.organization_id.isnot(None)
    ).count()

    assert global_count == 1
    assert override_count == 1
