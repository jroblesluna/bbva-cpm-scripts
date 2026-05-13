"""add_telemetry_and_connectivity_tables

Revision ID: 007_add_telemetry_connectivity
Revises: 006_add_phase3_config
Create Date: 2026-06-15

Crea las tablas telemetry_logs y connectivity_results para almacenar
datos históricos de telemetría y resultados de checks de conectividad
enviados por las workstations vía WebSocket.

Incluye índices compuestos para consultas eficientes por rango temporal
e índices simples en account_id para tenant isolation.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# Identificadores de revisión utilizados por Alembic
revision: str = '007_add_telemetry_connectivity'
down_revision: Union[str, None] = '006_add_phase3_config'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === TABLA telemetry_logs ===
    # Almacena snapshots periódicos de telemetría de cada workstation
    op.create_table(
        'telemetry_logs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('workstation_id', UUID(as_uuid=True), sa.ForeignKey('workstations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('account_id', UUID(as_uuid=True), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('queue_status', sa.String(20), nullable=True),
        sa.Column('contingency_active', sa.Boolean(), nullable=True),
        sa.Column('jobs_identified', sa.Integer(), nullable=True),
        sa.Column('avg_release_time_ms', sa.BigInteger(), nullable=True),
        sa.Column('disconnection_count', sa.Integer(), nullable=True),
        sa.Column('recorded_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
    )

    # === TABLA connectivity_results ===
    # Almacena resultados individuales de checks de conectividad
    op.create_table(
        'connectivity_results',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('workstation_id', UUID(as_uuid=True), sa.ForeignKey('workstations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('account_id', UUID(as_uuid=True), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('check_id', sa.String(100), nullable=False),
        sa.Column('check_type', sa.String(20), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('latency_ms', sa.BigInteger(), nullable=True),
        sa.Column('error', sa.String(500), nullable=True),
        sa.Column('recorded_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
    )

    # === ÍNDICES COMPUESTOS ===
    # Índice para consultas de telemetría por workstation y rango temporal
    op.create_index(
        'ix_telemetry_logs_ws_recorded',
        'telemetry_logs',
        ['workstation_id', 'recorded_at']
    )

    # Índice para consultas de conectividad por workstation, check y rango temporal
    op.create_index(
        'ix_connectivity_results_ws_check_recorded',
        'connectivity_results',
        ['workstation_id', 'check_id', 'recorded_at']
    )

    # === ÍNDICES SIMPLES en account_id para tenant isolation ===
    op.create_index(
        'ix_telemetry_logs_account',
        'telemetry_logs',
        ['account_id']
    )
    op.create_index(
        'ix_connectivity_results_account',
        'connectivity_results',
        ['account_id']
    )


def downgrade() -> None:
    # === ELIMINAR ÍNDICES ===
    op.drop_index('ix_connectivity_results_account', table_name='connectivity_results')
    op.drop_index('ix_connectivity_results_ws_check_recorded', table_name='connectivity_results')
    op.drop_index('ix_telemetry_logs_account', table_name='telemetry_logs')
    op.drop_index('ix_telemetry_logs_ws_recorded', table_name='telemetry_logs')

    # === ELIMINAR TABLAS ===
    op.drop_table('connectivity_results')
    op.drop_table('telemetry_logs')
