"""Agregar acciones de auditoría para login.

Revision ID: 033_add_login_audit_actions
Revises: 032_create_knowledge_articles
Create Date: 2026-08-07

Agrega 2 nuevos valores al enum PostgreSQL 'actiontype':
- LOGIN: al autenticarse exitosamente
- LOGIN_FAILED: al fallar un intento de autenticación
"""
from typing import Sequence, Union
from alembic import op

revision: str = '033_add_login_audit_actions'
down_revision: Union[str, None] = '032_create_knowledge_articles'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Agregar valores de login al enum actiontype."""
    op.execute("ALTER TYPE actiontype ADD VALUE IF NOT EXISTS 'login'")
    op.execute("ALTER TYPE actiontype ADD VALUE IF NOT EXISTS 'login_failed'")


def downgrade() -> None:
    """No-op: PostgreSQL no permite eliminar valores de un enum existente."""
    # Los valores de enum en PostgreSQL no se pueden eliminar con ALTER TYPE.
    # Para revertir completamente se requeriría recrear el tipo, lo cual es destructivo.
    pass
