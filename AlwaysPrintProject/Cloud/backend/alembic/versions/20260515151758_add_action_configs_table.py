"""add action_configs table

Revision ID: 20260515151758
Revises: 007_add_telemetry_connectivity
Create Date: 2026-05-15 15:17:58

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20260515151758'
down_revision = '007_add_telemetry_connectivity'
branch_labels = None
depends_on = None


def upgrade():
    """Crear tabla action_configs."""
    op.create_table(
        'action_configs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False, comment='Nombre de la configuración (ej: CPM_Compliant)'),
        sa.Column('version', sa.String(length=50), nullable=False, comment='Versión de la configuración (ej: 1.0)'),
        sa.Column('description', sa.Text(), nullable=True, comment='Descripción de la configuración'),
        sa.Column('config_json', sa.Text(), nullable=False, comment='JSON completo del archivo .alwaysconfig'),
        sa.Column('config_hash', sa.String(length=8), nullable=False, comment='Hash SHA256 corto (8 chars)'),
        sa.Column('is_active', sa.Boolean(), nullable=False, comment='Si está activa para propagación'),
        sa.Column('storage_path', sa.String(length=500), nullable=True, comment='Ruta en S3 o filesystem local'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('created_by_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['organization_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Índices
    op.create_index('ix_action_configs_id', 'action_configs', ['id'])
    op.create_index('ix_action_configs_config_hash', 'action_configs', ['config_hash'])
    op.create_index('ix_action_configs_org_active', 'action_configs', ['organization_id', 'is_active'])
    op.create_index('ix_action_configs_org_hash', 'action_configs', ['organization_id', 'config_hash'])


def downgrade():
    """Eliminar tabla action_configs."""
    op.drop_index('ix_action_configs_org_hash', table_name='action_configs')
    op.drop_index('ix_action_configs_org_active', table_name='action_configs')
    op.drop_index('ix_action_configs_config_hash', table_name='action_configs')
    op.drop_index('ix_action_configs_id', table_name='action_configs')
    op.drop_table('action_configs')
