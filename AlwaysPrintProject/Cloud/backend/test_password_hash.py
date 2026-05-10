"""
Script de prueba para verificar el sistema de hashing de contraseñas.

Este script prueba que:
1. Se pueden hashear contraseñas de cualquier longitud (incluyendo >72 bytes)
2. La verificación funciona correctamente
3. No hay errores de bcrypt
"""

import sys
sys.path.insert(0, '.')

from app.services.auth import AuthService


def test_password_hashing():
    """Prueba el sistema de hashing de contraseñas."""
    
    print("=" * 60)
    print("PRUEBA DE HASHING DE CONTRASEÑAS")
    print("=" * 60)
    print()
    
    # Casos de prueba
    test_cases = [
        ("password123", "Contraseña corta (11 chars)"),
        ("MiContraseña123!", "Contraseña con caracteres especiales (16 chars)"),
        ("a" * 16, "Contraseña de 16 caracteres"),
        ("a" * 72, "Contraseña de 72 caracteres (límite bcrypt)"),
        ("a" * 100, "Contraseña de 100 caracteres (>72)"),
        ("contraseña_con_ñ_y_acentos_áéíóú", "Contraseña con Unicode"),
        ("🔐🔑🗝️" * 10, "Contraseña con emojis (30 emojis)"),
    ]
    
    all_passed = True
    
    for password, description in test_cases:
        print(f"Probando: {description}")
        print(f"  Longitud: {len(password)} chars, {len(password.encode('utf-8'))} bytes")
        
        try:
            # Hashear contraseña
            hashed = AuthService.hash_password(password)
            print(f"  ✓ Hash generado: {hashed[:50]}...")
            
            # Verificar contraseña correcta
            if AuthService.verify_password(password, hashed):
                print(f"  ✓ Verificación correcta: PASS")
            else:
                print(f"  ✗ Verificación correcta: FAIL")
                all_passed = False
            
            # Verificar contraseña incorrecta
            if not AuthService.verify_password(password + "wrong", hashed):
                print(f"  ✓ Verificación incorrecta: PASS")
            else:
                print(f"  ✗ Verificación incorrecta: FAIL")
                all_passed = False
            
            print()
            
        except Exception as e:
            print(f"  ✗ ERROR: {type(e).__name__}: {str(e)}")
            all_passed = False
            print()
    
    print("=" * 60)
    if all_passed:
        print("✓ TODAS LAS PRUEBAS PASARON")
    else:
        print("✗ ALGUNAS PRUEBAS FALLARON")
    print("=" * 60)
    
    return all_passed


if __name__ == "__main__":
    success = test_password_hashing()
    sys.exit(0 if success else 1)
