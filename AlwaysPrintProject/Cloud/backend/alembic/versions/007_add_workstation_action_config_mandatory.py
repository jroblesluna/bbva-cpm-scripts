"""Agregar action_config_mandatory a workstations

Revision ID: 007_add_workstation_action_config_mandatory
Revises: 006_action_config_hierarchy
Create Date: 2026-05-25 19:00:00.000000

Agrega flag action_config_mandatory a workstations para completar
la jerarquía de herencia: Org → VLAN → Workstation.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '007_ws_action_config_mandatory'
down_revision: Union[str, None] = '006_action_config_hierarchy'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('workstations', sa.Column(
        'action_config_mandatory', sa.Boolean(),
        nullable=False, server_default='false',
        comment="Si es True, esta workstation usa su propia action config (solo si ningún padre es mandatory)"
    ))


def downgrade() -> None:
    op.drop_column('workstations', 'action_config_mandatory')
