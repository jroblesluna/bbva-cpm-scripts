"""Agregar campos contingency_ip y contingency_started_at a workstations

Revision ID: 006_add_contingency_ip_started_at
Revises: 005_add_forced_contingency
Create Date: 2026-05-20 10:00:00.000000

Esta migración agrega campos para rastrear la IP de contingencia activa
y el momento en que se activó la contingencia en cada workstation.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# Identificadores de revisión utilizados por Alembic
revision: str = '006_contingency_ip'
down_revision: Union[str, None] = '005_add_forced_contingency'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Agregar columnas contingency_ip y contingency_started_at a workstations."""
    op.add_column(
        'workstations',
        sa.Column('contingency_ip', sa.String(45), nullable=True)
    )
    op.add_column(
        'workstations',
        sa.Column('contingency_started_at', sa.DateTime(), nullable=True)
    )


def downgrade() -> None:
    """Eliminar columnas contingency_ip y contingency_started_at de workstations."""
    op.drop_column('workstations', 'contingency_started_at')
    op.drop_column('workstations', 'contingency_ip')
