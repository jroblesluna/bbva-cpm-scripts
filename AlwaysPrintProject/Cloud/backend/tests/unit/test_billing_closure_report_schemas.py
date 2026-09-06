"""
Tests unitarios de serialización de los schemas del Reporte de Cierre Mensual (task 2.2).

Cubren el contrato de salida de `app/schemas/billing_closures.py` para los schemas del reporte
(añadidos en task 2.1):

Defaults (Req 1.3, 11.5):
1. `ClosureReportUrlResponse.expires_in_seconds` por defecto = 3600 (expiración de la
   presigned URL, Req 1.3).
2. `ClosureReportDataResponse.currency` por defecto = "USD" y `taxes_included` = False
   (declaración obligatoria de precios en USD sin impuestos, Req 11.5).

`from_attributes` (Req 6.1):
3. `ClosureReportMeta` se construye desde un objeto tipo ORM (atributos, no dict) vía
   `model_validate`, mapeando `closure_id`, `ai_model` y las fechas de generación.

Convención: schemas puros, sin base de datos ni FastAPI (se validan defaults y
`from_attributes` directamente con Pydantic).

_Requirements: 1.3, 11.5_
"""

import uuid
from datetime import datetime

from app.schemas.billing_closures import (
    ClosureReportUrlResponse,
    ClosureReportMeta,
    ClosureReportDataResponse,
    ClosureHeaderResponse,
    HistoryPoint,
)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_header() -> ClosureHeaderResponse:
    """Cabecera mínima válida para poblar `ClosureReportDataResponse.header`."""
    return ClosureHeaderResponse(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        period_year=2026,
        period_month=1,
        cutoff_at=datetime(2026, 2, 1, 0, 0, 0),
        mode="monthly",
        timezone="America/Lima",
        total_billable=3,
        total_recycled=1,
        total_archived=0,
        amount="12.50",
        tiers_applied=[],
        is_retroactive=False,
        created_at=datetime(2026, 2, 1, 1, 0, 0),
    )


class _ClosureReportRow:
    """Doble de la fila ORM `BillingClosureReport` para verificar `from_attributes`."""

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


# ── Defaults ──────────────────────────────────────────────────────────────


def test_url_response_default_expires_in_seconds():
    """`expires_in_seconds` por defecto = 3600 cuando no se especifica (Req 1.3)."""
    resp = ClosureReportUrlResponse(
        report_url="https://s3.us-west-2.amazonaws.com/bucket/report.pdf?sig=x",
        cached=True,
        ai_analysis_available=True,
    )

    assert resp.expires_in_seconds == 3600


def test_url_response_expires_in_seconds_override():
    """`expires_in_seconds` es explícito cuando se pasa (no se pisa el default)."""
    resp = ClosureReportUrlResponse(
        report_url="https://example.test/report.pdf",
        expires_in_seconds=900,
        cached=False,
        ai_analysis_available=False,
    )

    assert resp.expires_in_seconds == 900


def test_data_response_default_currency_and_taxes():
    """`currency` por defecto = "USD" y `taxes_included` = False (Req 11.5)."""
    resp = ClosureReportDataResponse(
        header=_make_header(),
        tiers_applied=[],
        history=[],
    )

    assert resp.currency == "USD"
    assert resp.taxes_included is False


def test_data_response_defaults_ai_analysis_none():
    """`ai_analysis` por defecto = None (fail-safe: el reporte puede no tener texto IA)."""
    resp = ClosureReportDataResponse(
        header=_make_header(),
        tiers_applied=[],
        history=[
            HistoryPoint(
                cycle=1,
                period_year=2026,
                period_month=1,
                total_billable=3,
                total_recycled=1,
                total_archived=0,
                amount="12.50",
            )
        ],
    )

    assert resp.ai_analysis is None


# ── from_attributes de ClosureReportMeta ────────────────────────────────────


def test_meta_from_attributes_maps_orm_object():
    """
    `ClosureReportMeta` se puebla desde un objeto con atributos (no dict) vía
    `model_validate`, gracias a `from_attributes=True` (Req 6.1).
    """
    closure_id = uuid.uuid4()
    ai_generated_at = datetime(2026, 2, 1, 3, 0, 0)
    pdf_generated_at = datetime(2026, 2, 1, 3, 1, 0)

    row = _ClosureReportRow(
        closure_id=closure_id,
        ai_model="anthropic.claude-3-sonnet",
        ai_generated_at=ai_generated_at,
        pdf_generated_at=pdf_generated_at,
        ai_analysis_available=True,
    )

    meta = ClosureReportMeta.model_validate(row)

    assert meta.closure_id == closure_id
    assert meta.ai_model == "anthropic.claude-3-sonnet"
    assert meta.ai_generated_at == ai_generated_at
    assert meta.pdf_generated_at == pdf_generated_at
    assert meta.ai_analysis_available is True


def test_meta_from_attributes_allows_null_optionals():
    """
    Los campos opcionales (`ai_model`, `ai_generated_at`, `pdf_generated_at`) aceptan None
    cuando el reporte aún no se generó o el análisis IA no está disponible (Req 6.1).
    """
    closure_id = uuid.uuid4()

    row = _ClosureReportRow(
        closure_id=closure_id,
        ai_model=None,
        ai_generated_at=None,
        pdf_generated_at=None,
        ai_analysis_available=False,
    )

    meta = ClosureReportMeta.model_validate(row)

    assert meta.closure_id == closure_id
    assert meta.ai_model is None
    assert meta.ai_generated_at is None
    assert meta.pdf_generated_at is None
    assert meta.ai_analysis_available is False
