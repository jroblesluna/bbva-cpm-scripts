"""
Tests unitarios de ejecución de pasos del endpoint de sincronización de inventario.

Verifica:
- Ejecución individual de un paso (solo ese paso se ejecuta)
- Captura correcta de stdout
- "Run All" (step=7) ejecuta los 6 pasos secuencialmente
- Rollback ante fallo de un paso y detención de ejecución

**Validates: Requirements 3.2, 4.2, 4.3, 8.3, 8.5**
"""

import io
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.endpoints.sync_inventory import router, require_corporate_admin
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User, UserRole


# === FIXTURES ===


@pytest.fixture
def corporate_admin_user():
    """Usuario admin con email de dominio corporativo autorizado."""
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
    mock_org.id = "test-org-id"
    db.query.return_value.filter.return_value.first.return_value = mock_org
    return db


@pytest.fixture
def valid_csv_content():
    """Contenido CSV válido con todas las columnas requeridas."""
    return (
        "VLAN_CODE,VLAN_NAME,IP,MODELO,SERIE,UBICACION,DIRECCION,DISTRITO,PROVINCIA,DEPARTAMENTO,TIPO\n"
        "001,Test VLAN,10.0.0.1,HP LaserJet,SN123,Oficina,Av Principal,Miraflores,Lima,Lima,Laser\n"
    )


@pytest.fixture
def valid_csv_file(valid_csv_content):
    """Archivo CSV válido como tupla (nombre, contenido, content_type) para httpx."""
    return ("csv_file", ("inventory.csv", io.BytesIO(valid_csv_content.encode("utf-8")), "text/csv"))


@pytest.fixture
def test_org_id():
    """ID de organización para los tests."""
    return str(uuid.uuid4())


# === TEST: EJECUCIÓN INDIVIDUAL DE UN PASO ===


class TestEjecucionPasoIndividual:
    """Tests para verificar que solo el paso solicitado se ejecuta."""

    @pytest.mark.asyncio
    @patch("app.api.v1.endpoints.sync_inventory.step6_cleanup_vlan_cidrs")
    @patch("app.api.v1.endpoints.sync_inventory.step5_delete_empty_vlans")
    @patch("app.api.v1.endpoints.sync_inventory.step4_assign_orphan_devices")
    @patch("app.api.v1.endpoints.sync_inventory.step3_upsert_devices")
    @patch("app.api.v1.endpoints.sync_inventory.step2_reassign_workstations")
    @patch("app.api.v1.endpoints.sync_inventory.step1_sync_vlans")
    async def test_step4_solo_ejecuta_step4(
        self,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_step4,
        mock_step5,
        mock_step6,
        corporate_admin_user,
        mock_db,
        test_org_id,
    ):
        """
        WHEN se solicita ejecutar solo el paso 4 (DB step),
        THEN solo step4 se ejecuta y los demás no se invocan.
        Validates: Requirement 3.2
        """
        # Configurar mock: step4 imprime algo a stdout
        mock_step4.side_effect = lambda *args, **kwargs: print("Paso 4 ejecutado correctamente")

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        app.dependency_overrides[get_current_user] = lambda: corporate_admin_user
        app.dependency_overrides[require_corporate_admin] = lambda: corporate_admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/admin/sync-inventory/execute",
                data={
                    "step": "4",
                    "dry_run": "true",
                    "organization_id": test_org_id,
                },
            )

        assert response.status_code == 200
        data = response.json()

        # Verificar que step4 fue invocado exactamente una vez
        mock_step4.assert_called_once()

        # Verificar que los demás pasos NO fueron invocados
        mock_step1.assert_not_called()
        mock_step2.assert_not_called()
        mock_step3.assert_not_called()
        mock_step5.assert_not_called()
        mock_step6.assert_not_called()

        # Verificar que la respuesta contiene un solo StepResult
        assert len(data["steps_executed"]) == 1
        assert data["steps_executed"][0]["step"] == 4
        assert data["steps_executed"][0]["success"] is True

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    @patch("app.api.v1.endpoints.sync_inventory.step6_cleanup_vlan_cidrs")
    @patch("app.api.v1.endpoints.sync_inventory.step5_delete_empty_vlans")
    @patch("app.api.v1.endpoints.sync_inventory.step4_assign_orphan_devices")
    @patch("app.api.v1.endpoints.sync_inventory.step3_upsert_devices")
    @patch("app.api.v1.endpoints.sync_inventory.step2_reassign_workstations")
    @patch("app.api.v1.endpoints.sync_inventory.step1_sync_vlans")
    async def test_step5_solo_ejecuta_step5(
        self,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_step4,
        mock_step5,
        mock_step6,
        corporate_admin_user,
        mock_db,
        test_org_id,
    ):
        """
        WHEN se solicita ejecutar solo el paso 5 (DB step),
        THEN solo step5 se ejecuta y los demás no se invocan.
        Validates: Requirement 3.2
        """
        mock_step5.side_effect = lambda *args, **kwargs: print("Paso 5: sin VLANs vacías")

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        app.dependency_overrides[get_current_user] = lambda: corporate_admin_user
        app.dependency_overrides[require_corporate_admin] = lambda: corporate_admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/admin/sync-inventory/execute",
                data={
                    "step": "5",
                    "dry_run": "true",
                    "organization_id": test_org_id,
                },
            )

        assert response.status_code == 200

        mock_step5.assert_called_once()
        mock_step1.assert_not_called()
        mock_step2.assert_not_called()
        mock_step3.assert_not_called()
        mock_step4.assert_not_called()
        mock_step6.assert_not_called()

        app.dependency_overrides.clear()


