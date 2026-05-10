"""
Test rápido para verificar el truncamiento de contraseñas.
"""

from app.services.auth import AuthService

# Test con contraseña de 16 caracteres
password_16 = "1234567890123456"
print(f"Contraseña de 16 caracteres: {password_16}")
print(f"Longitud en bytes: {len(password_16.encode('utf-8'))}")

try:
    hashed = AuthService.hash_password(password_16)
    print(f"✓ Hash generado exitosamente: {hashed[:20]}...")
except Exception as e:
    print(f"✗ Error: {e}")

# Test con contraseña de 80 caracteres
password_80 = "a" * 80
print(f"\nContraseña de 80 caracteres: {password_80[:20]}...")
print(f"Longitud en bytes: {len(password_80.encode('utf-8'))}")

try:
    hashed = AuthService.hash_password(password_80)
    print(f"✓ Hash generado exitosamente: {hashed[:20]}...")
except Exception as e:
    print(f"✗ Error: {e}")
