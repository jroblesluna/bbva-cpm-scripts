"""Agregar tabla devices y columna default_printer_id a workstations

Revision ID: 004_add_devices_table
Revises: 003_add_auto_reregister
Create Date: 2026-05-19 18:00:00.000000

Esta migración:
- Crea la tabla 'devices' para registrar impresoras
- Agrega columna 'default_printer_id' a 'workstations' para asignar impresora predeterminada
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# Identificadores de revisión utilizados por Alembic
revision: str = '004_add_devices_table'
down_revision: Union[str, None] = '003_add_auto_reregister'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Crear tabla devices y agregar default_printer_id a workstations."""
    # Crear tabla de dispositivos
    op.create_table(
        'devices',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('organization_id', sa.String(36), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('vlan_id', sa.String(36), sa.ForeignKey('vlans.id', ondelete='SET NULL'), nullable=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('ip_address', sa.String(45), nullable=False),
        sa.Column('description', sa.String(1000), nullable=True),
        sa.Column('model', sa.String(255), nullable=True),
        sa.Column('location', sa.String(500), nullable=True),
        sa.Column('port', sa.Integer(), nullable=False, server_default='9100'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    
    # Agregar columna de impresora predeterminada a workstations
    op.add_column(
        'workstations',
        sa.Column('default_printer_id', sa.String(36), sa.ForeignKey('devices.id', ondelete='SET NULL'), nullable=True)
    )


def downgrade() -> None:
    """Revertir: eliminar columna default_printer_id y tabla devices."""
    op.drop_column('workstations', 'default_printer_id')
    op.drop_table('devices')
