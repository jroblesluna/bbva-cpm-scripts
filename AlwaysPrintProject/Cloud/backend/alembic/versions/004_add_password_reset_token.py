"""add_password_reset_token

Revision ID: 004_add_password_reset_token
Revises: 003_add_public_ip_auth
Create Date: 2026-05-10 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '004_add_password_reset_token'
down_revision = '003_add_public_ip_auth'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('password_reset_token', sa.String(255), nullable=True))
    op.add_column('users', sa.Column('password_reset_expires', sa.DateTime(), nullable=True))
    op.create_index('ix_users_password_reset_token', 'users', ['password_reset_token'])


def downgrade() -> None:
    op.drop_index('ix_users_password_reset_token', table_name='users')
    op.drop_column('users', 'password_reset_expires')
    op.drop_column('users', 'password_reset_token')
