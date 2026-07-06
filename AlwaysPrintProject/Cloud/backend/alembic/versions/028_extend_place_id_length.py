"""Ampliar place_id de VARCHAR(100) a VARCHAR(300)

Revision ID: 024_extend_place_id_length
Revises: 023
Create Date: 2026-07-06

Los Google Place IDs de direcciones específicas en Perú pueden exceder
100 caracteres (hasta ~300 chars para direcciones con sub-premisa).
"""
from alembic import op
import sqlalchemy as sa


revision = '028_extend_place_id_length'
down_revision = '027_add_ecdsa_cert_hash'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Ampliar place_id a 300 caracteres."""
    op.alter_column('vlans', 'place_id',
                    existing_type=sa.String(100),
                    type_=sa.String(300),
                    existing_nullable=True)


def downgrade() -> None:
    """Revertir place_id a 100 caracteres."""
    op.alter_column('vlans', 'place_id',
                    existing_type=sa.String(300),
                    type_=sa.String(100),
                    existing_nullable=True)
