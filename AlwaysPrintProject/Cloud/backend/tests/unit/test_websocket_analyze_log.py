"""
Tests unitarios para la integración WebSocket del comando analyze_log.

Verifica:
- Envío correcto del mensaje con formato esperado
- Uso de register_command_waiter y wait_for_command_response
- Parseo de respuesta: filename, content (base64), original_size, is_compressed
- Manejo de timeout configurable (default 30s)
- Manejo de workstation offline

Requirements: 1.3, 1.8, 1.9
"""

import base64
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1.endpoints.log_analysis import analyze_workstation_log


# === FIXTURES ===


@pytest.fixture
def mock_connection_manager():
    """Mock del connection_manager con métodos necesarios."""
    with patch(
        "app.api.v1.endpoints.log_analysis.connection_manager"
    ) as mock_cm:
        mock_cm.is_workstation_online = MagicMock(return_value=True)
        mock_cm.register_command_waiter = MagicMock()
        mock_cm.send_to_workstation = AsyncMock(return_value=True)
        mock_cm.wait_for_command_response = AsyncMock(return_value=None)
        yield mock_cm


@pytest.fixture
def mock_db():
    """Mock de sesión de base de datos."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    return db


@pytest.fixture
def mock_workstation():
    """Mock de workstation válida."""
    ws = MagicMock()
    ws.id = uuid.uuid4()
    ws.organization_id = uuid.uuid4()
    return ws


@pytest.fixture
def mock_current_user():
    """Mock de usuario autenticado."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "admin@test.com"
    user.role = MagicMock()
    user.role.value = "admin"
    user.organization_id = uuid.uuid4()
    return user


@pytest.fixture
def sample_log_content():
    """Contenido de log de ejemplo para respuestas simuladas."""
    return "[2025-01-15 10:30:00] [SVC] Event 1000: Servicio iniciado\n" * 10


@pytest.fixture
def sample_ws_response(sample_log_content):
    """Respuesta simulada de la workstation con formato correcto."""
    content_b64 = base64.b64encode(sample_log_content.encode("utf-8")).decode("ascii")
    output_data = {
        "filename": "AlwaysPrint_2025-01-15.log",
        "content": content_b64,
        "original_size": len(sample_log_content.encode("utf-8")),
        "is_compressed": False,
    }
    return {
        "command_id": str(uuid.uuid4()),
        "success": True,
        "output": json.dumps(output_data),
    }


# === TESTS: FORMATO DEL MENSAJE ENVIADO ===


class TestCommandMessageFormat:
    """Verifica que el mensaje enviado a la workstation tiene el formato correcto."""

    @pytest.mark.asyncio
    async def test_mensaje_tiene_tipo_command(self, mock_connection_manager):
        """
        WHEN se envía el comando analyze_log,
        THEN el mensaje tiene type='command'.
        Validates: Requirement 1.3
        """
        mock_connection_manager.send_to_workstation = AsyncMock(return_value=True)
        mock_connection_manager.wait_for_command_response = AsyncMock(return_value=None)

        # Simular envío (timeout para que no procese más)
        with patch(
            "app.api.v1.endpoints.log_analysis._verify_workstation_access"
        ) as mock_verify:
            mock_ws = MagicMock()
            mock_ws.organization_id = uuid.uuid4()
            mock_verify.return_value = mock_ws

            with patch(
                "app.api.v1.endpoints.log_analysis.LogAnalysisService"
            ) as mock_svc_cls:
                mock_svc = MagicMock()
                mock_svc.get_today_analysis.return_value = None
                mock_svc_cls.return_value = mock_svc

                from fastapi import HTTPException

                with pytest.raises(HTTPException) as exc_info:
                    await analyze_workstation_log(
                        workstation_id=uuid.uuid4(),
                        overwrite=False,
                        current_user=MagicMock(
                            role=MagicMock(value="admin"), email="a@b.com"
                        ),
                        db=MagicMock(),
                    )

                # Timeout esperado (wait_for_command_response retorna None)
                assert exc_info.value.status_code == 408

        # Verificar formato del mensaje enviado
        call_args = mock_connection_manager.send_to_workstation.call_args
        message = call_args[0][1]  # Segundo argumento posicional

        assert message["type"] == "command"
        assert message["command_type"] == "analyze_log"
        assert message["params"] == {}
        assert "command_id" in message
        # command_id debe ser un UUID válido
        uuid.UUID(message["command_id"])

    @pytest.mark.asyncio
    async def test_register_command_waiter_se_llama_antes_de_enviar(
        self, mock_connection_manager
    ):
        """
        WHEN se prepara el envío del comando,
        THEN register_command_waiter se llama antes de send_to_workstation.
        Validates: Requirement 1.3
        """
        call_order = []

        def track_register(cmd_id):
            call_order.append("register")

        async def track_send(ws_id, msg):
            call_order.append("send")
            return True

        mock_connection_manager.register_command_waiter = MagicMock(
            side_effect=track_register
        )
        mock_connection_manager.send_to_workstation = AsyncMock(side_effect=track_send)
        mock_connection_manager.wait_for_command_response = AsyncMock(return_value=None)

        with patch(
            "app.api.v1.endpoints.log_analysis._verify_workstation_access"
        ) as mock_verify:
            mock_ws = MagicMock()
            mock_ws.organization_id = uuid.uuid4()
            mock_verify.return_value = mock_ws

            with patch(
                "app.api.v1.endpoints.log_analysis.LogAnalysisService"
            ) as mock_svc_cls:
                mock_svc = MagicMock()
                mock_svc.get_today_analysis.return_value = None
                mock_svc_cls.return_value = mock_svc

                from fastapi import HTTPException

                with pytest.raises(HTTPException):
                    await analyze_workstation_log(
                        workstation_id=uuid.uuid4(),
                        overwrite=False,
                        current_user=MagicMock(
                            role=MagicMock(value="admin"), email="a@b.com"
                        ),
                        db=MagicMock(),
                    )

        assert call_order == ["register", "send"]


