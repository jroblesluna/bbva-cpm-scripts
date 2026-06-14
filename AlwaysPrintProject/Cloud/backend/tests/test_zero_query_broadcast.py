"""
Property test: Bug Condition - Broadcast check_update sin download_url genera N queries al backend

Verifica que los endpoints `send_org_command` (POST /organizations/{id}/command?command_type=check_update)
y `toggle_auto_update` (PUT /organizations/{id}/auto-update con enabled=true) generan un mensaje
WebSocket con `params` que INCLUYE `download_url`, `version` y `file_size`.

Este test codifica el COMPORTAMIENTO ESPERADO (correcto). En código sin corregir,
DEBE FALLAR — confirmando que el bug existe (params actualmente es `{}` vacío).

Bug actual: el broadcast envía `"params": {}` a todas las workstations, forzando a cada una
a llamar individualmente a `/api/v1/updates/check` y `/api/v1/updates/download`,
saturando el pool de conexiones a BD (30 max) cuando N > 30 workstations.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4**
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock

import pytest
from hypothesis import given, settings as hypothesis_settings, assume
from hypothesis import strategies as st
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import get_current_user
from app.models.organization import Organization, GUID
from app.models.workstation import Workstation
from app.models.user import User, UserRole
from app.main import app


# === MOCK DE AUTENTICACIÓN ===

mock_admin_user = User(
    id=uuid.uuid4(),
    email="admin@test.com",
    password_hash="hashed",
    full_name="Admin Test",
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

# Genera número de workstations online (> pool_size de 30 para triggear bug condition)
num_workstations_strategy = st.integers(min_value=31, max_value=50)

# Genera IPs privadas para workstations
ip_strategy = st.tuples(
    st.integers(min_value=1, max_value=254),
    st.integers(min_value=0, max_value=254),
    st.integers(min_value=0, max_value=254),
    st.integers(min_value=1, max_value=254),
).map(lambda t: f"10.{t[1]}.{t[2]}.{t[3]}")


# === PROPERTY TESTS ===


@hypothesis_settings(max_examples=10, deadline=None)
@given(num_ws=num_workstations_strategy)
def test_send_org_command_check_update_includes_download_url(num_ws: int):
    """
    Property 1: Bug Condition - send_org_command con check_update DEBE incluir download_url en params.

    Para cualquier organización con N workstations online (N > 30) y auto_update_enabled=true,
    al enviar comando check_update via POST /organizations/{id}/command?command_type=check_update,
    el mensaje WebSocket enviado a cada workstation DEBE incluir en params:
    - download_url (presigned URL de S3)
    - version (versión del MSI)
    - file_size (tamaño del archivo > 0)

    Bug actual: params es siempre `{}` vacío, lo que genera N queries al backend
    (thundering herd cuando N > 30).

    **Validates: Requirements 1.1, 1.2, 1.3, 1.4**
    """
    # Crear engine y BD frescos por iteración (evita problemas de FK circulares en SQLite)
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
        # Crear organización con auto_update habilitado
        org_id = uuid.uuid4()
        org = Organization(
            id=org_id,
            name=f"test-org-{org_id}",
            is_active=True,
            auto_update_enabled=True,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(org)
        db.flush()

        # Crear N workstations para la organización
        for i in range(num_ws):
            ws_id = uuid.uuid4()
            ws = Workstation(
                id=ws_id,
                organization_id=org_id,
                ip_private=f"10.0.{i // 256}.{i % 256 + 1}",
                hostname=f"ws-{i:03d}",
                is_online=True,
                first_seen=datetime.now(timezone.utc).replace(tzinfo=None),
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            db.add(ws)
        db.commit()

        # Mockear connection_manager para capturar mensajes WebSocket enviados
        sent_messages = []

        async def capture_send(ws_id, message):
            sent_messages.append({"ws_id": ws_id, "message": message})

        with patch(
            "app.api.v1.endpoints.organizations.connection_manager"
        ) as mock_cm:
            mock_cm.is_workstation_online.return_value = True
            mock_cm.send_to_workstation = AsyncMock(side_effect=capture_send)

            # Mockear S3UpdateService para simular MSI disponible en S3
            mock_update_info = {
                "download_url": "https://s3.amazonaws.com/bucket/latest/AlwaysPrint.msi?presigned",
                "version": "1.26.518.2152",
                "file_size": 52428800,
            }
            with patch(
                "app.api.v1.endpoints.organizations.S3UpdateService"
            ) as mock_s3_cls:
                mock_s3_cls.return_value.get_broadcast_update_info.return_value = mock_update_info

                # Ejecutar: enviar comando check_update a la organización
                response = client.post(
                    f"/api/v1/organizations/{org_id}/command?command_type=check_update"
                )

                # El endpoint debe responder exitosamente
                assert response.status_code == 200, (
                    f"Endpoint retornó {response.status_code}: {response.json()}"
                )

                # Verificar que se enviaron mensajes a las workstations
                assert len(sent_messages) > 0, (
                    "No se enviaron mensajes WebSocket a ninguna workstation"
                )

                # COMPORTAMIENTO ESPERADO (después del fix):
                # Cada mensaje debe incluir download_url, version, file_size en params
                for msg_data in sent_messages:
                    message = msg_data["message"]
                    params = message.get("params", {})

                    assert params.get("download_url") is not None, (
                        f"Bug confirmado: params.download_url es None/ausente. "
                        f"Mensaje enviado: {message}. "
                        f"Con {num_ws} workstations online, cada una llamará "
                        f"individualmente a /api/v1/updates/check → thundering herd. "
                        f"params actual: {params}"
                    )

                    assert params.get("version") is not None, (
                        f"Bug confirmado: params.version es None/ausente. "
                        f"Mensaje enviado: {message}. "
                        f"params actual: {params}"
                    )

                    assert params.get("file_size") is not None and params.get("file_size", 0) > 0, (
                        f"Bug confirmado: params.file_size es None/ausente o <= 0. "
                        f"Mensaje enviado: {message}. "
                        f"params actual: {params}"
                    )

    finally:
        db.close()
        test_engine.dispose()


@hypothesis_settings(max_examples=10, deadline=None)
@given(num_ws=num_workstations_strategy)
def test_toggle_auto_update_enabled_includes_download_url(num_ws: int):
    """
    Property 1: Bug Condition - toggle_auto_update con enabled=true DEBE incluir download_url en params.

    Para cualquier organización con N workstations online (N > 30), al activar
    auto_update via PUT /organizations/{id}/auto-update con body {"enabled": true},
    el mensaje WebSocket broadcast a cada workstation DEBE incluir en params:
    - download_url (presigned URL de S3)
    - version (versión del MSI)
    - file_size (tamaño del archivo > 0)

    Bug actual: params es siempre `{}` vacío, generando N queries simultáneas al backend.

    **Validates: Requirements 1.1, 1.2, 1.3, 1.4**
    """
    # Crear engine y BD frescos por iteración
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
        # Crear organización con auto_update deshabilitado (se habilitará via endpoint)
        org_id = uuid.uuid4()
        org = Organization(
            id=org_id,
            name=f"test-org-{org_id}",
            is_active=True,
            auto_update_enabled=False,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(org)
        db.flush()

        # Crear N workstations para la organización
        for i in range(num_ws):
            ws_id = uuid.uuid4()
            ws = Workstation(
                id=ws_id,
                organization_id=org_id,
                ip_private=f"10.1.{i // 256}.{i % 256 + 1}",
                hostname=f"ws-{i:03d}",
                is_online=True,
                first_seen=datetime.now(timezone.utc).replace(tzinfo=None),
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            db.add(ws)
        db.commit()

        # Mockear connection_manager para capturar mensajes WebSocket enviados
        sent_messages = []

        async def capture_send(ws_id, message):
            sent_messages.append({"ws_id": ws_id, "message": message})

        with patch(
            "app.api.v1.endpoints.organizations.connection_manager"
        ) as mock_cm:
            mock_cm.is_workstation_online.return_value = True
            mock_cm.send_to_workstation = AsyncMock(side_effect=capture_send)

            # Mockear S3UpdateService para simular MSI disponible en S3
            mock_update_info = {
                "download_url": "https://s3.amazonaws.com/bucket/latest/AlwaysPrint.msi?presigned",
                "version": "1.26.518.2152",
                "file_size": 52428800,
            }
            with patch(
                "app.api.v1.endpoints.organizations.S3UpdateService"
            ) as mock_s3_cls:
                mock_s3_cls.return_value.get_broadcast_update_info.return_value = mock_update_info

                # Ejecutar: activar auto-update para la organización
                response = client.patch(
                    f"/api/v1/organizations/{org_id}/auto-update",
                    json={"enabled": True},
                )

                # El endpoint debe responder exitosamente
                assert response.status_code == 200, (
                    f"Endpoint retornó {response.status_code}: {response.json()}"
                )

                # Verificar que se enviaron mensajes a las workstations
                assert len(sent_messages) > 0, (
                    "No se enviaron mensajes WebSocket a ninguna workstation "
                    "al activar auto_update"
                )

                # COMPORTAMIENTO ESPERADO (después del fix):
                # Cada mensaje debe incluir download_url, version, file_size en params
                for msg_data in sent_messages:
                    message = msg_data["message"]
                    params = message.get("params", {})

                    assert params.get("download_url") is not None, (
                        f"Bug confirmado: params.download_url es None/ausente. "
                        f"Mensaje enviado: {message}. "
                        f"Con {num_ws} workstations online y auto_update recién habilitado, "
                        f"cada workstation llamará individualmente a /api/v1/updates/check "
                        f"→ thundering herd → pool BD saturado. "
                        f"params actual: {params}"
                    )

                    assert params.get("version") is not None, (
                        f"Bug confirmado: params.version es None/ausente. "
                        f"Mensaje enviado: {message}. "
                        f"params actual: {params}"
                    )

                    assert params.get("file_size") is not None and params.get("file_size", 0) > 0, (
                        f"Bug confirmado: params.file_size es None/ausente o <= 0. "
                        f"Mensaje enviado: {message}. "
                        f"params actual: {params}"
                    )

    finally:
        db.close()
        test_engine.dispose()
