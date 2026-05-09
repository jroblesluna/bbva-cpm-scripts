"""
Script de entorno de Alembic para AlwaysPrint Cloud Management.

Este script configura Alembic para usar la configuración de SQLAlchemy
de la aplicación, permitiendo migraciones automáticas.
"""

from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
import sys
from pathlib import Path

# Agregar el directorio raíz al path para importar la aplicación
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.core.database import Base

# Importar todos los modelos para que Alembic los detecte
# IMPORTANTE: Estos imports son necesarios para que Alembic detecte los modelos
from app.models.user import User, UserRole
from app.models.account import Account, PublicIP
from app.models.workstation import Workstation, License
from app.models.vlan import VLAN
from app.models.config import GlobalConfig, VLANConfig, WorkstationConfig
from app.models.audit import AuditLog, ActionType
from app.models.message import Message, TargetType

# Configuración de Alembic
config = context.config

# Sobrescribir sqlalchemy.url con la configuración de la aplicación
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Configurar logging desde alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata de los modelos para autogenerar migraciones
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Ejecuta migraciones en modo 'offline'.
    
    En este modo, no se requiere una conexión activa a la base de datos.
    Se genera SQL que puede ejecutarse manualmente.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,  # Detectar cambios en tipos de columnas
        compare_server_default=True,  # Detectar cambios en valores por defecto
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Ejecuta migraciones en modo 'online'.
    
    En este modo, se crea una conexión activa a la base de datos
    y se ejecutan las migraciones directamente.
    """
    # Configuración del engine según el tipo de base de datos
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = settings.DATABASE_URL
    
    # Agregar configuración de pool para bases de datos de producción
    if not settings.is_sqlite:
        configuration["sqlalchemy.pool_size"] = str(settings.DB_POOL_SIZE)
        configuration["sqlalchemy.max_overflow"] = str(settings.DB_MAX_OVERFLOW)
        configuration["sqlalchemy.pool_timeout"] = str(settings.DB_POOL_TIMEOUT)
        configuration["sqlalchemy.pool_recycle"] = str(settings.DB_POOL_RECYCLE)
    
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # No usar pool en migraciones
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,  # Detectar cambios en tipos de columnas
            compare_server_default=True,  # Detectar cambios en valores por defecto
        )

        with context.begin_transaction():
            context.run_migrations()


# Determinar si ejecutar en modo offline u online
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
