from logging.config import fileConfig
from sqlalchemy import create_engine, pool
from alembic import context
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.core.database import Base

from app.models.user import User, UserRole
from app.models.organization import Organization, PublicIP
from app.models.workstation import Workstation, License
from app.models.vlan import VLAN
from app.models.config import GlobalConfig, VLANConfig, WorkstationConfig
from app.models.audit import AuditLog, ActionType
from app.models.message import Message, TargetType

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    # Usar settings.DATABASE_URL directamente — evita que configparser
    # interpole caracteres especiales (%, [, ]) como sintaxis de interpolación.
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # create_engine directo evita pasar la URL por configparser,
    # que falla con contraseñas que contienen %, [ o ].
    connectable = create_engine(settings.DATABASE_URL, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
