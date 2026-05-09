"""
Script de verificación de configuración de SQLAlchemy y Alembic.

Este script verifica que todos los componentes estén correctamente configurados.
"""

import sys
from pathlib import Path

# Agregar el directorio raíz al path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.core.database import (
    engine,
    SessionLocal,
    Base,
    get_db,
    check_db_connection
)


def print_header(text: str):
    """Imprime un encabezado formateado."""
    print()
    print("=" * 70)
    print(f"  {text}")
    print("=" * 70)


def print_success(text: str):
    """Imprime un mensaje de éxito."""
    print(f"✓ {text}")


def print_error(text: str):
    """Imprime un mensaje de error."""
    print(f"✗ {text}")


def print_info(key: str, value: str):
    """Imprime información formateada."""
    print(f"  {key:30s}: {value}")


def verify_settings():
    """Verifica que la configuración se carga correctamente."""
    print_header("Verificación de Configuración")
    
    try:
        print_info("PROJECT_NAME", settings.PROJECT_NAME)
        print_info("VERSION", settings.VERSION)
        print_info("API_V1_STR", settings.API_V1_STR)
        print_info("DATABASE_URL", settings.DATABASE_URL)
        print_info("LOG_LEVEL", settings.LOG_LEVEL)
        print_success("Configuración cargada correctamente")
        return True
    except Exception as e:
        print_error(f"Error al cargar configuración: {e}")
        return False


def verify_database_type():
    """Verifica la detección del tipo de base de datos."""
    print_header("Tipo de Base de Datos")
    
    if settings.is_sqlite:
        print_info("Tipo", "SQLite (Desarrollo)")
        print_info("Pool", "StaticPool")
    elif settings.is_postgresql:
        print_info("Tipo", "PostgreSQL (Producción)")
        print_info("Pool Size", str(settings.DB_POOL_SIZE))
        print_info("Max Overflow", str(settings.DB_MAX_OVERFLOW))
        print_info("Pool Timeout", f"{settings.DB_POOL_TIMEOUT}s")
        print_info("Pool Recycle", f"{settings.DB_POOL_RECYCLE}s")
    elif settings.is_sqlserver:
        print_info("Tipo", "SQL Server (Producción)")
        print_info("Pool Size", str(settings.DB_POOL_SIZE))
        print_info("Max Overflow", str(settings.DB_MAX_OVERFLOW))
    else:
        print_error("Tipo de base de datos no reconocido")
        return False
    
    print_success("Tipo de base de datos detectado correctamente")
    return True


def verify_engine():
    """Verifica que el engine esté configurado correctamente."""
    print_header("Engine de SQLAlchemy")
    
    try:
        print_info("URL", str(engine.url))
        print_info("Driver", engine.driver)
        print_info("Pool Class", engine.pool.__class__.__name__)
        print_success("Engine configurado correctamente")
        return True
    except Exception as e:
        print_error(f"Error al verificar engine: {e}")
        return False


def verify_session_factory():
    """Verifica que la session factory esté configurada correctamente."""
    print_header("Session Factory")
    
    try:
        db = SessionLocal()
        print_info("Autocommit", str(db.autocommit))
        print_info("Autoflush", str(db.autoflush))
        print_info("Bind", str(db.bind))
        db.close()
        print_success("Session factory configurada correctamente")
        return True
    except Exception as e:
        print_error(f"Error al verificar session factory: {e}")
        return False


def verify_base():
    """Verifica que Base esté configurada correctamente."""
    print_header("Base Declarativa")
    
    try:
        print_info("Metadata", str(Base.metadata))
        print_info("Tablas registradas", str(len(Base.metadata.tables)))
        print_success("Base declarativa configurada correctamente")
        return True
    except Exception as e:
        print_error(f"Error al verificar Base: {e}")
        return False


def verify_get_db():
    """Verifica que la dependencia get_db funcione correctamente."""
    print_header("Dependencia get_db()")
    
    try:
        db_generator = get_db()
        db = next(db_generator)
        print_info("Sesión creada", "Sí")
        print_info("Sesión activa", str(db.is_active))
        
        # Cerrar la sesión
        try:
            next(db_generator)
        except StopIteration:
            pass
        
        print_info("Sesión cerrada", str(not db.is_active))
        print_success("Dependencia get_db() funciona correctamente")
        return True
    except Exception as e:
        print_error(f"Error al verificar get_db(): {e}")
        return False


