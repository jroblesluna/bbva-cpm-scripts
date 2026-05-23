"""Crear tabla log_analyses para almacenar análisis de logs de workstations

Revision ID: 003_create_log_analyses
Revises: 002_add_default_device_vlans
Create Date: 2026-07-01 10:00:00.000000

Crea la tabla log_analyses que almacena los resultados de análisis LLM
de logs de workstations. Incluye metadata del procesamiento (ruta, tamaño,
duración) y relaciones con workstations y organizations.
Índices compuestos para búsqueda por workstation+fecha y por organización.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '003_create_log_analyses'
down_revision: Union[str, None] = '002_add_default_device_vlans'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Crear tabla log_analyses con índices y trigger de updated_at."""
    op.create_table(
        'log_analyses',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('workstation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('analysis_date', sa.Date(), nullable=False),
        sa.Column('analysis_text', sa.Text(), nullable=False),
        sa.Column('processing_path', sa.String(length=20), nullable=False, comment="Ruta de procesamiento: 'direct' o 'structural'"),
        sa.Column('log_size_bytes', sa.Integer(), nullable=False, comment='Tamaño del log en bytes'),
        sa.Column('processing_duration_ms', sa.Integer(), nullable=False, comment='Duración del procesamiento en milisegundos'),
        sa.Column('original_filename', sa.String(length=255), nullable=False, comment='Nombre original del archivo de log'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['workstation_id'], ['workstations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    # Índice compuesto para búsqueda por workstation y fecha (unicidad diaria)
    op.create_index(
        'ix_log_analyses_workstation_date',
        'log_analyses',
        ['workstation_id', 'analysis_date'],
    )

    # Índice para filtrado por organización (tenant isolation)
    op.create_index(
        'ix_log_analyses_organization',
        'log_analyses',
        ['organization_id'],
    )

    # Trigger para actualizar updated_at automáticamente (solo PostgreSQL)
    connection = op.get_bind()
    if connection.dialect.name == 'postgresql':
        op.execute("""
            CREATE TRIGGER update_log_analyses_updated_at
            BEFORE UPDATE ON log_analyses
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
        """)


def downgrade() -> None:
    """Eliminar tabla log_analyses y su trigger."""
    connection = op.get_bind()
    if connection.dialect.name == 'postgresql':
        op.execute("DROP TRIGGER IF EXISTS update_log_analyses_updated_at ON log_analyses;")

    op.drop_index('ix_log_analyses_organization', table_name='log_analyses')
    op.drop_index('ix_log_analyses_workstation_date', table_name='log_analyses')
    op.drop_table('log_analyses')
