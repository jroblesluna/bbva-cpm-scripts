"""Política de reciclaje configurable: tabla, columnas de freeze/ciclo, backfill y seed.

Revision ID: 039_add_recycle_policy
Revises: 038_billing_closure_reports
Create Date: 2026-08-22 00:00:00.000000

Introduce el esquema y los datos de la feature "recycle-policy-config" (Usage and Billing):

1. Tabla `billing_recycle_policies` (Global_Default + Org_Override versionados por periodo):
   índice `ix_recycle_policy_scope_key` (organization_id, effective_key) y
   CheckConstraint `ck_recycle_policy_month` (mes 1..12).
2. `workstations.billing_cycle_started_at` en 3 pasos (patrón idéntico a `last_seen` en 036):
   ADD nullable → `UPDATE ... = created_at` (Req 18.6) → SET NOT NULL + server_default
   CURRENT_TIMESTAMP. Sobre SQLite (tests) se usa `batch_alter_table`.
3. `billing_closures.recycle_policy_applied` (JSON NOT NULL, server_default '{}') + backfill
   transaccional con la política LEGACY `+1/-2/-3` + 24h (Req 6.1). Fail-closed: si alguna
   fila queda sin política válida, la migración aborta y revierte (Req 6.3).
4. Seed idempotente/atómico `seed_recycle_policies(op.get_bind())` (Global_Default legacy +
   Org_Override BBVA si la org existe) — Req 16.
5. Enum de auditoría: se agrega la etiqueta `BILLING_RECYCLE_POLICY_CHANGE` al tipo
   `actiontype` en PostgreSQL (mismo patrón que la migración 037) — Req 9.1.

Todo (esquema + backfill + seed) comparte la transacción de la migración: atomicidad
todo-o-nada. Se reutiliza el tipo GUID (UUID en PostgreSQL, String(36) en SQLite) para
consistencia con los modelos ORM y compatibilidad de tests sobre SQLite.

`downgrade()`: drop de `recycle_policy_applied`, drop de `billing_cycle_started_at` y drop de
la tabla `billing_recycle_policies`. La etiqueta de enum agregada NO se remueve (PostgreSQL
no permite eliminar valores de un enum), consistente con las migraciones de auditoría previas.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Reutilizar el tipo GUID para consistencia con los modelos ORM y compatibilidad SQLite.
from app.models.organization import GUID
# Seed idempotente y atómico de las políticas por defecto (comparte la transacción).
from app.services.recycle_policy_seed import seed_recycle_policies

revision: str = '039_add_recycle_policy'
down_revision: Union[str, None] = '038_billing_closure_reports'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Política LEGACY para el backfill de cierres históricos (Req 6.1): +1/-2/-3 + 24h,
# que fue la vigente cuando esos cierres se generaron. Se escribe como JSON literal.
_LEGACY_FREEZE = '{"cutoff":1,"cut1":-2,"cut2":-3,"ephemeral_hours":24}'


def _is_sqlite() -> bool:
    """Devuelve True si el dialecto activo es SQLite (path de tests)."""
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    """Crear tabla + columnas (3 pasos), backfill transaccional, seed y enum de auditoría."""
    is_sqlite = _is_sqlite()

    # ── 1. Tabla billing_recycle_policies ────────────────────────────────────
    # Global_Default (organization_id NULL) + Org_Override (organization_id != NULL),
    # versionados por Effective_From_Period (año-mes + clave cronológica entera).
    op.create_table(
        "billing_recycle_policies",
        sa.Column("id", GUID(), primary_key=True),
        # NULL = Global_Default del sistema; no-NULL = Org_Override (tenant isolation).
        sa.Column(
            "organization_id",
            GUID(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        # Recycle_Rule: tres offsets de mes con signo.
        sa.Column("cutoff_offset", sa.Integer(), nullable=False),  # legacy +1
        sa.Column("cut1_offset", sa.Integer(), nullable=False),    # legacy -2
        sa.Column("cut2_offset", sa.Integer(), nullable=False),    # legacy -3
        # Ephemeral_Use_Threshold en horas.
        sa.Column("ephemeral_hours", sa.Integer(), nullable=False),  # legacy 24
        # Effective_From_Period: año-mes + clave cronológica (year*12 + (month-1)).
        sa.Column("effective_from_year", sa.Integer(), nullable=False),   # 2000..2999
        sa.Column("effective_from_month", sa.Integer(), nullable=False),  # 1..12
        sa.Column("effective_key", sa.Integer(), nullable=False, index=True),
        sa.Column(
            "created_by_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        # CheckConstraint del mes (Req 3.1).
        sa.CheckConstraint(
            "effective_from_month BETWEEN 1 AND 12",
            name="ck_recycle_policy_month",
        ),
    )
    # Índice compuesto por scope + periodo, base de la resolución (mayor effective_key <= M).
    op.create_index(
        "ix_recycle_policy_scope_key",
        "billing_recycle_policies",
        ["organization_id", "effective_key"],
    )

    # ── 2. workstations.billing_cycle_started_at (3 pasos) ───────────────────
    # Patrón idéntico a last_seen (036): un DEFAULT SQL no puede referenciar created_at de
    # la misma fila, por eso se puebla con un UPDATE explícito antes de fijar NOT NULL.
    # Paso 1: añadir la columna como nullable (no bloquea sobre tablas grandes).
    op.add_column(
        "workstations",
        sa.Column("billing_cycle_started_at", sa.DateTime(), nullable=True),
    )
    # Paso 2: backfill del histórico con created_at (Req 18.6): comportamiento idéntico al
    # previo para workstations no reactivadas.
    op.execute("UPDATE workstations SET billing_cycle_started_at = created_at")
    # Paso 3: default de seguridad (para inserts que omitan el campo) + NOT NULL.
    if is_sqlite:
        with op.batch_alter_table("workstations") as batch_op:
            batch_op.alter_column(
                "billing_cycle_started_at",
                existing_type=sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            )
    else:
        op.alter_column(
            "workstations",
            "billing_cycle_started_at",
            existing_type=sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        )

    # ── 3. billing_closures.recycle_policy_applied + backfill (Req 6.1/6.3) ──
    # La columna se añade NOT NULL con server_default '{}' (freeze vacío = corrupto, tratado
    # fail-closed por los lectores). El backfill sobrescribe ese vacío con la política LEGACY
    # que aplicó cuando esos cierres se generaron.
    op.add_column(
        "billing_closures",
        sa.Column(
            "recycle_policy_applied",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
    )
    # Backfill transaccional: rellenar cada cierre histórico con la política LEGACY +1/-2/-3+24h.
    # El JSON legacy se pasa como bind param (:freeze) para evitar que SQLAlchemy interprete
    # los ':' internos del JSON (p.ej. "cutoff":1) como parámetros de vínculo.
    op.execute(
        sa.text(
            "UPDATE billing_closures SET recycle_policy_applied = :freeze "
            # CAST a TEXT: el tipo json de PostgreSQL no tiene operador de igualdad (=).
            "WHERE CAST(recycle_policy_applied AS TEXT) = '{}' OR recycle_policy_applied IS NULL"
        ).bindparams(freeze=_LEGACY_FREEZE)
    )
    # Verificación fail-closed (Req 6.3): si queda alguna fila sin política válida, abortar.
    # Al lanzar aquí, la transacción de la migración revierte TODOS los cambios parciales
    # (esquema + backfill previos), y la migración NO se marca como aplicada.
    remaining = op.get_bind().execute(
        sa.text(
            "SELECT COUNT(*) FROM billing_closures "
            # CAST a TEXT: el tipo json de PostgreSQL no tiene operador de igualdad (=).
            "WHERE recycle_policy_applied IS NULL "
            "OR CAST(recycle_policy_applied AS TEXT) = '{}' "
            "OR CAST(recycle_policy_applied AS TEXT) = ''"
        )
    ).scalar()
    if remaining and remaining > 0:
        raise RuntimeError(
            f"Backfill de recycle_policy_applied incompleto: {remaining} cierre(s) sin "
            "política congelada válida. La migración se aborta y revierte (fail-closed, Req 6.3)."
        )

    # ── 4. Seed idempotente/atómico de las políticas por defecto (Req 16) ────
    # Comparte la transacción de la migración: si falla, el rollback revierte también el seed.
    seed_recycle_policies(op.get_bind())

    # ── 5. Enum de auditoría (Req 9.1) ───────────────────────────────────────
    # Agregar la etiqueta BILLING_RECYCLE_POLICY_CHANGE al tipo actiontype (MAYÚSCULA, mismo
    # criterio que 037). Solo aplica a PostgreSQL; SQLite (tests) modela el enum como String.
    if not is_sqlite:
        op.execute(
            "ALTER TYPE actiontype ADD VALUE IF NOT EXISTS 'BILLING_RECYCLE_POLICY_CHANGE'"
        )


def downgrade() -> None:
    """Revertir columnas y tabla (el valor de enum agregado no es removible en PostgreSQL)."""
    is_sqlite = _is_sqlite()

    # ── billing_closures.recycle_policy_applied ──────────────────────────────
    if is_sqlite:
        with op.batch_alter_table("billing_closures") as batch_op:
            batch_op.drop_column("recycle_policy_applied")
    else:
        op.drop_column("billing_closures", "recycle_policy_applied")

    # ── workstations.billing_cycle_started_at ────────────────────────────────
    if is_sqlite:
        with op.batch_alter_table("workstations") as batch_op:
            batch_op.drop_column("billing_cycle_started_at")
    else:
        op.drop_column("workstations", "billing_cycle_started_at")

    # ── Tabla billing_recycle_policies (índice + tabla) ──────────────────────
    op.drop_index(
        "ix_recycle_policy_scope_key",
        table_name="billing_recycle_policies",
    )
    op.drop_table("billing_recycle_policies")
    # Nota: la etiqueta 'BILLING_RECYCLE_POLICY_CHANGE' agregada al enum actiontype NO se
    # elimina (PostgreSQL no permite quitar valores de un enum), consistente con 037.
