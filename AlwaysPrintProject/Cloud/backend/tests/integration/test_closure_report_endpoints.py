"""
Tests de integración de los endpoints del Reporte de Cierre Mensual (task 8.2).

Cubren, end-to-end contra `app/api/v1/endpoints/billing_closures.py`, los tres endpoints del
reporte con roles y tenant isolation (Req 1.4, 1.5, 5.4, 6.4, 6.5, 8.2, 8.3, 8.4, 8.5):

- `GET  /billing/closures/{closure_id}/report`
- `POST /billing/closures/{closure_id}/report/regenerate`
- `GET  /billing/closures/{closure_id}/report-data`

Escenarios validados:
1. Cache-miss → `report_url` + `cached=false`; segunda llamada (artefacto ya en S3) → `cached=true`.
2. Tenant isolation: operador de la org A pidiendo el cierre de la org B → 403; superadmin → 200.
3. `regenerate` con admin/superadmin → `cached=false` y `ai_generated_at` actualizado; operador de
   otra org → 403.
4. Fail-safe end-to-end: el LLM forzado a fallar → PDF generado (subido a S3) con
   `ai_analysis_available=false`.

Patrón de test (idéntico a `tests/unit/test_billing_service.py`):
- Router montado en una `FastAPI` aislada con `dependency_overrides` de `get_db` y
  `get_current_user` (los guards `require_operator_or_admin`/`require_admin` dependen de
  `get_current_user`, así que basta con sobreescribirlo para fijar la identidad).
- Sesión SQLite real in-memory para ejercer la lógica de query/tenant isolation de verdad.

Se mockea SOLO el boundary de infraestructura (no la lógica del endpoint):
- El cliente S3, en los métodos del servicio (`s3_exists`, `upload_to_s3`,
  `generate_presigned_url`), para que NINGÚN test toque AWS real.
- El LLM (`ClosureReportService._invoke_llm`, AsyncMock); en el test de fail-safe se hace
  lanzar para que el análisis IA caiga al fail-safe (`ai_analysis_available=false`).
El resto del pipeline (serie histórica, render de gráficos matplotlib "Agg", composición del
PDF con fpdf2, upsert del análisis IA) se ejecuta de verdad.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import get_current_user
import app.models  # noqa: F401 — registra todas las tablas en metadata
from app.models.billing import (
    BillingClosure,
    BillingClosureItem,
    BillingClosureReport,
)
from app.models.organization import Organization
from app.models.user import User, UserRole
from app.api.v1.endpoints import billing_closures
from app.api.v1.endpoints.billing_closures import router as billing_closures_router

# Instancia del servicio que USAN los endpoints (module-level). Los mocks se aplican sobre
# ESTA instancia para interceptar el boundary de S3/LLM sin tocar la lógica del endpoint.
SERVICE = billing_closures.closure_report_service


# ── Fixtures y helpers ──────────────────────────────────────────────────────


def _make_session():
    """Sesión SQLite in-memory con el esquema completo (aislada por test)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return Session(), engine


def _make_org(db, name="Org Reporte") -> Organization:
    """Crea y persiste una organización mensual."""
    org = Organization(
        id=uuid.uuid4(),
        name=name,
        timezone="UTC",
        billing_mode="monthly",
    )
    db.add(org)
    db.commit()
    return org


def _make_closure(db, org, *, year=2026, month=5) -> BillingClosure:
    """
    Crea un cierre con cabecera + items para ejercer el pipeline completo del reporte.

    Los tramos (`tiers_applied`) siguen el formato de `TierBreakdown.to_dict` para que el
    render del gráfico de composición y el desglose del PDF tengan datos reales.
    """
    closure = BillingClosure(
        id=uuid.uuid4(),
        organization_id=org.id,
        period_year=year,
        period_month=month,
        cutoff_at=datetime(year, month, 1),
        mode="monthly",
        timezone="UTC",
        total_billable=3,
        total_recycled=1,
        total_archived=0,
        amount=Decimal("1.50"),
        tiers_applied=[
            {
                "tier_index": 0,
                "from": 1,
                "to": 100,
                "rate": 0.5,
                "ips_in_tier": 3,
                "subtotal": 1.5,
            }
        ],
        is_retroactive=False,
        created_at=datetime(year, month, 1, 12, 0, 0),
    )
    db.add(closure)
    db.commit()

    # Items facturables (sustento por IP) para que el PDF/gráficos tengan detalle real.
    for i in range(3):
        db.add(
            BillingClosureItem(
                id=uuid.uuid4(),
                closure_id=closure.id,
                workstation_id=uuid.uuid4(),
                ip_private=f"10.0.0.{i}",
                created_at_ws=datetime(year, month, 1),
                last_seen_capped=datetime(year, month, 1),
                billing_status="billable",
                tier_index=0,
                amount=Decimal("0.5000"),
            )
        )
    db.commit()
    return closure


