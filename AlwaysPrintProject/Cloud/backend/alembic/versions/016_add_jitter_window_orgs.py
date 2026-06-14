"""Agregar campo jitter_window_seconds a organizations

Revision ID: 016_add_jitter_window_orgs
Revises: 015_add_offline_timeout
Create Date: 2026-06-15 12:00:00.000000

Agrega columna Integer NOT NULL con server_default='30' para definir la ventana
de jitter en segundos para distribución de reconexiones tras eventos masivos.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '016_add_jitter_window_orgs'
down_revision: Union[str, None] = '015_add_offline_timeout'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Añadir columna jitter_window_seconds a organizations."""
    op.add_column(
        'organizations',
        sa.Column('jitter_window_seconds', sa.Integer(), nullable=False, server_default='30')
    )


def downgrade() -> None:
    """Eliminar columna jitter_window_seconds de organizations."""
    op.drop_column('organizations', 'jitter_window_seconds')
