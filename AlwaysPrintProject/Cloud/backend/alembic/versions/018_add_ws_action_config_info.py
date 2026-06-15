"""Agregar action_config_name y action_config_hash a workstations

Revision ID: 018_add_ws_action_config_info
Revises: 017_add_ip_request_diagnostics
Create Date: 2026-06-15 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '018_add_ws_action_config_info'
down_revision: Union[str, None] = '017_add_ip_request_diagnostics'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'workstations',
        sa.Column('action_config_name', sa.String(100), nullable=True)
    )
    op.add_column(
        'workstations',
        sa.Column('action_config_hash', sa.String(16), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('workstations', 'action_config_hash')
    op.drop_column('workstations', 'action_config_name')
