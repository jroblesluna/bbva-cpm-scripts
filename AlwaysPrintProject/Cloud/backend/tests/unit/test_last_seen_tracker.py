"""
Tests unitarios de `LastSeenTracker` y `mark_activity` (Usage and Billing, task 5).

Cubren:
- El buffer en memoria solo avanza (ignora telemetría fuera de orden / más vieja).
- El flush periódico solo reporta las workstations que avanzaron respecto al último volcado.
- `mark_activity` setea `last_seen` y reactiva `recycled`/`archived` → `billable` (Req 2.8),
  dejando `billable`/`new` sin cambios.

Estos tests trabajan con objetos ORM en memoria (sin sesión de BD), igual que
`tests/unit/test_models.py`. La lógica de estado y del buffer no requiere BD.

_Requirements: 1.4, 1.5, 2.8_
"""

from datetime import datetime, timedelta

import pytest

from app.models.workstation import Workstation
from app.services.last_seen_tracker import LastSeenTracker, mark_activity


class TestLastSeenTrackerBuffer:
    """Tests del buffer en memoria por worker."""

    def test_record_telemetry_avanza(self):
        """El buffer guarda el ts más reciente."""
        tracker = LastSeenTracker()
        base = datetime(2026, 1, 1, 0, 0, 0)

        tracker.record_telemetry("ws-1", base)
        assert tracker.get_last_activity("ws-1") == base

        posterior = base + timedelta(minutes=5)
        tracker.record_telemetry("ws-1", posterior)
        assert tracker.get_last_activity("ws-1") == posterior

    def test_record_telemetry_ignora_fuera_de_orden(self):
        """Un mensaje más viejo no retrocede el valor almacenado."""
        tracker = LastSeenTracker()
        base = datetime(2026, 1, 1, 0, 0, 0)

        tracker.record_telemetry("ws-1", base)
        tracker.record_telemetry("ws-1", base - timedelta(hours=1))

        assert tracker.get_last_activity("ws-1") == base

    def test_get_last_activity_desconocida_es_none(self):
        """Sin telemetría previa, no hay última actividad."""
        tracker = LastSeenTracker()
        assert tracker.get_last_activity("ws-desconocida") is None

    def test_forget_es_idempotente(self):
        """`forget` limpia el buffer y no falla si la ws no existe."""
        tracker = LastSeenTracker()
        tracker.record_telemetry("ws-1", datetime(2026, 1, 1))

        tracker.forget("ws-1")
        assert tracker.get_last_activity("ws-1") is None

        # Segunda llamada sobre una ws ausente no debe lanzar.
        tracker.forget("ws-1")


class TestLastSeenTrackerFlush:
    """Tests del soporte al flush periódico (~60s)."""

    def test_pending_flush_reporta_solo_los_que_avanzaron(self):
        """Tras commit, la misma ws no vuelve a estar pendiente hasta avanzar."""
        tracker = LastSeenTracker()
        t0 = datetime(2026, 1, 1, 0, 0, 0)

        tracker.record_telemetry("ws-1", t0)
        assert tracker.get_pending_flush() == {"ws-1": t0}

        tracker.commit_flush({"ws-1": t0})
        assert tracker.get_pending_flush() == {}

        t1 = t0 + timedelta(minutes=5)
        tracker.record_telemetry("ws-1", t1)
        assert tracker.get_pending_flush() == {"ws-1": t1}

    def test_pending_flush_multiples_workstations(self):
        """El pending refleja solo las ws con avance desde el último volcado."""
        tracker = LastSeenTracker()
        t0 = datetime(2026, 1, 1, 0, 0, 0)

        tracker.record_telemetry("ws-1", t0)
        tracker.record_telemetry("ws-2", t0)
        tracker.commit_flush({"ws-1": t0, "ws-2": t0})

        # Solo ws-2 avanza.
        t1 = t0 + timedelta(minutes=1)
        tracker.record_telemetry("ws-2", t1)

        assert tracker.get_pending_flush() == {"ws-2": t1}


class TestMarkActivity:
    """Tests del helper `mark_activity` (reactivación inmediata, Req 2.8)."""

    @pytest.mark.parametrize(
        "estado_inicial,estado_esperado",
        [
            ("recycled", "billable"),
            ("archived", "billable"),
            ("billable", "billable"),
            ("new", "new"),
        ],
    )
    def test_reactivacion_de_estado(self, estado_inicial, estado_esperado):
        """`recycled`/`archived` se reactivan a `billable`; el resto no cambia."""
        ws = Workstation(ip_private="10.0.0.1", billing_status=estado_inicial)
        ts = datetime(2026, 2, 2, 12, 0, 0)

        mark_activity(db=None, ws=ws, ts=ts)

        assert ws.billing_status == estado_esperado

    def test_setea_last_seen(self):
        """Siempre actualiza `last_seen` al ts de la actividad."""
        ws = Workstation(ip_private="10.0.0.1", billing_status="billable")
        ts = datetime(2026, 2, 2, 12, 0, 0)

        mark_activity(db=None, ws=ws, ts=ts)

        assert ws.last_seen == ts