def _admin_user() -> User:
    """Superadmin: en este sistema es UserRole.ADMIN (organization_id = None, acceso global)."""
    return User(
        id=uuid.uuid4(),
        email=f"admin_{uuid.uuid4().hex}@system.com",
        password_hash="x",
        full_name="Super Admin",
        role=UserRole.ADMIN,
        organization_id=None,
    )


def _operator_user(org_id) -> User:
    """Operador (no superadmin) de una organización concreta."""
    return User(
        id=uuid.uuid4(),
        email=f"op_{uuid.uuid4().hex}@bbva.com",
        password_hash="x",
        full_name="Operador",
        role=UserRole.OPERATOR,
        organization_id=org_id,
    )


def _build_app(db, current_user) -> FastAPI:
    """Monta el router de cierres en una FastAPI aislada con overrides de auth + get_db."""
    app = FastAPI()
    app.include_router(billing_closures_router, prefix="/billing")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: current_user
    return app


def _mock_s3(monkeypatch, *, exists_sequence):
    """
    Mockea el boundary S3 del servicio para NO tocar AWS real.

    `exists_sequence` es una lista de valores booleanos que `s3_exists` devolverá en orden
    (para simular cache-miss en la 1ª llamada y cache-hit en la 2ª). `upload_to_s3` se
    convierte en no-op y `generate_presigned_url` en una URL sintética determinista.

    Devuelve el mock de `upload_to_s3` para poder aseverar que el artefacto se subió.
    """
    exists_iter = iter(exists_sequence)

    def _s3_exists(_s3_key):
        try:
            return next(exists_iter)
        except StopIteration:
            # Tras agotar la secuencia, asumir que ya existe (cache-hit).
            return True

    upload_mock = _RecordingUpload()
    monkeypatch.setattr(SERVICE, "s3_exists", _s3_exists)
    monkeypatch.setattr(SERVICE, "upload_to_s3", upload_mock)
    monkeypatch.setattr(
        SERVICE,
        "generate_presigned_url",
        lambda s3_key, download_filename=None: f"https://s3.example/{s3_key}",
    )
    return upload_mock


class _RecordingUpload:
    """Sustituto de `upload_to_s3` que registra si fue invocado (no toca S3)."""

    def __init__(self):
        self.called = False
        self.call_count = 0
        self.last_key = None

    def __call__(self, pdf_bytes, s3_key):
        self.called = True
        self.call_count += 1
        self.last_key = s3_key
        # Verifica que el PDF compuesto no esté vacío (pipeline real ejecutado).
        assert isinstance(pdf_bytes, (bytes, bytearray)) and len(pdf_bytes) > 0


# ─────────────────────────────────────────────────────────────────────────────
# 1. GET .../report — cache-miss → report_url, segunda llamada → cached=true
# ─────────────────────────────────────────────────────────────────────────────


class TestGetReportCacheMissThenHit:
    """Req 1.4/1.5/8.3: primera llamada genera (cached=false); la segunda sirve de caché."""

    @pytest.mark.asyncio
    async def test_report_cache_miss_then_hit(self, monkeypatch):
        db, engine = _make_session()
        try:
            org = _make_org(db)
            closure = _make_closure(db, org)

            # 1ª llamada: no existe en S3 (miss) → pipeline completo + upload.
            # 2ª llamada: ya existe (hit) → no recomputa.
            upload_mock = _mock_s3(monkeypatch, exists_sequence=[False, True])
            # LLM exitoso: devuelve (texto, model_id) como el pipeline real espera.
            monkeypatch.setattr(
                SERVICE,
                "_invoke_llm",
                AsyncMock(return_value=("Análisis IA de prueba.", "bedrock:test-model")),
            )

            app = _build_app(db, _admin_user())
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # Cache-miss.
                r1 = await client.get(f"/billing/closures/{closure.id}/report")
                assert r1.status_code == 200
                body1 = r1.json()
                assert body1["cached"] is False
                assert body1["report_url"].startswith("https://s3.example/")
                assert body1["ai_analysis_available"] is True
                assert body1["expires_in_seconds"] == 3600

                # Cache-hit.
                r2 = await client.get(f"/billing/closures/{closure.id}/report")
                assert r2.status_code == 200
                body2 = r2.json()
                assert body2["cached"] is True
                assert body2["ai_analysis_available"] is True

            # El artefacto se subió exactamente una vez (solo en el cache-miss).
            assert upload_mock.called is True
            assert upload_mock.call_count == 1
            app.dependency_overrides.clear()
        finally:
            db.close()
            engine.dispose()

    @pytest.mark.asyncio
    async def test_report_closure_inexistente_404(self, monkeypatch):
        """Un cierre inexistente devuelve 404 (antes de tocar S3)."""
        db, engine = _make_session()
        try:
            _make_org(db)
            _mock_s3(monkeypatch, exists_sequence=[False])
            monkeypatch.setattr(
                SERVICE,
                "_invoke_llm",
                AsyncMock(return_value=("x", "m")),
            )
            app = _build_app(db, _admin_user())
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(f"/billing/closures/{uuid.uuid4()}/report")
            assert resp.status_code == 404
            app.dependency_overrides.clear()
        finally:
            db.close()
            engine.dispose()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Tenant isolation — operador de otra org → 403; superadmin → 200
