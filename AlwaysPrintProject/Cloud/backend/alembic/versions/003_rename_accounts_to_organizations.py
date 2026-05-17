"""Renombrar tabla accounts a organizations y columnas account_id a organization_id

Revision ID: 003_rename_accounts_to_organizations
Revises: 002_add_auto_update_enabled
Create Date: 2026-06-22 00:00:00.000000

Migración completa de rename de la entidad multi-tenant:
- Tabla accounts → organizations
- Columnas account_id → organization_id en todas las tablas que la referencian
- Actualización de índices y foreign keys
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# Identificadores de revisión utilizados por Alembic
revision: str = '003_rename_accounts_to_organizations'
down_revision: Union[str, None] = '002_add_auto_update_enabled'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Renombrar tabla y columnas de accounts a organizations."""
    
    # 1. Renombrar la tabla principal
    op.rename_table('accounts', 'organizations')
    
    # 2. Renombrar columnas account_id → organization_id en todas las tablas
    # Nota: rename_column maneja automáticamente los índices en la mayoría de DBs
    
    # users.account_id → users.organization_id
    op.alter_column('users', 'account_id', new_column_name='organization_id')
    
    # workstations.account_id → workstations.organization_id
    op.alter_column('workstations', 'account_id', new_column_name='organization_id')
    
    # vlans.account_id → vlans.organization_id
    op.alter_column('vlans', 'account_id', new_column_name='organization_id')
    
    # global_configs.account_id → global_configs.organization_id
    op.alter_column('global_configs', 'account_id', new_column_name='organization_id')
    
    # messages.account_id → messages.organization_id
    op.alter_column('messages', 'account_id', new_column_name='organization_id')
    
    # audit_logs.account_id → audit_logs.organization_id
    op.alter_column('audit_logs', 'account_id', new_column_name='organization_id')
    
    # telemetry_logs.account_id → telemetry_logs.organization_id
    op.alter_column('telemetry_logs', 'account_id', new_column_name='organization_id')
    
    # connectivity_results.account_id → connectivity_results.organization_id
    op.alter_column('connectivity_results', 'account_id', new_column_name='organization_id')
    
    # public_ips.account_id → public_ips.organization_id
    op.alter_column('public_ips', 'account_id', new_column_name='organization_id')


def downgrade() -> None:
    """Revertir: renombrar organizations a accounts y organization_id a account_id."""
    
    # Revertir columnas organization_id → account_id
    op.alter_column('public_ips', 'organization_id', new_column_name='account_id')
    op.alter_column('connectivity_results', 'organization_id', new_column_name='account_id')
    op.alter_column('telemetry_logs', 'organization_id', new_column_name='account_id')
    op.alter_column('audit_logs', 'organization_id', new_column_name='account_id')
    op.alter_column('messages', 'organization_id', new_column_name='account_id')
    op.alter_column('global_configs', 'organization_id', new_column_name='account_id')
    op.alter_column('vlans', 'organization_id', new_column_name='account_id')
    op.alter_column('workstations', 'organization_id', new_column_name='account_id')
    op.alter_column('users', 'organization_id', new_column_name='account_id')
    
    # Revertir tabla
    op.rename_table('organizations', 'accounts')
