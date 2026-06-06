"""
Tests unitarios de autenticación/autorización del endpoint de métricas de escalabilidad.

Verifica:
- Token inválido → HTTP 401
- Token válido no-admin → HTTP 403
- Token válido admin → HTTP 200

**Validates: Requirements 1.2, 1.3**
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.endpoints.system_metrics import router
from app.core.database import get_db
from app.core.security import get_current_user, require_admin
from app.models.user import User, UserRole
from app.schemas.scalability_metrics import ScalabilityMetricsResponse


# === FIXTURES ===


@pytest.fixture
def admin_user():
    """Usuario admin con acceso global."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = "admin@system.com"
    user.role = UserRole.ADMIN
    user.organization_id = None
    return user


@pytest.fixture
def operator_user():
    """Usuario operador sin permisos de admin."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = "operator@bbva.com"
    user.role = UserRole.OPERATOR
    user.organization_id = uuid.uuid4()
    return user


@pytest.fixture
def readonly_user():
    """Usuario readonly sin permisos de admin."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = "readonly@bbva.com"
    user.role = UserRole.READONLY
    user.organization_id = uuid.uuid4()
    return user


@pytest.fixture
def mock_db():
    """Sesión de BD mock."""
    return MagicMock()


@pytest.fixture
def mock_metrics_response():
    """Respuesta de métricas mockeada para tests exitosos."""
    return ScalabilityMetricsResponse(
        websocket=None,
        python_memory=None,
        file_descriptors=None,
        network=None,
        db_pool=None,
        collected_at=datetime.now(timezone.utc),
    )


# === TEST: TOKEN INVÁLIDO → HTTP 401 ===


class TestTokenInvalido:
    """Tests para verificar HTTP 401 cuando el token es inválido."""

    @pytest.mark.asyncio
    async def test_sin_token_retorna_401(self):
        """
        WHEN se realiza petición sin token de autenticación,
        THEN se retorna HTTP 401/403.
        Validates: Requirement 1.2
        """
        app = FastAPI()
        app.include_router(router, prefix="/system")

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/system/metrics")

        # Sin token, FastAPI retorna 403 (HTTPBearer scheme)
        assert response.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_token_invalido_retorna_401(self, mock_db):
        """
        WHEN se presenta un token JWT inválido/malformado,
        THEN se retorna HTTP 401 Unauthorized.
        Validates: Requirement 1.2
        """
        app = FastAPI()
        app.include_router(router, prefix="/system")
        # No sobreescribimos get_current_user, dejamos la lógica real de seguridad
        app.dependency_overrides[get_db] = lambda: mock_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/system/metrics",
                headers={"Authorization": "Bearer token.invalido.xyz"},
            )

        assert response.status_code == 401

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_token_expirado_retorna_401(self, mock_db):
        """
        WHEN se presenta un token JWT expirado,
        THEN se retorna HTTP 401 Unauthorized.
        Validates: Requirement 1.2
        """
        from datetime import timedelta
        from app.core.security import create_access_token

        # Crear token ya expirado
        token = create_access_token(
            data={"sub": str(uuid.uuid4())},
            expires_delta=timedelta(minutes=-1),
        )

        app = FastAPI()
        app.include_router(router, prefix="/system")
        app.dependency_overrides[get_db] = lambda: mock_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/system/metrics",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 401

        app.dependency_overrides.clear()


# === TEST: TOKEN VÁLIDO NO-ADMIN → HTTP 403 ===


class TestTokenNoAdmin:
    """Tests para verificar HTTP 403 cuando el usuario no es admin."""

    @pytest.mark.asyncio
    async def test_operador_retorna_403(self, operator_user, mock_db):
        """
        WHEN un usuario autenticado con rol operador accede al endpoint,
        THEN se retorna HTTP 403 Forbidden.
        Validates: Requirement 1.3
        """
        app = FastAPI()
        app.include_router(router, prefix="/system")
        app.dependency_overrides[get_current_user] = lambda: operator_user
        app.dependency_overrides[get_db] = lambda: mock_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/system/metrics",
                headers={"Authorization": "Bearer token_valido"},
            )

        assert response.status_code == 403
        assert "administrador" in response.json()["detail"].lower()

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_readonly_retorna_403(self, readonly_user, mock_db):
        """
        WHEN un usuario autenticado con rol readonly accede al endpoint,
        THEN se retorna HTTP 403 Forbidden.
        Validates: Requirement 1.3
        """
        app = FastAPI()
        app.include_router(router, prefix="/system")
        app.dependency_overrides[get_current_user] = lambda: readonly_user
        app.dependency_overrides[get_db] = lambda: mock_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/system/metrics",
                headers={"Authorization": "Bearer token_valido"},
            )

        assert response.status_code == 403
        assert "administrador" in response.json()["detail"].lower()

        app.dependency_overrides.clear()


# === TEST: TOKEN VÁLIDO ADMIN → HTTP 200 ===


class TestTokenAdminValido:
    """Tests para verificar HTTP 200 cuando el usuario es admin autenticado."""

    @pytest.mark.asyncio
    async def test_admin_retorna_200(
        self, admin_user, mock_db, mock_metrics_response
    ):
        """
        WHEN un usuario autenticado con rol admin accede al endpoint,
        THEN se retorna HTTP 200 con las métricas de escalabilidad.
        Validates: Requirements 1.2, 1.3
        """
        app = FastAPI()
        app.include_router(router, prefix="/system")
        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "app.api.v1.endpoints.system_metrics.scalability_collector"
        ) as mock_collector:
            mock_collector.collect_all_metrics = AsyncMock(
                return_value=mock_metrics_response
            )

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(
                    "/system/metrics",
                    headers={"Authorization": "Bearer token_valido"},
                )

        assert response.status_code == 200
        data = response.json()
        # Verificar estructura de la respuesta
        assert "collected_at" in data
        assert "websocket" in data
        assert "python_memory" in data
        assert "file_descriptors" in data
        assert "network" in data
        assert "db_pool" in data

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_admin_respuesta_contiene_collected_at_valido(
        self, admin_user, mock_db, mock_metrics_response
    ):
        """
        WHEN un admin consulta las métricas,
        THEN la respuesta incluye un timestamp collected_at válido.
        Validates: Requirement 1.1
        """
        app = FastAPI()
        app.include_router(router, prefix="/system")
        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "app.api.v1.endpoints.system_metrics.scalability_collector"
        ) as mock_collector:
            mock_collector.collect_all_metrics = AsyncMock(
                return_value=mock_metrics_response
            )

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(
                    "/system/metrics",
                    headers={"Authorization": "Bearer token_valido"},
                )

        assert response.status_code == 200
        data = response.json()
        # Verificar que collected_at es un string ISO parseable
        collected_at = datetime.fromisoformat(data["collected_at"])
        assert collected_at is not None

        app.dependency_overrides.clear()
