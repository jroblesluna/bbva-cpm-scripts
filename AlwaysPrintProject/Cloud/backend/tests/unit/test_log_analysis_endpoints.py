"""
Tests unitarios para endpoints de análisis de logs de workstations.

Verifica los códigos de respuesta HTTP para los distintos escenarios de error
y éxito del endpoint POST /{workstation_id}/analyze-log:
- Workstation no encontrada (404)
- Workstation offline (409)
- Timeout WebSocket (408)
- Análisis existente sin overwrite (409)
- Overwrite exitoso (200)
- Permisos: operador solo su organización (403)
- ZIP corrupto (422)
- Upload > 50MB (413)
- LLM error → 502

Requirements: 1.8, 1.9, 2.4, 2.7, 2.8, 10.7
"""

import base64
import json
import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.api.v1.endpoints.log_analysis import router, _verify_workstation_access
from app.core.security import get_current_user
from app.core.database import get_db
from app.models.user import User, UserRole
from app.models.workstation import Workstation
from app.services.llm_service import LLMServiceError


# === FIXTURES ===


@pytest.fixture
def org_id():
    """UUID de organización para tests."""
    return uuid.uuid4()


@pytest.fixture
def other_org_id():
    """UUID de otra organización para tests de permisos."""
    return uuid.uuid4()


@pytest.fixture
def workstation_id():
    """UUID de workstation para tests."""
    return uuid.uuid4()


@pytest.fixture
def admin_user(org_id):
    """Usuario admin con acceso global."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = "admin@test.com"
    user.role = UserRole.ADMIN
    user.organization_id = None
    return user


@pytest.fixture
def operator_user(org_id):
    """Usuario operador con acceso limitado a su organización."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = "operator@test.com"
    user.role = UserRole.OPERATOR
    user.organization_id = org_id
    return user


@pytest.fixture
def mock_workstation(workstation_id, org_id):
    """Workstation mock con organización asignada."""
    ws = MagicMock(spec=Workstation)
    ws.id = workstation_id
    ws.organization_id = org_id
    ws.ip_private = "192.168.1.100"
    ws.is_online = True
    return ws


@pytest.fixture
def mock_db(mock_workstation):
    """Sesión de BD mock que retorna la workstation."""
    db = MagicMock()
    query_mock = MagicMock()
    filter_mock = MagicMock()
    filter_mock.first.return_value = mock_workstation
    query_mock.filter.return_value = filter_mock
    db.query.return_value = query_mock
    return db


@pytest.fixture
def mock_db_no_workstation():
    """Sesión de BD mock que no encuentra workstation."""
    db = MagicMock()
    query_mock = MagicMock()
    filter_mock = MagicMock()
    filter_mock.first.return_value = None
    query_mock.filter.return_value = filter_mock
    db.query.return_value = query_mock
    return db


@pytest.fixture
def app_with_mocks(admin_user, mock_db):
    """Aplicación FastAPI con dependencias mockeadas (usuario admin, BD con workstation)."""
    app = FastAPI()
    app.include_router(router, prefix="/workstations")

    app.dependency_overrides[get_current_user] = lambda: admin_user
    app.dependency_overrides[get_db] = lambda: mock_db

    yield app

    app.dependency_overrides.clear()


def _make_valid_ws_response():
    """Genera una respuesta válida de la workstation (log pequeño en base64)."""
    log_content = "[2025-01-15 10:30:00] [SVC] Event 1000: Servicio iniciado\n" * 10
    content_b64 = base64.b64encode(log_content.encode("utf-8")).decode("utf-8")
    return {
        "success": True,
        "output": json.dumps({
            "filename": "AlwaysPrint_2025-01-15.log",
            "content": content_b64,
            "original_size": len(log_content),
            "is_compressed": False,
        }),
    }


# === TEST: WORKSTATION NO ENCONTRADA (404) ===


