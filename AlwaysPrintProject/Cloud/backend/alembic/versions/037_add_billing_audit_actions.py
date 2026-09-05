"""Agregar acciones de auditoría de facturación (Usage and Billing, task 33).

Revision ID: 037_add_billing_audit_actions
Revises: 036_add_usage_and_billing
Create Date: 2026-08-20

Agrega 6 nuevos valores al enum PostgreSQL 'actiontype' para auditar las acciones
sensibles del módulo Usage and Billing (Req 11.4):
- BILLING_MODE_CHANGE: cambio de modalidad de facturación (monthly↔annual).
- TIMEZONE_LOCK: intento de cambio de timezone bloqueado tras el primer cierre.
- WORKSTATION_ARCHIVE: archivado manual de una workstation (soft-delete).
- RATE_PLAN_EDIT: edición de tarifas (plan por defecto o plan de organización).
- BILLING_CLOSURE: ejecución de un cierre mensual (automático o retroactivo).
- ANNUAL_SETTLEMENT: liquidación anual (creación de suscripción o confirmación).

IMPORTANTE (mismo criterio que las migraciones 022/033/035): SQLAlchemy, sin
`values_callable`, envía el NOMBRE del miembro del enum de Python (MAYÚSCULA) como
etiqueta del enum. Por eso los valores se agregan en MAYÚSCULA, coincidiendo con los
nombres definidos en `app/models/audit.py::ActionType`. `ADD VALUE IF NOT EXISTS` es
idempotente (PostgreSQL 9.3+).
"""
from typing import Sequence, Union
from alembic import op

revision: str = '037_add_billing_audit_actions'
down_revision: Union[str, None] = '036_add_usage_and_billing'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Agregar los valores de facturación al enum actiontype (MAYÚSCULA)."""
    op.execute("ALTER TYPE actiontype ADD VALUE IF NOT EXISTS 'BILLING_MODE_CHANGE'")
    op.execute("ALTER TYPE actiontype ADD VALUE IF NOT EXISTS 'TIMEZONE_LOCK'")
    op.execute("ALTER TYPE actiontype ADD VALUE IF NOT EXISTS 'WORKSTATION_ARCHIVE'")
    op.execute("ALTER TYPE actiontype ADD VALUE IF NOT EXISTS 'RATE_PLAN_EDIT'")
    op.execute("ALTER TYPE actiontype ADD VALUE IF NOT EXISTS 'BILLING_CLOSURE'")
    op.execute("ALTER TYPE actiontype ADD VALUE IF NOT EXISTS 'ANNUAL_SETTLEMENT'")


def downgrade() -> None:
    """No-op: PostgreSQL no permite eliminar valores de un enum existente."""
    pass