# === TESTS: MANEJO DE WORKSTATION OFFLINE ===


class TestWorkstationOffline:
    """Verifica el manejo cuando la workstation está offline."""

    @pytest.mark.asyncio
    async def test_workstation_offline_retorna_409(self, mock_connection_manager):
        """
        WHEN la workstation está offline (WebSocket desconectado),
        THEN el backend retorna HTTP 409.
        Validates: Requirement 1.8
        """
        mock_connection_manager.is_workstation_online = MagicMock(return_value=False)

        with patch(
            "app.api.v1.endpoints.log_analysis._verify_workstation_access"
        ) as mock_verify:
            mock_ws = MagicMock()
            mock_ws.organization_id = uuid.uuid4()
            mock_verify.return_value = mock_ws

            with patch(
                "app.api.v1.endpoints.log_analysis.LogAnalysisService"
            ) as mock_svc_cls:
                mock_svc = MagicMock()
                mock_svc.get_today_analysis.return_value = None
                mock_svc_cls.return_value = mock_svc

                from fastapi import HTTPException

                with pytest.raises(HTTPException) as exc_info:
                    await analyze_workstation_log(
                        workstation_id=uuid.uuid4(),
                        overwrite=False,
                        current_user=MagicMock(
                            role=MagicMock(value="admin"), email="a@b.com"
                        ),
                        db=MagicMock(),
                    )

                assert exc_info.value.status_code == 409
                assert "offline" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_workstation_desconecta_durante_envio_retorna_409(
        self, mock_connection_manager
    ):
        """
        WHEN la workstation se desconecta entre la verificación y el envío,
        THEN send_to_workstation retorna False y el backend retorna HTTP 409.
        Validates: Requirement 1.8
        """
        mock_connection_manager.is_workstation_online = MagicMock(return_value=True)
        mock_connection_manager.send_to_workstation = AsyncMock(return_value=False)

        with patch(
            "app.api.v1.endpoints.log_analysis._verify_workstation_access"
        ) as mock_verify:
            mock_ws = MagicMock()
            mock_ws.organization_id = uuid.uuid4()
            mock_verify.return_value = mock_ws

            with patch(
                "app.api.v1.endpoints.log_analysis.LogAnalysisService"
            ) as mock_svc_cls:
                mock_svc = MagicMock()
                mock_svc.get_today_analysis.return_value = None
                mock_svc_cls.return_value = mock_svc

                from fastapi import HTTPException

                with pytest.raises(HTTPException) as exc_info:
                    await analyze_workstation_log(
                        workstation_id=uuid.uuid4(),
                        overwrite=False,
                        current_user=MagicMock(
                            role=MagicMock(value="admin"), email="a@b.com"
                        ),
                        db=MagicMock(),
                    )

                assert exc_info.value.status_code == 409
                assert "desconectó" in exc_info.value.detail.lower()


