"""
Tests unitarios de composición del PDF y reconciliación de montos del Reporte de Cierre
Mensual (task 6.3).

Cubre, a nivel de módulo, `compose_pdf(...)`, `validate_reconciliation(...)` y la clase
`ReconciliationResult` de `app/services/closure_report_service.py`, con foco en:

1. Composición del PDF (Req 3.7, 3.8, 5.4):
   - `compose_pdf` produce bytes PDF válidos (empiezan con la firma `%PDF`).
   - Incluye la nota USD sin impuestos (`_USD_DISCLAIMER`, sección 8, Req 3.7) y el footer de
     copyright de Inversiones On Line S.A.C. (sección 9, Req 3.8).
   - Con `analysis=None` incluye la nota fail-safe (`_AI_FAILSAFE_NOTE`, Req 5.4); con
     `analysis=<texto>` incluye el texto del análisis.

2. Reconciliación de montos (Req 10.1, 10.2, 10.3):
   - Un cierre cuyos subtotales de tramos y suma de items coinciden con `header.amount`
     reconcilia dentro de `< 0.01` (`reconciled=True`, `note=None`).
   - Una discrepancia forzada (> 0.01) produce `reconciled=False`, una nota de discrepancia y
     un warning, SIN alterar `header.amount` (se preserva como fuente de verdad).

Los objetos de dominio (`BillingClosure`, `BillingClosureItem`, `Organization`) se construyen
en memoria: `compose_pdf` y `validate_reconciliation` sólo LEEN atributos, así que no hace
falta persistirlos en BD. Los PNG de los gráficos se generan con los renders reales
(`render_tiers_chart` / `render_history_chart`) para incrustar bytes PNG válidos.

Para verificar el contenido textual del PDF, en vez de depender de una librería de
extracción (no disponible en el env del backend), se descomprimen los content streams del
PDF (fpdf2 usa FlateDecode/zlib) y se leen los operadores de texto `Tj`. Como el texto se
sanitiza a Latin-1 y fpdf2 renderiza celda por celda, las aserciones buscan fragmentos ancla
robustos sobre el texto extraído y normalizado (sin whitespace).

_Requirements: 3.7, 3.8, 5.4, 10.1, 10.2, 10.3_
"""

import logging
import uuid
from decimal import Decimal

import pytest

# matplotlib emite miles de líneas DEBUG de "findfont" al renderizar los PNG, lo que satura la
# salida y ralentiza enormemente el test (la app configura logging a DEBUG). Se eleva el umbral
# de esos loggers a WARNING: no afecta el render (sólo el ruido de logs) y mantiene el test rápido.
logging.getLogger("matplotlib").setLevel(logging.WARNING)
logging.getLogger("matplotlib.font_manager").setLevel(logging.WARNING)
logging.getLogger("PIL").setLevel(logging.WARNING)

from app.models.billing import BillingClosure, BillingClosureItem
from app.models.organization import Organization
from app.schemas.billing_closures import HistoryPoint
from app.services.closure_report_service import (
    _AI_FAILSAFE_NOTE,
    _USD_DISCLAIMER,
    ReconciliationResult,
    compose_pdf,
    render_history_chart,
    render_tiers_chart,
    validate_reconciliation,
)

# Firma mágica de un archivo PDF (primeros bytes del artefacto).
PDF_SIGNATURE = b"%PDF"


# === Helpers de construcción de objetos de dominio en memoria ===


def _make_tier(tier_from, tier_to, ips_in_tier, rate, subtotal):
    """Construye un dict de tramo con las claves que consumen el render y la reconciliación."""
    return {
        "tier_index": 0,
        "from": tier_from,
        "to": tier_to,
        "rate": str(rate),
        "ips_in_tier": ips_in_tier,
        "subtotal": str(subtotal),
    }


def _make_org(name="Org de Prueba"):
    """Organización mínima en memoria (compose_pdf sólo lee `name`/`id`)."""
    return Organization(id=uuid.uuid4(), name=name)


