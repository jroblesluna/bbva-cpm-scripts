"""
Property test: Update check response completeness.

Feature: auto-update, Property 5: Update check response completeness

Verifica que para cualquier metadata S3 válida (version string, file_size int positivo,
build_date, commit_hash) y cualquier estado auto_update_enabled (bool), la respuesta
del endpoint GET /api/v1/updates/check siempre contiene todos los campos requeridos:
version, auto_update_enabled, y file_size.

Validates: Requirements 6.2
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

from app.main import app
from app.core.database import get_db
from app.models.account import Account
from app.models.workstation import Workstation


# === ESTRATEGIAS: generar metadata S3 aleatoria ===

# Versión semántica aleatoria (ej: "1.2.3", "10.0.1")
version_strategy = st.from_regex(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}", fullmatch=True)

# Tamaño de archivo positivo (entre 1 byte y 500 MB)
file_size_strategy = st.integers(min_value=1, max_value=500_000_000)

# Fecha de build en formato ISO 8601 simplificado
build_date_strategy = st.from_regex(
    r"20[2-3][0-9]-[01][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z",
    fullmatch=True,
)

# Hash de commit (7 caracteres hexadecimales)
commit_hash_strategy = st.from_regex(r"[0-9a-f]{7}", fullmatch=True)

# Flag de auto-actualización de la organización
auto_update_enabled_strategy = st.booleans()


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
    mock_workstation.account_id = account_id
    mock_workstation.ip_private = "192.168.1.100"

    # Mock de la cuenta con el flag configurado
    mock_account = MagicMock(spec=Account)
    mock_account.id = account_id
    mock_account.name = "Organización Test"
    mock_account.auto_update_enabled = auto_update_enabled

    # Mock de la sesión de BD
    mock_db = MagicMock()

    # Configurar query().filter().first() para retornar workstation o account
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
class TestUpdateCheckResponseCompleteness:
    """
    Property 5: Update check response completeness.

    Para cualquier metadata S3 válida y cualquier estado auto_update_enabled,
    la respuesta del endpoint /api/v1/updates/check siempre contiene todos
    los campos requeridos: version, auto_update_enabled, y file_size.

    **Validates: Requirements 6.2**
    """

    @given(
        version=version_strategy,
        file_size=file_size_strategy,
        build_date=build_date_strategy,
        commit_hash=commit_hash_strategy,
        auto_update_enabled=auto_update_enabled_strategy,
    )
    @settings(max_examples=100)
    def test_response_contains_all_required_fields(
        self,
        version: str,
        file_size: int,
        build_date: str,
        commit_hash: str,
        auto_update_enabled: bool,
        _,
    ):
        """
        Propiedad: la respuesta del endpoint /updates/check siempre contiene
        todos los campos requeridos (version, auto_update_enabled, file_size)
        independientemente de los valores de la metadata S3 y el flag de organización.

        **Validates: Requirements 6.2**
        """
        # Crear sesión mock con el flag generado por Hypothesis
        mock_db = _create_mock_db_session(auto_update_enabled)

        # Sobreescribir la dependencia get_db para usar nuestro mock
        def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        try:
            # Crear cliente de test
            client = TestClient(app, raise_server_exceptions=False)

            # Mock de S3UpdateService para retornar la metadata generada
            with patch(
                "app.api.v1.endpoints.updates.S3UpdateService"
            ) as MockS3Service:
                mock_s3_instance = MagicMock()
                mock_s3_instance.get_msi_metadata.return_value = {
                    "version": version,
                    "file_size": file_size,
                    "build_date": build_date,
                    "commit_hash": commit_hash,
                }
                MockS3Service.return_value = mock_s3_instance

                # Realizar la solicitud al endpoint de verificación
                response = client.get(
                    "/api/v1/updates/check",
                    headers={"X-Workstation-ID": str(uuid.uuid4())},
                )

            # Verificar que la respuesta es exitosa (200)
            assert response.status_code == 200, (
                f"Se esperaba status 200, pero se obtuvo {response.status_code}. "
                f"Detalle: {response.text}"
            )

            # Obtener el JSON de la respuesta
            data = response.json()

            # === PROPIEDAD PRINCIPAL: todos los campos requeridos están presentes ===
            assert "version" in data, (
                f"Campo 'version' ausente en la respuesta. "
                f"Metadata S3: version={version}, file_size={file_size}"
            )
            assert "auto_update_enabled" in data, (
                f"Campo 'auto_update_enabled' ausente en la respuesta. "
                f"Flag organización: {auto_update_enabled}"
            )
            assert "file_size" in data, (
                f"Campo 'file_size' ausente en la respuesta. "
                f"Metadata S3: file_size={file_size}"
            )

            # Verificar que los valores coinciden con los datos generados
            assert data["version"] == version, (
                f"Valor de 'version' incorrecto: esperado={version}, "
                f"obtenido={data['version']}"
            )
            assert data["auto_update_enabled"] == auto_update_enabled, (
                f"Valor de 'auto_update_enabled' incorrecto: "
                f"esperado={auto_update_enabled}, obtenido={data['auto_update_enabled']}"
            )
            assert data["file_size"] == file_size, (
                f"Valor de 'file_size' incorrecto: esperado={file_size}, "
                f"obtenido={data['file_size']}"
            )

        finally:
            # Limpiar override de dependencias
            app.dependency_overrides.clear()
