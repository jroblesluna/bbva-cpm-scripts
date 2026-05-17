"""Agregar campo auto_update_enabled a la tabla accounts

Revision ID: 002_add_auto_update_enabled
Revises: 001_initial_schema
Create Date: 2026-06-21 00:00:00.000000

Agrega un campo booleano `auto_update_enabled` a la tabla `accounts`
que controla si las workstations de una organización pueden
actualizarse automáticamente. Por defecto está deshabilitado (false).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# Identificadores de revisión utilizados por Alembic
revision: str = '002_add_auto_update_enabled'
down_revision: Union[str, None] = '001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Agregar columna auto_update_enabled a la tabla accounts."""
    op.add_column('accounts', sa.Column(
        'auto_update_enabled',
        sa.Boolean(),
        nullable=False,
        server_default='false'
    ))


def downgrade() -> None:
    """Eliminar columna auto_update_enabled de la tabla accounts."""
    op.drop_column('accounts', 'auto_update_enabled')
