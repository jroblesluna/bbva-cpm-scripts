"""
Tests unitarios de `mark_offline_with_last_seen` (Usage and Billing, task 7).

Verifican que al marcar workstations offline en batch:
- Se pone `is_online=False` a todas las del lote.
- Se persiste `last_seen` con el ts de actividad real conocido (Req 1.5, 1.6), NO el
  momento del evento de desconexión/muerte.
- Las ws sin actividad conocida (ts=None) conservan su `last_seen` previo (no se degrada).
- Cada ws recibe su propio `last_seen` en un único UPDATE batch (CASE por-ws).
- Ir offline NO reactiva `billing_status` (recycled/archived NO pasan a billable): ir
  offline no es actividad nueva.

_Requirements: 1.5, 1.6_
"""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
import app.models  # noqa: F401 — registra todas las tablas en metadata
from app.models.organization import Organization
from app.models.workstation import Workstation
from app.services.last_seen_tracker import mark_offline_with_last_seen


@pytest.fixture
def db_session():
    """Sesión SQLite in-memory con el esquema completo y una org para satisfacer la FK."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    # Organización única compartida por las ws del test (evita fallos de FK).
    org = Organization(id=uuid.uuid4(), name="Org Test", timezone="UTC")
    session.add(org)
    session.commit()
    session._org_id = org.id  # atajo para los helpers del test
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _make_ws(
    db,
    *,
    ip_private: str,
    is_online: bool = True,
    last_seen: datetime,
    billing_status: str = "billable",
) -> Workstation:
    ws = Workstation(
        id=uuid.uuid4(),
        organization_id=db._org_id,
        ip_private=ip_private,
        is_online=is_online,
        last_seen=last_seen,
        billing_status=billing_status,
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws


class TestMarkOfflineWithLastSeen:
    def test_lote_vacio_no_hace_nada(self, db_session):
        assert mark_offline_with_last_seen(db_session, {}) == 0

    def test_persiste_last_seen_con_actividad_conocida(self, db_session):
        """Con ts conocido, escribe is_online=False y last_seen = ese ts."""
        actividad = datetime(2026, 1, 10, 8, 0, 0)
        ws = _make_ws(
            db_session,
            ip_private="10.0.0.1",
            is_online=True,
            last_seen=datetime(2026, 1, 1, 0, 0, 0),
        )

        updated = mark_offline_with_last_seen(db_session, {str(ws.id): actividad})
        db_session.commit()
        db_session.refresh(ws)

        assert updated == 1
        assert ws.is_online is False
        assert ws.last_seen == actividad

    def test_ts_none_conserva_last_seen_previo(self, db_session):
        """Sin actividad conocida (None), solo marca offline; last_seen no cambia."""
        previo = datetime(2026, 1, 5, 12, 0, 0)
        ws = _make_ws(
            db_session,
            ip_private="10.0.0.2",
            is_online=True,
            last_seen=previo,
        )

        updated = mark_offline_with_last_seen(db_session, {str(ws.id): None})
        db_session.commit()
        db_session.refresh(ws)

        assert updated == 1
        assert ws.is_online is False
        assert ws.last_seen == previo  # no se degrada al momento del evento

    def test_no_usa_el_momento_del_evento(self, db_session):
        """El last_seen persistido es la actividad real, no 'ahora'."""
        actividad = datetime(2026, 2, 1, 9, 30, 0)
        ws = _make_ws(
            db_session,
            ip_private="10.0.0.3",
            last_seen=datetime(2026, 1, 1),
        )

        mark_offline_with_last_seen(db_session, {str(ws.id): actividad})
        db_session.commit()
        db_session.refresh(ws)

        # Debe ser exactamente el ts de actividad real, no un valor cercano a "ahora".
        assert ws.last_seen == actividad
        assert ws.last_seen.year == 2026 and ws.last_seen.month == 2

    def test_case_por_ws_valores_distintos(self, db_session):
        """Un único batch aplica last_seen distinto por workstation (CASE)."""
        ts1 = datetime(2026, 3, 1, 10, 0, 0)
        ts2 = datetime(2026, 3, 2, 11, 0, 0)
        ws1 = _make_ws(db_session, ip_private="10.0.1.1", last_seen=datetime(2026, 1, 1))
        ws2 = _make_ws(db_session, ip_private="10.0.1.2", last_seen=datetime(2026, 1, 1))
        # Tercera sin actividad conocida: conserva su valor.
        prev3 = datetime(2026, 1, 15)
        ws3 = _make_ws(db_session, ip_private="10.0.1.3", last_seen=prev3)

        updated = mark_offline_with_last_seen(
            db_session,
            {str(ws1.id): ts1, str(ws2.id): ts2, str(ws3.id): None},
        )
        db_session.commit()
        for ws in (ws1, ws2, ws3):
            db_session.refresh(ws)

        assert updated == 3
        assert ws1.is_online is False and ws2.is_online is False and ws3.is_online is False
        assert ws1.last_seen == ts1
        assert ws2.last_seen == ts2
        assert ws3.last_seen == prev3

    def test_offline_no_reactiva_billing_status(self, db_session):
        """Ir offline NO cambia recycled/archived a billable (no es actividad nueva)."""
        ts = datetime(2026, 4, 1, 8, 0, 0)
        ws_recycled = _make_ws(
            db_session,
            ip_private="10.0.2.1",
            last_seen=datetime(2026, 1, 1),
            billing_status="recycled",
        )
        ws_archived = _make_ws(
            db_session,
            ip_private="10.0.2.2",
            last_seen=datetime(2026, 1, 1),
            billing_status="archived",
        )

        mark_offline_with_last_seen(
            db_session,
            {str(ws_recycled.id): ts, str(ws_archived.id): ts},
        )
        db_session.commit()
        db_session.refresh(ws_recycled)
        db_session.refresh(ws_archived)

        # last_seen se actualiza, pero el estado NO se reactiva.
        assert ws_recycled.last_seen == ts
        assert ws_recycled.billing_status == "recycled"
        assert ws_archived.last_seen == ts
        assert ws_archived.billing_status == "archived"
