"""
Tests del motor de cierre mensual (`BillingCloseService.close_month`, task 14).

Cubren el comportamiento de negocio del cierre descrito en `design.md`
("Motor de cierre mensual") y en los requisitos 5, 6, 7.4 y 7.6:

1. Reglas de reciclaje Caso 1 (poco uso) y Caso 2 (abandono) con datos LÍMITE, usando el
   `last_seen` CRUDO (Req 5.4, 5.5, 5.6).
2. Alcance del recálculo: `created_at < cutoff`, exclusión de `archived` del recálculo pero
   inclusión en el snapshot (Req 5.2, 5.3, 6.3).
3. Paso 1 `new → billable` (Req 5.3.1).
4. Capping de `last_seen` a `cutoff` en el snapshot, sin tocar el `last_seen` crudo en BD
   (Req 5.7, 6.2).
5. Idempotencia: no se puede re-cerrar el mismo (org, año, mes) (Req 7.6).
6. Secuencialidad: no se puede saltar meses; el primer mes cerrable sí se permite (Req 7.4).
7. Estado vivo (Req 6.5): el último cierre define la columna viva; un cierre retroactivo
   anterior NO revierte la columna viva pero SÍ registra el histórico en su snapshot.
8. Escenario BBVA mayo–agosto 2026 (America/Lima): mayo/junio/julio cierran sin recycled y
   agosto produce los primeros recycled (las IPs de mayo que quedaron inactivas), reflejando
   las ventanas de corte M−2/M−3.

Convenciones (siguiendo `tests/integration/test_last_seen_persistence.py`): sesión SQLite
in-memory con el esquema completo + una `Organization` para la FK, y filas `Workstation`
construidas a mano. `close_month` controla su propia transacción (hace `commit`).

Nota (task 16): el cierre mensual ahora calcula el monto real (`amount` y `tiers_applied`)
a partir del plan por defecto sembrado en la sesión de test (`_seed_default_plans`) y de la
base `billable`. Los tests que verifican conteos también asertan el monto esperado según los
tramos por defecto (mensual). El aporte por IP (`tier_index`, `amount`) se cubre en su propia
clase de tests.

_Requirements: 5, 6, 7.4, 7.6, 8.3, 8.4_
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
    BillingSequenceError,
)
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
    # Sembrar los planes tarifarios por defecto (monthly + annual). El cierre mensual
    # (task 16) resuelve el plan para calcular el monto; sin este seed, resolve_plan
    # fallaría con BillingRateResolutionError (fail-closed).
    seed_default_rate_plans(session.connection())
    session.commit()
    return session, engine


@pytest.fixture
def db_utc():
    """Sesión con una org en timezone UTC (simplifica el cálculo de cortes en boundary tests)."""
    session, engine = _make_session()
    org = Organization(
        id=uuid.uuid4(),
        name="Org UTC Test",
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
def db_lima():
    """Sesión con una org en timezone America/Lima (escenario BBVA)."""
    session, engine = _make_session()
    org = Organization(
        id=uuid.uuid4(),
        name="BBVA Test",
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


def _add_ws(
    db,
    *,
    ip_private: str,
    created_at: datetime,
    last_seen: datetime,
    billing_status: str = "new",
    is_online: bool = False,
) -> Workstation:
    """Inserta una workstation con los campos relevantes para el cierre."""
    ws = Workstation(
        id=uuid.uuid4(),
        organization_id=db._org.id,
        ip_private=ip_private,
        created_at=created_at,
        first_seen=created_at,
        last_seen=last_seen,
        billing_status=billing_status,
        is_online=is_online,
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws


def _refresh(db, ws: Workstation) -> Workstation:
    """Relee la workstation fresca desde BD (para ver el estado commiteado)."""
    db.expire_all()
    return db.query(Workstation).filter(Workstation.id == ws.id).one()


def _items(db, closure: BillingClosure):
    """Devuelve los ítems del snapshot indexados por ip_private."""
    rows = (
        db.query(BillingClosureItem)
        .filter(BillingClosureItem.closure_id == closure.id)
        .all()
    )
    return {r.ip_private: r for r in rows}


def _close_up_to(db, year: int, month: int) -> BillingClosure:
    """
    Cierra secuencialmente desde el primer mes cerrable de la org (el `created_at` más
    antiguo de una IP) hasta `(year, month)`, respetando la secuencialidad (Req 7.4), y
    devuelve el cierre del mes objetivo.

    Los cortes de reciclaje son estables en cada mes intermedio, así que los cierres previos
    no alteran el resultado del cierre objetivo (una ws que aún no cumple la regla queda
    billable en los meses intermedios y se evalúa igual al llegar a M). Esto permite escribir
    tests de la REGLA de reciclaje sobre un mes M concreto sin que la validación de
    secuencialidad los rechace por tener `created_at` en un mes anterior.
    """
    first = billing_close_service._org_first_period(db, db._org)
    assert first is not None, "la org debe tener al menos una IP para cerrar"
    idx = first[0] * 12 + (first[1] - 1)
    target_idx = year * 12 + (month - 1)
    closure = None
    while idx <= target_idx:
        y, m0 = divmod(idx, 12)
        closure = billing_close_service.close_month(db, db._org, y, m0 + 1)
        idx += 1
    return closure


# ── 1. Caso 1 (poco uso) — datos límite ─────────────────────────────────────


class TestCaso1PocoUso:
    """
    Caso 1 (Req 5.4): `billable` AND `last_seen < cut1` AND `(last_seen − created_at) < 24h`
    → recycled. Con org en UTC, cerrando M=2026-05: cut1 = 00:00 2026-03-01 (M−2).
    """

    YEAR, MONTH = 2026, 5

    def _cuts(self):
        return compute_cuts("UTC", self.YEAR, self.MONTH)

    def test_last_seen_justo_antes_de_cut1_y_uso_menor_24h_recicla(self, db_utc):
        """last_seen 1s antes de cut1 y uso <24h → recycled."""
        cuts = self._cuts()
        last_seen = cuts.cut1 - timedelta(seconds=1)
        # Uso = 12h (< 24h): created_at 12h antes de last_seen.
        created_at = last_seen - timedelta(hours=12)
        ws = _add_ws(
            db_utc,
            ip_private="10.1.0.1",
            created_at=created_at,
            last_seen=last_seen,
            billing_status="billable",
        )

        _close_up_to(db_utc, self.YEAR, self.MONTH)

        assert _refresh(db_utc, ws).billing_status == "recycled"

    def test_uso_igual_o_mayor_24h_permanece_billable(self, db_utc):
        """last_seen antes de cut1 pero uso >= 24h → NO recicla (sigue billable)."""
        cuts = self._cuts()
        last_seen = cuts.cut1 - timedelta(seconds=1)
        # Uso = exactamente 24h (frontera: no es < 24h).
        created_at = last_seen - timedelta(hours=24)
        ws = _add_ws(
            db_utc,
            ip_private="10.1.0.2",
            created_at=created_at,
            last_seen=last_seen,
            billing_status="billable",
        )

        _close_up_to(db_utc, self.YEAR, self.MONTH)

        assert _refresh(db_utc, ws).billing_status == "billable"

    def test_last_seen_exactamente_en_cut1_permanece_billable(self, db_utc):
        """last_seen == cut1 (no es estrictamente <) y uso <24h → NO recicla."""
        cuts = self._cuts()
        last_seen = cuts.cut1  # frontera exacta: la condición es `< cut1`
        created_at = last_seen - timedelta(hours=1)
        ws = _add_ws(
            db_utc,
            ip_private="10.1.0.3",
            created_at=created_at,
            last_seen=last_seen,
            billing_status="billable",
        )

        _close_up_to(db_utc, self.YEAR, self.MONTH)

        assert _refresh(db_utc, ws).billing_status == "billable"

    def test_last_seen_despues_de_cut1_permanece_billable(self, db_utc):
        """last_seen posterior a cut1 (actividad reciente) → billable, sin importar el uso."""
        cuts = self._cuts()
        last_seen = cuts.cut1 + timedelta(days=10)
        created_at = last_seen - timedelta(hours=1)  # uso corto, pero last_seen es reciente
        ws = _add_ws(
            db_utc,
            ip_private="10.1.0.4",
            created_at=created_at,
            last_seen=last_seen,
            billing_status="billable",
        )

        _close_up_to(db_utc, self.YEAR, self.MONTH)

        assert _refresh(db_utc, ws).billing_status == "billable"


# ── 2. Caso 2 (abandono) — datos límite ─────────────────────────────────────


class TestCaso2Abandono:
    """
    Caso 2 (Req 5.5): `billable` AND `last_seen < cut2` → recycled, sin importar el uso.
    Con org en UTC, cerrando M=2026-05: cut2 = 00:00 2026-02-01 (M−3).
    """

    YEAR, MONTH = 2026, 5

    def _cuts(self):
        return compute_cuts("UTC", self.YEAR, self.MONTH)

    def test_last_seen_justo_antes_de_cut2_recicla_pese_a_uso_largo(self, db_utc):
        """last_seen 1s antes de cut2 recicla aunque el uso sea >> 24h (abandono)."""
        cuts = self._cuts()
        last_seen = cuts.cut2 - timedelta(seconds=1)
        # Uso enorme (30 días): irrelevante para Caso 2.
        created_at = last_seen - timedelta(days=30)
        ws = _add_ws(
            db_utc,
            ip_private="10.2.0.1",
            created_at=created_at,
            last_seen=last_seen,
            billing_status="billable",
        )

        _close_up_to(db_utc, self.YEAR, self.MONTH)

        assert _refresh(db_utc, ws).billing_status == "recycled"

    def test_last_seen_en_cut2_cae_a_caso1_y_con_uso_largo_permanece_billable(self, db_utc):
        """
        last_seen == cut2 no dispara Caso 2 (`< cut2`). Cae a la evaluación del Caso 1:
        como cut2 < cut1, `last_seen < cut1` es cierto, pero con uso >= 24h NO recicla.
        """
        cuts = self._cuts()
        last_seen = cuts.cut2  # exactamente en cut2 → no es < cut2
        created_at = last_seen - timedelta(days=5)  # uso largo → Caso 1 no aplica
        ws = _add_ws(
            db_utc,
            ip_private="10.2.0.2",
            created_at=created_at,
            last_seen=last_seen,
            billing_status="billable",
        )

        _close_up_to(db_utc, self.YEAR, self.MONTH)

        assert _refresh(db_utc, ws).billing_status == "billable"

    def test_last_seen_en_cut2_con_uso_corto_recicla_por_caso1(self, db_utc):
        """
        last_seen == cut2 (no dispara Caso 2), pero < cut1 y uso <24h → recicla por Caso 1.
        Confirma que la frontera de Caso 2 delega correctamente en Caso 1.
        """
        cuts = self._cuts()
        last_seen = cuts.cut2
        created_at = last_seen - timedelta(hours=2)  # uso corto
        ws = _add_ws(
            db_utc,
            ip_private="10.2.0.3",
            created_at=created_at,
            last_seen=last_seen,
            billing_status="billable",
        )

        _close_up_to(db_utc, self.YEAR, self.MONTH)

        assert _refresh(db_utc, ws).billing_status == "recycled"


# ── 3. Paso 1: new → billable ────────────────────────────────────────────────


class TestPaso1NewABillable:
    """Req 5.3.1: toda `new` dentro del corte pasa a `billable`."""

    YEAR, MONTH = 2026, 5

    def test_new_en_alcance_pasa_a_billable(self, db_utc):
        cuts = compute_cuts("UTC", self.YEAR, self.MONTH)
        # last_seen reciente para que no recicle tras convertirse a billable.
        ws = _add_ws(
            db_utc,
            ip_private="10.3.0.1",
            created_at=cuts.cutoff - timedelta(days=2),
            last_seen=cuts.cutoff - timedelta(hours=1),
            billing_status="new",
        )

        closure = billing_close_service.close_month(
            db_utc, db_utc._org, self.YEAR, self.MONTH
        )

        assert _refresh(db_utc, ws).billing_status == "billable"
        assert closure.total_billable == 1
        assert closure.total_recycled == 0
        # Monto (task 16): 1 IP en T1 (0.500) → 0.50 (Req 8.3, 8.4).
        assert closure.amount == Decimal("0.50")
        assert len(closure.tiers_applied) == 1
        assert closure.tiers_applied[0]["tier_index"] == 0
        assert closure.tiers_applied[0]["ips_in_tier"] == 1
        # No hay 'new' en el snapshot: el ítem quedó billable (Req 6.3).
        item = _items(db_utc, closure)["10.3.0.1"]
        assert item.billing_status == "billable"
        # Aporte por IP: tramo 0 y tarifa marginal 0.500.
        assert item.tier_index == 0
        assert item.amount == Decimal("0.5000")


# ── 4. Alcance: created_at >= cutoff excluido; archived fuera del recálculo ──


class TestAlcanceYArchived:
    """Req 5.2 (created_at < cutoff), Req 5.3/6.3 (archived no se recalcula pero entra al snapshot)."""

    YEAR, MONTH = 2026, 5

    def test_created_at_en_o_despues_de_cutoff_se_excluye(self, db_utc):
        """Una ws creada en/después del cutoff no entra al cierre (ni recalc ni snapshot)."""
        cuts = compute_cuts("UTC", self.YEAR, self.MONTH)
        ws_fuera = _add_ws(
            db_utc,
            ip_private="10.4.0.99",
            created_at=cuts.cutoff,  # exactamente en cutoff → fuera (`< cutoff`)
            last_seen=cuts.cutoff,
            billing_status="new",
        )

        closure = billing_close_service.close_month(
            db_utc, db_utc._org, self.YEAR, self.MONTH
        )

        # Sigue 'new' (no se tocó) y no está en el snapshot.
        assert _refresh(db_utc, ws_fuera).billing_status == "new"
        assert "10.4.0.99" not in _items(db_utc, closure)
        assert closure.total_billable == 0
        # Sin base facturable → monto 0.00 y desglose vacío (Req 8.4).
        assert closure.amount == Decimal("0.00")
        assert closure.tiers_applied == []

    def test_archived_no_se_recalcula_pero_entra_al_snapshot(self, db_utc):
        """Una ws archived dentro del corte se conserva archived y aparece en el snapshot."""
        cuts = compute_cuts("UTC", self.YEAR, self.MONTH)
        ws_arch = _add_ws(
            db_utc,
            ip_private="10.4.0.1",
            created_at=cuts.cutoff - timedelta(days=5),
            last_seen=cuts.cut2 - timedelta(days=10),  # inactiva, pero es archived
            billing_status="archived",
        )

        closure = billing_close_service.close_month(
            db_utc, db_utc._org, self.YEAR, self.MONTH
        )

        assert _refresh(db_utc, ws_arch).billing_status == "archived"
        assert closure.total_archived == 1
        item = _items(db_utc, closure)["10.4.0.1"]
        assert item.billing_status == "archived"
        # La archived no se factura: aporte 0 y sin tramo (Req 8.4).
        assert item.tier_index is None
        assert item.amount == Decimal("0")
        # Solo había una archived, sin billable → monto 0.00.
        assert closure.total_billable == 0
        assert closure.amount == Decimal("0.00")


# ── 5. Capping del snapshot ──────────────────────────────────────────────────


class TestCappingSnapshot:
    """Req 5.7 / 6.2: `last_seen_capped = min(last_seen, cutoff)` sin tocar el last_seen crudo."""

    YEAR, MONTH = 2026, 5

    def test_last_seen_posterior_a_cutoff_se_capa_en_snapshot(self, db_utc):
        cuts = compute_cuts("UTC", self.YEAR, self.MONTH)
        raw_last_seen = cuts.cutoff + timedelta(days=20)  # actividad posterior al mes cerrado
        ws = _add_ws(
            db_utc,
            ip_private="10.5.0.1",
            created_at=cuts.cutoff - timedelta(days=2),
            last_seen=raw_last_seen,
            billing_status="billable",
        )

        closure = billing_close_service.close_month(
            db_utc, db_utc._org, self.YEAR, self.MONTH
        )

        item = _items(db_utc, closure)["10.5.0.1"]
        # El snapshot capa a cutoff...
        assert item.last_seen_capped == cuts.cutoff
        # ...pero el last_seen CRUDO en BD no se modifica.
        assert _refresh(db_utc, ws).last_seen == raw_last_seen

    def test_last_seen_anterior_a_cutoff_no_se_modifica_en_snapshot(self, db_utc):
        cuts = compute_cuts("UTC", self.YEAR, self.MONTH)
        raw_last_seen = cuts.cutoff - timedelta(days=3)
        ws = _add_ws(
            db_utc,
            ip_private="10.5.0.2",
            created_at=cuts.cutoff - timedelta(days=10),
            last_seen=raw_last_seen,
            billing_status="billable",
        )

        closure = billing_close_service.close_month(
            db_utc, db_utc._org, self.YEAR, self.MONTH
        )

        item = _items(db_utc, closure)["10.5.0.2"]
        assert item.last_seen_capped == raw_last_seen


# ── 6. Idempotencia ──────────────────────────────────────────────────────────


class TestIdempotencia:
    """Req 7.6: cerrar dos veces el mismo (org, año, mes) falla con BillingAlreadyClosedError."""

    YEAR, MONTH = 2026, 5

    def test_cerrar_dos_veces_lanza_already_closed(self, db_utc):
        cuts = compute_cuts("UTC", self.YEAR, self.MONTH)
        _add_ws(
            db_utc,
            ip_private="10.6.0.1",
            created_at=cuts.cutoff - timedelta(days=2),
            last_seen=cuts.cutoff - timedelta(hours=1),
            billing_status="new",
        )

        billing_close_service.close_month(db_utc, db_utc._org, self.YEAR, self.MONTH)

        with pytest.raises(BillingAlreadyClosedError):
            billing_close_service.close_month(db_utc, db_utc._org, self.YEAR, self.MONTH)

        # No se creó un segundo cierre.
        total = (
            db_utc.query(BillingClosure)
            .filter(BillingClosure.organization_id == db_utc._org.id)
            .count()
        )
        assert total == 1


# ── 7. Secuencialidad ────────────────────────────────────────────────────────


class TestSecuencialidad:
    """Req 7.4: no se puede saltar meses; el primer mes cerrable sí se permite."""

    def test_cerrar_primer_mes_de_la_org_es_permitido(self, db_utc):
        """El mes del created_at más antiguo es el inicio del rango: no exige mes previo."""
        # created_at en marzo 2026 → primer mes cerrable = 2026-03.
        created_at = datetime(2026, 3, 10, 8, 0, 0)
        _add_ws(
            db_utc,
            ip_private="10.7.0.1",
            created_at=created_at,
            last_seen=datetime(2026, 3, 20, 9, 0, 0),
            billing_status="new",
        )

        # Cerrar marzo (primer mes) no debe lanzar.
        closure = billing_close_service.close_month(db_utc, db_utc._org, 2026, 3)
        assert closure.period_year == 2026 and closure.period_month == 3

    def test_saltar_un_mes_sin_cerrar_lanza_sequence_error(self, db_utc):
        """Con marzo cerrado, intentar cerrar mayo (saltando abril) falla."""
        created_at = datetime(2026, 3, 10, 8, 0, 0)
        _add_ws(
            db_utc,
            ip_private="10.7.0.2",
            created_at=created_at,
            last_seen=datetime(2026, 3, 20, 9, 0, 0),
            billing_status="new",
        )

        # Cerrar marzo (permitido, primer mes).
        billing_close_service.close_month(db_utc, db_utc._org, 2026, 3)

        # Saltar abril y cerrar mayo debe fallar (abril sin cerrar).
        with pytest.raises(BillingSequenceError):
            billing_close_service.close_month(db_utc, db_utc._org, 2026, 5)

    def test_cierre_secuencial_consecutivo_es_permitido(self, db_utc):
        """marzo → abril → mayo consecutivos no lanzan."""
        created_at = datetime(2026, 3, 10, 8, 0, 0)
        _add_ws(
            db_utc,
            ip_private="10.7.0.3",
            created_at=created_at,
            last_seen=datetime(2026, 4, 20, 9, 0, 0),
            billing_status="new",
        )

        billing_close_service.close_month(db_utc, db_utc._org, 2026, 3)
        billing_close_service.close_month(db_utc, db_utc._org, 2026, 4)
        closure_mayo = billing_close_service.close_month(db_utc, db_utc._org, 2026, 5)
        assert closure_mayo.period_month == 5


# ── 8. Estado vivo vs cierre retroactivo (Req 6.5) ───────────────────────────


class TestEstadoVivoVsRetroactivo:
    """
    Req 6.5: la columna viva refleja el ÚLTIMO cierre (mayor periodo). Un cierre retroactivo
    anterior NO revierte la columna viva, pero SÍ registra el histórico en su snapshot.
    """

    def test_cierre_reciente_actualiza_columna_viva(self, db_utc):
        """Tras cerrar el mes más reciente, la columna viva refleja el estado calculado."""
        created_at = datetime(2026, 1, 10, 8, 0, 0)
        # last_seen muy antiguo → al cerrar un mes reciente, recicla (Caso 2).
        ws = _add_ws(
            db_utc,
            ip_private="10.8.0.1",
            created_at=created_at,
            last_seen=datetime(2026, 1, 15, 9, 0, 0),
            billing_status="new",
        )

        # Cerrar secuencialmente hasta mayo; en mayo el last_seen (enero) < cut2 (feb) → recycled.
        for m in (1, 2, 3, 4, 5):
            billing_close_service.close_month(db_utc, db_utc._org, 2026, m)

        assert _refresh(db_utc, ws).billing_status == "recycled"

    def test_retroactivo_no_revierte_columna_viva_pero_registra_historico(self, db_utc):
        """
        La columna viva la fija el cierre de MAYOR periodo; los cierres anteriores solo
        registran histórico en su snapshot (Req 6.5). Se cierran enero..mayo de una ws activa
        en enero: en mayo recicla (last_seen de enero < cut2 de mayo) y esa es la columna viva.
        Se verifica que el snapshot de un mes intermedio (marzo) conserva el estado histórico
        de marzo (billable), distinto del estado vivo final (recycled).
        """
        created_at = datetime(2026, 1, 10, 8, 0, 0)
        ws = _add_ws(
            db_utc,
            ip_private="10.8.0.2",
            created_at=created_at,
            last_seen=datetime(2026, 1, 15, 9, 0, 0),
            billing_status="new",
        )

        closures = {}
        for m in (1, 2, 3, 4, 5):
            closures[m] = billing_close_service.close_month(db_utc, db_utc._org, 2026, m)

        # Estado vivo final = recycled (definido por mayo, el más reciente).
        assert _refresh(db_utc, ws).billing_status == "recycled"

        # En marzo (M=3): cut2 = 00:00 dic-2025, cut1 = 00:00 ene-2026.
        # last_seen (15-ene) NO < cut2 (dic) y NO < cut1 (1-ene)? 15-ene > 1-ene → no recicla.
        # => histórico de marzo debe ser billable, distinto del vivo (recycled).
        item_marzo = _items(db_utc, closures[3])["10.8.0.2"]
        assert item_marzo.billing_status == "billable"

        # En mayo (M=5): cut2 = 00:00 feb-2026, cut1 = 00:00 mar-2026.
        # last_seen (15-ene) < cut2 (1-feb) → recycled histórico en el snapshot de mayo.
        item_mayo = _items(db_utc, closures[5])["10.8.0.2"]
        assert item_mayo.billing_status == "recycled"

    def test_retroactivo_explicito_no_toca_columna_viva(self, db_utc):
        """
        La bandera `is_retroactive` se persiste tal cual en la cabecera del cierre. Con una ws
        de actividad continua (nunca recicla), se cierran enero..abril; el cierre de enero no es
        retroactivo y el de abril se marca retroactivo. La columna viva permanece billable
        (ningún cierre la recicla), demostrando que la bandera no altera el estado calculado.
        """
        # ws con actividad continua: nunca recicla en ninguno de estos meses.
        ws = _add_ws(
            db_utc,
            ip_private="10.8.0.3",
            created_at=datetime(2026, 1, 5, 8, 0, 0),
            last_seen=datetime(2026, 4, 25, 9, 0, 0),
            billing_status="new",
        )

        c_ene = billing_close_service.close_month(db_utc, db_utc._org, 2026, 1)
        billing_close_service.close_month(db_utc, db_utc._org, 2026, 2)
        billing_close_service.close_month(db_utc, db_utc._org, 2026, 3)
        c_abr = billing_close_service.close_month(
            db_utc, db_utc._org, 2026, 4, is_retroactive=True
        )

        # La bandera se persiste tal cual se pasó.
        assert c_ene.is_retroactive is False
        assert c_abr.is_retroactive is True
        # Columna viva: billable (actividad continua, nunca recicla).
        assert _refresh(db_utc, ws).billing_status == "billable"


# ── 9. Escenario BBVA mayo–agosto 2026 (America/Lima) ────────────────────────


class TestEscenarioBBVA:
    """
    Escenario BBVA (America/Lima), mayo–agosto 2026, versión reducida pero fiel a la lógica
    temporal de los cortes.

    Contexto real (Task 4): el `created_at` acumulado de IPs de BBVA crece por mes:
    mayo ~13, junio ~585, julio ~3136, agosto ~6286. Aquí se ESCALA a un puñado de
    workstations representativas, preservando lo esencial:

      - Un grupo de IPs "de mayo" que dejó de reportar poco después de crearse (last_seen a
        mediados de mayo, uso corto). Estas son las candidatas a reciclarse.
      - IPs que se van sumando en junio y julio y siguen activas.

    Ventanas de corte (para el mes M, tz America/Lima):
      - cerrar MAYO   (M=5): cut2 = 00:00 feb, cut1 = 00:00 mar.  last_seen de mayo NO es < esos cortes.
      - cerrar JUNIO  (M=6): cut2 = 00:00 mar, cut1 = 00:00 abr.  last_seen de mayo NO es < esos cortes.
      - cerrar JULIO  (M=7): cut2 = 00:00 abr, cut1 = 00:00 may.  last_seen de mayo (medio mayo) NO < 1-may.
      - cerrar AGOSTO (M=8): cut2 = 00:00 may, cut1 = 00:00 jun.  last_seen de mayo (medio mayo) < 1-jun (cut1)
                             y uso corto (<24h) → RECICLA por Caso 1. (Y si fuese < 1-may, Caso 2.)

    Conclusión esperada: mayo/junio/julio → 0 recycled; agosto → primeros recycled
    (exactamente las IPs de mayo inactivas y de uso corto).
    """

    TZ = "America/Lima"

    def _seed(self, db):
        """
        Crea las workstations del escenario. `created_at`/`last_seen` en UTC naive
        (convención del modelo); los valores están elegidos lejos de la medianoche local
        para no depender del offset (-05:00 de Lima) en las fronteras.
        """
        org = db._org

        # --- IPs de MAYO que se abandonan pronto (uso corto). Candidatas a recycled. ---
        # created_at 3-may, last_seen 4-may (uso ~1 día, tomamos <24h para Caso 1).
        mayo_inactivas = []
        for i in range(3):
            ws = _add_ws(
                db,
                ip_private=f"10.90.5.{i}",
                created_at=datetime(2026, 5, 3, 12, 0, 0),
                last_seen=datetime(2026, 5, 4, 6, 0, 0),  # uso 18h (<24h)
                billing_status="new",
            )
            mayo_inactivas.append(ws)

        # --- IPs de MAYO que siguen activas (last_seen se mueve mes a mes). ---
        mayo_activas = []
        for i in range(2):
            ws = _add_ws(
                db,
                ip_private=f"10.90.15.{i}",
                created_at=datetime(2026, 5, 6, 12, 0, 0),
                last_seen=datetime(2026, 8, 10, 12, 0, 0),  # activa hasta agosto
                billing_status="new",
            )
            mayo_activas.append(ws)

        # --- IPs que aparecen en JUNIO (activas). ---
        junio = []
        for i in range(4):
            ws = _add_ws(
                db,
                ip_private=f"10.90.6.{i}",
                created_at=datetime(2026, 6, 8, 12, 0, 0),
                last_seen=datetime(2026, 8, 10, 12, 0, 0),
                billing_status="new",
            )
            junio.append(ws)

        # --- IPs que aparecen en JULIO (activas). ---
        julio = []
        for i in range(5):
            ws = _add_ws(
                db,
                ip_private=f"10.90.7.{i}",
                created_at=datetime(2026, 7, 9, 12, 0, 0),
                last_seen=datetime(2026, 8, 10, 12, 0, 0),
                billing_status="new",
            )
            julio.append(ws)

        return {
            "mayo_inactivas": mayo_inactivas,
            "mayo_activas": mayo_activas,
            "junio": junio,
            "julio": julio,
        }

    def test_mayo_junio_julio_sin_recycled_agosto_primeros_recycled(self, db_lima):
        db = db_lima
        grupos = self._seed(db)

        # Cierres secuenciales mayo → agosto.
        c_mayo = billing_close_service.close_month(db, db._org, 2026, 5)
        c_junio = billing_close_service.close_month(db, db._org, 2026, 6)
        c_julio = billing_close_service.close_month(db, db._org, 2026, 7)
        c_agosto = billing_close_service.close_month(db, db._org, 2026, 8)

        # mayo/junio/julio: sin recycled.
        assert c_mayo.total_recycled == 0, "mayo no debe reciclar aún"
        assert c_junio.total_recycled == 0, "junio no debe reciclar aún"
        assert c_julio.total_recycled == 0, "julio no debe reciclar aún"

        # agosto: los primeros recycled = exactamente las 3 IPs de mayo inactivas de uso corto.
        assert c_agosto.total_recycled == 3, "agosto produce los primeros recycled"

        # Verificar que los recycled del snapshot de agosto son precisamente las de mayo inactivas.
        items_agosto = _items(db, c_agosto)
        recicladas = {ip for ip, it in items_agosto.items() if it.billing_status == "recycled"}
        esperadas = {ws.ip_private for ws in grupos["mayo_inactivas"]}
        assert recicladas == esperadas

        # Las activas siguen billable en agosto (columna viva).
        for ws in grupos["mayo_activas"] + grupos["junio"] + grupos["julio"]:
            assert _refresh(db, ws).billing_status == "billable"

        # Y las inactivas de mayo quedaron recycled en la columna viva (agosto es el más reciente).
        for ws in grupos["mayo_inactivas"]:
            assert _refresh(db, ws).billing_status == "recycled"

    def test_conteos_billable_por_mes_reflejan_altas_acumuladas(self, db_lima):
        """
        Verifica que la base billable crece con las altas acumuladas (created_at < cutoff)
        y que las inactivas de mayo permanecen billable hasta el cierre de agosto.

        Altas por mes (este escenario reducido): mayo=5 (3 inact + 2 act), junio=+4, julio=+5.
        - mayo   (cutoff = 1-jun): en alcance las 5 de mayo → billable=5, recycled=0.
        - junio  (cutoff = 1-jul): 5 + 4 = 9 → billable=9, recycled=0.
        - julio  (cutoff = 1-ago): 9 + 5 = 14 → billable=14, recycled=0.
        - agosto (cutoff = 1-sep): 14 en alcance; 3 reciclan → billable=11, recycled=3.
        """
        db = db_lima
        self._seed(db)

        c_mayo = billing_close_service.close_month(db, db._org, 2026, 5)
        c_junio = billing_close_service.close_month(db, db._org, 2026, 6)
        c_julio = billing_close_service.close_month(db, db._org, 2026, 7)
        c_agosto = billing_close_service.close_month(db, db._org, 2026, 8)

        assert (c_mayo.total_billable, c_mayo.total_recycled) == (5, 0)
        assert (c_junio.total_billable, c_junio.total_recycled) == (9, 0)
        assert (c_julio.total_billable, c_julio.total_recycled) == (14, 0)
        assert (c_agosto.total_billable, c_agosto.total_recycled) == (11, 3)

        # Monto (task 16): con todos los billable dentro del T1 (1–100, tarifa 0.500), el
        # monto mensual es billable × 0.50 (Req 8.3, 8.4).
        assert c_mayo.amount == Decimal("2.50")    # 5 × 0.50
        assert c_junio.amount == Decimal("4.50")   # 9 × 0.50
        assert c_julio.amount == Decimal("7.00")   # 14 × 0.50
        assert c_agosto.amount == Decimal("5.50")  # 11 × 0.50 (3 recicladas no facturan)


# ── 10. Integración del cálculo de monto (task 16) ───────────────────────────


class TestMontoMensual:
    """
    Req 8.3, 8.4: tras el cierre, el monto de cabecera y el aporte por IP se calculan con el
    plan mensual por defecto (T1: 1–100 @0.500, T2: 101–2000 @0.250, ...).
    """

    YEAR, MONTH = 2026, 5

    def _add_billable(self, db, n: int):
        """
        Crea `n` workstations que quedarán billable en el cierre de mayo (last_seen reciente,
        creadas dentro del corte). Devuelve la lista de ws creadas.
        """
        cuts = compute_cuts("UTC", self.YEAR, self.MONTH)
        wss = []
        for i in range(n):
            ws = _add_ws(
                db,
                ip_private=f"10.16.{i // 254}.{i % 254 + 1}",
                created_at=cuts.cutoff - timedelta(days=5) + timedelta(seconds=i),
                last_seen=cuts.cutoff - timedelta(hours=1),
                billing_status="new",
            )
            wss.append(ws)
        return wss

    def test_monto_un_solo_tramo(self, db_utc):
        """50 IPs, todas en T1 → 50 × 0.500 = 25.00; cada ítem aporta 0.5000 en tramo 0."""
        self._add_billable(db_utc, 50)

        closure = billing_close_service.close_month(
            db_utc, db_utc._org, self.YEAR, self.MONTH
        )

        assert closure.total_billable == 50
        assert closure.amount == Decimal("25.00")
        # Un solo tramo aplicado (T1).
        assert len(closure.tiers_applied) == 1
        assert closure.tiers_applied[0]["tier_index"] == 0
        assert closure.tiers_applied[0]["ips_in_tier"] == 50

        items = _items(db_utc, closure)
        billable_items = [it for it in items.values() if it.billing_status == "billable"]
        assert len(billable_items) == 50
        assert all(it.tier_index == 0 for it in billable_items)
        assert all(it.amount == Decimal("0.5000") for it in billable_items)
        # La suma de aportes por IP coincide con la cabecera (todo en un tramo, sin redondeo).
        assert sum((it.amount for it in billable_items), Decimal("0")) == Decimal("25.0000")

    def test_monto_multi_tramo_y_reconciliacion(self, db_utc):
        """
        150 IPs cruzan T1 y T2: 100 × 0.500 + 50 × 0.250 = 50.00 + 12.50 = 62.50.
        Verifica el desglose de cabecera, el reparto por tramo en los ítems y que la suma de
        aportes por IP reconcilia con el monto de cabecera.
        """
        self._add_billable(db_utc, 150)

        closure = billing_close_service.close_month(
            db_utc, db_utc._org, self.YEAR, self.MONTH
        )

        assert closure.total_billable == 150
        assert closure.amount == Decimal("62.50")

        # Desglose de cabecera: T1 con 100 IPs, T2 con 50 IPs.
        by_index = {t["tier_index"]: t for t in closure.tiers_applied}
        assert by_index[0]["ips_in_tier"] == 100
        assert by_index[1]["ips_in_tier"] == 50

        items = _items(db_utc, closure)
        billable_items = [it for it in items.values() if it.billing_status == "billable"]
        tramo0 = [it for it in billable_items if it.tier_index == 0]
        tramo1 = [it for it in billable_items if it.tier_index == 1]
        assert len(tramo0) == 100
        assert len(tramo1) == 50
        assert all(it.amount == Decimal("0.5000") for it in tramo0)
        assert all(it.amount == Decimal("0.2500") for it in tramo1)
        # Reconciliación: Σ aportes por IP == monto de cabecera (sin diferencia de redondeo).
        suma = sum((it.amount for it in billable_items), Decimal("0"))
        assert suma == Decimal("62.5000")
        assert suma.quantize(Decimal("0.01")) == closure.amount

    def test_recycled_no_factura(self, db_utc):
        """Una ws que recicla en el cierre no aporta monto (amount=0, tier_index=None)."""
        cuts = compute_cuts("UTC", self.YEAR, self.MONTH)
        # 1 billable activa (creada dentro del corte de mayo, last_seen reciente).
        self._add_billable(db_utc, 1)
        # 1 ws abandonada: creada mucho antes y con last_seen < cut2 → recycled (Caso 2).
        # Su created_at antiguo adelanta el primer mes cerrable, así que cerramos
        # secuencialmente hasta mayo con `_close_up_to` (evita el error de secuencialidad).
        _add_ws(
            db_utc,
            ip_private="10.16.200.1",
            created_at=cuts.cut2 - timedelta(days=30),
            last_seen=cuts.cut2 - timedelta(seconds=1),  # < cut2 → recycled (Caso 2)
            billing_status="billable",
        )

        closure = _close_up_to(db_utc, self.YEAR, self.MONTH)

        assert closure.total_billable == 1
        assert closure.total_recycled == 1
        assert closure.amount == Decimal("0.50")  # solo la billable factura

        items = _items(db_utc, closure)
        recicladas = [it for it in items.values() if it.billing_status == "recycled"]
        assert len(recicladas) == 1
        assert recicladas[0].tier_index is None
        assert recicladas[0].amount == Decimal("0")


class TestModalidadAnual:
    """
    Req 9.2 / 8.6: en modalidad anual, el invoice mensual es 0.00 durante la vigencia; los
    ítems facturables quedan sin tramo ni aporte (la liquidación anual es tasks 19-21).
    """

    YEAR, MONTH = 2026, 5

    @pytest.fixture
    def db_annual(self):
        """Sesión con una org en modalidad anual (timezone UTC)."""
        session, engine = _make_session()
        org = Organization(
            id=uuid.uuid4(),
            name="Org Anual Test",
            timezone="UTC",
            billing_mode="annual",
        )
        session.add(org)
        session.commit()
        session._org = org
        try:
            yield session
        finally:
            session.close()
            engine.dispose()

    def test_anual_amount_cero_y_items_sin_aporte(self, db_annual):
        cuts = compute_cuts("UTC", self.YEAR, self.MONTH)
        for i in range(3):
            _add_ws(
                db_annual,
                ip_private=f"10.17.0.{i + 1}",
                created_at=cuts.cutoff - timedelta(days=5),
                last_seen=cuts.cutoff - timedelta(hours=1),
                billing_status="new",
            )

        closure = billing_close_service.close_month(
            db_annual, db_annual._org, self.YEAR, self.MONTH
        )

        # Base billable presente pero invoice mensual 0.00 (Req 9.2).
        assert closure.total_billable == 3
        assert closure.amount == Decimal("0.00")
        assert closure.mode == "annual"
        # tiers_applied vacío (informativo) en anual.
        assert closure.tiers_applied == []

        items = _items(db_annual, closure)
        billable_items = [it for it in items.values() if it.billing_status == "billable"]
        assert len(billable_items) == 3
        assert all(it.tier_index is None for it in billable_items)
        assert all(it.amount == Decimal("0") for it in billable_items)
