"""
Script para crear usuario administrador inicial.
"""

import sys
from pathlib import Path
import uuid

# Agregar el directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import SessionLocal
from app.services.auth import AuthService
from app.models.user import User, UserRole


def create_admin():
    """Crear usuario administrador."""
    db = SessionLocal()
    
    try:
        # Verificar si ya existe un admin
        existing = db.query(User).filter(User.email == "admin@example.com").first()
        if existing:
            print("⚠️  El usuario admin@example.com ya existe")
            print(f"   Email: {existing.email}")
            print(f"   Nombre: {existing.full_name}")
            print(f"   Rol: {existing.role}")
            print()
            print("🔐 Puedes hacer login en http://localhost:3000/login")
            print("   Email: admin@example.com")
            print("   Contraseña: admin123")
            return
        
        # Crear usuario admin
        admin = User(
            id=str(uuid.uuid4()),
            email="admin@example.com",
            password_hash=AuthService.hash_password("admin123"),
            full_name="Administrador",
            role=UserRole.ADMIN,
            account_id=None,
            is_active=True
        )
        
        db.add(admin)
        db.commit()
        db.refresh(admin)
        
        print("✅ Usuario administrador creado exitosamente!")
        print(f"   Email: {admin.email}")
        print(f"   Contraseña: admin123")
        print(f"   Nombre: {admin.full_name}")
        print(f"   Rol: {admin.role}")
        print()
        print("🔐 Puedes hacer login en http://localhost:3000/login")
        
    except Exception as e:
        print(f"❌ Error al crear usuario: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    create_admin()