# ─────────────────────────────────────────────────────────────────────────────


class TestReportTenantIsolation:
    """Req 6.4/8.4/8.5: aislamiento por organización en `GET .../report`."""

    @pytest.mark.asyncio
    async def test_operador_de_otra_org_403(self, monkeypatch):
        """Operador de la org A pidiendo el cierre de la org B → 403 (tenant isolation)."""
        db, engine = _make_session()
        try:
            org_a = _make_org(db, name="Org A")
            org_b = _make_org(db, name="Org B")
            closure_b = _make_closure(db, org_b)

            _mock_s3(monkeypatch, exists_sequence=[True])
            monkeypatch.setattr(
                SERVICE, "_invoke_llm", AsyncMock(return_value=("x", "m"))
            )

            # Usuario: operador de la org A pidiendo el cierre de la org B.
            app = _build_app(db, _operator_user(org_a.id))
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(f"/billing/closures/{closure_b.id}/report")
            assert resp.status_code == 403
            app.dependency_overrides.clear()
        finally:
            db.close()
            engine.dispose()

    @pytest.mark.asyncio
    async def test_superadmin_200(self, monkeypatch):
        """El superadmin (acceso global) obtiene 200 para el cierre de cualquier org."""
        db, engine = _make_session()
        try:
            org_b = _make_org(db, name="Org B")
            closure_b = _make_closure(db, org_b)

            _mock_s3(monkeypatch, exists_sequence=[False, True])
            monkeypatch.setattr(
                SERVICE,
                "_invoke_llm",
                AsyncMock(return_value=("Análisis IA.", "bedrock:test")),
            )

            app = _build_app(db, _admin_user())
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(f"/billing/closures/{closure_b.id}/report")
            assert resp.status_code == 200
            assert resp.json()["cached"] is False
            app.dependency_overrides.clear()
        finally:
            db.close()
            engine.dispose()

    @pytest.mark.asyncio
    async def test_operador_de_su_propia_org_200(self, monkeypatch):
        """Un operador SÍ puede pedir el reporte de un cierre de SU propia org."""
        db, engine = _make_session()
        try:
            org_a = _make_org(db, name="Org A")
            closure_a = _make_closure(db, org_a)

            _mock_s3(monkeypatch, exists_sequence=[False, True])
            monkeypatch.setattr(
                SERVICE,
                "_invoke_llm",
                AsyncMock(return_value=("Análisis IA.", "bedrock:test")),
            )

            app = _build_app(db, _operator_user(org_a.id))
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(f"/billing/closures/{closure_a.id}/report")
            assert resp.status_code == 200
            app.dependency_overrides.clear()
        finally:
            db.close()
            engine.dispose()


# ─────────────────────────────────────────────────────────────────────────────
# 3. regenerate — admin/superadmin cached=false + ai_generated_at; otra org → 403
# ─────────────────────────────────────────────────────────────────────────────


