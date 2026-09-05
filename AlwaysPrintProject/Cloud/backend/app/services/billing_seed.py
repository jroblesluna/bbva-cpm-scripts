"""
Seed idempotente de los planes tarifarios por defecto del módulo Usage and Billing.

Define los valores canónicos de las tarifas por defecto del sistema (Req 8.1) y una
función idempotente para insertarlos en `billing_rate_plans`. La misma lógica se usa desde:

- La migración Alembic 036 (data migration sobre `op.get_bind()`), para que una BD nueva
  quede sembrada automáticamente al aplicar el esquema.
- El script de bootstrap `scripts/seed_rate_plans.py`, re-ejecutable de forma segura.

Idempotencia: antes de insertar un plan por defecto de una modalidad se verifica que no
exista ya un `billing_rate_plans` con `is_default = TRUE` para esa `mode`. Si ya existe,
NO se toca (los cambios de tarifas posteriores hechos por el superadmin no se sobrescriben).

Formato de `tiers` (JSON ordenado por rango):
- monthly: [{"from": 1, "to": 100, "rate": 0.500}, ...]  (último tramo "to": null)
- annual:  [{"from": 1, "to": 100, "rate": 5.00, "free_growth_to": 200}, ...]
           (el último tramo no tiene "to" ni "free_growth_to")
"""

import uuid
from datetime import datetime

from sqlalchemy import Table, MetaData, select
from sqlalchemy.engine import Connection


# ── Valores canónicos de las tarifas por defecto (Req 8.1) ──────────────────

# Mensual — tarifa incremental por tramos (US$/IP). Cada tramo factura solo las IPs
# contenidas en él. El último tramo (10,001+) no tiene tope superior ("to": None).
MONTHLY_DEFAULT_TIERS = [
    {"from": 1, "to": 100, "rate": 0.500},        # T1: 1–100
    {"from": 101, "to": 2000, "rate": 0.250},     # T2: 101–2,000
    {"from": 2001, "to": 5000, "rate": 0.200},    # T3: 2,001–5,000
    {"from": 5001, "to": 10000, "rate": 0.180},   # T4: 5,001–10,000
    {"from": 10001, "to": None, "rate": 0.175},   # T5: 10,001+
]

# Anual — tarifa preferencial única del tramo contratado (US$/IP/año). Cada tramo declara
# su tope de "crecimiento libre" (`free_growth_to`) hasta el cual no se reclasifica. El
# último tramo (11,201+) no tiene tope superior ni crecimiento libre.
ANNUAL_DEFAULT_TIERS = [
    {"from": 1, "to": 100, "rate": 5.00, "free_growth_to": 200},       # 1–100 (crec. libre 200)
    {"from": 201, "to": 2000, "rate": 2.50, "free_growth_to": 2250},   # 201–2,000 (2,250)
    {"from": 2251, "to": 5000, "rate": 2.25, "free_growth_to": 5800},  # 2,251–5,000 (5,800)
    {"from": 5801, "to": 10000, "rate": 1.95, "free_growth_to": 11200},  # 5,801–10,000 (11,200)
    {"from": 11201, "to": None, "rate": 1.75},                         # 11,201+
]

# Nombres de los planes por defecto (visibles en la UI de superadmin).
MONTHLY_DEFAULT_NAME = "Tarifa Mensual por Defecto"
ANNUAL_DEFAULT_NAME = "Tarifa Anual por Defecto"

DEFAULT_CURRENCY = "USD"

# Definición de los planes por defecto a sembrar, por modalidad.
_DEFAULT_PLANS = [
    {"mode": "monthly", "name": MONTHLY_DEFAULT_NAME, "tiers": MONTHLY_DEFAULT_TIERS},
    {"mode": "annual", "name": ANNUAL_DEFAULT_NAME, "tiers": ANNUAL_DEFAULT_TIERS},
]


def seed_default_rate_plans(connection: Connection) -> list:
    """
    Inserta los planes tarifarios por defecto (monthly + annual) de forma idempotente.

    Para cada modalidad, si ya existe un `billing_rate_plans` con `is_default = TRUE`,
    NO se inserta nada (se preserva el plan existente y cualquier edición del superadmin).

    Args:
        connection: conexión SQLAlchemy activa (por ejemplo `op.get_bind()` en la
            migración o `db.connection()` desde una sesión del bootstrap).

    Returns:
        list[str]: modalidades efectivamente insertadas en esta ejecución (vacío si ya
            estaban sembradas).
    """
    # Reflejar la tabla desde la BD para no acoplar la migración al modelo ORM (evita
    # drift si el modelo cambia en el futuro; la tabla ya existe cuando se llama).
    metadata = MetaData()
    rate_plans = Table("billing_rate_plans", metadata, autoload_with=connection)

    inserted = []
    now = datetime.utcnow()

    for plan in _DEFAULT_PLANS:
        mode = plan["mode"]

        # Idempotencia: ¿ya hay un plan por defecto para esta modalidad?
        existing = connection.execute(
            select(rate_plans.c.id).where(
                (rate_plans.c.mode == mode) & (rate_plans.c.is_default.is_(True))
            )
        ).first()
        if existing is not None:
            continue  # ya sembrado; no sobrescribir

        connection.execute(
            rate_plans.insert().values(
                id=str(uuid.uuid4()),
                mode=mode,
                is_default=True,
                name=plan["name"],
                tiers=plan["tiers"],
                currency=DEFAULT_CURRENCY,
                effective_from=None,  # vigente de inmediato
                created_at=now,
                updated_at=now,
            )
        )
        inserted.append(mode)

    return inserted
