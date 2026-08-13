"""Agregar acción de auditoría para ejecución de comandos remotos.

Revision ID: 035_add_remote_cmd_audit
Revises: 034_fix_login_audit_enum_case
Create Date: 2026-08-14

Agrega el valor 'REMOTE_COMMAND_EXECUTED' al enum PostgreSQL 'actiontype'.
Se usa para registrar cuando un Admin/Operator ejecuta un comando OS
en una workstation remota vía Remote Terminal.
"""
from typing import Sequence, Union
from alembic import op

revision: str = '035_add_remote_cmd_audit'
down_revision: Union[str, None] = '034_fix_login_audit_enum_case'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Agregar valor REMOTE_COMMAND_EXECUTED al enum actiontype."""
    op.execute("ALTER TYPE actiontype ADD VALUE IF NOT EXISTS 'REMOTE_COMMAND_EXECUTED'")


def downgrade() -> None:
    """No-op: PostgreSQL no permite eliminar valores de un enum existente."""
    pass
