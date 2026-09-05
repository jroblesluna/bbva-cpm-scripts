"""
Tests de integración de persistencia de `last_seen` (Usage and Billing, task 9).

Cierran los huecos de nivel-BD que las pruebas unitarias (objetos ORM sueltos) no cubren:

1. Transición offline→online por el path real de telemetría del WebSocket
   (`_handle_telemetry`): con una workstation offline en BD, al llegar telemetría se
   persiste (con commit) `is_online=True` y `last_seen = telemetry_log.recorded_at`
   (el ts de la telemetría real, Req 1.5), NO el `last_seen` previo ni el momento del
   evento.

2. Reactivación de estado en la MISMA transacción a nivel BD (Req 2.8): una workstation
   `recycled`/`archived` que estaba offline pasa a `billable` tras la telemetría, y el
   cambio queda commiteado (no solo en un objeto desprendido).

3. `mark_activity` con sesión real + commit: verifica la atomicidad last_seen + estado
   sobre una fila persistida y refrescada desde BD.

Estos tests usan una sesión SQLite in-memory con el esquema completo, como el resto de
las pruebas del repo. `_handle_telemetry` es `async`, así que se ejecutan con
`asyncio.run` (no requiere plugin extra ni un mock de conexión: `_handle_telemetry` solo
toca la BD; el broadcast/connection_manager es responsabilidad del caller).

_Requirements: 1.4, 1.5, 2.8_
"""

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
import app.models  # noqa: F401 — registra todas las tablas en metadata
from app.models.organization import Organization
from app.models.workstation import Workstation
from app.models.telemetry import TelemetryLog
from app.api.v1.websocket.workstation import _handle_telemetry
from app.services.last_seen_tracker import mark_activity


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


