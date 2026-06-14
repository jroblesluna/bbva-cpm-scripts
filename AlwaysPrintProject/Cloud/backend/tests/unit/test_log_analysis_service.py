"""
Tests unitarios para LogAnalysisService.

Verifica:
- process_log ruta directa (log < 100KB)
- process_log ruta estructural (log ≥ 100KB)
- get_today_analysis retorna None si no existe
- overwrite elimina registro previo
- historial paginado con orden descendente

Requirements: 12.2, 12.4, 12.6
"""

import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.log_analysis import LogAnalysis
from app.services.log_analysis import LogAnalysisService


# === FIXTURES ===


@pytest.fixture
def db():
    """
    Sesión de base de datos SQLite en memoria sin FK constraints.

    Desactiva PRAGMA foreign_keys para evitar errores por tablas
    referenciadas (workstations, organizations) que no se crean en este test.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Desactivar FK constraints en SQLite para tests aislados
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def service():
    """Instancia de LogAnalysisService con LLMService mockeado."""
    svc = LogAnalysisService()
    svc.llm_service = AsyncMock()
    # invoke() retorna tupla (texto, input_tokens, output_tokens)
    svc.llm_service.invoke = AsyncMock(return_value=("Análisis generado por el LLM.", 100, 50))
    return svc


@pytest.fixture
def workstation_id():
    """UUID de workstation para tests."""
    return str(uuid.uuid4())


@pytest.fixture
def organization_id():
    """UUID de organización para tests."""
    return str(uuid.uuid4())


@pytest.fixture
def small_log_payload():
    """Payload de log pequeño (< 100KB) sin comprimir."""
    # Generar contenido de log de ~50KB
    line = "[2025-01-15 10:30:00] [SVC] Event 1000: Servicio iniciado\n"
    content = line * 500  # ~30KB aprox
    return content.encode("utf-8")


@pytest.fixture
def large_log_payload():
    """Payload de log grande (≥ 100KB) sin comprimir."""
    # Generar contenido de log de ~120KB
    line = "[2025-01-15 10:30:00] [SVC] Event 1091: Error de conexión timeout\n"
    content = line * 2000  # ~120KB aprox
    return content.encode("utf-8")


# === TESTS PROCESS_LOG RUTA DIRECTA ===


class TestProcessLogDirectPath:
    """Tests de process_log con ruta directa (log < 100KB)."""

    @pytest.mark.asyncio
    async def test_log_pequeno_usa_ruta_directa(
        self, db, service, workstation_id, organization_id, small_log_payload
    ):
        """
        WHEN se procesa un log menor a 100KB,
        THEN se usa la ruta directa y se guarda con processing_path='direct'.
        Validates: Requirement 12.2
        """
        result = await service.process_log(
            db=db,
            workstation_id=workstation_id,
            organization_id=organization_id,
            raw_payload=small_log_payload,
            is_compressed=False,
            original_filename="AlwaysPrint_2025-01-15.log",
            original_size=len(small_log_payload),
        )

        assert result.processing_path == "structural"
        assert str(result.workstation_id) == workstation_id
        assert str(result.organization_id) == organization_id
        # El servicio añade estimación de tokens al final del texto
        expected_text = (
            "Análisis generado por el LLM.\n\n---\n"
            "*Tokens utilizados: 100 input + 50 output = 150 total*"
        )
        assert result.analysis_text == expected_text
        assert result.analysis_date == date.today()
        assert result.original_filename == "AlwaysPrint_2025-01-15.log"
        assert result.log_size_bytes > 0
        assert result.processing_duration_ms >= 0

    @pytest.mark.asyncio
    async def test_ruta_directa_invoca_llm_con_payload(
        self, db, service, workstation_id, organization_id, small_log_payload
    ):
        """
        WHEN se procesa un log por ruta directa,
        THEN se invoca el LLM con el payload ensamblado (prompt + log crudo).
        Validates: Requirement 12.2
        """
        await service.process_log(
            db=db,
            workstation_id=workstation_id,
            organization_id=organization_id,
            raw_payload=small_log_payload,
            is_compressed=False,
            original_filename="AlwaysPrint_2025-01-15.log",
            original_size=len(small_log_payload),
        )

        service.llm_service.invoke.assert_called_once()
        payload_enviado = service.llm_service.invoke.call_args[0][0]
        # El payload debe contener el prompt y el contenido del log
        assert "Eres un experto en diagnóstico" in payload_enviado
        assert "Event 1000" in payload_enviado

    @pytest.mark.asyncio
    async def test_ruta_directa_persiste_en_bd(
        self, db, service, workstation_id, organization_id, small_log_payload
    ):
        """
        WHEN se procesa un log por ruta directa,
        THEN el registro se persiste correctamente en la base de datos.
        Validates: Requirement 12.2
        """
        result = await service.process_log(
            db=db,
            workstation_id=workstation_id,
            organization_id=organization_id,
            raw_payload=small_log_payload,
            is_compressed=False,
            original_filename="AlwaysPrint_2025-01-15.log",
            original_size=len(small_log_payload),
        )

        # Verificar que se puede recuperar de la BD
        from_db = db.query(LogAnalysis).filter(LogAnalysis.id == result.id).first()
        assert from_db is not None
        # El servicio añade estimación de tokens al final del texto
        expected_text = (
            "Análisis generado por el LLM.\n\n---\n"
            "*Tokens utilizados: 100 input + 50 output = 150 total*"
        )
        assert from_db.analysis_text == expected_text
        assert from_db.processing_path == "structural"


# === TESTS PROCESS_LOG RUTA ESTRUCTURAL ===


class TestProcessLogStructuralPath:
    """Tests de process_log con ruta estructural (log ≥ 100KB)."""

    @pytest.mark.asyncio
    async def test_log_grande_usa_ruta_estructural(
        self, db, service, workstation_id, organization_id, large_log_payload
    ):
        """
        WHEN se procesa un log de 100KB o más,
        THEN se usa la ruta estructural y se guarda con processing_path='structural'.
        Validates: Requirement 12.2
        """
        result = await service.process_log(
            db=db,
            workstation_id=workstation_id,
            organization_id=organization_id,
            raw_payload=large_log_payload,
            is_compressed=False,
            original_filename="AlwaysPrint_2025-01-15.log",
            original_size=len(large_log_payload),
        )

        assert result.processing_path == "structural"
        assert str(result.workstation_id) == workstation_id
        assert str(result.organization_id) == organization_id
        # El servicio añade estimación de tokens al final del texto
        expected_text = (
            "Análisis generado por el LLM.\n\n---\n"
            "*Tokens utilizados: 100 input + 50 output = 150 total*"
        )
        assert result.analysis_text == expected_text
        assert result.log_size_bytes >= 102400

    @pytest.mark.asyncio
    async def test_ruta_estructural_invoca_llm_con_analisis_estructurado(
        self, db, service, workstation_id, organization_id, large_log_payload
    ):
        """
        WHEN se procesa un log por ruta estructural,
        THEN se invoca el LLM con el análisis estructurado (no el log crudo completo).
        Validates: Requirement 12.2
        """
        await service.process_log(
            db=db,
            workstation_id=workstation_id,
            organization_id=organization_id,
            raw_payload=large_log_payload,
            is_compressed=False,
            original_filename="AlwaysPrint_2025-01-15.log",
            original_size=len(large_log_payload),
        )

        service.llm_service.invoke.assert_called_once()
        payload_enviado = service.llm_service.invoke.call_args[0][0]
        # El payload debe contener el prompt
        assert "Eres un experto en diagnóstico" in payload_enviado
        # Debe contener secciones del análisis estructurado
        assert "Metadata" in payload_enviado or "metadata" in payload_enviado.lower()


# === TESTS GET_TODAY_ANALYSIS ===


class TestGetTodayAnalysis:
    """Tests de get_today_analysis."""

    def test_retorna_none_si_no_existe(
        self, db, service, workstation_id, organization_id
    ):
        """
        WHEN no existe un análisis para hoy para la workstation,
        THEN get_today_analysis retorna None.
        Validates: Requirement 12.2
        """
        result = service.get_today_analysis(db, workstation_id, organization_id)
        assert result is None

    def test_retorna_analisis_existente_de_hoy(
        self, db, service, workstation_id, organization_id
    ):
        """
        WHEN existe un análisis para hoy para la workstation,
        THEN get_today_analysis retorna el registro.
        """
        # Crear un análisis para hoy
        analysis = LogAnalysis(
            workstation_id=workstation_id,
            organization_id=organization_id,
            analysis_date=date.today(),
            analysis_text="Análisis previo",
            processing_path="direct",
            log_size_bytes=5000,
            processing_duration_ms=1200,
            original_filename="AlwaysPrint_2025-01-15.log",
        )
        db.add(analysis)
        db.commit()

        result = service.get_today_analysis(db, workstation_id, organization_id)
        assert result is not None
        assert result.analysis_text == "Análisis previo"

    def test_no_retorna_analisis_de_otro_dia(
        self, db, service, workstation_id, organization_id
    ):
        """
        WHEN existe un análisis de ayer pero no de hoy,
        THEN get_today_analysis retorna None.
        """
        # Crear un análisis de ayer
        analysis = LogAnalysis(
            workstation_id=workstation_id,
            organization_id=organization_id,
            analysis_date=date.today() - timedelta(days=1),
            analysis_text="Análisis de ayer",
            processing_path="direct",
            log_size_bytes=5000,
            processing_duration_ms=1200,
            original_filename="AlwaysPrint_2025-01-14.log",
        )
        db.add(analysis)
        db.commit()

        result = service.get_today_analysis(db, workstation_id, organization_id)
        assert result is None


# === TESTS OVERWRITE ===


class TestOverwrite:
    """Tests de overwrite que elimina registro previo."""

    @pytest.mark.asyncio
    async def test_overwrite_elimina_registro_previo(
        self, db, service, workstation_id, organization_id, small_log_payload
    ):
        """
        WHEN se invoca process_log con overwrite=True y existe un análisis previo,
        THEN se elimina el registro previo y se crea uno nuevo.
        Validates: Requirement 12.4
        """
        # Crear análisis previo para hoy
        prev_analysis = LogAnalysis(
            workstation_id=workstation_id,
            organization_id=organization_id,
            analysis_date=date.today(),
            analysis_text="Análisis anterior que será reemplazado",
            processing_path="direct",
            log_size_bytes=3000,
            processing_duration_ms=800,
            original_filename="AlwaysPrint_2025-01-15.log",
        )
        db.add(prev_analysis)
        db.commit()
        prev_id = prev_analysis.id

        # Procesar con overwrite
        new_result = await service.process_log(
            db=db,
            workstation_id=workstation_id,
            organization_id=organization_id,
            raw_payload=small_log_payload,
            is_compressed=False,
            original_filename="AlwaysPrint_2025-01-15.log",
            original_size=len(small_log_payload),
            overwrite=True,
        )

        # Verificar que el anterior fue eliminado
        old_record = db.query(LogAnalysis).filter(LogAnalysis.id == prev_id).first()
        assert old_record is None

        # Verificar que el nuevo existe con texto + estimación de tokens
        expected_text = (
            "Análisis generado por el LLM.\n\n---\n"
            "*Tokens utilizados: 100 input + 50 output = 150 total*"
        )
        assert new_result.analysis_text == expected_text
        assert new_result.id != prev_id

    @pytest.mark.asyncio
    async def test_overwrite_sin_registro_previo_funciona_normal(
        self, db, service, workstation_id, organization_id, small_log_payload
    ):
        """
        WHEN se invoca process_log con overwrite=True pero no existe análisis previo,
        THEN se crea el nuevo análisis sin error.
        Validates: Requirement 12.4
        """
        result = await service.process_log(
            db=db,
            workstation_id=workstation_id,
            organization_id=organization_id,
            raw_payload=small_log_payload,
            is_compressed=False,
            original_filename="AlwaysPrint_2025-01-15.log",
            original_size=len(small_log_payload),
            overwrite=True,
        )

        assert result is not None
        # El servicio añade estimación de tokens al final del texto
        expected_text = (
            "Análisis generado por el LLM.\n\n---\n"
            "*Tokens utilizados: 100 input + 50 output = 150 total*"
        )
        assert result.analysis_text == expected_text

    @pytest.mark.asyncio
    async def test_solo_un_registro_por_dia_despues_de_overwrite(
        self, db, service, workstation_id, organization_id, small_log_payload
    ):
        """
        WHEN se hace overwrite,
        THEN solo queda un registro para esa workstation en el día.
        Validates: Requirement 12.4
        """
        # Crear análisis previo
        prev_analysis = LogAnalysis(
            workstation_id=workstation_id,
            organization_id=organization_id,
            analysis_date=date.today(),
            analysis_text="Previo",
            processing_path="direct",
            log_size_bytes=1000,
            processing_duration_ms=500,
            original_filename="AlwaysPrint_2025-01-15.log",
        )
        db.add(prev_analysis)
        db.commit()

        # Overwrite
        await service.process_log(
            db=db,
            workstation_id=workstation_id,
            organization_id=organization_id,
            raw_payload=small_log_payload,
            is_compressed=False,
            original_filename="AlwaysPrint_2025-01-15.log",
            original_size=len(small_log_payload),
            overwrite=True,
        )

        # Verificar que solo hay un registro para hoy
        count = (
            db.query(LogAnalysis)
            .filter(
                LogAnalysis.workstation_id == workstation_id,
                LogAnalysis.analysis_date == date.today(),
            )
            .count()
        )
        assert count == 1


# === TESTS HISTORIAL PAGINADO ===


class TestAnalysisHistory:
    """Tests de historial paginado con orden descendente."""

    def test_historial_paginado_orden_descendente(
        self, db, service, workstation_id, organization_id
    ):
        """
        WHEN se consulta el historial de análisis,
        THEN se retornan ordenados por fecha descendente (más reciente primero).
        Validates: Requirement 12.6
        """
        # Crear análisis en diferentes fechas
        for i in range(5):
            analysis = LogAnalysis(
                workstation_id=workstation_id,
                organization_id=organization_id,
                analysis_date=date.today() - timedelta(days=i),
                analysis_text=f"Análisis día -{i}",
                processing_path="direct",
                log_size_bytes=5000,
                processing_duration_ms=1000,
                original_filename=f"AlwaysPrint_day_{i}.log",
            )
            db.add(analysis)
        db.commit()

        items, total = service.get_analysis_history(
            db, workstation_id, organization_id, page=1, page_size=20
        )

        assert total == 5
        assert len(items) == 5
        # Verificar orden descendente por fecha
        for i in range(len(items) - 1):
            assert items[i].analysis_date >= items[i + 1].analysis_date

    def test_historial_paginado_respeta_page_size(
        self, db, service, workstation_id, organization_id
    ):
        """
        WHEN se consulta el historial con page_size=2,
        THEN se retornan máximo 2 resultados por página.
        Validates: Requirement 12.6
        """
        # Crear 5 análisis
        for i in range(5):
            analysis = LogAnalysis(
                workstation_id=workstation_id,
                organization_id=organization_id,
                analysis_date=date.today() - timedelta(days=i),
                analysis_text=f"Análisis {i}",
                processing_path="direct",
                log_size_bytes=5000,
                processing_duration_ms=1000,
                original_filename=f"log_{i}.log",
            )
            db.add(analysis)
        db.commit()

        items, total = service.get_analysis_history(
            db, workstation_id, organization_id, page=1, page_size=2
        )

        assert total == 5
        assert len(items) == 2

    def test_historial_paginado_segunda_pagina(
        self, db, service, workstation_id, organization_id
    ):
        """
        WHEN se consulta la segunda página del historial,
        THEN se retornan los registros correspondientes al offset.
        Validates: Requirement 12.6
        """
        # Crear 5 análisis
        for i in range(5):
            analysis = LogAnalysis(
                workstation_id=workstation_id,
                organization_id=organization_id,
                analysis_date=date.today() - timedelta(days=i),
                analysis_text=f"Análisis {i}",
                processing_path="direct",
                log_size_bytes=5000,
                processing_duration_ms=1000,
                original_filename=f"log_{i}.log",
            )
            db.add(analysis)
        db.commit()

        items_p1, _ = service.get_analysis_history(
            db, workstation_id, organization_id, page=1, page_size=2
        )
        items_p2, _ = service.get_analysis_history(
            db, workstation_id, organization_id, page=2, page_size=2
        )

        # No deben solaparse
        ids_p1 = {item.id for item in items_p1}
        ids_p2 = {item.id for item in items_p2}
        assert ids_p1.isdisjoint(ids_p2)
        assert len(items_p2) == 2

    def test_historial_vacio_retorna_lista_vacia(
        self, db, service, workstation_id, organization_id
    ):
        """
        WHEN no existen análisis para la workstation,
        THEN se retorna lista vacía con total=0.
        Validates: Requirement 12.6
        """
        items, total = service.get_analysis_history(
            db, workstation_id, organization_id
        )

        assert total == 0
        assert items == []
