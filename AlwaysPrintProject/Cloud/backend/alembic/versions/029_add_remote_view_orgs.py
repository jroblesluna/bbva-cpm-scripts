"""Agregar campo remote_view (JSONB) a organizations.

Revision ID: 029_add_remote_view_orgs
Revises: 028_extend_place_id_length
Create Date: 2026-07-12

Configuración por organización para la funcionalidad de vista remota
de workstations. Almacena 13 campos de configuración como JSON.
Default: {"enabled": false} (feature deshabilitado por defecto).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from typing import Union, Sequence


# Identificadores de revisión
revision: str = '029_add_remote_view_orgs'
down_revision: Union[str, None] = '028_extend_place_id_length'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Configuración por defecto de remote_view
DEFAULT_REMOTE_VIEW = '{"enabled": false}'


def upgrade() -> None:
    """Agregar columna remote_view JSONB a organizations."""
    op.add_column(
        'organizations',
        sa.Column(
            'remote_view',
            JSONB,
            nullable=False,
            server_default=DEFAULT_REMOTE_VIEW,
        )
    )


def downgrade() -> None:
    """Eliminar columna remote_view de organizations."""
    op.drop_column('organizations', 'remote_view')
