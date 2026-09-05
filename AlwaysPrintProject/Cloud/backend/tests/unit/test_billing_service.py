"""
Tests de facturación mensual del módulo Usage and Billing (task 18).

Cubren `app/services/billing_service.py` (`BillingService`) y, a nivel de endpoint, la
gestión de tarifas de `app/api/v1/endpoints/billing_rates.py`. Requisitos referenciados:

- Req 8.3: cálculo mensual incremental por tramos (ejemplos de la propuesta: 13, 585,
  3.136 y 6.276 IPs) y fronteras de tramo.
- Req 8.4: la base facturable son las IPs `billable`; `count <= 0` → monto 0.00.
- Req 8.7: redondeo final half-up a 2 decimales (tarifas con hasta 3 decimales).
- Req 8.2: el plan individual de la organización tiene prioridad sobre el default vigente.
- Req 8.8: editar los defaults NO sobrescribe los planes de organización.

Convenciones (siguiendo `tests/unit/test_billing_close_service.py` y
`tests/unit/test_maps_key_endpoint.py`):

- Sesión SQLite in-memory con el esquema completo; se siembran los planes por defecto con
  `seed_default_rate_plans` (mismo helper que usa la migración y el bootstrap).
- Todo el dinero se compara con `Decimal` (nunca float), en línea con el principio del repo.
- Los tests de endpoint montan el router en una `FastAPI` aislada y sobreescriben
  `get_current_user`/`get_db` con `dependency_overrides` (patrón del repo), usando una
  sesión SQLite real para ejercer la lógica de query de verdad.
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
from app.core.security import get_current_user, require_admin
import app.models  # noqa: F401 — registra todas las tablas en metadata
from app.models.billing import BillingOrgPlan, BillingRatePlan
from app.models.organization import Organization
from app.models.user import User, UserRole
from app.api.v1.endpoints.billing_rates import router as billing_rates_router
from app.services.billing_seed import (
    MONTHLY_DEFAULT_TIERS,
    ANNUAL_DEFAULT_TIERS,
    seed_default_rate_plans,
)
from app.services.billing_service import (
    BillingRateResolutionError,
    BillingService,
    billing_service,
)


# ── Fixtures y helpers ──────────────────────────────────────────────────────


def _make_session(seed: bool = True):
    """
    Crea una sesión SQLite in-memory con el esquema completo.

    Si `seed=True`, siembra los planes por defecto (monthly + annual) usando el mismo helper
    idempotente de la migración/bootstrap, para que `resolve_plan` pueda caer al default.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    if seed:
        seed_default_rate_plans(session.connection())
        session.commit()
    return session, engine


