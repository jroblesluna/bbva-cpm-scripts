"""
Tests unitarios de `ClosureReportService.build_contingency_summary`.

Verifican el contrato de las métricas de contingencia que alimentan el prompt IA, el PDF y el
endpoint report-data del Reporte de Cierre Mensual:

1. `activations_in_cycle` / `distinct_ws_activated`: cuenta SOLO activaciones
   (`contingency_active=true`) dentro del ciclo `[cycle_start, cutoff)`; excluye desactivaciones
   y eventos fuera de rango.
2. `active_at_cutoff` (reconstrucción point-in-time): una WS cuenta si su ÚLTIMO toggle con
   `created_at < cutoff` es una activación; si su último toggle es una desactivación, no cuenta.
3. `mass_vlan_events` (entrada masiva por VLAN): `>= _MASS_MIN_PER_VLAN` WS distintas de la misma
   VLAN activadas dentro de `_MASS_WINDOW_MINUTES` → al menos 1 evento masivo; activaciones
   dispersas → 0.
4. Fail-safe: ante una excepción al consultar la auditoría → `data_available=False` y ceros, sin
   propagar. Y una org sin datos devuelve ceros con `data_available=True`.

Convenciones: se reutiliza la fixture `db` de `tests/conftest.py` (SQLite in-memory con el
esquema completo, aislada por test). Se construyen a mano `Organization`, `VLAN`, `Workstation`,
`BillingClosure` y `AuditLog` (action_type `CONTINGENCY_TOGGLE`, con `new_values`).
"""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.models.organization import Organization
from app.models.vlan import VLAN
from app.models.workstation import Workstation
from app.models.billing import BillingClosure
from app.models.audit import AuditLog, ActionType
from app.services.closure_report_service import (
    ClosureReportService,
    ContingencySummary,
    _MASS_MIN_PER_VLAN,
    _MASS_WINDOW_MINUTES,
)


# Periodo de prueba fijo: cierre de 2026-05, ciclo [2026-05-01, 2026-06-01).
_YEAR = 2026
_MONTH = 5
_CYCLE_START = datetime(_YEAR, _MONTH, 1)
_CUTOFF = datetime(_YEAR, _MONTH + 1, 1)


def _make_org(db, name: str, *, forced_contingency: bool = False) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name=name,
        timezone="UTC",
        billing_mode="monthly",
        forced_contingency=forced_contingency,
    )
    db.add(org)
    db.flush()
    return org


def _make_vlan(db, org: Organization, name: str, *, forced_contingency: bool = False) -> VLAN:
    vlan = VLAN(
        id=uuid.uuid4(),
        organization_id=org.id,
        name=name,
        cidr_ranges=[],
        forced_contingency=forced_contingency,
    )
    db.add(vlan)
    db.flush()
    return vlan


_IP_COUNTER = [0]


def _make_ws(db, org: Organization, vlan: VLAN = None) -> Workstation:
    _IP_COUNTER[0] += 1
    ws = Workstation(
        id=uuid.uuid4(),
        organization_id=org.id,
        vlan_id=vlan.id if vlan is not None else None,
        ip_private=f"10.0.{_IP_COUNTER[0] // 256}.{_IP_COUNTER[0] % 256}",
        hostname=f"ws-{_IP_COUNTER[0]}",
        last_seen=_CYCLE_START,
    )
    db.add(ws)
    db.flush()
    return ws


def _make_closure(db, org: Organization) -> BillingClosure:
    closure = BillingClosure(
        id=uuid.uuid4(),
        organization_id=org.id,
        period_year=_YEAR,
        period_month=_MONTH,
        cutoff_at=_CUTOFF,
        mode="monthly",
        timezone="UTC",
        total_billable=0,
        total_recycled=0,
        total_archived=0,
        amount=Decimal("0.00"),
        tiers_applied=[],
    )
    db.add(closure)
    db.flush()
    return closure


