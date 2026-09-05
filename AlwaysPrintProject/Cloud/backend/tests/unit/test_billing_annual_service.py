"""
Tests de la suscripción y liquidación anual del módulo Usage and Billing (task 21).

Cubren el comportamiento de negocio descrito en `design.md` (sección "Suscripción y
liquidación anual (informativa)") y los requisitos 9.2, 9.3 y 9.4:

1. `BillingAnnualService.create_subscription` (Req 9.1):
   - `start_date` = `created_at` del PRIMER registro de la organización.
   - `end_date` = aniversario − 1 día (con manejo de año bisiesto vía `relativedelta`).
   - Congela `tier_rate`/`tier_from`/`tier_to`/`tier_cap` y pone `org.billing_mode='annual'`.
   - Rechaza si no hay workstations (`BillingNoFirstRegistrationError`).
   - Rechaza una segunda suscripción activa (`BillingSubscriptionOverlapError`).

2. `compute_settlement` (Req 9.3, 9.4):
   - Tope de tramo: billable 10,500 con `tier_cap` 10,000 ⇒ real 10,000 (Req 9.3).
   - Crédito: real < declarado ⇒ `credit = (declarado − real) × tier_rate`, `charge = 0`.
   - Cargo: real > declarado ⇒ `charge = (real − declarado) × tier_rate`, `credit = 0`.
   - Sin tope: `real = billable_count`.
   - Indicador de "crecimiento libre" informativo (NO reclasifica).
   - Dinero en `Decimal`, half-up a 2 decimales.

3. `confirm_settlement` (Req 9.5): persiste el `settlement` (dinero como string), pasa a
   `status='settled'`; una segunda confirmación lanza `BillingSubscriptionAlreadySettledError`.

4. Invoice mensual US$ 0.00 durante la vigencia (Req 9.2): con una suscripción anual creada
   (que pone `billing_mode='annual'`), el cierre mensual genera `amount == 0.00` y
   `tiers_applied == []`.

5. Endpoints (superadmin, Req 11.1): GET liquidación (404 sin suscripción activa, admin OK),
   POST confirmar (aplica y segunda confirmación ⇒ 409), operador ⇒ 403.

Convenciones (siguiendo `tests/unit/test_billing_close_service.py` y
`tests/unit/test_billing_service.py`): sesión SQLite in-memory con el esquema completo,
planes por defecto sembrados con `seed_default_rate_plans`, filas `Workstation` a mano, y
tests de endpoint sobre una `FastAPI` aislada con `dependency_overrides` de
`get_db`/`get_current_user`. Todo el dinero se compara con `Decimal`.

_Requirements: 9.2, 9.3, 9.4_
"""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import get_current_user
import app.models  # noqa: F401 — registra todas las tablas en metadata
from app.models.organization import Organization
from app.models.user import User, UserRole
from app.models.workstation import Workstation
from app.models.billing import BillingAnnualSubscription, BillingClosure
from app.api.v1.endpoints.billing_annual import router as billing_annual_router
from app.services.billing_annual_service import (
    BillingAnnualService,
    BillingNoFirstRegistrationError,
    BillingSubscriptionAlreadySettledError,
    BillingSubscriptionOverlapError,
    billing_annual_service,
)
from app.services.billing_close_service import billing_close_service
from app.services.billing_seed import seed_default_rate_plans
from app.services.billing_time import compute_cuts


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
    # Sembrar los planes por defecto (monthly + annual). El indicador de crecimiento libre
    # de la liquidación resuelve el plan anual; sin este seed no se reportaría margen.
    seed_default_rate_plans(session.connection())
    session.commit()
    return session, engine