# === TEST: CAPTURA DE STDOUT ===


class TestCapturaStdout:
    """Tests para verificar que stdout se captura correctamente en el output."""

    @pytest.mark.asyncio
    @patch("app.api.v1.endpoints.sync_inventory.step4_assign_orphan_devices")
    async def test_stdout_capturado_en_output(
        self,
        mock_step4,
        corporate_admin_user,
        mock_db,
        test_org_id,
    ):
        """
        WHEN una función de paso imprime texto a stdout,
        THEN el output capturado aparece en steps_executed[0].output.
        Validates: Requirement 8.3
        """
        # El step imprime varias líneas a stdout
        def step4_con_output(*args, **kwargs):
            print("=== Asignando devices huérfanos ===")
            print("  Device 10.0.0.5 → VLAN 001")
            print("  Device 10.0.1.3 → VLAN 002")
            print("Total: 2 devices asignados")

        mock_step4.side_effect = step4_con_output

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        app.dependency_overrides[get_current_user] = lambda: corporate_admin_user
        app.dependency_overrides[require_corporate_admin] = lambda: corporate_admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/admin/sync-inventory/execute",
                data={
                    "step": "4",
                    "dry_run": "true",
                    "organization_id": test_org_id,
                },
            )

        assert response.status_code == 200
        data = response.json()

        step_output = data["steps_executed"][0]["output"]
        assert "=== Asignando devices huérfanos ===" in step_output
        assert "Device 10.0.0.5 → VLAN 001" in step_output
        assert "Device 10.0.1.3 → VLAN 002" in step_output
        assert "Total: 2 devices asignados" in step_output

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    @patch("app.api.v1.endpoints.sync_inventory.step6_cleanup_vlan_cidrs")
    async def test_stdout_multilínea_preservado(
        self,
        mock_step6,
        corporate_admin_user,
        mock_db,
        test_org_id,
    ):
        """
        WHEN un step imprime múltiples líneas con formato,
        THEN todas las líneas se preservan en el output.
        Validates: Requirement 8.3
        """
        def step6_con_output(*args, **kwargs):
            print("[DRY-RUN] VLAN 001 - Limpieza de CIDRs")
            print("  Eliminando CIDR redundante: 10.0.0.0/24")
            print("[DRY-RUN] Sin cambios reales aplicados")

        mock_step6.side_effect = step6_con_output

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        app.dependency_overrides[get_current_user] = lambda: corporate_admin_user
        app.dependency_overrides[require_corporate_admin] = lambda: corporate_admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/admin/sync-inventory/execute",
                data={
                    "step": "6",
                    "dry_run": "true",
                    "organization_id": test_org_id,
                },
            )

        assert response.status_code == 200
        data = response.json()

        step_output = data["steps_executed"][0]["output"]
        assert "[DRY-RUN] VLAN 001 - Limpieza de CIDRs" in step_output
        assert "Eliminando CIDR redundante: 10.0.0.0/24" in step_output
        assert "[DRY-RUN] Sin cambios reales aplicados" in step_output

        app.dependency_overrides.clear()


