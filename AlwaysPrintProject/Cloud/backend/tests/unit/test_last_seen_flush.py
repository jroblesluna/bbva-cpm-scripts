"""
Tests unitarios del flush periódico de `last_seen` (Usage and Billing, task 8).

Cubren dos piezas:

1. `batch_update_last_seen(db, ws_ts_map)`: el UPDATE batch de `last_seen` de las
   workstations ONLINE que avanzaron. A diferencia de `mark_offline_with_last_seen`:
   - NO toca `is_online` (siguen online).
   - NO reactiva `billing_status` (es un volcado plano de actividad).
   - Usa un `CASE` por-ws para escribir valores distintos en un único UPDATE.
   - Ignora entradas con ts None.

2. La lógica de SELECCIÓN del flush del loop de ~60s (Req 1.7, 1.8): dado el mapa de
   actividad de las ws conectadas y el mapa de lo ya volcado (`_last_seen_flushed`), solo
   se persisten las que avanzaron. Se testea la función pura equivalente para no depender
   del event loop del `start_ping_loop`.

_Requirements: 1.7, 1.8_
"""

import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
import app.models  # noqa: F401 — registra todas las tablas en metadata
from app.models.organization import Organization
from app.models.workstation import Workstation
from app.services.last_seen_tracker import batch_update_last_seen


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
    org = Organization(id=uuid.uuid4(), name="Org Test", timezone="UTC")
    session.add(org)
    session.commit()
    session._org_id = org.id
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


def _select_pending(
    connected_activity: Dict[str, Optional[datetime]],
    already_flushed: Dict[str, datetime],
) -> Dict[str, datetime]:
    """
    Réplica pura de la selección de FASE 3.5 en `start_ping_loop` (ambos managers).

    Devuelve las ws cuya actividad en memoria avanzó respecto al último valor volcado.
    """
    pending: Dict[str, datetime] = {}
    for ws_id, ts in connected_activity.items():
        if ts is None:
            continue
        flushed = already_flushed.get(ws_id)
        if flushed is None or ts > flushed:
            pending[ws_id] = ts
    return pending


class TestBatchUpdateLastSeen:
    def test_lote_vacio_no_hace_nada(self, db_session):
        assert batch_update_last_seen(db_session, {}) == 0

    def test_solo_ts_none_no_actualiza(self, db_session):
        """Un mapa con solo ts None no escribe nada."""
        ws = _make_ws(db_session, ip_private="10.0.0.9", last_seen=datetime(2026, 1, 1))
        assert batch_update_last_seen(db_session, {str(ws.id): None}) == 0
        db_session.refresh(ws)
        assert ws.last_seen == datetime(2026, 1, 1)

    def test_persiste_last_seen_sin_tocar_is_online(self, db_session):
        """Actualiza last_seen y deja is_online=True (la ws sigue online)."""
        nueva_actividad = datetime(2026, 1, 10, 8, 0, 0)
        ws = _make_ws(
            db_session,
            ip_private="10.0.0.1",
            is_online=True,
            last_seen=datetime(2026, 1, 1, 0, 0, 0),
        )

        updated = batch_update_last_seen(db_session, {str(ws.id): nueva_actividad})
        db_session.commit()
        db_session.refresh(ws)

        assert updated == 1
        assert ws.last_seen == nueva_actividad
        assert ws.is_online is True  # NO se toca

    def test_no_reactiva_billing_status(self, db_session):
        """El flush plano NO reactiva recycled/archived (eso lo hace mark_activity)."""
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

        batch_update_last_seen(
            db_session,
            {str(ws_recycled.id): ts, str(ws_archived.id): ts},
        )
        db_session.commit()
        db_session.refresh(ws_recycled)
        db_session.refresh(ws_archived)

        assert ws_recycled.last_seen == ts
        assert ws_recycled.billing_status == "recycled"
        assert ws_archived.last_seen == ts
        assert ws_archived.billing_status == "archived"

    def test_case_por_ws_valores_distintos(self, db_session):
        """Un único batch aplica last_seen distinto por workstation (CASE)."""
        ts1 = datetime(2026, 3, 1, 10, 0, 0)
        ts2 = datetime(2026, 3, 2, 11, 0, 0)
        ws1 = _make_ws(db_session, ip_private="10.0.1.1", last_seen=datetime(2026, 1, 1))
        ws2 = _make_ws(db_session, ip_private="10.0.1.2", last_seen=datetime(2026, 1, 1))
        # Una con None: conserva su valor y no cuenta.
        prev3 = datetime(2026, 1, 15)
        ws3 = _make_ws(db_session, ip_private="10.0.1.3", last_seen=prev3)

        updated = batch_update_last_seen(
            db_session,
            {str(ws1.id): ts1, str(ws2.id): ts2, str(ws3.id): None},
        )
        db_session.commit()
        for ws in (ws1, ws2, ws3):
            db_session.refresh(ws)

        assert updated == 2  # ws3 (None) no participa
        assert ws1.last_seen == ts1
        assert ws2.last_seen == ts2
        assert ws3.last_seen == prev3


class TestFlushSelection:
    """Lógica de selección de FASE 3.5 (solo las que avanzaron — Req 1.7)."""

    def test_primera_vez_selecciona_todas_las_conocidas(self):
        t0 = datetime(2026, 1, 1, 0, 0, 0)
        connected = {"ws-1": t0, "ws-2": t0}
        assert _select_pending(connected, {}) == {"ws-1": t0, "ws-2": t0}

    def test_ignora_ws_sin_actividad(self):
        t0 = datetime(2026, 1, 1, 0, 0, 0)
        connected = {"ws-1": t0, "ws-2": None}
        assert _select_pending(connected, {}) == {"ws-1": t0}

    def test_no_reescribe_las_ya_volcadas(self):
        t0 = datetime(2026, 1, 1, 0, 0, 0)
        connected = {"ws-1": t0}
        # Ya se volcó exactamente t0 → no vuelve a estar pendiente.
        assert _select_pending(connected, {"ws-1": t0}) == {}

    def test_reescribe_solo_las_que_avanzaron(self):
        t0 = datetime(2026, 1, 1, 0, 0, 0)
        t1 = t0 + timedelta(minutes=5)
        connected = {"ws-1": t0, "ws-2": t1}
        already = {"ws-1": t0, "ws-2": t0}
        # ws-1 no avanzó; ws-2 sí.
        assert _select_pending(connected, already) == {"ws-2": t1}
