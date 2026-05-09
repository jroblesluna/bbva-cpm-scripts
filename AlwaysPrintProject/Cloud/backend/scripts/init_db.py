"""
Script para inicializar la base de datos.

Este script verifica la conexión a la base de datos y opcionalmente
crea las tablas iniciales.
"""

import sys
from pathlib import Path

# Agregar el directorio raíz al path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import check_db_connection, init_db
from app.core.config import settings


def main():
    """Función principal del script."""
    print("=" * 60)
    print("Inicialización de Base de Datos - AlwaysPrint Cloud Management")
    print("=" * 60)
    print()
    
    # Mostrar configuración
    print(f"Base de datos: {settings.DATABASE_URL}")
    print(f"Tipo: ", end="")
    if settings.is_sqlite:
        print("SQLite (Desarrollo)")
    elif settings.is_postgresql:
        print("PostgreSQL (Producción)")
    elif settings.is_sqlserver:
        print("SQL Server (Producción)")
    else:
        print("Desconocido")
    print()
    
    # Verificar conexión
    print("Verificando conexión a la base de datos...")
    if check_db_connection():
        print("✓ Conexión exitosa")
    else:
        print("✗ Error al conectar con la base de datos")
        print("\nVerifica:")
        print("  1. Que la base de datos esté en ejecución")
        print("  2. Que DATABASE_URL en .env sea correcta")
        print("  3. Que las credenciales sean válidas")
        sys.exit(1)
    
    print()
    print("=" * 60)
    print("Inicialización completada exitosamente")
    print("=" * 60)
    print()
    print("Próximos pasos:")
    print("  1. Crear los modelos de datos en app/models/")
    print("  2. Importar los modelos en alembic/env.py")
    print("  3. Generar migración: alembic revision --autogenerate -m 'Initial'")
    print("  4. Aplicar migración: alembic upgrade head")
    print()


if __name__ == "__main__":
    main()
