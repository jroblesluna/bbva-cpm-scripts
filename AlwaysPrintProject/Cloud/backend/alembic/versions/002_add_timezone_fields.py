"""add timezone fields to accounts and users

Revision ID: 002_add_timezone
Revises: 001_initial_migration
Create Date: 2026-05-09 23:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002_add_timezone'
down_revision = 'd4a203945821'  # Última migración (add_full_name_to_users)
branch_labels = None
depends_on = None


def upgrade():
    # Agregar campo timezone a accounts
    op.add_column('accounts', sa.Column('timezone', sa.String(length=50), nullable=False, server_default='UTC'))
    
    # Agregar campo timezone a users (nullable porque hereda del cliente)
    op.add_column('users', sa.Column('timezone', sa.String(length=50), nullable=True))


def downgrade():
    # Eliminar campos en orden inverso
    op.drop_column('users', 'timezone')
    op.drop_column('accounts', 'timezone')
