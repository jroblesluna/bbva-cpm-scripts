"""Agregar campo metadata JSON a la tabla vlans

Revision ID: 007_add_vlan_metadata
Revises: 006_action_config_hierarchy
Create Date: 2026-06-01 12:00:00.000000

Agrega columna metadata (JSON, nullable) a la tabla vlans para almacenar
pares clave-valor arbitrarios como remote_queue_path y otras configuraciones
específicas de la VLAN.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '007_add_vlan_metadata'
down_revision: Union[str, None] = '006_action_config_hierarchy'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Agregar columna metadata a vlans."""
    op.add_column('vlans', sa.Column(
        'metadata', sa.JSON(), nullable=True,
        comment="Metadatos arbitrarios de la VLAN (ej: remote_queue_path)"
    ))


def downgrade() -> None:
    """Eliminar columna metadata de vlans."""
    op.drop_column('vlans', 'metadata')
