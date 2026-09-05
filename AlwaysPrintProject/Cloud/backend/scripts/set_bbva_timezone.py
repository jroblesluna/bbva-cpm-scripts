"""
Task operativa 28 (Usage and Billing, Req 4.5): fijar la zona horaria de la organización
BBVA en 'America/Lima' ANTES de su primer cierre de facturación.

Contexto y garantía de seguridad
---------------------------------
El "timezone lock" (Task 25) impide cambiar la zona horaria de una organización una vez que
tiene ≥1 BillingClosure, porque los cortes mensuales ya se calcularon con esa tz. Este script
respeta esa garantía de forma FAIL-CLOSED:

  - Si la org BBVA YA tiene algún cierre → NO modifica la tz, informa que está bloqueada y
    termina con código de salida distinto de cero.
  - Si la org NO tiene cierres → setea 'America/Lima', hace commit e informa (viejo → nuevo).
  - Si la tz ya es 'America/Lima' → no cambia nada (idempotente) y termina con éxito (0).

Además la búsqueda de la organización es robusta: si hay cero o más de una coincidencia con el
patrón de nombre, aborta con un mensaje claro en vez de adivinar.

Uso local / dev
---------------
    conda activate alwaysprint
    cd AlwaysPrintProject/Cloud/backend

    # Usa el patrón por defecto (name ILIKE '%BBVA%'):
    python scripts/set_bbva_timezone.py

    # O especifica el nombre exacto o el id de la organización:
    python scripts/set_bbva_timezone.py --name "BBVA"
    python scripts/set_bbva_timezone.py --org-id 123e4567-e89b-12d3-a456-426614174000

    # Ejecución en seco (no escribe, solo informa qué haría):
    python scripts/set_bbva_timezone.py --dry-run

La base de datos objetivo se toma de DATABASE_URL (.env). No modifica ninguna otra tabla ni
ninguna otra organización.

Ejecución por entorno (AWS, región us-west-2)
---------------------------------------------
DEV  (cuenta AlwaysPrint-dev-747301449278):
    export AWS_PROFILE=AlwaysPrint-dev-747301449278
    export AWS_DEFAULT_REGION=us-west-2
    # Ejecutar dentro del contenedor del backend (ejemplo vía SSM run-command o docker exec):
    docker exec alwaysprint-backend-1 python scripts/set_bbva_timezone.py --dry-run
    docker exec alwaysprint-backend-1 python scripts/set_bbva_timezone.py

PROD (cuenta AlwaysPrint-prod-425642439683) — NO EJECUTAR DESDE ESTE REPO/AGENTE:
    export AWS_PROFILE=AlwaysPrint-prod-425642439683
    export AWS_DEFAULT_REGION=us-west-2
    # Normalmente se corre dentro del contenedor del backend vía SSM (sin SSH), p.ej.:
    aws ssm send-command \
      --profile AlwaysPrint-prod-425642439683 --region us-west-2 \
      --instance-ids "i-XXXXXXXXX" \
      --document-name "AWS-RunShellScript" \
      --parameters 'commands=["docker exec alwaysprint-backend-1 python scripts/set_bbva_timezone.py --dry-run"]'
    # Revisar la salida del --dry-run y, sólo si confirma que NO hay cierres, repetir SIN --dry-run.

    IMPORTANTE: este script es la operación de escritura. Debe correrlo un operador en el
    entorno objetivo (típicamente PROD vía SSM dentro del contenedor). El agente/repo NO lo
    ejecuta contra PROD.
"""

import argparse
import sys
from pathlib import Path

# Agregar el directorio raíz del backend al path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal
from app.core.config import settings
from app.models.organization import Organization
from app.models.billing import BillingClosure

# Zona horaria objetivo para BBVA (Req 4.5)
TARGET_TIMEZONE = "America/Lima"
# Patrón de nombre por defecto para localizar la organización BBVA
DEFAULT_NAME_PATTERN = "%BBVA%"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fija la zona horaria de la organización BBVA en 'America/Lima' "
        "antes de su primer cierre (fail-closed si ya tiene cierres).",
    )
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument(
        "--name",
        help="Nombre exacto de la organización (coincidencia case-insensitive). "
        "Si se omite, se usa el patrón por defecto '%%BBVA%%'.",
    )
    grupo.add_argument(
        "--org-id",
        help="ID (UUID) exacto de la organización. Tiene prioridad sobre --name.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="No escribe cambios; sólo informa qué haría.",
    )
    return parser.parse_args()


