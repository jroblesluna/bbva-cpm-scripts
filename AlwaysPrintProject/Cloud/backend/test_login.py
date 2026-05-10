"""
Script para probar el endpoint de login.
"""

import requests
import json

BASE_URL = "http://127.0.0.1:8000/api/v1"

print("=" * 60)
print("PRUEBA DEL ENDPOINT DE LOGIN")
print("=" * 60)
print()

# Primero, crear un usuario de prueba
print("1. Creando usuario de prueba...")
setup_data = {
    "email": "test@ejemplo.com",
    "password": "Test123456",
    "full_name": "Usuario de Prueba"
}

try:
    response = requests.post(
        f"{BASE_URL}/setup/initialize",
        json=setup_data,
        headers={"Content-Type": "application/json"}
    )
    
    if response.status_code == 201:
        print(f"   ✓ Usuario creado exitosamente")
    elif response.status_code == 400:
        print(f"   ℹ Usuario ya existe (esto es normal)")
    else:
        print(f"   Status: {response.status_code}")
        print(f"   Response: {response.json()}")
except Exception as e:
    print(f"   Error: {e}")

print()

# Ahora, intentar login
print("2. Intentando login...")
login_data = {
    "email": "test@ejemplo.com",
    "password": "Test123456"
}

try:
    response = requests.post(
        f"{BASE_URL}/auth/login",
        json=login_data,
        headers={"Content-Type": "application/json"}
    )
    
    print(f"   Status: {response.status_code}")
    
    if response.status_code == 200:
        print(f"   ✓ Login exitoso")
        data = response.json()
        print(f"   Access Token: {data['access_token'][:50]}...")
        print(f"   Token Type: {data['token_type']}")
        print(f"   Expires In: {data['expires_in']} segundos")
    else:
        print(f"   ✗ Login falló")
        print(f"   Response: {response.json()}")
        
except Exception as e:
    print(f"   ✗ Error: {e}")

print()
print("=" * 60)
