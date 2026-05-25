"""Agregar action_config_mandatory a workstations

Revision ID: 008_add_ws_action_mandatory
Revises: 007_add_vlan_metadata
Create Date: 2026-05-25 20:00:00.000000

Agrega flag action_config_mandatory a workstations para completar
la jerarquía de herencia: Org → VLAN → Workstation.
Si es True, la workstation usa su propia action config
(solo aplica si ningún padre —org o vlan— tiene mandatory habilitado).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '008_add_ws_action_mandatory'
down_revision: Union[str, None] = '007_add_vlan_metadata'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Agregar columna action_config_mandatory a workstations."""
    op.add_column('workstations', sa.Column(
        'action_config_mandatory', sa.Boolean(),
        nullable=False, server_default='false',
        comment="Si es True, esta workstation usa su propia action config (solo si ningún padre es mandatory)"
    ))


def downgrade() -> None:
    """Eliminar columna action_config_mandatory de workstations."""
    op.drop_column('workstations', 'action_config_mandatory')
