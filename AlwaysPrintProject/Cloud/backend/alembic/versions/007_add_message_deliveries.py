"""Agregar tabla message_deliveries y campo delivery_mode a messages

Revision ID: 007_msg_deliveries
Revises: 006_contingency_ip
Create Date: 2026-05-20 14:00:00.000000

Esta migración es 100% idempotente (safe to re-run):
- Crea enums si no existen
- Agrega columnas si no existen
- Crea tabla si no existe
- Convierte columnas a enum si aún son varchar
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '007_msg_deliveries'
down_revision: Union[str, None] = '006_contingency_ip'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Agregar delivery_mode a messages y crear tabla message_deliveries (idempotente)."""
    
    # 1. Crear enums (idempotente)
    op.execute("DO $$ BEGIN CREATE TYPE targettype AS ENUM ('workstation', 'vlan', 'account'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE deliverymode AS ENUM ('all', 'only_connected'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE deliverystatus AS ENUM ('pending', 'sent', 'skipped'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;")

    # 2. Agregar columna target_type a messages si no existe (pudo ser eliminada por CASCADE)
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE messages ADD COLUMN target_type targettype NOT NULL DEFAULT 'workstation';
        EXCEPTION WHEN duplicate_column THEN NULL;
        END $$;
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_messages_target_type ON messages (target_type)")

    # 3. Agregar columna delivery_mode a messages si no existe
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE messages ADD COLUMN delivery_mode deliverymode NOT NULL DEFAULT 'all';
        EXCEPTION WHEN duplicate_column THEN NULL;
        END $$;
    """)

    # 4. Crear tabla message_deliveries si no existe
    op.execute("""
        CREATE TABLE IF NOT EXISTS message_deliveries (
            id UUID PRIMARY KEY,
            message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
            workstation_id UUID NOT NULL REFERENCES workstations(id) ON DELETE CASCADE,
            status deliverystatus NOT NULL DEFAULT 'pending',
            delivered_at TIMESTAMP
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_message_deliveries_message_id ON message_deliveries (message_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_message_deliveries_workstation_id ON message_deliveries (workstation_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_message_deliveries_status ON message_deliveries (status)")

    # 5. Si delivery_mode es varchar (de un intento anterior), convertir a enum
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'messages' AND column_name = 'delivery_mode' 
                AND data_type = 'character varying'
            ) THEN
                ALTER TABLE messages ALTER COLUMN delivery_mode DROP DEFAULT;
                ALTER TABLE messages ALTER COLUMN delivery_mode TYPE deliverymode USING delivery_mode::deliverymode;
                ALTER TABLE messages ALTER COLUMN delivery_mode SET DEFAULT 'all';
            END IF;
        END $$;
    """)

    # 6. Si status es varchar (de un intento anterior), convertir a enum
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'message_deliveries' AND column_name = 'status' 
                AND data_type = 'character varying'
            ) THEN
                ALTER TABLE message_deliveries ALTER COLUMN status DROP DEFAULT;
                ALTER TABLE message_deliveries ALTER COLUMN status TYPE deliverystatus USING status::deliverystatus;
                ALTER TABLE message_deliveries ALTER COLUMN status SET DEFAULT 'pending';
            END IF;
        END $$;
    """)


def downgrade() -> None:
    """Revertir: eliminar tabla message_deliveries y columnas agregadas."""
    op.execute("DROP TABLE IF EXISTS message_deliveries CASCADE")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS delivery_mode")
    op.execute("DROP TYPE IF EXISTS deliverystatus CASCADE")
    op.execute("DROP TYPE IF EXISTS deliverymode CASCADE")
