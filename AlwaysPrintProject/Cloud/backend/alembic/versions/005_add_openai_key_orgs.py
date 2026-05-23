"""Agregar campo openai_api_key a organizations

Revision ID: 005_add_openai_key_orgs
Revises: 004_add_llm_model_orgs
Create Date: 2026-05-23 18:00:00.000000

Permite configurar una API Key de OpenAI por organización como alternativa
a AWS Bedrock para el análisis de logs.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '005_add_openai_key_orgs'
down_revision: Union[str, None] = '004_add_llm_model_orgs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Agregar columna openai_api_key a organizations."""
    op.add_column(
        'organizations',
        sa.Column('openai_api_key', sa.String(length=200), nullable=True)
    )


def downgrade() -> None:
    """Eliminar columna openai_api_key de organizations."""
    op.drop_column('organizations', 'openai_api_key')
