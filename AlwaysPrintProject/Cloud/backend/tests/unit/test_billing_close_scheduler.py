"""
Tests del scheduler de cierre mensual automático (`BillingCloseScheduler`, task 26).

Cubren el comportamiento del scheduler descrito en `design.md` (sección "Scheduler de cierre
automático") y el requisito 7.1:

- `_due_period`: determina el mes recién terminado en la tz de la org (incluye rollover
  enero → diciembre) y devuelve None ante timezone inválida (fail-safe, no revienta el lote).
- Corrida programada (`_process_all_organizations`): cierra el mes recién terminado de una org
  activa cuando ya cruzó la medianoche del día 1 en su tz, es idempotente (una segunda corrida
  no crea un segundo cierre) y NO auto-rellena huecos de secuencia (los deja para el endpoint
  retroactivo, task 27).
- Lock de concurrencia: una corrida en curso descarta la siguiente (no se encolan cierres).

Convenciones (siguiendo `tests/unit/test_billing_close_service.py`): sesión SQLite in-memory
con el esquema completo, planes por defecto sembrados con `seed_default_rate_plans`, filas
`Workstation` construidas a mano. El scheduler crea su propia `SessionLocal`, por lo que los
tests monkeypatchean `SessionLocal` del módulo del scheduler para reutilizar la sesión de test.

**Validates: Requirements 7.1**
"""

import asyncio
import uuid
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.billing import BillingClosure
from app.models.organization import Organization
from app.models.workstation import Workstation
from app.services.billing_seed import seed_default_rate_plans
import app.services.billing_close_scheduler as scheduler_module
from app.services.billing_close_scheduler import BillingCloseScheduler


# ── Fixtures y helpers ──────────────────────────────────────────────────────


