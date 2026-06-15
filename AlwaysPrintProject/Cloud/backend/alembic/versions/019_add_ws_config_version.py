"""Agregar action_config_version a workstations (fix para DEV donde 018 se aplicó sin esta columna)

Revision ID: 019_add_ws_config_version
Revises: 018_add_ws_action_config_info
Create Date: 2026-06-15 16:00:00.000000

En PROD, 018 ya incluye action_config_version. Esta migración es
idempotente: solo agrega la columna si no existe.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = '019_add_ws_config_version'
down_revision: Union[str, None] = '018_add_ws_action_config_info'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotente: solo agregar si no existe (PROD ya la tiene via 018)
    conn = op.get_bind()
    insp = inspect(conn)
    columns = [c['name'] for c in insp.get_columns('workstations')]
    if 'action_config_version' not in columns:
        op.add_column(
            'workstations',
            sa.Column('action_config_version', sa.String(20), nullable=True)
        )


def downgrade() -> None:
    op.drop_column('workstations', 'action_config_version')
