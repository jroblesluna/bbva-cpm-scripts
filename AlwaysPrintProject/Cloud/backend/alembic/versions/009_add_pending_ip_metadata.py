"""Agregar metadata de estación a public_ips pendientes

Revision ID: 009_add_pending_ip_metadata
Revises: 008_add_ws_action_mandatory
Create Date: 2026-05-26 00:00:00.000000

Almacena hostname y usuario activo de la última estación que intentó
registrarse desde cada IP pendiente, para dar contexto al admin.
"""
from typing import Sequence, Union
from alembic import op


revision: str = '009_add_pending_ip_metadata'
down_revision: Union[str, None] = '008_add_ws_action_mandatory'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public_ips ADD COLUMN IF NOT EXISTS "
        "last_hostname VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE public_ips ADD COLUMN IF NOT EXISTS "
        "last_user VARCHAR(255)"
    )


def downgrade() -> None:
    op.drop_column('public_ips', 'last_hostname')
    op.drop_column('public_ips', 'last_user')