def _make_closure(*, amount, tiers, is_retroactive=False):
    """
    Cabecera de cierre en memoria con totales coherentes y `tiers_applied` dados.

    `amount` es la fuente de verdad de la factura; `tiers` es la lista de dicts de tramos.
    """
    return BillingClosure(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        period_year=2026,
        period_month=3,
        mode="monthly",
        timezone="America/Lima",
        total_billable=sum(int(t["ips_in_tier"]) for t in tiers),
        total_recycled=2,
        total_archived=1,
        amount=Decimal(str(amount)),
        tiers_applied=tiers,
        is_retroactive=is_retroactive,
    )


def _make_item(amount, ip="10.0.0.1", tier_index=0):
    """Item (aporte por IP) en memoria; sólo se lee `amount` en la reconciliación."""
    return BillingClosureItem(
        id=uuid.uuid4(),
        closure_id=uuid.uuid4(),
        ip_private=ip,
        billing_status="billable",
        tier_index=tier_index,
        amount=Decimal(str(amount)),
    )


def _make_history():
    """Serie histórica mínima de varios ciclos para el gráfico de evolución."""
    return [
        HistoryPoint(
            cycle=1,
            period_year=2026,
            period_month=1,
            total_billable=100,
            total_recycled=0,
            total_archived=0,
            amount=Decimal("150.00"),
        ),
        HistoryPoint(
            cycle=2,
            period_year=2026,
            period_month=2,
            total_billable=140,
            total_recycled=1,
            total_archived=0,
            amount=Decimal("210.00"),
        ),
        HistoryPoint(
            cycle=3,
            period_year=2026,
            period_month=3,
            total_billable=190,
            total_recycled=2,
            total_archived=1,
            amount=Decimal("360.00"),
        ),
    ]


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """
    Extrae el texto renderizado del PDF descomprimiendo sus content streams.

    fpdf2 comprime los content streams con FlateDecode (zlib). Se localiza cada bloque
    `stream ... endstream`, se descomprime (si no descomprime, se usa crudo) y se concatenan
    los contenidos de los operadores de texto `(...) Tj`. El resultado se normaliza quitando
    todo whitespace para que las aserciones sean robustas frente al render celda por celda.
    """
    import re
    import zlib

    collected: list[str] = []
    # Recorrer los bloques `stream ... endstream` sin regex codiciosa sobre binario grande:
    # se ubican los marcadores por índice y se descomprime cada segmento por separado. Sólo se
    # consideran los streams que, al descomprimir, contienen operadores de texto `Tj` (los de
    # contenido de página); se ignoran los de imagen/ICC (binario, sin `Tj`).
    marker_open = b"stream"
    marker_close = b"endstream"
    pos = 0
    while True:
        start = pdf_bytes.find(marker_open, pos)
        if start == -1:
            break
        # Saltar el CR/LF que sigue a la palabra clave `stream`.
        data_start = start + len(marker_open)
        if pdf_bytes[data_start : data_start + 2] == b"\r\n":
            data_start += 2
        elif pdf_bytes[data_start : data_start + 1] in (b"\n", b"\r"):
            data_start += 1
        end = pdf_bytes.find(marker_close, data_start)
        if end == -1:
            break
        raw = pdf_bytes[data_start:end].rstrip(b"\r\n")
        pos = end + len(marker_close)

        try:
            decoded = zlib.decompress(raw)
        except zlib.error:
            continue  # no es un stream FlateDecode de contenido (imagen/ICC/etc.)

        if b"Tj" not in decoded:
            continue  # stream sin texto (imagen); no aporta contenido textual

        blob = decoded.decode("latin-1", errors="replace")
        # Literal de texto `(...) Tj` de fpdf2: el contenido puede incluir paréntesis ESCAPADOS
        # (`\(`, `\)`) y otros escapes (`\\`). El patrón `(?:[^()\\]|\\.)*` acepta cualquier
        # carácter no especial o una secuencia de escape de dos chars, sin backtracking
        # catastrófico (alternancia mutuamente excluyente sobre el mismo char).
        for literal in re.findall(r"\(((?:[^()\\]|\\.)*)\)\s*Tj", blob):
            collected.append(literal)

    text = "".join(collected)
    # Des-escapar las secuencias PDF básicas que fpdf2 usa dentro de literales de cadena.
    text = text.replace(r"\(", "(").replace(r"\)", ")").replace(r"\\", "\\")
    return "".join(text.split())


