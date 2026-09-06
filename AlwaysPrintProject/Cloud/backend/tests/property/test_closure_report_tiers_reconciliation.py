"""
Property tests (hypothesis) para la composición de tramos y la reconciliación de montos
del Reporte de Cierre Mensual (task 11.1).

Propiedades (ver design.md, sección "Property-based (opcional)"):

1. **Composición nunca infla el conteo**: para cualquier `count >= 0` y un plan de tramos
   válido, la suma de `ips_in_tier` del desglose (lo que `render_tiers_chart` grafica) NUNCA
   excede `count`. El gráfico de composición jamás muestra más IPs facturables de las que
   existen.

2. **Reconciliación con el motor de facturación**: el subtotal del desglose reconcilia con el
   `amount` de `billing_service.compute_amount_monthly` dentro de la tolerancia de redondeo
   (`< 0.01`, half-up), tal como lo valida `closure_report_service.validate_reconciliation`
   (que preserva `header.amount` como fuente de verdad).

Se usa el motor de facturación REAL (`compute_amount_monthly`) para derivar `amount` y
`tiers_applied` a partir del `count` y el plan generados por Hypothesis; no se mockea la lógica
de cálculo. Las estrategias están acotadas (count y tamaños de tramo razonables) para mantener
la suite rápida.

Feature: monthly-closure-report, Property: composición de tramos + reconciliación

**Validates: Requirements 4.2, 10.1**
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.services.billing_service import billing_service
from app.services.closure_report_service import (
    _tier_ips,
    validate_reconciliation,
    _RECONCILIATION_TOLERANCE,
)


# === Doble de la cabecera del cierre =========================================
#
# `validate_reconciliation` y `render_tiers_chart` solo leen `header.amount`,
# `header.tiers_applied` (y `header.id` de forma defensiva vía getattr). Se usa un doble
# ligero (duck-typing) en vez de la ORM `BillingClosure` para no requerir BD ni sesión, tal
# como sugiere el conftest de property tests.


@dataclass
class _FakeHeader:
    """Doble mínimo de `BillingClosure` para reconciliación (solo campos leídos)."""

    amount: Decimal
    tiers_applied: List[dict] = field(default_factory=list)
    id: str = "fake-closure"


@dataclass
class _FakeItem:
    """Doble mínimo de `BillingClosureItem` (solo `amount`)."""

    amount: Decimal


# === Estrategias =============================================================
#
# Genera un plan de tramos válido: contiguo, ordenado por `from`, con tarifas de hasta 3
# decimales, y un último tramo opcionalmente sin tope superior (`to = None`). El `count` se
# acota para mantener la suite rápida sin perder cobertura de fronteras de tramo.

_MAX_COUNT = 15_000


@st.composite
def tier_plan(draw) -> List[dict]:
    """
    Construye un plan de tramos contiguos y ordenados.

    - 1 a 5 tramos, empezando en `from = 1`.
    - Cada tramo tiene un ancho >= 1; los límites son contiguos (`to` del tramo N + 1 =
      `from` del tramo N+1).
    - El último tramo puede ser sin tope (`to = None`) para ejercer el caso "sin límite".
    - Tarifas positivas con hasta 3 decimales (como los planes reales del repo).
    """
    n_tiers = draw(st.integers(min_value=1, max_value=5))
    widths = draw(
        st.lists(st.integers(min_value=1, max_value=4000), min_size=n_tiers, max_size=n_tiers)
    )
    open_last = draw(st.booleans())

    tiers: List[dict] = []
    lo = 1
    for i, width in enumerate(widths):
        rate = draw(
            st.integers(min_value=1, max_value=2000).map(lambda milli: Decimal(milli) / 1000)
        )
        is_last = i == len(widths) - 1
        if is_last and open_last:
            tiers.append({"from": lo, "to": None, "rate": str(rate)})
        else:
            hi = lo + width - 1
            tiers.append({"from": lo, "to": hi, "rate": str(rate)})
            lo = hi + 1
    return tiers


_count_strategy = st.integers(min_value=0, max_value=_MAX_COUNT)


# === Propiedad 1: la composición nunca excede el conteo ======================


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(count=_count_strategy, tiers=tier_plan())
def test_sum_ips_in_tier_never_exceeds_count(count: int, tiers: List[dict]):
    """
    La suma de `ips_in_tier` del desglose (lo que grafica `render_tiers_chart`) nunca supera
    `count`. Verifica que el gráfico de composición no puede mostrar más IPs de las que hay.

    **Validates: Requirements 4.2**
    """
    _amount, breakdown = billing_service.compute_amount_monthly(count, tiers)

    # tiers_applied tal como se serializa en la cabecera del cierre.
    tiers_applied = [tb.to_dict() for tb in breakdown]

    # Suma vista por el renderer (usa el mismo helper `_tier_ips` que render_tiers_chart).
    total_ips = sum(_tier_ips(t) for t in tiers_applied)

    assert total_ips <= max(count, 0), (
        f"La composición mostró {total_ips} IPs facturables para un count={count}: "
        "no puede exceder el conteo real."
    )
    # Todas las IPs contadas son no negativas.
    assert all(_tier_ips(t) >= 0 for t in tiers_applied)


# === Propiedad 2: reconciliación con compute_amount_monthly ==================


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(count=_count_strategy, tiers=tier_plan())
def test_breakdown_reconciles_with_computed_amount(count: int, tiers: List[dict]):
    """
    El subtotal del desglose reconcilia con el `amount` de `compute_amount_monthly` dentro de
    la tolerancia de redondeo (`< 0.01`, half-up), según `validate_reconciliation`.

    Se construye la cabecera con el `amount` y el `tiers_applied` REALES del motor de
    facturación, y un item cuyo `amount` iguala el total (aporte por IP agregado), de modo que
    ambas ramas (desglose e items) deben reconciliar.

    **Validates: Requirements 10.1**
    """
    amount, breakdown = billing_service.compute_amount_monthly(count, tiers)
    tiers_applied = [tb.to_dict() for tb in breakdown]

    header = _FakeHeader(amount=amount, tiers_applied=tiers_applied)
    # Un único item que representa el total facturado (suma de aportes por IP == amount).
    items = [_FakeItem(amount=amount)]

    result = validate_reconciliation(header, items)

    assert result.reconciled, (
        f"No reconcilió: header={result.header_amount}, tiers_total={result.tiers_total} "
        f"(dif={result.tiers_diff}), items_total={result.items_total} "
        f"(dif={result.items_diff}), tolerancia={_RECONCILIATION_TOLERANCE}"
    )
    # La cabecera se preserva como fuente de verdad (no se altera).
    assert result.header_amount == amount.quantize(Decimal("0.01"))
    # Ambas diferencias por debajo de la tolerancia.
    assert result.tiers_diff < _RECONCILIATION_TOLERANCE
    assert result.items_diff < _RECONCILIATION_TOLERANCE
