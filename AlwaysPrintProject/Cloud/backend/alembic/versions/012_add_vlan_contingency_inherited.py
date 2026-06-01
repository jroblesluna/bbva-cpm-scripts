"""Agregar contingency_inherited a vlans

Revision ID: 012_add_vlan_contingency_inherited
Revises: 011_add_system_status
Create Date: 2026-06-01 00:00:00.000000

Permite rastrear si la contingencia de una VLAN fue activada por herencia
de su organización padre o de forma individual. Necesario para la
desactivación inteligente (solo deshabilita las heredadas, no las individuales).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '012_vlan_contingency_inh'
down_revision: Union[str, None] = '011_add_system_status'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'vlans',
        sa.Column('contingency_inherited', sa.Boolean(), nullable=True, server_default=sa.text('false'))
    )


def downgrade() -> None:
    op.drop_column('vlans', 'contingency_inherited')
