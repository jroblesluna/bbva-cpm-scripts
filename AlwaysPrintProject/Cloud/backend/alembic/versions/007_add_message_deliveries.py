"""Agregar tabla message_deliveries y campo delivery_mode a messages

Revision ID: 007_msg_deliveries
Revises: 006_contingency_ip
Create Date: 2026-05-20 14:00:00.000000

Esta migración:
- Agrega columna delivery_mode a la tabla messages (all / only_connected)
- Crea tabla message_deliveries para tracking individual de entrega por workstation
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '007_msg_deliveries'
down_revision: Union[str, None] = '006_contingency_ip'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Agregar delivery_mode a messages y crear tabla message_deliveries."""
    # Crear enums primero (PostgreSQL requiere que existan antes de usarlos)
    # Usar DO $$ para evitar error si ya existen (checkfirst no siempre funciona en Alembic)
    op.execute("DO $$ BEGIN CREATE TYPE deliverymode AS ENUM ('all', 'only_connected'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE deliverystatus AS ENUM ('pending', 'sent', 'skipped'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;")

    deliverymode_enum = sa.Enum('all', 'only_connected', name='deliverymode', create_type=False)
    deliverystatus_enum = sa.Enum('pending', 'sent', 'skipped', name='deliverystatus', create_type=False)

    # Agregar columna delivery_mode a messages
    op.add_column(
        'messages',
        sa.Column(
            'delivery_mode',
            deliverymode_enum,
            nullable=False,
            server_default='all'
        )
    )

    # Crear tabla message_deliveries
    op.create_table(
        'message_deliveries',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('message_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('workstation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            'status',
            deliverystatus_enum,
            nullable=False,
            server_default='pending'
        ),
        sa.Column('delivered_at', sa.DateTime, nullable=True),
        sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workstation_id'], ['workstations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    # Índices para consultas frecuentes
    op.create_index('ix_message_deliveries_message_id', 'message_deliveries', ['message_id'])
    op.create_index('ix_message_deliveries_workstation_id', 'message_deliveries', ['workstation_id'])
    op.create_index('ix_message_deliveries_status', 'message_deliveries', ['status'])


def downgrade() -> None:
    """Revertir: eliminar tabla message_deliveries y columna delivery_mode."""
    op.drop_index('ix_message_deliveries_status', table_name='message_deliveries')
    op.drop_index('ix_message_deliveries_workstation_id', table_name='message_deliveries')
    op.drop_index('ix_message_deliveries_message_id', table_name='message_deliveries')
    op.drop_table('message_deliveries')

    op.drop_column('messages', 'delivery_mode')

    # Eliminar enums creados
    sa.Enum(name='deliverystatus').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='deliverymode').drop(op.get_bind(), checkfirst=True)
