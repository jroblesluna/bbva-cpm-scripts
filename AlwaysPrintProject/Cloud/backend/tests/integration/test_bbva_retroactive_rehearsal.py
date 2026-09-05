"""
Ensayo end-to-end (dry-run) de la secuencia de cierres retroactivos de BBVA
mayo→agosto (Usage and Billing, task 35 — verificación final).

Este test es la materialización del "ensayo de la secuencia de cierres retroactivos de
BBVA (mayo→agosto) en dev" pedido por la task 35. NO toca PROD: usa una BD SQLite
in-memory con el esquema completo y los planes tarifarios por defecto sembrados, y ejecuta
el flujo real de `BillingCloseService.close_month` en orden (el mismo motor que usan el
scheduler automático y el endpoint retroactivo de superadmin).

Escenario (America/Lima, timezone de BBVA):
- Un grupo de IPs "de mayo" que se abandonó pronto (uso corto <24h, last_seen a mediados
  de mayo): candidatas a `recycled` cuando la ventana de corte las alcance.
- Un grupo de IPs "de mayo" que sigue activo hasta agosto: permanece `billable`.
- IPs que aparecen en junio y julio, activas: permanecen `billable`.

Ventanas de corte por mes M (tz America/Lima): cut1 = 00:00 día 1 de (M−2),
cut2 = 00:00 día 1 de (M−3). Con last_seen de las "mayo inactivas" a mediados de mayo:
- mayo/junio/julio (M=5,6,7): last_seen NO cae antes de cut1 → 0 recycled.
- agosto (M=8): cut1 = 00:00 jun; last_seen (medio mayo) < cut1 y uso <24h → Caso 1 recycled.

Aserciones (cubren Req 5, 6, 7, 8 end-to-end):
1. Un `BillingClosure` por mes (mayo, junio, julio, agosto) — cuatro cabeceras.
2. Idempotencia: re-ejecutar un cierre ya hecho lanza `BillingAlreadyClosedError` y NO
   crea una segunda fila (respeta `uq_closure_org_period`).
3. Transiciones de estado: `new → billable` (mayo) y `billable → recycled` (agosto, solo
   las mayo inactivas). Nadie retrocede a `new`.
4. Montos calculados por el plan mensual por defecto (T1 = US$0.500/IP para los conteos
   pequeños de este ensayo escalado).
5. Secuencialidad (Req 7.4) y selección del mes pendiente más antiguo (`next_pending_period`),
   que es como el endpoint retroactivo avanza uno por uno.

Nota: es un ensayo ESCALADO. Los volúmenes reales de BBVA (Task 4: ~13 → 585 → 3136 →
6286 IPs acumuladas) se reducen a un puñado de workstations representativas; lo que se
valida es la LÓGICA temporal de los cortes y el pipeline completo, no el volumen.

_Requirements: todos (5, 6, 7, 8) — verificación end-to-end task 35_
"""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
import app.models  # noqa: F401 — registra todas las tablas en metadata
from app.models.organization import Organization
from app.models.workstation import Workstation
from app.models.billing import BillingClosure, BillingClosureItem
from app.services.billing_close_service import (
    billing_close_service,
    BillingAlreadyClosedError,
)
from app.services.billing_seed import seed_default_rate_plans


# ── Fixture: sesión con org BBVA (America/Lima) y planes por defecto ─────────


