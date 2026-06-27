"""Corregir case de valores enum actiontype agregados en migración 022

Revision ID: 024_fix_audit_enum_case
Revises: 023_normalize_config_hash
Create Date: 2026-06-27 21:00:00.000000

La migración 022 agregó valores en minúscula ('cert_generated', 'cert_rotated',
'ondemand_executed') pero el enum original usa MAYÚSCULAS ('CREATE', 'UPDATE', etc.).
SQLAlchemy sin values_callable envía el nombre del atributo (MAYÚSCULA), causando
DataError: invalid input value for enum actiontype: "ONDEMAND_EXECUTED".

Solución: Renombrar los valores en PostgreSQL de minúscula a MAYÚSCULA.
PostgreSQL 10+ soporta ALTER TYPE ... RENAME VALUE.
"""
from typing import Sequence, Union
from alembic import op

revision: str = '024_fix_audit_enum_case'
down_revision: Union[str, None] = '023_normalize_config_hash'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Renombrar valores del enum actiontype de minúscula a MAYÚSCULA."""
    # PostgreSQL 10+ soporta RENAME VALUE
    # Usamos DO block para manejar el caso donde ya estén en mayúscula (idempotencia)
    op.execute("""
        DO $$
        BEGIN
            -- Solo renombrar si el valor en minúscula existe
            IF EXISTS (
                SELECT 1 FROM pg_enum
                WHERE enumtypid = 'actiontype'::regtype
                AND enumlabel = 'cert_generated'
            ) THEN
                ALTER TYPE actiontype RENAME VALUE 'cert_generated' TO 'CERT_GENERATED';
            END IF;

            IF EXISTS (
                SELECT 1 FROM pg_enum
                WHERE enumtypid = 'actiontype'::regtype
                AND enumlabel = 'cert_rotated'
            ) THEN
                ALTER TYPE actiontype RENAME VALUE 'cert_rotated' TO 'CERT_ROTATED';
            END IF;

            IF EXISTS (
                SELECT 1 FROM pg_enum
                WHERE enumtypid = 'actiontype'::regtype
                AND enumlabel = 'ondemand_executed'
            ) THEN
                ALTER TYPE actiontype RENAME VALUE 'ondemand_executed' TO 'ONDEMAND_EXECUTED';
            END IF;
        END $$;
    """)


def downgrade() -> None:
    """Revertir nombres de enum a minúscula."""
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_enum
                WHERE enumtypid = 'actiontype'::regtype
                AND enumlabel = 'CERT_GENERATED'
            ) THEN
                ALTER TYPE actiontype RENAME VALUE 'CERT_GENERATED' TO 'cert_generated';
            END IF;

            IF EXISTS (
                SELECT 1 FROM pg_enum
                WHERE enumtypid = 'actiontype'::regtype
                AND enumlabel = 'CERT_ROTATED'
            ) THEN
                ALTER TYPE actiontype RENAME VALUE 'CERT_ROTATED' TO 'cert_rotated';
            END IF;

            IF EXISTS (
                SELECT 1 FROM pg_enum
                WHERE enumtypid = 'actiontype'::regtype
                AND enumlabel = 'ONDEMAND_EXECUTED'
            ) THEN
                ALTER TYPE actiontype RENAME VALUE 'ONDEMAND_EXECUTED' TO 'ondemand_executed';
            END IF;
        END $$;
    """)
