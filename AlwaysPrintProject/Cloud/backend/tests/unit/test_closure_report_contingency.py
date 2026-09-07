"""
Tests unitarios de `ClosureReportService.build_contingency_summary` (estadísticas de uso).

Verifican el NUEVO contrato de estadísticas de contingencia orientadas a valor operativo que
alimentan el prompt IA, el PDF (tabla) y el endpoint report-data del Reporte de Cierre Mensual:

1. Nivel ORGANIZACIÓN (scope=organization, esquema B): `org_entries`/`org_exits` cuentan los
   eventos ON/OFF forzados; `org_protection_seconds` suma el tiempo de estadía en contingencia
   emparejando ON→OFF (con corte a cycle_start y cutoff); `org_entry_datetimes` lista los
   timestamps de entrada YA convertidos a la tz de la org.
2. Nivel VLAN/AGENCIA (scope=vlan): `vlan_entries`/`vlan_exits` cuentan ON/OFF; el tiempo de
   protección se calcula por VLAN (agrupando por `entity_id`) y se suma.
3. Nivel WORKSTATION: esquema A (`contingency_active`) y esquema B (scope=workstation) mezclados;
   `ws_interventions` cuenta las intervenciones EMPAREJADAS entrada→salida (tickets ahorrados);
   un ON sin OFF suma a `ws_entries` pero NO a `ws_interventions`.
4. `max_affected_ws` es el MÁXIMO de affected_workstations entre los ON forzados (no la suma).
5. Timezone: el formateo de `org_entry_datetimes` respeta la tz de la org.
6. Fail-safe: ante una excepción → `data_available=False` y ceros; org vacía → ceros con
   `data_available=True`.
7. Smoke de `compose_pdf`: genera bytes `%PDF` con datos y con fail-safe (data_available=False).

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
    compose_pdf,
)


# Periodo de prueba fijo: cierre de 2026-05, ciclo [2026-05-01, 2026-06-01).
_YEAR = 2026
_MONTH = 5
_CYCLE_START = datetime(_YEAR, _MONTH, 1)
_CUTOFF = datetime(_YEAR, _MONTH + 1, 1)


def _make_org(
    db, name: str, *, forced_contingency: bool = False, timezone: str = "UTC"
) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name=name,
        timezone=timezone,
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


def _make_closure(db, org: Organization, *, timezone: str = "UTC") -> BillingClosure:
    closure = BillingClosure(
        id=uuid.uuid4(),
        organization_id=org.id,
        period_year=_YEAR,
        period_month=_MONTH,
        cutoff_at=_CUTOFF,
        mode="monthly",
        timezone=timezone,
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
    """Crea un AuditLog CONTINGENCY_TOGGLE del ESQUEMA A (new_values.contingency_active)."""
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


def _make_forced_toggle(
    db,
    org: Organization,
    *,
    forced: bool,
    scope: str,
    affected_workstations: int,
    created_at: datetime,
    entity_id=None,
    workstation_id=None,
) -> AuditLog:
    """
    Crea un AuditLog CONTINGENCY_TOGGLE del ESQUEMA B (contingencia forzada Org/VLAN/Workstation).

    new_values trae `forced_contingency`/`scope`/`source`/`force_all`/`affected_workstations` y
    `workstation_id = None` (salvo scope="workstation", donde puede venir poblado). El servicio
    agrupa por:
      - scope="vlan"        → `entity_id` (id de la VLAN, ver vlans.py).
      - scope="workstation" → `workstation_id` si viene, si no `entity_id`.
    Por eso este helper permite fijar `entity_id`/`workstation_id` para simular equipos/VLANs
    distintos.
    """
    if scope == "organization":
        entity_type = "organization"
        eid = entity_id if entity_id is not None else org.id
    elif scope == "vlan":
        entity_type = "vlan"
        eid = entity_id if entity_id is not None else org.id
    else:  # workstation
        entity_type = "workstation"
        eid = entity_id if entity_id is not None else org.id

    log = AuditLog(
        id=uuid.uuid4(),
        workstation_id=workstation_id,
        organization_id=org.id,
        action_type=ActionType.CONTINGENCY_TOGGLE,
        entity_type=entity_type,
        entity_id=eid,
        new_values={
            "forced_contingency": forced,
            "scope": scope,
            "source": "manual_endpoint",
            "force_all": True,
            "affected_workstations": affected_workstations,
        },
        created_at=created_at,
    )
    db.add(log)
    db.flush()
    return log


@pytest.fixture
def service() -> ClosureReportService:
    return ClosureReportService()


# === Nivel ORGANIZACIÓN ===


def test_org_entries_exits_paired_and_protection_time(db, service):
    """
    2 ON + 2 OFF scope=organization emparejados → org_entries=2, org_exits=2,
    org_protection_seconds = suma de las 2 estadías (>0); org_entry_datetimes tiene 2 elementos.
    """
    org = _make_org(db, "Org Emparejada")
    base = _CYCLE_START + timedelta(days=2)

    # Estadía 1: [base, base+1h] = 3600s. Estadía 2: [base+3h, base+3h+30m] = 1800s.
    _make_forced_toggle(db, org, forced=True, scope="organization", affected_workstations=5, created_at=base)
    _make_forced_toggle(db, org, forced=False, scope="organization", affected_workstations=5, created_at=base + timedelta(hours=1))
    _make_forced_toggle(db, org, forced=True, scope="organization", affected_workstations=5, created_at=base + timedelta(hours=3))
    _make_forced_toggle(db, org, forced=False, scope="organization", affected_workstations=5, created_at=base + timedelta(hours=3, minutes=30))

    closure = _make_closure(db, org)
    summary = service.build_contingency_summary(db, org, closure)

    assert summary.data_available is True
    assert summary.org_entries == 2
    assert summary.org_exits == 2
    assert summary.org_protection_seconds == 3600 + 1800
    assert len(summary.org_entry_datetimes) == 2


def test_org_protection_two_hours(db, service):
    """1 ON en t=base y 1 OFF en t=base+2h → org_protection_seconds == 7200."""
    org = _make_org(db, "Org 2h")
    base = _CYCLE_START + timedelta(days=1)

    _make_forced_toggle(db, org, forced=True, scope="organization", affected_workstations=1, created_at=base)
    _make_forced_toggle(db, org, forced=False, scope="organization", affected_workstations=1, created_at=base + timedelta(hours=2))

    closure = _make_closure(db, org)
    summary = service.build_contingency_summary(db, org, closure)

    assert summary.org_protection_seconds == 7200


def test_org_open_interval_cut_at_cutoff(db, service):
    """
    ON sin OFF (abierto al cierre) → se corta en cutoff: 1 ON en t=cutoff-1h →
    org_protection_seconds == 3600.
    """
    org = _make_org(db, "Org Abierta")
    _make_forced_toggle(
        db, org, forced=True, scope="organization",
        affected_workstations=1, created_at=_CUTOFF - timedelta(hours=1),
    )

    closure = _make_closure(db, org)
    summary = service.build_contingency_summary(db, org, closure)

    assert summary.org_entries == 1
    assert summary.org_exits == 0
    assert summary.org_protection_seconds == 3600


def test_org_off_without_on_cut_at_cycle_start(db, service):
    """
    OFF sin ON previo (venía del mes anterior) → arranca en cycle_start: 1 OFF en
    t=cycle_start+1h → org_protection_seconds == 3600.
    """
    org = _make_org(db, "Org Heredada")
    _make_forced_toggle(
        db, org, forced=False, scope="organization",
        affected_workstations=1, created_at=_CYCLE_START + timedelta(hours=1),
    )

    closure = _make_closure(db, org)
    summary = service.build_contingency_summary(db, org, closure)

    assert summary.org_entries == 0
    assert summary.org_exits == 1
    assert summary.org_protection_seconds == 3600


# === Nivel VLAN/AGENCIA ===


def test_vlan_entries_and_protection_per_entity(db, service):
    """
    Eventos scope=vlan con distintos entity_id → vlan_entries cuenta todos los ON y
    vlan_protection_seconds suma la protección de cada VLAN por separado.
    """
    org = _make_org(db, "Org VLAN")
    vlan_a = uuid.uuid4()
    vlan_b = uuid.uuid4()
    base = _CYCLE_START + timedelta(days=3)

    # VLAN A: [base, base+1h] = 3600s.
    _make_forced_toggle(db, org, forced=True, scope="vlan", affected_workstations=3, created_at=base, entity_id=vlan_a)
    _make_forced_toggle(db, org, forced=False, scope="vlan", affected_workstations=3, created_at=base + timedelta(hours=1), entity_id=vlan_a)
    # VLAN B: [base, base+30m] = 1800s.
    _make_forced_toggle(db, org, forced=True, scope="vlan", affected_workstations=4, created_at=base, entity_id=vlan_b)
    _make_forced_toggle(db, org, forced=False, scope="vlan", affected_workstations=4, created_at=base + timedelta(minutes=30), entity_id=vlan_b)

    closure = _make_closure(db, org)
    summary = service.build_contingency_summary(db, org, closure)

    assert summary.data_available is True
    assert summary.vlan_entries == 2  # un ON por VLAN
    assert summary.vlan_exits == 2
    assert summary.vlan_protection_seconds == 3600 + 1800
    # Los eventos VLAN no contaminan el nivel org.
    assert summary.org_entries == 0
    assert summary.org_protection_seconds == 0


# === Nivel WORKSTATION ===


def test_ws_interventions_paired_only(db, service):
    """
    Esquema A: 1 ws con ON→OFF = 1 intervención emparejada; otro ws con ON sin OFF NO suma
    intervención (pero sí ws_entries).
    """
    org = _make_org(db, "Org WS")
    vlan = _make_vlan(db, org, "VLAN WS")
    ws_paired = _make_ws(db, org, vlan)
    ws_open = _make_ws(db, org, vlan)
    base = _CYCLE_START + timedelta(days=4)

    # ws_paired: ON→OFF (1 intervención).
    _make_toggle(db, org, ws_paired, active=True, created_at=base)
    _make_toggle(db, org, ws_paired, active=False, created_at=base + timedelta(hours=1))
    # ws_open: ON sin OFF (no cierra intervención).
    _make_toggle(db, org, ws_open, active=True, created_at=base + timedelta(hours=2))

    closure = _make_closure(db, org)
    summary = service.build_contingency_summary(db, org, closure)

    assert summary.data_available is True
    assert summary.ws_entries == 2  # 2 ON
    assert summary.ws_exits == 1    # 1 OFF
    assert summary.ws_interventions == 1  # solo el par ON→OFF cuenta


def test_ws_scheme_b_workstation_scope_counts(db, service):
    """
    Esquema B scope=workstation: ON→OFF de un equipo → ws_entries/ws_exits +1 y 1 intervención
    emparejada; se agrupa por workstation_id (o entity_id si no viene).
    """
    org = _make_org(db, "Org WS Forzada")
    ws_id = uuid.uuid4()
    base = _CYCLE_START + timedelta(days=5)

    _make_forced_toggle(db, org, forced=True, scope="workstation", affected_workstations=1, created_at=base, workstation_id=ws_id)
    _make_forced_toggle(db, org, forced=False, scope="workstation", affected_workstations=1, created_at=base + timedelta(hours=1), workstation_id=ws_id)

    closure = _make_closure(db, org)
    summary = service.build_contingency_summary(db, org, closure)

    assert summary.ws_entries == 1
    assert summary.ws_exits == 1
    assert summary.ws_interventions == 1


# === max_affected_ws ===


def test_max_affected_ws_is_maximum_not_sum(db, service):
    """
    max_affected_ws = máximo de affected_workstations entre los ON forzados
    (ON con 5373 y 5382 → 5382, NO 10755).
    """
    org = _make_org(db, "Org Magnitud")
    base = _CYCLE_START + timedelta(days=6)

    _make_forced_toggle(db, org, forced=True, scope="organization", affected_workstations=5373, created_at=base)
    _make_forced_toggle(db, org, forced=False, scope="organization", affected_workstations=5373, created_at=base + timedelta(minutes=10))
    _make_forced_toggle(db, org, forced=True, scope="organization", affected_workstations=5382, created_at=base + timedelta(hours=1))

    closure = _make_closure(db, org)
    summary = service.build_contingency_summary(db, org, closure)

    assert summary.max_affected_ws == 5382


# === Timezone ===


def test_timezone_converts_org_entry_datetimes(db, service):
    """
    org.timezone="America/Lima" (UTC-5): un ON con created_at UTC → org_entry_datetimes[0]
    refleja el offset -05:00 y la hora local esperada.
    """
    org = _make_org(db, "Org Lima", timezone="America/Lima")
    # created_at UTC = 2026-05-10 15:00 → Lima = 10:00 -05:00.
    on_utc = datetime(_YEAR, _MONTH, 10, 15, 0, 0)
    _make_forced_toggle(db, org, forced=True, scope="organization", affected_workstations=1, created_at=on_utc)

    # closure.timezone vacío para que caiga a org.timezone; usamos UTC en closure y confiamos
    # en el orden closure.timezone or org.timezone. Para forzar org.timezone, dejamos closure UTC
    # NO: el servicio usa closure.timezone primero. Creamos el closure con la misma tz de la org.
    closure = _make_closure(db, org, timezone="America/Lima")
    summary = service.build_contingency_summary(db, org, closure)

    assert summary.timezone == "America/Lima"
    assert len(summary.org_entry_datetimes) == 1
    iso = summary.org_entry_datetimes[0]
    assert "-05:00" in iso
    assert "10:00:00" in iso


# === Fail-safe / vacío ===


def test_fail_safe_returns_zeros_and_data_available_false(db, service, monkeypatch):
    """
    Fail-safe: si una consulta interna lanza, se devuelve un summary en ceros con
    data_available=False, sin propagar.
    """
    org = _make_org(db, "Org FailSafe")
    closure = _make_closure(db, org)

    def _boom(*args, **kwargs):
        raise RuntimeError("fallo simulado en la auditoria")

    monkeypatch.setattr(db, "query", _boom)

    summary = service.build_contingency_summary(db, org, closure)

    assert isinstance(summary, ContingencySummary)
    assert summary.data_available is False
    assert summary.org_entries == 0
    assert summary.org_protection_seconds == 0
    assert summary.vlan_entries == 0
    assert summary.ws_interventions == 0
    assert summary.max_affected_ws == 0


def test_empty_org_returns_zeros_with_data_available_true(db, service):
    """Una org sin toggles ni WS devuelve ceros con data_available=True (no es un fallo)."""
    org = _make_org(db, "Org Vacia")
    closure = _make_closure(db, org)

    summary = service.build_contingency_summary(db, org, closure)

    assert summary.data_available is True
    assert summary.org_entries == 0
    assert summary.org_exits == 0
    assert summary.org_protection_seconds == 0
    assert summary.vlan_entries == 0
    assert summary.vlan_protection_seconds == 0
    assert summary.ws_entries == 0
    assert summary.ws_interventions == 0
    assert summary.forced_org_now is False
    assert summary.forced_vlan_count_now == 0
    assert summary.max_affected_ws == 0


def test_forced_state_now_reflects_current_flags(db, service):
    """forced_org_now / forced_vlan_count_now reflejan el estado vigente (no eventos del ciclo)."""
    org = _make_org(db, "Org Vigente", forced_contingency=True)
    _make_vlan(db, org, "VLAN Forzada 1", forced_contingency=True)
    _make_vlan(db, org, "VLAN Forzada 2", forced_contingency=True)
    _make_vlan(db, org, "VLAN Normal", forced_contingency=False)

    closure = _make_closure(db, org)
    summary = service.build_contingency_summary(db, org, closure)

    assert summary.forced_org_now is True
    assert summary.forced_vlan_count_now == 2


def test_to_dict_has_exact_new_fields(db, service):
    """to_dict() serializa EXACTAMENTE los nuevos campos (contrato con el schema/endpoint)."""
    summary = ContingencySummary(data_available=True)
    keys = set(summary.to_dict().keys())
    assert keys == {
        "data_available",
        "timezone",
        "org_entries",
        "org_exits",
        "org_entry_datetimes",
        "org_protection_seconds",
        "vlan_entries",
        "vlan_exits",
        "vlan_protection_seconds",
        "ws_entries",
        "ws_exits",
        "ws_interventions",
        "forced_org_now",
        "forced_vlan_count_now",
        "max_affected_ws",
    }


# === Smoke de compose_pdf (genera %PDF con datos y con fail-safe) ===


def _minimal_pdf_header():
    """SimpleNamespace mínimo con los atributos que compose_pdf lee de la cabecera del cierre."""
    from types import SimpleNamespace

    return SimpleNamespace(
        period_year=_YEAR,
        period_month=_MONTH,
        mode="monthly",
        is_retroactive=False,
        total_billable=10,
        total_recycled=2,
        total_archived=1,
        amount=Decimal("100.00"),
        tiers_applied=[
            {"from": 1, "to": 100, "rate": "1.00", "ips_in_tier": 10, "subtotal": "10.00"}
        ],
    )


def _minimal_org():
    from types import SimpleNamespace

    return SimpleNamespace(id=uuid.uuid4(), name="Org Smoke")


def test_compose_pdf_smoke_with_contingency_data():
    """compose_pdf con un ContingencySummary poblado genera bytes que empiezan con %PDF."""
    header = _minimal_pdf_header()
    org = _minimal_org()
    contingency = ContingencySummary(
        data_available=True,
        timezone="America/Lima",
        org_entries=2,
        org_exits=2,
        org_entry_datetimes=["2026-05-10T10:00:00-05:00", "2026-05-11T08:00:00-05:00"],
        org_protection_seconds=5400,
        vlan_entries=3,
        vlan_exits=3,
        vlan_protection_seconds=7200,
        ws_entries=4,
        ws_exits=4,
        ws_interventions=4,
        forced_org_now=True,
        forced_vlan_count_now=2,
        max_affected_ws=5382,
    )

    pdf_bytes = compose_pdf(
        header, [], [], b"", b"", "Analisis IA de ejemplo.", org, contingency=contingency
    )

    assert isinstance(pdf_bytes, (bytes, bytearray))
    assert bytes(pdf_bytes).startswith(b"%PDF")


def test_compose_pdf_smoke_failsafe_no_data():
    """compose_pdf con data_available=False (fail-safe) igual genera bytes %PDF."""
    header = _minimal_pdf_header()
    org = _minimal_org()
    contingency = ContingencySummary(data_available=False)

    pdf_bytes = compose_pdf(
        header, [], [], b"", b"", None, org, contingency=contingency
    )

    assert isinstance(pdf_bytes, (bytes, bytearray))
    assert bytes(pdf_bytes).startswith(b"%PDF")
