"""Crear tabla billing_closure_reports (artefacto derivado del cierre: análisis IA + PDF cacheado).

Revision ID: 038_create_billing_closure_reports
Revises: 037_add_billing_audit_actions
Create Date: 2026-08-21 00:00:00.000000

Crea la tabla auxiliar `billing_closure_reports` (1:1 con `billing_closures`) que almacena
el análisis IA y la referencia al PDF cacheado en S3. Se modela como tabla separada (no
como columnas sobre `billing_closures`) para NO contaminar el sustento inmutable de la
factura con datos derivados/mutables (Req 6.1, 11.4).

Detalles clave:
- `closure_id` FK → `billing_closures.id` con `ON DELETE CASCADE` y restricción `UNIQUE`
  (relación 1:1): borrar el cierre padre elimina en cascada su reporte.
- `organization_id` desnormalizado e indexado para tenant isolation y tareas de limpieza.
- Columnas de análisis IA y PDF nullable (fail-safe: un fallo del LLM no bloquea el PDF).

Se reutiliza el tipo GUID (UUID en PostgreSQL, String(36) en SQLite) para consistencia con
los modelos ORM y compatibilidad de tests sobre SQLite.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Reutilizar el tipo GUID para consistencia con los modelos ORM y compatibilidad SQLite.
from app.models.organization import GUID

revision: str = '038_create_billing_closure_reports'
down_revision: Union[str, None] = '037_add_billing_audit_actions'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Crear la tabla billing_closure_reports con FK CASCADE, UNIQUE 1:1 e índice de org."""
    op.create_table(
        "billing_closure_reports",
        sa.Column("id", GUID(), primary_key=True),
        # FK 1:1 con el cierre: ON DELETE CASCADE + UNIQUE (relación 1:1).
        sa.Column(
            "closure_id",
            GUID(),
            sa.ForeignKey("billing_closures.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        # Desnormalizado (indexado) para tenant isolation / tareas de limpieza.
        sa.Column("organization_id", GUID(), nullable=False),
        sa.Column("ai_analysis", sa.Text(), nullable=True),  # NULL = IA no disponible (fail-safe)
        sa.Column("ai_model", sa.String(length=100), nullable=True),  # id del modelo LLM usado
        sa.Column("ai_generated_at", sa.DateTime(), nullable=True),
        sa.Column("pdf_s3_key", sa.String(length=512), nullable=True),  # key determinista cacheada
        sa.Column("pdf_generated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    # Índice sobre organization_id (tenant isolation / limpieza).
    op.create_index(
        "ix_billing_closure_reports_org",
        "billing_closure_reports",
        ["organization_id"],
    )


def downgrade() -> None:
    """Eliminar el índice y la tabla billing_closure_reports."""
    op.drop_index(
        "ix_billing_closure_reports_org",
        table_name="billing_closure_reports",
    )
    op.drop_table("billing_closure_reports")
