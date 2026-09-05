"""Añadir columnas y tablas del módulo Usage and Billing (facturación por IP)

Revision ID: 036_add_usage_and_billing
Revises: 035_add_remote_cmd_audit
Create Date: 2026-08-20 00:00:00.000000

Migración en 3 pasos, segura sobre PROD (6,315+ filas en `workstations`), que:

1. Añade `workstations.last_seen` (DateTime) en 3 pasos:
   - columna nullable → backfill con COALESCE(last_connection, first_seen)
   - server_default CURRENT_TIMESTAMP + NOT NULL.
2. Añade `workstations.billing_status` (String(16)) en 3 pasos:
   - columna nullable → backfill a 'new'
   - server_default 'new' + NOT NULL + CHECK IN ('new','billable','recycled','archived').
3. Añade `organizations.billing_mode` (String(16)) NOT NULL server_default 'monthly'
   + CHECK IN ('monthly','annual').
4. Crea las 5 tablas nuevas del módulo con sus FK, índices y el UniqueConstraint de
   idempotencia `uq_closure_org_period`.

El path SQLite (tests) usa `batch_alter_table` porque SQLite no soporta ALTER de
columnas ni ADD CONSTRAINT sobre tablas existentes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Reutilizar el tipo GUID (UUID en PostgreSQL, String(36) en SQLite) para consistencia
# con los modelos ORM y compatibilidad de tests sobre SQLite.
from app.models.organization import GUID

revision: str = '036_add_usage_and_billing'
down_revision: Union[str, None] = '035_add_remote_cmd_audit'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_sqlite() -> bool:
    """Devuelve True si el dialecto activo es SQLite (path de tests)."""
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    """Aplicar cambios de columnas (3 pasos) y crear las tablas del módulo de facturación."""
    is_sqlite = _is_sqlite()

    # ── 1. workstations.last_seen (3 pasos) ─────────────────────────────────
    # Paso 1: añadir la columna como nullable (no bloquea sobre tablas grandes).
    op.add_column(
        "workstations",
        sa.Column("last_seen", sa.DateTime(), nullable=True),
    )
    # Paso 2: backfill del histórico con la última actividad conocida.
    op.execute(
        "UPDATE workstations SET last_seen = COALESCE(last_connection, first_seen)"
    )
    # Paso 3: fijar default de seguridad (para inserts que omitan el campo) y NOT NULL.
    if is_sqlite:
        with op.batch_alter_table("workstations") as batch_op:
            batch_op.alter_column(
                "last_seen",
                existing_type=sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            )
    else:
        op.alter_column(
            "workstations",
            "last_seen",
            existing_type=sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        )

    # ── 2. workstations.billing_status (3 pasos + CHECK) ────────────────────
    # Paso 1: añadir la columna como nullable.
    op.add_column(
        "workstations",
        sa.Column("billing_status", sa.String(length=16), nullable=True),
    )
    # Paso 2: backfill de todos los registros existentes a 'new' (Req 2.3 / F2:
    # los cierres retroactivos moverán las IPs a billable/recycled mes a mes).
    op.execute("UPDATE workstations SET billing_status = 'new'")
    # Paso 3: default 'new' + NOT NULL + CHECK constraint.
    if is_sqlite:
        with op.batch_alter_table("workstations") as batch_op:
            batch_op.alter_column(
                "billing_status",
                existing_type=sa.String(length=16),
                server_default="new",
                nullable=False,
            )
            batch_op.create_check_constraint(
                "ck_ws_billing_status",
                "billing_status IN ('new','billable','recycled','archived')",
            )
    else:
        op.alter_column(
            "workstations",
            "billing_status",
            existing_type=sa.String(length=16),
            server_default="new",
            nullable=False,
        )
        op.create_check_constraint(
            "ck_ws_billing_status",
            "workstations",
            "billing_status IN ('new','billable','recycled','archived')",
        )

    # ── 3. organizations.billing_mode (NOT NULL + CHECK) ────────────────────
    # Se añade directamente con server_default 'monthly' (valor por defecto seguro,
    # Req 4.6), por lo que puede crearse NOT NULL de una vez.
    op.add_column(
        "organizations",
        sa.Column(
            "billing_mode",
            sa.String(length=16),
            nullable=False,
            server_default="monthly",
        ),
    )
    if is_sqlite:
        with op.batch_alter_table("organizations") as batch_op:
            batch_op.create_check_constraint(
                "ck_org_billing_mode",
                "billing_mode IN ('monthly','annual')",
            )
    else:
        op.create_check_constraint(
            "ck_org_billing_mode",
            "organizations",
            "billing_mode IN ('monthly','annual')",
        )

    # ── 4. Tablas nuevas del módulo de facturación ──────────────────────────

    # billing_rate_plans — tarifas por defecto del sistema (editables por superadmin).
    op.create_table(
        "billing_rate_plans",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("mode", sa.String(length=16), nullable=False),  # 'monthly' | 'annual'
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("tiers", sa.JSON(), nullable=False),  # tramos ordenados por rango
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("effective_from", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # billing_org_plans — plan tarifario individual por organización y modalidad.
    op.create_table(
        "billing_org_plans",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "organization_id",
            GUID(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mode", sa.String(length=16), nullable=False),  # 'monthly' | 'annual'
        sa.Column("tiers", sa.JSON(), nullable=False),  # copia congelable del plan aplicado
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("effective_from", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_billing_org_plans_org",
        "billing_org_plans",
        ["organization_id"],
    )

    # billing_closures — cabecera de cierre mensual (una por org/año/mes).
    op.create_table(
        "billing_closures",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "organization_id",
            GUID(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_year", sa.Integer(), nullable=False),
        sa.Column("period_month", sa.Integer(), nullable=False),  # 1..12
        sa.Column("cutoff_at", sa.DateTime(), nullable=False),  # 00:00 día 1 de M+1 (UTC)
        sa.Column("mode", sa.String(length=16), nullable=False),  # modalidad al cierre
        sa.Column("timezone", sa.String(length=50), nullable=False),  # tz usada
        sa.Column("total_billable", sa.Integer(), nullable=False),
        sa.Column("total_recycled", sa.Integer(), nullable=False),
        sa.Column("total_archived", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("tiers_applied", sa.JSON(), nullable=False),  # desglose por tramo
        sa.Column("is_retroactive", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_by_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        # Idempotencia (Req 7.6): un mes ya cerrado no puede volver a cerrarse.
        sa.UniqueConstraint(
            "organization_id",
            "period_year",
            "period_month",
            name="uq_closure_org_period",
        ),
    )
    op.create_index(
        "ix_billing_closures_org",
        "billing_closures",
        ["organization_id"],
    )

    # billing_closure_items — detalle por IP de un cierre (sustento inmutable).
    op.create_table(
        "billing_closure_items",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "closure_id",
            GUID(),
            sa.ForeignKey("billing_closures.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # nullable: la workstation puede eliminarse físicamente después del cierre.
        sa.Column("workstation_id", GUID(), nullable=True),
        sa.Column("ip_private", sa.String(length=45), nullable=False),
        sa.Column("created_at_ws", sa.DateTime(), nullable=False),  # created_at de la ws
        sa.Column("last_seen_capped", sa.DateTime(), nullable=False),  # last_seen capado a M+1
        sa.Column("billing_status", sa.String(length=16), nullable=False),  # estado en ESE cierre
        sa.Column("tier_index", sa.Integer(), nullable=True),  # tramo aplicado (mensual)
        sa.Column(
            "amount",
            sa.Numeric(precision=12, scale=4),
            nullable=False,
            server_default="0",
        ),  # aporte de esta IP
    )
    op.create_index(
        "ix_billing_closure_items_closure",
        "billing_closure_items",
        ["closure_id"],
    )

    # billing_annual_subscriptions — suscripción anual y su liquidación informativa.
    op.create_table(
        "billing_annual_subscriptions",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "organization_id",
            GUID(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("start_date", sa.DateTime(), nullable=False),  # created_at del primer registro
        sa.Column("end_date", sa.DateTime(), nullable=False),  # 1 día antes del aniversario
        sa.Column("declared_volume", sa.Integer(), nullable=False),  # input manual superadmin
        sa.Column("tier_rate", sa.Numeric(precision=12, scale=4), nullable=False),  # tarifa congelada
        sa.Column("tier_from", sa.Integer(), nullable=False),
        sa.Column("tier_to", sa.Integer(), nullable=True),  # null = último tramo
        sa.Column("tier_cap", sa.Integer(), nullable=True),  # tope contabilizable (ej. 10000)
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("settlement", sa.JSON(), nullable=True),  # {declared, real, diff, credit, charge}
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_billing_annual_subscriptions_org",
        "billing_annual_subscriptions",
        ["organization_id"],
    )

    # ── 5. Seed de planes tarifarios por defecto (Req 8.1) ──────────────────
    # Data migration idempotente: inserta el plan por defecto 'monthly' (T1–T5) y
    # 'annual' (5 tramos con free_growth_to) solo si aún no existe un plan por defecto
    # para esa modalidad. Reutiliza la lógica compartida con el bootstrap
    # scripts/seed_rate_plans.py para tener una única fuente de verdad de las tarifas.
    from app.services.billing_seed import seed_default_rate_plans

    seed_default_rate_plans(op.get_bind())


def downgrade() -> None:
    """Revertir en orden inverso: tablas nuevas primero, luego columnas añadidas."""
    is_sqlite = _is_sqlite()

    # ── Tablas nuevas (en orden inverso de dependencias FK) ─────────────────
    op.drop_index("ix_billing_annual_subscriptions_org", table_name="billing_annual_subscriptions")
    op.drop_table("billing_annual_subscriptions")

    op.drop_index("ix_billing_closure_items_closure", table_name="billing_closure_items")
    op.drop_table("billing_closure_items")

    op.drop_index("ix_billing_closures_org", table_name="billing_closures")
    op.drop_table("billing_closures")

    op.drop_index("ix_billing_org_plans_org", table_name="billing_org_plans")
    op.drop_table("billing_org_plans")

    op.drop_table("billing_rate_plans")

    # ── organizations.billing_mode ──────────────────────────────────────────
    if is_sqlite:
        with op.batch_alter_table("organizations") as batch_op:
            batch_op.drop_constraint("ck_org_billing_mode", type_="check")
            batch_op.drop_column("billing_mode")
    else:
        op.drop_constraint("ck_org_billing_mode", "organizations", type_="check")
        op.drop_column("organizations", "billing_mode")

    # ── workstations.billing_status ─────────────────────────────────────────
    if is_sqlite:
        with op.batch_alter_table("workstations") as batch_op:
            batch_op.drop_constraint("ck_ws_billing_status", type_="check")
            batch_op.drop_column("billing_status")
    else:
        op.drop_constraint("ck_ws_billing_status", "workstations", type_="check")
        op.drop_column("workstations", "billing_status")

    # ── workstations.last_seen ──────────────────────────────────────────────
    if is_sqlite:
        with op.batch_alter_table("workstations") as batch_op:
            batch_op.drop_column("last_seen")
    else:
        op.drop_column("workstations", "last_seen")