def _make_ws(
    db,
    *,
    ip_private: str,
    is_online: bool,
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


def _telemetry_payload() -> dict:
    """Payload de telemetría válido mínimo (mismo formato que envía el Tray)."""
    return {
        "type": "telemetry",
        "queue_status": "ok",
        "contingency_active": False,
        "jobs_identified": 3,
        "avg_release_time_ms": 120,
        "disconnection_log": [],
    }


class TestTelemetriaOfflineOnline:
    """Path real `_handle_telemetry`: offline→online persiste el ts correcto (Req 1.5)."""

    def test_transicion_offline_online_persiste_last_seen_de_telemetria(self, db_session):
        """
        WS offline en BD → llega telemetría → se commitea is_online=True y
        last_seen = recorded_at de la telemetría (no el last_seen previo).
        """
        previo = datetime(2026, 1, 1, 0, 0, 0)
        ws = _make_ws(
            db_session,
            ip_private="10.0.0.10",
            is_online=False,
            last_seen=previo,
        )

        result = asyncio.run(
            _handle_telemetry(
                data=_telemetry_payload(),
                workstation_id=str(ws.id),
                organization_id=str(db_session._org_id),
                db=db_session,
            )
        )

        # El handler retorna el mensaje de broadcast (persistencia exitosa).
        assert isinstance(result, dict)
        assert result["type"] == "telemetry_received"

        # La telemetría persistida marca el ts de actividad real usado como last_seen.
        telemetry_log = (
            db_session.query(TelemetryLog)
            .filter(TelemetryLog.workstation_id == str(ws.id))
            .one()
        )

        # Verificar el estado COMMITEADO leyendo fresco desde BD.
        db_session.expire_all()
        ws_fresco = db_session.query(Workstation).filter(Workstation.id == ws.id).one()
        assert ws_fresco.is_online is True
        assert ws_fresco.last_seen == telemetry_log.recorded_at
        assert ws_fresco.last_seen != previo  # no es el valor anterior

    def test_offline_online_reactiva_recycled_a_billable_commiteado(self, db_session):
        """WS recycled + offline → telemetría la reactiva a billable, commiteado (Req 2.8)."""
        ws = _make_ws(
            db_session,
            ip_private="10.0.0.11",
            is_online=False,
            last_seen=datetime(2026, 1, 1),
            billing_status="recycled",
        )

        asyncio.run(
            _handle_telemetry(
                data=_telemetry_payload(),
                workstation_id=str(ws.id),
                organization_id=str(db_session._org_id),
                db=db_session,
            )
        )

        telemetry_log = (
            db_session.query(TelemetryLog)
            .filter(TelemetryLog.workstation_id == str(ws.id))
            .one()
        )

        db_session.expire_all()
        ws_fresco = db_session.query(Workstation).filter(Workstation.id == ws.id).one()
        assert ws_fresco.is_online is True
        assert ws_fresco.billing_status == "billable"  # reactivado
        assert ws_fresco.last_seen == telemetry_log.recorded_at

    def test_offline_online_reactiva_archived_a_billable_commiteado(self, db_session):
        """WS archived + offline → telemetría la reactiva a billable, commiteado (Req 2.8)."""
        ws = _make_ws(
            db_session,
            ip_private="10.0.0.12",
            is_online=False,
            last_seen=datetime(2026, 1, 1),
            billing_status="archived",
        )

        asyncio.run(
            _handle_telemetry(
                data=_telemetry_payload(),
                workstation_id=str(ws.id),
                organization_id=str(db_session._org_id),
                db=db_session,
            )
        )

        db_session.expire_all()
        ws_fresco = db_session.query(Workstation).filter(Workstation.id == ws.id).one()
        assert ws_fresco.is_online is True
        assert ws_fresco.billing_status == "billable"

    def test_telemetria_estando_online_no_reescribe_last_seen_por_mensaje(self, db_session):
        """
        Si la WS ya está online, `_handle_telemetry` NO toca last_seen ni billing_status
        (esa persistencia la hace el flush periódico, no cada telemetría — Req 1.8).
        """
        previo = datetime(2026, 1, 1, 0, 0, 0)
        ws = _make_ws(
            db_session,
            ip_private="10.0.0.13",
            is_online=True,
            last_seen=previo,
            billing_status="billable",
        )

        asyncio.run(
            _handle_telemetry(
                data=_telemetry_payload(),
                workstation_id=str(ws.id),
                organization_id=str(db_session._org_id),
                db=db_session,
            )
        )

        db_session.expire_all()
        ws_fresco = db_session.query(Workstation).filter(Workstation.id == ws.id).one()
        # last_seen intacto: estando online no se persiste por mensaje individual.
        assert ws_fresco.last_seen == previo
        assert ws_fresco.is_online is True


class TestMarkActivityNivelBD:
    """`mark_activity` con sesión real + commit (Req 1.4, 2.8)."""

    @pytest.mark.parametrize(
        "estado_inicial,estado_esperado",
        [
            ("recycled", "billable"),
            ("archived", "billable"),
            ("billable", "billable"),
            ("new", "new"),
        ],
    )
    def test_mark_activity_commiteado(self, db_session, estado_inicial, estado_esperado):
        """last_seen + reactivación quedan persistidos tras commit y relectura desde BD."""
        ws = _make_ws(
            db_session,
            ip_private=f"10.0.9.{hash(estado_inicial) % 200}",
            is_online=True,
            last_seen=datetime(2026, 1, 1),
            billing_status=estado_inicial,
        )
        ts = datetime(2026, 5, 5, 15, 0, 0)

        # El helper NO hace commit; el caller (aquí el test) confirma la transacción.
        mark_activity(db_session, ws, ts)
        db_session.commit()

        # Releer fresco para confirmar que el cambio está en BD, no solo en el objeto.
        db_session.expire_all()
        ws_fresco = db_session.query(Workstation).filter(Workstation.id == ws.id).one()
        assert ws_fresco.last_seen == ts
        assert ws_fresco.billing_status == estado_esperado

    def test_mark_activity_reactiva_en_la_misma_transaccion(self, db_session):
        """
        last_seen y el nuevo billing_status se escriben juntos: antes del commit ambos
        cambios coexisten en la sesión; tras el commit persisten atómicamente.
        """
        ws = _make_ws(
            db_session,
            ip_private="10.0.9.250",
            is_online=True,
            last_seen=datetime(2026, 1, 1),
            billing_status="recycled",
        )
        ts = datetime(2026, 6, 6, 12, 0, 0)

        mark_activity(db_session, ws, ts)
        # Aún en la transacción abierta: ambos efectos presentes en el objeto gestionado.
        assert ws.last_seen == ts
        assert ws.billing_status == "billable"

        db_session.commit()
        db_session.expire_all()
        ws_fresco = db_session.query(Workstation).filter(Workstation.id == ws.id).one()
        assert ws_fresco.last_seen == ts
        assert ws_fresco.billing_status == "billable"