@pytest.fixture
def db_seeded():
    """Sesión con planes por defecto sembrados y una org mensual para las FK."""
    session, engine = _make_session(seed=True)
    org = Organization(
        id=uuid.uuid4(),
        name="Org Test Billing",
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


@pytest.fixture
def db_unseeded():
    """Sesión SIN planes por defecto (para probar el fail-closed de resolve_plan)."""
    session, engine = _make_session(seed=False)
    org = Organization(
        id=uuid.uuid4(),
        name="Org Sin Plan",
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


def _default_monthly_plan(db) -> BillingRatePlan:
    """Devuelve el plan por defecto mensual sembrado en la sesión."""
    return (
        db.query(BillingRatePlan)
        .filter(
            BillingRatePlan.mode == "monthly",
            BillingRatePlan.is_default.is_(True),
        )
        .one()
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. compute_amount_monthly — ejemplos de la propuesta, fronteras y redondeo
# ─────────────────────────────────────────────────────────────────────────────


class TestComputeAmountMonthlyPropuesta:
    """
    Casos de la propuesta con los tramos por defecto (Req 8.3):
        T1 1–100 = 0.500 | T2 101–2000 = 0.250 | T3 2001–5000 = 0.200
        T4 5001–10000 = 0.180 | T5 10001+ = 0.175
    """

    def setup_method(self):
        # Instancia sin estado; se usan directamente los tramos por defecto del seed.
        self.svc = BillingService()
        self.tiers = MONTHLY_DEFAULT_TIERS

    def test_13_ips(self):
        """13 IPs → 13×0.500 = 6.50 (todas en T1)."""
        amount, breakdown = self.svc.compute_amount_monthly(13, self.tiers)
        assert amount == Decimal("6.50")
        # Solo aporta el primer tramo.
        assert len(breakdown) == 1
        assert breakdown[0].tier_index == 0
        assert breakdown[0].ips_in_tier == 13

    def test_585_ips(self):
        """585 IPs → 100×0.5 + 485×0.25 = 50 + 121.25 = 171.25."""
        amount, breakdown = self.svc.compute_amount_monthly(585, self.tiers)
        assert amount == Decimal("171.25")
        assert len(breakdown) == 2
        assert breakdown[0].ips_in_tier == 100
        assert breakdown[1].ips_in_tier == 485
        assert breakdown[1].tier_index == 1

    def test_3136_ips(self):
        """3.136 IPs → 100×0.5 + 1900×0.25 + 1136×0.20 = 50 + 475 + 227.20 = 752.20 (design)."""
        amount, breakdown = self.svc.compute_amount_monthly(3136, self.tiers)
        assert amount == Decimal("752.20")
        assert len(breakdown) == 3
        assert breakdown[0].ips_in_tier == 100     # T1: 1–100
        assert breakdown[1].ips_in_tier == 1900    # T2: 101–2000
        assert breakdown[2].ips_in_tier == 1136    # T3: 2001–3136
        # Subtotales exactos (sin redondear) por tramo.
        assert breakdown[0].subtotal == Decimal("50.000")
        assert breakdown[1].subtotal == Decimal("475.000")
        assert breakdown[2].subtotal == Decimal("227.200")

    def test_6276_ips(self):
        """
        6.276 IPs → 100×0.5 + 1900×0.25 + 3000×0.20 + 1276×0.18
                  = 50 + 475 + 600 + 229.68 = 1354.68.
        """
        amount, breakdown = self.svc.compute_amount_monthly(6276, self.tiers)
        assert amount == Decimal("1354.68")
        assert len(breakdown) == 4
        assert breakdown[0].ips_in_tier == 100     # T1
        assert breakdown[1].ips_in_tier == 1900    # T2
        assert breakdown[2].ips_in_tier == 3000    # T3: 2001–5000
        assert breakdown[3].ips_in_tier == 1276    # T4: 5001–6276
        assert breakdown[3].tier_index == 3
        assert breakdown[3].subtotal == Decimal("229.680")


class TestComputeAmountMonthlyFronteras:
    """Fronteras de los tramos por defecto (Req 8.3) y base facturable (Req 8.4)."""

    def setup_method(self):
        self.svc = BillingService()
        self.tiers = MONTHLY_DEFAULT_TIERS

    def test_0_ips_monto_cero_y_desglose_vacio(self):
        """count = 0 → 0.00 y sin desglose (Req 8.4)."""
        amount, breakdown = self.svc.compute_amount_monthly(0, self.tiers)
        assert amount == Decimal("0.00")
        assert breakdown == []

    def test_count_negativo_monto_cero(self):
        """count < 0 (defensivo) → 0.00 y sin desglose."""
        amount, breakdown = self.svc.compute_amount_monthly(-5, self.tiers)
        assert amount == Decimal("0.00")
        assert breakdown == []

    def test_100_ips_ultimo_del_primer_tramo(self):
        """100 IPs → borde superior de T1: 100×0.5 = 50.00, un solo tramo."""
        amount, breakdown = self.svc.compute_amount_monthly(100, self.tiers)
        assert amount == Decimal("50.00")
        assert len(breakdown) == 1
        assert breakdown[0].ips_in_tier == 100

    def test_101_ips_primera_del_segundo_tramo(self):
        """101 IPs → T1 completo + 1 IP en T2: 50 + 0.25 = 50.25."""
        amount, breakdown = self.svc.compute_amount_monthly(101, self.tiers)
        assert amount == Decimal("50.25")
        assert len(breakdown) == 2
        assert breakdown[1].ips_in_tier == 1

    def test_10000_ips_borde_superior_de_t4(self):
        """
        10.000 IPs → borde superior de T4 (sin entrar a T5):
            100×0.5 + 1900×0.25 + 3000×0.20 + 5000×0.18
            = 50 + 475 + 600 + 900 = 2025.00.
        """
        amount, breakdown = self.svc.compute_amount_monthly(10000, self.tiers)
        assert amount == Decimal("2025.00")
        assert len(breakdown) == 4          # no aparece T5
        assert breakdown[3].ips_in_tier == 5000

    def test_10001_ips_primera_del_ultimo_tramo_sin_tope(self):
        """
        10.001 IPs → una IP entra en T5 (10001+, sin tope superior):
            2025.00 (T1–T4) + 1×0.175 = 2025.175 → half-up → 2025.18.
        """
        amount, breakdown = self.svc.compute_amount_monthly(10001, self.tiers)
        assert amount == Decimal("2025.18")
        assert len(breakdown) == 5
        # El último tramo no tiene tope superior.
        assert breakdown[4].tier_index == 4
        assert breakdown[4].tier_to is None
        assert breakdown[4].ips_in_tier == 1


class TestComputeAmountMonthlyRedondeo:
    """Redondeo final half-up a 2 decimales con tarifas de 3 decimales (Req 8.7)."""

    def setup_method(self):
        self.svc = BillingService()

    def test_half_up_en_tercer_decimal(self):
        """
        Tramo único con tarifa 0.125 (3er decimal) y 1 IP → total 0.125.
        Half-up → 0.13 (half-even daría 0.12, ya que el 2 es par). Distingue el modo de
        redondeo exigido por Req 8.7.
        """
        tiers = [{"from": 1, "to": None, "rate": 0.125}]
        amount, breakdown = self.svc.compute_amount_monthly(1, tiers)
        assert amount == Decimal("0.13")
        # El subtotal crudo conserva la precisión antes de cuantizar.
        assert breakdown[0].subtotal == Decimal("0.125")

    def test_half_up_acumulado_de_varios_tramos(self):
        """
        Dos tramos que suman un 3er decimal = 5 exacto:
            T1: 3 IPs × 0.001 = 0.003 ; T2: 1 IP × 0.002 = 0.002 → total 0.005.
        Half-up sobre 0.005 → 0.01 (half-even daría 0.00). Se acumula sin redondear y solo
        el TOTAL se cuantiza (Req 8.7).
        """
        tiers = [
            {"from": 1, "to": 3, "rate": 0.001},
            {"from": 4, "to": None, "rate": 0.002},
        ]
        amount, _ = self.svc.compute_amount_monthly(4, tiers)
        assert amount == Decimal("0.01")

    def test_tarifa_string_preserva_decimales(self):
        """La tarifa puede venir como string en el JSON; se preserva vía Decimal(str(...))."""
        tiers = [{"from": 1, "to": None, "rate": "0.333"}]
        amount, _ = self.svc.compute_amount_monthly(3, tiers)
        # 3 × 0.333 = 0.999 → half-up → 1.00.
        assert amount == Decimal("1.00")


# ─────────────────────────────────────────────────────────────────────────────
# 2. resolve_plan — prioridad org vs default, vigencia y fail-closed
# ─────────────────────────────────────────────────────────────────────────────


class TestResolvePlan:
    """Resolución de plan (Req 8.2) con prioridad de org sobre default y vigencia."""

    def test_sin_plan_org_usa_default_vigente(self, db_seeded):
        """Sin plan de org → se usa el default vigente sembrado (Req 8.2)."""
        resolved = billing_service.resolve_plan(db_seeded, db_seeded._org, "monthly")
        assert resolved.source == "default"
        assert resolved.mode == "monthly"
        # Los tramos coinciden con los del seed por defecto.
        assert resolved.tiers == MONTHLY_DEFAULT_TIERS

    def test_plan_org_tiene_prioridad_sobre_default(self, db_seeded):
        """Con un plan de org para la modalidad → prevalece sobre el default (Req 8.2)."""
        org_tiers = [{"from": 1, "to": None, "rate": 0.100}]
        db_seeded.add(
            BillingOrgPlan(
                id=uuid.uuid4(),
                organization_id=db_seeded._org.id,
                mode="monthly",
                tiers=org_tiers,
                currency="USD",
                effective_from=None,
            )
        )
        db_seeded.commit()

        resolved = billing_service.resolve_plan(db_seeded, db_seeded._org, "monthly")
        assert resolved.source == "org"
        assert resolved.tiers == org_tiers

    def test_default_none_mode_usa_billing_mode_de_la_org(self, db_seeded):
        """Si `mode` es None, se usa `org.billing_mode` (monthly por defecto)."""
        resolved = billing_service.resolve_plan(db_seeded, db_seeded._org, None)
        assert resolved.mode == "monthly"
        assert resolved.source == "default"

    def test_filtrado_por_modalidad(self, db_seeded):
        """resolve_plan(annual) resuelve el default anual, no el mensual (mode filtering)."""
        resolved = billing_service.resolve_plan(db_seeded, db_seeded._org, "annual")
        assert resolved.mode == "annual"
        assert resolved.source == "default"
        assert resolved.tiers == ANNUAL_DEFAULT_TIERS

    def test_plan_org_de_otra_modalidad_no_interfiere(self, db_seeded):
        """
        Un plan de org ANNUAL no debe usarse al resolver MONTHLY: la modalidad monthly cae al
        default (tenant + mode isolation).
        """
        db_seeded.add(
            BillingOrgPlan(
                id=uuid.uuid4(),
                organization_id=db_seeded._org.id,
                mode="annual",
                tiers=[{"from": 1, "to": None, "rate": 9.99}],
                currency="USD",
                effective_from=None,
            )
        )
        db_seeded.commit()

        resolved_monthly = billing_service.resolve_plan(db_seeded, db_seeded._org, "monthly")
        assert resolved_monthly.source == "default"
        assert resolved_monthly.tiers == MONTHLY_DEFAULT_TIERS

    def test_plan_org_futuro_es_ignorado_usa_default(self, db_seeded):
        """
        Un plan de org con `effective_from` en el futuro aún NO está vigente → se usa el
        default vigente (Req 8.2: se toma el vigente <= ahora).
        """
        futuro = datetime.utcnow() + timedelta(days=30)
        db_seeded.add(
            BillingOrgPlan(
                id=uuid.uuid4(),
                organization_id=db_seeded._org.id,
                mode="monthly",
                tiers=[{"from": 1, "to": None, "rate": 0.010}],
                currency="USD",
                effective_from=futuro,
            )
        )
        db_seeded.commit()

        resolved = billing_service.resolve_plan(db_seeded, db_seeded._org, "monthly")
        assert resolved.source == "default"

    def test_entre_dos_planes_org_gana_el_mas_reciente_vigente(self, db_seeded):
        """
        Con dos planes de org vigentes (distinto `effective_from` <= ahora), se toma el de
        mayor `effective_from` (el más reciente aplicable).
        """
        viejo = datetime.utcnow() - timedelta(days=60)
        reciente = datetime.utcnow() - timedelta(days=1)
        db_seeded.add(
            BillingOrgPlan(
                id=uuid.uuid4(),
                organization_id=db_seeded._org.id,
                mode="monthly",
                tiers=[{"from": 1, "to": None, "rate": 0.400}],
                currency="USD",
                effective_from=viejo,
            )
        )
        db_seeded.add(
            BillingOrgPlan(
                id=uuid.uuid4(),
                organization_id=db_seeded._org.id,
                mode="monthly",
                tiers=[{"from": 1, "to": None, "rate": 0.300}],
                currency="USD",
                effective_from=reciente,
            )
        )
        db_seeded.commit()

        resolved = billing_service.resolve_plan(db_seeded, db_seeded._org, "monthly")
        assert resolved.source == "org"
        assert resolved.tiers == [{"from": 1, "to": None, "rate": 0.300}]

    def test_tenant_isolation_plan_de_otra_org_no_se_usa(self, db_seeded):
        """El plan de OTRA organización no debe resolverse para la org objetivo."""
        otra = Organization(
            id=uuid.uuid4(),
            name="Otra Org",
            timezone="UTC",
            billing_mode="monthly",
        )
        db_seeded.add(otra)
        db_seeded.commit()  # commitear la org antes de referenciarla en la FK del plan
        db_seeded.add(
            BillingOrgPlan(
                id=uuid.uuid4(),
                organization_id=otra.id,
                mode="monthly",
                tiers=[{"from": 1, "to": None, "rate": 0.001}],
                currency="USD",
                effective_from=None,
            )
        )
        db_seeded.commit()

        # La org objetivo no tiene plan propio → cae al default, no al de "otra".
        resolved = billing_service.resolve_plan(db_seeded, db_seeded._org, "monthly")
        assert resolved.source == "default"

    def test_fail_closed_sin_plan_ni_default(self, db_unseeded):
        """
        Sin plan de org y sin default vigente → BillingRateResolutionError (fail-closed).
        No se factura con tarifa desconocida.
        """
        with pytest.raises(BillingRateResolutionError):
            billing_service.resolve_plan(db_unseeded, db_unseeded._org, "monthly")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Editar defaults NO sobrescribe planes de organización (Req 8.8)
# ─────────────────────────────────────────────────────────────────────────────


class TestEditarDefaultsNoAfectaOrg:
    """Req 8.8: los cambios de defaults no sobrescriben los planes de organización."""

    def test_editar_default_no_cambia_plan_de_org(self, db_seeded):
        """
        1) Se crea un plan de org (tarifa 0.100).
        2) Se editan los tramos del plan por defecto.
        3) Al re-resolver para la org → sigue obteniendo los tramos de SU plan (0.100),
           no los del default editado.
        """
        org_tiers = [{"from": 1, "to": None, "rate": 0.100}]
        db_seeded.add(
            BillingOrgPlan(
                id=uuid.uuid4(),
                organization_id=db_seeded._org.id,
                mode="monthly",
                tiers=org_tiers,
                currency="USD",
                effective_from=None,
            )
        )
        db_seeded.commit()

        # Editar los tramos del plan por defecto (como haría el superadmin).
        default_plan = _default_monthly_plan(db_seeded)
        default_plan.tiers = [{"from": 1, "to": None, "rate": 0.999}]
        db_seeded.commit()

        resolved = billing_service.resolve_plan(db_seeded, db_seeded._org, "monthly")
        assert resolved.source == "org"
        assert resolved.tiers == org_tiers  # intacto pese a la edición del default

        # Y el cálculo usa la tarifa de la org, no la del default editado.
        amount, _ = billing_service.compute_amount_monthly(10, resolved.tiers)
        assert amount == Decimal("1.00")  # 10 × 0.100

    def test_editar_default_si_afecta_org_sin_plan_propio(self, db_seeded):
        """
        Contraparte: una org SIN plan propio sí ve el default editado (usa el default vigente).
        Confirma que el aislamiento del test anterior se debe al plan de org, no a otra causa.
        """
        default_plan = _default_monthly_plan(db_seeded)
        default_plan.tiers = [{"from": 1, "to": None, "rate": 0.200}]
        db_seeded.commit()

        resolved = billing_service.resolve_plan(db_seeded, db_seeded._org, "monthly")
        assert resolved.source == "default"
        amount, _ = billing_service.compute_amount_monthly(10, resolved.tiers)
        assert amount == Decimal("2.00")  # 10 × 0.200 (default editado)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Endpoints de tarifas (superadmin) — permisos y no-sobrescritura
# ─────────────────────────────────────────────────────────────────────────────


def _admin_user():
    """Superadmin: en este sistema es UserRole.ADMIN (organization_id = None)."""
    u = User(
        id=uuid.uuid4(),
        email=f"admin_{uuid.uuid4().hex}@system.com",
        password_hash="x",
        full_name="Super Admin",
        role=UserRole.ADMIN,
        organization_id=None,
    )
    return u


def _operator_user(org_id):
    """Operador (no superadmin) de una organización."""
    u = User(
        id=uuid.uuid4(),
        email=f"op_{uuid.uuid4().hex}@bbva.com",
        password_hash="x",
        full_name="Operador",
        role=UserRole.OPERATOR,
        organization_id=org_id,
    )
    return u


def _build_app(db, current_user):
    """
    Monta el router de tarifas en una FastAPI aislada con overrides de auth + get_db.

    Usa la sesión SQLite real `db` para que la lógica de query del endpoint (y de
    `resolve_plan`) se ejecute de verdad (patrón de test_maps_key_endpoint pero con BD real).
    """
    app = FastAPI()
    app.include_router(billing_rates_router, prefix="/billing")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: current_user
    return app


class TestEndpointsTarifas:
    """GET/PUT rate-plans y PUT organizations/{id}/plan (Req 8.1, 8.5, 8.8, 11.1)."""

    @pytest.mark.asyncio
    async def test_list_rate_plans_admin_ok(self, db_seeded):
        """El superadmin lista los planes por defecto (monthly + annual)."""
        app = _build_app(db_seeded, _admin_user())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/billing/rate-plans")
        assert resp.status_code == 200
        modes = sorted(p["mode"] for p in resp.json())
        assert modes == ["annual", "monthly"]
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_list_rate_plans_operador_403(self, db_seeded):
        """Un operador (no superadmin) recibe 403 (Req 11.1)."""
        app = _build_app(db_seeded, _operator_user(db_seeded._org.id))
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/billing/rate-plans")
        assert resp.status_code == 403
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_put_rate_plan_edita_tramos_mensuales(self, db_seeded):
        """El superadmin edita los tramos del plan mensual por defecto (Req 8.5)."""
        plan = _default_monthly_plan(db_seeded)
        nuevos_tiers = [
            {"from": 1, "to": 100, "rate": 0.4},
            {"from": 101, "to": None, "rate": 0.2},
        ]
        app = _build_app(db_seeded, _admin_user())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                f"/billing/rate-plans/{plan.id}",
                json={"tiers": nuevos_tiers},
            )
        assert resp.status_code == 200
        assert resp.json()["tiers"] == nuevos_tiers
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_upsert_org_plan_operador_403(self, db_seeded):
        """Un operador no puede crear/editar el plan de una org (Req 11.1)."""
        app = _build_app(db_seeded, _operator_user(db_seeded._org.id))
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                f"/billing/organizations/{db_seeded._org.id}/plan",
                json={
                    "mode": "monthly",
                    "tiers": [{"from": 1, "to": None, "rate": 0.1}],
                    "currency": "USD",
                },
            )
        assert resp.status_code == 403
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_upsert_org_plan_admin_crea_y_persiste(self, db_seeded):
        """El superadmin crea el plan de org; queda persistido y resoluble (Req 8.2)."""
        org_tiers = [{"from": 1, "to": None, "rate": 0.15}]
        app = _build_app(db_seeded, _admin_user())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                f"/billing/organizations/{db_seeded._org.id}/plan",
                json={"mode": "monthly", "tiers": org_tiers, "currency": "USD"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "monthly"
        assert body["tiers"] == org_tiers

        # El plan quedó en BD y ahora resolve_plan lo prioriza sobre el default.
        resolved = billing_service.resolve_plan(db_seeded, db_seeded._org, "monthly")
        assert resolved.source == "org"
        assert resolved.tiers == org_tiers
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_editar_default_via_endpoint_no_afecta_org(self, db_seeded):
        """
        Flujo end-to-end de Req 8.8 vía endpoints:
        1) crear plan de org (0.15), 2) editar el default vía PUT, 3) re-resolver → sigue org.
        """
        admin = _admin_user()
        org_tiers = [{"from": 1, "to": None, "rate": 0.15}]
        app = _build_app(db_seeded, admin)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # 1) Crear plan de org.
            r1 = await client.put(
                f"/billing/organizations/{db_seeded._org.id}/plan",
                json={"mode": "monthly", "tiers": org_tiers, "currency": "USD"},
            )
            assert r1.status_code == 200

            # 2) Editar el default mensual.
            plan = _default_monthly_plan(db_seeded)
            r2 = await client.put(
                f"/billing/rate-plans/{plan.id}",
                json={"tiers": [{"from": 1, "to": None, "rate": 0.999}]},
            )
            assert r2.status_code == 200

        # 3) La org sigue con su plan (Req 8.8).
        resolved = billing_service.resolve_plan(db_seeded, db_seeded._org, "monthly")
        assert resolved.source == "org"
        assert resolved.tiers == org_tiers
        app.dependency_overrides.clear()


# ─────────────────────────────────────────────────────────────────────────────
# 5. Endpoint de modalidad de organización (superadmin) — task 25 / Req 4.1
# ─────────────────────────────────────────────────────────────────────────────


class TestEndpointModalidadOrg:
    """PUT /billing/organizations/{id}/mode (Req 4.1, 4.6, 11.1)."""

    @pytest.mark.asyncio
    async def test_set_mode_admin_ok(self, db_seeded):
        """El superadmin cambia la modalidad monthly → annual y queda persistida."""
        app = _build_app(db_seeded, _admin_user())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                f"/billing/organizations/{db_seeded._org.id}/mode",
                json={"mode": "annual"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["billing_mode"] == "annual"
        assert body["organization_id"] == str(db_seeded._org.id)

        # Persistió en BD.
        db_seeded.refresh(db_seeded._org)
        assert db_seeded._org.billing_mode == "annual"
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_set_mode_operador_403(self, db_seeded):
        """Un operador (no superadmin) recibe 403 (Req 11.1)."""
        app = _build_app(db_seeded, _operator_user(db_seeded._org.id))
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                f"/billing/organizations/{db_seeded._org.id}/mode",
                json={"mode": "annual"},
            )
        assert resp.status_code == 403
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_set_mode_valor_invalido_422(self, db_seeded):
        """Una modalidad fuera del enum se rechaza con 422 (validación de schema)."""
        app = _build_app(db_seeded, _admin_user())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                f"/billing/organizations/{db_seeded._org.id}/mode",
                json={"mode": "weekly"},
            )
        assert resp.status_code == 422
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_set_mode_org_inexistente_404(self, db_seeded):
        """Una organización inexistente devuelve 404."""
        app = _build_app(db_seeded, _admin_user())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                f"/billing/organizations/{uuid.uuid4()}/mode",
                json={"mode": "monthly"},
            )
        assert resp.status_code == 404
        app.dependency_overrides.clear()
