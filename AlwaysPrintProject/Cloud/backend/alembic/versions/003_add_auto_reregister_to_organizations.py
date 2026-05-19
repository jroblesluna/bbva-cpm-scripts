"""Agregar columna auto_reregister_enabled a tabla organizations

Revision ID: 003_add_auto_reregister
Revises: 002_add_cidr_tray_version
Create Date: 2026-05-19 12:00:00.000000

Esta migración agrega la columna auto_reregister_enabled a la tabla organizations.
Controla si las workstations eliminadas pueden re-registrarse automáticamente
cuando envían telemetría desde una IP pública autorizada.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# Identificadores de revisión utilizados por Alembic
revision: str = '003_add_auto_reregister'
down_revision: Union[str, None] = '002_add_cidr_tray_version'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Agregar columna auto_reregister_enabled a organizations."""
    op.add_column(
        'organizations',
        sa.Column('auto_reregister_enabled', sa.Boolean(), nullable=False, server_default='false')
    )


def downgrade() -> None:
    """Revertir: eliminar columna auto_reregister_enabled de organizations."""
    op.drop_column('organizations', 'auto_reregister_enabled')