@pytest.fixture
def db():
    """Sesión con una org en modalidad mensual (la suscripción la pasará a anual)."""
    session, engine = _make_session()
    org = Organization(
        id=uuid.uuid4(),
        name="Org Anual Test",
        timezone="UTC",
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


def _add_ws(
    db,
    *,
    ip_private: str,
    created_at: datetime,
    billing_status: str = "billable",
    last_seen: datetime = None,
) -> Workstation:
    """Inserta una workstation con los campos relevantes para la suscripción/liquidación."""
    ws = Workstation(
        id=uuid.uuid4(),
        organization_id=db._org.id,
        ip_private=ip_private,
        created_at=created_at,
        first_seen=created_at,
        last_seen=last_seen or created_at,
        billing_status=billing_status,
        is_online=False,
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws


def _add_billable(db, n: int, *, created_at: datetime = None):
    """
    Crea `n` workstations en estado 'billable' (base de la liquidación, Req 9.3).

    Inserción en lote (un solo commit) para que los casos de alto volumen (10,500 IPs del
    tope de tramo) sean rápidos. Las IPs se generan sobre un espacio /8 amplio para no chocar
    con el límite de 254 por octeto ni duplicar `ip_private` (unique).
    """
    base = created_at or datetime(2026, 1, 1, 12, 0, 0)
    wss = []
    for i in range(n):
        # 10.a.b.c con a,b,c en 0..255 → hasta ~16M direcciones únicas.
        a = (i // 65536) % 256
        b = (i // 256) % 256
        c = i % 256
        wss.append(
            Workstation(
                id=uuid.uuid4(),
                organization_id=db._org.id,
                ip_private=f"10.{a}.{b}.{c}",
                created_at=base,
                first_seen=base,
                last_seen=base,
                billing_status="billable",
                is_online=False,
            )
        )
    db.bulk_save_objects(wss)
    db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# 1. create_subscription — fechas, congelación, modalidad y guards
# ─────────────────────────────────────────────────────────────────────────────


class TestCreateSubscription:
    """Req 9.1: derivación de fechas, congelación de tramo y coherencia de modalidad."""

    def test_start_es_created_at_del_primer_registro(self, db):
        """El inicio es el `created_at` más antiguo de una IP de la org (5-may-2026)."""
        # Primer registro 5-may-2026; una segunda IP posterior no debe adelantar el inicio.
        _add_ws(db, ip_private="10.20.0.1", created_at=datetime(2026, 5, 5, 9, 0, 0))
        _add_ws(db, ip_private="10.20.0.2", created_at=datetime(2026, 6, 1, 9, 0, 0))

        sub = billing_annual_service.create_subscription(
            db,
            db._org,
            declared_volume=100,
            tier_from=1,
            tier_rate=Decimal("5.00"),
            tier_to=100,
            tier_cap=None,
        )

        assert sub.start_date == datetime(2026, 5, 5, 9, 0, 0)

    def test_end_es_aniversario_menos_un_dia(self, db):
        """Fin = aniversario − 1 día: inicio 5-may-2026 ⇒ fin 4-may-2027 (Req 9.1)."""
        _add_ws(db, ip_private="10.20.0.1", created_at=datetime(2026, 5, 5, 9, 0, 0))

        sub = billing_annual_service.create_subscription(
            db,
            db._org,
            declared_volume=100,
            tier_from=1,
            tier_rate=Decimal("5.00"),
        )

        # Aniversario = 5-may-2027 ⇒ fin = 4-may-2027 (conserva la hora del inicio).
        assert sub.end_date == datetime(2027, 5, 4, 9, 0, 0)

    def test_congela_tramo_y_tope(self, db):
        """Se congelan tier_rate/tier_from/tier_to/tier_cap tal cual se declaran (Req 8.6)."""
        _add_ws(db, ip_private="10.20.0.1", created_at=datetime(2026, 5, 5, 9, 0, 0))

        sub = billing_annual_service.create_subscription(
            db,
            db._org,
            declared_volume=8000,
            tier_from=5801,
            tier_rate=Decimal("1.95"),
            tier_to=10000,
            tier_cap=10000,
        )

        assert sub.tier_from == 5801
        assert sub.tier_to == 10000
        assert sub.tier_cap == 10000
        # La tarifa se guarda como Decimal (dinero), sin pérdida de precisión.
        assert Decimal(str(sub.tier_rate)) == Decimal("1.95")
        assert sub.status == "active"

    def test_alinea_billing_mode_a_annual(self, db):
        """Crear la suscripción pone `org.billing_mode='annual'` (coherencia Req 9.2)."""
        assert db._org.billing_mode == "monthly"
        _add_ws(db, ip_private="10.20.0.1", created_at=datetime(2026, 5, 5, 9, 0, 0))

        billing_annual_service.create_subscription(
            db,
            db._org,
            declared_volume=100,
            tier_from=1,
            tier_rate=Decimal("5.00"),
        )

        assert db._org.billing_mode == "annual"

    def test_sin_workstations_lanza_no_first_registration(self, db):
        """Sin ninguna IP registrada no hay fecha de inicio posible (Req 9.1, fail-closed)."""
        with pytest.raises(BillingNoFirstRegistrationError):
            billing_annual_service.create_subscription(
                db,
                db._org,
                declared_volume=100,
                tier_from=1,
                tier_rate=Decimal("5.00"),
            )

    def test_segunda_suscripcion_activa_lanza_overlap(self, db):
        """No se permite una segunda suscripción activa para la misma org (guard de solape)."""
        _add_ws(db, ip_private="10.20.0.1", created_at=datetime(2026, 5, 5, 9, 0, 0))
        billing_annual_service.create_subscription(
            db,
            db._org,
            declared_volume=100,
            tier_from=1,
            tier_rate=Decimal("5.00"),
        )

        with pytest.raises(BillingSubscriptionOverlapError):
            billing_annual_service.create_subscription(
                db,
                db._org,
                declared_volume=200,
                tier_from=1,
                tier_rate=Decimal("5.00"),
            )

    def test_ano_bisiesto_29_feb_2024(self, db):
        """
        Inicio 2024-02-29 ⇒ aniversario 2025-02-28 (relativedelta ajusta el bisiesto) ⇒
        fin = aniversario − 1 día = 2025-02-27. Verifica el comportamiento real del servicio.
        """
        _add_ws(db, ip_private="10.20.0.1", created_at=datetime(2024, 2, 29, 10, 0, 0))

        sub = billing_annual_service.create_subscription(
            db,
            db._org,
            declared_volume=100,
            tier_from=1,
            tier_rate=Decimal("5.00"),
        )

        assert sub.start_date == datetime(2024, 2, 29, 10, 0, 0)
        # Aniversario 2025-02-28 (no existe 29-feb en 2025) ⇒ fin 2025-02-27.
        assert sub.end_date == datetime(2025, 2, 27, 10, 0, 0)


# ─────────────────────────────────────────────────────────────────────────────
# 2. compute_settlement — tope, crédito/cargo, sin tope, crecimiento libre
# ─────────────────────────────────────────────────────────────────────────────


class TestComputeSettlement:
    """Req 9.3, 9.4: tope del tramo, crédito/cargo, y money en Decimal half-up."""

    def _make_sub(
        self,
        db,
        *,
        declared_volume,
        tier_rate,
        tier_from=5801,
        tier_to=10000,
        tier_cap=10000,
    ) -> BillingAnnualSubscription:
        """
        Crea una suscripción anual persistida SIN pasar por `create_subscription` (para
        controlar exactamente declared/cap y el conteo billable del test). Requiere al menos
        una workstation solo para tener una org válida; el conteo billable lo fija cada test.
        """
        sub = BillingAnnualSubscription(
            id=uuid.uuid4(),
            organization_id=db._org.id,
            start_date=datetime(2026, 5, 5, 9, 0, 0),
            end_date=datetime(2027, 5, 4, 9, 0, 0),
            declared_volume=declared_volume,
            tier_rate=Decimal(str(tier_rate)),
            tier_from=tier_from,
            tier_to=tier_to,
            tier_cap=tier_cap,
            status="active",
        )
        db.add(sub)
        db.commit()
        db.refresh(sub)
        return sub

    def test_tope_de_tramo_10500_a_10000(self, db):
        """
        Billable 10,500 con `tier_cap` 10,000 ⇒ real = 10,000 (Req 9.3). El billable_count
        informa el crudo (10,500) pero el real se capa al tope contratado.
        """
        _add_billable(db, 10500)
        sub = self._make_sub(db, declared_volume=10000, tier_rate="1.95", tier_cap=10000)

        s = billing_annual_service.compute_settlement(db, sub)

        assert s["billable_count"] == 10500
        assert s["real"] == 10000
        assert s["tier_cap"] == 10000

    def test_credito_cuando_real_menor_que_declarado(self, db):
        """
        real < declarado ⇒ crédito = (declarado − real) × tarifa, cargo = 0 (Req 9.4).
        200 billable, declarado 250, tarifa 2.50 ⇒ crédito = 50 × 2.50 = 125.00.
        """
        _add_billable(db, 200)
        sub = self._make_sub(
            db,
            declared_volume=250,
            tier_rate="2.50",
            tier_from=201,
            tier_to=2000,
            tier_cap=None,
        )

        s = billing_annual_service.compute_settlement(db, sub)

        assert s["real"] == 200
        assert s["diff"] == 50
        assert s["credit"] == Decimal("125.00")
        assert s["charge"] == Decimal("0.00")
        # El dinero es Decimal.
        assert isinstance(s["credit"], Decimal)
        assert isinstance(s["charge"], Decimal)

    def test_cargo_cuando_real_mayor_que_declarado(self, db):
        """
        real > declarado ⇒ cargo = (real − declarado) × tarifa, crédito = 0 (Req 9.4).
        300 billable, declarado 250, tarifa 2.50 ⇒ cargo = 50 × 2.50 = 125.00.
        """
        _add_billable(db, 300)
        sub = self._make_sub(
            db,
            declared_volume=250,
            tier_rate="2.50",
            tier_from=201,
            tier_to=2000,
            tier_cap=None,
        )

        s = billing_annual_service.compute_settlement(db, sub)

        assert s["real"] == 300
        assert s["diff"] == -50
        assert s["charge"] == Decimal("125.00")
        assert s["credit"] == Decimal("0.00")

    def test_sin_tope_real_igual_billable(self, db):
        """Sin `tier_cap` (None) ⇒ real = billable_count (no se capa)."""
        _add_billable(db, 137)
        sub = self._make_sub(
            db,
            declared_volume=137,
            tier_rate="2.50",
            tier_from=101,
            tier_to=2000,
            tier_cap=None,
        )

        s = billing_annual_service.compute_settlement(db, sub)

        assert s["billable_count"] == 137
        assert s["real"] == 137
        assert s["tier_cap"] is None
        # real == declarado ⇒ ni crédito ni cargo.
        assert s["diff"] == 0
        assert s["credit"] == Decimal("0.00")
        assert s["charge"] == Decimal("0.00")

    def test_dinero_half_up_dos_decimales(self, db):
        """
        Money con redondeo half-up a 2 decimales: tarifa 0.125 y diff 1 ⇒ 0.125 → 0.13
        (half-even daría 0.12). Confirma el modo de redondeo exigido.
        """
        _add_billable(db, 99)
        sub = self._make_sub(
            db,
            declared_volume=100,
            tier_rate="0.125",
            tier_from=1,
            tier_to=100,
            tier_cap=None,
        )

        s = billing_annual_service.compute_settlement(db, sub)

        assert s["diff"] == 1  # declarado 100 − real 99
        assert s["credit"] == Decimal("0.13")  # 1 × 0.125 = 0.125 → half-up → 0.13

    def test_crecimiento_libre_informativo_no_reclasifica(self, db):
        """
        El indicador de crecimiento libre resuelve el `free_growth_to` del tramo anual
        contratado (Req 9.6) y es SOLO informativo: no cambia el estado de ninguna IP.
        Tramo anual 201–2000 declara free_growth_to=2250; con real=200 → within_free_growth.
        """
        _add_billable(db, 200)
        sub = self._make_sub(
            db,
            declared_volume=200,
            tier_rate="2.50",
            tier_from=201,
            tier_to=2000,
            tier_cap=None,
        )

        s = billing_annual_service.compute_settlement(db, sub)

        fg = s["free_growth"]
        assert fg["free_growth_to"] == 2250
        assert fg["within_free_growth"] is True
        assert fg["requires_reclassification"] is False
        # No reclasifica: las IPs siguen 'billable' en BD.
        billable_now = (
            db.query(Workstation)
            .filter(
                Workstation.organization_id == db._org.id,
                Workstation.billing_status == "billable",
            )
            .count()
        )
        assert billable_now == 200

    def test_crecimiento_libre_excedido_requiere_reclasificacion(self, db):
        """Con real por encima del `free_growth_to` (2250) del tramo → requires_reclassification."""
        # 2300 billable, tope de tramo alto para no capar (real = 2300 > 2250).
        _add_billable(db, 2300)
        sub = self._make_sub(
            db,
            declared_volume=2300,
            tier_rate="2.50",
            tier_from=201,
            tier_to=2000,
            tier_cap=None,
        )

        s = billing_annual_service.compute_settlement(db, sub)

        fg = s["free_growth"]
        assert fg["free_growth_to"] == 2250
        assert fg["within_free_growth"] is False
        assert fg["requires_reclassification"] is True

    def test_compute_settlement_no_persiste(self, db):
        """El GET informativo no persiste: la suscripción sigue 'active' y sin settlement."""
        _add_billable(db, 10)
        sub = self._make_sub(
            db,
            declared_volume=10,
            tier_rate="5.00",
            tier_from=1,
            tier_to=100,
            tier_cap=None,
        )

        billing_annual_service.compute_settlement(db, sub)

        db.refresh(sub)
        assert sub.status == "active"
        assert sub.settlement is None


# ─────────────────────────────────────────────────────────────────────────────
# 3. confirm_settlement — persistencia y guard de doble confirmación
# ─────────────────────────────────────────────────────────────────────────────


class TestConfirmSettlement:
    """Req 9.5: aplicar manualmente la liquidación (status='settled') una sola vez."""

    def _make_sub(self, db, **kwargs) -> BillingAnnualSubscription:
        defaults = dict(
            declared_volume=250,
            tier_rate=Decimal("2.50"),
            tier_from=201,
            tier_to=2000,
            tier_cap=None,
        )
        defaults.update(kwargs)
        sub = BillingAnnualSubscription(
            id=uuid.uuid4(),
            organization_id=db._org.id,
            start_date=datetime(2026, 5, 5, 9, 0, 0),
            end_date=datetime(2027, 5, 4, 9, 0, 0),
            status="active",
            **defaults,
        )
        db.add(sub)
        db.commit()
        db.refresh(sub)
        return sub

    def test_confirm_persiste_settlement_y_marca_settled(self, db):
        """Persiste el JSON de liquidación (dinero como string) y pasa a 'settled'."""
        _add_billable(db, 200)  # real 200 < declarado 250 ⇒ crédito 125.00
        sub = self._make_sub(db)

        updated = billing_annual_service.confirm_settlement(db, sub)

        assert updated.status == "settled"
        assert updated.settlement is not None
        # El dinero se guarda como string para no perder precisión decimal.
        assert updated.settlement["credit"] == "125.00"
        assert updated.settlement["charge"] == "0.00"
        # tier_rate se persiste con la escala de la columna Numeric(12,4) leída de BD (2.5000);
        # se compara por valor Decimal para no acoplarse a los ceros de escala.
        assert Decimal(updated.settlement["tier_rate"]) == Decimal("2.50")
        assert updated.settlement["declared"] == 250
        assert updated.settlement["real"] == 200
        assert updated.settlement["diff"] == 50

    def test_segunda_confirmacion_lanza_already_settled(self, db):
        """Una segunda confirmación de la misma suscripción falla (fail-closed)."""
        _add_billable(db, 200)
        sub = self._make_sub(db)

        billing_annual_service.confirm_settlement(db, sub)

        with pytest.raises(BillingSubscriptionAlreadySettledError):
            billing_annual_service.confirm_settlement(db, sub)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Invoice mensual US$ 0.00 durante la vigencia (Req 9.2)
# ─────────────────────────────────────────────────────────────────────────────


class TestInvoiceMensualCeroEnAnual:
    """
    Req 9.2: con una suscripción anual creada (que pone `billing_mode='annual'`), el cierre
    mensual se ejecuta normalmente pero el invoice mensual es US$ 0.00. Test de integración
    que ata la suscripción real al cierre mensual (no solo un org en modo anual sintético).
    """

    YEAR, MONTH = 2026, 6

    def test_cierre_mensual_es_cero_con_suscripcion_activa(self, db):
        cuts = compute_cuts("UTC", self.YEAR, self.MONTH)

        # Altas dentro del corte de junio (created_at < cutoff, last_seen reciente).
        for i in range(4):
            _add_ws(
                db,
                ip_private=f"10.21.0.{i + 1}",
                created_at=cuts.cutoff - timedelta(days=10),
                last_seen=cuts.cutoff - timedelta(hours=1),
                billing_status="new",
            )

        # Crear la suscripción anual: alinea `org.billing_mode` a 'annual' (Req 9.2).
        billing_annual_service.create_subscription(
            db,
            db._org,
            declared_volume=100,
            tier_from=1,
            tier_rate=Decimal("5.00"),
            tier_to=100,
            tier_cap=None,
        )
        assert db._org.billing_mode == "annual"

        # Cerrar el mes: se ejecuta normalmente pero el monto es 0.00 (Req 9.2).
        closure = billing_close_service.close_month(db, db._org, self.YEAR, self.MONTH)

        assert closure.mode == "annual"
        assert closure.total_billable == 4  # base facturable presente...
        assert closure.amount == Decimal("0.00")  # ...pero invoice mensual 0.00
        assert closure.tiers_applied == []

        # Persistencia: no se creó un segundo cierre y el monto quedó en 0.00 en BD.
        stored = (
            db.query(BillingClosure)
            .filter(
                BillingClosure.organization_id == db._org.id,
                BillingClosure.period_year == self.YEAR,
                BillingClosure.period_month == self.MONTH,
            )
            .one()
        )
        assert stored.amount == Decimal("0.00")


# ─────────────────────────────────────────────────────────────────────────────
# 5. Endpoints (superadmin) — permisos, 404, aplicar y 409
# ─────────────────────────────────────────────────────────────────────────────


def _admin_user() -> User:
    """Superadmin: en este sistema es UserRole.ADMIN (organization_id = None)."""
    return User(
        id=uuid.uuid4(),
        email=f"admin_{uuid.uuid4().hex}@system.com",
        password_hash="x",
        full_name="Super Admin",
        role=UserRole.ADMIN,
        organization_id=None,
    )


def _operator_user(org_id) -> User:
    """Operador (no superadmin) de una organización."""
    return User(
        id=uuid.uuid4(),
        email=f"op_{uuid.uuid4().hex}@bbva.com",
        password_hash="x",
        full_name="Operador",
        role=UserRole.OPERATOR,
        organization_id=org_id,
    )


def _build_app(db, current_user) -> FastAPI:
    """
    Monta el router anual en una FastAPI aislada con overrides de auth + get_db.

    Usa la sesión SQLite real `db` para ejercer de verdad la lógica de query del endpoint y
    del servicio (patrón de `test_billing_service.py`).
    """
    app = FastAPI()
    app.include_router(billing_annual_router, prefix="/billing")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: current_user
    return app


class TestEndpointsAnual:
    """GET/POST liquidación anual (Req 9.3-9.5, 11.1)."""

    def _seed_active_subscription(self, db, *, declared_volume=250, tier_rate="2.50"):
        """Registra una suscripción anual activa con base billable=200 (crédito esperado)."""
        _add_billable(db, 200)
        sub = BillingAnnualSubscription(
            id=uuid.uuid4(),
            organization_id=db._org.id,
            start_date=datetime(2026, 5, 5, 9, 0, 0),
            end_date=datetime(2027, 5, 4, 9, 0, 0),
            declared_volume=declared_volume,
            tier_rate=Decimal(str(tier_rate)),
            tier_from=201,
            tier_to=2000,
            tier_cap=None,
            status="active",
        )
        db.add(sub)
        db.commit()
        return sub

    async def test_get_settlement_sin_suscripcion_activa_404(self, db):
        """Sin suscripción anual activa, el GET informativo devuelve 404."""
        app = _build_app(db, _admin_user())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                f"/billing/organizations/{db._org.id}/annual-settlement"
            )
        assert resp.status_code == 404
        app.dependency_overrides.clear()

    async def test_get_settlement_admin_ok(self, db):
        """El superadmin obtiene la liquidación informativa (crédito 125.00, real 200)."""
        self._seed_active_subscription(db)
        app = _build_app(db, _admin_user())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                f"/billing/organizations/{db._org.id}/annual-settlement"
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["real"] == 200
        assert body["declared"] == 250
        assert body["diff"] == 50
        assert Decimal(body["credit"]) == Decimal("125.00")
        assert Decimal(body["charge"]) == Decimal("0.00")
        app.dependency_overrides.clear()

    async def test_get_settlement_operador_403(self, db):
        """Un operador (no superadmin) recibe 403 (Req 11.1)."""
        self._seed_active_subscription(db)
        app = _build_app(db, _operator_user(db._org.id))
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                f"/billing/organizations/{db._org.id}/annual-settlement"
            )
        assert resp.status_code == 403
        app.dependency_overrides.clear()

    async def test_confirm_aplica_y_segunda_confirmacion_409(self, db):
        """El POST /confirm aplica (settled) y una segunda confirmación devuelve 409."""
        self._seed_active_subscription(db)
        app = _build_app(db, _admin_user())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r1 = await client.post(
                f"/billing/organizations/{db._org.id}/annual-settlement/confirm"
            )
            assert r1.status_code == 200
            assert r1.json()["status"] == "settled"
            assert r1.json()["settlement"]["credit"] == "125.00"

            # Tras confirmar, ya no hay suscripción 'active' → el endpoint responde 404.
            r2 = await client.post(
                f"/billing/organizations/{db._org.id}/annual-settlement/confirm"
            )
            assert r2.status_code == 404
        app.dependency_overrides.clear()

    async def test_confirm_operador_403(self, db):
        """Un operador no puede confirmar la liquidación (Req 11.1)."""
        self._seed_active_subscription(db)
        app = _build_app(db, _operator_user(db._org.id))
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/billing/organizations/{db._org.id}/annual-settlement/confirm"
            )
        assert resp.status_code == 403
        app.dependency_overrides.clear()
