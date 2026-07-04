"""Agregar campo ecdsa_cert_hash a organizations para validación de integridad del certificado.

Revision ID: 027
Revises: 026
Create Date: 2026-07-03

El cert_hash se envía en el enrichment WebSocket para que las workstations
validen que el .cer en disco no fue manipulado antes de usarlo para verificar firmas.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '027'
down_revision = '026'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('organizations', sa.Column('ecdsa_cert_hash', sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column('organizations', 'ecdsa_cert_hash')
