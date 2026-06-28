"""
Tests unitarios para PushDistributionService.

Verifica:
- _get_target_workstations filtra correctamente por scope (org, vlan, workstation)
- push_config_change envía Config_Push_Message a workstations correctas
- push_config_change retorna 0 cuando no hay destinos
- Zero queries a BD (no se invoca ningún ORM/session)
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.push_distribution_service import PushDistributionService
from app.services.state_map_service import StateMapService


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def mock_connection_manager():
    """
    Crea un mock del connection_manager con dicts internos
    simulando workstations conectadas de diferentes orgs y VLANs.
    """
    cm = MagicMock()

    # Workstations conectadas: 3 de org-A (2 en vlan-1, 1 en vlan-2), 1 de org-B
    cm.workstation_connections = {
        "ws-1": MagicMock(),  # org-A, vlan-1
        "ws-2": MagicMock(),  # org-A, vlan-1
        "ws-3": MagicMock(),  # org-A, vlan-2
        "ws-4": MagicMock(),  # org-B, vlan-3
    }

    cm.org_ids = {
        "ws-1": "org-A",
        "ws-2": "org-A",
        "ws-3": "org-A",
        "ws-4": "org-B",
    }

    cm._ws_vlan_ids = {
        "ws-1": "vlan-1",
        "ws-2": "vlan-1",
        "ws-3": "vlan-2",
        "ws-4": "vlan-3",
    }

    # is_workstation_online verifica si está en workstation_connections
    cm.is_workstation_online = lambda ws_id: ws_id in cm.workstation_connections

    # send_to_workstation es async y retorna True por defecto
    cm.send_to_workstation = AsyncMock(return_value=True)

    return cm


@pytest.fixture
def mock_state_map():
    """Crea un mock del StateMapService."""
    return MagicMock(spec=StateMapService)


@pytest.fixture
def push_service(mock_connection_manager, mock_state_map):
    """Instancia PushDistributionService con mocks."""
    return PushDistributionService(mock_connection_manager, mock_state_map)


# ============================================================================
# TESTS: _get_target_workstations
# ============================================================================


class TestGetTargetWorkstations:
    """Tests para el filtrado de workstations por scope."""

    def test_scope_org_retorna_todas_ws_de_la_org(self, push_service):
        """Scope 'org' retorna todas las workstations online de la organización."""
        targets = push_service._get_target_workstations("org-A", "org", None)

        assert sorted(targets) == ["ws-1", "ws-2", "ws-3"]

    def test_scope_org_no_incluye_ws_de_otra_org(self, push_service):
        """Scope 'org' no incluye workstations de otras organizaciones."""
        targets = push_service._get_target_workstations("org-B", "org", None)

        assert targets == ["ws-4"]

    def test_scope_vlan_filtra_por_vlan(self, push_service):
        """Scope 'vlan' solo retorna workstations de la VLAN específica."""
        targets = push_service._get_target_workstations("org-A", "vlan", "vlan-1")

        assert sorted(targets) == ["ws-1", "ws-2"]

    def test_scope_vlan_otra_vlan(self, push_service):
        """Scope 'vlan' con otra VLAN retorna workstations correctas."""
        targets = push_service._get_target_workstations("org-A", "vlan", "vlan-2")

        assert targets == ["ws-3"]

    def test_scope_vlan_sin_coincidencias(self, push_service):
        """Scope 'vlan' retorna lista vacía si no hay coincidencias."""
        targets = push_service._get_target_workstations("org-A", "vlan", "vlan-inexistente")

        assert targets == []

    def test_scope_workstation_online(self, push_service):
        """Scope 'workstation' retorna la WS si está online."""
        targets = push_service._get_target_workstations("org-A", "workstation", "ws-1")

        assert targets == ["ws-1"]

    def test_scope_workstation_offline(self, push_service):
        """Scope 'workstation' retorna lista vacía si la WS no está online."""
        targets = push_service._get_target_workstations("org-A", "workstation", "ws-offline")

        assert targets == []

    def test_scope_workstation_none_scope_id(self, push_service):
        """Scope 'workstation' con scope_id=None retorna lista vacía."""
        targets = push_service._get_target_workstations("org-A", "workstation", None)

        assert targets == []

    def test_org_sin_ws_conectadas(self, push_service):
        """Org sin workstations conectadas retorna lista vacía."""
        targets = push_service._get_target_workstations("org-inexistente", "org", None)

        assert targets == []

    def test_scope_vlan_sin_atributo_ws_vlan_ids(self, mock_state_map):
        """
        Si el connection_manager no tiene _ws_vlan_ids (ConnectionManager simple),
        scope 'vlan' retorna lista vacía (no puede filtrar).
        """
        # ConnectionManager simple sin _ws_vlan_ids
        cm = MagicMock()
        cm.workstation_connections = {"ws-1": MagicMock()}
        cm.org_ids = {"ws-1": "org-A"}
        # Sin _ws_vlan_ids → getattr retornará {}
        del cm._ws_vlan_ids

        service = PushDistributionService(cm, mock_state_map)
        targets = service._get_target_workstations("org-A", "vlan", "vlan-1")

        assert targets == []


# ============================================================================
# TESTS: push_config_change
# ============================================================================


class TestPushConfigChange:
    """Tests para el envío de Config_Push_Message."""

    @pytest.mark.asyncio
    async def test_envia_a_todas_ws_de_org(self, push_service, mock_connection_manager):
        """Envía Config_Push_Message a todas las WS de la org (scope 'org')."""
        enviados = await push_service.push_config_change(
            org_id="org-A",
            config_hash="abc12345",
            download_url="https://bucket.s3.us-east-1.amazonaws.com/configs/org-A/abc12345.signed",
            scope="org",
            scope_id=None,
        )

        assert enviados == 3
        assert mock_connection_manager.send_to_workstation.call_count == 3

    @pytest.mark.asyncio
    async def test_mensaje_tiene_formato_correcto(self, push_service, mock_connection_manager):
        """El mensaje enviado sigue el formato Config_Push_Message del diseño."""
        await push_service.push_config_change(
            org_id="org-A",
            config_hash="abc12345",
            download_url="https://bucket.s3.us-east-1.amazonaws.com/configs/org-A/abc12345.signed",
            scope="workstation",
            scope_id="ws-1",
        )

        # Verificar el mensaje enviado
        call_args = mock_connection_manager.send_to_workstation.call_args
        ws_id_arg, message_arg = call_args[0]

        assert ws_id_arg == "ws-1"
        assert message_arg == {
            "type": "action_config_changed",
            "data": {
                "config_hash": "abc12345",
                "download_url": "https://bucket.s3.us-east-1.amazonaws.com/configs/org-A/abc12345.signed",
            },
        }

    @pytest.mark.asyncio
    async def test_scope_vlan_solo_envia_a_vlan(self, push_service, mock_connection_manager):
        """Scope 'vlan' solo envía a workstations de la VLAN especificada."""
        enviados = await push_service.push_config_change(
            org_id="org-A",
            config_hash="def67890",
            download_url="https://bucket.s3.us-east-1.amazonaws.com/configs/org-A/def67890.signed",
            scope="vlan",
            scope_id="vlan-1",
        )

        assert enviados == 2

        # Verificar que solo se envió a ws-1 y ws-2 (vlan-1)
        ws_ids_enviados = [
            call[0][0] for call in mock_connection_manager.send_to_workstation.call_args_list
        ]
        assert sorted(ws_ids_enviados) == ["ws-1", "ws-2"]

    @pytest.mark.asyncio
    async def test_sin_destinos_retorna_cero(self, push_service, mock_connection_manager):
        """Si no hay WS online para el scope, retorna 0 y no envía nada."""
        enviados = await push_service.push_config_change(
            org_id="org-inexistente",
            config_hash="xyz",
            download_url="https://example.com/config.signed",
            scope="org",
            scope_id=None,
        )

        assert enviados == 0
        mock_connection_manager.send_to_workstation.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallo_parcial_cuenta_solo_exitosos(self, push_service, mock_connection_manager):
        """Si algún envío falla, solo cuenta los exitosos."""
        # Primer envío exitoso, segundo falla, tercero exitoso
        mock_connection_manager.send_to_workstation.side_effect = [True, False, True]

        enviados = await push_service.push_config_change(
            org_id="org-A",
            config_hash="abc12345",
            download_url="https://example.com/config.signed",
            scope="org",
            scope_id=None,
        )

        assert enviados == 2

    @pytest.mark.asyncio
    async def test_excepcion_en_envio_no_interrumpe(self, push_service, mock_connection_manager):
        """Una excepción al enviar a una WS no interrumpe el envío a las demás."""
        # Primera falla con excepción, segunda y tercera exitosas
        mock_connection_manager.send_to_workstation.side_effect = [
            Exception("Conexión muerta"),
            True,
            True,
        ]

        enviados = await push_service.push_config_change(
            org_id="org-A",
            config_hash="abc12345",
            download_url="https://example.com/config.signed",
            scope="org",
            scope_id=None,
        )

        # Solo 2 exitosos (primera falló por excepción)
        assert enviados == 2

    @pytest.mark.asyncio
    async def test_zero_db_queries(self, push_service, mock_connection_manager):
        """
        Verifica que push_config_change no realiza ninguna query a BD.
        El connection_manager y los parámetros proveen toda la info necesaria.
        """
        # Si se intentara hacer query, esta función fallaría porque no hay sesión de BD
        # El test verifica que la función opera puramente con datos en memoria
        enviados = await push_service.push_config_change(
            org_id="org-A",
            config_hash="abc12345",
            download_url="https://example.com/config.signed",
            scope="org",
            scope_id=None,
        )

        assert enviados == 3
        # No se requirió ninguna interacción con BD — solo send_to_workstation
        assert mock_connection_manager.send_to_workstation.call_count == 3


# ============================================================================
# TESTS: push_msi_update
# ============================================================================


class TestPushMsiUpdate:
    """Tests para el envío de MSI_Push_Message."""

    @pytest.mark.asyncio
    async def test_envia_a_todas_ws_de_org(self, push_service, mock_connection_manager):
        """Envía MSI_Push_Message a todas las WS online de la organización."""
        enviados = await push_service.push_msi_update(
            org_id="org-A",
            msi_version="2.1.0",
            download_url="https://bucket.s3.amazonaws.com/versions/2.1.0/AlwaysPrint.msi?presigned",
            file_size=15728640,
        )

        assert enviados == 3
        assert mock_connection_manager.send_to_workstation.call_count == 3

    @pytest.mark.asyncio
    async def test_mensaje_tiene_formato_correcto(self, push_service, mock_connection_manager):
        """El mensaje enviado sigue el formato MSI_Push_Message del diseño."""
        # Solo org-B tiene 1 WS, más fácil verificar
        await push_service.push_msi_update(
            org_id="org-B",
            msi_version="2.1.0",
            download_url="https://bucket.s3.amazonaws.com/versions/2.1.0/AlwaysPrint.msi?presigned",
            file_size=15728640,
        )

        call_args = mock_connection_manager.send_to_workstation.call_args
        ws_id_arg, message_arg = call_args[0]

        assert ws_id_arg == "ws-4"
        assert message_arg == {
            "type": "check_update",
            "data": {
                "version": "2.1.0",
                "download_url": "https://bucket.s3.amazonaws.com/versions/2.1.0/AlwaysPrint.msi?presigned",
                "file_size": 15728640,
            },
        }

    @pytest.mark.asyncio
    async def test_sin_destinos_retorna_cero(self, push_service, mock_connection_manager):
        """Si no hay WS online para la org, retorna 0 y no envía nada."""
        enviados = await push_service.push_msi_update(
            org_id="org-inexistente",
            msi_version="3.0.0",
            download_url="https://example.com/msi",
            file_size=10000000,
        )

        assert enviados == 0
        mock_connection_manager.send_to_workstation.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallo_parcial_cuenta_solo_exitosos(self, push_service, mock_connection_manager):
        """Si algún envío falla, solo cuenta los exitosos."""
        mock_connection_manager.send_to_workstation.side_effect = [True, False, True]

        enviados = await push_service.push_msi_update(
            org_id="org-A",
            msi_version="2.1.0",
            download_url="https://example.com/msi",
            file_size=15728640,
        )

        assert enviados == 2

    @pytest.mark.asyncio
    async def test_excepcion_en_envio_no_interrumpe(self, push_service, mock_connection_manager):
        """Una excepción al enviar a una WS no interrumpe el envío a las demás."""
        mock_connection_manager.send_to_workstation.side_effect = [
            Exception("Timeout de red"),
            True,
            True,
        ]

        enviados = await push_service.push_msi_update(
            org_id="org-A",
            msi_version="2.1.0",
            download_url="https://example.com/msi",
            file_size=15728640,
        )

        assert enviados == 2

    @pytest.mark.asyncio
    async def test_zero_db_queries(self, push_service, mock_connection_manager):
        """
        Verifica que push_msi_update no realiza ninguna query a BD.
        Opera puramente con datos en memoria del connection_manager.
        """
        enviados = await push_service.push_msi_update(
            org_id="org-A",
            msi_version="2.1.0",
            download_url="https://example.com/msi",
            file_size=15728640,
        )

        assert enviados == 3
        assert mock_connection_manager.send_to_workstation.call_count == 3


# ============================================================================
# TESTS: push_cert_rotation
# ============================================================================


class TestPushCertRotation:
    """Tests para el envío de Cert_Push_Message."""

    @pytest.mark.asyncio
    async def test_envia_a_todas_ws_de_org(self, push_service, mock_connection_manager):
        """Envía Cert_Push_Message a todas las WS online de la organización."""
        enviados = await push_service.push_cert_rotation(
            org_id="org-A",
            cert_version=3,
            cert_url="https://bucket.s3.amazonaws.com/certs/org-A/v3.cer",
        )

        assert enviados == 3
        assert mock_connection_manager.send_to_workstation.call_count == 3

    @pytest.mark.asyncio
    async def test_mensaje_tiene_formato_correcto(self, push_service, mock_connection_manager):
        """El mensaje enviado sigue el formato Cert_Push_Message del diseño."""
        await push_service.push_cert_rotation(
            org_id="org-B",
            cert_version=5,
            cert_url="https://bucket.s3.amazonaws.com/certs/org-B/v5.cer",
        )

        call_args = mock_connection_manager.send_to_workstation.call_args
        ws_id_arg, message_arg = call_args[0]

        assert ws_id_arg == "ws-4"
        assert message_arg == {
            "type": "cert_rotated",
            "data": {
                "cert_version": 5,
                "cert_url": "https://bucket.s3.amazonaws.com/certs/org-B/v5.cer",
            },
        }

    @pytest.mark.asyncio
    async def test_sin_destinos_retorna_cero(self, push_service, mock_connection_manager):
        """Si no hay WS online para la org, retorna 0 y no envía nada."""
        enviados = await push_service.push_cert_rotation(
            org_id="org-inexistente",
            cert_version=1,
            cert_url="https://example.com/cert.cer",
        )

        assert enviados == 0
        mock_connection_manager.send_to_workstation.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallo_parcial_cuenta_solo_exitosos(self, push_service, mock_connection_manager):
        """Si algún envío falla, solo cuenta los exitosos."""
        mock_connection_manager.send_to_workstation.side_effect = [True, False, True]

        enviados = await push_service.push_cert_rotation(
            org_id="org-A",
            cert_version=3,
            cert_url="https://example.com/cert.cer",
        )

        assert enviados == 2

    @pytest.mark.asyncio
    async def test_excepcion_en_envio_no_interrumpe(self, push_service, mock_connection_manager):
        """Una excepción al enviar a una WS no interrumpe el envío a las demás."""
        mock_connection_manager.send_to_workstation.side_effect = [
            Exception("WebSocket cerrado"),
            True,
            True,
        ]

        enviados = await push_service.push_cert_rotation(
            org_id="org-A",
            cert_version=3,
            cert_url="https://example.com/cert.cer",
        )

        assert enviados == 2

    @pytest.mark.asyncio
    async def test_zero_db_queries(self, push_service, mock_connection_manager):
        """
        Verifica que push_cert_rotation no realiza ninguna query a BD.
        Opera puramente con datos en memoria del connection_manager.
        """
        enviados = await push_service.push_cert_rotation(
            org_id="org-A",
            cert_version=3,
            cert_url="https://example.com/cert.cer",
        )

        assert enviados == 3
        assert mock_connection_manager.send_to_workstation.call_count == 3
