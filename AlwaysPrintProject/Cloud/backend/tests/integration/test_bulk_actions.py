"""
Tests de integración para el sistema de acciones masivas (bulk actions).

Verifica los flujos completos:
1. Start → progress → complete
2. Start → cancel → final report
3. Mutex: segundo start rechazado con 409
4. Auth: readonly user gets 403
5. Tenant isolation
6. Audit logs

**Validates: Requirements 2.7, 4.1, 5.1, 5.2, 5.3, 7.1, 7.2**
"""

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.user import User, UserRole
from app.services.bulk_execution import BulkExecutionService


# === FIXTURES ===


@pytest.fixture
def org_id():
    """UUID de organización para los tests."""
    return uuid.uuid4()


@pytest.fixture
def other_org_id():
    """UUID de otra organización (para tenant isolation)."""
    return uuid.uuid4()


@pytest.fixture
def user_id():
    """UUID de usuario operador."""
    return uuid.uuid4()


@pytest.fixture
def bulk_service():
    """Instancia de BulkExecutionService."""
    return BulkExecutionService()


@pytest.fixture
def mock_redis(org_id):
    """Mock de Redis async client sin mutex existente."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    redis.hset = AsyncMock()
    redis.hgetall = AsyncMock(return_value={})
    redis.expire = AsyncMock()
    redis.delete = AsyncMock()
    redis.aclose = AsyncMock()
    return redis


@pytest.fixture
def mock_connection_manager(org_id):
    """ConnectionManager mock con 10 workstations online."""
    cm = MagicMock()
    ws_ids = [f"ws-{i}" for i in range(10)]
    cm.org_ids = {ws_id: str(org_id) for ws_id in ws_ids}
    cm.workstation_connections = {ws_id: MagicMock() for ws_id in ws_ids}
    cm.send_to_workstation = AsyncMock(return_value=True)
    cm.broadcast_to_organization = AsyncMock()
    return cm


@pytest.fixture
def mock_active_config():
    """Mock de ActionConfig con triggers OnDemand."""
    config = MagicMock()
    config.config_json = json.dumps({
        "version": "1.0",
        "name": "Test",
        "triggers": [
            {
                "event": "OnDemand",
                "label": "TestAction",
                "description": "Acción de test",
                "actions": [],
            },
            {
                "event": "OnDemand",
                "label": "OtherAction",
                "description": "Otra acción",
                "actions": [],
            },
            {"event": "OnServiceStart", "actions": []},
        ],
    })
    return config


# === TEST 1: FLUJO COMPLETO START → PROGRESS → COMPLETE ===


class TestFlujoCompletoStartComplete:
    """
    Tests de integración del flujo completo de ejecución masiva.

    Simula: start → ejecución throttled → progress → complete.
    Validates: Requirements 2.7, 7.1, 7.2
    """

    @pytest.mark.asyncio
    @patch("app.services.bulk_execution.AuditService")
    @patch("app.services.bulk_execution.ActionConfigService.get_active_config")
    @patch("app.services.bulk_execution.BulkExecutionService._get_redis_client")
    async def test_start_session_creates_mutex_and_session(
        self,
        mock_get_redis,
        mock_get_config,
        mock_audit_class,
        bulk_service,
        mock_redis,
        mock_active_config,
        mock_connection_manager,
        org_id,
        user_id,
        db,
    ):
        """
        WHEN un operador inicia una Bulk_Session,
        THEN se crea el mutex Redis y el hash de sesión con estado running.
        """
        mock_get_redis.return_value = mock_redis
        mock_get_config.return_value = mock_active_config
        mock_audit_class.return_value.log_action = MagicMock()

        with patch(
            "app.services.websocket_manager.connection_manager",
            mock_connection_manager,
        ):
            response, ws_ids = await bulk_service.start_session(
                org_id=org_id,
                label="TestAction",
                delay_ms=500,
                user_id=user_id,
                db=db,
            )

        # Verificar que se creó el mutex con TTL de 30 min
        mock_redis.set.assert_any_call(
            f"bulk:running:{org_id}", str(response.session_id), ex=1800
        )

        # Verificar que se creó el hash de sesión
        mock_redis.hset.assert_called()
        hset_calls = mock_redis.hset.call_args_list
        # El primer hset debe ser el hash de sesión
        session_call = hset_calls[0]
        assert f"bulk:session:{response.session_id}" in str(session_call)

        # Verificar respuesta correcta
        assert response.total == 10
        assert response.session_id is not None
        assert response.started_at is not None
        assert len(ws_ids) == 10


    @pytest.mark.asyncio
    @patch("app.services.bulk_execution.AuditService")
    @patch("app.services.bulk_execution.ActionConfigService.get_active_config")
    @patch("app.services.bulk_execution.BulkExecutionService._get_redis_client")
    async def test_start_session_registers_audit_log(
        self,
        mock_get_redis,
        mock_get_config,
        mock_audit_class,
        bulk_service,
        mock_redis,
        mock_active_config,
        mock_connection_manager,
        org_id,
        user_id,
        db,
    ):
        """
        WHEN una Bulk_Session se inicia exitosamente,
        THEN se registra un log de auditoría con datos de inicio.
        Validates: Requirement 7.1
        """
        mock_get_redis.return_value = mock_redis
        mock_get_config.return_value = mock_active_config
        mock_audit_instance = MagicMock()
        mock_audit_class.return_value = mock_audit_instance

        with patch(
            "app.services.websocket_manager.connection_manager",
            mock_connection_manager,
        ):
            response, _ = await bulk_service.start_session(
                org_id=org_id,
                label="TestAction",
                delay_ms=500,
                user_id=user_id,
                db=db,
            )

        # Verificar que se llamó a log_action con datos de auditoría
        mock_audit_instance.log_action.assert_called_once()
        call_kwargs = mock_audit_instance.log_action.call_args[1]
        assert call_kwargs["entity_type"] == "BulkSession"
        assert call_kwargs["user_id"] == str(user_id)
        assert call_kwargs["organization_id"] == str(org_id)
        assert call_kwargs["new_values"]["action"] == "bulk_start"
        assert call_kwargs["new_values"]["label"] == "TestAction"
        assert call_kwargs["new_values"]["delay_ms"] == 500
        assert call_kwargs["new_values"]["total_workstations"] == 10


    @pytest.mark.asyncio
    @patch("app.services.bulk_execution.SessionLocal")
    @patch("app.services.bulk_execution.AuditService")
    @patch("app.services.bulk_execution.BulkExecutionService._get_redis_client")
    async def test_execute_bulk_completes_all_workstations(
        self,
        mock_get_redis,
        mock_audit_class,
        mock_session_local,
        bulk_service,
        mock_redis,
        mock_connection_manager,
        org_id,
        user_id,
    ):
        """
        WHEN el background task ejecuta contra 5 workstations sin cancelación,
        THEN estado final es completed y sent == total.
        Validates: Requirements 2.3, 3.3
        """
        # Configurar Redis para simular sesión existente
        mock_redis.hgetall.return_value = {
            "status": "running",
            "user_id": str(user_id),
        }
        mock_get_redis.return_value = mock_redis
        mock_audit_class.return_value.log_action = MagicMock()
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db

        ws_ids = [f"ws-{i}" for i in range(5)]
        session_id = uuid.uuid4()

        with patch(
            "app.services.websocket_manager.connection_manager",
            mock_connection_manager,
        ):
            await bulk_service._execute_bulk(
                session_id=session_id,
                org_id=org_id,
                label="TestAction",
                delay_ms=50,  # delay mínimo para test rápido
                workstation_ids=ws_ids,
            )

        # Verificar que se marcó como completed
        hset_calls = mock_redis.hset.call_args_list
        status_updates = [
            c for c in hset_calls
            if len(c[0]) >= 2 and c[0][1] == "status"
        ]
        assert any(c[0][2] == "completed" for c in status_updates)

        # Verificar que se envió a todas las workstations
        assert mock_connection_manager.send_to_workstation.call_count == 5

        # Verificar que se liberó el mutex
        mock_redis.delete.assert_called_with(f"bulk:running:{org_id}")

        # Verificar progress report final enviado vía WebSocket
        broadcast_calls = mock_connection_manager.broadcast_to_organization.call_args_list
        final_report = broadcast_calls[-1][0][1]
        assert final_report["status"] == "completed"
        assert final_report["sent"] == 5
        assert final_report["total"] == 5


# === TEST 2: FLUJO CANCELACIÓN START → CANCEL → FINAL REPORT ===


class TestFlujoCancelacion:
    """
    Tests de integración del flujo de cancelación.

    Simula: start → cancel flag → background task detecta → cancelled.
    Validates: Requirements 4.1, 4.2, 4.3, 4.4
    """

    @pytest.mark.asyncio
    @patch("app.services.bulk_execution.BulkExecutionService._get_redis_client")
    async def test_cancel_session_sets_cancel_flag(
        self,
        mock_get_redis,
        bulk_service,
        mock_redis,
        org_id,
    ):
        """
        WHEN un operador cancela una sesión running,
        THEN se establece el flag de cancelación en Redis.
        Validates: Requirement 4.1
        """
        session_id = uuid.uuid4()
        started_at = datetime.now(timezone.utc).replace(tzinfo=None)

        # Simular sesión existente en Redis con estado running
        mock_redis.hgetall.return_value = {
            "status": "running",
            "org_id": str(org_id),
            "total": "10",
            "sent": "3",
            "success": "3",
            "errors": "0",
            "failed_workstations": "[]",
            "started_at": started_at.isoformat(),
        }
        mock_get_redis.return_value = mock_redis

        result = await bulk_service.cancel_session(session_id, org_id)

        # Verificar que se estableció el flag de cancelación con TTL 5 min
        mock_redis.set.assert_called_once_with(
            f"bulk:cancel:{session_id}", "1", ex=300
        )

        # Verificar que se retorna el estado actual
        assert result.session_id == session_id
        assert result.status == "running"  # Aún running hasta que BG task procese
        assert result.sent == 3

    @pytest.mark.asyncio
    @patch("app.services.bulk_execution.BulkExecutionService._get_redis_client")
    async def test_cancel_session_rejected_when_not_running(
        self,
        mock_get_redis,
        bulk_service,
        mock_redis,
        org_id,
    ):
        """
        WHEN un operador intenta cancelar una sesión que NO está running,
        THEN se rechaza con HTTP 409.
        Validates: Requirement 4.4
        """
        session_id = uuid.uuid4()
        started_at = datetime.now(timezone.utc).replace(tzinfo=None)

        # Sesión ya completada
        mock_redis.hgetall.return_value = {
            "status": "completed",
            "org_id": str(org_id),
            "total": "10",
            "sent": "10",
            "success": "10",
            "errors": "0",
            "failed_workstations": "[]",
            "started_at": started_at.isoformat(),
        }
        mock_get_redis.return_value = mock_redis

        with pytest.raises(HTTPException) as exc_info:
            await bulk_service.cancel_session(session_id, org_id)

        assert exc_info.value.status_code == 409
        assert "no está en estado ejecutable" in exc_info.value.detail


    @pytest.mark.asyncio
    @patch("app.services.bulk_execution.SessionLocal")
    @patch("app.services.bulk_execution.AuditService")
    @patch("app.services.bulk_execution.BulkExecutionService._get_redis_client")
    async def test_execute_bulk_stops_on_cancel_flag(
        self,
        mock_get_redis,
        mock_audit_class,
        mock_session_local,
        bulk_service,
        mock_redis,
        mock_connection_manager,
        org_id,
        user_id,
    ):
        """
        WHEN el background task detecta el flag de cancelación,
        THEN se detiene, marca cancelled, y envía progress report final.
        Validates: Requirements 4.1, 4.2, 4.3
        """
        session_id = uuid.uuid4()
        ws_ids = [f"ws-{i}" for i in range(10)]

        # Simular: primeros 3 envíos OK, luego cancelación
        call_count = {"n": 0}

        async def mock_get_cancel(key):
            """Retorna None las primeras 3 veces, luego '1' (cancelado)."""
            if key.startswith("bulk:cancel:"):
                call_count["n"] += 1
                return "1" if call_count["n"] > 3 else None
            return None

        mock_redis.get = AsyncMock(side_effect=mock_get_cancel)
        mock_redis.hgetall.return_value = {
            "status": "cancelled",
            "user_id": str(user_id),
        }
        mock_get_redis.return_value = mock_redis
        mock_audit_class.return_value.log_action = MagicMock()
        mock_session_local.return_value = MagicMock()

        with patch(
            "app.services.websocket_manager.connection_manager",
            mock_connection_manager,
        ):
            await bulk_service._execute_bulk(
                session_id=session_id,
                org_id=org_id,
                label="TestAction",
                delay_ms=50,
                workstation_ids=ws_ids,
            )

        # Verificar que se detuvo antes de enviar a todos (máx 3 envíos)
        send_count = mock_connection_manager.send_to_workstation.call_count
        assert send_count <= 3  # Se detuvo en la 4ta iteración

        # Verificar que se marcó como cancelled en Redis
        hset_calls = mock_redis.hset.call_args_list
        status_updates = [
            c for c in hset_calls
            if len(c[0]) >= 2 and c[0][1] == "status"
        ]
        assert any(c[0][2] == "cancelled" for c in status_updates)

        # Verificar progress report final con estado cancelled
        broadcast_calls = mock_connection_manager.broadcast_to_organization.call_args_list
        final_report = broadcast_calls[-1][0][1]
        assert final_report["status"] == "cancelled"


# === TEST 3: MUTEX — SEGUNDO START RECHAZADO CON 409 ===


class TestMutexConcurrencia:
    """
    Tests de integración para el mutex por organización.

    Verifica que solo una Bulk_Session puede ejecutarse por org.
    Validates: Requirement 2.7
    """

    @pytest.mark.asyncio
    @patch("app.services.bulk_execution.ActionConfigService.get_active_config")
    @patch("app.services.bulk_execution.BulkExecutionService._get_redis_client")
    async def test_start_session_rejected_when_mutex_exists(
        self,
        mock_get_redis,
        mock_get_config,
        bulk_service,
        mock_redis,
        mock_active_config,
        mock_connection_manager,
        org_id,
        user_id,
        db,
    ):
        """
        WHEN ya existe una Bulk_Session running para la org,
        THEN un segundo start es rechazado con HTTP 409.
        Validates: Requirement 2.7
        """
        # Simular mutex existente en Redis
        existing_session_id = str(uuid.uuid4())
        mock_redis.get = AsyncMock(return_value=existing_session_id)
        mock_get_redis.return_value = mock_redis
        mock_get_config.return_value = mock_active_config

        with patch(
            "app.services.websocket_manager.connection_manager",
            mock_connection_manager,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await bulk_service.start_session(
                    org_id=org_id,
                    label="TestAction",
                    delay_ms=500,
                    user_id=user_id,
                    db=db,
                )

        assert exc_info.value.status_code == 409
        assert "Ya existe una ejecución masiva en curso" in exc_info.value.detail

    @pytest.mark.asyncio
    @patch("app.services.bulk_execution.AuditService")
    @patch("app.services.bulk_execution.ActionConfigService.get_active_config")
    @patch("app.services.bulk_execution.BulkExecutionService._get_redis_client")
    async def test_different_org_can_start_independently(
        self,
        mock_get_redis,
        mock_get_config,
        mock_audit_class,
        bulk_service,
        mock_redis,
        mock_active_config,
        org_id,
        other_org_id,
        user_id,
        db,
    ):
        """
        WHEN una org tiene sesión running, otra org puede iniciar independientemente.
        Validates: Requirement 2.7
        """
        # Simular que no hay mutex para other_org_id
        mock_redis.get = AsyncMock(return_value=None)
        mock_get_redis.return_value = mock_redis
        mock_get_config.return_value = mock_active_config
        mock_audit_class.return_value.log_action = MagicMock()

        # ConnectionManager con workstations de la otra org
        cm = MagicMock()
        ws_ids = [f"ws-other-{i}" for i in range(3)]
        cm.org_ids = {ws_id: str(other_org_id) for ws_id in ws_ids}
        cm.workstation_connections = {ws_id: MagicMock() for ws_id in ws_ids}

        with patch("app.services.websocket_manager.connection_manager", cm):
            response, ws_list = await bulk_service.start_session(
                org_id=other_org_id,
                label="TestAction",
                delay_ms=500,
                user_id=user_id,
                db=db,
            )

        # Debe tener éxito (sin 409)
        assert response.session_id is not None
        assert response.total == 3


# === TEST 4: AUTH — READONLY USER GETS 403 ===


class TestAuthorizacion:
    """
    Tests de integración para autorización y control de acceso.

    Validates: Requirements 5.1, 5.2, 5.3
    """

    def test_readonly_user_rejected_with_403(self):
        """
        WHEN un usuario readonly intenta usar bulk actions,
        THEN el helper _resolve_org_id lanza HTTP 403.
        Validates: Requirement 5.3
        """
        from app.api.v1.endpoints.bulk_actions import _resolve_org_id

        # Crear usuario mock con rol readonly
        user = MagicMock(spec=User)
        user.role = UserRole.READONLY
        user.organization_id = uuid.uuid4()

        with pytest.raises(HTTPException) as exc_info:
            _resolve_org_id(user)

        assert exc_info.value.status_code == 403
        assert "Permisos insuficientes" in exc_info.value.detail

    def test_operator_user_returns_org_id(self):
        """
        WHEN un usuario operator usa bulk actions,
        THEN _resolve_org_id retorna su organization_id.
        Validates: Requirement 5.1
        """
        from app.api.v1.endpoints.bulk_actions import _resolve_org_id

        org_id = uuid.uuid4()
        user = MagicMock(spec=User)
        user.role = UserRole.OPERATOR
        user.organization_id = org_id

        result = _resolve_org_id(user)
        assert result == org_id

    def test_admin_user_returns_org_id(self):
        """
        WHEN un usuario admin usa bulk actions,
        THEN _resolve_org_id retorna su organization_id.
        Validates: Requirement 5.1
        """
        from app.api.v1.endpoints.bulk_actions import _resolve_org_id

        org_id = uuid.uuid4()
        user = MagicMock(spec=User)
        user.role = UserRole.ADMIN
        user.organization_id = org_id

        result = _resolve_org_id(user)
        assert result == org_id


# === TEST 5: TENANT ISOLATION ===


class TestTenantIsolation:
    """
    Tests de integración para aislamiento de tenant (organización).

    Validates: Requirement 5.2
    """

    @pytest.mark.asyncio
    @patch("app.services.bulk_execution.BulkExecutionService._get_redis_client")
    async def test_get_session_status_rejects_other_org(
        self,
        mock_get_redis,
        bulk_service,
        mock_redis,
        org_id,
        other_org_id,
    ):
        """
        WHEN un operador consulta una sesión de OTRA organización,
        THEN se retorna HTTP 403.
        Validates: Requirement 5.2
        """
        session_id = uuid.uuid4()
        started_at = datetime.now(timezone.utc).replace(tzinfo=None)

        # Sesión pertenece a org_id
        mock_redis.hgetall.return_value = {
            "status": "running",
            "org_id": str(org_id),
            "total": "10",
            "sent": "5",
            "success": "5",
            "errors": "0",
            "failed_workstations": "[]",
            "started_at": started_at.isoformat(),
        }
        mock_get_redis.return_value = mock_redis

        # Intentar acceder con other_org_id
        with pytest.raises(HTTPException) as exc_info:
            await bulk_service.get_session_status(session_id, other_org_id)

        assert exc_info.value.status_code == 403
        assert "No tienes permisos para esta organización" in exc_info.value.detail

    @pytest.mark.asyncio
    @patch("app.services.bulk_execution.BulkExecutionService._get_redis_client")
    async def test_cancel_session_rejects_other_org(
        self,
        mock_get_redis,
        bulk_service,
        mock_redis,
        org_id,
        other_org_id,
    ):
        """
        WHEN un operador intenta cancelar una sesión de OTRA organización,
        THEN se retorna HTTP 403.
        Validates: Requirement 5.2
        """
        session_id = uuid.uuid4()
        started_at = datetime.now(timezone.utc).replace(tzinfo=None)

        # Sesión pertenece a org_id
        mock_redis.hgetall.return_value = {
            "status": "running",
            "org_id": str(org_id),
            "total": "10",
            "sent": "5",
            "success": "5",
            "errors": "0",
            "failed_workstations": "[]",
            "started_at": started_at.isoformat(),
        }
        mock_get_redis.return_value = mock_redis

        # Intentar cancelar con other_org_id
        with pytest.raises(HTTPException) as exc_info:
            await bulk_service.cancel_session(session_id, other_org_id)

        assert exc_info.value.status_code == 403
        assert "No tienes permisos para esta organización" in exc_info.value.detail


# === TEST 6: AUDIT LOGS ===


class TestAuditLogs:
    """
    Tests de integración para registro de auditoría.

    Validates: Requirements 7.1, 7.2
    """

    @pytest.mark.asyncio
    @patch("app.services.bulk_execution.SessionLocal")
    @patch("app.services.bulk_execution.AuditService")
    @patch("app.services.bulk_execution.BulkExecutionService._get_redis_client")
    async def test_audit_log_on_bulk_complete(
        self,
        mock_get_redis,
        mock_audit_class,
        mock_session_local,
        bulk_service,
        mock_redis,
        mock_connection_manager,
        org_id,
        user_id,
    ):
        """
        WHEN una Bulk_Session finaliza (completada),
        THEN se registra un audit log con datos de finalización.
        Validates: Requirement 7.2
        """
        session_id = uuid.uuid4()
        ws_ids = [f"ws-{i}" for i in range(3)]

        mock_redis.hgetall.return_value = {
            "status": "completed",
            "user_id": str(user_id),
        }
        mock_get_redis.return_value = mock_redis

        mock_audit_instance = MagicMock()
        mock_audit_class.return_value = mock_audit_instance
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db

        with patch(
            "app.services.websocket_manager.connection_manager",
            mock_connection_manager,
        ):
            await bulk_service._execute_bulk(
                session_id=session_id,
                org_id=org_id,
                label="TestAction",
                delay_ms=50,
                workstation_ids=ws_ids,
            )

        # Verificar que se llamó a log_action al finalizar
        mock_audit_instance.log_action.assert_called_once()
        call_kwargs = mock_audit_instance.log_action.call_args[1]
        assert call_kwargs["entity_type"] == "BulkSession"
        assert call_kwargs["entity_id"] == str(session_id)
        assert call_kwargs["organization_id"] == str(org_id)
        assert call_kwargs["new_values"]["action"] == "bulk_complete"
        assert call_kwargs["new_values"]["final_status"] == "completed"
        assert call_kwargs["new_values"]["success"] == 3
        assert call_kwargs["new_values"]["errors"] == 0
        assert call_kwargs["new_values"]["total"] == 3
        assert "duration_ms" in call_kwargs["new_values"]

    @pytest.mark.asyncio
    @patch("app.services.bulk_execution.SessionLocal")
    @patch("app.services.bulk_execution.AuditService")
    @patch("app.services.bulk_execution.BulkExecutionService._get_redis_client")
    async def test_audit_log_on_bulk_cancelled(
        self,
        mock_get_redis,
        mock_audit_class,
        mock_session_local,
        bulk_service,
        mock_redis,
        mock_connection_manager,
        org_id,
        user_id,
    ):
        """
        WHEN una Bulk_Session es cancelada,
        THEN se registra un audit log con final_status=cancelled.
        Validates: Requirement 7.2
        """
        session_id = uuid.uuid4()
        ws_ids = [f"ws-{i}" for i in range(10)]

        # Simular cancelación inmediata (flag siempre activo)
        async def mock_get(key):
            if key.startswith("bulk:cancel:"):
                return "1"
            return None

        mock_redis.get = AsyncMock(side_effect=mock_get)
        mock_redis.hgetall.return_value = {
            "status": "cancelled",
            "user_id": str(user_id),
        }
        mock_get_redis.return_value = mock_redis

        mock_audit_instance = MagicMock()
        mock_audit_class.return_value = mock_audit_instance
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db

        with patch(
            "app.services.websocket_manager.connection_manager",
            mock_connection_manager,
        ):
            await bulk_service._execute_bulk(
                session_id=session_id,
                org_id=org_id,
                label="TestAction",
                delay_ms=50,
                workstation_ids=ws_ids,
            )

        # Verificar que se registró con estado cancelled
        mock_audit_instance.log_action.assert_called_once()
        call_kwargs = mock_audit_instance.log_action.call_args[1]
        assert call_kwargs["new_values"]["final_status"] == "cancelled"
        assert call_kwargs["new_values"]["success"] == 0
        assert call_kwargs["new_values"]["errors"] == 0


# === TEST 7: GET SESSION STATUS ===


class TestGetSessionStatus:
    """
    Tests de integración para consulta de estado de sesión.

    Validates: Requirements 3.1, 3.2
    """

    @pytest.mark.asyncio
    @patch("app.services.bulk_execution.BulkExecutionService._get_redis_client")
    async def test_get_session_status_returns_metrics(
        self,
        mock_get_redis,
        bulk_service,
        mock_redis,
        org_id,
    ):
        """
        WHEN un operador consulta el estado de su sesión,
        THEN se retornan las métricas correctas desde Redis.
        Validates: Requirements 3.1, 3.2
        """
        session_id = uuid.uuid4()
        started_at = datetime.now(timezone.utc).replace(tzinfo=None)

        mock_redis.hgetall.return_value = {
            "status": "running",
            "org_id": str(org_id),
            "total": "10",
            "sent": "5",
            "success": "4",
            "errors": "1",
            "failed_workstations": '["ws-3"]',
            "started_at": started_at.isoformat(),
        }
        mock_get_redis.return_value = mock_redis

        result = await bulk_service.get_session_status(session_id, org_id)

        assert result.session_id == session_id
        assert result.status == "running"
        assert result.total == 10
        assert result.sent == 5
        assert result.success == 4
        assert result.errors == 1
        assert result.failed_workstations == ["ws-3"]
        assert result.elapsed_ms is not None
        assert result.elapsed_ms >= 0

    @pytest.mark.asyncio
    @patch("app.services.bulk_execution.BulkExecutionService._get_redis_client")
    async def test_get_session_status_not_found(
        self,
        mock_get_redis,
        bulk_service,
        mock_redis,
        org_id,
    ):
        """
        WHEN se consulta una sesión que no existe,
        THEN se retorna HTTP 404.
        """
        session_id = uuid.uuid4()
        mock_redis.hgetall.return_value = {}  # Vacío = no existe
        mock_get_redis.return_value = mock_redis

        with pytest.raises(HTTPException) as exc_info:
            await bulk_service.get_session_status(session_id, org_id)

        assert exc_info.value.status_code == 404
        assert "Sesión no encontrada" in exc_info.value.detail
