"""
Módulo core de la aplicación.

Contiene configuración, base de datos y utilidades de seguridad.
"""

from app.core.config import settings
from app.core.database import (
    Base,
    engine,
    SessionLocal,
    get_db,
    init_db,
    drop_db,
    check_db_connection,
)

__all__ = [
    "settings",
    "Base",
    "engine",
    "SessionLocal",
    "get_db",
    "init_db",
    "drop_db",
    "check_db_connection",
]