# === TESTS: MANEJO DE TIMEOUT ===


class TestTimeout:
    """Verifica el manejo de timeout configurable."""

    @pytest.mark.asyncio
    async def test_timeout_retorna_408(self, mock_connection_manager):
        """
        WHEN la workstation no responde dentro del timeout,
        THEN wait_for_command_response retorna None y el backend retorna HTTP 408.
        Validates: Requirement 1.9
        """
        mock_connection_manager.wait_for_command_response = AsyncMock(return_value=None)

        with patch(
            "app.api.v1.endpoints.log_analysis._verify_workstation_access"
        ) as mock_verify:
            mock_ws = MagicMock()
            mock_ws.organization_id = uuid.uuid4()
            mock_verify.return_value = mock_ws

            with patch(
                "app.api.v1.endpoints.log_analysis.LogAnalysisService"
            ) as mock_svc_cls:
                mock_svc = MagicMock()
                mock_svc.get_today_analysis.return_value = None
                mock_svc_cls.return_value = mock_svc

                from fastapi import HTTPException

                with pytest.raises(HTTPException) as exc_info:
                    await analyze_workstation_log(
                        workstation_id=uuid.uuid4(),
                        overwrite=False,
                        current_user=MagicMock(
                            role=MagicMock(value="admin"), email="a@b.com"
                        ),
                        db=MagicMock(),
                    )

                assert exc_info.value.status_code == 408
                assert "timeout" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_timeout_usa_valor_configurable(self, mock_connection_manager):
        """
        WHEN se espera la respuesta,
        THEN se usa el timeout de settings.LOG_ANALYZER_COMMAND_TIMEOUT.
        Validates: Requirement 1.9
        """
        mock_connection_manager.wait_for_command_response = AsyncMock(return_value=None)

        with patch(
            "app.api.v1.endpoints.log_analysis._verify_workstation_access"
        ) as mock_verify:
            mock_ws = MagicMock()
            mock_ws.organization_id = uuid.uuid4()
            mock_verify.return_value = mock_ws

            with patch(
                "app.api.v1.endpoints.log_analysis.LogAnalysisService"
            ) as mock_svc_cls:
                mock_svc = MagicMock()
                mock_svc.get_today_analysis.return_value = None
                mock_svc_cls.return_value = mock_svc

                with patch(
                    "app.api.v1.endpoints.log_analysis.settings"
                ) as mock_settings:
                    mock_settings.LOG_ANALYZER_COMMAND_TIMEOUT = 45
                    mock_settings.LOG_ANALYZER_MAX_UPLOAD_SIZE = 52428800

                    from fastapi import HTTPException

                    with pytest.raises(HTTPException):
                        await analyze_workstation_log(
                            workstation_id=uuid.uuid4(),
                            overwrite=False,
                            current_user=MagicMock(
                                role=MagicMock(value="admin"), email="a@b.com"
                            ),
                            db=MagicMock(),
                        )

                # Verificar que se usó el timeout configurado
                call_args = (
                    mock_connection_manager.wait_for_command_response.call_args
                )
                assert call_args[1]["timeout"] == 45.0 or call_args[0][1] == 45.0


# === TESTS: PARSEO DE RESPUESTA ===


