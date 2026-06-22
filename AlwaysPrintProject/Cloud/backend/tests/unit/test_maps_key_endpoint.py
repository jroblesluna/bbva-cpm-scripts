"""
Tests unitarios del endpoint GET /api/v1/config/maps-key.

Verifica:
- Admin sin organization_id → HTTP 400
- Operador sin organización asignada → HTTP 403
- Organización no encontrada → HTTP 404
- Organización sin API Key → HTTP 404
- Admin con key configurada → HTTP 200 con key completa
- Operador con key configurada → HTTP 200 con key completa

**Validates: Requirements 7.3, 7.4**
"""

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.endpoints.config import router
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.organization import Organization
from app.models.user import User, UserRole


# === FIXTURES ===


@pytest.fixture
def admin_user():
    """Usuario admin sin organización asignada."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = "admin@system.com"
    user.role = UserRole.ADMIN
    user.organization_id = None
    return user


@pytest.fixture
def operator_user():
    """Usuario operador con organización asignada."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = "operator@bbva.com"
    user.role = UserRole.OPERATOR
    user.organization_id = uuid.uuid4()
    return user


@pytest.fixture
def operator_without_org():
    """Usuario operador SIN organización asignada."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = "operator@unassigned.com"
    user.role = UserRole.OPERATOR
    user.organization_id = None
    return user


@pytest.fixture
def org_with_key():
    """Organización con API Key de Google Maps configurada."""
    org = MagicMock(spec=Organization)
    org.id = uuid.uuid4()
    org.name = "BBVA"
    org.google_maps_api_key = "AIzaSyB1234567890abcdefghijklmnopqrstuv"
    return org


@pytest.fixture
def org_without_key():
    """Organización SIN API Key de Google Maps configurada."""
    org = MagicMock(spec=Organization)
    org.id = uuid.uuid4()
    org.name = "Ripley"
    org.google_maps_api_key = None
    return org


def _mock_db_with_org(org):
    """Crea un mock de sesión de BD que retorna la organización dada."""
    db = MagicMock()
    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query
    query.first.return_value = org
    return db


def _mock_db_no_org():
    """Crea un mock de sesión de BD que no encuentra la organización."""
    db = MagicMock()
    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query
    query.first.return_value = None
    return db


# === TEST: ADMIN SIN ORGANIZATION_ID → HTTP 400 ===


class TestAdminSinOrganizationId:
    """Tests para admin que no pasa organization_id."""

    @pytest.mark.asyncio
    async def test_admin_sin_org_id_retorna_400(self, admin_user):
        """
        WHEN un admin hace GET /config/maps-key sin ?organization_id,
        THEN se retorna HTTP 400 indicando que es requerido.
        Validates: Requirement 7.3
        """
        app = FastAPI()
        app.include_router(router, prefix="/config")
        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: MagicMock()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/config/maps-key")

        assert response.status_code == 400
        assert "organization_id" in response.json()["detail"]

        app.dependency_overrides.clear()


# === TEST: OPERADOR SIN ORGANIZACIÓN → HTTP 403 ===


class TestOperadorSinOrganizacion:
    """Tests para operador sin organización asignada."""

    @pytest.mark.asyncio
    async def test_operador_sin_org_retorna_403(self, operator_without_org):
        """
        WHEN un operador sin organización asignada hace GET /config/maps-key,
        THEN se retorna HTTP 403.
        Validates: Requirement 7.3
        """
        app = FastAPI()
        app.include_router(router, prefix="/config")
        app.dependency_overrides[get_current_user] = lambda: operator_without_org
        app.dependency_overrides[get_db] = lambda: MagicMock()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/config/maps-key")

        assert response.status_code == 403

        app.dependency_overrides.clear()


# === TEST: ORGANIZACIÓN NO ENCONTRADA → HTTP 404 ===


class TestOrganizacionNoEncontrada:
    """Tests cuando la organización no existe en BD."""

    @pytest.mark.asyncio
    async def test_admin_org_inexistente_retorna_404(self, admin_user):
        """
        WHEN un admin consulta maps-key de una org que no existe,
        THEN se retorna HTTP 404.
        Validates: Requirement 7.3
        """
        app = FastAPI()
        app.include_router(router, prefix="/config")
        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: _mock_db_no_org()

        org_id = str(uuid.uuid4())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/config/maps-key?organization_id={org_id}")

        assert response.status_code == 404
        assert "no encontrada" in response.json()["detail"].lower()

        app.dependency_overrides.clear()


# === TEST: ORGANIZACIÓN SIN API KEY → HTTP 404 ===


class TestOrganizacionSinApiKey:
    """Tests cuando la organización no tiene API Key configurada."""

    @pytest.mark.asyncio
    async def test_org_sin_key_retorna_404(self, operator_user, org_without_key):
        """
        WHEN la organización del operador no tiene google_maps_api_key,
        THEN se retorna HTTP 404 con mensaje descriptivo.
        Validates: Requirement 7.3
        """
        app = FastAPI()
        app.include_router(router, prefix="/config")
        app.dependency_overrides[get_current_user] = lambda: operator_user
        app.dependency_overrides[get_db] = lambda: _mock_db_with_org(org_without_key)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/config/maps-key")

        assert response.status_code == 404
        assert "no configurada" in response.json()["detail"].lower()

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_org_con_key_vacia_retorna_404(self, operator_user):
        """
        WHEN la organización tiene google_maps_api_key como string vacío,
        THEN se retorna HTTP 404 (se trata como no configurada).
        Validates: Requirement 7.3
        """
        org = MagicMock(spec=Organization)
        org.id = uuid.uuid4()
        org.google_maps_api_key = ""

        app = FastAPI()
        app.include_router(router, prefix="/config")
        app.dependency_overrides[get_current_user] = lambda: operator_user
        app.dependency_overrides[get_db] = lambda: _mock_db_with_org(org)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/config/maps-key")

        assert response.status_code == 404

        app.dependency_overrides.clear()


# === TEST: OPERADOR CON KEY CONFIGURADA → HTTP 200 ===


class TestOperadorConKey:
    """Tests para operador autenticado con key configurada."""

    @pytest.mark.asyncio
    async def test_operador_retorna_key_completa(self, operator_user, org_with_key):
        """
        WHEN un operador con organización asignada consulta maps-key,
        AND la organización tiene google_maps_api_key configurada,
        THEN se retorna HTTP 200 con la key completa (sin enmascarar).
        Validates: Requirements 7.3, 7.4
        """
        app = FastAPI()
        app.include_router(router, prefix="/config")
        app.dependency_overrides[get_current_user] = lambda: operator_user
        app.dependency_overrides[get_db] = lambda: _mock_db_with_org(org_with_key)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/config/maps-key")

        assert response.status_code == 200
        data = response.json()
        assert "api_key" in data
        # La key se retorna completa (sin enmascarar) para uso del SDK
        assert data["api_key"] == org_with_key.google_maps_api_key

        app.dependency_overrides.clear()


# === TEST: ADMIN CON KEY CONFIGURADA → HTTP 200 ===


class TestAdminConKey:
    """Tests para admin autenticado con key configurada."""

    @pytest.mark.asyncio
    async def test_admin_con_org_id_retorna_key_completa(self, admin_user, org_with_key):
        """
        WHEN un admin pasa ?organization_id válido con key configurada,
        THEN se retorna HTTP 200 con la key completa.
        Validates: Requirements 7.3, 7.4
        """
        app = FastAPI()
        app.include_router(router, prefix="/config")
        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: _mock_db_with_org(org_with_key)

        org_id = str(uuid.uuid4())
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/config/maps-key?organization_id={org_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["api_key"] == org_with_key.google_maps_api_key

        app.dependency_overrides.clear()
