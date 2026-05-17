"""Esquema inicial consolidado — todas las tablas del sistema AlwaysPrint Cloud

Revision ID: 001_initial_schema
Revises: (ninguna — migración base)
Create Date: 2026-06-22 00:00:00.000000

Esta migración crea el esquema completo de la base de datos:
- organizations, public_ips (organizaciones y autorización de IPs)
- users (usuarios con roles y password reset)
- workstations, licenses (estaciones y licencias)
- vlans (segmentos de red)
- global_configs, vlan_configs, workstation_configs (configuración jerárquica)
- messages (mensajería a workstations)
- audit_logs (auditoría de operaciones)
- telemetry_logs, connectivity_results (telemetría y conectividad)
- action_configs (configuración de acciones administrativas)
- Índices, triggers y funciones auxiliares PostgreSQL
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Identificadores de revisión utilizados por Alembic
revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Crear todas las tablas, índices, triggers y funciones del sistema."""

    # === TABLA: organizations ===
    op.create_table(
        'organizations',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.String(length=1000), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('timezone', sa.String(length=50), nullable=False, server_default='UTC'),
        sa.Column('language', sa.String(length=2), nullable=False, server_default='en'),
        sa.Column('auto_update_enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index(op.f('ix_organizations_name'), 'organizations', ['name'], unique=True)

    # === TABLA: users ===
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=False),
        sa.Column('role', sa.Enum('ADMIN', 'OPERATOR', 'READONLY', name='userrole'), nullable=False, server_default='READONLY'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('timezone', sa.String(length=50), nullable=True),
        sa.Column('language', sa.String(length=2), nullable=False, server_default='en'),
        sa.Column('password_reset_token', sa.String(length=255), nullable=True),
        sa.Column('password_reset_expires', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index('ix_users_password_reset_token', 'users', ['password_reset_token'])

    # === TABLA: public_ips ===
    op.create_table(
        'public_ips',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('is_authorized', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('first_seen', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('authorized_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ip_address')
    )
    op.create_index(op.f('ix_public_ips_ip_address'), 'public_ips', ['ip_address'], unique=True)
    op.create_index('ix_public_ips_is_authorized', 'public_ips', ['is_authorized'])

    # === TABLA: vlans ===
    op.create_table(
        'vlans',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.String(length=1000), nullable=True),
        sa.Column('cidr_ranges', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # === TABLA: workstations ===
    op.create_table(
        'workstations',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['vlan_id'], ['vlans.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ip_private')
    )
    op.create_index(op.f('ix_workstations_ip_private'), 'workstations', ['ip_private'], unique=True)
    op.create_index('ix_workstations_organization_id', 'workstations', ['organization_id'])
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
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('corporate_queue_name', sa.String(length=255), nullable=False, server_default='LexmarkRoblesAI'),
        sa.Column('search_targets', sa.JSON(), nullable=True),
        sa.Column('pending_task_polling_minutes', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('bootstrap_domains', sa.String(length=1000), nullable=False, server_default='apps.iol.pe,iol.pe,sistemas.com.pe,robles.ai'),
        sa.Column('language', sa.String(length=2), nullable=False, server_default='en'),
        sa.Column('connectivity_checks', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('locale', sa.String(length=10), nullable=False, server_default=''),
        sa.Column('telemetry_enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('telemetry_interval_seconds', sa.Integer(), nullable=False, server_default='300'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id')
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
        sa.Column('connectivity_checks', sa.JSON(), nullable=True),
        sa.Column('locale', sa.String(length=10), nullable=True),
        sa.Column('telemetry_enabled', sa.Boolean(), nullable=True),
        sa.Column('telemetry_interval_seconds', sa.Integer(), nullable=True),
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
        sa.Column('connectivity_checks', sa.JSON(), nullable=True),
        sa.Column('locale', sa.String(length=10), nullable=True),
        sa.Column('telemetry_enabled', sa.Boolean(), nullable=True),
        sa.Column('telemetry_interval_seconds', sa.Integer(), nullable=True),
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
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('action_type', sa.Enum('CREATE', 'UPDATE', 'DELETE', 'CONFIG_CHANGE', 'CONTINGENCY_TOGGLE', 'MESSAGE_SENT', 'COMMAND_SENT', name='actiontype'), nullable=False),
        sa.Column('entity_type', sa.String(length=100), nullable=False),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('old_values', sa.JSON(), nullable=True),
        sa.Column('new_values', sa.JSON(), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['workstation_id'], ['workstations.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='SET NULL'),
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
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('sender_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('target_type', sa.Enum('WORKSTATION', 'VLAN', 'ACCOUNT', name='targettype'), nullable=False),
        sa.Column('target_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('content', sa.String(length=5000), nullable=False),
        sa.Column('is_delivered', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('sent_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('delivered_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['sender_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_messages_target_type'), 'messages', ['target_type'])
    op.create_index(op.f('ix_messages_target_id'), 'messages', ['target_id'])
    op.create_index(op.f('ix_messages_sent_at'), 'messages', ['sent_at'])

    # === TABLA: telemetry_logs ===
    op.create_table(
        'telemetry_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('workstation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('queue_status', sa.String(length=20), nullable=True),
        sa.Column('contingency_active', sa.Boolean(), nullable=True),
        sa.Column('jobs_identified', sa.Integer(), nullable=True),
        sa.Column('avg_release_time_ms', sa.BigInteger(), nullable=True),
        sa.Column('disconnection_count', sa.Integer(), nullable=True),
        sa.Column('recorded_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['workstation_id'], ['workstations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_telemetry_logs_ws_recorded', 'telemetry_logs', ['workstation_id', 'recorded_at'])
    op.create_index('ix_telemetry_logs_organization', 'telemetry_logs', ['organization_id'])

    # === TABLA: connectivity_results ===
    op.create_table(
        'connectivity_results',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('workstation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('check_id', sa.String(length=100), nullable=False),
        sa.Column('check_type', sa.String(length=20), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('latency_ms', sa.BigInteger(), nullable=True),
        sa.Column('error', sa.String(length=500), nullable=True),
        sa.Column('recorded_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['workstation_id'], ['workstations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_connectivity_results_ws_check_recorded', 'connectivity_results', ['workstation_id', 'check_id', 'recorded_at'])
    op.create_index('ix_connectivity_results_organization', 'connectivity_results', ['organization_id'])

    # === TABLA: action_configs ===
    op.create_table(
        'action_configs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False, comment='Nombre de la configuración'),
        sa.Column('version', sa.String(length=50), nullable=False, comment='Versión de la configuración'),
        sa.Column('description', sa.Text(), nullable=True, comment='Descripción de la configuración'),
        sa.Column('config_json', sa.Text(), nullable=False, comment='JSON completo del archivo .alwaysconfig'),
        sa.Column('config_hash', sa.String(length=8), nullable=False, comment='Hash SHA256 corto (8 chars)'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true', comment='Si está activa para propagación'),
        sa.Column('storage_path', sa.String(length=500), nullable=True, comment='Ruta en S3 o filesystem local'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('created_by_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_action_configs_config_hash', 'action_configs', ['config_hash'])
    op.create_index('ix_action_configs_org_active', 'action_configs', ['organization_id', 'is_active'])
    op.create_index('ix_action_configs_org_hash', 'action_configs', ['organization_id', 'config_hash'])

    # === TRIGGERS PARA updated_at (solo PostgreSQL) ===
    connection = op.get_bind()
    if connection.dialect.name == 'postgresql':
        op.execute("""
            CREATE OR REPLACE FUNCTION update_updated_at_column()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = CURRENT_TIMESTAMP;
                RETURN NEW;
            END;
            $$ language 'plpgsql';
        """)

        for table in ['organizations', 'users', 'vlans', 'workstations',
                      'global_configs', 'vlan_configs', 'workstation_configs']:
            op.execute(f"""
                CREATE TRIGGER update_{table}_updated_at
                BEFORE UPDATE ON {table}
                FOR EACH ROW
                EXECUTE FUNCTION update_updated_at_column();
            """)

    # === FUNCIONES AUXILIARES (solo PostgreSQL) ===
    if connection.dialect.name == 'postgresql':
        op.execute("""
            CREATE OR REPLACE FUNCTION calculate_license_serial(ip_private TEXT)
            RETURNS VARCHAR(8) AS $$
            BEGIN
                RETURN RIGHT(MD5(ip_private), 8);
            END;
            $$ LANGUAGE plpgsql IMMUTABLE;
        """)

        op.execute("""
            CREATE OR REPLACE FUNCTION detect_vlan_for_ip(p_organization_id UUID, p_ip_private TEXT)
            RETURNS UUID AS $$
            DECLARE
                v_vlan_id UUID;
                v_cidr TEXT;
                v_vlan RECORD;
            BEGIN
                FOR v_vlan IN
                    SELECT id, cidr_ranges
                    FROM vlans
                    WHERE organization_id = p_organization_id
                    ORDER BY created_at DESC
                LOOP
                    FOR v_cidr IN
                        SELECT jsonb_array_elements_text(v_vlan.cidr_ranges::jsonb) AS cidr
                    LOOP
                        IF (p_ip_private::inet << v_cidr::cidr) THEN
                            RETURN v_vlan.id;
                        END IF;
                    END LOOP;
                END LOOP;
                RETURN NULL;
            END;
            $$ LANGUAGE plpgsql STABLE;
        """)


def downgrade() -> None:
    """Eliminar todas las tablas, funciones y tipos del sistema."""

    connection = op.get_bind()

    if connection.dialect.name == 'postgresql':
        op.execute("DROP FUNCTION IF EXISTS detect_vlan_for_ip(UUID, TEXT);")
        op.execute("DROP FUNCTION IF EXISTS calculate_license_serial(TEXT);")
        op.execute("DROP FUNCTION IF EXISTS update_updated_at_column() CASCADE;")

    op.drop_table('action_configs')
    op.drop_table('connectivity_results')
    op.drop_table('telemetry_logs')
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
    op.drop_table('organizations')

    if connection.dialect.name == 'postgresql':
        op.execute("DROP TYPE IF EXISTS targettype;")
        op.execute("DROP TYPE IF EXISTS actiontype;")
        op.execute("DROP TYPE IF EXISTS userrole;")
