"""
Tests unitarios de la política de reciclaje CONGELADA en el Reporte de Cierre Mensual (task 7.5).

Cubre el comportamiento fail-closed y la descripción en prosa de la Recycle_Policy congelada del
cierre, tanto en el PDF (`compose_pdf` / `_recycle_policy_prose_lines`) como en el prompt del
Análisis IA (`build_ai_prompt`), en `app/services/closure_report_service.py`:

1. PDF — prosa de la política (Req 11.1, 11.2, 11.3):
   - `_recycle_policy_prose_lines(parse_frozen_policy(freeze))` devuelve líneas que contienen la
     Recycle_Rule `"+1/-2/-3"` (signo explícito) y el umbral de uso efímero `"24h"`, describiendo
     el significado de cutoff/cut1/cut2 y ephemeral_hours.
   - `compose_pdf` con un freeze válido produce bytes PDF válidos (empiezan con `%PDF`).

2. PDF — fail-closed (Req 11.4):
   - `compose_pdf` con `recycle_policy_applied={}` (o `None`) NO genera PDF y lanza
     `FrozenPolicyCorruptError`.

3. Prompt IA (Req 12.1):
   - `build_ai_prompt` con un freeze válido incluye la sección de política congelada con la regla
     y las horas.

4. Prompt IA — no muta totales al regenerar (Req 12.2):
   - `build_ai_prompt` sólo LEE el header: `total_billable`/`amount`/`tiers_applied` quedan
     idénticos antes y después de construir el prompt.

5. Prompt IA fail-closed + PDF fail-safe (Req 12.3):
   - `build_ai_prompt` con freeze corrupto lanza `FrozenPolicyCorruptError`.
   - `resolve_ai_analysis` captura ese fallo (fail-safe) y devuelve `None` SIN invocar el LLM
     (el chequeo del freeze precede a la invocación).
   - `compose_pdf` con un freeze válido y `analysis=None` sigue generando el PDF (fail-safe
     "IA no disponible"): el fallo del AI_Analysis no bloquea el reporte.

Los objetos de dominio se construyen en memoria (SimpleNamespace/`BillingClosure`): las
funciones bajo prueba sólo LEEN atributos del header. El LLM nunca se ejecuta: el chequeo del
freeze en `build_ai_prompt` precede a `_invoke_llm`, y se verifica que no se invoque.

_Requirements: 11.1, 11.2, 11.3, 11.4, 12.1, 12.2, 12.3_
"""

import logging
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

# Silenciar el ruido DEBUG de matplotlib/PIL al render (no afecta el resultado, solo velocidad).
logging.getLogger("matplotlib").setLevel(logging.WARNING)
logging.getLogger("matplotlib.font_manager").setLevel(logging.WARNING)
logging.getLogger("PIL").setLevel(logging.WARNING)

from app.services.closure_report_service import (
    ClosureReportService,
    _recycle_policy_prose_lines,
    compose_pdf,
)
from app.services.recycle_policy_service import (
    FrozenPolicyCorruptError,
    parse_frozen_policy,
)

# Firma mágica de un archivo PDF.
PDF_SIGNATURE = b"%PDF"

# Freeze de política legacy válido (+1/-2/-3, 24h) tal como lo persiste `freeze_dict()`.
_VALID_FREEZE = {"cutoff": 1, "cut1": -2, "cut2": -3, "ephemeral_hours": 24}


# === Helpers de construcción en memoria ===


def _make_header(*, recycle_policy_applied=_VALID_FREEZE):
    """
    Cabecera de cierre en memoria con los atributos que leen `compose_pdf`/`build_ai_prompt`.

    `recycle_policy_applied` es el freeze de política; se puede pasar `{}`/`None` para simular un
    freeze corrupto (fail-closed).
    """
    return SimpleNamespace(
        id=uuid.uuid4(),
        period_year=2026,
        period_month=3,
        mode="monthly",
        is_retroactive=False,
        total_billable=190,
        total_recycled=2,
        total_archived=1,
        amount=Decimal("360.00"),
        tiers_applied=[
            {"from": 1, "to": 100, "rate": "1.50", "ips_in_tier": 100, "subtotal": "150.00"},
            {"from": 101, "to": 250, "rate": "1.40", "ips_in_tier": 90, "subtotal": "126.00"},
        ],
        recycle_policy_applied=recycle_policy_applied,
    )


