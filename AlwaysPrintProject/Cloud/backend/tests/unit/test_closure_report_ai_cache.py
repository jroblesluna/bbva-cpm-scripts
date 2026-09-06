"""
Tests unitarios de `ClosureReportService.resolve_ai_analysis` (task 5.2).

Verifica el comportamiento de caché y fail-safe del análisis IA del Reporte de Cierre Mensual:

1. Cache-hit: con una fila `BillingClosureReport` que ya tiene `ai_analysis` persistido y
   `regenerate=False`, el LLM NO se invoca (0 llamadas) y se devuelve el texto cacheado.
2. Regeneración: con `regenerate=True`, el LLM SÍ se invoca y el texto cacheado se
   sobre-escribe con la nueva respuesta (texto + modelo + `ai_generated_at`).
3. Fail-safe: si `_invoke_llm` lanza una excepción (tras agotar los reintentos),
   `resolve_ai_analysis` devuelve `None` sin propagar la excepción y sin persistir análisis.

Convenciones: se reutiliza la fixture `db` de `tests/conftest.py` (sesión SQLite in-memory
con el esquema completo, aislada por test). El LLM se mockea parcheando el método
`ClosureReportService._invoke_llm` con un `AsyncMock` para no ejecutar el proveedor real.
`asyncio_mode = "auto"` (ver pyproject.toml) hace que las funciones `async def test_*` se
ejecuten sobre el event loop; se añade el marcador explícito por claridad.

_Requirements: 5.4, 5.5, 6.2_
"""

import uuid
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.models.organization import Organization
from app.models.billing import BillingClosure, BillingClosureReport
from app.services.closure_report_service import (
    ClosureReportError,
    ClosureReportService,
)


def _make_org(db, name: str) -> Organization:
    """Crea y persiste una organización mínima (sin OpenAI → rama Bedrock por defecto)."""
    org = Organization(
        id=uuid.uuid4(),
        name=name,
        timezone="UTC",
        billing_mode="monthly",
    )
    db.add(org)
    db.flush()
    return org


def _make_closure(db, org: Organization, year: int = 2025, month: int = 1) -> BillingClosure:
    """Construye un cierre mensual mínimo para la organización dada."""
    closure = BillingClosure(
        id=uuid.uuid4(),
        organization_id=org.id,
        period_year=year,
        period_month=month,
        cutoff_at=datetime(year if month < 12 else year + 1, (month % 12) + 1, 1),
        mode="monthly",
        timezone="UTC",
        total_billable=10,
        total_recycled=2,
        total_archived=1,
        amount=Decimal("5.00"),
        tiers_applied=[],
    )
    db.add(closure)
    db.flush()
    return closure


@pytest.fixture
def service() -> ClosureReportService:
    return ClosureReportService()


@pytest.mark.asyncio
async def test_cache_hit_does_not_invoke_llm(db, service, monkeypatch):
    """
    Con `ai_analysis` persistido y `regenerate=False`, se devuelve el texto cacheado y el LLM
    NO se invoca (0 llamadas) (Req 5.5, 6.2).
    """
    org = _make_org(db, "Org Cache")
    closure = _make_closure(db, org)

    # Fila de reporte con análisis IA ya persistido (cache-hit esperado).
    cached_text = "Analisis IA previamente cacheado."
    db.add(
        BillingClosureReport(
            closure_id=closure.id,
            organization_id=org.id,
            ai_analysis=cached_text,
            ai_model="cached-model",
            ai_generated_at=datetime(2025, 1, 1),
        )
    )
    db.flush()

    # Espía del LLM: si se invoca, el test fallará en la aserción de 0 llamadas.
    llm_mock = AsyncMock(return_value=("NO DEBERIA USARSE", "modelo-x"))
    monkeypatch.setattr(ClosureReportService, "_invoke_llm", llm_mock)

    result = await service.resolve_ai_analysis(
        db, closure, org, header=closure, items=[], history=[], regenerate=False
    )

    assert result == cached_text
    llm_mock.assert_not_called()  # 0 invocaciones del LLM en cache-hit


