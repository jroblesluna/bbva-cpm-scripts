"""Crear datos de prueba para el frontend."""
from app.core.database import SessionLocal
from app.models.user import User, UserRole
from app.models.account import Account
from app.services.auth import AuthService

db = SessionLocal()

try:
    # Crear cuenta BBVA
    bbva = Account(
        name="BBVA",
        description="Banco BBVA",
        is_active=True
    )
    db.add(bbva)
    db.flush()  # Flush para obtener el ID
    print(f"✓ Cuenta creada: {bbva.name} (ID: {bbva.id}, tipo: {type(bbva.id)})")

    # Crear cuenta Ripley
    ripley = Account(
        name="Ripley",
        description="Tiendas Ripley",
        is_active=True
    )
    db.add(ripley)
    db.flush()
    print(f"✓ Cuenta creada: {ripley.name} (ID: {ripley.id}, tipo: {type(ripley.id)})")

    # Crear usuario admin
    admin = User(
        email="antonio@robles.ai",
        password_hash=AuthService.hash_password("Admin123456"),
        full_name="Antonio Robles",
        role=UserRole.ADMIN,
        account_id=None,
        is_active=True
    )
    db.add(admin)
    db.flush()
    print(f"✓ Usuario admin creado: {admin.email}")

    # Crear operador BBVA
    print(f"Creando operador BBVA con account_id={bbva.id} (tipo: {type(bbva.id)})")
    operator_bbva = User(
        email="operador@bbva.com",
        password_hash=AuthService.hash_password("Operador123"),
        full_name="Operador BBVA",
        role=UserRole.OPERATOR,
        account_id=bbva.id,  # Usar el UUID directamente
        is_active=True
    )
    db.add(operator_bbva)
    db.flush()
    print(f"✓ Usuario operador creado: {operator_bbva.email}")

    # Crear operador Ripley
    operator_ripley = User(
        email="operador@ripley.com",
        password_hash=AuthService.hash_password("Operador123"),
        full_name="Operador Ripley",
        role=UserRole.OPERATOR,
        account_id=ripley.id,
        is_active=True
    )
    db.add(operator_ripley)
    db.flush()
    print(f"✓ Usuario operador creado: {operator_ripley.email}")

    # Commit final
    db.commit()

    print("\n=== RESUMEN ===")
    print(f"Cuentas: {db.query(Account).count()}")
    print(f"Usuarios: {db.query(User).count()}")
    print("\nCredenciales:")
    print(f"  Admin: antonio@robles.ai / Admin123456")
    print(f"  Operador BBVA: operador@bbva.com / Operador123")
    print(f"  Operador Ripley: operador@ripley.com / Operador123")

except Exception as e:
    print(f"ERROR: {e}")
    db.rollback()
    raise
finally:
    db.close()
