"""Test simple para debug."""

import hashlib
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

# Test 1: Hash directo de string corto
print("Test 1: Hash directo de 'password123'")
try:
    result = pwd_context.hash("password123")
    print(f"  ✓ Éxito: {result[:50]}...")
except Exception as e:
    print(f"  ✗ Error: {e}")

# Test 2: Hash de SHA-256
print("\nTest 2: Hash de SHA-256 de 'password123'")
try:
    password_sha256 = hashlib.sha256("password123".encode('utf-8')).hexdigest()
    print(f"  SHA-256: {password_sha256}")
    print(f"  Longitud: {len(password_sha256)} chars, {len(password_sha256.encode('utf-8'))} bytes")
    result = pwd_context.hash(password_sha256)
    print(f"  ✓ Éxito: {result[:50]}...")
except Exception as e:
    print(f"  ✗ Error: {e}")

# Test 3: Importar AuthService
print("\nTest 3: Importar AuthService")
try:
    import sys
    sys.path.insert(0, '.')
    from app.services.auth import AuthService
    print("  ✓ Import exitoso")
    
    # Test 4: Usar AuthService.hash_password
    print("\nTest 4: AuthService.hash_password('password123')")
    result = AuthService.hash_password("password123")
    print(f"  ✓ Éxito: {result[:50]}...")
    
    # Test 5: Verificar
    print("\nTest 5: AuthService.verify_password")
    if AuthService.verify_password("password123", result):
        print("  ✓ Verificación correcta")
    else:
        print("  ✗ Verificación falló")
        
except Exception as e:
    print(f"  ✗ Error: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
