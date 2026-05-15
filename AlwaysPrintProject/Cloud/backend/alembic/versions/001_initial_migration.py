"""Migración inicial: crear todas las tablas del sistema

Revision ID: 001
Revises: 
Create Date: 2025-01-15 10:00:00.000000

Esta migración crea todas las tablas del sistema AlwaysPrint Cloud Management:
- Tablas de usuarios y cuentas
- Tablas de estaciones y licencias
- Tablas de VLANs y configuración jerárquica
- Tablas de auditoría y mensajes
- Índices para optimización de consultas
- Triggers para updated_at automático
- Funciones auxiliares (calculate_license_serial, detect_vlan_for_ip)
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Crear todas las tablas del sistema."""
    
    # === TABLA: accounts ===
    op.create_table(
        'accounts',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.String(length=1000), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index(op.f('ix_accounts_name'), 'accounts', ['name'], unique=True)
    
    # === TABLA: users ===
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('role', sa.Enum('ADMIN', 'OPERATOR', 'READONLY', name='userrole'), nullable=False, server_default='READONLY'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    
    # === TABLA: public_ips ===
    op.create_table(
        'public_ips',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('ip_address', sa.String(length=45), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ip_address')
    )
    op.create_index(op.f('ix_public_ips_ip_address'), 'public_ips', ['ip_address'], unique=True)
    
    # === TABLA: vlans ===
    op.create_table(
        'vlans',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.String(length=1000), nullable=True),
        sa.Column('cidr_ranges', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # === TABLA: workstations ===
    op.create_table(
        'workstations',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('vlan_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('ip_private', sa.String(length=45), nullable=False),
        sa.Column('hostname', sa.String(length=255), nullable=True),
        sa.Column('os_serial', sa.String(length=255), nullable=True),
        sa.Column('current_user', sa.String(length=255), nullable=True),
        sa.Column('is_online', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('contingency_active', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('last_connection', sa.DateTime(), nullable=True),
        sa.Column('first_seen', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['vlan_id'], ['vlans.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ip_private')
    )
    op.create_index(op.f('ix_workstations_ip_private'), 'workstations', ['ip_private'], unique=True)
    op.create_index('ix_workstations_account_id', 'workstations', ['account_id'])
    op.create_index('ix_workstations_vlan_id', 'workstations', ['vlan_id'])
    op.create_index('ix_workstations_is_online', 'workstations', ['is_online'])
    
    # === TABLA: licenses ===
    op.create_table(
        'licenses',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('workstation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('serial_number', sa.String(length=8), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('activated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('deactivated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['workstation_id'], ['workstations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_licenses_serial_number'), 'licenses', ['serial_number'])
    op.create_index('ix_licenses_workstation_id', 'licenses', ['workstation_id'])
    
    # === TABLA: global_configs ===
    op.create_table(
        'global_configs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('corporate_queue_name', sa.String(length=255), nullable=False, server_default='LexmarkRoblesAI'),
        sa.Column('search_targets', sa.JSON(), nullable=True),
        sa.Column('pending_task_polling_minutes', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('bootstrap_domains', sa.String(length=1000), nullable=False, server_default='apps.iol.pe,iol.pe,sistemas.com.pe,robles.ai'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_id')
    )
    
    # === TABLA: vlan_configs ===
    op.create_table(
        'vlan_configs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('vlan_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('corporate_queue_name', sa.String(length=255), nullable=True),
        sa.Column('search_targets', sa.JSON(), nullable=True),
        sa.Column('pending_task_polling_minutes', sa.Integer(), nullable=True),
        sa.Column('bootstrap_domains', sa.String(length=1000), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['vlan_id'], ['vlans.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('vlan_id')
    )
    
    # === TABLA: workstation_configs ===
    op.create_table(
        'workstation_configs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('workstation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('corporate_queue_name', sa.String(length=255), nullable=True),
        sa.Column('search_targets', sa.JSON(), nullable=True),
        sa.Column('pending_task_polling_minutes', sa.Integer(), nullable=True),
        sa.Column('bootstrap_domains', sa.String(length=1000), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['workstation_id'], ['workstations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workstation_id')
    )
    
    # === TABLA: audit_logs ===
    op.create_table(
        'audit_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('workstation_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('action_type', sa.Enum('CREATE', 'UPDATE', 'DELETE', 'CONFIG_CHANGE', 'CONTINGENCY_TOGGLE', 'MESSAGE_SENT', 'COMMAND_SENT', name='actiontype'), nullable=False),
        sa.Column('entity_type', sa.String(length=100), nullable=False),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('old_values', sa.JSON(), nullable=True),
        sa.Column('new_values', sa.JSON(), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['workstation_id'], ['workstations.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_logs_action_type'), 'audit_logs', ['action_type'])
    op.create_index(op.f('ix_audit_logs_entity_type'), 'audit_logs', ['entity_type'])
    op.create_index(op.f('ix_audit_logs_entity_id'), 'audit_logs', ['entity_id'])
    op.create_index(op.f('ix_audit_logs_created_at'), 'audit_logs', ['created_at'])
    
    # === TABLA: messages ===
    op.create_table(
        'messages',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('sender_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('target_type', sa.Enum('WORKSTATION', 'VLAN', 'ACCOUNT', name='targettype'), nullable=False),
        sa.Column('target_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('content', sa.String(length=5000), nullable=False),
        sa.Column('is_delivered', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('sent_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('delivered_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['sender_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_messages_target_type'), 'messages', ['target_type'])
    op.create_index(op.f('ix_messages_target_id'), 'messages', ['target_id'])
    op.create_index(op.f('ix_messages_sent_at'), 'messages', ['sent_at'])
    
    # === TRIGGERS PARA updated_at ===
    # Estos triggers actualizan automáticamente el campo updated_at cuando se modifica un registro
    
    # Verificar si estamos usando PostgreSQL para crear triggers
    connection = op.get_bind()
    if connection.dialect.name == 'postgresql':
        # Función para actualizar updated_at
        op.execute("""
            CREATE OR REPLACE FUNCTION update_updated_at_column()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = CURRENT_TIMESTAMP;
                RETURN NEW;
            END;
            $$ language 'plpgsql';
        """)
        
        # Triggers para cada tabla con updated_at
        for table in ['accounts', 'users', 'vlans', 'workstations', 'global_configs', 'vlan_configs', 'workstation_configs']:
            op.execute(f"""
                CREATE TRIGGER update_{table}_updated_at
                BEFORE UPDATE ON {table}
                FOR EACH ROW
                EXECUTE FUNCTION update_updated_at_column();
            """)
    
    # === FUNCIONES AUXILIARES ===
    
    if connection.dialect.name == 'postgresql':
        # Función para calcular el serial de licencia (últimos 8 caracteres del MD5 de ip_private)
        op.execute("""
            CREATE OR REPLACE FUNCTION calculate_license_serial(ip_private TEXT)
            RETURNS VARCHAR(8) AS $$
            BEGIN
                RETURN RIGHT(MD5(ip_private), 8);
            END;
            $$ LANGUAGE plpgsql IMMUTABLE;
        """)
        
        # Función para detectar VLAN por IP privada
        # Esta función busca en todas las VLANs de una cuenta y retorna la VLAN más reciente que contiene la IP
        op.execute("""
            CREATE OR REPLACE FUNCTION detect_vlan_for_ip(p_account_id UUID, p_ip_private TEXT)
            RETURNS UUID AS $$
            DECLARE
                v_vlan_id UUID;
                v_cidr TEXT;
                v_vlan RECORD;
            BEGIN
                -- Buscar VLANs que contengan la IP (ordenadas por created_at DESC para obtener la más reciente)
                FOR v_vlan IN 
                    SELECT id, cidr_ranges 
                    FROM vlans 
                    WHERE account_id = p_account_id 
                    ORDER BY created_at DESC
                LOOP
                    -- Iterar sobre los rangos CIDR de cada VLAN
                    FOR v_cidr IN 
                        SELECT jsonb_array_elements_text(v_vlan.cidr_ranges::jsonb) AS cidr
                    LOOP
                        -- Verificar si la IP está en el rango CIDR
                        IF (p_ip_private::inet << v_cidr::cidr) THEN
                            RETURN v_vlan.id;
                        END IF;
                    END LOOP;
                END LOOP;
                
                -- Si no se encuentra ninguna VLAN, retornar NULL
                RETURN NULL;
            END;
            $$ LANGUAGE plpgsql STABLE;
        """)


def downgrade() -> None:
    """Eliminar todas las tablas del sistema."""
    
    connection = op.get_bind()
    
    # === ELIMINAR FUNCIONES AUXILIARES ===
    if connection.dialect.name == 'postgresql':
        op.execute("DROP FUNCTION IF EXISTS detect_vlan_for_ip(UUID, TEXT);")
        op.execute("DROP FUNCTION IF EXISTS calculate_license_serial(TEXT);")
        op.execute("DROP FUNCTION IF EXISTS update_updated_at_column();")
    
    # === ELIMINAR TABLAS (en orden inverso para respetar foreign keys) ===
    op.drop_table('messages')
    op.drop_table('audit_logs')
    op.drop_table('workstation_configs')
    op.drop_table('vlan_configs')
    op.drop_table('global_configs')
    op.drop_table('licenses')
    op.drop_table('workstations')
    op.drop_table('vlans')
    op.drop_table('public_ips')
    op.drop_table('users')
    op.drop_table('accounts')
    
    # === ELIMINAR ENUMS ===
    if connection.dialect.name == 'postgresql':
        op.execute("DROP TYPE IF EXISTS targettype;")
        op.execute("DROP TYPE IF EXISTS actiontype;")
        op.execute("DROP TYPE IF EXISTS userrole;")
