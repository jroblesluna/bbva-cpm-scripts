"""Agregar campos ECDSA de firma digital a organizations

Revision ID: 021_add_ecdsa_orgs
Revises: 020_add_vlan_geolocation
Create Date: 2026-06-25 10:00:00.000000

Agrega columnas para soporte de firma ECDSA en organizaciones:
- ecdsa_private_key_encrypted: clave privada cifrada con AES-256-GCM (Base64)
- ecdsa_cert_s3_key: key S3 del certificado .cer activo
- ecdsa_cert_version: versión del certificado (default 0)
- ecdsa_cert_expires_at: fecha de expiración del certificado
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '021_add_ecdsa_orgs'
down_revision: Union[str, None] = '020_add_vlan_geolocation'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Agregar campos ECDSA a la tabla organizations."""
    op.add_column('organizations', sa.Column('ecdsa_private_key_encrypted', sa.Text, nullable=True))
    op.add_column('organizations', sa.Column('ecdsa_cert_s3_key', sa.String(500), nullable=True))
    op.add_column('organizations', sa.Column('ecdsa_cert_version', sa.Integer, nullable=False, server_default='0'))
    op.add_column('organizations', sa.Column('ecdsa_cert_expires_at', sa.DateTime, nullable=True))


def downgrade() -> None:
    """Eliminar campos ECDSA de la tabla organizations."""
    op.drop_column('organizations', 'ecdsa_cert_expires_at')
    op.drop_column('organizations', 'ecdsa_cert_version')
    op.drop_column('organizations', 'ecdsa_cert_s3_key')
    op.drop_column('organizations', 'ecdsa_private_key_encrypted')
