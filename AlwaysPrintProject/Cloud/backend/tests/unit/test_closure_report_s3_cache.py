"""
Tests unitarios de la caché S3 y la orquestación `ClosureReportService.generate_or_get` (task 7.3).

Verifica el comportamiento de cache-hit / cache-miss del artefacto PDF en S3 y la construcción
correcta del cliente S3 (SigV4 + endpoint regional). El acceso real a S3 se mockea por completo:

1. Cache-hit: con `s3_exists=True` y `regenerate=False`, `generate_or_get` devuelve `cached=True`
   SIN recomputar (no se invoca `compose_pdf` ni ninguna función de render, y `upload_to_s3`
   NO se llama).
2. Cache-miss: con `s3_exists=False`, se ejecuta el pipeline completo (items → history → IA →
   render → PDF) y `upload_to_s3` se llama exactamente una vez; se devuelve `cached=False`.
3. Regenerate: con `regenerate=True` y artefacto existente, se sobre-escribe (el shortcut de
   `s3_exists` se omite, el pipeline corre y `upload_to_s3` se llama) devolviendo `cached=False`.
4. Construcción del cliente S3 (`_get_s3_client`): se parchea `boto3.Session` para capturar los
   kwargs de `session.client(...)` y se verifica SigV4 (`Config.signature_version == "s3v4"`) y el
   endpoint regional explícito (`https://s3.<region>.amazonaws.com`).

Convenciones: se reutiliza la fixture `db` de `tests/conftest.py` (sesión SQLite in-memory con el
esquema completo) y `asyncio_mode = "auto"` (pyproject.toml) para las funciones `async def test_*`.
El LLM nunca se ejecuta: `resolve_ai_analysis` se parchea con un `AsyncMock`. Las funciones de
render y `compose_pdf` (módulo-level) se parchean para evitar trabajo pesado de matplotlib/fpdf.

_Requirements: 1.2, 2.2, 2.3, 2.4_
"""

import uuid
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from botocore.client import Config

from app.core.config import settings
from app.models.organization import Organization
from app.models.billing import BillingClosure, BillingClosureReport
from app.services import closure_report_service as crs_module
from app.services.closure_report_service import ClosureReportService


def _make_org(db, name: str) -> Organization:
    """Crea y persiste una organización mínima."""
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


def _patch_pipeline(monkeypatch, service):
    """
    Parchea las etapas pesadas del pipeline (IA + render + PDF) con mocks livianos.

    Devuelve el dict de mocks para que cada test pueda hacer aserciones sobre ellos:
    `resolve_ai_analysis` (AsyncMock), `render_tiers`, `render_history` y `compose_pdf`.
    Estos parches no afectan el shortcut de cache-hit (que no debe invocarlos).
    """
    ai_mock = AsyncMock(return_value="Analisis IA de prueba")
    monkeypatch.setattr(service, "resolve_ai_analysis", ai_mock)

    render_tiers = MagicMock(return_value=b"\x89PNG-tiers")
    render_history = MagicMock(return_value=b"\x89PNG-history")
    compose_pdf = MagicMock(return_value=b"%PDF-1.4 fake")
    monkeypatch.setattr(crs_module, "render_tiers_chart", render_tiers)
    monkeypatch.setattr(crs_module, "render_history_chart", render_history)
    monkeypatch.setattr(crs_module, "compose_pdf", compose_pdf)

    return {
        "resolve_ai_analysis": ai_mock,
        "render_tiers": render_tiers,
        "render_history": render_history,
        "compose_pdf": compose_pdf,
    }


# === Caso 1: cache-hit (artefacto existe + regenerate=False) ===