# === TEST: RUN ALL (STEP=7) EJECUTA TODOS LOS PASOS ===


class TestRunAll:
    """Tests para verificar que step=7 ejecuta los 6 pasos secuencialmente."""

    @pytest.mark.asyncio
    @patch("app.api.v1.endpoints.sync_inventory.step6_cleanup_vlan_cidrs")
    @patch("app.api.v1.endpoints.sync_inventory.step5_delete_empty_vlans")
    @patch("app.api.v1.endpoints.sync_inventory.step4_assign_orphan_devices")
    @patch("app.api.v1.endpoints.sync_inventory.step3_upsert_devices")
    @patch("app.api.v1.endpoints.sync_inventory.step2_reassign_workstations")
    @patch("app.api.v1.endpoints.sync_inventory.step1_sync_vlans")
    async def test_run_all_ejecuta_6_pasos(
        self,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_step4,
        mock_step5,
        mock_step6,
        corporate_admin_user,
        mock_db,
        test_org_id,
        valid_csv_content,
    ):
        """
        WHEN se ejecuta step=7 (Run All) con un CSV válido,
        THEN se ejecutan los 6 pasos en orden secuencial.
        Validates: Requirement 4.2
        """
        # Configurar mocks: step1 retorna code_to_id, los demás solo imprimen
        mock_step1.side_effect = lambda *args, **kwargs: (
            print("Step 1 ejecutado") or {"001": "vlan-id-1"}
        )
        mock_step2.side_effect = lambda *args, **kwargs: print("Step 2 ejecutado")
        mock_step3.side_effect = lambda *args, **kwargs: print("Step 3 ejecutado")
        mock_step4.side_effect = lambda *args, **kwargs: print("Step 4 ejecutado")
        mock_step5.side_effect = lambda *args, **kwargs: print("Step 5 ejecutado")
        mock_step6.side_effect = lambda *args, **kwargs: print("Step 6 ejecutado")

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        app.dependency_overrides[get_current_user] = lambda: corporate_admin_user
        app.dependency_overrides[require_corporate_admin] = lambda: corporate_admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        csv_file = ("csv_file", ("inventory.csv", io.BytesIO(valid_csv_content.encode("utf-8")), "text/csv"))

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/admin/sync-inventory/execute",
                data={
                    "step": "7",
                    "dry_run": "true",
                    "organization_id": test_org_id,
                },
                files=[csv_file],
            )

        assert response.status_code == 200
        data = response.json()

        # Verificar que todos los pasos se ejecutaron
        mock_step1.assert_called_once()
        mock_step2.assert_called_once()
        mock_step3.assert_called_once()
        mock_step4.assert_called_once()
        mock_step5.assert_called_once()
        mock_step6.assert_called_once()

        # Verificar que la respuesta contiene 6 StepResult
        assert len(data["steps_executed"]) == 6
        assert data["success"] is True

        # Verificar orden secuencial
        for i, step_result in enumerate(data["steps_executed"], start=1):
            assert step_result["step"] == i
            assert step_result["success"] is True

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    @patch("app.api.v1.endpoints.sync_inventory.step6_cleanup_vlan_cidrs")
    @patch("app.api.v1.endpoints.sync_inventory.step5_delete_empty_vlans")
    @patch("app.api.v1.endpoints.sync_inventory.step4_assign_orphan_devices")
    @patch("app.api.v1.endpoints.sync_inventory.step3_upsert_devices")
    @patch("app.api.v1.endpoints.sync_inventory.step2_reassign_workstations")
    @patch("app.api.v1.endpoints.sync_inventory.step1_sync_vlans")
    async def test_run_all_output_agrupado_por_paso(
        self,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_step4,
        mock_step5,
        mock_step6,
        corporate_admin_user,
        mock_db,
        test_org_id,
        valid_csv_content,
    ):
        """
        WHEN se ejecuta Run All,
        THEN el total_output contiene el output de cada paso agrupado.
        Validates: Requirements 4.2, 8.3
        """
        mock_step1.side_effect = lambda *args, **kwargs: (
            print("Output del paso 1") or {"001": "vlan-id-1"}
        )
        mock_step2.side_effect = lambda *args, **kwargs: print("Output del paso 2")
        mock_step3.side_effect = lambda *args, **kwargs: print("Output del paso 3")
        mock_step4.side_effect = lambda *args, **kwargs: print("Output del paso 4")
        mock_step5.side_effect = lambda *args, **kwargs: print("Output del paso 5")
        mock_step6.side_effect = lambda *args, **kwargs: print("Output del paso 6")

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        app.dependency_overrides[get_current_user] = lambda: corporate_admin_user
        app.dependency_overrides[require_corporate_admin] = lambda: corporate_admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        csv_file = ("csv_file", ("inventory.csv", io.BytesIO(valid_csv_content.encode("utf-8")), "text/csv"))

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/admin/sync-inventory/execute",
                data={
                    "step": "7",
                    "dry_run": "true",
                    "organization_id": test_org_id,
                },
                files=[csv_file],
            )

        assert response.status_code == 200
        data = response.json()

        # Verificar que total_output contiene separadores por paso
        total_output = data["total_output"]
        assert "Paso 1" in total_output
        assert "Paso 2" in total_output
        assert "Paso 3" in total_output
        assert "Paso 4" in total_output
        assert "Paso 5" in total_output
        assert "Paso 6" in total_output

        # Verificar que el output individual de cada paso se capturó
        assert "Output del paso 1" in data["steps_executed"][0]["output"]
        assert "Output del paso 2" in data["steps_executed"][1]["output"]
        assert "Output del paso 6" in data["steps_executed"][5]["output"]

        app.dependency_overrides.clear()


