"""Corregir case de valores enum actiontype agregados en migración 033.

Revision ID: 034_fix_login_audit_enum_case
Revises: 033_add_login_audit_actions
Create Date: 2026-08-07

La migración 033 agregó los valores en minúscula ('login', 'login_failed')
pero el enum actiontype usa MAYÚSCULAS (mismo bug ya documentado en la
migración 024_fix_audit_enum_case para 'cert_generated'/'cert_rotated'/
'ondemand_executed'). SQLAlchemy sin values_callable envía el nombre del
atributo del enum de Python (MAYÚSCULA), causando:
DataError: invalid input value for enum actiontype: "LOGIN"

Solución: Agregar las variantes en MAYÚSCULA. Las variantes en minúscula
agregadas por error en 033 quedan huérfanas (PostgreSQL no permite eliminar
valores de un enum sin recrear el tipo), igual que se hizo en 024.
"""
from typing import Sequence, Union
from alembic import op

revision: str = '034_fix_login_audit_enum_case'
down_revision: Union[str, None] = '033_add_login_audit_actions'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Agregar valores de login en MAYÚSCULA al enum actiontype."""
    op.execute("ALTER TYPE actiontype ADD VALUE IF NOT EXISTS 'LOGIN'")
    op.execute("ALTER TYPE actiontype ADD VALUE IF NOT EXISTS 'LOGIN_FAILED'")


def downgrade() -> None:
    """No-op: PostgreSQL no permite eliminar valores de un enum existente."""
    pass