async def test_cache_hit_returns_cached_without_recomputing(db, service, monkeypatch):
    """
    Artefacto existente + `regenerate=False` → `cached=True` sin recomputar: `upload_to_s3` NO se
    llama y el pipeline (`compose_pdf`, render, IA) NO se invoca (Req 1.2, 2.2).
    """
    org = _make_org(db, "Org CacheHit")
    closure = _make_closure(db, org)

    # Fila persistida con análisis IA → ai_available debe derivarse de aquí (True).
    db.add(
        BillingClosureReport(
            closure_id=closure.id,
            organization_id=org.id,
            ai_analysis="Analisis previamente cacheado",
            ai_model="modelo-cache",
            ai_generated_at=datetime(2025, 1, 1),
        )
    )
    db.flush()

    # S3 dice que el artefacto existe (cache-hit).
    monkeypatch.setattr(service, "s3_exists", MagicMock(return_value=True))
    upload_mock = MagicMock()
    monkeypatch.setattr(service, "upload_to_s3", upload_mock)
    mocks = _patch_pipeline(monkeypatch, service)

    s3_key, ai_available, cached = await service.generate_or_get(
        db, closure, org, regenerate=False
    )

    assert cached is True
    assert ai_available is True  # derivado de la fila persistida
    assert s3_key == service.build_s3_key(closure)

    # No se recomputó nada: ni pipeline ni subida.
    upload_mock.assert_not_called()
    mocks["compose_pdf"].assert_not_called()
    mocks["render_tiers"].assert_not_called()
    mocks["render_history"].assert_not_called()
    mocks["resolve_ai_analysis"].assert_not_called()


async def test_cache_hit_ai_unavailable_when_no_row(db, service, monkeypatch):
    """
    Cache-hit sin fila de reporte (o sin `ai_analysis`) → `cached=True` pero `ai_available=False`.
    """
    org = _make_org(db, "Org CacheHit SinIA")
    closure = _make_closure(db, org)

    monkeypatch.setattr(service, "s3_exists", MagicMock(return_value=True))
    upload_mock = MagicMock()
    monkeypatch.setattr(service, "upload_to_s3", upload_mock)
    _patch_pipeline(monkeypatch, service)

    _, ai_available, cached = await service.generate_or_get(db, closure, org, regenerate=False)

    assert cached is True
    assert ai_available is False
    upload_mock.assert_not_called()


# === Caso 2: cache-miss (artefacto no existe) ===


async def test_cache_miss_runs_full_pipeline_and_uploads(db, service, monkeypatch):
    """
    Sin artefacto (`s3_exists=False`) → pipeline completo + `upload_to_s3` llamado una vez y
    `cached=False` (Req 2.3).
    """
    org = _make_org(db, "Org CacheMiss")
    closure = _make_closure(db, org)

    monkeypatch.setattr(service, "s3_exists", MagicMock(return_value=False))
    upload_mock = MagicMock()
    monkeypatch.setattr(service, "upload_to_s3", upload_mock)
    mocks = _patch_pipeline(monkeypatch, service)

    s3_key, ai_available, cached = await service.generate_or_get(
        db, closure, org, regenerate=False
    )

    assert cached is False
    assert ai_available is True  # resolve_ai_analysis devolvió texto no nulo
    assert s3_key == service.build_s3_key(closure)

    # Pipeline completo ejecutado exactamente una vez.
    mocks["resolve_ai_analysis"].assert_awaited_once()
    mocks["render_tiers"].assert_called_once()
    mocks["render_history"].assert_called_once()
    mocks["compose_pdf"].assert_called_once()

    # Subida a S3 del PDF compuesto exactamente una vez con la key determinista.
    upload_mock.assert_called_once()
    uploaded_bytes, uploaded_key = upload_mock.call_args.args
    assert uploaded_bytes == b"%PDF-1.4 fake"
    assert uploaded_key == s3_key

    # El artefacto quedó registrado en la fila auxiliar (pdf_s3_key/pdf_generated_at).
    row = service.get_report_row(db, closure)
    assert row is not None
    assert row.pdf_s3_key == s3_key
    assert row.pdf_generated_at is not None