# === TEST: ROLLBACK ANTE FALLO ===


class TestRollbackAnteError:
    """Tests para verificar rollback y detención de ejecución ante fallos."""

    @pytest.mark.asyncio
    @patch("app.api.v1.endpoints.sync_inventory.step6_cleanup_vlan_cidrs")
    @patch("app.api.v1.endpoints.sync_inventory.step5_delete_empty_vlans")
    @patch("app.api.v1.endpoints.sync_inventory.step4_assign_orphan_devices")
    @patch("app.api.v1.endpoints.sync_inventory.step3_upsert_devices")
    @patch("app.api.v1.endpoints.sync_inventory.step2_reassign_workstations")
    @patch("app.api.v1.endpoints.sync_inventory.step1_sync_vlans")
    async def test_fallo_en_step3_detiene_ejecucion(
        self,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_step4,
        mock_step5,
        mock_step6,
        corporate_admin_user,
        mock_db,
        test_org_id,
        valid_csv_content,
    ):
        """
        WHEN step3 falla durante "Run All",
        THEN steps 1 y 2 se ejecutan, step3 se intenta, steps 4-6 NO se ejecutan.
        THEN db.rollback() se invoca.
        THEN la respuesta tiene success=False.
        Validates: Requirements 4.3, 8.5
        """
        # Steps 1 y 2 exitosos
        mock_step1.side_effect = lambda *args, **kwargs: (
            print("Step 1 OK") or {"001": "vlan-id-1"}
        )
        mock_step2.side_effect = lambda *args, **kwargs: print("Step 2 OK")

        # Step 3 lanza excepción
        mock_step3.side_effect = Exception("Error de integridad en BD: duplicate key")

        # Steps 4-6 no deberían ejecutarse
        mock_step4.side_effect = lambda *args, **kwargs: print("Step 4 no debería ejecutarse")
        mock_step5.side_effect = lambda *args, **kwargs: print("Step 5 no debería ejecutarse")
        mock_step6.side_effect = lambda *args, **kwargs: print("Step 6 no debería ejecutarse")

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        app.dependency_overrides[get_current_user] = lambda: corporate_admin_user
        app.dependency_overrides[require_corporate_admin] = lambda: corporate_admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        csv_file = ("csv_file", ("inventory.csv", io.BytesIO(valid_csv_content.encode("utf-8")), "text/csv"))

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/admin/sync-inventory/execute",
                data={
                    "step": "7",
                    "dry_run": "true",
                    "organization_id": test_org_id,
                },
                files=[csv_file],
            )

        assert response.status_code == 200
        data = response.json()

        # Verificar que steps 1 y 2 se ejecutaron
        mock_step1.assert_called_once()
        mock_step2.assert_called_once()

        # Verificar que step3 se intentó (pero falló)
        mock_step3.assert_called_once()

        # Verificar que steps 4-6 NO se ejecutaron (se detuvo tras el fallo)
        mock_step4.assert_not_called()
        mock_step5.assert_not_called()
        mock_step6.assert_not_called()

        # Verificar rollback de la transacción
        mock_db.rollback.assert_called_once()

        # Verificar respuesta con success=False
        assert data["success"] is False

        # Verificar que la respuesta tiene 3 StepResult (steps 1, 2, 3)
        assert len(data["steps_executed"]) == 3

        # Steps 1 y 2 exitosos
        assert data["steps_executed"][0]["success"] is True
        assert data["steps_executed"][1]["success"] is True

        # Step 3 fallido con error
        step3_result = data["steps_executed"][2]
        assert step3_result["success"] is False
        assert step3_result["error"] is not None
        assert "duplicate key" in step3_result["error"]

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    @patch("app.api.v1.endpoints.sync_inventory.step4_assign_orphan_devices")
    async def test_fallo_en_paso_individual_rollback(
        self,
        mock_step4,
        corporate_admin_user,
        mock_db,
        test_org_id,
    ):
        """
        WHEN un paso individual falla con excepción,
        THEN db.rollback() se invoca y la respuesta indica el error.
        Validates: Requirement 8.5
        """
        mock_step4.side_effect = RuntimeError("Connection reset by peer")

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        app.dependency_overrides[get_current_user] = lambda: corporate_admin_user
        app.dependency_overrides[require_corporate_admin] = lambda: corporate_admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/admin/sync-inventory/execute",
                data={
                    "step": "4",
                    "dry_run": "false",
                    "organization_id": test_org_id,
                },
            )

        assert response.status_code == 200
        data = response.json()

        # Verificar rollback
        mock_db.rollback.assert_called_once()

        # Verificar respuesta de error
        assert data["success"] is False
        assert len(data["steps_executed"]) == 1
        assert data["steps_executed"][0]["success"] is False
        assert "Connection reset by peer" in data["steps_executed"][0]["error"]

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    @patch("app.api.v1.endpoints.sync_inventory.step6_cleanup_vlan_cidrs")
    @patch("app.api.v1.endpoints.sync_inventory.step5_delete_empty_vlans")
    @patch("app.api.v1.endpoints.sync_inventory.step4_assign_orphan_devices")
    @patch("app.api.v1.endpoints.sync_inventory.step3_upsert_devices")
    @patch("app.api.v1.endpoints.sync_inventory.step2_reassign_workstations")
    @patch("app.api.v1.endpoints.sync_inventory.step1_sync_vlans")
    async def test_fallo_en_step1_no_ejecuta_ninguno_mas(
        self,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_step4,
        mock_step5,
        mock_step6,
        corporate_admin_user,
        mock_db,
        test_org_id,
        valid_csv_content,
    ):
        """
        WHEN step1 falla durante "Run All",
        THEN ninguno de los pasos 2-6 se ejecuta.
        Validates: Requirement 4.3
        """
        mock_step1.side_effect = ValueError("CSV contiene VLAN_CODE duplicados")

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        app.dependency_overrides[get_current_user] = lambda: corporate_admin_user
        app.dependency_overrides[require_corporate_admin] = lambda: corporate_admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        csv_file = ("csv_file", ("inventory.csv", io.BytesIO(valid_csv_content.encode("utf-8")), "text/csv"))

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/admin/sync-inventory/execute",
                data={
                    "step": "7",
                    "dry_run": "true",
                    "organization_id": test_org_id,
                },
                files=[csv_file],
            )

        assert response.status_code == 200
        data = response.json()

        # Solo step1 fue llamado
        mock_step1.assert_called_once()
        mock_step2.assert_not_called()
        mock_step3.assert_not_called()
        mock_step4.assert_not_called()
        mock_step5.assert_not_called()
        mock_step6.assert_not_called()

        # Verificar rollback
        mock_db.rollback.assert_called_once()

        # Respuesta indica fallo
        assert data["success"] is False
        assert len(data["steps_executed"]) == 1
        assert data["steps_executed"][0]["success"] is False
        assert "VLAN_CODE duplicados" in data["steps_executed"][0]["error"]

        app.dependency_overrides.clear()
