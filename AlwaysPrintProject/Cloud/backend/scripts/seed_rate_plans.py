"""
Bootstrap idempotente de los planes tarifarios por defecto (Usage and Billing, Req 8.1).

Inserta en `billing_rate_plans` el plan por defecto 'monthly' (T1–T5) y 'annual' (5 tramos
con free_growth_to) con los valores de la propuesta, SOLO si aún no existe un plan por
defecto para esa modalidad. Es seguro re-ejecutarlo: no duplica ni sobrescribe planes ya
sembrados (ni ediciones posteriores del superadmin).

Normalmente el seed ya lo aplica la migración Alembic 036. Este script sirve para BDs que
se crearon antes de incorporar el seed a la migración, o para re-verificar el estado.

Uso:
    python scripts/seed_rate_plans.py

La modalidad tarifaria se lee de la conexión configurada en DATABASE_URL (.env). No modifica
ninguna otra tabla.
"""

import sys
from pathlib import Path

# Agregar el directorio raíz del backend al path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal
from app.core.config import settings
from app.services.billing_seed import seed_default_rate_plans


def main() -> None:
    """Ejecutar el seed idempotente de planes tarifarios por defecto."""
    print("=" * 60)
    print("Seed de planes tarifarios por defecto — Usage and Billing")
    print("=" * 60)
    print(f"Base de datos: {settings.DATABASE_URL}")
    print()

    db = SessionLocal()
    try:
        inserted = seed_default_rate_plans(db.connection())
        db.commit()

        if inserted:
            print(f"✅ Planes por defecto insertados: {', '.join(inserted)}")
        else:
            print("ℹ️  Los planes por defecto ya existían; nada que insertar (idempotente).")
    except Exception as e:
        db.rollback()
        print(f"❌ Error al sembrar planes tarifarios: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()

    print()
    print("Seed completado.")


if __name__ == "__main__":
    main()