class TestRegenerateReport:
    """Req 6.4/6.5/8.5: regeneración con roles y actualización de `ai_generated_at`."""

    @pytest.mark.asyncio
    async def test_regenerate_superadmin_cached_false_y_ai_generated_at(self, monkeypatch):
        """
        Superadmin regenera → `cached=false`, `ai_analysis_available=true` y se persiste
        `ai_generated_at` (nuevo) en `billing_closure_reports`.
        """
        db, engine = _make_session()
        try:
            org = _make_org(db)
            closure = _make_closure(db, org)

            # regenerate NO consulta s3_exists (siempre recomputa); igual mockeamos el upload.
            upload_mock = _mock_s3(monkeypatch, exists_sequence=[True])
            monkeypatch.setattr(
                SERVICE,
                "_invoke_llm",
                AsyncMock(return_value=("Análisis IA regenerado.", "bedrock:test")),
            )

            app = _build_app(db, _admin_user())
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/billing/closures/{closure.id}/report/regenerate"
                )
            assert resp.status_code == 200
            body = resp.json()
            assert body["cached"] is False
            assert body["ai_analysis_available"] is True

            # El artefacto se (re)generó y subió, y el análisis IA quedó persistido con fecha.
            assert upload_mock.called is True
            row = (
                db.query(BillingClosureReport)
                .filter(BillingClosureReport.closure_id == closure.id)
                .one()
            )
            assert row.ai_analysis == "Análisis IA regenerado."
            assert row.ai_generated_at is not None
            app.dependency_overrides.clear()
        finally:
            db.close()
            engine.dispose()

    @pytest.mark.asyncio
    async def test_regenerate_actualiza_ai_generated_at(self, monkeypatch):
        """
        Regenerar sobre un reporte ya existente sobre-escribe el análisis y avanza
        `ai_generated_at` (no se queda con el valor viejo).
        """
        db, engine = _make_session()
        try:
            org = _make_org(db)
            closure = _make_closure(db, org)

            # Estado previo: fila con análisis y una fecha antigua.
            old_dt = datetime(2020, 1, 1, 0, 0, 0)
            db.add(
                BillingClosureReport(
                    id=uuid.uuid4(),
                    closure_id=closure.id,
                    organization_id=org.id,
                    ai_analysis="Análisis viejo.",
                    ai_model="bedrock:old",
                    ai_generated_at=old_dt,
                )
            )
            db.commit()

            _mock_s3(monkeypatch, exists_sequence=[True])
            monkeypatch.setattr(
                SERVICE,
                "_invoke_llm",
                AsyncMock(return_value=("Análisis nuevo.", "bedrock:new")),
            )

            app = _build_app(db, _admin_user())
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/billing/closures/{closure.id}/report/regenerate"
                )
            assert resp.status_code == 200

            db.expire_all()
            row = (
                db.query(BillingClosureReport)
                .filter(BillingClosureReport.closure_id == closure.id)
                .one()
            )
            assert row.ai_analysis == "Análisis nuevo."
            assert row.ai_generated_at is not None
            assert row.ai_generated_at > old_dt
            app.dependency_overrides.clear()
        finally:
            db.close()
            engine.dispose()

    @pytest.mark.asyncio
    async def test_regenerate_operador_de_otra_org_403(self, monkeypatch):
        """Un operador de OTRA org no puede regenerar el reporte → 403 (tenant isolation)."""
        db, engine = _make_session()
        try:
            org_a = _make_org(db, name="Org A")
            org_b = _make_org(db, name="Org B")
            closure_b = _make_closure(db, org_b)

            upload_mock = _mock_s3(monkeypatch, exists_sequence=[True])
            monkeypatch.setattr(
                SERVICE, "_invoke_llm", AsyncMock(return_value=("x", "m"))
            )

            app = _build_app(db, _operator_user(org_a.id))
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/billing/closures/{closure_b.id}/report/regenerate"
                )
            assert resp.status_code == 403
            # Un 403 no debe haber generado/ subido ningún artefacto.
            assert upload_mock.called is False
            app.dependency_overrides.clear()
        finally:
            db.close()
            engine.dispose()


# ─────────────────────────────────────────────────────────────────────────────
# 4. Fail-safe end-to-end — LLM falla → PDF generado con ai_analysis_available=false
# ─────────────────────────────────────────────────────────────────────────────


class TestReportFailSafe:
    """Req 5.4: un fallo del LLM NO bloquea el PDF; se refleja en ai_analysis_available=false."""

    @pytest.mark.asyncio
    async def test_llm_falla_pdf_generado_ai_no_disponible(self, monkeypatch):
        """
        El LLM lanza (fallo tras reintentos) → el reporte se genera igual (PDF subido a S3) y
        la respuesta trae `ai_analysis_available=false` (fail-safe).
        """
        db, engine = _make_session()
        try:
            org = _make_org(db)
            closure = _make_closure(db, org)

            upload_mock = _mock_s3(monkeypatch, exists_sequence=[False, True])
            # LLM forzado a fallar: `resolve_ai_analysis` captura y devuelve None (fail-safe).
            monkeypatch.setattr(
                SERVICE,
                "_invoke_llm",
                AsyncMock(side_effect=RuntimeError("LLM caído")),
            )

            app = _build_app(db, _admin_user())
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(f"/billing/closures/{closure.id}/report")
            assert resp.status_code == 200
            body = resp.json()
            # El PDF se generó (cache-miss) pese al fallo del LLM.
            assert body["cached"] is False
            assert body["ai_analysis_available"] is False
            assert body["report_url"].startswith("https://s3.example/")

            # El artefacto (PDF) se subió a S3 aunque la IA no esté disponible.
            assert upload_mock.called is True
            app.dependency_overrides.clear()
        finally:
            db.close()
            engine.dispose()
