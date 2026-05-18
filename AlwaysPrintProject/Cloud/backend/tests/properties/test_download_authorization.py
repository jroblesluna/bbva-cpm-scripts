"""
Property test: Download endpoint authorization.

Feature: auto-update, Property 6: Download endpoint authorization

Verifica que el endpoint GET /api/v1/updates/download retorna:
- 302 (redirect) si y solo si auto_update_enabled es True para la organización
- 403 (forbidden) si auto_update_enabled es False

Validates: Requirements 7.3, 7.4
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

from app.main import app
from app.core.database import get_db
from app.models.organization import Organization as Account
from app.models.workstation import Workstation


# === ESTRATEGIA: generar booleano para auto_update_enabled ===
auto_update_flag_strategy = st.booleans()


# === URL dummy para presigned URL de S3 ===
DUMMY_PRESIGNED_URL = "https://alwaysprint-artifacts.s3.amazonaws.com/latest/AlwaysPrint.msi?presigned=true"


def _create_mock_db_session(auto_update_enabled: bool):
    """
    Crea una sesión de BD mock que simula la identificación de workstation
    y la consulta de la cuenta con el flag auto_update_enabled configurado.

    Args:
        auto_update_enabled: Valor del flag de auto-actualización de la organización.

    Returns:
        Sesión mock de SQLAlchemy configurada para el escenario.
    """
    # Crear IDs fijos para la workstation y cuenta
    account_id = uuid.uuid4()
    workstation_id = uuid.uuid4()

    # Mock de la workstation
    mock_workstation = MagicMock(spec=Workstation)
    mock_workstation.id = workstation_id
    mock_workstation.organization_id = account_id
    mock_workstation.ip_private = "192.168.1.100"

    # Mock de la cuenta con el flag configurado
    mock_account = MagicMock(spec=Account)
    mock_account.id = account_id
    mock_account.name = "Organización Test"
    mock_account.auto_update_enabled = auto_update_enabled

    # Mock de la sesión de BD
    mock_db = MagicMock()

    # Configurar query().filter().first() para retornar workstation o account
    # según el modelo consultado
    def mock_query(model):
        query_mock = MagicMock()
        filter_mock = MagicMock()

        if model == Workstation:
            filter_mock.first.return_value = mock_workstation
        elif model == Account:
            filter_mock.first.return_value = mock_account
        else:
            filter_mock.first.return_value = None

        query_mock.filter.return_value = filter_mock
        return query_mock

    mock_db.query.side_effect = mock_query

    return mock_db


@pytest.mark.parametrize("_", [""])  # Marcador para pytest
class TestDownloadEndpointAuthorization:
    """
    Property 6: Download endpoint authorization.

    Para cualquier workstation perteneciente a una organización,
    el endpoint /api/v1/updates/download retorna:
    - 302 redirect si y solo si auto_update_enabled es True
    - 403 forbidden en caso contrario

    **Validates: Requirements 7.3, 7.4**
    """

    @given(auto_update_enabled=auto_update_flag_strategy)
    @settings(max_examples=100)
    def test_download_authorization_property(self, auto_update_enabled: bool, _):
        """
        Propiedad: el código de respuesta del endpoint /updates/download
        depende exclusivamente del flag auto_update_enabled de la organización.

        - Si auto_update_enabled=True → respuesta 302 (redirect a presigned URL)
        - Si auto_update_enabled=False → respuesta 403 (forbidden)

        **Validates: Requirements 7.3, 7.4**
        """
        # Crear sesión mock con el flag generado por Hypothesis
        mock_db = _create_mock_db_session(auto_update_enabled)

        # Sobreescribir la dependencia get_db para usar nuestro mock
        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        try:
            # Crear cliente de test con allow_redirects=False para capturar el 302
            client = TestClient(app, raise_server_exceptions=False)

            # Mock de S3UpdateService.generate_download_url para evitar llamadas reales a AWS
            with patch(
                "app.api.v1.endpoints.updates.S3UpdateService"
            ) as MockS3Service:
                mock_s3_instance = MagicMock()
                mock_s3_instance.generate_download_url.return_value = DUMMY_PRESIGNED_URL
                MockS3Service.return_value = mock_s3_instance

                # Realizar la solicitud al endpoint de descarga
                response = client.get(
                    "/api/v1/updates/download",
                    headers={"X-Workstation-ID": str(uuid.uuid4())},
                    follow_redirects=False,
                )

            # Verificar la propiedad: 302 si y solo si auto_update_enabled es True
            if auto_update_enabled:
                assert response.status_code == 302, (
                    f"Con auto_update_enabled=True se esperaba 302, "
                    f"pero se obtuvo {response.status_code}"
                )
                # Verificar que el redirect apunta a la URL presigned
                assert response.headers.get("location") == DUMMY_PRESIGNED_URL
            else:
                assert response.status_code == 403, (
                    f"Con auto_update_enabled=False se esperaba 403, "
                    f"pero se obtuvo {response.status_code}"
                )

        finally:
            # Limpiar solo el override de get_db que este test configuró
            app.dependency_overrides.pop(get_db, None)
