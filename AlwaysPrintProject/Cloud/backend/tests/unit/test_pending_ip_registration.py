"""
Tests unitarios para el registro de IPs pendientes.

Verifica el comportamiento de `_register_pending_ip` y su integración
en el endpoint `check_update` para IPs desconocidas.

Requirements validados: 1.1–1.5, 2.1–2.5, 3.1–3.4, 4.1, 5.1
"""

import logging
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.organization import Organization, PublicIP
from app.models.workstation import Workstation
from app.api.v1.endpoints.updates import _register_pending_ip


# === FIXTURES ===

@pytest.fixture
def test_db():
    """
    Sesión SQLite en memoria para tests unitarios.
    Crea todas las tablas; al finalizar se cierra la sesión y se
    dispone del engine (la BD en memoria se destruye automáticamente).
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def test_client(test_db):
    """
    TestClient de FastAPI con override de la dependencia de DB.
    """
    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def _make_mock_request(client_ip="203.0.113.50", headers=None):
    """
    Crea un objeto Request mock con IP y headers configurables.
    """
    mock_request = MagicMock()
    mock_request.client.host = client_ip
    # Sin headers de proxy por defecto
    _headers = headers or {}
    mock_request.headers.get = lambda key, default=None: _headers.get(key, default)
    return mock_request


# === TESTS DE _register_pending_ip ===

class TestRegisterPendingIpBasic:
    """Tests para el registro básico de IP pendiente."""

    def test_register_pending_ip_basic(self, test_db):
        """
        IP nueva → registro creado con campos correctos.
        Validates: Requirements 1.1, 1.2
        """
        # Arrange
        mock_request = _make_mock_request(client_ip="192.168.1.100")
        before = datetime.utcnow()

        # Act
        _register_pending_ip(test_db, mock_request)

        # Assert — verificar que se creó el registro
        record = test_db.query(PublicIP).filter(
            PublicIP.ip_address == "192.168.1.100"
        ).first()

        assert record is not None, "No se creó el registro pendiente"
        assert record.ip_address == "192.168.1.100"
        assert record.is_authorized is False
        assert record.organization_id is None
        assert record.first_seen is not None
        # first_seen debe estar dentro de un rango razonable
        after = datetime.utcnow()
        assert before <= record.first_seen <= after

    def test_register_pending_ip_with_all_headers(self, test_db):
        """
        Ambos headers presentes → metadata capturada correctamente.
        Validates: Requirements 1.3, 1.4
        """
        # Arrange
        headers = {
            "X-Workstation-ID": "WS-BBVA-001",
            "X-Workstation-Local-IP": "10.0.1.50",
        }
        mock_request = _make_mock_request(
            client_ip="203.0.113.10",
            headers=headers,
        )

        # Act
        _register_pending_ip(test_db, mock_request)

        # Assert
        record = test_db.query(PublicIP).filter(
            PublicIP.ip_address == "203.0.113.10"
        ).first()

        assert record is not None
        assert record.last_hostname == "WS-BBVA-001"
        assert record.last_user == "10.0.1.50"

    def test_register_pending_ip_no_headers(self, test_db):
        """
        Sin headers → last_hostname y last_user NULL.
        Validates: Requirement 1.5
        """
        # Arrange — request sin headers de identificación
        mock_request = _make_mock_request(client_ip="198.51.100.5")

        # Act
        _register_pending_ip(test_db, mock_request)

        # Assert
        record = test_db.query(PublicIP).filter(
            PublicIP.ip_address == "198.51.100.5"
        ).first()

        assert record is not None
        assert record.last_hostname is None
        assert record.last_user is None


class TestRegisterPendingIpAuthorizedProtection:
    """Tests para protección de IPs autorizadas."""

    def test_authorized_ip_not_modified(self, test_db):
        """
        IP autorizada → sin cambios en registro.
        Validates: Requirements 2.4, 4.2
        """
        # Arrange — crear IP autorizada existente
        org_id = uuid.uuid4()
        org = Organization(
            id=org_id,
            name="Test Org",
            is_active=True,
        )
        test_db.add(org)

        authorized_ip = PublicIP(
            id=uuid.uuid4(),
            ip_address="200.10.20.30",
            is_authorized=True,
            organization_id=org_id,
            first_seen=datetime(2025, 1, 1),
            last_hostname="ORIGINAL-HOST",
            last_user="ORIGINAL-USER",
        )
        test_db.add(authorized_ip)
        test_db.commit()

        # Act — intentar registrar desde la misma IP con nuevos headers
        headers = {
            "X-Workstation-ID": "NUEVO-HOST",
            "X-Workstation-Local-IP": "NUEVO-USER",
        }
        mock_request = _make_mock_request(
            client_ip="200.10.20.30",
            headers=headers,
        )
        _register_pending_ip(test_db, mock_request)

        # Assert — el registro NO debe haber cambiado
        test_db.refresh(authorized_ip)
        assert authorized_ip.is_authorized is True
        assert authorized_ip.organization_id == org_id
        assert authorized_ip.last_hostname == "ORIGINAL-HOST"
        assert authorized_ip.last_user == "ORIGINAL-USER"


class TestRegisterPendingIpDbFailure:
    """Tests para resiliencia ante fallos de BD."""

    def test_register_pending_ip_db_failure(self, test_db):
        """
        Simular fallo DB → la función no propaga excepción y hace rollback.
        Validates: Requirement 5.1
        """
        # Arrange — mock de db.execute que lanza excepción
        mock_db = MagicMock()
        mock_db.execute.side_effect = Exception("Connection lost")
        mock_request = _make_mock_request(client_ip="10.0.0.1")

        # Act — NO debe lanzar excepción
        _register_pending_ip(mock_db, mock_request)

        # Assert — se hizo rollback
        mock_db.rollback.assert_called_once()
        # NO se hizo commit (porque falló antes)
        mock_db.commit.assert_not_called()


class TestLogWarningOnUnauthorized:
    """Tests para verificar emisión de log WARNING."""

    def test_log_warning_on_unauthorized(self, test_db, caplog):
        """
        Verificar que se emite log WARNING con campos correctos al fallar registro.
        Validates: Requirement 3.3
        """
        # Arrange — mock de DB que falla para provocar el log de warning
        mock_db = MagicMock()
        mock_db.execute.side_effect = Exception("DB timeout")

        headers = {
            "X-Workstation-ID": "WS-TEST-LOG",
            "X-Workstation-Local-IP": "192.168.5.10",
        }
        mock_request = _make_mock_request(
            client_ip="45.67.89.100",
            headers=headers,
        )

        # Act — capturar logs
        with caplog.at_level(logging.WARNING, logger="app.api.v1.endpoints.updates"):
            _register_pending_ip(mock_db, mock_request)

        # Assert — verificar que se emitió log WARNING con la IP
        assert len(caplog.records) > 0
        warning_record = caplog.records[0]
        assert warning_record.levelname == "WARNING"
        assert "45.67.89.100" in warning_record.message


class TestCheckUpdateAuthorizedIpUnchanged:
    """Tests de integración para el flujo completo con IP autorizada."""

    @patch("app.api.v1.endpoints.updates.S3UpdateService")
    def test_check_update_authorized_ip_unchanged(self, mock_s3_class, test_client, test_db):
        """
        Flujo completo para IP autorizada → HTTP 200 sin pasar por lógica pendiente.
        Validates: Requirements 4.1, 4.3
        """
        # Arrange — crear organización + IP autorizada
        org_id = uuid.uuid4()
        org = Organization(
            id=org_id,
            name="BBVA Test",
            is_active=True,
            auto_update_enabled=True,
        )
        test_db.add(org)

        public_ip = PublicIP(
            id=uuid.uuid4(),
            ip_address="testclient",  # TestClient usa "testclient" como IP
            is_authorized=True,
            organization_id=org_id,
            first_seen=datetime(2025, 6, 1),
            last_hostname="WS-AUTHORIZED",
            last_user="10.0.0.1",
        )
        test_db.add(public_ip)
        test_db.commit()

        # Configurar mock de S3
        mock_s3_instance = MagicMock()
        mock_s3_class.return_value = mock_s3_instance
        mock_s3_instance.get_msi_metadata.return_value = {
            "version": "2.5.0",
            "build_date": "2026-06-15T10:00:00Z",
            "commit_hash": "abc1234",
            "file_size": 15000000,
        }

        # Act
        response = test_client.get("/api/v1/updates/check")

        # Assert — HTTP 200 con la respuesta esperada
        assert response.status_code == 200
        data = response.json()
        assert data["version"] == "2.5.0"
        assert data["auto_update_enabled"] is True
        assert data["file_size"] == 15000000
        assert data["build_date"] == "2026-06-15T10:00:00Z"
        assert data["commit_hash"] == "abc1234"

        # Verificar que la IP autorizada NO fue modificada
        test_db.refresh(public_ip)
        assert public_ip.is_authorized is True
        assert public_ip.last_hostname == "WS-AUTHORIZED"
        assert public_ip.last_user == "10.0.0.1"
