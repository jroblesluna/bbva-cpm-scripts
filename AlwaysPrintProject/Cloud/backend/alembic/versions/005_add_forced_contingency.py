"""Agregar campo forced_contingency a organizations, vlans y workstations

Revision ID: 005_add_forced_contingency
Revises: 004_add_devices_table
Create Date: 2026-05-19 20:00:00.000000

Esta migración agrega el campo 'forced_contingency' (Boolean) a las tablas:
- organizations: contingencia forzada a nivel de organización (hereda a VLANs y workstations)
- vlans: contingencia forzada a nivel de VLAN (hereda a workstations de esa VLAN)
- workstations: contingencia forzada a nivel individual
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# Identificadores de revisión utilizados por Alembic
revision: str = '005_add_forced_contingency'
down_revision: Union[str, None] = '004_add_devices_table'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Agregar columna forced_contingency a organizations, vlans y workstations."""
    op.add_column(
        'organizations',
        sa.Column('forced_contingency', sa.Boolean(), nullable=False, server_default='false')
    )
    op.add_column(
        'vlans',
        sa.Column('forced_contingency', sa.Boolean(), nullable=False, server_default='false')
    )
    op.add_column(
        'workstations',
        sa.Column('forced_contingency', sa.Boolean(), nullable=False, server_default='false')
    )


def downgrade() -> None:
    """Revertir: eliminar columna forced_contingency de las tres tablas."""
    op.drop_column('workstations', 'forced_contingency')
    op.drop_column('vlans', 'forced_contingency')
    op.drop_column('organizations', 'forced_contingency')
