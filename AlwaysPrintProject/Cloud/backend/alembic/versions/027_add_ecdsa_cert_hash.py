"""Agregar campo ecdsa_cert_hash a organizations para validación de integridad del certificado.

Revision ID: 027_add_ecdsa_cert_hash
Revises: 026_add_signature_paused
Create Date: 2026-07-03

El cert_hash se envía en el enrichment WebSocket para que las workstations
validen que el .cer en disco no fue manipulado antes de usarlo para verificar firmas.
"""

from alembic import op
import sqlalchemy as sa
from typing import Union, Sequence

# revision identifiers
revision: str = '027_add_ecdsa_cert_hash'
down_revision: Union[str, None] = '026_add_signature_paused'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('organizations', sa.Column('ecdsa_cert_hash', sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column('organizations', 'ecdsa_cert_hash')
