"""add_full_name_to_users

Revision ID: d4a203945821
Revises: 001
Create Date: 2026-05-09 08:32:12.970351

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4a203945821'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing = [col['name'] for col in inspector.get_columns('users')]

    if 'full_name' not in existing:
        op.add_column('users', sa.Column('full_name', sa.String(length=255), nullable=True))
        op.execute("UPDATE users SET full_name = email WHERE full_name IS NULL")

    # batch_alter_table es compatible con SQLite (que no soporta ALTER COLUMN directo)
    with op.batch_alter_table('users') as batch_op:
        batch_op.alter_column('full_name', nullable=False)


def downgrade() -> None:
    # Eliminar columna full_name de la tabla users
    op.drop_column('users', 'full_name')