@pytest.fixture
def db_bbva():
    """Sesión SQLite in-memory con esquema completo, planes por defecto y org BBVA."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    # Sembrar planes tarifarios por defecto (mensual + anual). El cierre resuelve el plan
    # para calcular el monto; sin este seed, la resolución falla (fail-closed).
    seed_default_rate_plans(session.connection())
    session.commit()

    org = Organization(
        id=uuid.uuid4(),
        name="BBVA (ensayo retroactivo)",
        timezone="America/Lima",
        billing_mode="monthly",
    )
    session.add(org)
    session.commit()
    session._org = org
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _add_ws(db, *, ip_private, created_at, last_seen, is_online=False):
    """Inserta una workstation en estado inicial `new` (como en el alta real)."""
    ws = Workstation(
        id=uuid.uuid4(),
        organization_id=db._org.id,
        ip_private=ip_private,
        created_at=created_at,
        first_seen=created_at,
        last_seen=last_seen,
        billing_status="new",
        is_online=is_online,
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws


def _refresh(db, ws):
    """Relee la workstation fresca desde BD (estado commiteado)."""
    db.expire_all()
    return db.query(Workstation).filter(Workstation.id == ws.id).one()


def _seed_bbva(db):
    """Crea las workstations del ensayo. Timestamps en UTC naive (convención del modelo),
    elegidos lejos de la medianoche local para no depender del offset -05:00 de Lima."""
    # --- IPs de MAYO abandonadas pronto (uso corto <24h). Candidatas a recycled en agosto. ---
    mayo_inactivas = []
    for i in range(3):
        ws = _add_ws(
            db,
            ip_private=f"10.90.5.{i}",
            created_at=datetime(2026, 5, 3, 12, 0, 0),
            last_seen=datetime(2026, 5, 4, 6, 0, 0),  # ~18h de uso (<24h) → Caso 1
        )
        mayo_inactivas.append(ws)

    # --- IPs de MAYO que siguen activas hasta agosto. Permanecen billable. ---
    mayo_activas = []
    for i in range(2):
        ws = _add_ws(
            db,
            ip_private=f"10.90.15.{i}",
            created_at=datetime(2026, 5, 6, 12, 0, 0),
            last_seen=datetime(2026, 8, 10, 12, 0, 0),
        )
        mayo_activas.append(ws)

    # --- IPs que aparecen en JUNIO (activas). ---
    junio = []
    for i in range(2):
        ws = _add_ws(
            db,
            ip_private=f"10.91.6.{i}",
            created_at=datetime(2026, 6, 8, 12, 0, 0),
            last_seen=datetime(2026, 8, 10, 12, 0, 0),
        )
        junio.append(ws)

    # --- IPs que aparecen en JULIO (activas). ---
    julio = []
    for i in range(2):
        ws = _add_ws(
            db,
            ip_private=f"10.92.7.{i}",
            created_at=datetime(2026, 7, 9, 12, 0, 0),
            last_seen=datetime(2026, 8, 10, 12, 0, 0),
        )
        julio.append(ws)

    return {
        "mayo_inactivas": mayo_inactivas,
        "mayo_activas": mayo_activas,
        "junio": junio,
        "julio": julio,
    }


def _closures(db):
    """Todas las cabeceras de cierre de la org, ordenadas por periodo."""
    return (
        db.query(BillingClosure)
        .filter(BillingClosure.organization_id == db._org.id)
        .order_by(BillingClosure.period_year, BillingClosure.period_month)
        .all()
    )


def _monthly_amount_t1(billable_count: int) -> Decimal:
    """Monto esperado para conteos pequeños (todo dentro del tramo T1: US$0.500/IP)."""
    assert billable_count <= 100, "el ensayo escalado se mantiene dentro del tramo T1"
    return (Decimal("0.500") * billable_count).quantize(Decimal("0.01"))


# ── Ensayo end-to-end ────────────────────────────────────────────────────────


class TestEnsayoRetroactivoBBVA:
    """Ensayo dry-run de la secuencia mayo→agosto de BBVA (task 35)."""

    def test_secuencia_mayo_a_agosto_end_to_end(self, db_bbva):
        db = db_bbva
        grupos = _seed_bbva(db)

        # ── 1. Ejecutar la secuencia retroactiva en orden (oldest-first) ──────
        c_mayo = billing_close_service.close_month(db, db._org, 2026, 5)
        c_junio = billing_close_service.close_month(db, db._org, 2026, 6)
        c_julio = billing_close_service.close_month(db, db._org, 2026, 7)
        c_agosto = billing_close_service.close_month(db, db._org, 2026, 8)

        # ── 2. Un BillingClosure por mes: cuatro cabeceras ────────────────────
        cierres = _closures(db)
        assert [(c.period_year, c.period_month) for c in cierres] == [
            (2026, 5),
            (2026, 6),
            (2026, 7),
            (2026, 8),
        ], "debe existir exactamente un cierre por mes mayo..agosto"

        # ── 3. Conteos por mes (scope = created_at < cutoff) ─────────────────
        # mayo: 3 inactivas + 2 activas = 5 IPs, todas billable (aún ninguna reciclada).
        assert c_mayo.total_billable == 5
        assert c_mayo.total_recycled == 0

        # junio: +2 (junio) = 7 billable.
        assert c_junio.total_billable == 7
        assert c_junio.total_recycled == 0

        # julio: +2 (julio) = 9 billable.
        assert c_julio.total_billable == 9
        assert c_julio.total_recycled == 0

        # agosto: la ventana alcanza a las mayo inactivas → 3 recycled, 6 billable.
        assert c_agosto.total_recycled == 3, "agosto recicla las 3 mayo inactivas"
        assert c_agosto.total_billable == 6, "quedan 2 mayo activas + 2 junio + 2 julio"

        # ── 4. Transiciones de estado en la columna viva (definida por agosto) ─
        for ws in grupos["mayo_inactivas"]:
            assert _refresh(db, ws).billing_status == "recycled"
        for ws in grupos["mayo_activas"] + grupos["junio"] + grupos["julio"]:
            assert _refresh(db, ws).billing_status == "billable"

        # Nadie retrocede a 'new' tras el primer cierre.
        estados = {w.billing_status for w in db.query(Workstation).all()}
        assert "new" not in estados

        # ── 5. Montos por el plan mensual por defecto (tramo T1) ─────────────
        assert c_mayo.amount == _monthly_amount_t1(5)   # 5 × 0.50 = 2.50
        assert c_junio.amount == _monthly_amount_t1(7)  # 7 × 0.50 = 3.50
        assert c_julio.amount == _monthly_amount_t1(9)  # 9 × 0.50 = 4.50
        assert c_agosto.amount == _monthly_amount_t1(6)  # 6 × 0.50 = 3.00

        # El snapshot de agosto registra el estado histórico por IP.
        items_agosto = {
            it.ip_private: it
            for it in db.query(BillingClosureItem).filter(
                BillingClosureItem.closure_id == c_agosto.id
            )
        }
        for ws in grupos["mayo_inactivas"]:
            assert items_agosto[ws.ip_private].billing_status == "recycled"

    def test_idempotencia_no_duplica_cierre(self, db_bbva):
        """Re-ejecutar un cierre ya hecho lanza error y NO crea una segunda fila
        (respeta uq_closure_org_period)."""
        db = db_bbva
        _seed_bbva(db)

        billing_close_service.close_month(db, db._org, 2026, 5)

        # Re-cerrar mayo debe fallar (idempotencia, Req 7.6).
        with pytest.raises(BillingAlreadyClosedError):
            billing_close_service.close_month(db, db._org, 2026, 5)

        # Sigue habiendo un único cierre de mayo.
        cierres_mayo = (
            db.query(BillingClosure)
            .filter(
                BillingClosure.organization_id == db._org.id,
                BillingClosure.period_year == 2026,
                BillingClosure.period_month == 5,
            )
            .all()
        )
        assert len(cierres_mayo) == 1

    def test_next_pending_period_selecciona_el_mas_antiguo(self, db_bbva):
        """El motor selecciona el mes pendiente más antiguo (Req 7.2/7.3), que es como el
        endpoint retroactivo de superadmin avanza uno por uno."""
        db = db_bbva
        _seed_bbva(db)

        # Sin cierres: el pendiente más antiguo es mayo (primer created_at).
        pendiente = billing_close_service.next_pending_period(db, db._org)
        assert pendiente == (2026, 5)

        # Tras cerrar mayo, el siguiente pendiente es junio.
        billing_close_service.close_month(db, db._org, 2026, 5)
        assert billing_close_service.next_pending_period(db, db._org) == (2026, 6)
