"""
Script de prueba para el endpoint de setup.
"""

import requests
import json

BASE_URL = "http://127.0.0.1:8000/api/v1"

print("=" * 60)
print("PRUEBA DEL ENDPOINT DE SETUP")
print("=" * 60)
print()

# 1. Verificar estado
print("1. Verificando estado del sistema...")
response = requests.get(f"{BASE_URL}/setup/status")
print(f"   Status: {response.status_code}")
print(f"   Response: {response.json()}")
print()

# 2. Crear usuario administrador
print("2. Creando usuario administrador...")
data = {
    "email": "admin@ejemplo.com",
    "password": "Admin123!@#$%^&*",
    "full_name": "Administrador del Sistema"
}

response = requests.post(
    f"{BASE_URL}/setup/initialize",
    json=data,
    headers={"Content-Type": "application/json"}
)

print(f"   Status: {response.status_code}")
if response.status_code == 201:
    print(f"   ✓ Usuario creado exitosamente")
    print(f"   Response: {json.dumps(response.json(), indent=2)}")
else:
    print(f"   ✗ Error al crear usuario")
    print(f"   Response: {response.json()}")
print()

# 3. Verificar estado nuevamente
print("3. Verificando estado después de crear usuario...")
response = requests.get(f"{BASE_URL}/setup/status")
print(f"   Status: {response.status_code}")
print(f"   Response: {response.json()}")
print()

# 4. Intentar crear otro usuario (debería fallar)
print("4. Intentando crear otro usuario (debería fallar)...")
data2 = {
    "email": "otro@ejemplo.com",
    "password": "Password123",
    "full_name": "Otro Usuario"
}

response = requests.post(
    f"{BASE_URL}/setup/initialize",
    json=data2,
    headers={"Content-Type": "application/json"}
)

print(f"   Status: {response.status_code}")
if response.status_code == 400:
    print(f"   ✓ Correctamente rechazado")
    print(f"   Response: {response.json()}")
else:
    print(f"   ✗ Debería haber sido rechazado")
    print(f"   Response: {response.json()}")
print()

print("=" * 60)
print("PRUEBA COMPLETADA")
print("=" * 60)