def _make_org(name="Org Politica"):
    return SimpleNamespace(id=uuid.uuid4(), name=name)


@pytest.fixture
def service() -> ClosureReportService:
    return ClosureReportService()


# === 1. PDF — prosa de la política (Req 11.1, 11.2, 11.3) ===


def test_prose_lines_contain_rule_and_hours():
    """
    `_recycle_policy_prose_lines(parse_frozen_policy(freeze))` describe la Recycle_Rule
    `"+1/-2/-3"` y el umbral efímero `"24h"`, más el significado de cada offset (Req 11.1, 11.2).
    """
    policy = parse_frozen_policy(_VALID_FREEZE)
    lines = _recycle_policy_prose_lines(policy)

    joined = "\n".join(lines)
    # Regla de reciclaje con signo explícito (Req 11.1 / 11.2).
    assert "+1/-2/-3" in joined
    # Umbral de uso efímero en horas (Req 11.2).
    assert "24h" in joined
    # Se describe el significado de cada offset y del umbral (Req 11.2).
    assert "cutoff" in joined
    assert "cut1" in joined
    assert "cut2" in joined
    assert "ephemeral_hours" in joined


def test_prose_lines_read_frozen_policy_not_current():
    """
    La prosa refleja EXACTAMENTE el freeze recibido, no una política vigente distinta (Req 11.3):
    un freeze `+1/0/-1` con 48h produce esa regla y esas horas.
    """
    policy = parse_frozen_policy({"cutoff": 1, "cut1": 0, "cut2": -1, "ephemeral_hours": 48})
    joined = "\n".join(_recycle_policy_prose_lines(policy))

    # `format_recycle_rule` usa signo explícito en TODOS los offsets, incluido el cero (+0).
    assert "+1/+0/-1" in joined
    assert "48h" in joined
    # No aparece la regla legacy (no se está leyendo la política vigente/otra).
    assert "+1/-2/-3" not in joined


def test_compose_pdf_valid_freeze_generates_pdf():
    """`compose_pdf` con un freeze válido genera bytes que empiezan con `%PDF` (Req 11.1)."""
    header = _make_header()
    org = _make_org()

    pdf_bytes = compose_pdf(header, [], [], b"", b"", None, org)

    assert isinstance(pdf_bytes, (bytes, bytearray))
    assert bytes(pdf_bytes).startswith(PDF_SIGNATURE)


# === 2. PDF — fail-closed (Req 11.4) ===


def test_compose_pdf_empty_freeze_raises_and_no_pdf():
    """`compose_pdf` con `recycle_policy_applied={}` aborta con `FrozenPolicyCorruptError` (Req 11.4)."""
    header = _make_header(recycle_policy_applied={})
    org = _make_org()

    with pytest.raises(FrozenPolicyCorruptError):
        compose_pdf(header, [], [], b"", b"", None, org)


def test_compose_pdf_none_freeze_raises_and_no_pdf():
    """`compose_pdf` con `recycle_policy_applied=None` aborta con `FrozenPolicyCorruptError` (Req 11.4)."""
    header = _make_header(recycle_policy_applied=None)
    org = _make_org()

    with pytest.raises(FrozenPolicyCorruptError):
        compose_pdf(header, [], [], b"", b"", None, org)


def test_compose_pdf_incomplete_freeze_raises():
    """Un freeze al que le falta una clave (ephemeral_hours) también aborta fail-closed (Req 11.4)."""
    header = _make_header(recycle_policy_applied={"cutoff": 1, "cut1": -2, "cut2": -3})
    org = _make_org()

    with pytest.raises(FrozenPolicyCorruptError):
        compose_pdf(header, [], [], b"", b"", None, org)


# === 3. Prompt IA (Req 12.1) ===


