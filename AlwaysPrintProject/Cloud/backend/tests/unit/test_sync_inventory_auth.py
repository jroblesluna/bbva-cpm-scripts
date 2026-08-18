"""
Tests unitarios de autenticación/autorización del endpoint de sincronización de inventario.

Verifica:
- Admin con email @robles.ai → acceso permitido (no 403)
- Admin con email @sistemas.com.pe → acceso permitido (no 403)
- Admin con email de otro dominio → HTTP 403
- Usuario no-admin (operador) → HTTP 403

**Validates: Requirements 1.3, 1.4**
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.endpoints.sync_inventory import router, require_corporate_admin
from app.core.database import get_db
from app.core.security import get_current_user, require_admin
from app.models.user import User, UserRole


# === FIXTURES ===


@pytest.fixture
def mock_db():
    """Sesión de BD mock con query que retorna una organización válida."""
    db = MagicMock()
    # Simular que la organización existe
    mock_org = MagicMock()
    mock_org.id = str(uuid.uuid4())
    db.query.return_value.filter.return_value.first.return_value = mock_org
    return db


@pytest.fixture
def admin_robles():
    """Usuario admin con dominio @robles.ai."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = "antonio@robles.ai"
    user.role = UserRole.ADMIN
    user.organization_id = None
    return user


@pytest.fixture
def admin_sistemas():
    """Usuario admin con dominio @sistemas.com.pe."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = "admin@sistemas.com.pe"
    user.role = UserRole.ADMIN
    user.organization_id = None
    return user


@pytest.fixture
def admin_otro_dominio():
    """Usuario admin con dominio no autorizado."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = "admin@other.com"
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
def org_id():
    """UUID de organización para los requests."""
    return str(uuid.uuid4())


# === TEST: ADMIN CON DOMINIO @robles.ai → ACCESO PERMITIDO ===


class TestAdminRoblesPermitido:
    """Tests para verificar acceso de admin con email @robles.ai."""

    @pytest.mark.asyncio
    async def test_admin_robles_no_recibe_403(self, admin_robles, mock_db, org_id):
        """
        WHEN un admin con email @robles.ai ejecuta un paso de sincronización,
        THEN no se retorna HTTP 403 (la autorización corporativa pasa).
        Validates: Requirement 1.4
        """
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: admin_robles
        app.dependency_overrides[get_db] = lambda: mock_db

        # Usar step=4 (DB_Step) para no requerir CSV
        with patch(
            "app.api.v1.endpoints.sync_inventory.step4_assign_orphan_devices"
        ) as mock_step4:
            mock_step4.return_value = None

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/admin/sync-inventory/execute",
                    data={
                        "step": "4",
                        "dry_run": "true",
                        "organization_id": org_id,
                    },
                    headers={"Authorization": "Bearer token_valido"},
                )

        # No debe ser 403 — la autorización por dominio pasa
        assert response.status_code != 403
        assert response.status_code == 200

        app.dependency_overrides.clear()


# === TEST: ADMIN CON DOMINIO @sistemas.com.pe → ACCESO PERMITIDO ===


class TestAdminSistemasPermitido:
    """Tests para verificar acceso de admin con email @sistemas.com.pe."""

    @pytest.mark.asyncio
    async def test_admin_sistemas_no_recibe_403(self, admin_sistemas, mock_db, org_id):
        """
        WHEN un admin con email @sistemas.com.pe ejecuta un paso de sincronización,
        THEN no se retorna HTTP 403 (la autorización corporativa pasa).
        Validates: Requirement 1.4
        """
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: admin_sistemas
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "app.api.v1.endpoints.sync_inventory.step4_assign_orphan_devices"
        ) as mock_step4:
            mock_step4.return_value = None

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/admin/sync-inventory/execute",
                    data={
                        "step": "4",
                        "dry_run": "true",
                        "organization_id": org_id,
                    },
                    headers={"Authorization": "Bearer token_valido"},
                )

        assert response.status_code != 403
        assert response.status_code == 200

        app.dependency_overrides.clear()


# === TEST: ADMIN CON DOMINIO NO AUTORIZADO → HTTP 403 ===


class TestAdminDominioNoAutorizado:
    """Tests para verificar HTTP 403 cuando el admin tiene un dominio no permitido."""

    @pytest.mark.asyncio
    async def test_admin_otro_dominio_retorna_403(self, admin_otro_dominio, mock_db, org_id):
        """
        WHEN un admin con email de dominio no autorizado intenta ejecutar sincronización,
        THEN se retorna HTTP 403 Forbidden.
        Validates: Requirements 1.3, 1.4
        """
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: admin_otro_dominio
        app.dependency_overrides[get_db] = lambda: mock_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/admin/sync-inventory/execute",
                data={
                    "step": "4",
                    "dry_run": "true",
                    "organization_id": org_id,
                },
                headers={"Authorization": "Bearer token_valido"},
            )

        assert response.status_code == 403
        assert "corporativos" in response.json()["detail"].lower()

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_admin_gmail_retorna_403(self, mock_db, org_id):
        """
        WHEN un admin con email @gmail.com intenta ejecutar sincronización,
        THEN se retorna HTTP 403 Forbidden.
        Validates: Requirement 1.3
        """
        user = MagicMock(spec=User)
        user.id = uuid.uuid4()
        user.email = "admin@gmail.com"
        user.role = UserRole.ADMIN
        user.organization_id = None

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: mock_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/admin/sync-inventory/execute",
                data={
                    "step": "4",
                    "dry_run": "true",
                    "organization_id": org_id,
                },
                headers={"Authorization": "Bearer token_valido"},
            )

        assert response.status_code == 403

        app.dependency_overrides.clear()


# === TEST: USUARIO NO-ADMIN → HTTP 403 ===


class TestUsuarioNoAdmin:
    """Tests para verificar HTTP 403 cuando el usuario no es admin."""

    @pytest.mark.asyncio
    async def test_operador_retorna_403(self, operator_user, mock_db, org_id):
        """
        WHEN un usuario operador intenta ejecutar sincronización de inventario,
        THEN se retorna HTTP 403 Forbidden (por no ser admin).
        Validates: Requirement 1.3
        """
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: operator_user
        app.dependency_overrides[get_db] = lambda: mock_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/admin/sync-inventory/execute",
                data={
                    "step": "4",
                    "dry_run": "true",
                    "organization_id": org_id,
                },
                headers={"Authorization": "Bearer token_valido"},
            )

        assert response.status_code == 403
        assert "administrador" in response.json()["detail"].lower()

        app.dependency_overrides.clear()
