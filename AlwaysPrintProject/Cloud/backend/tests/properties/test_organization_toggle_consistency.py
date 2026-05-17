"""
Property test: Organization flag toggle consistency

Verifica que para cualquier secuencia de operaciones PATCH con valores booleanos
en el endpoint /api/v1/organizations/{org_id}/auto-update, el valor final de
auto_update_enabled en la base de datos siempre es igual al último valor PATCH
de la secuencia.

Feature: auto-update, Property 7: Organization flag toggle consistency
**Validates: Requirements 8.3, 8.4**
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import given, settings as hypothesis_settings
from hypothesis import strategies as st
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import require_admin
from app.models.organization import Organization as Account
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


# === MOCK DE AUTENTICACIÓN ADMIN ===

# Usuario admin ficticio para los tests
mock_admin_user = User(
    id=uuid.uuid4(),
    email="admin@test.com",
    password_hash="hashed",
    full_name="Admin Test",
    role=UserRole.ADMIN,
    is_active=True,
)


async def override_require_admin():
    """Dependencia sobreescrita que siempre retorna un usuario admin."""
    return mock_admin_user


# === SOBREESCRIBIR DEPENDENCIAS ===

app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[require_admin] = override_require_admin

client = TestClient(app)


# === PROPERTY TEST ===

@hypothesis_settings(max_examples=100, deadline=None)
@given(toggle_sequence=st.lists(st.booleans(), min_size=1))
def test_organization_flag_toggle_consistency(toggle_sequence: list[bool]):
    """
    Propiedad 7: Consistencia del toggle de organización.

    Para cualquier secuencia no vacía de operaciones PATCH con valores booleanos,
    el valor final de auto_update_enabled en la BD siempre debe ser igual
    al último valor de la secuencia.

    Feature: auto-update, Property 7: Organization flag toggle consistency
    **Validates: Requirements 8.3, 8.4**
    """
    # Asegurar que los overrides estén configurados (pueden ser limpiados por otros tests)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = override_require_admin

    # Crear tablas frescas para cada ejemplo
    Base.metadata.create_all(bind=engine)

    # Crear una organización de prueba en la BD
    db = TestingSessionLocal()
    org_id = uuid.uuid4()
    account = Account(
        id=org_id,
        name=f"test-org-{org_id}",
        is_active=True,
        auto_update_enabled=False,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(account)
    db.commit()
    db.close()

    # Aplicar toda la secuencia de operaciones PATCH
    for enabled_value in toggle_sequence:
        response = client.patch(
            f"/api/v1/organizations/{org_id}/auto-update",
            json={"enabled": enabled_value},
        )
        # Cada PATCH debe ser exitoso
        assert response.status_code == 200, (
            f"PATCH falló con status {response.status_code}: {response.text}"
        )

    # Verificar que el valor final en BD es igual al último PATCH
    db = TestingSessionLocal()
    final_account = db.query(Account).filter(Account.id == org_id).first()
    assert final_account is not None, "La organización no se encontró en la BD"
    assert final_account.auto_update_enabled == toggle_sequence[-1], (
        f"Valor final en BD ({final_account.auto_update_enabled}) "
        f"no coincide con último PATCH ({toggle_sequence[-1]}). "
        f"Secuencia completa: {toggle_sequence}"
    )
    db.close()

    # Limpiar tablas después de cada ejemplo
    Base.metadata.drop_all(bind=engine)
