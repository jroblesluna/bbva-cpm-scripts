"""Añadir campo scalability_metrics_json a status_snapshots

Revision ID: 014_add_scalability_json
Revises: 013_create_documents
Create Date: 2026-07-01 10:00:00.000000

Agrega columna Text nullable para almacenar las métricas de escalabilidad
serializadas como JSON dentro de cada snapshot del sistema.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '014_add_scalability_json'
down_revision: Union[str, None] = '013_create_documents'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Añadir columna scalability_metrics_json a status_snapshots."""
    op.add_column(
        'status_snapshots',
        sa.Column(
            'scalability_metrics_json',
            sa.Text(),
            nullable=True,
            comment='JSON serializado de métricas de escalabilidad'
        )
    )


def downgrade() -> None:
    """Eliminar columna scalability_metrics_json de status_snapshots."""
    op.drop_column('status_snapshots', 'scalability_metrics_json')
