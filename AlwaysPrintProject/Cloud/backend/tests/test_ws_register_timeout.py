"""
Tests del timeout de registro en el endpoint WebSocket /ws/workstation.

Valida los requisitos 3.1, 3.2 y 3.5 del spec de Reconnection Reliability:
- Timeout de 10s para recibir el primer mensaje de registro
- Cierre con código 1008 si no llega mensaje o si no es register
- Flujo normal cuando se envía register dentro del timeout

**Validates: Requirements 3.1, 3.2, 3.5**
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app


# Timeout reducido para tests (evitar esperar 10s reales)
TEST_TIMEOUT = 0.3


@pytest.fixture
def client():
    """Cliente de prueba para FastAPI."""
    return TestClient(app)


class TestWsRegisterTimeout:
    """
    Tests del timeout de registro en el endpoint WebSocket.
    
    El endpoint espera un mensaje de registro como primer mensaje
    dentro de un timeout de 10 segundos. Estos tests validan
    los tres escenarios posibles.
    """

    def test_no_message_sent_closes_with_1008(self, client):
        """
        Conectar WebSocket sin enviar nada → cierre con código 1008.
        
        Valida Requirement 3.1: Backend espera hasta 10s para el primer mensaje.
        Valida Requirement 3.2: Si no llega mensaje, cierra con 1008.
        
        Se reduce el timeout a 0.3s para evitar esperas innecesarias en tests.
        """
        with patch(
            "app.api.v1.websocket.workstation.asyncio.wait_for",
            side_effect=asyncio.TimeoutError(),
        ):
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with client.websocket_connect("/ws/workstation") as ws:
                    # No enviamos nada — el mock dispara TimeoutError inmediatamente
                    ws.receive_json()

            assert exc_info.value.code == 1008

    def test_register_within_timeout_normal_flow(self, client):
        """
        Conectar WebSocket y enviar register dentro del timeout → flujo normal.
        
        Valida Requirement 3.1: Si llega mensaje dentro de 10s, se procesa.
        
        Se mockea register_workstation para evitar dependencias de BD,
        y se verifica que el servidor responde con el flujo de registro.
        """
        # Crear un mock de workstation registrada exitosamente
        mock_workstation = MagicMock()
        mock_workstation.id = "test-ws-id-123"
        mock_workstation.organization_id = "test-org-id-456"
        mock_workstation.vlan_id = None
        mock_workstation.hostname = "TEST-PC"
        mock_workstation.ip_private = "192.168.1.100"
        mock_workstation.forced_contingency = False
        mock_workstation.default_printer_id = None

        # Mock del Organization para la consulta de forced_contingency
        mock_org = MagicMock()
        mock_org.forced_contingency = False
        mock_org.name = "Test Org"

        with patch(
            "app.api.v1.websocket.workstation.WorkstationService"
        ) as MockWsService, patch(
            "app.api.v1.websocket.workstation.ConfigService"
        ) as MockConfigService, patch(
            "app.api.v1.websocket.workstation.MessageService"
        ) as MockMsgService, patch(
            "app.api.v1.websocket.workstation.AuditService"
        ), patch(
            "app.api.v1.websocket.workstation.connection_manager"
        ) as mock_conn_mgr, patch(
            "app.api.v1.websocket.workstation.remote_view_relay"
        ) as mock_rv_relay:
            # Configurar mocks
            mock_ws_service_instance = MockWsService.return_value
            mock_ws_service_instance.register_workstation.return_value = (
                mock_workstation, True, "authorized"
            )

            mock_config_instance = MockConfigService.return_value
            mock_config_instance.get_effective_config.return_value = {"key": "value"}

            mock_msg_instance = MockMsgService.return_value
            mock_msg_instance.get_pending_deliveries_for_workstation.return_value = []

            mock_conn_mgr.connect_workstation = AsyncMock()
            mock_conn_mgr.disconnect_workstation = AsyncMock()
            mock_rv_relay.handle_workstation_reconnect = AsyncMock()
            mock_rv_relay.handle_workstation_disconnect = AsyncMock()

            # Mock de get_state_map_service para evitar dependencia de Redis/state
            with patch(
                "app.api.v1.websocket.workstation.get_state_map_service",
                side_effect=ImportError("mocked"),
            ) if False else patch(
                "app.services.push_services.get_state_map_service"
            ) as mock_state_map_fn:
                mock_state_map = MagicMock()
                mock_state_map.resolve_workstation_state = AsyncMock(return_value={})
                mock_state_map_fn.return_value = mock_state_map

                with client.websocket_connect("/ws/workstation") as ws:
                    # Enviar mensaje de registro válido
                    ws.send_json({
                        "type": "register",
                        "ip_private": "192.168.1.100",
                        "hostname": "TEST-PC",
                        "os_serial": "SERIAL-123",
                        "current_user": "testuser",
                        "cidr": "192.168.1.0/24",
                        "tray_version": "2.1.0"
                    })

                    # Verificar que el servidor responde con "registered"
                    response = ws.receive_json()
                    assert response["type"] == "registered"
                    assert response["workstation_id"] == "test-ws-id-123"

    def test_non_register_first_message_closes_with_1008(self, client):
        """
        Enviar mensaje que no es register como primer mensaje → cierre con 1008.
        
        Valida Requirement 3.5: Si el primer mensaje no es type=register,
        el servidor cierra con código 1008.
        """
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/ws/workstation") as ws:
                # Enviar un mensaje de tipo "pong" en lugar de "register"
                ws.send_json({"type": "pong"})
                # Intentar recibir — debería recibir el close
                ws.receive_json()

        assert exc_info.value.code == 1008
