"""
stale_ips.py — Lista workstations con IPs que:
  1. Estuvieron activas al menos 24h  (updated_at - created_at > 24h)
  2. No se han conectado en más de 90 días  (updated_at < hoy - 90 días)

Uso:
    python scripts/stale_ips.py
    python scripts/stale_ips.py --days 60          # umbral distinto
    python scripts/stale_ips.py --csv              # exportar a CSV
    python scripts/stale_ips.py --org <org_id>     # filtrar por organización
"""

import argparse
import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Asegurar que el directorio raíz del backend esté en el path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.models.workstation import Workstation
from app.models.organization import Organization
from sqlalchemy import and_, func


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Lista workstations inactivas por más de N días con al menos 24h de actividad registrada."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Días de inactividad para considerar una IP como stale (default: 90)",
    )
    parser.add_argument(
        "--min-hours",
        type=int,
        default=24,
        help="Horas mínimas de actividad (updated_at - created_at) para incluir la IP (default: 24)",
    )
    parser.add_argument(
        "--org",
        type=str,
        default=None,
        help="Filtrar por organization_id (UUID)",
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        default=False,
        help="Exportar resultado a CSV en stdout",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    stale_threshold = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=args.days)
    min_active_seconds = args.min_hours * 3600

    db = SessionLocal()
    try:
        query = (
            db.query(
                Workstation.ip_private,
                Workstation.hostname,
                Workstation.current_user,
                Workstation.created_at,
                Workstation.updated_at,
                Workstation.is_online,
                Organization.name.label("org_name"),
            )
            .join(Organization, Workstation.organization_id == Organization.id, isouter=True)
            .filter(
                and_(
                    # Condición 1: al menos 24h de actividad registrada
                    func.extract(
                        "epoch",
                        Workstation.updated_at - Workstation.created_at
                    ) > min_active_seconds,
                    # Condición 2: última actualización hace más de N días
                    Workstation.updated_at < stale_threshold,
                )
            )
            .order_by(Workstation.updated_at.asc())
        )

        if args.org:
            query = query.filter(Workstation.organization_id == args.org)

        rows = query.all()

        if not rows:
            print(f"No se encontraron IPs stale (inactivas >{args.days}d con >{args.min_hours}h de actividad).")
            return

        headers = ["ip_private", "hostname", "current_user", "created_at", "updated_at", "dias_inactiva", "is_online", "org_name"]

        if args.csv:
            writer = csv.writer(sys.stdout)
            writer.writerow(headers)
            for row in rows:
                dias = (datetime.now(timezone.utc).replace(tzinfo=None) - row.updated_at).days
                writer.writerow([
                    row.ip_private,
                    row.hostname or "",
                    row.current_user or "",
                    row.created_at.isoformat() if row.created_at else "",
                    row.updated_at.isoformat() if row.updated_at else "",
                    dias,
                    row.is_online,
                    row.org_name or "",
                ])
        else:
            # Salida tabular en consola
            print(f"\nWorkstations inactivas >  {args.days} días  |  actividad mínima > {args.min_hours}h")
            print(f"Umbral de inactividad: {stale_threshold.date()}  |  Total encontradas: {len(rows)}\n")
            print(f"{'IP':<18} {'Hostname':<20} {'Usuario':<15} {'Creada':<12} {'Últ. actualización':<20} {'Días inactiva':>13}  {'Org'}")
            print("-" * 110)
            for row in rows:
                dias = (datetime.now(timezone.utc).replace(tzinfo=None) - row.updated_at).days
                created = row.created_at.date() if row.created_at else "-"
                updated = row.updated_at.isoformat()[:19] if row.updated_at else "-"
                print(
                    f"{row.ip_private or '-':<18} "
                    f"{(row.hostname or '-')[:19]:<20} "
                    f"{(row.current_user or '-')[:14]:<15} "
                    f"{str(created):<12} "
                    f"{updated:<20} "
                    f"{dias:>13}  "
                    f"{row.org_name or '-'}"
                )
            print()

    finally:
        db.close()


if __name__ == "__main__":
    main()
