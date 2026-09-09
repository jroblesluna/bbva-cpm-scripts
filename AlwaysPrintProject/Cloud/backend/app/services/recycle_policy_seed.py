"""
Seed idempotente y atómico de las políticas de reciclaje por defecto del módulo
Usage and Billing.

Define los valores canónicos de la política de reciclaje del sistema (Req 16.1/16.2)
y una función idempotente para insertarlos en `billing_recycle_policies`. Se invoca desde:

- La migración Alembic 039 (data migration sobre `op.get_bind()`), para que una BD nueva
  quede sembrada automáticamente al aplicar el esquema (task 6.2).

Idempotencia (Req 16.1/16.3): antes de insertar el Global_Default se verifica que no
exista ya una fila con `organization_id IS NULL`. Si ya existe, NO se re-inserta nada
(no se sobrescriben cambios posteriores hechos por el superadmin). El Org_Override de
BBVA se localiza por identificador estable (`organizations.name = 'BBVA'`) y se siembra
solo si aún no existe un override para esa org.

Atomicidad (Req 16.3): la función NO commitea por su cuenta; comparte la transacción de
la migración (o del caller). Si algo falla, el rollback del caller revierte también el
seed. Mismo criterio que `billing_seed.seed_default_rate_plans`.

Semántica de `effective_key` (ver modelo `BillingRecyclePolicy`):
`effective_key = year*12 + (month-1)`. Se persiste para indexar/comparar sin recomputar.
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy import Table, MetaData, select
from sqlalchemy.engine import Connection


logger = logging.getLogger(__name__)


# ── Valores canónicos de las políticas por defecto ──────────────────────────

# Global_Default legacy (Req 16.1): Recycle_Rule +1/-2/-3, umbral efímero 24h,
# vigente "desde siempre" (2000-01). Reproduce el comportamiento legacy pre-configurable.
GLOBAL_DEFAULT = dict(
    cutoff=1,
    cut1=-2,
    cut2=-3,
    ephemeral_hours=24,
    effective_from_year=2000,
    effective_from_month=1,
)

# Org_Override de BBVA (Req 16.2): Recycle_Rule +1/0/-1, umbral efímero 24h,
# vigente desde 2026-09 (inclusive).
BBVA_OVERRIDE = dict(
    cutoff=1,
    cut1=0,
    cut2=-1,
    ephemeral_hours=24,
    effective_from_year=2026,
    effective_from_month=9,
)

# Identificador estable de la organización BBVA (Req 16.2). Se busca por nombre exacto
# para no depender de un id concreto entre entornos.
BBVA_ORG_NAME = "BBVA"


def _effective_key(year: int, month: int) -> int:
    """Clave cronológica entera de un periodo año-mes: year*12 + (month-1)."""
    return year * 12 + (month - 1)


def seed_recycle_policies(connection: Connection) -> list:
    """
    Siembra las políticas de reciclaje por defecto de forma idempotente y atómica.

    - Global_Default (Req 16.1): se inserta solo si NO existe ya una fila con
      `organization_id IS NULL`. Si existe, se preserva (idempotente).
    - Org_Override de BBVA (Req 16.2): se localiza la org por `name = 'BBVA'`. Si la org
      no existe (p.ej. entorno de test sin BBVA), el override se OMITE sin fallar (solo
      se registra una advertencia); nunca se siembra un override huérfano. Si la org
      existe pero ya tiene algún override, tampoco se re-inserta.

    La función NO commitea: comparte la transacción del caller (la migración), de modo
    que si algo falla, el rollback revierte también el seed (Req 16.3).

    Args:
        connection: conexión SQLAlchemy activa (por ejemplo `op.get_bind()` en la
            migración).

    Returns:
        list[str]: etiquetas de las políticas efectivamente insertadas en esta ejecución
            (subconjunto de `["global_default", "bbva_override"]`; vacío si ya estaban
            sembradas o si BBVA no existe).
    """
    # Reflejar las tablas desde la BD para no acoplar la migración al modelo ORM (evita
    # drift si el modelo cambia; las tablas ya existen cuando se llama). Mismo patrón que
    # billing_seed.seed_default_rate_plans.
    metadata = MetaData()
    recycle_policies = Table("billing_recycle_policies", metadata, autoload_with=connection)
    organizations = Table("organizations", metadata, autoload_with=connection)

    inserted = []
    now = datetime.utcnow()

    # ── Global_Default (Req 16.1) ────────────────────────────────────────────
    # Idempotencia: ¿ya hay un Global_Default (organization_id IS NULL)?
    existing_global = connection.execute(
        select(recycle_policies.c.id).where(
            recycle_policies.c.organization_id.is_(None)
        )
    ).first()

    if existing_global is None:
        connection.execute(
            recycle_policies.insert().values(
                id=str(uuid.uuid4()),
                organization_id=None,  # NULL = Global_Default del sistema
                cutoff_offset=GLOBAL_DEFAULT["cutoff"],
                cut1_offset=GLOBAL_DEFAULT["cut1"],
                cut2_offset=GLOBAL_DEFAULT["cut2"],
                ephemeral_hours=GLOBAL_DEFAULT["ephemeral_hours"],
                effective_from_year=GLOBAL_DEFAULT["effective_from_year"],
                effective_from_month=GLOBAL_DEFAULT["effective_from_month"],
                effective_key=_effective_key(
                    GLOBAL_DEFAULT["effective_from_year"],
                    GLOBAL_DEFAULT["effective_from_month"],
                ),
                created_by_id=None,
                created_at=now,
                updated_at=now,
            )
        )
        inserted.append("global_default")
    # Si ya existe, no se toca (no sobrescribir ediciones del superadmin).

    # ── Org_Override de BBVA (Req 16.2) ──────────────────────────────────────
    # Localizar BBVA por identificador estable (name = 'BBVA').
    bbva = connection.execute(
        select(organizations.c.id).where(organizations.c.name == BBVA_ORG_NAME)
    ).first()

    if bbva is None:
        # Org BBVA ausente (p.ej. entorno de test): omitir el override sin fallar.
        logger.warning(
            "Seed recycle: organización '%s' no encontrada; se omite el Org_Override "
            "y solo se siembra el Global_Default.",
            BBVA_ORG_NAME,
        )
        return inserted

    bbva_org_id = bbva[0]

    # Idempotencia del override: ¿ya hay algún override para BBVA?
    existing_override = connection.execute(
        select(recycle_policies.c.id).where(
            recycle_policies.c.organization_id == bbva_org_id
        )
    ).first()

    if existing_override is None:
        connection.execute(
            recycle_policies.insert().values(
                id=str(uuid.uuid4()),
                organization_id=bbva_org_id,
                cutoff_offset=BBVA_OVERRIDE["cutoff"],
                cut1_offset=BBVA_OVERRIDE["cut1"],
                cut2_offset=BBVA_OVERRIDE["cut2"],
                ephemeral_hours=BBVA_OVERRIDE["ephemeral_hours"],
                effective_from_year=BBVA_OVERRIDE["effective_from_year"],
                effective_from_month=BBVA_OVERRIDE["effective_from_month"],
                effective_key=_effective_key(
                    BBVA_OVERRIDE["effective_from_year"],
                    BBVA_OVERRIDE["effective_from_month"],
                ),
                created_by_id=None,
                created_at=now,
                updated_at=now,
            )
        )
        inserted.append("bbva_override")

    return inserted
