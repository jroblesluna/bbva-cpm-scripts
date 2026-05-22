"""Agregar campo default_device_id a tabla vlans

Revision ID: 002_add_default_device_vlans
Revises: 001_initial_schema
Create Date: 2026-05-22 12:00:00.000000

Agrega columna default_device_id (FK a devices.id) a la tabla vlans para permitir
asignar una impresora predeterminada a nivel de VLAN. Las workstations de la VLAN
que no tengan impresora favorita individual usarán esta como fallback.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '002_add_default_device_vlans'
down_revision: Union[str, None] = '001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Agregar columna default_device_id a vlans con FK a devices."""
    op.add_column(
        'vlans',
        sa.Column('default_device_id', postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        'fk_vlans_default_device_id',
        'vlans', 'devices',
        ['default_device_id'], ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    """Eliminar columna default_device_id de vlans."""
    op.drop_constraint('fk_vlans_default_device_id', 'vlans', type_='foreignkey')
    op.drop_column('vlans', 'default_device_id')
