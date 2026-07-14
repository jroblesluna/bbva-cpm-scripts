"""Crear tabla remote_view_sessions.

Revision ID: 030_create_remote_view_sessions
Revises: 029_add_remote_view_orgs
Create Date: 2026-07-13

Tabla para registrar sesiones de vista remota entre operadores y workstations.
Incluye índices parciales para optimizar consultas de sesiones activas.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from typing import Union, Sequence


# Identificadores de revisión
revision: str = '030_create_remote_view_sessions'
down_revision: Union[str, None] = '029_add_remote_view_orgs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Crear tabla remote_view_sessions con índices parciales."""
    op.create_table(
        'remote_view_sessions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('workstation_id', UUID(as_uuid=True), sa.ForeignKey('workstations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('organization_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('mode', sa.String(20), nullable=False, server_default='screenshot'),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending_consent'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_activity_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('monitor_index', sa.Integer, nullable=False, server_default='0'),
        sa.Column('resolution', sa.String(10), nullable=False, server_default='auto'),
        sa.Column('end_reason', sa.String(30), nullable=True),
        sa.Column('consent_given', sa.Boolean, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
    )

    # Índice parcial: sesiones activas o pendientes por workstation
    op.execute(
        "CREATE INDEX ix_rv_sessions_ws_status "
        "ON remote_view_sessions(workstation_id, status) "
        "WHERE status IN ('pending_consent', 'active')"
    )

    # Índice parcial: sesiones activas por usuario
    op.execute(
        "CREATE INDEX ix_rv_sessions_user_status "
        "ON remote_view_sessions(user_id, status) "
        "WHERE status = 'active'"
    )

    # Índice estándar por organización (tenant isolation)
    op.create_index('ix_rv_sessions_org', 'remote_view_sessions', ['organization_id'])


def downgrade() -> None:
    """Eliminar tabla remote_view_sessions y sus índices."""
    op.drop_index('ix_rv_sessions_org', table_name='remote_view_sessions')
    op.drop_index('ix_rv_sessions_user_status', table_name='remote_view_sessions')
    op.drop_index('ix_rv_sessions_ws_status', table_name='remote_view_sessions')
    op.drop_table('remote_view_sessions')