class TestWorkstationNoEncontrada:
    """Tests para verificar respuesta 404 cuando la workstation no existe."""

    @pytest.mark.asyncio
    async def test_analyze_log_workstation_no_encontrada(
        self, admin_user, mock_db_no_workstation, workstation_id
    ):
        """
        WHEN se solicita análisis de una workstation que no existe en BD,
        THEN se retorna HTTP 404 con mensaje descriptivo.
        Validates: Requirement 1.8
        """
        app = FastAPI()
        app.include_router(router, prefix="/workstations")
        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db_no_workstation

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                f"/workstations/{workstation_id}/analyze-log"
            )

        assert response.status_code == 404
        assert "no encontrada" in response.json()["detail"]

        app.dependency_overrides.clear()


# === TEST: WORKSTATION OFFLINE (409) ===


class TestWorkstationOffline:
    """Tests para verificar respuesta 409 cuando la workstation está offline."""

    @pytest.mark.asyncio
    async def test_analyze_log_workstation_offline(
        self, admin_user, mock_db, workstation_id
    ):
        """
        WHEN la workstation está offline (WebSocket desconectado),
        THEN se retorna HTTP 409 indicando que no se puede contactar.
        Validates: Requirement 1.8
        """
        app = FastAPI()
        app.include_router(router, prefix="/workstations")
        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "app.api.v1.endpoints.log_analysis.LogAnalysisService"
        ) as MockService, patch(
            "app.api.v1.endpoints.log_analysis.connection_manager"
        ) as mock_cm:
            # No hay análisis existente
            mock_svc_instance = MockService.return_value
            mock_svc_instance.get_today_analysis.return_value = None

            # Workstation offline
            mock_cm.is_workstation_online.return_value = False

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    f"/workstations/{workstation_id}/analyze-log"
                )

        assert response.status_code == 409
        assert "offline" in response.json()["detail"].lower()

        app.dependency_overrides.clear()


# === TEST: TIMEOUT WEBSOCKET (408) ===


class TestTimeoutWebSocket:
    """Tests para verificar respuesta 408 cuando la workstation no responde a tiempo."""

    @pytest.mark.asyncio
    async def test_analyze_log_timeout(
        self, admin_user, mock_db, workstation_id
    ):
        """
        WHEN la workstation no responde dentro del timeout configurado,
        THEN se retorna HTTP 408 indicando timeout.
        Validates: Requirement 1.9
        """
        app = FastAPI()
        app.include_router(router, prefix="/workstations")
        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "app.api.v1.endpoints.log_analysis.LogAnalysisService"
        ) as MockService, patch(
            "app.api.v1.endpoints.log_analysis.connection_manager"
        ) as mock_cm, patch(
            "app.api.v1.endpoints.log_analysis.settings"
        ) as mock_settings:
            # No hay análisis existente
            mock_svc_instance = MockService.return_value
            mock_svc_instance.get_today_analysis.return_value = None

            # Workstation online
            mock_cm.is_workstation_online.return_value = True
            mock_cm.register_command_waiter.return_value = None

            # Envío exitoso
            mock_cm.send_to_workstation = AsyncMock(return_value=True)

            # Timeout: wait_for_command_response retorna None
            mock_cm.wait_for_command_response = AsyncMock(return_value=None)

            # Settings
            mock_settings.LOG_ANALYZER_COMMAND_TIMEOUT = 30
            mock_settings.LOG_ANALYZER_MAX_UPLOAD_SIZE = 52428800

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    f"/workstations/{workstation_id}/analyze-log"
                )

        assert response.status_code == 408
        assert "timeout" in response.json()["detail"].lower()

        app.dependency_overrides.clear()


# === TEST: ANÁLISIS EXISTENTE SIN OVERWRITE (409) ===