def _normalize(text: str) -> str:
    """Quita todo whitespace de un texto (para comparar contra el texto extraído del PDF)."""
    return "".join(text.split())


# === Fixtures ===


@pytest.fixture
def reconciling_closure():
    """
    Cierre con varios tramos cuyos subtotales y items suman exactamente `header.amount`.

    Tramos: 100 IPs * 1.50 = 150.00 ; 150 IPs * 1.20 = 180.00 → total 330.00.
    Items: aportes por IP que suman 330.00. header.amount = 330.00 → reconcilia.
    """
    tiers = [
        _make_tier(1, 100, 100, rate="1.50", subtotal="150.00"),
        _make_tier(101, 250, 150, rate="1.20", subtotal="180.00"),
    ]
    closure = _make_closure(amount="330.00", tiers=tiers)
    # 250 items: 100 aportan 1.50 y 150 aportan 1.20 → 150.00 + 180.00 = 330.00.
    items = [_make_item("1.50", ip=f"10.0.0.{i}", tier_index=0) for i in range(100)]
    items += [_make_item("1.20", ip=f"10.0.1.{i}", tier_index=1) for i in range(150)]
    return closure, items


# === Reconciliación (Req 10.1, 10.2, 10.3) ===


def test_validate_reconciliation_reconciles_within_tolerance(reconciling_closure):
    """Subtotales de tramos + items que igualan header.amount → reconciled=True, note=None."""
    closure, items = reconciling_closure

    result = validate_reconciliation(closure, items)

    assert isinstance(result, ReconciliationResult)
    assert result.reconciled is True
    assert result.note is None
    assert result.header_amount == Decimal("330.00")
    # Ambas diferencias están dentro de la tolerancia (< 0.01).
    assert result.tiers_diff < Decimal("0.01")
    assert result.items_diff < Decimal("0.01")


def test_validate_reconciliation_forced_discrepancy_warns_and_preserves_header():
    """
    Discrepancia forzada (> 0.01) → reconciled=False, note presente con la advertencia, y
    `header.amount` NO se altera (Req 10.2, 10.3).

    La advertencia (Req 10.2) se materializa tanto en el log warning del servicio como en la
    `note` de discrepancia (destinada al PDF). Se verifica sobre la `note` — el contrato
    observable — para no depender del backend de logging (structlog) en el aserto.
    """
    tiers = [_make_tier(1, 100, 100, rate="1.50", subtotal="150.00")]
    # header.amount declara 200.00 pero los tramos suman 150.00 y los items 150.00 → dif 50.00.
    closure = _make_closure(amount="200.00", tiers=tiers)
    items = [_make_item("1.50", ip=f"10.0.0.{i}") for i in range(100)]

    amount_before = closure.amount

    result = validate_reconciliation(closure, items)

    assert result.reconciled is False
    # Req 10.2: nota de discrepancia (aviso) presente para anotar en el PDF.
    assert result.note is not None
    assert "reconciliacion" in result.note.lower()
    assert "fuente de verdad" in result.note.lower()
    # Diferencias por encima de la tolerancia.
    assert result.tiers_diff >= Decimal("0.01")
    assert result.items_diff >= Decimal("0.01")
    # Req 10.3: header.amount se preserva como fuente de verdad (objeto sin mutar).
    assert closure.amount == amount_before == Decimal("200.00")
    assert result.header_amount == Decimal("200.00")


# === Composición del PDF (Req 3.7, 3.8, 5.4) ===


