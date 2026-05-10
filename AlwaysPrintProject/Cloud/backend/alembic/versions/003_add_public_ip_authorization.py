"""add public ip authorization fields

Revision ID: 003_add_public_ip_auth
Revises: 002_add_timezone
Create Date: 2026-05-10 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime


# revision identifiers, used by Alembic.
revision = '003_add_public_ip_auth'
down_revision = '002_add_timezone'
branch_labels = None
depends_on = None


def upgrade():
    """
    Agregar campos de autorización a public_ips.
    
    Permite que IPs se registren automáticamente como "pendientes"
    y luego sean autorizadas por un administrador.
    """
    # Agregar columnas nuevas
    op.add_column('public_ips', sa.Column('is_authorized', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('public_ips', sa.Column('first_seen', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')))
    op.add_column('public_ips', sa.Column('authorized_at', sa.DateTime(), nullable=True))
    
    # Crear índice en is_authorized para queries rápidas
    op.create_index('ix_public_ips_is_authorized', 'public_ips', ['is_authorized'])
    
    # Hacer account_id nullable (permitir IPs pendientes sin cuenta asignada)
    # Nota: En SQLite esto requiere recrear la tabla
    with op.batch_alter_table('public_ips') as batch_op:
        batch_op.alter_column('account_id', nullable=True)
    
    # Actualizar IPs existentes como autorizadas
    op.execute("""
        UPDATE public_ips 
        SET is_authorized = true, 
            authorized_at = created_at,
            first_seen = created_at
        WHERE account_id IS NOT NULL
    """)


def downgrade():
    """Revertir cambios."""
    # Eliminar índice
    op.drop_index('ix_public_ips_is_authorized', 'public_ips')
    
    # Eliminar columnas
    op.drop_column('public_ips', 'authorized_at')
    op.drop_column('public_ips', 'first_seen')
    op.drop_column('public_ips', 'is_authorized')
    
    # Revertir account_id a NOT NULL
    # Nota: Esto fallará si hay IPs pendientes sin cuenta
    with op.batch_alter_table('public_ips') as batch_op:
        batch_op.alter_column('account_id', nullable=False)
