"""Crear tablas para capturas de debugging a nivel de organización

Revision ID: 025_create_debugging
Revises: 024_fix_audit_enum_case
Create Date: 2026-06-28 20:00:00.000000

Crea las tablas debugging_profiles y debugging_sessions para el sistema
de capturas de debugging bajo demanda. Incluye el enum debuggingsessionstatus
para los estados del ciclo de vida de una sesión.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '025_create_debugging'
down_revision: Union[str, None] = '024_fix_audit_enum_case'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Crear tablas debugging_profiles y debugging_sessions con enum de status."""

    # Crear enum de forma idempotente
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE debuggingsessionstatus AS ENUM (
                'active', 'ready', 'uploading', 'analyzing',
                'analyzed', 'analysis_failed', 'deleted', 'failed'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    # Tabla debugging_profiles
    op.create_table(
        'debugging_profiles',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('organization_id', sa.String(36),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(60), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('confirmation_message', sa.String(200), nullable=False),
        sa.Column('external_logs', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('eventlog_groups', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('registry_keys', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('monitored_services', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_by', sa.String(36),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        'ix_debugging_profiles_org_active',
        'debugging_profiles',
        ['organization_id', 'is_active']
    )

    # Tabla debugging_sessions
    op.create_table(
        'debugging_sessions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('organization_id', sa.String(36),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('profile_id', sa.String(36),
                  sa.ForeignKey('debugging_profiles.id', ondelete='SET NULL'), nullable=True),
        sa.Column('workstation_id', sa.String(36),
                  sa.ForeignKey('workstations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status',
                  sa.Enum('active', 'ready', 'uploading', 'analyzing', 'analyzed',
                          'analysis_failed', 'deleted', 'failed',
                          name='debuggingsessionstatus', create_type=False),
                  nullable=False, server_default='active'),
        sa.Column('duration_seconds', sa.Integer(), nullable=False),
        sa.Column('start_time', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('end_time', sa.DateTime(), nullable=True),
        sa.Column('motivo', sa.Text(), nullable=True),
        sa.Column('additional_instructions', sa.Text(), nullable=True),
        sa.Column('total_data_size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('s3_report_key', sa.String(500), nullable=True),
        sa.Column('initiated_by', sa.String(36),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        'ix_debugging_sessions_org_status',
        'debugging_sessions',
        ['organization_id', 'status']
    )
    op.create_index(
        'ix_debugging_sessions_ws_status',
        'debugging_sessions',
        ['workstation_id', 'status']
    )


def downgrade() -> None:
    """Eliminar tablas de debugging y enum."""
    op.drop_table('debugging_sessions')
    op.drop_table('debugging_profiles')
    sa.Enum(name='debuggingsessionstatus').drop(op.get_bind(), checkfirst=True)