class TestResponseParsing:
    """Verifica el parseo correcto de la respuesta de la workstation."""

    @pytest.mark.asyncio
    async def test_parseo_respuesta_json_completa(
        self, mock_connection_manager, sample_ws_response
    ):
        """
        WHEN la workstation responde con JSON conteniendo filename, content, original_size, is_compressed,
        THEN se extraen correctamente todos los campos.
        Validates: Requirement 1.3
        """
        mock_connection_manager.wait_for_command_response = AsyncMock(
            return_value=sample_ws_response
        )

        with patch(
            "app.api.v1.endpoints.log_analysis._verify_workstation_access"
        ) as mock_verify:
            mock_ws = MagicMock()
            mock_ws.organization_id = uuid.uuid4()
            mock_verify.return_value = mock_ws

            with patch(
                "app.api.v1.endpoints.log_analysis.LogAnalysisService"
            ) as mock_svc_cls:
                mock_svc = MagicMock()
                mock_svc.get_today_analysis.return_value = None
                mock_svc.process_log = AsyncMock()
                # Simular resultado del análisis
                mock_result = MagicMock()
                mock_result.id = uuid.uuid4()
                mock_result.processing_path = "direct"
                mock_result.processing_duration_ms = 1500
                mock_svc.process_log.return_value = mock_result
                mock_svc_cls.return_value = mock_svc

                result = await analyze_workstation_log(
                    workstation_id=uuid.uuid4(),
                    overwrite=False,
                    current_user=MagicMock(
                        role=MagicMock(value="admin"), email="a@b.com"
                    ),
                    db=MagicMock(),
                )

                # Verificar que process_log fue llamado con los datos correctos
                call_kwargs = mock_svc.process_log.call_args[1]
                assert call_kwargs["is_compressed"] is False
                assert call_kwargs["original_filename"] == "AlwaysPrint_2025-01-15.log"
                assert call_kwargs["original_size"] > 0
                assert isinstance(call_kwargs["raw_payload"], bytes)

    @pytest.mark.asyncio
    async def test_parseo_respuesta_comprimida(self, mock_connection_manager):
        """
        WHEN la workstation responde con is_compressed=True,
        THEN se pasa is_compressed=True al servicio de procesamiento.
        Validates: Requirement 1.3
        """
        # Crear respuesta con flag de compresión
        content = b"contenido comprimido simulado"
        content_b64 = base64.b64encode(content).decode("ascii")
        output_data = {
            "filename": "AlwaysPrint_2025-01-15.log",
            "content": content_b64,
            "original_size": 48000,
            "is_compressed": True,
        }
        response = {
            "command_id": str(uuid.uuid4()),
            "success": True,
            "output": json.dumps(output_data),
        }

        mock_connection_manager.wait_for_command_response = AsyncMock(
            return_value=response
        )

        with patch(
            "app.api.v1.endpoints.log_analysis._verify_workstation_access"
        ) as mock_verify:
            mock_ws = MagicMock()
            mock_ws.organization_id = uuid.uuid4()
            mock_verify.return_value = mock_ws

            with patch(
                "app.api.v1.endpoints.log_analysis.LogAnalysisService"
            ) as mock_svc_cls:
                mock_svc = MagicMock()
                mock_svc.get_today_analysis.return_value = None
                mock_svc.process_log = AsyncMock()
                mock_result = MagicMock()
                mock_result.id = uuid.uuid4()
                mock_svc.process_log.return_value = mock_result
                mock_svc_cls.return_value = mock_svc

                await analyze_workstation_log(
                    workstation_id=uuid.uuid4(),
                    overwrite=False,
                    current_user=MagicMock(
                        role=MagicMock(value="admin"), email="a@b.com"
                    ),
                    db=MagicMock(),
                )

                call_kwargs = mock_svc.process_log.call_args[1]
                assert call_kwargs["is_compressed"] is True
                assert call_kwargs["original_size"] == 48000

    @pytest.mark.asyncio
    async def test_respuesta_sin_contenido_retorna_422(self, mock_connection_manager):
        """
        WHEN la workstation responde con content vacío,
        THEN el backend retorna HTTP 422.
        Validates: Requirement 1.3
        """
        output_data = {
            "filename": "AlwaysPrint_2025-01-15.log",
            "content": "",
            "original_size": 0,
            "is_compressed": False,
        }
        response = {
            "command_id": str(uuid.uuid4()),
            "success": True,
            "output": json.dumps(output_data),
        }

        mock_connection_manager.wait_for_command_response = AsyncMock(
            return_value=response
        )

        with patch(
            "app.api.v1.endpoints.log_analysis._verify_workstation_access"
        ) as mock_verify:
            mock_ws = MagicMock()
            mock_ws.organization_id = uuid.uuid4()
            mock_verify.return_value = mock_ws

            with patch(
                "app.api.v1.endpoints.log_analysis.LogAnalysisService"
            ) as mock_svc_cls:
                mock_svc = MagicMock()
                mock_svc.get_today_analysis.return_value = None
                mock_svc_cls.return_value = mock_svc

                from fastapi import HTTPException

                with pytest.raises(HTTPException) as exc_info:
                    await analyze_workstation_log(
                        workstation_id=uuid.uuid4(),
                        overwrite=False,
                        current_user=MagicMock(
                            role=MagicMock(value="admin"), email="a@b.com"
                        ),
                        db=MagicMock(),
                    )

                assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_respuesta_base64_invalido_retorna_422(self, mock_connection_manager):
        """
        WHEN la workstation responde con base64 inválido,
        THEN el backend retorna HTTP 422.
        Validates: Requirement 1.3
        """
        output_data = {
            "filename": "AlwaysPrint_2025-01-15.log",
            "content": "esto-no-es-base64-válido!!!@@@",
            "original_size": 1000,
            "is_compressed": False,
        }
        response = {
            "command_id": str(uuid.uuid4()),
            "success": True,
            "output": json.dumps(output_data),
        }

        mock_connection_manager.wait_for_command_response = AsyncMock(
            return_value=response
        )

        with patch(
            "app.api.v1.endpoints.log_analysis._verify_workstation_access"
        ) as mock_verify:
            mock_ws = MagicMock()
            mock_ws.organization_id = uuid.uuid4()
            mock_verify.return_value = mock_ws

            with patch(
                "app.api.v1.endpoints.log_analysis.LogAnalysisService"
            ) as mock_svc_cls:
                mock_svc = MagicMock()
                mock_svc.get_today_analysis.return_value = None
                mock_svc_cls.return_value = mock_svc

                from fastapi import HTTPException

                with pytest.raises(HTTPException) as exc_info:
                    await analyze_workstation_log(
                        workstation_id=uuid.uuid4(),
                        overwrite=False,
                        current_user=MagicMock(
                            role=MagicMock(value="admin"), email="a@b.com"
                        ),
                        db=MagicMock(),
                    )

                assert exc_info.value.status_code == 422
                assert "base64" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_respuesta_workstation_error_retorna_500(
        self, mock_connection_manager
    ):
        """
        WHEN la workstation responde con success=False,
        THEN el backend retorna HTTP 500 con el mensaje de error.
        Validates: Requirement 1.3
        """
        response = {
            "command_id": str(uuid.uuid4()),
            "success": False,
            "output": "Archivo de log no encontrado",
        }

        mock_connection_manager.wait_for_command_response = AsyncMock(
            return_value=response
        )

        with patch(
            "app.api.v1.endpoints.log_analysis._verify_workstation_access"
        ) as mock_verify:
            mock_ws = MagicMock()
            mock_ws.organization_id = uuid.uuid4()
            mock_verify.return_value = mock_ws

            with patch(
                "app.api.v1.endpoints.log_analysis.LogAnalysisService"
            ) as mock_svc_cls:
                mock_svc = MagicMock()
                mock_svc.get_today_analysis.return_value = None
                mock_svc_cls.return_value = mock_svc

                from fastapi import HTTPException

                with pytest.raises(HTTPException) as exc_info:
                    await analyze_workstation_log(
                        workstation_id=uuid.uuid4(),
                        overwrite=False,
                        current_user=MagicMock(
                            role=MagicMock(value="admin"), email="a@b.com"
                        ),
                        db=MagicMock(),
                    )

                assert exc_info.value.status_code == 500
                assert "Archivo de log no encontrado" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_respuesta_output_none_retorna_422(self, mock_connection_manager):
        """
        WHEN la workstation responde con output=None,
        THEN el backend maneja correctamente y retorna HTTP 422.
        Validates: Requirement 1.3
        """
        response = {
            "command_id": str(uuid.uuid4()),
            "success": True,
            "output": None,
        }

        mock_connection_manager.wait_for_command_response = AsyncMock(
            return_value=response
        )

        with patch(
            "app.api.v1.endpoints.log_analysis._verify_workstation_access"
        ) as mock_verify:
            mock_ws = MagicMock()
            mock_ws.organization_id = uuid.uuid4()
            mock_verify.return_value = mock_ws

            with patch(
                "app.api.v1.endpoints.log_analysis.LogAnalysisService"
            ) as mock_svc_cls:
                mock_svc = MagicMock()
                mock_svc.get_today_analysis.return_value = None
                mock_svc_cls.return_value = mock_svc

                from fastapi import HTTPException

                with pytest.raises(HTTPException) as exc_info:
                    await analyze_workstation_log(
                        workstation_id=uuid.uuid4(),
                        overwrite=False,
                        current_user=MagicMock(
                            role=MagicMock(value="admin"), email="a@b.com"
                        ),
                        db=MagicMock(),
                    )

                # Debería retornar 422 porque no hay contenido
                assert exc_info.value.status_code == 422
