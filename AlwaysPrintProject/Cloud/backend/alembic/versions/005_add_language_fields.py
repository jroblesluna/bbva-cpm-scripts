"""add_language_fields

Revision ID: 005_add_language
Revises: 004_add_password_reset_token
Create Date: 2026-05-11

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '005_add_language'
down_revision: Union[str, None] = '004_add_password_reset_token'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('language', sa.String(2), nullable=False, server_default='en'))
    op.add_column('accounts', sa.Column('language', sa.String(2), nullable=False, server_default='en'))
    op.add_column('global_configs', sa.Column('language', sa.String(2), nullable=False, server_default='en'))


def downgrade() -> None:
    op.drop_column('users', 'language')
    op.drop_column('accounts', 'language')
    op.drop_column('global_configs', 'language')
