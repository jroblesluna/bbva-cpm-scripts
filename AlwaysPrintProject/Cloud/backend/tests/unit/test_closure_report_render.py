"""
Tests unitarios del render server-side de gráficos del Reporte de Cierre Mensual (task 4.2).

Cubre las funciones puras a nivel de módulo `render_tiers_chart(tiers_applied)` y
`render_history_chart(history)` de `app/services/closure_report_service.py`, con foco en:

1. Salida válida: bytes PNG no vacíos (empiezan con la firma PNG `\\x89PNG\\r\\n\\x1a\\n`) en
   todos los escenarios, incluida la degradación elegante.
2. Degradación elegante (Req 4.5/4.6): tramos sin IPs facturables → placeholder; historia
   vacía → placeholder; historia de un solo punto → render mínimo (primer ciclo de servicio).
3. Sin fugas de figuras (Req 4.3): tras CADA llamada, `pyplot.get_fignums()` queda vacío, lo
   que confirma que `plt.close(fig)` se invocó (el backend headless "Agg" no debe acumular
   figuras en memoria).

Las funciones son puras (no requieren BD), por lo que no se usa la fixture `db`. El backend
"Agg" ya se fija a nivel de módulo en `closure_report_service` antes de importar pyplot.

_Requirements: 4.3, 4.5, 4.6_
"""

from decimal import Decimal

import matplotlib.pyplot as plt

from app.schemas.billing_closures import HistoryPoint
from app.services.closure_report_service import (
    render_history_chart,
    render_tiers_chart,
)

# Firma mágica de un archivo PNG (los primeros 8 bytes).
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _assert_valid_png(data: object) -> None:
    """Verifica que `data` sean bytes no vacíos con la firma PNG al inicio."""
    assert isinstance(data, (bytes, bytearray))
    assert len(data) > 0
    assert bytes(data).startswith(PNG_SIGNATURE)


def _assert_no_figure_leak() -> None:
    """Confirma que no quedan figuras abiertas (prueba que `plt.close(fig)` corrió)."""
    assert plt.get_fignums() == []


def _make_tier(tier_from, tier_to, ips_in_tier, rate="1.00", subtotal="0.00"):
    """Construye un dict de tramo con las claves que consume el render (from/to/ips_in_tier)."""
    return {
        "from": tier_from,
        "to": tier_to,
        "rate": rate,
        "ips_in_tier": ips_in_tier,
        "subtotal": subtotal,
    }


def _make_point(cycle, year, month, *, total_billable, amount):
    """Construye un `HistoryPoint` mínimo para alimentar el gráfico de evolución."""
    return HistoryPoint(
        cycle=cycle,
        period_year=year,
        period_month=month,
        total_billable=total_billable,
        total_recycled=0,
        total_archived=0,
        amount=Decimal(str(amount)),
    )


# === render_tiers_chart ===


def test_render_tiers_chart_normal_returns_png_and_no_leak():
    """Caso normal: varios tramos con IPs → PNG válido y sin fugas de figuras."""
    tiers = [
        _make_tier(1, 100, 100, rate="1.50", subtotal="150.00"),
        _make_tier(101, 500, 250, rate="1.20", subtotal="300.00"),
        _make_tier(501, None, 40, rate="1.00", subtotal="40.00"),
    ]

    png = render_tiers_chart(tiers)

    _assert_valid_png(png)
    _assert_no_figure_leak()


def test_render_tiers_chart_empty_uses_placeholder_and_no_leak():
    """Tramos vacíos (o sin IPs facturables) → placeholder PNG válido, sin excepción ni fugas."""
    # Lista vacía y lista con tramos de 0 IPs deben degradar al mismo placeholder.
    for tiers in ([], [_make_tier(1, 100, 0), _make_tier(101, None, 0)]):
        png = render_tiers_chart(tiers)
        _assert_valid_png(png)
        _assert_no_figure_leak()


# === render_history_chart ===


def test_render_history_chart_multi_point_returns_png_and_no_leak():
    """Serie histórica normal (varios ciclos) → PNG válido y sin fugas de figuras."""
    history = [
        _make_point(1, 2025, 1, total_billable=100, amount="150.00"),
        _make_point(2, 2025, 2, total_billable=140, amount="210.00"),
        _make_point(3, 2025, 3, total_billable=180, amount="270.00"),
    ]

    png = render_history_chart(history)

    _assert_valid_png(png)
    _assert_no_figure_leak()


def test_render_history_chart_single_point_returns_png_and_no_leak():
    """Un solo cierre → render mínimo (primer ciclo de servicio), PNG válido y sin fugas."""
    history = [_make_point(1, 2025, 1, total_billable=90, amount="120.00")]

    png = render_history_chart(history)

    _assert_valid_png(png)
    _assert_no_figure_leak()


def test_render_history_chart_empty_uses_placeholder_and_no_leak():
    """Historia vacía → placeholder PNG válido, sin excepción ni fugas de figuras."""
    png = render_history_chart([])

    _assert_valid_png(png)
    _assert_no_figure_leak()