def test_build_ai_prompt_includes_policy_section(service):
    """
    `build_ai_prompt` con un freeze válido incluye la sección de política congelada con la regla
    `"+1/-2/-3"` y el umbral de horas (Req 12.1).
    """
    header = _make_header()
    prompt = service.build_ai_prompt(header, [], [])

    assert "Politica de reciclaje aplicada (congelada en el cierre)" in prompt
    assert "+1/-2/-3" in prompt
    # El umbral efímero se menciona con las horas del freeze.
    assert "24h" in prompt
    assert "cutoff" in prompt


def test_build_ai_prompt_reads_frozen_not_current(service):
    """El prompt refleja el freeze recibido (Req 12.1/11.3), no una política vigente distinta."""
    header = _make_header(
        recycle_policy_applied={"cutoff": 1, "cut1": 0, "cut2": -1, "ephemeral_hours": 12}
    )
    prompt = service.build_ai_prompt(header, [], [])

    # `format_recycle_rule` usa signo explícito en el offset cero (+0).
    assert "+1/+0/-1" in prompt
    assert "12h" in prompt
    assert "+1/-2/-3" not in prompt


# === 4. Prompt IA — no muta totales al regenerar (Req 12.2) ===


def test_build_ai_prompt_does_not_mutate_header_totals(service):
    """
    `build_ai_prompt` sólo LEE el header: `total_billable`/`amount`/`tiers_applied` quedan
    idénticos antes y después de construir el prompt (Req 12.2 — regenerar no cambia totales).
    """
    header = _make_header()
    billable_before = header.total_billable
    amount_before = header.amount
    tiers_before = list(header.tiers_applied)

    service.build_ai_prompt(header, [], [])

    assert header.total_billable == billable_before == 190
    assert header.amount == amount_before == Decimal("360.00")
    assert header.tiers_applied == tiers_before


# === 5. Prompt IA fail-closed + PDF fail-safe (Req 12.3) ===


def test_build_ai_prompt_corrupt_freeze_raises(service):
    """`build_ai_prompt` con freeze corrupto lanza `FrozenPolicyCorruptError` (Req 12.3)."""
    header = _make_header(recycle_policy_applied={})

    with pytest.raises(FrozenPolicyCorruptError):
        service.build_ai_prompt(header, [], [])


@pytest.mark.asyncio
async def test_resolve_ai_analysis_returns_none_on_corrupt_freeze_without_llm(
    service, monkeypatch
):
    """
    `resolve_ai_analysis` captura el `FrozenPolicyCorruptError` de `build_ai_prompt` (fail-safe) y
    devuelve `None` SIN invocar el LLM: el chequeo del freeze precede a `_invoke_llm` (Req 12.3).

    Se mockea `get_report_row` para forzar cache-miss (no hay caché) y `_invoke_llm` como espía
    que NO debe llamarse. `db` se pasa como None porque el flujo nunca llega a tocar la BD.
    """
    org = _make_org()
    header = _make_header(recycle_policy_applied={})
    closure = SimpleNamespace(id=uuid.uuid4())

    # Cache-miss: no hay fila de reporte previa.
    monkeypatch.setattr(service, "get_report_row", lambda db, c: None)
    # Espía del LLM: si se invoca, la aserción de 0 llamadas falla.
    llm_mock = AsyncMock(return_value=("NO DEBERIA USARSE", "modelo-x"))
    monkeypatch.setattr(ClosureReportService, "_invoke_llm", llm_mock)

    result = await service.resolve_ai_analysis(
        None, closure, org, header=header, items=[], history=[], regenerate=False
    )

    assert result is None  # fail-safe: IA no disponible por freeze corrupto
    llm_mock.assert_not_called()  # el chequeo del freeze precede a la invocación del LLM


def test_compose_pdf_valid_freeze_with_analysis_none_still_generates():
    """
    PDF fail-safe (Req 12.3): con un freeze VÁLIDO y `analysis=None` (IA no disponible), el PDF se
    genera igual — el fallo del AI_Analysis no bloquea el reporte.
    """
    header = _make_header()
    org = _make_org()

    pdf_bytes = compose_pdf(header, [], [], b"", b"", None, org)

    assert bytes(pdf_bytes).startswith(PDF_SIGNATURE)