class TestAnalisisExistenteSinOverwrite:
    """Tests para verificar respuesta 409 cuando ya existe análisis del día sin overwrite."""

    @pytest.mark.asyncio
    async def test_analyze_log_existente_sin_overwrite(
        self, admin_user, mock_db, workstation_id
    ):
        """
        WHEN ya existe un análisis del día para la workstation y no se pasa overwrite=true,
        THEN se retorna HTTP 409 indicando que ya existe un análisis.
        Validates: Requirement 2.7
        """
        app = FastAPI()
        app.include_router(router, prefix="/workstations")
        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "app.api.v1.endpoints.log_analysis.LogAnalysisService"
        ) as MockService:
            # Existe análisis previo
            mock_existing = MagicMock()
            mock_existing.id = uuid.uuid4()
            mock_svc_instance = MockService.return_value
            mock_svc_instance.get_today_analysis.return_value = mock_existing

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    f"/workstations/{workstation_id}/analyze-log"
                )

        assert response.status_code == 409
        assert "ya existe" in response.json()["detail"].lower() or "overwrite" in response.json()["detail"].lower()

        app.dependency_overrides.clear()


# === TEST: OVERWRITE EXITOSO (200) ===


class TestOverwriteExitoso:
    """Tests para verificar respuesta 200 cuando se hace overwrite exitoso."""

    @pytest.mark.asyncio
    async def test_analyze_log_overwrite_exitoso(
        self, admin_user, mock_db, workstation_id, org_id
    ):
        """
        WHEN se solicita análisis con overwrite=true y el flujo completo es exitoso,
        THEN se retorna HTTP 200 con el resultado del análisis.
        Validates: Requirement 2.8
        """
        app = FastAPI()
        app.include_router(router, prefix="/workstations")
        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        # Crear un mock de LogAnalysis con todos los campos necesarios
        mock_analysis = MagicMock()
        mock_analysis.id = uuid.uuid4()
        mock_analysis.workstation_id = workstation_id
        mock_analysis.organization_id = org_id
        mock_analysis.analysis_date = date.today()
        mock_analysis.analysis_text = "Análisis generado por LLM"
        mock_analysis.processing_path = "direct"
        mock_analysis.log_size_bytes = 5000
        mock_analysis.processing_duration_ms = 1200
        mock_analysis.original_filename = "AlwaysPrint_2025-01-15.log"
        mock_analysis.created_at = datetime.now(timezone.utc)
        mock_analysis.updated_at = datetime.now(timezone.utc)

        with patch(
            "app.api.v1.endpoints.log_analysis.LogAnalysisService"
        ) as MockService, patch(
            "app.api.v1.endpoints.log_analysis.connection_manager"
        ) as mock_cm, patch(
            "app.api.v1.endpoints.log_analysis.settings"
        ) as mock_settings:
            mock_svc_instance = MockService.return_value
            # No se verifica análisis existente cuando overwrite=true
            mock_svc_instance.get_today_analysis.return_value = None

            # Workstation online
            mock_cm.is_workstation_online.return_value = True
            mock_cm.register_command_waiter.return_value = None

            # Envío exitoso
            mock_cm.send_to_workstation = AsyncMock(return_value=True)

            # Respuesta válida de la workstation
            mock_cm.wait_for_command_response = AsyncMock(
                return_value=_make_valid_ws_response()
            )

            # Settings
            mock_settings.LOG_ANALYZER_COMMAND_TIMEOUT = 30
            mock_settings.LOG_ANALYZER_MAX_UPLOAD_SIZE = 52428800

            # process_log retorna el análisis
            mock_svc_instance.process_log = AsyncMock(return_value=mock_analysis)

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    f"/workstations/{workstation_id}/analyze-log?overwrite=true"
                )

        assert response.status_code == 200
        data = response.json()
        assert data["analysis_text"] == "Análisis generado por LLM"
        assert data["processing_path"] == "direct"

        app.dependency_overrides.clear()


# === TEST: PERMISOS - OPERADOR SOLO SU ORGANIZACIÓN (403) ===


