"""Agregar columnas cidr y tray_version a tabla workstations

Revision ID: 002_add_cidr_tray_version
Revises: 001_initial_schema
Create Date: 2026-06-22 12:00:00.000000

Esta migración agrega dos columnas a la tabla workstations:
- cidr: CIDR de red reportado por la workstation (ej: "192.168.1.0/24")
- tray_version: versión del AlwaysPrintTray instalado (ej: "2.1.0.0")

Ambas columnas son nullable para mantener compatibilidad con workstations
existentes que aún no reportan estos campos.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# Identificadores de revisión utilizados por Alembic
revision: str = '002_add_cidr_tray_version'
down_revision: Union[str, None] = '001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Agregar columnas cidr y tray_version a workstations."""
    op.add_column('workstations', sa.Column('cidr', sa.String(45), nullable=True))
    op.add_column('workstations', sa.Column('tray_version', sa.String(50), nullable=True))


def downgrade() -> None:
    """Revertir: eliminar columnas cidr y tray_version de workstations."""
    op.drop_column('workstations', 'tray_version')
    op.drop_column('workstations', 'cidr')