def _buscar_organizacion(db, args) -> Organization:
    """
    Localiza la organización BBVA de forma robusta.

    - Con --org-id: busca por id exacto.
    - Con --name: busca por nombre exacto (case-insensitive).
    - Sin argumentos: busca por patrón ILIKE '%BBVA%'.

    Si hay cero o más de una coincidencia, imprime un error claro y termina con código != 0
    (no adivina).
    """
    if args.org_id:
        org = db.query(Organization).filter(Organization.id == args.org_id).first()
        if org is None:
            print(f"❌ No se encontró ninguna organización con id '{args.org_id}'.")
            sys.exit(2)
        return org

    if args.name:
        # Coincidencia exacta case-insensitive por nombre
        matches = (
            db.query(Organization)
            .filter(Organization.name.ilike(args.name))
            .all()
        )
        criterio = f"nombre '{args.name}'"
    else:
        # Patrón por defecto
        matches = (
            db.query(Organization)
            .filter(Organization.name.ilike(DEFAULT_NAME_PATTERN))
            .all()
        )
        criterio = f"patrón '{DEFAULT_NAME_PATTERN}'"

    if len(matches) == 0:
        print(f"❌ No se encontró ninguna organización con {criterio}.")
        print("   Especifique --name exacto o --org-id.")
        sys.exit(2)

    if len(matches) > 1:
        print(f"❌ Se encontró más de una organización con {criterio} (ambiguo). No se adivina:")
        for m in matches:
            print(f"     - {m.name}  (id={m.id})")
        print("   Especifique --name exacto o --org-id.")
        sys.exit(2)

    return matches[0]


def main() -> None:
    """Punto de entrada: localiza BBVA, verifica cierres y fija la tz de forma fail-closed."""
    args = _parse_args()

    print("=" * 64)
    print("Configurar timezone de BBVA — Usage and Billing (Req 4.5)")
    print("=" * 64)
    print(f"Base de datos: {settings.DATABASE_URL}")
    print(f"Timezone objetivo: {TARGET_TIMEZONE}")
    if args.dry_run:
        print("Modo: DRY-RUN (no se escribirán cambios)")
    print()

    db = SessionLocal()
    try:
        org = _buscar_organizacion(db, args)
        print(f"Organización encontrada: '{org.name}' (id={org.id})")
        print(f"Timezone actual: {org.timezone}")
        print()

        # === VERIFICACIÓN DEL TIMEZONE LOCK (fail-closed) ===
        cierre = (
            db.query(BillingClosure)
            .filter_by(organization_id=org.id)
            .first()
        )
        if cierre is not None:
            print("🔒 La organización ya tiene al menos un cierre de facturación.")
            print("   El timezone está BLOQUEADO (Task 25) y NO se modificará.")
            print(f"   Cierre existente: {org.name} "
                  f"{cierre.period_year}-{cierre.period_month:02d} (id={cierre.id})")
            sys.exit(3)

        # === IDEMPOTENCIA ===
        if org.timezone == TARGET_TIMEZONE:
            print(f"ℹ️  El timezone ya es '{TARGET_TIMEZONE}'. Nada que cambiar (idempotente).")
            sys.exit(0)

        # === CAMBIO SEGURO ===
        anterior = org.timezone
        if args.dry_run:
            print(f"DRY-RUN: se cambiaría el timezone '{anterior}' → '{TARGET_TIMEZONE}'.")
            print("No se escribió ningún cambio (--dry-run).")
            sys.exit(0)

        org.timezone = TARGET_TIMEZONE
        db.commit()
        print(f"✅ Timezone actualizado: '{anterior}' → '{TARGET_TIMEZONE}'.")

    except SystemExit:
        raise
    except Exception as e:
        db.rollback()
        print(f"❌ Error al configurar el timezone: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()

    print()
    print("Operación completada.")


if __name__ == "__main__":
    main()
