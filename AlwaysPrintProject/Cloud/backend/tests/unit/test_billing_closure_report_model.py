"""
Tests unitarios del modelo y la migración de `billing_closure_reports` (task 1.4).

Cubren las dos garantías estructurales de la tabla auxiliar del reporte de cierre
(`BillingClosureReport`, 1:1 con `BillingClosure`), definidas en `app/models/billing.py`
y en la migración `038_create_billing_closure_reports.py`:

1. Restricción `UNIQUE` sobre `closure_id` (relación 1:1): insertar un segundo reporte con
   el mismo `closure_id` viola la unicidad y levanta `IntegrityError` (Req 6.1).
2. FK `ON DELETE CASCADE`: borrar el `BillingClosure` padre elimina en cascada la fila del
   reporte hijo (Req 6.1, 11.4).

Nota sobre foreign keys en SQLite: el fixture `db` de `conftest.py` desactiva
`PRAGMA foreign_keys` (para poder hacer `drop_all` con dependencias circulares), por lo que
la cascada NO se dispararía con esa sesión. Para verificar de verdad el `ON DELETE CASCADE`
declarado en la FK, este test construye su propia sesión SQLite in-memory con
`PRAGMA foreign_keys=ON` (patrón de `test_billing_close_service.py::_make_session`, pero
activando las FK). Así ambas garantías —UNIQUE y CASCADE— se ejercitan realmente contra el
motor, no solo contra la declaración ORM.

_Requirements: 6.1, 11.4_
"""

import uuid
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
import app.models  # noqa: F401 — registra todas las tablas en metadata
from app.models.organization import Organization
from app.models.billing import BillingClosure, BillingClosureReport


# ── Fixtures y helpers ──────────────────────────────────────────────────────


@pytest.fixture
def db_fk():
    """
    Sesión SQLite in-memory con `PRAGMA foreign_keys=ON`.

    A diferencia del fixture global `db` (que desactiva las FK para permitir `drop_all`),
    aquí las activamos explícitamente para que la restricción `ON DELETE CASCADE` se dispare
    y podamos verificar la cascada real declarada en la FK de `billing_closure_reports`.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        # Con FK activas, borramos primero los hijos para evitar violaciones al hacer drop.
        engine.dispose()


def _make_org(session) -> Organization:
    """Crea y persiste una organización mínima para satisfacer la FK del cierre."""
    org = Organization(
        id=uuid.uuid4(),
        name=f"Org-{uuid.uuid4().hex[:8]}",
        timezone="America/Lima",
    )
    session.add(org)
    session.commit()
    return org


def _make_closure(session, org: Organization) -> BillingClosure:
    """Crea y persiste un cierre mínimo válido (cabecera) asociado a la organización."""
    closure = BillingClosure(
        id=uuid.uuid4(),
        organization_id=org.id,
        period_year=2026,
        period_month=1,
        cutoff_at=datetime(2026, 2, 1, 0, 0, 0),
        mode="monthly",
        timezone="America/Lima",
        total_billable=3,
        total_recycled=1,
        total_archived=0,
        amount=Decimal("12.50"),
        tiers_applied=[],
        is_retroactive=False,
    )
    session.add(closure)
    session.commit()
    return closure


def _make_report(closure_id, **overrides) -> BillingClosureReport:
    """Construye un reporte 1:1 para un cierre dado (sin persistir)."""
    fields = dict(
        id=uuid.uuid4(),
        closure_id=closure_id,
        organization_id=uuid.uuid4(),
        ai_analysis="Resumen ejecutivo de prueba.",
        ai_model="anthropic.claude-3-sonnet",
        ai_generated_at=datetime(2026, 2, 1, 3, 0, 0),
        pdf_s3_key="billing-reports/org/closure/report.pdf",
        pdf_generated_at=datetime(2026, 2, 1, 3, 1, 0),
    )
    fields.update(overrides)
    return BillingClosureReport(**fields)


# ── UNIQUE sobre closure_id (relación 1:1) ──────────────────────────────────


def test_duplicate_closure_id_violates_unique(db_fk):
    """
    Insertar un segundo `BillingClosureReport` con el mismo `closure_id` viola la
    restricción `UNIQUE` (relación 1:1 con el cierre) y levanta `IntegrityError` (Req 6.1).
    """
    org = _make_org(db_fk)
    closure = _make_closure(db_fk, org)

    db_fk.add(_make_report(closure.id, organization_id=org.id))
    db_fk.commit()

    # Segundo reporte para el MISMO cierre → debe violar el UNIQUE de closure_id.
    db_fk.add(_make_report(closure.id, organization_id=org.id))
    with pytest.raises(IntegrityError):
        db_fk.commit()

    db_fk.rollback()


# ── FK ON DELETE CASCADE ─────────────────────────────────────────────────────


def test_delete_closure_cascades_to_report(db_fk):
    """
    Borrar el `BillingClosure` padre elimina en cascada la fila del reporte hijo
    gracias a la FK `ON DELETE CASCADE` sobre `closure_id` (Req 6.1, 11.4).

    Se ejecuta un `DELETE` a nivel de motor (`Query.delete`) para que SQLite aplique la
    cascada de la FK, en vez de la cascada ORM.
    """
    org = _make_org(db_fk)
    closure = _make_closure(db_fk, org)

    db_fk.add(_make_report(closure.id, organization_id=org.id))
    db_fk.commit()

    assert db_fk.query(BillingClosureReport).count() == 1

    # Borrar el cierre padre a nivel de fila (dispara la cascada de la FK en SQLite).
    db_fk.query(BillingClosure).filter(BillingClosure.id == closure.id).delete(
        synchronize_session=False
    )
    db_fk.commit()

    # El reporte hijo debe haber desaparecido por CASCADE.
    assert db_fk.query(BillingClosure).count() == 0
    assert db_fk.query(BillingClosureReport).count() == 0
