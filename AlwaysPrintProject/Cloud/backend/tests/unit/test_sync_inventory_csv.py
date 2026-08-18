"""
Tests unitarios de validación de CSV para el endpoint de sincronización de inventario.

Verifica:
- CSV con columnas faltantes → HTTP 422
- CSV vacío (sin headers) → HTTP 422
- CSV válido con todas las columnas → ejecución exitosa (200)
- CSV-step sin archivo CSV → HTTP 422

**Validates: Requirements 2.2, 8.4**
"""

import io
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.endpoints.sync_inventory import router, require_corporate_admin
from app.core.database import get_db
from app.core.security import get_current_user, require_admin
from app.models.user import User, UserRole


# === COLUMNAS REQUERIDAS DEL CSV ===

ALL_REQUIRED_COLUMNS = [
    "VLAN_CODE", "VLAN_NAME", "IP", "MODELO", "SERIE",
    "UBICACION", "DIRECCION", "DISTRITO", "PROVINCIA",
    "DEPARTAMENTO", "TIPO",
]


# === FIXTURES ===


@pytest.fixture
def corporate_admin_user():
    """Usuario admin corporativo con dominio autorizado (@robles.ai)."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = "admin@robles.ai"
    user.role = UserRole.ADMIN
    user.organization_id = None
    return user


@pytest.fixture
def mock_db():
    """Sesión de BD mock con organización existente."""
    db = MagicMock()
    mock_org = MagicMock()
    mock_org.id = str(uuid.uuid4())
    mock_org.name = "Test Org"
    db.query.return_value.filter.return_value.first.return_value = mock_org
    return db


@pytest.fixture
def org_id(mock_db):
    """ID de la organización mock para usar en los requests."""
    return mock_db.query.return_value.filter.return_value.first.return_value.id


def _build_csv_content(columns: list[str], rows: list[list[str]] = None) -> bytes:
    """
    Construye contenido CSV con las columnas indicadas y filas opcionales.

    Args:
        columns: Lista de nombres de columna para el header
        rows: Lista de filas (cada fila es una lista de valores)

    Returns:
        Contenido CSV codificado en UTF-8
    """
    lines = [",".join(columns)]
    if rows:
        for row in rows:
            lines.append(",".join(row))
    return "\n".join(lines).encode("utf-8")


# === TEST: CSV CON COLUMNAS FALTANTES → HTTP 422 ===


class TestCsvColumnasFaltantes:
    """Tests para verificar HTTP 422 cuando el CSV no tiene todas las columnas requeridas."""

    @pytest.mark.asyncio
    async def test_csv_con_solo_dos_columnas_retorna_422(
        self, corporate_admin_user, mock_db, org_id
    ):
        """
        WHEN se sube un CSV con solo VLAN_CODE y VLAN_NAME (faltan 9 columnas),
        THEN se retorna HTTP 422 con "Columnas faltantes" en el detalle.
        Validates: Requirement 8.4
        """
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: corporate_admin_user
        app.dependency_overrides[require_admin] = lambda: corporate_admin_user
        app.dependency_overrides[require_corporate_admin] = lambda: corporate_admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        # CSV con solo 2 de las 11 columnas requeridas
        csv_content = _build_csv_content(
            ["VLAN_CODE", "VLAN_NAME"],
            [["001", "VLAN Test"]],
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/admin/sync-inventory/execute",
                data={"step": "1", "dry_run": "true", "organization_id": org_id},
                files={"csv_file": ("test.csv", io.BytesIO(csv_content), "text/csv")},
                headers={"Authorization": "Bearer token_valido"},
            )

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "Columnas faltantes" in detail or "faltantes" in detail.lower()

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_csv_con_columnas_parciales_retorna_422(
        self, corporate_admin_user, mock_db, org_id
    ):
        """
        WHEN se sube un CSV con 6 de las 11 columnas requeridas,
        THEN se retorna HTTP 422 indicando las columnas que faltan.
        Validates: Requirement 8.4
        """
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: corporate_admin_user
        app.dependency_overrides[require_admin] = lambda: corporate_admin_user
        app.dependency_overrides[require_corporate_admin] = lambda: corporate_admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        # Solo 6 columnas — faltan IP, MODELO, SERIE, UBICACION, TIPO
        csv_content = _build_csv_content(
            ["VLAN_CODE", "VLAN_NAME", "DIRECCION", "DISTRITO", "PROVINCIA", "DEPARTAMENTO"],
            [["001", "VLAN Test", "Av Lima 123", "Miraflores", "Lima", "Lima"]],
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/admin/sync-inventory/execute",
                data={"step": "1", "dry_run": "true", "organization_id": org_id},
                files={"csv_file": ("inventario.csv", io.BytesIO(csv_content), "text/csv")},
                headers={"Authorization": "Bearer token_valido"},
            )

        assert response.status_code == 422
        detail = response.json()["detail"]
        # Verificar que menciona las columnas específicas que faltan
        assert "IP" in detail
        assert "MODELO" in detail
        assert "SERIE" in detail

        app.dependency_overrides.clear()


# === TEST: CSV VACÍO (SIN HEADERS) → HTTP 422 ===


class TestCsvVacio:
    """Tests para verificar HTTP 422 cuando el CSV está vacío o no tiene datos."""

    @pytest.mark.asyncio
    async def test_csv_completamente_vacio_retorna_422(
        self, corporate_admin_user, mock_db, org_id
    ):
        """
        WHEN se sube un archivo CSV completamente vacío (0 bytes),
        THEN se retorna HTTP 422 indicando que está vacío.
        Validates: Requirement 8.4
        """
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: corporate_admin_user
        app.dependency_overrides[require_admin] = lambda: corporate_admin_user
        app.dependency_overrides[require_corporate_admin] = lambda: corporate_admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/admin/sync-inventory/execute",
                data={"step": "1", "dry_run": "true", "organization_id": org_id},
                files={"csv_file": ("vacio.csv", io.BytesIO(b""), "text/csv")},
                headers={"Authorization": "Bearer token_valido"},
            )

        assert response.status_code == 422

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_csv_solo_headers_sin_filas_retorna_422(
        self, corporate_admin_user, mock_db, org_id
    ):
        """
        WHEN se sube un CSV con headers correctos pero sin filas de datos,
        THEN se retorna HTTP 422 indicando que no hay datos.
        Validates: Requirement 8.4
        """
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: corporate_admin_user
        app.dependency_overrides[require_admin] = lambda: corporate_admin_user
        app.dependency_overrides[require_corporate_admin] = lambda: corporate_admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        # CSV con todos los headers pero sin filas
        csv_content = _build_csv_content(ALL_REQUIRED_COLUMNS)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/admin/sync-inventory/execute",
                data={"step": "1", "dry_run": "true", "organization_id": org_id},
                files={"csv_file": ("headers_only.csv", io.BytesIO(csv_content), "text/csv")},
                headers={"Authorization": "Bearer token_valido"},
            )

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "no contiene filas" in detail.lower() or "vacío" in detail.lower() or "filas" in detail.lower()

        app.dependency_overrides.clear()


# === TEST: CSV VÁLIDO → EJECUCIÓN EXITOSA (200) ===


class TestCsvValido:
    """Tests para verificar que un CSV válido permite ejecución exitosa."""

    @pytest.mark.asyncio
    async def test_csv_valido_con_step1_retorna_200(
        self, corporate_admin_user, mock_db, org_id
    ):
        """
        WHEN se sube un CSV con todas las columnas requeridas y datos válidos,
        THEN el endpoint retorna HTTP 200 con resultado de ejecución.
        Validates: Requirements 2.2, 8.3
        """
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: corporate_admin_user
        app.dependency_overrides[require_admin] = lambda: corporate_admin_user
        app.dependency_overrides[require_corporate_admin] = lambda: corporate_admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        # CSV completo con 1 fila de datos
        csv_content = _build_csv_content(
            ALL_REQUIRED_COLUMNS,
            [["001", "VLAN Agencia Lima", "10.0.0.1", "HP LaserJet", "SN12345",
              "Piso 3", "Av Javier Prado 123", "San Isidro", "Lima", "Lima", "Laser"]],
        )

        # Mock de step1_sync_vlans para evitar operaciones reales de BD
        with patch(
            "app.api.v1.endpoints.sync_inventory.step1_sync_vlans"
        ) as mock_step1:
            mock_step1.return_value = {"001": str(uuid.uuid4())}

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/admin/sync-inventory/execute",
                    data={"step": "1", "dry_run": "true", "organization_id": org_id},
                    files={"csv_file": ("inventario.csv", io.BytesIO(csv_content), "text/csv")},
                    headers={"Authorization": "Bearer token_valido"},
                )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["dry_run"] is True
        assert len(data["steps_executed"]) == 1
        assert data["steps_executed"][0]["step"] == 1
        assert data["steps_executed"][0]["success"] is True

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_csv_valido_con_multiples_filas_retorna_200(
        self, corporate_admin_user, mock_db, org_id
    ):
        """
        WHEN se sube un CSV con múltiples filas de datos válidos,
        THEN el endpoint procesa correctamente y retorna 200.
        Validates: Requirements 2.2, 8.3
        """
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: corporate_admin_user
        app.dependency_overrides[require_admin] = lambda: corporate_admin_user
        app.dependency_overrides[require_corporate_admin] = lambda: corporate_admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        # CSV con 3 filas de datos
        csv_content = _build_csv_content(
            ALL_REQUIRED_COLUMNS,
            [
                ["001", "VLAN Lima", "10.0.0.1", "HP", "SN001", "Piso 1", "Av 1", "Dist1", "Prov1", "Dept1", "Laser"],
                ["002", "VLAN Cusco", "10.0.1.1", "Lexmark", "SN002", "Piso 2", "Av 2", "Dist2", "Prov2", "Dept2", "Inkjet"],
                ["001", "VLAN Lima", "10.0.0.2", "Canon", "SN003", "Piso 3", "Av 1", "Dist1", "Prov1", "Dept1", "Laser"],
            ],
        )

        with patch(
            "app.api.v1.endpoints.sync_inventory.step1_sync_vlans"
        ) as mock_step1:
            mock_step1.return_value = {"001": str(uuid.uuid4()), "002": str(uuid.uuid4())}

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/admin/sync-inventory/execute",
                    data={"step": "1", "dry_run": "true", "organization_id": org_id},
                    files={"csv_file": ("multi_row.csv", io.BytesIO(csv_content), "text/csv")},
                    headers={"Authorization": "Bearer token_valido"},
                )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        app.dependency_overrides.clear()


# === TEST: CSV-STEP SIN ARCHIVO CSV → HTTP 422 ===


class TestCsvStepSinArchivo:
    """Tests para verificar HTTP 422 cuando un CSV_Step se ejecuta sin archivo CSV."""

    @pytest.mark.asyncio
    async def test_step1_sin_csv_retorna_422(
        self, corporate_admin_user, mock_db, org_id
    ):
        """
        WHEN se ejecuta el paso 1 (CSV_Step) sin proporcionar un archivo CSV,
        THEN se retorna HTTP 422 indicando que el CSV es requerido.
        Validates: Requirement 2.5
        """
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: corporate_admin_user
        app.dependency_overrides[require_admin] = lambda: corporate_admin_user
        app.dependency_overrides[require_corporate_admin] = lambda: corporate_admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/admin/sync-inventory/execute",
                data={"step": "1", "dry_run": "true", "organization_id": org_id},
                headers={"Authorization": "Bearer token_valido"},
            )

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "requerido" in detail.lower()

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_step2_sin_csv_retorna_422(
        self, corporate_admin_user, mock_db, org_id
    ):
        """
        WHEN se ejecuta el paso 2 (CSV_Step) sin proporcionar un archivo CSV,
        THEN se retorna HTTP 422 indicando que el CSV es requerido.
        Validates: Requirement 2.5
        """
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: corporate_admin_user
        app.dependency_overrides[require_admin] = lambda: corporate_admin_user
        app.dependency_overrides[require_corporate_admin] = lambda: corporate_admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/admin/sync-inventory/execute",
                data={"step": "2", "dry_run": "true", "organization_id": org_id},
                headers={"Authorization": "Bearer token_valido"},
            )

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "requerido" in detail.lower()

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_step3_sin_csv_retorna_422(
        self, corporate_admin_user, mock_db, org_id
    ):
        """
        WHEN se ejecuta el paso 3 (CSV_Step) sin proporcionar un archivo CSV,
        THEN se retorna HTTP 422 indicando que el CSV es requerido.
        Validates: Requirement 2.5
        """
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: corporate_admin_user
        app.dependency_overrides[require_admin] = lambda: corporate_admin_user
        app.dependency_overrides[require_corporate_admin] = lambda: corporate_admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/admin/sync-inventory/execute",
                data={"step": "3", "dry_run": "true", "organization_id": org_id},
                headers={"Authorization": "Bearer token_valido"},
            )

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "requerido" in detail.lower()

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_step7_run_all_sin_csv_retorna_422(
        self, corporate_admin_user, mock_db, org_id
    ):
        """
        WHEN se ejecuta "Run All" (step=7) sin proporcionar un archivo CSV,
        THEN se retorna HTTP 422 porque steps 1-3 requieren CSV.
        Validates: Requirement 4.4
        """
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: corporate_admin_user
        app.dependency_overrides[require_admin] = lambda: corporate_admin_user
        app.dependency_overrides[require_corporate_admin] = lambda: corporate_admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/admin/sync-inventory/execute",
                data={"step": "7", "dry_run": "true", "organization_id": org_id},
                headers={"Authorization": "Bearer token_valido"},
            )

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "requerido" in detail.lower()

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_step4_db_step_sin_csv_retorna_200(
        self, corporate_admin_user, mock_db, org_id
    ):
        """
        WHEN se ejecuta el paso 4 (DB_Step) sin proporcionar un archivo CSV,
        THEN se ejecuta correctamente porque los DB_Steps no requieren CSV.
        Validates: Requirement 3.5
        """
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: corporate_admin_user
        app.dependency_overrides[require_admin] = lambda: corporate_admin_user
        app.dependency_overrides[require_corporate_admin] = lambda: corporate_admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        # Mock de step4 para evitar operaciones reales de BD
        with patch(
            "app.api.v1.endpoints.sync_inventory.step4_assign_orphan_devices"
        ) as mock_step4:
            mock_step4.return_value = None

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/admin/sync-inventory/execute",
                    data={"step": "4", "dry_run": "true", "organization_id": org_id},
                    headers={"Authorization": "Bearer token_valido"},
                )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["steps_executed"][0]["step"] == 4

        app.dependency_overrides.clear()
