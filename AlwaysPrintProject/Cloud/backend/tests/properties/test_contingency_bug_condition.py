"""
Property test: Bug Condition - Activación de contingencia sin IP resoluble

Verifica que el endpoint PATCH /workstations/{id}/forced-contingency rechaza
la activación cuando no se puede resolver una printer_ip válida, y que la
desactivación individual se bloquea cuando la VLAN tiene contingencia forzada.

Este test codifica el COMPORTAMIENTO ESPERADO (correcto). En código sin corregir,
DEBE FALLAR — confirmando que el bug existe.

**Validates: Requirements 1.1, 1.4, 2.1, 2.4**
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
from app.models.vlan import VLAN
from app.models.workstation import Workstation
from app.models.device import Device
from app.models.user import User, UserRole
from app.main import app


# === CONFIGURACIÓN DE BASE DE DATOS EN MEMORIA PARA TESTS ===

SQLALCHEMY_TEST_URL = "sqlite://"

engine = create_engine(
    SQLALCHEMY_TEST_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

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

# Genera IPs privadas válidas para workstations
ip_strategy = st.tuples(
    st.integers(min_value=1, max_value=254),
    st.integers(min_value=0, max_value=254),
    st.integers(min_value=0, max_value=254),
    st.integers(min_value=1, max_value=254),
).map(lambda t: f"10.{t[1]}.{t[2]}.{t[3]}")


# === PROPERTY TESTS ===

@hypothesis_settings(max_examples=20, deadline=None)
@given(ws_ip=ip_strategy)
def test_activation_without_resolvable_ip_returns_400(ws_ip: str):
    """
    Property 1: Bug Condition - Activación sin IP resoluble retorna HTTP 400.

    Para cualquier workstation sin default_printer_id y cuya VLAN no tiene
    dispositivos activos, activar contingencia forzada (enabled=true) DEBE
    retornar HTTP 400 y NO persistir forced_contingency=true en la BD.

    Bug actual: retorna 200, persiste forced_contingency=true, envía printer_ip: null.

    **Validates: Requirements 1.1, 1.4, 2.1, 2.4**
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

        # Crear VLAN sin dispositivos activos
        vlan_id = uuid.uuid4()
        vlan = VLAN(
            id=vlan_id,
            organization_id=org_id,
            name="VLAN sin dispositivos",
            cidr_ranges=["10.0.0.0/24"],
            forced_contingency=False,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(vlan)
        db.flush()

        # Crear workstation SIN default_printer_id en VLAN sin dispositivos
        ws_id = uuid.uuid4()
        workstation = Workstation(
            id=ws_id,
            organization_id=org_id,
            vlan_id=vlan_id,
            ip_private=ws_ip,
            hostname=f"ws-{ws_ip}",
            is_online=True,
            forced_contingency=False,
            default_printer_id=None,  # Sin impresora predeterminada
            first_seen=datetime.now(timezone.utc).replace(tzinfo=None),
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(workstation)
        db.commit()

        # Mockear connection_manager para capturar mensajes WebSocket
        with patch(
            "app.api.v1.endpoints.workstations.connection_manager"
        ) as mock_cm:
            mock_cm.is_workstation_online.return_value = True
            mock_cm.send_to_workstation = AsyncMock(return_value=True)

            # Ejecutar: activar contingencia forzada sin IP resoluble
            response = client.patch(
                f"/api/v1/workstations/{ws_id}/forced-contingency?enabled=true"
            )

            # COMPORTAMIENTO ESPERADO (después del fix):
            # - HTTP 400 porque no hay IP resoluble
            assert response.status_code == 400, (
                f"Bug confirmado: endpoint retorna {response.status_code} en vez de 400 "
                f"cuando no hay IP resoluble. "
                f"Workstation: ip={ws_ip}, default_printer_id=None, "
                f"VLAN sin dispositivos activos. "
                f"Response: {response.json()}"
            )

            # Verificar que forced_contingency NO se persistió
            db.expire_all()
            ws_after = db.query(Workstation).filter(Workstation.id == ws_id).first()
            assert ws_after.forced_contingency is False, (
                f"Bug confirmado: forced_contingency se persistió como True "
                f"a pesar de no tener IP resoluble. "
                f"Workstation: ip={ws_ip}"
            )

            # Verificar que NO se envió mensaje WebSocket
            mock_cm.send_to_workstation.assert_not_called(), (
                f"Bug confirmado: se envió mensaje WebSocket con printer_ip: null. "
                f"Workstation: ip={ws_ip}"
            )

    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@hypothesis_settings(max_examples=20, deadline=None)
@given(ws_ip=ip_strategy)
def test_individual_deactivation_blocked_under_vlan_contingency(ws_ip: str):
    """
    Property 1: Bug Condition - Desactivación individual bloqueada bajo contingencia VLAN.

    Para cualquier workstation cuya VLAN tiene forced_contingency=true,
    intentar desactivar contingencia individual (enabled=false) DEBE
    retornar HTTP 409 y NO cambiar el estado.

    Bug actual: permite la desactivación individual, rompiendo la intención VLAN.

    **Validates: Requirements 1.1, 1.4, 2.1, 2.4**
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

        # Crear VLAN con contingencia forzada activa
        vlan_id = uuid.uuid4()
        vlan = VLAN(
            id=vlan_id,
            organization_id=org_id,
            name="VLAN contingencia activa",
            cidr_ranges=["10.0.0.0/24"],
            forced_contingency=True,  # VLAN tiene contingencia forzada
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(vlan)
        db.flush()

        # Crear workstation con contingencia activa (heredada de VLAN)
        ws_id = uuid.uuid4()
        workstation = Workstation(
            id=ws_id,
            organization_id=org_id,
            vlan_id=vlan_id,
            ip_private=ws_ip,
            hostname=f"ws-{ws_ip}",
            is_online=True,
            forced_contingency=True,  # Activa por la VLAN
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

            # Ejecutar: intentar desactivar contingencia individual
            response = client.patch(
                f"/api/v1/workstations/{ws_id}/forced-contingency?enabled=false"
            )

            # COMPORTAMIENTO ESPERADO (después del fix):
            # - HTTP 409 porque la VLAN controla la contingencia
            assert response.status_code == 409, (
                f"Bug confirmado: endpoint retorna {response.status_code} en vez de 409 "
                f"cuando se intenta desactivar contingencia individual "
                f"pero la VLAN tiene forced_contingency=true. "
                f"Workstation: ip={ws_ip}, VLAN.forced_contingency=True. "
                f"Response: {response.json()}"
            )

            # Verificar que el estado NO cambió
            db.expire_all()
            ws_after = db.query(Workstation).filter(Workstation.id == ws_id).first()
            assert ws_after.forced_contingency is True, (
                f"Bug confirmado: forced_contingency cambió a False "
                f"a pesar de que la VLAN tiene contingencia forzada activa. "
                f"Workstation: ip={ws_ip}"
            )

    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@hypothesis_settings(max_examples=20, deadline=None)
@given(ws_ip=ip_strategy)
def test_no_websocket_message_sent_with_null_ip(ws_ip: str):
    """
    Property 1: Bug Condition - No se envía mensaje WebSocket con printer_ip null.

    Para cualquier workstation online sin IP resoluble, al intentar activar
    contingencia forzada, NO se debe enviar mensaje WebSocket (porque el
    endpoint debe rechazar la request con 400 antes de llegar al envío).

    Bug actual: envía mensaje con printer_ip: null, el cliente ejecuta
    OnContingencyActivated sin haber establecido contingency_printer_ip.

    **Validates: Requirements 1.1, 1.4, 2.1, 2.4**
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

        # Crear VLAN sin dispositivos
        vlan_id = uuid.uuid4()
        vlan = VLAN(
            id=vlan_id,
            organization_id=org_id,
            name="VLAN vacía",
            cidr_ranges=["10.0.0.0/24"],
            forced_contingency=False,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(vlan)
        db.flush()

        # Crear workstation online sin impresora predeterminada
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

        # Mockear connection_manager para capturar si se envía mensaje
        with patch(
            "app.api.v1.endpoints.workstations.connection_manager"
        ) as mock_cm:
            mock_cm.is_workstation_online.return_value = True
            mock_cm.send_to_workstation = AsyncMock(return_value=True)

            # Ejecutar: activar contingencia sin IP resoluble
            response = client.patch(
                f"/api/v1/workstations/{ws_id}/forced-contingency?enabled=true"
            )

            # Si el endpoint retorna 400 (comportamiento correcto), no debería
            # haber enviado mensaje. Si retorna 200 (bug), verificamos que
            # al menos no envió printer_ip: null.
            if response.status_code == 200:
                # Bug: el endpoint no rechazó la request
                # Verificar si envió mensaje con printer_ip: null
                if mock_cm.send_to_workstation.called:
                    call_args = mock_cm.send_to_workstation.call_args
                    message = call_args[0][1] if call_args[0] else call_args[1].get("message")
                    if message and message.get("printer_ip") is None:
                        pytest.fail(
                            f"Bug confirmado: se envió mensaje WebSocket con printer_ip=null. "
                            f"Workstation: ip={ws_ip}, mensaje={message}. "
                            f"El cliente ejecutaría OnContingencyActivated sin "
                            f"haber establecido contingency_printer_ip."
                        )

            # El test principal: el endpoint DEBE retornar 400
            assert response.status_code == 400, (
                f"Bug confirmado: endpoint retorna {response.status_code} en vez de 400 "
                f"para activación sin IP resoluble. "
                f"Workstation: ip={ws_ip}, sin default_printer_id, VLAN sin dispositivos."
            )

    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
