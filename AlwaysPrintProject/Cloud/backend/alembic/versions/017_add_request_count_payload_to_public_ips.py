"""Agregar request_count y first_payload a public_ips

Revision ID: 017_add_request_count_payload_to_public_ips
Revises: 016_add_jitter_window_orgs
Create Date: 2026-06-14 22:00:00.000000

Agrega campos de diagnóstico para IPs pendientes:
- request_count: contador de intentos de registro (default 1)
- first_payload: JSON del primer request para análisis
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '017_add_request_count_payload_to_public_ips'
down_revision: Union[str, None] = '016_add_jitter_window_orgs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'public_ips',
        sa.Column('request_count', sa.Integer(), nullable=False, server_default='1')
    )
    op.add_column(
        'public_ips',
        sa.Column('first_payload', sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('public_ips', 'first_payload')
    op.drop_column('public_ips', 'request_count')
