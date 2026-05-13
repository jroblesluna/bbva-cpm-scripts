"""add_phase3_config_fields

Revision ID: 006_add_phase3_config
Revises: 005_add_language
Create Date: 2026-06-01

Agrega campos de configuración de Fase 3 a las tablas global_configs,
vlan_configs y workstation_configs:
- connectivity_checks: verificaciones de conectividad (JSON)
- locale: override de idioma (VARCHAR(10))
- telemetry_enabled: habilitar telemetría (BOOLEAN)
- telemetry_interval_seconds: intervalo de telemetría (INTEGER)
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '006_add_phase3_config'
down_revision: Union[str, None] = '005_add_language'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # === GLOBAL_CONFIGS: campos no-nullable con defaults ===
    op.add_column('global_configs', sa.Column(
        'connectivity_checks', sa.JSON(), nullable=False, server_default='[]'
    ))
    op.add_column('global_configs', sa.Column(
        'locale', sa.String(10), nullable=False, server_default=''
    ))
    op.add_column('global_configs', sa.Column(
        'telemetry_enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')
    ))
    op.add_column('global_configs', sa.Column(
        'telemetry_interval_seconds', sa.Integer(), nullable=False, server_default='300'
    ))

    # === VLAN_CONFIGS: campos nullable para override selectivo ===
    op.add_column('vlan_configs', sa.Column(
        'connectivity_checks', sa.JSON(), nullable=True
    ))
    op.add_column('vlan_configs', sa.Column(
        'locale', sa.String(10), nullable=True
    ))
    op.add_column('vlan_configs', sa.Column(
        'telemetry_enabled', sa.Boolean(), nullable=True
    ))
    op.add_column('vlan_configs', sa.Column(
        'telemetry_interval_seconds', sa.Integer(), nullable=True
    ))

    # === WORKSTATION_CONFIGS: campos nullable para override selectivo ===
    op.add_column('workstation_configs', sa.Column(
        'connectivity_checks', sa.JSON(), nullable=True
    ))
    op.add_column('workstation_configs', sa.Column(
        'locale', sa.String(10), nullable=True
    ))
    op.add_column('workstation_configs', sa.Column(
        'telemetry_enabled', sa.Boolean(), nullable=True
    ))
    op.add_column('workstation_configs', sa.Column(
        'telemetry_interval_seconds', sa.Integer(), nullable=True
    ))


def downgrade() -> None:
    # === WORKSTATION_CONFIGS ===
    op.drop_column('workstation_configs', 'telemetry_interval_seconds')
    op.drop_column('workstation_configs', 'telemetry_enabled')
    op.drop_column('workstation_configs', 'locale')
    op.drop_column('workstation_configs', 'connectivity_checks')

    # === VLAN_CONFIGS ===
    op.drop_column('vlan_configs', 'telemetry_interval_seconds')
    op.drop_column('vlan_configs', 'telemetry_enabled')
    op.drop_column('vlan_configs', 'locale')
    op.drop_column('vlan_configs', 'connectivity_checks')

    # === GLOBAL_CONFIGS ===
    op.drop_column('global_configs', 'telemetry_interval_seconds')
    op.drop_column('global_configs', 'telemetry_enabled')
    op.drop_column('global_configs', 'locale')
    op.drop_column('global_configs', 'connectivity_checks')
