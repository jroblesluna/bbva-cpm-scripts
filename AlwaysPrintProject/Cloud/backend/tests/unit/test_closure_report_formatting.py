"""
Tests unitarios de los helpers de FORMATEO/PRESENTACION del Reporte de Cierre Mensual.

Cubre las funciones puras a nivel de módulo de `app/services/closure_report_service.py`:

1. `_fmt_money(value)` — importes SIEMPRE con 2 decimales (half-up), fail-safe "0.00".
2. `_fmt_closure_date(header, org)` — "Fecha de cierre" = día 1 del mes SIGUIENTE al periodo
   a las 00:00 hora local de la organización, formateada como `YYYY-MM-DD HH:MM (<tz>)`.
3. Markdown inline: `_split_bold_segments(text)` segmenta por `**...**` sin dejar asteriscos.

Son helpers puros (no requieren BD ni PDF real), por lo que se usan objetos stub simples
(`SimpleNamespace`) para `header`/`org`. Convenciones tomadas de `test_closure_report_render.py`.

_Requirements: BUG 1 (fecha de cierre), BUG 2 (montos 2 decimales), BUG 3 (markdown inline)_
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.closure_report_service import (
    _fmt_closure_date,
    _fmt_money,
    _split_bold_segments,
)


# === _fmt_money ===


@pytest.mark.parametrize(
    "value,expected",
    [
        (0.5, "0.50"),
        (6.5, "6.50"),
        (228.8, "228.80"),
        ("50.0", "50.00"),
        (Decimal("0.25"), "0.25"),
        (0, "0.00"),
        (None, "0.00"),          # fail-safe
        ("basura", "0.00"),      # fail-safe
    ],
)
def test_fmt_money_formatea_dos_decimales(value, expected):
    """Todo importe se renderiza con EXACTAMENTE 2 decimales; valores no parseables → "0.00"."""
    assert _fmt_money(value) == expected


def test_fmt_money_siempre_tiene_dos_decimales():
    """Estructuralmente: el string devuelto siempre tiene un punto y 2 dígitos de fracción."""
    for value in [0, 0.5, 1, 6.5, 228.8, "50.0", Decimal("0.25"), None, "x"]:
        out = _fmt_money(value)
        assert "**" not in out
        entero, _, frac = out.partition(".")
        assert frac != "" and len(frac) == 2


# Property test opcional con Hypothesis (si está disponible en el entorno).
try:
    from hypothesis import given, strategies as st

    _HAS_HYPOTHESIS = True
except ImportError:  # pragma: no cover
    _HAS_HYPOTHESIS = False


if _HAS_HYPOTHESIS:

    @given(
        st.decimals(
            min_value=Decimal("0"),
            max_value=Decimal("1000000"),
            places=4,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    def test_fmt_money_property_dos_decimales_y_valor_correcto(value):
        """Para cualquier Decimal >=0 con <=4 decimales: 2 decimales de salida y == half-up a 2."""
        from decimal import ROUND_HALF_UP

        out = _fmt_money(value)
        # Exactamente 2 decimales.
        _, _, frac = out.partition(".")
        assert len(frac) == 2
        # El valor coincide con el redondeo half-up a 2 decimales.
        expected = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        assert Decimal(out) == expected


# === _fmt_closure_date ===


def test_fmt_closure_date_mes_siguiente_en_tz_org():
    """Periodo (2026,5) + tz "America/Lima" → 2026-06-01 00:00 (America/Lima)."""
    header = SimpleNamespace(period_year=2026, period_month=5, timezone=None)
    org = SimpleNamespace(timezone="America/Lima")

    out = _fmt_closure_date(header, org)

    assert "2026-06-01 00:00" in out
    assert "America/Lima" in out


def test_fmt_closure_date_diciembre_rollover_de_anio():
    """Periodo (2026,12) → primer día del año siguiente: 2027-01-01 00:00."""
    header = SimpleNamespace(period_year=2026, period_month=12, timezone="America/Lima")
    org = SimpleNamespace(timezone=None)

    out = _fmt_closure_date(header, org)

    assert "2027-01-01 00:00" in out
    assert "America/Lima" in out


def test_fmt_closure_date_tz_del_closure_tiene_prioridad():
    """El `header` (closure) es prioritario sobre `org` para resolver la tz."""
    header = SimpleNamespace(period_year=2026, period_month=5, timezone="Europe/Madrid")
    org = SimpleNamespace(timezone="America/Lima")

    out = _fmt_closure_date(header, org)

    assert "2026-06-01 00:00" in out
    assert "Europe/Madrid" in out


def test_fmt_closure_date_tz_invalida_cae_a_utc():
    """Tz inválida → fallback "UTC" sin lanzar excepción."""
    header = SimpleNamespace(period_year=2026, period_month=5, timezone="No/Existe")
    org = SimpleNamespace(timezone=None)

    out = _fmt_closure_date(header, org)

    assert "2026-06-01 00:00" in out
    assert "(UTC)" in out


def test_fmt_closure_date_tz_ausente_cae_a_utc():
    """Sin tz en header ni org → fallback "UTC"."""
    header = SimpleNamespace(period_year=2026, period_month=5)
    org = SimpleNamespace()

    out = _fmt_closure_date(header, org)

    assert "2026-06-01 00:00" in out
    assert "(UTC)" in out


def test_fmt_closure_date_periodo_invalido_no_rompe():
    """Periodo no numérico → fail-safe: devuelve un string sin lanzar excepción."""
    header = SimpleNamespace(period_year="X", period_month="Y")
    org = SimpleNamespace(timezone="America/Lima")

    out = _fmt_closure_date(header, org)

    assert isinstance(out, str)
    assert out != ""


# === Markdown inline (_split_bold_segments) ===


def test_split_bold_segments_linea_numerada_con_negrita():
    """"1. **Resumen ejecutivo:**" → [("1. ", False), ("Resumen ejecutivo:", True)]."""
    segments = _split_bold_segments("1. **Resumen ejecutivo:**")

    assert segments == [("1. ", False), ("Resumen ejecutivo:", True)]
    # Ningún fragmento conserva los marcadores.
    assert all("**" not in frag for frag, _ in segments)


def test_split_bold_segments_sin_negrita_un_solo_segmento():
    """Texto sin negrita → un único segmento normal."""
    segments = _split_bold_segments("linea sin negrita")

    assert segments == [("linea sin negrita", False)]


def test_split_bold_segments_multiples_negritas_alternan():
    """Varias negritas en una línea alternan normal/negrita correctamente."""
    segments = _split_bold_segments("a **b** c **d**")

    assert segments == [("a ", False), ("b", True), (" c ", False), ("d", True)]
    assert all("**" not in frag for frag, _ in segments)


def test_split_bold_segments_ningun_asterisco_en_salida():
    """Ningún fragmento de salida debe contener "**" (evita asteriscos literales en el PDF)."""
    ejemplos = [
        "1. **Resumen ejecutivo:**",
        "3. **Observaciones:** texto normal despues",
        "**todo negrita**",
        "sin nada",
    ]
    for texto in ejemplos:
        segments = _split_bold_segments(texto)
        assert all("**" not in frag for frag, _ in segments)


def test_split_bold_segments_vacio():
    """Cadena vacía → lista vacía."""
    assert _split_bold_segments("") == []
