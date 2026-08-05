"""Crear tablas para artículos de conocimiento y asociación con perfiles

Revision ID: 032_create_knowledge_articles
Revises: 031_add_rv_audit_actions
Create Date: 2026-07-01 00:00:00.000000

Crea las tablas knowledge_articles y profile_knowledge_articles para la
biblioteca de artículos de conocimiento técnico que se inyectan como contexto
adicional en el prompt del LLM durante el análisis de debugging.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '032_create_knowledge_articles'
down_revision: Union[str, None] = '031_add_rv_audit_actions'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Crear tablas knowledge_articles y profile_knowledge_articles."""

    # Tabla knowledge_articles
    op.create_table(
        'knowledge_articles',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('description', sa.String(500), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        'ix_knowledge_articles_org',
        'knowledge_articles',
        ['organization_id']
    )

    # Tabla de asociación many-to-many: perfil ↔ artículo
    op.create_table(
        'profile_knowledge_articles',
        sa.Column('profile_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('debugging_profiles.id', ondelete='CASCADE'),
                  primary_key=True),
        sa.Column('article_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('knowledge_articles.id', ondelete='CASCADE'),
                  primary_key=True),
    )


def downgrade() -> None:
    """Eliminar tablas de artículos de conocimiento."""
    op.drop_table('profile_knowledge_articles')
    op.drop_table('knowledge_articles')