def _make_session():
    """Crea una sesión SQLite in-memory con el esquema completo y planes por defecto."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    seed_default_rate_plans(session.connection())
    session.commit()
    return session, engine


@pytest.fixture
def db_utc():
    """Sesión con una org activa en timezone UTC."""
    session, engine = _make_session()
    org = Organization(
        id=uuid.uuid4(),
        name="Org UTC Scheduler Test",
        timezone="UTC",
        billing_mode="monthly",
        is_active=True,
    )
    session.add(org)
    session.commit()
    session._org = org
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _add_ws(db, *, ip_private: str, created_at: datetime, last_seen: datetime):
    """Inserta una workstation `new` con los campos relevantes para el cierre."""
    ws = Workstation(
        id=uuid.uuid4(),
        organization_id=db._org.id,
        ip_private=ip_private,
        created_at=created_at,
        first_seen=created_at,
        last_seen=last_seen,
        billing_status="new",
        is_online=False,
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws


def _closures(db, org) -> list:
    return (
        db.query(BillingClosure)
        .filter(BillingClosure.organization_id == org.id)
        .all()
    )


def _use_session(monkeypatch, db):
    """Hace que el scheduler reutilice la sesión de test en vez de abrir una nueva.

    El scheduler llama `SessionLocal()` y luego `db.close()` al final de la corrida. Se
    envuelve la sesión de test para que `close()` sea un no-op y no invalide el resto del test.
    """

    class _NoCloseSession:
        def __init__(self, real):
            self._real = real

        def __getattr__(self, name):
            return getattr(self._real, name)

        def close(self):  # no-op: la fixture cierra la sesión real
            pass

    monkeypatch.setattr(
        scheduler_module, "SessionLocal", lambda: _NoCloseSession(db)
    )


# ── 1. _due_period ───────────────────────────────────────────────────────────


class TestDuePeriod:
    """El mes objetivo es el inmediatamente anterior al mes local actual de la org."""

    def _org(self, tz: str) -> Organization:
        return Organization(id=uuid.uuid4(), name="x", timezone=tz, is_active=True)

    def test_mes_anterior_normal(self, monkeypatch):
        """En marzo local, el mes recién terminado es febrero del mismo año."""
        sched = BillingCloseScheduler()

        class _FakeDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 3, 15, 0, 5, tzinfo=tz)

        monkeypatch.setattr(scheduler_module, "datetime", _FakeDatetime)
        assert sched._due_period(self._org("UTC")) == (2026, 2)

    def test_rollover_enero_a_diciembre(self, monkeypatch):
        """En enero local, el mes recién terminado es diciembre del año anterior."""
        sched = BillingCloseScheduler()

        class _FakeDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 1, 1, 0, 5, tzinfo=tz)

        monkeypatch.setattr(scheduler_module, "datetime", _FakeDatetime)
        assert sched._due_period(self._org("UTC")) == (2025, 12)

    def test_timezone_invalida_devuelve_none(self):
        """Una timezone inválida no revienta: devuelve None (fail-safe)."""
        sched = BillingCloseScheduler()
        assert sched._due_period(self._org("No/Existe")) is None


# ── 2. Corrida programada ─────────────────────────────────────────────────────


class TestScheduledClose:
    """Comportamiento de la corrida programada sobre organizaciones reales."""

    def _run(self, sched):
        asyncio.run(sched._process_all_organizations())

    def _freeze_local_month(self, monkeypatch, year, month, day=15):
        """Fija el "ahora" local (para todas las tz) a un día del mes indicado."""

        class _FakeDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(year, month, day, 0, 5, tzinfo=tz)

        monkeypatch.setattr(scheduler_module, "datetime", _FakeDatetime)

    def test_cierra_mes_recien_terminado(self, db_utc, monkeypatch):
        """Con una org en UTC y "ahora" = junio, se cierra mayo automáticamente."""
        _use_session(monkeypatch, db_utc)
        # IP creada en mayo → mayo es cerrable. En junio local el scheduler cierra mayo.
        _add_ws(
            db_utc,
            ip_private="10.0.0.1",
            created_at=datetime(2026, 5, 2, 12, 0),
            last_seen=datetime(2026, 5, 20, 12, 0),
        )
        self._freeze_local_month(monkeypatch, 2026, 6)

        sched = BillingCloseScheduler()
        self._run(sched)

        cierres = _closures(db_utc, db_utc._org)
        assert len(cierres) == 1
        assert (cierres[0].period_year, cierres[0].period_month) == (2026, 5)

    def test_idempotente_segunda_corrida_no_recierra(self, db_utc, monkeypatch):
        """Dos corridas en el mismo mes local no crean un segundo cierre (Req 7.6)."""
        _use_session(monkeypatch, db_utc)
        _add_ws(
            db_utc,
            ip_private="10.0.0.1",
            created_at=datetime(2026, 5, 2, 12, 0),
            last_seen=datetime(2026, 5, 20, 12, 0),
        )
        self._freeze_local_month(monkeypatch, 2026, 6)

        sched = BillingCloseScheduler()
        self._run(sched)
        self._run(sched)

        cierres = _closures(db_utc, db_utc._org)
        assert len(cierres) == 1

    def test_hueco_de_secuencia_no_se_autorrellena(self, db_utc, monkeypatch):
        """
        Si hay un mes anterior sin cerrar, el scheduler NO cierra (deja el retroactivo para
        la task 27). Org con IP creada en marzo; "ahora" = junio → mes objetivo mayo, pero
        marzo/abril no están cerrados → BillingSequenceError → se ignora, sin cierres.
        """
        _use_session(monkeypatch, db_utc)
        _add_ws(
            db_utc,
            ip_private="10.0.0.1",
            created_at=datetime(2026, 3, 2, 12, 0),
            last_seen=datetime(2026, 3, 20, 12, 0),
        )
        self._freeze_local_month(monkeypatch, 2026, 6)

        sched = BillingCloseScheduler()
        self._run(sched)

        # No se cerró nada: mayo no puede cerrarse con marzo/abril pendientes.
        assert _closures(db_utc, db_utc._org) == []

    def test_org_inactiva_se_ignora(self, db_utc, monkeypatch):
        """Las organizaciones inactivas no se procesan."""
        _use_session(monkeypatch, db_utc)
        db_utc._org.is_active = False
        db_utc.commit()
        _add_ws(
            db_utc,
            ip_private="10.0.0.1",
            created_at=datetime(2026, 5, 2, 12, 0),
            last_seen=datetime(2026, 5, 20, 12, 0),
        )
        self._freeze_local_month(monkeypatch, 2026, 6)

        sched = BillingCloseScheduler()
        self._run(sched)

        assert _closures(db_utc, db_utc._org) == []


# ── 3. Lock de concurrencia ────────────────────────────────────────────────────


class TestConcurrencyLock:
    """Una corrida en curso descarta la siguiente (no se encolan cierres)."""

    def test_corrida_descartada_si_lock_tomado(self, monkeypatch):
        async def scenario():
            sched = BillingCloseScheduler()
            llamado = {"n": 0}

            async def _fake_process():
                llamado["n"] += 1
                await asyncio.sleep(0.05)

            monkeypatch.setattr(sched, "_process_all_organizations", _fake_process)

            # Tomar el lock manualmente para simular una corrida en curso.
            await sched._lock.acquire()
            try:
                await sched._scheduled_close()  # debe descartarse (lock tomado)
            finally:
                sched._lock.release()

            assert llamado["n"] == 0

        asyncio.run(scenario())