class TestPermisosOperador:
    """Tests para verificar que un operador no puede acceder a workstations de otra organización."""

    @pytest.mark.asyncio
    async def test_operador_otra_organizacion_retorna_403(
        self, operator_user, workstation_id, other_org_id
    ):
        """
        WHEN un operador intenta analizar una workstation de otra organización,
        THEN se retorna HTTP 403 indicando que no tiene permisos.
        Validates: Requirement 2.7
        """
        # Crear workstation de OTRA organización
        ws_other_org = MagicMock(spec=Workstation)
        ws_other_org.id = workstation_id
        ws_other_org.organization_id = other_org_id  # Diferente a la del operador

        # Mock de BD que retorna la workstation de otra org
        mock_db = MagicMock()
        query_mock = MagicMock()
        filter_mock = MagicMock()
        filter_mock.first.return_value = ws_other_org
        query_mock.filter.return_value = filter_mock
        mock_db.query.return_value = query_mock

        app = FastAPI()
        app.include_router(router, prefix="/workstations")
        app.dependency_overrides[get_current_user] = lambda: operator_user
        app.dependency_overrides[get_db] = lambda: mock_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                f"/workstations/{workstation_id}/analyze-log"
            )

        assert response.status_code == 403
        assert "permisos" in response.json()["detail"].lower()

        app.dependency_overrides.clear()


# === TEST: ZIP CORRUPTO (422) ===


class TestZipCorrupto:
    """Tests para verificar respuesta 422 cuando el ZIP recibido es corrupto."""

    @pytest.mark.asyncio
    async def test_zip_corrupto_retorna_422(
        self, admin_user, mock_db, workstation_id, org_id
    ):
        """
        WHEN la workstation envía un payload con base64 inválido o ZIP corrupto,
        THEN se retorna HTTP 422 indicando error de procesamiento.
        Validates: Requirement 2.4
        """
        app = FastAPI()
        app.include_router(router, prefix="/workstations")
        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "app.api.v1.endpoints.log_analysis.LogAnalysisService"
        ) as MockService, patch(
            "app.api.v1.endpoints.log_analysis.connection_manager"
        ) as mock_cm, patch(
            "app.api.v1.endpoints.log_analysis.settings"
        ) as mock_settings:
            mock_svc_instance = MockService.return_value
            mock_svc_instance.get_today_analysis.return_value = None

            # Workstation online
            mock_cm.is_workstation_online.return_value = True
            mock_cm.register_command_waiter.return_value = None
            mock_cm.send_to_workstation = AsyncMock(return_value=True)

            # Respuesta con contenido válido base64 pero que produce ValueError en process_log
            log_content = b"contenido valido"
            content_b64 = base64.b64encode(log_content).decode("utf-8")
            mock_cm.wait_for_command_response = AsyncMock(return_value={
                "success": True,
                "output": json.dumps({
                    "filename": "AlwaysPrint_2025-01-15.log",
                    "content": content_b64,
                    "original_size": len(log_content),
                    "is_compressed": True,
                }),
            })

            # Settings
            mock_settings.LOG_ANALYZER_COMMAND_TIMEOUT = 30
            mock_settings.LOG_ANALYZER_MAX_UPLOAD_SIZE = 52428800

            # process_log lanza ValueError (ZIP corrupto)
            mock_svc_instance.process_log = AsyncMock(
                side_effect=ValueError("ZIP corrupto: no se puede descomprimir")
            )

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    f"/workstations/{workstation_id}/analyze-log"
                )

        assert response.status_code == 422
        assert "error" in response.json()["detail"].lower() or "zip" in response.json()["detail"].lower()

        app.dependency_overrides.clear()


# === TEST: UPLOAD > 50MB (413) ===


