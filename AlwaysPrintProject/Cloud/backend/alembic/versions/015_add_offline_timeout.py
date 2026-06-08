"""Agregar campo offline_timeout_minutes a organizations

Revision ID: 015_add_offline_timeout
Revises: 014_add_scalability_json
Create Date: 2026-07-10 12:00:00.000000

Agrega columna Integer NOT NULL con server_default='10' para definir los minutos
de inactividad permitidos antes de enviar Death Ping a las workstations de la org.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '015_add_offline_timeout'
down_revision: Union[str, None] = '014_add_scalability_json'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Añadir columna offline_timeout_minutes a organizations."""
    op.add_column(
        'organizations',
        sa.Column('offline_timeout_minutes', sa.Integer(), nullable=False, server_default='10')
    )


def downgrade() -> None:
    """Eliminar columna offline_timeout_minutes de organizations."""
    op.drop_column('organizations', 'offline_timeout_minutes')
