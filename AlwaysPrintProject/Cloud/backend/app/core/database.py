"""
Configuración de SQLAlchemy para gestión de base de datos.

Este módulo configura el engine, session factory y base declarativa
para SQLAlchemy, soportando SQLite, PostgreSQL y SQL Server.
"""

from typing import Generator
from sqlalchemy import create_engine, event, text, Engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool, NullPool

from app.core.config import settings


# === CONFIGURACIÓN DEL ENGINE ===

def get_engine_config() -> dict:
    """
    Obtiene la configuración del engine según el tipo de base de datos.
    
    Returns:
        dict: Configuración del engine para create_engine()
    """
    config = {
        "echo": settings.LOG_LEVEL == "DEBUG",  # Log de queries SQL en modo debug
    }
    
    if settings.is_sqlite:
        # SQLite: configuración para desarrollo/testing
        # Usar NullPool para evitar problemas de concurrencia
        # Cada petición obtiene una nueva conexión que se cierra al terminar
        config.update({
            "connect_args": {
                "check_same_thread": False,
                "timeout": 30  # Timeout de 30 segundos para locks
            },
            "poolclass": NullPool,  # Sin pool - nueva conexión por petición
        })
    else:
        # PostgreSQL/SQL Server: configuración para producción
        config.update({
            "pool_size": settings.DB_POOL_SIZE,
            "max_overflow": settings.DB_MAX_OVERFLOW,
            "pool_timeout": settings.DB_POOL_TIMEOUT,
            "pool_recycle": settings.DB_POOL_RECYCLE,
            "pool_pre_ping": True,  # Verifica conexiones antes de usarlas
        })
    
    return config


# Crear engine con configuración apropiada
engine = create_engine(
    settings.DATABASE_URL,
    **get_engine_config()
)


# === HABILITAR FOREIGN KEYS EN SQLITE ===

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    """
    Habilita foreign keys en SQLite.
    
    SQLite no habilita foreign keys por defecto, este listener
    las activa automáticamente al conectarse.
    """
    if settings.is_sqlite:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


# === SESSION FACTORY ===

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


# === BASE DECLARATIVA ===

Base = declarative_base()


# === DEPENDENCIA PARA FASTAPI ===

def get_db() -> Generator[Session, None, None]:
    """
    Dependencia de FastAPI para obtener una sesión de base de datos.
    
    Uso en endpoints:
        @app.get("/items")
        def read_items(db: Session = Depends(get_db)):
            return db.query(Item).all()
    
    Yields:
        Session: Sesión de SQLAlchemy que se cierra automáticamente
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# === FUNCIONES DE UTILIDAD ===

def init_db() -> None:
    """
    Inicializa la base de datos creando todas las tablas.
    
    Esta función debe llamarse al iniciar la aplicación si no se usan
    migraciones de Alembic, o para crear la base de datos inicial.
    
    Nota: En producción, usar Alembic para gestionar el esquema.
    """
    Base.metadata.create_all(bind=engine)


def drop_db() -> None:
    """
    Elimina todas las tablas de la base de datos.
    
    ADVERTENCIA: Esta función es destructiva y solo debe usarse
    en desarrollo o testing.
    """
    Base.metadata.drop_all(bind=engine)


def check_db_connection() -> bool:
    """
    Verifica que la conexión a la base de datos funcione correctamente.
    
    Returns:
        bool: True si la conexión es exitosa, False en caso contrario
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        print(f"Error al conectar con la base de datos: {e}")
        return False
