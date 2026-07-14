"""Agregar acciones de auditoría para remote view.

Revision ID: 031_add_rv_audit_actions
Revises: 030_create_rv_sessions
Create Date: 2026-07-13

Agrega 3 nuevos valores al enum PostgreSQL 'actiontype':
- REMOTE_VIEW_START: al iniciar una sesión de vista remota
- REMOTE_VIEW_STOP: al cerrar una sesión de vista remota
- REMOTE_VIEW_MODE_CHANGE: al cambiar el modo durante una sesión
"""
from typing import Sequence, Union
from alembic import op

revision: str = '031_add_rv_audit_actions'
down_revision: Union[str, None] = '030_create_rv_sessions'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Agregar valores de remote view al enum actiontype."""
    op.execute("ALTER TYPE actiontype ADD VALUE IF NOT EXISTS 'REMOTE_VIEW_START'")
    op.execute("ALTER TYPE actiontype ADD VALUE IF NOT EXISTS 'REMOTE_VIEW_STOP'")
    op.execute("ALTER TYPE actiontype ADD VALUE IF NOT EXISTS 'REMOTE_VIEW_MODE_CHANGE'")


def downgrade() -> None:
    """No-op: PostgreSQL no permite eliminar valores de un enum existente."""
    # Los valores de enum en PostgreSQL no se pueden eliminar con ALTER TYPE.
    # Para revertir completamente se requeriría recrear el tipo, lo cual es destructivo.
    pass
