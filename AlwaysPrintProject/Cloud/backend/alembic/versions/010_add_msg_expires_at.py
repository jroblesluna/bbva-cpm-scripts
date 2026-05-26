"""Agregar campo expires_at a mensajes y status expired a deliveries

Revision ID: 010_add_msg_expires_at
Revises: 009_add_pending_ip_metadata
Create Date: 2026-05-26 12:00:00.000000

Agrega TTL a mensajes (expires_at) para descartar deliveries pendientes
que superen el tiempo máximo de entrega. También agrega el valor 'expired'
al enum deliverystatus.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '010_add_msg_expires_at'
down_revision: Union[str, None] = '009_add_pending_ip_metadata'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Agregar expires_at a messages y valor 'expired' al enum deliverystatus."""
    # Agregar columna expires_at a messages (nullable, sin default en BD)
    op.add_column('messages', sa.Column('expires_at', sa.DateTime(), nullable=True))
    
    # Crear índice para consultas de expiración
    op.create_index('ix_messages_expires_at', 'messages', ['expires_at'])
    
    # Agregar valor 'expired' al enum deliverystatus
    # PostgreSQL permite ALTER TYPE ... ADD VALUE de forma segura
    op.execute("ALTER TYPE deliverystatus ADD VALUE IF NOT EXISTS 'expired'")


def downgrade() -> None:
    """Revertir: eliminar columna expires_at e índice."""
    op.drop_index('ix_messages_expires_at', table_name='messages')
    op.drop_column('messages', 'expires_at')
    # Nota: PostgreSQL no permite eliminar valores de un enum existente.
    # El valor 'expired' quedará en el tipo pero no se usará.
