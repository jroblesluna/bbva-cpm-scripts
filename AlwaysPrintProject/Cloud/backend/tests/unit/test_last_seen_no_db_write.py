"""
Tests unitarios: `last_seen` NO se escribe en cada telemetría individual (Req 1.8).

Complementan a `test_last_seen_tracker.py` y `test_last_seen_flush.py` cerrando el
hueco explícito del Req 1.8: registrar telemetría en el `LastSeenTracker` es una
operación EN MEMORIA que no toca la base de datos. La única escritura de `last_seen`
para workstations online ocurre en el flush periódico (batch_update_last_seen), NO por
cada mensaje de telemetría.

Estrategia: se usa una sesión SQLite real con una workstation persistida y se verifica
que:
- Registrar N telemetrías en el tracker no cambia el `last_seen` persistido ni añade
  filas (el buffer vive solo en memoria).
- Recién cuando el caller ejecuta el flush (selección de las que avanzaron +
  `batch_update_last_seen`) se materializa UNA escritura con el último ts.

_Requirements: 1.7, 1.8_
"""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
import app.models  # noqa: F401 — registra todas las tablas en metadata
from app.models.organization import Organization
from app.models.workstation import Workstation
from app.services.last_seen_tracker import LastSeenTracker, batch_update_last_seen


@pytest.fixture
def db_session():
    """Sesión SQLite in-memory con el esquema completo y una org para la FK."""
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


def _make_ws(db, *, ip_private: str, last_seen: datetime) -> Workstation:
    ws = Workstation(
        id=uuid.uuid4(),
        organization_id=db._org_id,
        ip_private=ip_private,
        is_online=True,
        last_seen=last_seen,
        billing_status="billable",
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws


class TestTelemetriaNoEscribeEnBD:
    """El registro de telemetría en el tracker es en memoria (Req 1.8)."""

    def test_record_telemetry_no_toca_bd(self, db_session):
        """Registrar muchas telemetrías no modifica `last_seen` en BD."""
        persistido = datetime(2026, 1, 1, 0, 0, 0)
        ws = _make_ws(db_session, ip_private="10.0.0.1", last_seen=persistido)

        tracker = LastSeenTracker()
        # Simula ~10 mensajes de telemetría (uno cada ~5 min), como el cliente real.
        base = datetime(2026, 1, 5, 8, 0, 0)
        for i in range(10):
            tracker.record_telemetry(str(ws.id), base + timedelta(minutes=5 * i))

        # Sin flush: la BD NO cambió pese a los 10 mensajes en memoria.
        db_session.expire_all()
        db_session.refresh(ws)
        assert ws.last_seen == persistido

        # El buffer en memoria sí avanzó al último ts (fuente para el flush).
        assert tracker.get_last_activity(str(ws.id)) == base + timedelta(minutes=45)

    def test_solo_el_flush_materializa_una_escritura(self, db_session):
        """La única escritura de `last_seen` la produce el flush, no la telemetría."""
        persistido = datetime(2026, 1, 1, 0, 0, 0)
        ws = _make_ws(db_session, ip_private="10.0.0.2", last_seen=persistido)

        tracker = LastSeenTracker()
        ultimo = datetime(2026, 1, 6, 9, 30, 0)
        tracker.record_telemetry(str(ws.id), datetime(2026, 1, 6, 9, 0, 0))
        tracker.record_telemetry(str(ws.id), ultimo)

        # Aún nada en BD.
        db_session.refresh(ws)
        assert ws.last_seen == persistido

        # El caller del loop de ~60s: selección de pendientes + batch UPDATE + commit_flush.
        pending = tracker.get_pending_flush()
        assert pending == {str(ws.id): ultimo}

        updated = batch_update_last_seen(db_session, pending)
        db_session.commit()
        tracker.commit_flush(pending)

        # Ahora sí, UNA escritura con el último ts (no uno por mensaje).
        assert updated == 1
        db_session.refresh(ws)
        assert ws.last_seen == ultimo

        # Tras el commit del flush, sin nueva telemetría no queda nada pendiente:
        # no se reescribe en cada ciclo (Req 1.7).
        assert tracker.get_pending_flush() == {}

    def test_flush_sin_avance_no_reescribe(self, db_session):
        """Si el ts en memoria no avanzó desde el último volcado, no hay nueva escritura."""
        ws = _make_ws(db_session, ip_private="10.0.0.3", last_seen=datetime(2026, 1, 1))

        tracker = LastSeenTracker()
        ts = datetime(2026, 1, 7, 10, 0, 0)
        tracker.record_telemetry(str(ws.id), ts)

        # Primer flush.
        first = tracker.get_pending_flush()
        batch_update_last_seen(db_session, first)
        db_session.commit()
        tracker.commit_flush(first)
        db_session.refresh(ws)
        assert ws.last_seen == ts

        # Llega telemetría repetida (mismo ts, sin avanzar). El flush no la selecciona.
        tracker.record_telemetry(str(ws.id), ts)
        assert tracker.get_pending_flush() == {}
        # Y un batch vacío no escribe nada.
        assert batch_update_last_seen(db_session, {}) == 0