async def test_cache_miss_ai_none_reports_unavailable(db, service, monkeypatch):
    """
    Cache-miss con IA no disponible (fail-safe → `resolve_ai_analysis` devuelve `None`):
    el PDF igual se genera/sube y `ai_available=False`, `cached=False`.
    """
    org = _make_org(db, "Org CacheMiss SinIA")
    closure = _make_closure(db, org)

    monkeypatch.setattr(service, "s3_exists", MagicMock(return_value=False))
    upload_mock = MagicMock()
    monkeypatch.setattr(service, "upload_to_s3", upload_mock)
    mocks = _patch_pipeline(monkeypatch, service)
    mocks["resolve_ai_analysis"].return_value = None  # IA no disponible

    _, ai_available, cached = await service.generate_or_get(db, closure, org, regenerate=False)

    assert cached is False
    assert ai_available is False
    upload_mock.assert_called_once()
    mocks["compose_pdf"].assert_called_once()


# === Caso 3: regenerate=True (sobre-escribe aunque exista) ===


async def test_regenerate_overwrites_even_when_artifact_exists(db, service, monkeypatch):
    """
    `regenerate=True` con artefacto existente → se omite el shortcut de `s3_exists`, corre el
    pipeline y se sobre-escribe (`upload_to_s3` llamado), devolviendo `cached=False` (Req 2.4).
    """
    org = _make_org(db, "Org Regenerate")
    closure = _make_closure(db, org)

    # s3_exists devolvería True, pero regenerate=True debe ignorarlo (ni siquiera consultarlo).
    s3_exists_mock = MagicMock(return_value=True)
    monkeypatch.setattr(service, "s3_exists", s3_exists_mock)
    upload_mock = MagicMock()
    monkeypatch.setattr(service, "upload_to_s3", upload_mock)
    mocks = _patch_pipeline(monkeypatch, service)

    s3_key, ai_available, cached = await service.generate_or_get(
        db, closure, org, regenerate=True
    )

    assert cached is False
    assert ai_available is True

    # El shortcut de cache-hit NO se toma con regenerate=True (no debe consultarse s3_exists).
    s3_exists_mock.assert_not_called()

    # Se sobre-escribe: pipeline corre y se sube el nuevo PDF a la misma key determinista.
    mocks["compose_pdf"].assert_called_once()
    upload_mock.assert_called_once()
    _, uploaded_key = upload_mock.call_args.args
    assert uploaded_key == s3_key

    # resolve_ai_analysis se invoca con regenerate=True propagado.
    mocks["resolve_ai_analysis"].assert_awaited_once()
    assert mocks["resolve_ai_analysis"].await_args.kwargs.get("regenerate") is True


# === Construcción del cliente S3: SigV4 + endpoint regional ===


def test_get_s3_client_uses_sigv4_and_regional_endpoint(service, monkeypatch):
    """
    `_get_s3_client` construye el cliente con SigV4 (`Config.signature_version == "s3v4"`) y el
    endpoint regional explícito (`https://s3.<region>.amazonaws.com`) (Req 1.2, 2.5).
    """
    captured = {}
    fake_client = MagicMock(name="s3-client")

    class _FakeSession:
        def __init__(self, *args, **kwargs):
            captured["session_kwargs"] = kwargs

        def client(self, service_name, **kwargs):
            captured["client_service"] = service_name
            captured["client_kwargs"] = kwargs
            return fake_client

    # Parchear boto3.Session en el módulo del servicio para capturar los kwargs.
    monkeypatch.setattr(crs_module.boto3, "Session", _FakeSession)

    result = service._get_s3_client()

    assert result is fake_client
    assert captured["client_service"] == "s3"

    # Endpoint regional explícito derivado de settings.AWS_REGION.
    expected_endpoint = f"https://s3.{settings.AWS_REGION}.amazonaws.com"
    assert captured["client_kwargs"]["endpoint_url"] == expected_endpoint

    # SigV4 forzado vía botocore Config.
    config = captured["client_kwargs"]["config"]
    assert isinstance(config, Config)
    assert config.signature_version == "s3v4"

    # La sesión usa la región (y no rompe con el profile).
    assert captured["session_kwargs"].get("region_name") == settings.AWS_REGION
