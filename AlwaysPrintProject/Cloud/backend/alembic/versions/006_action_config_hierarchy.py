"""Agregar herencia jerárquica a action_configs (Org → VLAN → Workstation)

Revision ID: 006_action_config_hierarchy
Revises: 005_add_openai_key_orgs
Create Date: 2026-05-25 18:00:00.000000

Agrega campos para soportar action configs a nivel de VLAN y workstation,
con lógica de mandatory/default para controlar la herencia.

Cambios:
- action_configs: agregar vlan_id, workstation_id, scope
- organizations: agregar action_config_mandatory (bool)
- vlans: agregar action_config_mandatory (bool)
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '006_action_config_hierarchy'
down_revision: Union[str, None] = '005_add_openai_key_orgs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Agregar soporte de herencia jerárquica para action configs."""

    # 1. Agregar scope a action_configs (org, vlan, workstation)
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE actionconfigscope AS ENUM ('org', 'vlan', 'workstation'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$;"
    )

    scope_enum = sa.Enum('org', 'vlan', 'workstation', name='actionconfigscope', create_type=False)

    op.add_column('action_configs', sa.Column(
        'scope', scope_enum, nullable=False, server_default='org',
        comment="Nivel de la configuración: org, vlan o workstation"
    ))

    # 2. Agregar vlan_id nullable a action_configs (tipo UUID para coincidir con vlans.id)
    op.add_column('action_configs', sa.Column(
        'vlan_id', postgresql.UUID(as_uuid=True), nullable=True,
        comment="VLAN a la que aplica (solo si scope=vlan)"
    ))
    op.create_foreign_key(
        'fk_action_configs_vlan_id',
        'action_configs', 'vlans',
        ['vlan_id'], ['id'],
        ondelete='CASCADE'
    )

    # 3. Agregar workstation_id nullable a action_configs (tipo UUID)
    op.add_column('action_configs', sa.Column(
        'workstation_id', postgresql.UUID(as_uuid=True), nullable=True,
        comment="Workstation a la que aplica (solo si scope=workstation)"
    ))
    op.create_foreign_key(
        'fk_action_configs_workstation_id',
        'action_configs', 'workstations',
        ['workstation_id'], ['id'],
        ondelete='CASCADE'
    )

    # 4. Agregar action_config_mandatory a organizations
    op.add_column('organizations', sa.Column(
        'action_config_mandatory', sa.Boolean(),
        nullable=False, server_default='false',
        comment="Si es True, la config de org es obligatoria para todas las VLANs/workstations"
    ))

    # 5. Agregar action_config_mandatory a vlans
    op.add_column('vlans', sa.Column(
        'action_config_mandatory', sa.Boolean(),
        nullable=False, server_default='false',
        comment="Si es True, la config de VLAN es obligatoria para todas sus workstations"
    ))

    # 6. Índices para búsqueda eficiente
    op.create_index(
        'ix_action_configs_vlan_active',
        'action_configs', ['vlan_id', 'is_active'],
        unique=False
    )
    op.create_index(
        'ix_action_configs_ws_active',
        'action_configs', ['workstation_id', 'is_active'],
        unique=False
    )


def downgrade() -> None:
    """Revertir herencia jerárquica de action configs."""

    # Eliminar índices
    op.drop_index('ix_action_configs_ws_active', table_name='action_configs')
    op.drop_index('ix_action_configs_vlan_active', table_name='action_configs')

    # Eliminar columnas de vlans y organizations
    op.drop_column('vlans', 'action_config_mandatory')
    op.drop_column('organizations', 'action_config_mandatory')

    # Eliminar FKs y columnas de action_configs
    op.drop_constraint('fk_action_configs_workstation_id', 'action_configs', type_='foreignkey')
    op.drop_column('action_configs', 'workstation_id')
    op.drop_constraint('fk_action_configs_vlan_id', 'action_configs', type_='foreignkey')
    op.drop_column('action_configs', 'vlan_id')
    op.drop_column('action_configs', 'scope')

    # Eliminar enum
    sa.Enum(name='actionconfigscope').drop(op.get_bind(), checkfirst=True)