@pytest.mark.asyncio
async def test_regenerate_invokes_llm_and_overwrites(db, service, monkeypatch):
    """
    Con `regenerate=True`, el LLM SÍ se invoca y el texto cacheado se sobre-escribe
    (texto + modelo + `ai_generated_at`) (Req 5.4, 6.2).
    """
    org = _make_org(db, "Org Regenerate")
    closure = _make_closure(db, org)

    # Fila con análisis viejo que debe ser sobre-escrito.
    db.add(
        BillingClosureReport(
            closure_id=closure.id,
            organization_id=org.id,
            ai_analysis="Analisis IA VIEJO",
            ai_model="modelo-viejo",
            ai_generated_at=datetime(2024, 12, 31),
        )
    )
    db.flush()

    new_text = "Analisis IA REGENERADO por el LLM."
    new_model = "bedrock-nuevo"
    llm_mock = AsyncMock(return_value=(new_text, new_model))
    monkeypatch.setattr(ClosureReportService, "_invoke_llm", llm_mock)

    result = await service.resolve_ai_analysis(
        db, closure, org, header=closure, items=[], history=[], regenerate=True
    )

    # Se invocó exactamente una vez y se devolvió el texto nuevo.
    assert result == new_text
    llm_mock.assert_awaited_once()

    # La fila del reporte quedó sobre-escrita con el nuevo análisis/modelo/fecha.
    row = service.get_report_row(db, closure)
    assert row is not None
    assert row.ai_analysis == new_text
    assert row.ai_model == new_model
    assert row.ai_generated_at is not None
    assert row.ai_generated_at.year >= 2025  # fecha de generación actualizada (utcnow)


@pytest.mark.asyncio
async def test_regenerate_creates_row_when_absent(db, service, monkeypatch):
    """
    Con `regenerate=True` y sin fila previa, se crea la fila y se persiste el análisis
    (upsert) (Req 5.4, 6.2).
    """
    org = _make_org(db, "Org Sin Fila")
    closure = _make_closure(db, org)

    # No existe fila de reporte todavía.
    assert service.get_report_row(db, closure) is None

    new_text = "Primer analisis IA generado."
    llm_mock = AsyncMock(return_value=(new_text, "bedrock-default"))
    monkeypatch.setattr(ClosureReportService, "_invoke_llm", llm_mock)

    result = await service.resolve_ai_analysis(
        db, closure, org, header=closure, items=[], history=[], regenerate=True
    )

    assert result == new_text
    llm_mock.assert_awaited_once()

    row = service.get_report_row(db, closure)
    assert row is not None
    assert row.ai_analysis == new_text
    assert row.ai_model == "bedrock-default"


@pytest.mark.asyncio
async def test_llm_failure_returns_none_without_propagating(db, service, monkeypatch):
    """
    FAIL-SAFE: si `_invoke_llm` lanza tras agotar reintentos, `resolve_ai_analysis` devuelve
    `None` sin propagar la excepción y sin persistir análisis (Req 5.4, 6.2).
    """
    org = _make_org(db, "Org FailSafe")
    closure = _make_closure(db, org)

    # No hay caché → se intentará invocar el LLM, que falla.
    llm_mock = AsyncMock(
        side_effect=ClosureReportError("Error del LLM tras 3 intentos: boom")
    )
    monkeypatch.setattr(ClosureReportService, "_invoke_llm", llm_mock)

    # No debe propagar la excepción.
    result = await service.resolve_ai_analysis(
        db, closure, org, header=closure, items=[], history=[], regenerate=False
    )

    assert result is None
    llm_mock.assert_awaited_once()

    # Fail-safe: no se persiste ninguna fila de análisis (o queda sin ai_analysis).
    row = service.get_report_row(db, closure)
    assert row is None or row.ai_analysis is None


@pytest.mark.asyncio
async def test_generic_llm_exception_is_failsafe(db, service, monkeypatch):
    """
    El fail-safe cubre CUALQUIER excepción del LLM (no solo `ClosureReportError`): un error
    genérico también resulta en `None` sin propagar (Req 5.4).
    """
    org = _make_org(db, "Org FailSafe Generico")
    closure = _make_closure(db, org)

    llm_mock = AsyncMock(side_effect=RuntimeError("fallo inesperado del proveedor"))
    monkeypatch.setattr(ClosureReportService, "_invoke_llm", llm_mock)

    result = await service.resolve_ai_analysis(
        db, closure, org, header=closure, items=[], history=[], regenerate=True
    )

    assert result is None
    llm_mock.assert_awaited_once()
