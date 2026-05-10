"""Crear usuario admin para pruebas."""
from app.core.database import SessionLocal
from app.models.user import User, UserRole
from app.services.auth import AuthService

db = SessionLocal()

# Crear usuario admin
admin = User(
    email="admin@example.com",
    password_hash=AuthService.hash_password("Admin123456"),
    full_name="Administrator",
    role=UserRole.ADMIN,
    account_id=None,
    is_active=True
)

db.add(admin)
db.commit()
db.refresh(admin)

print(f"Usuario admin creado: {admin.email}")
print(f"ID: {admin.id}")
print(f"Rol: {admin.role.value}")

db.close()