def test_compose_pdf_with_analysis_includes_disclaimer_footer_and_analysis(reconciling_closure):
    """
    PDF válido con `analysis=<texto>`: firma %PDF, nota USD sin impuestos, footer de copyright
    y el texto del análisis IA incluido.
    """
    closure, items = reconciling_closure
    org = _make_org()
    history = _make_history()
    tiers_png = render_tiers_chart(closure.tiers_applied)
    history_png = render_history_chart(history)
    analysis = (
        "## Resumen ejecutivo\n"
        "El consumo del periodo se mantiene estable con crecimiento moderado.\n"
        "## Observaciones\n"
        "MARCADOR_ANALISIS_UNICO presente en el analisis.\n"
    )

    pdf_bytes = compose_pdf(closure, items, history, tiers_png, history_png, analysis, org)

    assert isinstance(pdf_bytes, (bytes, bytearray))
    assert bytes(pdf_bytes).startswith(PDF_SIGNATURE)

    text = _extract_pdf_text(pdf_bytes)
    # Nota USD sin impuestos (sección 8, Req 3.7). El disclaimer se renderiza en un único `Tj`,
    # así que aparece completo en el texto normalizado.
    assert _normalize(_USD_DISCLAIMER) in text
    # Footer de copyright (sección 9, Req 3.8).
    assert "InversionesOnLineS.A.C." in text
    assert "Todoslosderechosreservados" in text
    # El texto del análisis IA está incrustado.
    assert "MARCADOR_ANALISIS_UNICO" in text
    # La nota fail-safe NO debe aparecer cuando hay análisis (ancla robusta al inicio de la nota).
    assert "AnalisisIAnodisponibleenestemomento" not in text


def test_compose_pdf_without_analysis_includes_failsafe_note(reconciling_closure):
    """
    PDF válido con `analysis=None`: firma %PDF, nota fail-safe (Req 5.4), nota USD sin
    impuestos y footer de copyright.
    """
    closure, items = reconciling_closure
    org = _make_org()
    history = _make_history()
    tiers_png = render_tiers_chart(closure.tiers_applied)
    history_png = render_history_chart(history)

    pdf_bytes = compose_pdf(closure, items, history, tiers_png, history_png, None, org)

    assert bytes(pdf_bytes).startswith(PDF_SIGNATURE)

    text = _extract_pdf_text(pdf_bytes)
    # Nota fail-safe presente (Req 5.4). El texto se ajusta en varias líneas al renderizar, por
    # lo que se ancla en el inicio de la nota (contiguo dentro de un mismo `Tj`) y en la palabra
    # clave "fail-safe" que aparece en la segunda línea.
    assert "AnalisisIAnodisponibleenestemomento" in text
    assert "fail-safe" in text
    # Nota USD sin impuestos y footer siguen presentes.
    assert _normalize(_USD_DISCLAIMER) in text
    assert "InversionesOnLineS.A.C." in text


def test_compose_pdf_with_discrepancy_annotates_without_altering_header():
    """
    Un cierre no reconciliado compone el PDF, anota la discrepancia y preserva `header.amount`.

    Verifica la integración compose_pdf ↔ validate_reconciliation (Req 10.2/10.3): el PDF se
    genera igual (fail-safe de reconciliación) y el monto de cabecera no se altera.
    """
    tiers = [_make_tier(1, 100, 100, rate="1.50", subtotal="150.00")]
    closure = _make_closure(amount="200.00", tiers=tiers)  # dif 50.00 vs tramos/items
    items = [_make_item("1.50", ip=f"10.0.0.{i}") for i in range(100)]
    org = _make_org()
    history = _make_history()
    tiers_png = render_tiers_chart(closure.tiers_applied)
    history_png = render_history_chart(history)

    amount_before = closure.amount
    pdf_bytes = compose_pdf(closure, items, history, tiers_png, history_png, None, org)

    assert bytes(pdf_bytes).startswith(PDF_SIGNATURE)
    # Req 10.3: header.amount se conserva tras componer.
    assert closure.amount == amount_before == Decimal("200.00")

    text = _extract_pdf_text(pdf_bytes)
    # La anotación de discrepancia aparece en el PDF (fragmento ancla del inicio de la nota,
    # contiguo dentro de un mismo `Tj`).
    assert "Avisodereconciliacion:eltotaldeldesglose" in text