class TestUploadExcedeTamano:
    """Tests para verificar respuesta 413 cuando el upload excede el tamaño máximo."""

    @pytest.mark.asyncio
    async def test_upload_mayor_50mb_retorna_413(
        self, admin_user, mock_db, workstation_id
    ):
        """
        WHEN el payload decodificado excede el tamaño máximo (50MB),
        THEN se retorna HTTP 413 indicando que excede el límite.
        Validates: Requirement 2.8
        """
        app = FastAPI()
        app.include_router(router, prefix="/workstations")
        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        # Crear un payload grande (> 50MB) codificado en base64
        # Usamos un contenido que al decodificarse sea > 50MB
        large_content = b"X" * (52428800 + 1)  # 50MB + 1 byte
        content_b64 = base64.b64encode(large_content).decode("utf-8")

        with patch(
            "app.api.v1.endpoints.log_analysis.LogAnalysisService"
        ) as MockService, patch(
            "app.api.v1.endpoints.log_analysis.connection_manager"
        ) as mock_cm, patch(
            "app.api.v1.endpoints.log_analysis.settings"
        ) as mock_settings:
            mock_svc_instance = MockService.return_value
            mock_svc_instance.get_today_analysis.return_value = None

            # Workstation online
            mock_cm.is_workstation_online.return_value = True
            mock_cm.register_command_waiter.return_value = None
            mock_cm.send_to_workstation = AsyncMock(return_value=True)

            # Respuesta con contenido grande
            mock_cm.wait_for_command_response = AsyncMock(return_value={
                "success": True,
                "output": json.dumps({
                    "filename": "AlwaysPrint_2025-01-15.log",
                    "content": content_b64,
                    "original_size": len(large_content),
                    "is_compressed": False,
                }),
            })

            # Settings con límite de 50MB
            mock_settings.LOG_ANALYZER_COMMAND_TIMEOUT = 30
            mock_settings.LOG_ANALYZER_MAX_UPLOAD_SIZE = 52428800

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    f"/workstations/{workstation_id}/analyze-log"
                )

        assert response.status_code == 413
        assert "tamaño" in response.json()["detail"].lower() or "excede" in response.json()["detail"].lower()

        app.dependency_overrides.clear()


# === TEST: LLM ERROR → 502 ===


class TestLlmError:
    """Tests para verificar respuesta 502 cuando el servicio LLM falla."""

    @pytest.mark.asyncio
    async def test_llm_error_retorna_502(
        self, admin_user, mock_db, workstation_id, org_id
    ):
        """
        WHEN el servicio LLM falla después de todos los reintentos,
        THEN se retorna HTTP 502 indicando error del servicio de IA.
        Validates: Requirement 10.7
        """
        app = FastAPI()
        app.include_router(router, prefix="/workstations")
        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "app.api.v1.endpoints.log_analysis.LogAnalysisService"
        ) as MockService, patch(
            "app.api.v1.endpoints.log_analysis.connection_manager"
        ) as mock_cm, patch(
            "app.api.v1.endpoints.log_analysis.settings"
        ) as mock_settings:
            mock_svc_instance = MockService.return_value
            mock_svc_instance.get_today_analysis.return_value = None

            # Workstation online
            mock_cm.is_workstation_online.return_value = True
            mock_cm.register_command_waiter.return_value = None
            mock_cm.send_to_workstation = AsyncMock(return_value=True)

            # Respuesta válida de la workstation
            mock_cm.wait_for_command_response = AsyncMock(
                return_value=_make_valid_ws_response()
            )

            # Settings
            mock_settings.LOG_ANALYZER_COMMAND_TIMEOUT = 30
            mock_settings.LOG_ANALYZER_MAX_UPLOAD_SIZE = 52428800

            # process_log lanza LLMServiceError
            mock_svc_instance.process_log = AsyncMock(
                side_effect=LLMServiceError(
                    "Servicio LLM no disponible después de 3 reintentos"
                )
            )

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    f"/workstations/{workstation_id}/analyze-log"
                )

        assert response.status_code == 502
        assert "servicio" in response.json()["detail"].lower() or "ia" in response.json()["detail"].lower()

        app.dependency_overrides.clear()
