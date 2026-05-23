"""Agregar campo llm_model_id a organizations

Revision ID: 004_add_llm_model_orgs
Revises: 003_create_log_analyses
Create Date: 2026-05-23 12:00:00.000000

Permite configurar un modelo LLM distinto por organización para el análisis de logs.
Si es NULL, se usa el modelo por defecto global.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '004_add_llm_model_orgs'
down_revision: Union[str, None] = '003_create_log_analyses'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Agregar columna llm_model_id a organizations."""
    op.add_column(
        'organizations',
        sa.Column('llm_model_id', sa.String(length=100), nullable=True)
    )


def downgrade() -> None:
    """Eliminar columna llm_model_id de organizations."""
    op.drop_column('organizations', 'llm_model_id')
