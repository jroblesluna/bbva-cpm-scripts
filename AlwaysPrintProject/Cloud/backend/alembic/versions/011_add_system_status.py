"""Crear tablas de monitoreo de estado del sistema

Revision ID: 011_add_system_status
Revises: 010_add_msg_expires_at
Create Date: 2026-06-23 10:00:00.000000

Crea las 4 tablas para el sistema de monitoreo de infraestructura:
- status_snapshots: Registro completo de cada ejecución de recolección
- metric_records: Métricas individuales asociadas a un snapshot
- health_check_results: Resultados de verificación de servicios
- container_metrics: Métricas de contenedores Docker

También crea el tipo enum 'overallstatus' para el estado general del sistema.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '011_add_system_status'
down_revision: Union[str, None] = '010_add_msg_expires_at'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Crear tablas de monitoreo de estado del sistema con índices y foreign keys."""

    # === ENUM: overallstatus ===
    # Creación idempotente del tipo enum para PostgreSQL
    connection = op.get_bind()
    if connection.dialect.name == 'postgresql':
        op.execute(
            "DO $$ BEGIN "
            "CREATE TYPE overallstatus AS ENUM ('healthy', 'degraded', 'critical'); "
            "EXCEPTION WHEN duplicate_object THEN NULL; "
            "END $$;"
        )

    # Usar String(20) para la columna — el tipo enum ya fue creado manualmente arriba.
    # No usar sa.Enum() en create_table porque SQLAlchemy intenta CREATE TYPE
    # incluso con create_type=False cuando se asocia a una tabla nueva.
    overall_status_type = sa.String(20)

    # === TABLA: status_snapshots ===
    op.create_table(
        'status_snapshots',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False,
                  comment='Momento de la recolección (UTC)'),
        sa.Column('overall_status', overall_status_type, nullable=False,
                  comment='Estado general: healthy, degraded, critical'),
        # Métricas de memoria
        sa.Column('memory_percent', sa.Float(), nullable=False,
                  comment='Porcentaje de memoria usada'),
        sa.Column('memory_total_mb', sa.Float(), nullable=False,
                  comment='RAM total en MB'),
        sa.Column('memory_used_mb', sa.Float(), nullable=False,
                  comment='RAM usada en MB'),
        sa.Column('memory_available_mb', sa.Float(), nullable=False,
                  comment='RAM disponible en MB'),
        # Métricas de disco
        sa.Column('disk_percent', sa.Float(), nullable=False,
                  comment='Porcentaje de disco usado'),
        sa.Column('disk_total_mb', sa.Float(), nullable=False,
                  comment='Disco total en MB'),
        sa.Column('disk_used_mb', sa.Float(), nullable=False,
                  comment='Disco usado en MB'),
        sa.Column('disk_available_mb', sa.Float(), nullable=False,
                  comment='Disco disponible en MB'),
        # Métricas de CPU
        sa.Column('cpu_percent', sa.Float(), nullable=False,
                  comment='Porcentaje de CPU promedio'),
        # Métricas de swap
        sa.Column('swap_used_mb', sa.Float(), nullable=False,
                  comment='Swap usado en MB'),
        sa.Column('swap_total_mb', sa.Float(), nullable=False,
                  comment='Swap total en MB'),
        sa.Column('swap_available_mb', sa.Float(), nullable=False,
                  comment='Swap disponible en MB'),
        # Sistema
        sa.Column('uptime_seconds', sa.Integer(), nullable=False,
                  comment='Uptime del SO en segundos'),
        sa.Column('docker_available', sa.Boolean(), nullable=False,
                  comment='Si Docker respondió correctamente'),
        # Auditoría
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP'),
                  comment='Timestamp de inserción en BD'),
        sa.PrimaryKeyConstraint('id')
    )
    # Índices para queries de rango temporal y filtrado por estado
    op.create_index('ix_status_snapshots_timestamp', 'status_snapshots', ['timestamp'])
    op.create_index('ix_status_snapshots_overall_status', 'status_snapshots', ['overall_status'])

    # === TABLA: metric_records ===
    op.create_table(
        'metric_records',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('snapshot_id', postgresql.UUID(as_uuid=True), nullable=False,
                  comment='Snapshot padre'),
        sa.Column('metric_name', sa.String(length=100), nullable=False,
                  comment='Nombre de la métrica (cpu_percent, memory_percent, etc.)'),
        sa.Column('value', sa.Float(), nullable=False,
                  comment='Valor numérico de la métrica'),
        sa.Column('unit', sa.String(length=20), nullable=False,
                  comment='Unidad de medida (percent, mb, seconds, bytes)'),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False,
                  comment='Momento de recolección (UTC)'),
        sa.ForeignKeyConstraint(['snapshot_id'], ['status_snapshots.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    # Índices para queries por snapshot y series temporales por métrica
    op.create_index('ix_metric_records_snapshot_id', 'metric_records', ['snapshot_id'])
    op.create_index('ix_metric_records_name_timestamp', 'metric_records', ['metric_name', 'timestamp'])

    # === TABLA: health_check_results ===
    op.create_table(
        'health_check_results',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('snapshot_id', postgresql.UUID(as_uuid=True), nullable=False,
                  comment='Snapshot padre'),
        sa.Column('service_name', sa.String(length=100), nullable=False,
                  comment='Nombre del servicio verificado'),
        sa.Column('is_available', sa.Boolean(), nullable=False,
                  comment='Si el servicio está disponible'),
        sa.Column('latency_ms', sa.Float(), nullable=True,
                  comment='Latencia de respuesta en milisegundos'),
        sa.Column('error_message', sa.Text(), nullable=True,
                  comment='Mensaje de error si el servicio no está disponible'),
        sa.Column('details_json', sa.Text(), nullable=True,
                  comment='JSON con detalles extra (días SSL restantes, etc.)'),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False,
                  comment='Momento de verificación (UTC)'),
        sa.ForeignKeyConstraint(['snapshot_id'], ['status_snapshots.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    # Índices para queries por snapshot y uptime por servicio
    op.create_index('ix_health_checks_snapshot_id', 'health_check_results', ['snapshot_id'])
    op.create_index('ix_health_checks_service_timestamp', 'health_check_results',
                    ['service_name', 'timestamp'])

    # === TABLA: container_metrics ===
    op.create_table(
        'container_metrics',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('snapshot_id', postgresql.UUID(as_uuid=True), nullable=False,
                  comment='Snapshot padre'),
        sa.Column('container_name', sa.String(length=100), nullable=False,
                  comment='Nombre del contenedor Docker'),
        sa.Column('status', sa.String(length=20), nullable=False,
                  comment='Estado: running, stopped, restarting'),
        sa.Column('cpu_percent', sa.Float(), nullable=False,
                  comment='Porcentaje de CPU del contenedor'),
        sa.Column('memory_used_mb', sa.Float(), nullable=False,
                  comment='Memoria usada en MB'),
        sa.Column('memory_limit_mb', sa.Float(), nullable=False,
                  comment='Límite de memoria en MB'),
        sa.Column('network_rx_bytes', sa.BigInteger(), nullable=False,
                  comment='Bytes recibidos por red'),
        sa.Column('network_tx_bytes', sa.BigInteger(), nullable=False,
                  comment='Bytes enviados por red'),
        sa.Column('uptime_seconds', sa.Integer(), nullable=False,
                  comment='Tiempo activo del contenedor en segundos'),
        sa.ForeignKeyConstraint(['snapshot_id'], ['status_snapshots.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    # Índice para queries por snapshot
    op.create_index('ix_container_metrics_snapshot_id', 'container_metrics', ['snapshot_id'])


def downgrade() -> None:
    """Eliminar tablas de monitoreo de estado del sistema y tipo enum."""

    # Eliminar tablas hijas primero (por foreign keys)
    op.drop_table('container_metrics')
    op.drop_table('health_check_results')
    op.drop_table('metric_records')
    op.drop_table('status_snapshots')

    # Eliminar tipo enum (solo PostgreSQL)
    connection = op.get_bind()
    if connection.dialect.name == 'postgresql':
        op.execute("DROP TYPE IF EXISTS overallstatus;")
