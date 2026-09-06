"""
Tests unitarios de `ClosureReportService.build_history_series` (task 3.2).

Verifica el contrato de la serie histórica de cierres que alimenta la evolución histórica
del Reporte de Cierre Mensual:

1. `cycle=1` para el cierre más antiguo (primer mes de servicio).
2. Numeración de ciclos creciente y consecutiva (1, 2, 3, ...).
3. Orden cronológico por `(period_year, period_month)` ascendente, independientemente del
   orden de inserción en la BD.
4. Filtrado exclusivo por `organization_id` (tenant isolation): los cierres de otra
   organización nunca aparecen en la serie.

Convenciones: se reutiliza la fixture `db` de `tests/conftest.py` (sesión SQLite in-memory
con el esquema completo, aislada por test). Se construyen `Organization` y `BillingClosure`
a mano con periodos desordenados.

_Requirements: 7.1, 7.2, 7.3, 8.6_
"""

import uuid
from datetime import datetime
from decimal import Decimal

import pytest

from app.models.organization import Organization
from app.models.billing import BillingClosure
from app.services.closure_report_service import ClosureReportService


def _make_org(db, name: str) -> Organization:
    """Crea y persiste una organización mínima para asociar cierres."""
    org = Organization(
        id=uuid.uuid4(),
        name=name,
        timezone="UTC",
        billing_mode="monthly",
    )
    db.add(org)
    db.flush()
    return org


def _make_closure(
    db,
    org: Organization,
    year: int,
    month: int,
    *,
    total_billable: int = 0,
    total_recycled: int = 0,
    total_archived: int = 0,
    amount: str = "0.00",
) -> BillingClosure:
    """Construye un cierre mensual mínimo para la organización dada."""
    closure = BillingClosure(
        id=uuid.uuid4(),
        organization_id=org.id,
        period_year=year,
        period_month=month,
        cutoff_at=datetime(year if month < 12 else year + 1, (month % 12) + 1, 1),
        mode="monthly",
        timezone="UTC",
        total_billable=total_billable,
        total_recycled=total_recycled,
        total_archived=total_archived,
        amount=Decimal(amount),
        tiers_applied=[],
    )
    db.add(closure)
    db.flush()
    return closure


@pytest.fixture
def service() -> ClosureReportService:
    return ClosureReportService()


def test_oldest_closure_is_cycle_1_and_ordered_by_period(db, service):
    """
    Con periodos insertados desordenados, la serie se ordena por (year, month) ASC y el
    cierre más antiguo recibe cycle=1 (Req 7.1, 7.3).
    """
    org = _make_org(db, "Org A")

    # Insertar deliberadamente desordenado (y cruzando año) para probar el ordenamiento.
    _make_closure(db, org, 2025, 3, total_billable=30)
    _make_closure(db, org, 2024, 11, total_billable=10)  # el más antiguo
    _make_closure(db, org, 2025, 1, total_billable=20)
    _make_closure(db, org, 2024, 12, total_billable=15)

    series = service.build_history_series(db, org)

    # Orden cronológico esperado por (period_year, period_month).
    periods = [(p.period_year, p.period_month) for p in series]
    assert periods == [(2024, 11), (2024, 12), (2025, 1), (2025, 3)]

    # El más antiguo (2024-11) es el ciclo 1.
    assert series[0].cycle == 1
    assert (series[0].period_year, series[0].period_month) == (2024, 11)
    assert series[0].total_billable == 10


def test_cycle_numbering_is_consecutive_and_increasing(db, service):
    """La numeración de ciclos es 1-based, creciente y consecutiva (Req 7.2)."""
    org = _make_org(db, "Org Consecutiva")

    for month in (6, 4, 5, 2, 3, 1):  # orden de inserción arbitrario
        _make_closure(db, org, 2026, month, total_billable=month)

    series = service.build_history_series(db, org)

    cycles = [p.cycle for p in series]
    assert cycles == list(range(1, len(series) + 1))  # 1, 2, 3, ... sin saltos
    assert cycles == [1, 2, 3, 4, 5, 6]

    # El ciclo N corresponde al mes N (por el orden cronológico).
    for point in series:
        assert point.cycle == point.period_month


def test_tenant_isolation_only_target_org(db, service):
    """
    Solo aparecen los cierres de la organización objetivo; los de otra org se excluyen y la
    numeración de ciclos se calcula de forma independiente por organización (Req 8.6).
    """
    org_a = _make_org(db, "Org A Tenant")
    org_b = _make_org(db, "Org B Tenant")

    # Org A: dos cierres.
    _make_closure(db, org_a, 2025, 1, total_billable=100)
    _make_closure(db, org_a, 2025, 2, total_billable=200)

    # Org B: tres cierres con periodos que se solapan con los de A.
    _make_closure(db, org_b, 2024, 12, total_billable=1)
    _make_closure(db, org_b, 2025, 1, total_billable=2)
    _make_closure(db, org_b, 2025, 2, total_billable=3)

    series_a = service.build_history_series(db, org_a)
    series_b = service.build_history_series(db, org_b)

    # Aislamiento: cada serie tiene solo sus propios cierres.
    assert len(series_a) == 2
    assert len(series_b) == 3

    # Ningún total de B se filtra en A y viceversa.
    assert [p.total_billable for p in series_a] == [100, 200]
    assert [p.total_billable for p in series_b] == [1, 2, 3]

    # La numeración de ciclos es independiente por org (ambas empiezan en 1).
    assert series_a[0].cycle == 1
    assert series_b[0].cycle == 1
    assert [p.cycle for p in series_a] == [1, 2]
    assert [p.cycle for p in series_b] == [1, 2, 3]


def test_empty_series_for_org_without_closures(db, service):
    """Una organización sin cierres produce una serie vacía (sin excepción)."""
    org = _make_org(db, "Org Sin Cierres")
    assert service.build_history_series(db, org) == []
