"""
Property test: Preservation - Comportamiento sin cambios para inputs no-buggy

Verifica que el comportamiento existente se preserva para inputs que NO disparan
el bug. Estos tests capturan el baseline del código ANTES del fix.

Propiedades verificadas:
- Activación con IP válida retorna 200 y envía WebSocket con printer_ip
- Desactivación siempre retorna 200 y envía mensaje
- Toggle individual permitido cuando VLAN no tiene forced_contingency
- Activación VLAN con dispositivos activos retorna 200
- Cliente con printer_ip válido ejecuta trigger normalmente

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock

import pytest
from hypothesis import given, settings as hypothesis_settings, assume
from hypothesis import strategies as st
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import get_current_user
from app.models.organization import Organization, GUID
from app.models.vlan import VLAN
from app.models.workstation import Workstation
from app.models.device import Device
from app.models.user import User, UserRole

# Importar todos los modelos para registrar tablas en Base.metadata
from app import models as _all_models  # noqa: F401

from app.main import app


# === CONFIGURACIÓN DE BASE DE DATOS EN MEMORIA PARA TESTS ===

SQLALCHEMY_TEST_URL = "sqlite://"

engine = create_engine(
    SQLALCHEMY_TEST_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


# Desactivar foreign keys para evitar errores de dependencia circular al hacer drop_all
# (el listener global de database.py activa PRAGMA foreign_keys=ON en todos los Engine)
@event.listens_for(engine, "connect")
def _disable_fk_for_tests(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=OFF")
    cursor.close()


TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    """Dependencia de BD sobreescrita para usar SQLite en memoria."""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


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


# === SOBREESCRIBIR DEPENDENCIAS ===

app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[get_current_user] = override_get_current_user

client = TestClient(app)


# === ESTRATEGIAS DE GENERACIÓN ===

# Genera IPs privadas válidas
ip_strategy = st.tuples(
    st.integers(min_value=1, max_value=254),
    st.integers(min_value=0, max_value=254),
    st.integers(min_value=0, max_value=254),
    st.integers(min_value=1, max_value=254),
).map(lambda t: f"10.{t[1]}.{t[2]}.{t[3]}")

# Genera IPs de impresora válidas (rango diferente para evitar colisiones)
printer_ip_strategy = st.tuples(
    st.integers(min_value=1, max_value=254),
    st.integers(min_value=0, max_value=254),
    st.integers(min_value=1, max_value=254),
).map(lambda t: f"192.168.{t[1]}.{t[2]}")


# === PROPERTY TESTS ===


@hypothesis_settings(max_examples=20, deadline=None)
@given(ws_ip=ip_strategy, device_ip=printer_ip_strategy)
def test_activation_with_valid_ip_returns_200(ws_ip: str, device_ip: str):
    """
    Property 2: Preservation - Activación con IP válida retorna HTTP 200.

    Para cualquier workstation cuya VLAN tiene al menos un dispositivo activo,
    activar contingencia forzada (enabled=true) DEBE retornar HTTP 200,
    persistir forced_contingency=true, y enviar mensaje WebSocket con printer_ip.

    Este es el happy path que debe preservarse después del fix.

    **Validates: Requirements 3.1, 3.5**
    """
    # Asegurar overrides
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    # Crear tablas frescas
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    try:
        # Crear organización
        org_id = uuid.uuid4()
        org = Organization(
            id=org_id,
            name=f"test-org-{org_id}",
            is_active=True,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(org)
        db.flush()

        # Crear VLAN con dispositivo activo
        vlan_id = uuid.uuid4()
        vlan = VLAN(
            id=vlan_id,
            organization_id=org_id,
            name="VLAN con dispositivos",
            cidr_ranges=["10.0.0.0/24"],
            forced_contingency=False,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(vlan)
        db.flush()

        # Crear dispositivo activo en la VLAN
        device_id = uuid.uuid4()
        device = Device(
            id=device_id,
            organization_id=org_id,
            vlan_id=vlan_id,
            name="Impresora Test",
            ip_address=device_ip,
            is_active=True,
            port=9100,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(device)
        db.flush()

        # Crear workstation SIN default_printer_id (usará dispositivo de VLAN)
        ws_id = uuid.uuid4()
        workstation = Workstation(
            id=ws_id,
            organization_id=org_id,
            vlan_id=vlan_id,
            ip_private=ws_ip,
            hostname=f"ws-{ws_ip}",
            is_online=True,
            forced_contingency=False,
            default_printer_id=None,
            first_seen=datetime.now(timezone.utc).replace(tzinfo=None),
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(workstation)
        db.commit()

        # Mockear connection_manager
        with patch(
            "app.api.v1.endpoints.workstations.connection_manager"
        ) as mock_cm:
            mock_cm.is_workstation_online.return_value = True
            mock_cm.send_to_workstation = AsyncMock(return_value=True)

            # Ejecutar: activar contingencia forzada con IP resoluble
            response = client.patch(
                f"/api/v1/workstations/{ws_id}/forced-contingency?enabled=true"
            )

            # Preservación: retorna 200 cuando hay IP resoluble
            assert response.status_code == 200, (
                f"Preservation violada: activación con IP válida debería retornar 200, "
                f"pero retornó {response.status_code}. "
                f"Workstation: ip={ws_ip}, device_ip={device_ip}"
            )

            # Verificar que forced_contingency se persistió
            db.expire_all()
            ws_after = db.query(Workstation).filter(
                Workstation.id == ws_id
            ).first()
            assert ws_after.forced_contingency is True, (
                f"Preservation violada: forced_contingency debería ser True "
                f"después de activación exitosa. Workstation: ip={ws_ip}"
            )

            # Verificar que se envió mensaje WebSocket con printer_ip
            mock_cm.send_to_workstation.assert_called_once()
            call_args = mock_cm.send_to_workstation.call_args
            message = call_args[0][1]
            assert message["printer_ip"] == device_ip, (
                f"Preservation violada: mensaje WebSocket debería contener "
                f"printer_ip={device_ip}, pero contiene "
                f"printer_ip={message.get('printer_ip')}. "
                f"Workstation: ip={ws_ip}"
            )
            assert message["enabled"] is True
            assert message["type"] == "forced_contingency"

    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@hypothesis_settings(max_examples=20, deadline=None)
@given(ws_ip=ip_strategy)
def test_deactivation_always_returns_200(ws_ip: str):
    """
    Property 2: Preservation - Desactivación siempre retorna HTTP 200.

    Para cualquier workstation, desactivar contingencia forzada (enabled=false)
    DEBE retornar HTTP 200 y enviar mensaje de desactivación, independientemente
    de la disponibilidad de dispositivos.

    Nota: Este test verifica desactivación cuando la VLAN NO tiene
    forced_contingency=true (caso no-buggy).

    **Validates: Requirements 3.2**
    """
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    try:
        # Crear organización
        org_id = uuid.uuid4()
        org = Organization(
            id=org_id,
            name=f"test-org-{org_id}",
            is_active=True,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(org)
        db.flush()

        # Crear VLAN SIN contingencia forzada (caso no-buggy)
        vlan_id = uuid.uuid4()
        vlan = VLAN(
            id=vlan_id,
            organization_id=org_id,
            name="VLAN normal",
            cidr_ranges=["10.0.0.0/24"],
            forced_contingency=False,  # VLAN sin contingencia forzada
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(vlan)
        db.flush()

        # Crear workstation con contingencia activa (para desactivar)
        ws_id = uuid.uuid4()
        workstation = Workstation(
            id=ws_id,
            organization_id=org_id,
            vlan_id=vlan_id,
            ip_private=ws_ip,
            hostname=f"ws-{ws_ip}",
            is_online=True,
            forced_contingency=True,  # Activa, para desactivar
            default_printer_id=None,
            first_seen=datetime.now(timezone.utc).replace(tzinfo=None),
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(workstation)
        db.commit()

        # Mockear connection_manager
        with patch(
            "app.api.v1.endpoints.workstations.connection_manager"
        ) as mock_cm:
            mock_cm.is_workstation_online.return_value = True
            mock_cm.send_to_workstation = AsyncMock(return_value=True)

            # Ejecutar: desactivar contingencia forzada
            response = client.patch(
                f"/api/v1/workstations/{ws_id}/forced-contingency?enabled=false"
            )

            # Preservación: desactivación siempre retorna 200
            assert response.status_code == 200, (
                f"Preservation violada: desactivación debería retornar 200, "
                f"pero retornó {response.status_code}. "
                f"Workstation: ip={ws_ip}"
            )

            # Verificar que forced_contingency se desactivó
            db.expire_all()
            ws_after = db.query(Workstation).filter(
                Workstation.id == ws_id
            ).first()
            assert ws_after.forced_contingency is False, (
                f"Preservation violada: forced_contingency debería ser False "
                f"después de desactivación. Workstation: ip={ws_ip}"
            )

            # Verificar que se envió mensaje de desactivación
            mock_cm.send_to_workstation.assert_called_once()
            call_args = mock_cm.send_to_workstation.call_args
            message = call_args[0][1]
            assert message["enabled"] is False
            assert message["type"] == "forced_contingency"

    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@hypothesis_settings(max_examples=20, deadline=None)
@given(ws_ip=ip_strategy, device_ip=printer_ip_strategy)
def test_individual_toggle_permitted_without_vlan_contingency(
    ws_ip: str, device_ip: str
):
    """
    Property 2: Preservation - Toggle individual permitido sin contingencia VLAN.

    Para cualquier workstation cuya VLAN NO tiene forced_contingency=true,
    el toggle individual de contingencia (tanto activar como desactivar)
    DEBE seguir permitido y retornar HTTP 200.

    **Validates: Requirements 3.3, 3.4**
    """
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    try:
        # Crear organización
        org_id = uuid.uuid4()
        org = Organization(
            id=org_id,
            name=f"test-org-{org_id}",
            is_active=True,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(org)
        db.flush()

        # Crear VLAN SIN contingencia forzada
        vlan_id = uuid.uuid4()
        vlan = VLAN(
            id=vlan_id,
            organization_id=org_id,
            name="VLAN sin contingencia",
            cidr_ranges=["10.0.0.0/24"],
            forced_contingency=False,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(vlan)
        db.flush()

        # Crear dispositivo activo en la VLAN
        device_id = uuid.uuid4()
        device = Device(
            id=device_id,
            organization_id=org_id,
            vlan_id=vlan_id,
            name="Impresora Test",
            ip_address=device_ip,
            is_active=True,
            port=9100,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(device)
        db.flush()

        # Crear workstation sin contingencia (para activar)
        ws_id = uuid.uuid4()
        workstation = Workstation(
            id=ws_id,
            organization_id=org_id,
            vlan_id=vlan_id,
            ip_private=ws_ip,
            hostname=f"ws-{ws_ip}",
            is_online=True,
            forced_contingency=False,
            default_printer_id=None,
            first_seen=datetime.now(timezone.utc).replace(tzinfo=None),
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(workstation)
        db.commit()

        with patch(
            "app.api.v1.endpoints.workstations.connection_manager"
        ) as mock_cm:
            mock_cm.is_workstation_online.return_value = True
            mock_cm.send_to_workstation = AsyncMock(return_value=True)

            # Activar contingencia individual (VLAN no tiene forzada)
            response = client.patch(
                f"/api/v1/workstations/{ws_id}/forced-contingency?enabled=true"
            )
            assert response.status_code == 200, (
                f"Preservation violada: toggle individual activar debería "
                f"retornar 200 cuando VLAN no tiene forced_contingency. "
                f"Retornó {response.status_code}. Workstation: ip={ws_ip}"
            )

            # Ahora desactivar (VLAN sigue sin forzada)
            mock_cm.reset_mock()
            response = client.patch(
                f"/api/v1/workstations/{ws_id}/forced-contingency?enabled=false"
            )
            assert response.status_code == 200, (
                f"Preservation violada: toggle individual desactivar debería "
                f"retornar 200 cuando VLAN no tiene forced_contingency. "
                f"Retornó {response.status_code}. Workstation: ip={ws_ip}"
            )

    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@hypothesis_settings(max_examples=20, deadline=None)
@given(ws_ip=ip_strategy, device_ip=printer_ip_strategy)
def test_vlan_activation_with_devices_returns_200(ws_ip: str, device_ip: str):
    """
    Property 2: Preservation - Activación VLAN con dispositivos retorna HTTP 200.

    Para cualquier VLAN que tiene al menos un dispositivo activo,
    activar contingencia forzada a nivel VLAN (enabled=true) DEBE
    retornar HTTP 200 y persistir forced_contingency=true en la VLAN.

    **Validates: Requirements 3.4**
    """
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    try:
        # Crear organización
        org_id = uuid.uuid4()
        org = Organization(
            id=org_id,
            name=f"test-org-{org_id}",
            is_active=True,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(org)
        db.flush()

        # Crear VLAN
        vlan_id = uuid.uuid4()
        vlan = VLAN(
            id=vlan_id,
            organization_id=org_id,
            name="VLAN con dispositivos",
            cidr_ranges=["10.0.0.0/24"],
            forced_contingency=False,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(vlan)
        db.flush()

        # Crear dispositivo activo en la VLAN
        device_id = uuid.uuid4()
        device = Device(
            id=device_id,
            organization_id=org_id,
            vlan_id=vlan_id,
            name="Impresora VLAN",
            ip_address=device_ip,
            is_active=True,
            port=9100,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(device)
        db.flush()

        # Crear workstation en la VLAN
        ws_id = uuid.uuid4()
        workstation = Workstation(
            id=ws_id,
            organization_id=org_id,
            vlan_id=vlan_id,
            ip_private=ws_ip,
            hostname=f"ws-{ws_ip}",
            is_online=True,
            forced_contingency=False,
            default_printer_id=None,
            first_seen=datetime.now(timezone.utc).replace(tzinfo=None),
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(workstation)
        db.commit()

        # Mockear connection_manager en el módulo fuente (vlans.py lo importa inline)
        with patch(
            "app.services.websocket_manager.connection_manager"
        ) as mock_cm:
            mock_cm.is_workstation_online.return_value = True
            mock_cm.send_to_workstation = AsyncMock(return_value=True)

            # Ejecutar: activar contingencia forzada a nivel VLAN
            response = client.patch(
                f"/api/v1/vlans/{vlan_id}/forced-contingency?enabled=true"
            )

            # Preservación: retorna 200 cuando VLAN tiene dispositivos
            assert response.status_code == 200, (
                f"Preservation violada: activación VLAN con dispositivos "
                f"debería retornar 200, pero retornó {response.status_code}. "
                f"VLAN tiene device_ip={device_ip}"
            )

            # Verificar que forced_contingency se persistió en la VLAN
            db.expire_all()
            vlan_after = db.query(VLAN).filter(VLAN.id == vlan_id).first()
            assert vlan_after.forced_contingency is True, (
                f"Preservation violada: VLAN.forced_contingency debería ser True "
                f"después de activación. VLAN: id={vlan_id}"
            )

    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@hypothesis_settings(max_examples=20, deadline=None)
@given(ws_ip=ip_strategy, device_ip=printer_ip_strategy)
def test_activation_with_default_printer_returns_200(ws_ip: str, device_ip: str):
    """
    Property 2: Preservation - Activación con default_printer_id válido retorna 200.

    Para cualquier workstation con default_printer_id apuntando a un dispositivo
    existente, activar contingencia forzada DEBE retornar HTTP 200 y enviar
    mensaje WebSocket con la IP de la impresora predeterminada.

    **Validates: Requirements 3.1, 3.5**
    """
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    try:
        # Crear organización
        org_id = uuid.uuid4()
        org = Organization(
            id=org_id,
            name=f"test-org-{org_id}",
            is_active=True,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(org)
        db.flush()

        # Crear VLAN (sin dispositivos - la IP viene del default_printer)
        vlan_id = uuid.uuid4()
        vlan = VLAN(
            id=vlan_id,
            organization_id=org_id,
            name="VLAN test",
            cidr_ranges=["10.0.0.0/24"],
            forced_contingency=False,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(vlan)
        db.flush()

        # Crear dispositivo (impresora predeterminada)
        device_id = uuid.uuid4()
        device = Device(
            id=device_id,
            organization_id=org_id,
            vlan_id=vlan_id,
            name="Impresora Favorita",
            ip_address=device_ip,
            is_active=True,
            port=9100,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(device)
        db.flush()

        # Crear workstation CON default_printer_id
        ws_id = uuid.uuid4()
        workstation = Workstation(
            id=ws_id,
            organization_id=org_id,
            vlan_id=vlan_id,
            ip_private=ws_ip,
            hostname=f"ws-{ws_ip}",
            is_online=True,
            forced_contingency=False,
            default_printer_id=device_id,  # Tiene impresora predeterminada
            first_seen=datetime.now(timezone.utc).replace(tzinfo=None),
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(workstation)
        db.commit()

        with patch(
            "app.api.v1.endpoints.workstations.connection_manager"
        ) as mock_cm:
            mock_cm.is_workstation_online.return_value = True
            mock_cm.send_to_workstation = AsyncMock(return_value=True)

            # Ejecutar: activar contingencia con default_printer_id
            response = client.patch(
                f"/api/v1/workstations/{ws_id}/forced-contingency?enabled=true"
            )

            # Preservación: retorna 200 con IP de impresora predeterminada
            assert response.status_code == 200, (
                f"Preservation violada: activación con default_printer_id "
                f"debería retornar 200, pero retornó {response.status_code}. "
                f"Workstation: ip={ws_ip}, default_printer_id={device_id}"
            )

            # Verificar que el mensaje WebSocket usa la IP del default_printer
            mock_cm.send_to_workstation.assert_called_once()
            call_args = mock_cm.send_to_workstation.call_args
            message = call_args[0][1]
            assert message["printer_ip"] == device_ip, (
                f"Preservation violada: mensaje debería usar IP de "
                f"default_printer ({device_ip}), pero usa "
                f"printer_ip={message.get('printer_ip')}. "
                f"Workstation: ip={ws_ip}"
            )

    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
