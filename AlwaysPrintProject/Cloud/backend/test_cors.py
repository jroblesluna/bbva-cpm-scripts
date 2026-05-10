"""
Script para verificar la configuración de CORS.
"""

from app.core.config import settings

print("=" * 60)
print("CONFIGURACIÓN DE CORS")
print("=" * 60)
print()
print(f"CORS_ORIGINS: {settings.CORS_ORIGINS}")
print(f"Tipo: {type(settings.CORS_ORIGINS)}")
print()

if isinstance(settings.CORS_ORIGINS, list):
    print("Orígenes permitidos:")
    for origin in settings.CORS_ORIGINS:
        print(f"  - {origin}")
else:
    print(f"ERROR: CORS_ORIGINS no es una lista, es {type(settings.CORS_ORIGINS)}")

print()
print("=" * 60)