def verify_connection():
    """Verifica la conexión a la base de datos."""
    print_header("Conexión a Base de Datos")
    
    if check_db_connection():
        print_success("Conexión exitosa")
        return True
    else:
        print_error("No se pudo conectar a la base de datos")
        print()
        print("Verifica:")
        print("  1. Que la base de datos esté en ejecución")
        print("  2. Que DATABASE_URL en .env sea correcta")
        print("  3. Que las credenciales sean válidas")
        return False


def verify_alembic():
    """Verifica que Alembic esté configurado correctamente."""
    print_header("Configuración de Alembic")
    
    alembic_ini = Path(__file__).resolve().parent.parent / "alembic.ini"
    alembic_dir = Path(__file__).resolve().parent.parent / "alembic"
    env_py = alembic_dir / "env.py"
    versions_dir = alembic_dir / "versions"
    
    checks = [
        ("alembic.ini", alembic_ini.exists()),
        ("alembic/", alembic_dir.exists()),
        ("alembic/env.py", env_py.exists()),
        ("alembic/versions/", versions_dir.exists()),
    ]
    
    all_ok = True
    for name, exists in checks:
        if exists:
            print_info(name, "✓ Existe")
        else:
            print_info(name, "✗ No existe")
            all_ok = False
    
    if all_ok:
        print_success("Alembic configurado correctamente")
    else:
        print_error("Faltan archivos de Alembic")
    
    return all_ok


def main():
    """Función principal del script."""
    print()
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 68 + "║")
    print("║" + "  Verificación de Configuración - AlwaysPrint Cloud Management".ljust(68) + "║")
    print("║" + "  Tarea 2.1: Configurar SQLAlchemy y Alembic".ljust(68) + "║")
    print("║" + " " * 68 + "║")
    print("╚" + "═" * 68 + "╝")
    
    results = []
    
    # Ejecutar verificaciones
    results.append(("Configuración", verify_settings()))
    results.append(("Tipo de Base de Datos", verify_database_type()))
    results.append(("Engine", verify_engine()))
    results.append(("Session Factory", verify_session_factory()))
    results.append(("Base Declarativa", verify_base()))
    results.append(("Dependencia get_db()", verify_get_db()))
    results.append(("Conexión a BD", verify_connection()))
    results.append(("Alembic", verify_alembic()))
    
    # Resumen
    print_header("Resumen de Verificación")
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {name:30s}: {status}")
    
    print()
    print(f"  Total: {passed}/{total} verificaciones exitosas")
    
    if passed == total:
        print()
        print("╔" + "═" * 68 + "╗")
        print("║" + " " * 68 + "║")
        print("║" + "  ✓ TODAS LAS VERIFICACIONES EXITOSAS".ljust(68) + "║")
        print("║" + " " * 68 + "║")
        print("║" + "  La configuración de SQLAlchemy y Alembic está completa.".ljust(68) + "║")
        print("║" + " " * 68 + "║")
        print("║" + "  Próximos pasos:".ljust(68) + "║")
        print("║" + "    1. Crear modelos en app/models/".ljust(68) + "║")
        print("║" + "    2. Importar modelos en alembic/env.py".ljust(68) + "║")
        print("║" + "    3. Generar migración: alembic revision --autogenerate".ljust(68) + "║")
        print("║" + "    4. Aplicar migración: alembic upgrade head".ljust(68) + "║")
        print("║" + " " * 68 + "║")
        print("╚" + "═" * 68 + "╝")
        print()
        return 0
    else:
        print()
        print("╔" + "═" * 68 + "╗")
        print("║" + " " * 68 + "║")
        print("║" + "  ✗ ALGUNAS VERIFICACIONES FALLARON".ljust(68) + "║")
        print("║" + " " * 68 + "║")
        print("║" + "  Revisa los errores anteriores y corrige la configuración.".ljust(68) + "║")
        print("║" + " " * 68 + "║")
        print("╚" + "═" * 68 + "╝")
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())
