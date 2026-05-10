"""Script de prueba para logout."""
import requests

# Hacer login
print("Haciendo login...")
login_response = requests.post(
    "http://localhost:8000/api/v1/auth/login",
    json={
        "email": "admin@example.com",
        "password": "Admin123456"
    }
)

print("Login response:", login_response.status_code)
if login_response.status_code == 200:
    token = login_response.json()["access_token"]
    print("Token obtenido:", token[:50] + "...")
    
    # Ahora hacer logout
    print("\nIntentando logout...")
    logout_response = requests.post(
        "http://localhost:8000/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    print("Logout response:", logout_response.status_code)
    if logout_response.status_code != 204:
        print("Error:", logout_response.text)
    else:
        print("✓ Logout exitoso!")
else:
    print("Error en login:", login_response.text)