def _make_toggle(
    db,
    org: Organization,
    ws: Workstation,
    *,
    active: bool,
    created_at: datetime,
) -> AuditLog:
    """Crea un AuditLog CONTINGENCY_TOGGLE con new_values.contingency_active = active."""
    log = AuditLog(
        id=uuid.uuid4(),
        workstation_id=ws.id,
        organization_id=org.id,
        action_type=ActionType.CONTINGENCY_TOGGLE,
        entity_type="workstation",
        entity_id=ws.id,
        new_values={"contingency_active": active},
        created_at=created_at,
    )
    db.add(log)
    db.flush()
    return log


@pytest.fixture
def service() -> ClosureReportService:
    return ClosureReportService()


def test_activations_count_only_true_toggles_in_cycle(db, service):
    """
    `activations_in_cycle` cuenta solo activaciones true dentro de [cycle_start, cutoff) y
    `distinct_ws_activated` las WS distintas; desactivaciones y eventos fuera de rango se excluyen.
    """
    org = _make_org(db, "Org Activaciones")
    vlan = _make_vlan(db, org, "VLAN A")
    ws1 = _make_ws(db, org, vlan)
    ws2 = _make_ws(db, org, vlan)

    base = _CYCLE_START + timedelta(days=2)

    # 2 activaciones true de WS distintas dentro del ciclo.
    _make_toggle(db, org, ws1, active=True, created_at=base)
    _make_toggle(db, org, ws2, active=True, created_at=base + timedelta(hours=1))
    # Una desactivación (false) dentro del ciclo → NO cuenta como activación.
    _make_toggle(db, org, ws1, active=False, created_at=base + timedelta(hours=2))
    # Activación ANTES del ciclo → fuera de rango.
    _make_toggle(db, org, ws2, active=True, created_at=_CYCLE_START - timedelta(days=1))
    # Activación EN/DESPUÉS del cutoff → fuera de rango (cutoff es exclusivo).
    _make_toggle(db, org, ws1, active=True, created_at=_CUTOFF)

    closure = _make_closure(db, org)
    summary = service.build_contingency_summary(db, org, closure)

    assert summary.data_available is True
    assert summary.activations_in_cycle == 2
    assert summary.distinct_ws_activated == 2


def test_active_at_cutoff_uses_last_toggle_before_cutoff(db, service):
    """
    `active_at_cutoff`: una WS cuyo último toggle < cutoff es activación cuenta; una WS cuyo
    último toggle es desactivación (salió de contingencia) no cuenta.
    """
    org = _make_org(db, "Org Cutoff")
    vlan = _make_vlan(db, org, "VLAN B")
    ws_still_active = _make_ws(db, org, vlan)   # último toggle = activación → cuenta
    ws_left = _make_ws(db, org, vlan)           # último toggle = desactivación → no cuenta
    ws_never = _make_ws(db, org, vlan)          # sin toggles → no cuenta

    base = _CYCLE_START + timedelta(days=1)

    # ws_still_active: activa y se queda activa.
    _make_toggle(db, org, ws_still_active, active=True, created_at=base)

    # ws_left: activa y luego desactiva (la desactivación es el último toggle).
    _make_toggle(db, org, ws_left, active=True, created_at=base)
    _make_toggle(db, org, ws_left, active=False, created_at=base + timedelta(hours=3))

    closure = _make_closure(db, org)
    summary = service.build_contingency_summary(db, org, closure)

    assert summary.data_available is True
    assert summary.active_at_cutoff == 1  # solo ws_still_active


