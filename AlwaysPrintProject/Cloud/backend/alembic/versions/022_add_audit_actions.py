"""Agregar nuevos valores al enum actiontype para firma ECDSA y OnDemand

Revision ID: 022_add_audit_actions
Revises: 021_add_ecdsa_orgs
Create Date: 2026-06-25 12:00:00.000000

Agrega tres nuevos valores al enum PostgreSQL 'actiontype':
- cert_generated: generación de certificado ECDSA
- cert_rotated: rotación de certificado ECDSA
- ondemand_executed: ejecución remota de acción OnDemand
"""
from typing import Sequence, Union
from alembic import op

revision: str = '022_add_audit_actions'
down_revision: Union[str, None] = '021_add_ecdsa_orgs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Agregar nuevos valores al enum actiontype."""
    # PostgreSQL ALTER TYPE ... ADD VALUE IF NOT EXISTS es idempotente (PG 9.3+)
    op.execute("ALTER TYPE actiontype ADD VALUE IF NOT EXISTS 'cert_generated'")
    op.execute("ALTER TYPE actiontype ADD VALUE IF NOT EXISTS 'cert_rotated'")
    op.execute("ALTER TYPE actiontype ADD VALUE IF NOT EXISTS 'ondemand_executed'")


def downgrade() -> None:
    """No se puede eliminar valores de un enum en PostgreSQL sin recrearlo."""
    # PostgreSQL no soporta DROP VALUE de un enum.
    # Se necesitaría recrear el tipo completo, lo cual es destructivo.
    pass
