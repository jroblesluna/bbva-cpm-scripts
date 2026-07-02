"""Agregar campo signature_paused_until a organizations.

Revision ID: 026
Revises: 025
Create Date: 2026-07-01

Permite suspender temporalmente la firma ECDSA de configuraciones
para que workstations con versiones legacy puedan descargar configs
sin envelope firmado y actualizarse. Auto-expira después del tiempo
configurado sin intervención manual.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = '026'
down_revision = '025'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Agregar campo signature_paused_until a organizations."""
    op.add_column(
        'organizations',
        sa.Column('signature_paused_until', sa.DateTime, nullable=True,
                  comment='Si no es NULL y > now(), la firma ECDSA está pausada temporalmente')
    )


def downgrade() -> None:
    """Eliminar campo signature_paused_until."""
    op.drop_column('organizations', 'signature_paused_until')
