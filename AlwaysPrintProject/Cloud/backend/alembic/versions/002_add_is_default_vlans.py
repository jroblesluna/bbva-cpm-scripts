"""Agregar campo is_default a tabla vlans

Revision ID: 002_add_is_default_vlans
Revises: 001_initial_schema
Create Date: 2026-05-22 12:00:00.000000

Agrega columna is_default (Boolean) a la tabla vlans para permitir
marcar una VLAN como predeterminada por organización. Las workstations
que no coincidan con ningún CIDR se asignarán a la VLAN predeterminada.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '002_add_is_default_vlans'
down_revision: Union[str, None] = '001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Agregar columna is_default a vlans con server_default false."""
    op.add_column(
        'vlans',
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false')
    )


def downgrade() -> None:
    """Eliminar columna is_default de vlans."""
    op.drop_column('vlans', 'is_default')
