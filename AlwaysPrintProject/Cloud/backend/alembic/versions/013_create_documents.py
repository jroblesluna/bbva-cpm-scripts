"""Crear tabla de documentos del sistema

Revision ID: 013_create_documents
Revises: 012_vlan_contingency_inh
Create Date: 2026-06-01 12:00:00.000000

Crea la tabla 'documents' para almacenar metadatos de documentos PDF
subidos por administradores. Los archivos se guardan en S3.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '013_create_documents'
down_revision: Union[str, None] = '012_vlan_contingency_inh'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Crear tabla documents."""
    op.create_table(
        'documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('title', sa.String(500), nullable=False, comment="Título del documento"),
        sa.Column('description', sa.Text(), nullable=True, comment="Descripción del documento"),
        sa.Column('file_name', sa.String(500), nullable=False, comment="Nombre original del archivo PDF"),
        sa.Column('s3_key', sa.String(1000), nullable=False, comment="Clave del objeto en S3"),
        sa.Column('file_size', sa.Integer(), nullable=False, server_default='0', comment="Tamaño del archivo en bytes"),
        sa.Column('created_by_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # Índice para ordenar por fecha de creación
    op.create_index('ix_documents_created_at', 'documents', ['created_at'])


def downgrade() -> None:
    """Eliminar tabla documents."""
    op.drop_index('ix_documents_created_at', table_name='documents')
    op.drop_table('documents')
