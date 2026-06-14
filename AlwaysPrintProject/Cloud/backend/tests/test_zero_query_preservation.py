"""
Property test: Preservation - Flujo legacy y timer 24h sin cambios.

Verifica que los endpoints individuales `/api/v1/updates/check` y `/api/v1/updates/download`
siguen funcionando sin cambios para requests de workstations individuales.

Estos tests DEBEN PASAR tanto antes como después del fix para confirmar que:
1. El endpoint /updates/check sigue respondiendo correctamente a workstations individuales
2. El endpoint /updates/download sigue verificando flags y sirviendo el MSI
3. Con auto_update_enabled=false, /updates/download retorna 403
4. La identificación de workstation por IP pública sigue funcionando

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
from hypothesis import given, settings as hypothesis_settings, assume
from hypothesis import strategies as st
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import get_current_user
from app.models.organization import Organization, PublicIP, GUID
from app.models.workstation import Workstation
from app.models.user import User, UserRole
from app.main import app

# Deshabilitar rate limiting para los tests de preservación
# (el rate limiter interfiere con property-based testing que ejecuta muchas iteraciones)
from app.core.config import settings as app_settings
app_settings.RATE_LIMIT_API = 100000


# === MOCK DE AUTENTICACIÓN ===

mock_admin_user = User(
    id=uuid.uuid4(),
    email="admin@preservation-test.com",
    password_hash="hashed",
    full_name="Admin Preservation",
    role=UserRole.ADMIN,
    is_active=True,
)


async def override_get_current_user():
    """Dependencia sobreescrita que siempre retorna un usuario admin."""
    return mock_admin_user


def create_test_db():
    """Crea un engine y session factory frescos por cada iteración del test."""
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=test_engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    return test_engine, session_factory


# === ESTRATEGIAS DE GENERACIÓN ===

# Versiones semánticas para MSI
version_strategy = st.from_regex(r"[1-9]\.[0-9]{1,2}\.[0-9]{1,3}\.[0-9]{1,4}", fullmatch=True)

# Tamaños de archivo realistas (1MB a 100MB)
file_size_strategy = st.integers(min_value=1_000_000, max_value=100_000_000)

# IPs privadas para workstations
ip_strategy = st.tuples(
    st.integers(min_value=1, max_value=254),
    st.integers(min_value=0, max_value=254),
    st.integers(min_value=0, max_value=254),
    st.integers(min_value=1, max_value=254),
).map(lambda t: f"10.{t[1]}.{t[2]}.{t[3]}")


# === MOCK DE S3 ===

def create_s3_mock(version: str = "1.26.518.2152", file_size: int = 45_000_000):
    """Crea un mock del S3UpdateService con metadata realista."""
    mock_s3 = MagicMock()
    mock_s3.get_msi_metadata.return_value = {
        "version": version,
        "build_date": "2026-01-15T10:30:00Z",
        "commit_hash": "abc1234",
        "file_size": file_size,
    }
    # Mock para get_object (streaming del MSI)
    mock_body = MagicMock()
    mock_body.iter_chunks.return_value = iter([b"fake-msi-content"])
    mock_body.read.return_value = b"fake-msi-content"
    mock_s3.get_object.return_value = {
        "Body": mock_body,
        "ContentLength": file_size,
        "ContentType": "application/x-msi",
    }
    return mock_s3


# === PROPERTY TESTS - ENDPOINT /updates/check ===


@hypothesis_settings(max_examples=15, deadline=None)
@given(
    version=version_strategy,
    file_size=file_size_strategy,
    auto_update_enabled=st.booleans(),
)
def test_check_update_endpoint_responds_correctly_for_individual_workstation(
    version: str, file_size: int, auto_update_enabled: bool
):
    """
    Preservation Property: El endpoint GET /api/v1/updates/check responde correctamente
    para workstations individuales, retornando versión, flag y metadata del MSI.

    Para cualquier combinación de (versión disponible, flag auto_update, workstation individual),
    el endpoint DEBE retornar 200 con UpdateCheckResponse válido.

    Este comportamiento NO debe cambiar con el fix de zero-query (el fix solo afecta broadcast).

    **Validates: Requirements 3.2, 3.4**
    """
    test_engine, SessionFactory = create_test_db()

    def override_get_db():
        db = SessionFactory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    client = TestClient(app)

    db = SessionFactory()
    try:
        # Crear organización con el flag generado
        org_id = uuid.uuid4()
        org = Organization(
            id=org_id,
            name=f"test-org-{org_id}",
            is_active=True,
            auto_update_enabled=auto_update_enabled,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(org)
        db.flush()

        # Crear workstation individual
        ws_id = uuid.uuid4()
        ws = Workstation(
            id=ws_id,
            organization_id=org_id,
            ip_private="10.0.0.1",
            hostname="ws-individual-001",
            is_online=True,
            first_seen=datetime.now(timezone.utc).replace(tzinfo=None),
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(ws)

        # Registrar IP pública para identificación
        public_ip = PublicIP(
            ip_address="127.0.0.1",
            is_authorized=True,
            organization_id=org_id,
        )
        db.add(public_ip)
        db.commit()

        # Mockear S3 con la versión generada
        mock_s3 = create_s3_mock(version=version, file_size=file_size)

        with patch(
            "app.api.v1.endpoints.updates.S3UpdateService",
            return_value=mock_s3,
        ):
            # Ejecutar: workstation individual llama a /updates/check
            response = client.get(
                "/api/v1/updates/check",
                headers={
                    "X-Workstation-ID": str(ws_id),
                    "X-Workstation-Local-IP": "10.0.0.1",
                },
            )

            # Preservation: endpoint responde 200 con datos correctos
            assert response.status_code == 200, (
                f"Endpoint /updates/check retornó {response.status_code} en vez de 200. "
                f"Respuesta: {response.text}. "
                f"version={version}, auto_update={auto_update_enabled}"
            )

            data = response.json()

            # Verificar campos requeridos del response
            assert "version" in data, (
                f"Respuesta no contiene campo 'version': {data}"
            )
            assert "auto_update_enabled" in data, (
                f"Respuesta no contiene campo 'auto_update_enabled': {data}"
            )
            assert "file_size" in data, (
                f"Respuesta no contiene campo 'file_size': {data}"
            )

            # Verificar que el flag de organización se refleja correctamente
            assert data["auto_update_enabled"] == auto_update_enabled, (
                f"Flag auto_update_enabled no coincide: "
                f"esperado={auto_update_enabled}, obtenido={data['auto_update_enabled']}"
            )

            # Verificar que la versión retornada es la del MSI en S3
            assert data["version"] == version, (
                f"Versión no coincide: esperado={version}, obtenido={data['version']}"
            )

            # Verificar tamaño de archivo
            assert data["file_size"] == file_size, (
                f"Tamaño de archivo no coincide: "
                f"esperado={file_size}, obtenido={data['file_size']}"
            )

    finally:
        db.close()
        test_engine.dispose()


# === PROPERTY TESTS - ENDPOINT /updates/download ===


@hypothesis_settings(max_examples=10, deadline=None)
@given(
    version=version_strategy,
    file_size=file_size_strategy,
)
def test_download_update_endpoint_blocked_when_auto_update_disabled(
    version: str, file_size: int
):
    """
    Preservation Property: El endpoint GET /api/v1/updates/download retorna 403
    cuando auto_update_enabled=false para la organización.

    Para cualquier workstation cuya organización tiene auto_update_enabled=false,
    el endpoint DEBE retornar HTTP 403 Forbidden sin servir el archivo.

    Este comportamiento NO debe cambiar con el fix de zero-query.

    **Validates: Requirements 3.3, 3.5**
    """
    test_engine, SessionFactory = create_test_db()

    def override_get_db():
        db = SessionFactory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    client = TestClient(app)

    db = SessionFactory()
    try:
        # Crear organización con auto_update DESHABILITADO
        org_id = uuid.uuid4()
        org = Organization(
            id=org_id,
            name=f"test-org-disabled-{org_id}",
            is_active=True,
            auto_update_enabled=False,  # Flag deshabilitado
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(org)
        db.flush()

        # Crear workstation individual
        ws_id = uuid.uuid4()
        ws = Workstation(
            id=ws_id,
            organization_id=org_id,
            ip_private="10.0.0.50",
            hostname="ws-disabled-001",
            is_online=True,
            first_seen=datetime.now(timezone.utc).replace(tzinfo=None),
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(ws)

        # Registrar IP pública
        public_ip = PublicIP(
            ip_address="127.0.0.1",
            is_authorized=True,
            organization_id=org_id,
        )
        db.add(public_ip)
        db.commit()

        # Mockear S3
        mock_s3 = create_s3_mock(version=version, file_size=file_size)

        with patch(
            "app.api.v1.endpoints.updates.S3UpdateService",
            return_value=mock_s3,
        ):
            # Ejecutar: workstation intenta descargar con auto_update=false
            response = client.get(
                "/api/v1/updates/download",
                headers={
                    "X-Workstation-ID": str(ws_id),
                    "X-Workstation-Local-IP": "10.0.0.50",
                },
            )

            # Preservation: endpoint retorna 403 cuando auto_update está deshabilitado
            assert response.status_code == 403, (
                f"Endpoint /updates/download debería retornar 403 con auto_update=false, "
                f"pero retornó {response.status_code}. "
                f"Respuesta: {response.text}. "
                f"version={version}, file_size={file_size}"
            )

    finally:
        db.close()
        test_engine.dispose()


@hypothesis_settings(max_examples=10, deadline=None)
@given(
    version=version_strategy,
    file_size=file_size_strategy,
)
def test_download_update_endpoint_works_when_auto_update_enabled(
    version: str, file_size: int
):
    """
    Preservation Property: El endpoint GET /api/v1/updates/download sirve el MSI
    cuando auto_update_enabled=true para la organización.

    Para cualquier workstation cuya organización tiene auto_update_enabled=true,
    el endpoint DEBE servir el archivo MSI (streaming desde S3).

    Este comportamiento NO debe cambiar con el fix de zero-query (el endpoint individual
    sigue funcionando normalmente, es el broadcast el que se enriquece con presigned URL).

    **Validates: Requirements 3.4**
    """
    test_engine, SessionFactory = create_test_db()

    def override_get_db():
        db = SessionFactory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    client = TestClient(app)

    db = SessionFactory()
    try:
        # Crear organización con auto_update HABILITADO
        org_id = uuid.uuid4()
        org = Organization(
            id=org_id,
            name=f"test-org-enabled-{org_id}",
            is_active=True,
            auto_update_enabled=True,  # Flag habilitado
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(org)
        db.flush()

        # Crear workstation individual
        ws_id = uuid.uuid4()
        ws = Workstation(
            id=ws_id,
            organization_id=org_id,
            ip_private="10.0.0.100",
            hostname="ws-enabled-001",
            is_online=True,
            first_seen=datetime.now(timezone.utc).replace(tzinfo=None),
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(ws)

        # Registrar IP pública
        public_ip = PublicIP(
            ip_address="127.0.0.1",
            is_authorized=True,
            organization_id=org_id,
        )
        db.add(public_ip)
        db.commit()

        # Mockear S3 con streaming body
        mock_s3 = create_s3_mock(version=version, file_size=file_size)

        with patch(
            "app.api.v1.endpoints.updates.S3UpdateService",
            return_value=mock_s3,
        ):
            # Ejecutar: workstation descarga con auto_update=true
            response = client.get(
                "/api/v1/updates/download",
                headers={
                    "X-Workstation-ID": str(ws_id),
                    "X-Workstation-Local-IP": "10.0.0.100",
                },
            )

            # Preservation: endpoint sirve el archivo (200) cuando auto_update habilitado
            assert response.status_code == 200, (
                f"Endpoint /updates/download debería retornar 200 con auto_update=true, "
                f"pero retornó {response.status_code}. "
                f"Respuesta: {response.text}. "
                f"version={version}, file_size={file_size}"
            )

    finally:
        db.close()
        test_engine.dispose()


# === PROPERTY TEST - IDENTIFICACIÓN POR IP PÚBLICA (BACKWARD COMPAT) ===


@hypothesis_settings(max_examples=10, deadline=None)
@given(
    version=version_strategy,
    auto_update_enabled=st.booleans(),
)
def test_check_update_fallback_by_public_ip(
    version: str, auto_update_enabled: bool
):
    """
    Preservation Property: El endpoint /updates/check funciona con fallback por IP pública
    (clientes antiguos sin headers X-Workstation-ID).

    Para cualquier organización con IP pública registrada, el endpoint DEBE identificar
    la organización por IP pública cuando no se envían headers de workstation.

    **Validates: Requirements 3.1, 3.2**
    """
    test_engine, SessionFactory = create_test_db()

    def override_get_db():
        db = SessionFactory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    client = TestClient(app)

    db = SessionFactory()
    try:
        # Crear organización
        org_id = uuid.uuid4()
        org = Organization(
            id=org_id,
            name=f"test-org-fallback-{org_id}",
            is_active=True,
            auto_update_enabled=auto_update_enabled,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(org)
        db.flush()

        # Registrar IP pública con la IP que usa TestClient ("testclient")
        # para simular backward compatibility con clientes antiguos
        public_ip = PublicIP(
            ip_address="testclient",
            is_authorized=True,
            organization_id=org_id,
        )
        db.add(public_ip)
        db.commit()

        # Mockear S3
        mock_s3 = create_s3_mock(version=version)

        with patch(
            "app.api.v1.endpoints.updates.S3UpdateService",
            return_value=mock_s3,
        ):
            # Ejecutar: cliente antiguo SIN headers de workstation
            response = client.get("/api/v1/updates/check")

            # Preservation: endpoint funciona con fallback por IP pública
            assert response.status_code == 200, (
                f"Endpoint /updates/check con fallback por IP pública debería "
                f"retornar 200 pero retornó {response.status_code}. "
                f"Respuesta: {response.text}. "
                f"auto_update={auto_update_enabled}"
            )

            data = response.json()
            assert data["auto_update_enabled"] == auto_update_enabled, (
                f"Flag auto_update_enabled no coincide en fallback: "
                f"esperado={auto_update_enabled}, obtenido={data['auto_update_enabled']}"
            )

    finally:
        db.close()
        test_engine.dispose()