def test_mass_vlan_event_detected_within_window(db, service):
    """
    `_MASS_MIN_PER_VLAN` WS distintas de la misma VLAN activadas dentro de
    `_MASS_WINDOW_MINUTES` → mass_vlan_events >= 1 (con detalle).
    """
    org = _make_org(db, "Org Masiva")
    vlan = _make_vlan(db, org, "VLAN Masiva")

    base = _CYCLE_START + timedelta(days=3)
    # Exactamente _MASS_MIN_PER_VLAN WS distintas, todas dentro de la ventana.
    for i in range(_MASS_MIN_PER_VLAN):
        ws = _make_ws(db, org, vlan)
        _make_toggle(
            db, org, ws, active=True,
            created_at=base + timedelta(minutes=i),  # todas < ventana
        )

    closure = _make_closure(db, org)
    summary = service.build_contingency_summary(db, org, closure)

    assert summary.data_available is True
    assert summary.mass_vlan_events >= 1
    assert any(d["count"] >= _MASS_MIN_PER_VLAN for d in summary.mass_vlan_detail)


def test_no_mass_event_when_activations_are_dispersed(db, service):
    """
    Pocas activaciones dispersas (separadas más allá de la ventana) → mass_vlan_events == 0.
    """
    org = _make_org(db, "Org Dispersa")
    vlan = _make_vlan(db, org, "VLAN Dispersa")

    base = _CYCLE_START + timedelta(days=4)
    # _MASS_MIN_PER_VLAN WS pero separadas más de _MASS_WINDOW_MINUTES entre sí.
    for i in range(_MASS_MIN_PER_VLAN):
        ws = _make_ws(db, org, vlan)
        _make_toggle(
            db, org, ws, active=True,
            created_at=base + timedelta(minutes=i * (_MASS_WINDOW_MINUTES + 5)),
        )

    closure = _make_closure(db, org)
    summary = service.build_contingency_summary(db, org, closure)

    assert summary.data_available is True
    assert summary.mass_vlan_events == 0


def test_forced_contingency_org_and_vlan(db, service):
    """`forced_org` y `forced_vlan_count` reflejan la contingencia forzada vigente."""
    org = _make_org(db, "Org Forzada", forced_contingency=True)
    _make_vlan(db, org, "VLAN Forzada 1", forced_contingency=True)
    _make_vlan(db, org, "VLAN Forzada 2", forced_contingency=True)
    _make_vlan(db, org, "VLAN Normal", forced_contingency=False)

    closure = _make_closure(db, org)
    summary = service.build_contingency_summary(db, org, closure)

    assert summary.data_available is True
    assert summary.forced_org is True
    assert summary.forced_vlan_count == 2


def test_empty_org_returns_zeros_with_data_available_true(db, service):
    """Una org sin toggles ni WS devuelve ceros con data_available=True (no es un fallo)."""
    org = _make_org(db, "Org Vacia")
    closure = _make_closure(db, org)

    summary = service.build_contingency_summary(db, org, closure)

    assert summary.data_available is True
    assert summary.activations_in_cycle == 0
    assert summary.distinct_ws_activated == 0
    assert summary.active_at_cutoff == 0
    assert summary.mass_vlan_events == 0
    assert summary.mass_org_events == 0
    assert summary.forced_vlan_count == 0
    assert summary.forced_org is False


def test_fail_safe_returns_zeros_and_data_available_false(db, service, monkeypatch):
    """
    Fail-safe: si una consulta interna lanza una excepción, se devuelve un summary en ceros con
    data_available=False, sin propagar (el reporte no debe romperse por las métricas).
    """
    org = _make_org(db, "Org FailSafe")
    closure = _make_closure(db, org)

    # Forzar el fail-safe: parchear db.query para que lance al calcular el resumen.
    def _boom(*args, **kwargs):
        raise RuntimeError("fallo simulado en la auditoria")

    monkeypatch.setattr(db, "query", _boom)

    summary = service.build_contingency_summary(db, org, closure)

    assert isinstance(summary, ContingencySummary)
    assert summary.data_available is False
    assert summary.activations_in_cycle == 0
    assert summary.active_at_cutoff == 0
    assert summary.mass_vlan_events == 0
    assert summary.mass_org_events == 0
