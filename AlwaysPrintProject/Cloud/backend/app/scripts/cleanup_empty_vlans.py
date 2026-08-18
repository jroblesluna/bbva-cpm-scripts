#!/usr/bin/env python3
"""
Script de limpieza de VLANs vacías.

Elimina todas las VLANs que no tienen ninguna workstation asignada.
Diseñado para ejecutarse dentro del container Docker del backend.

Uso:
    python /tmp/cleanup_empty_vlans.py [--org BBVA] [--dry-run]
"""

import sys
import argparse

sys.path.insert(0, '/app')

from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.vlan import VLAN
from app.models.workstation import Workstation
from app.models.organization import Organization


def get_organization(db: Session, org_name: str = None):
    """Obtiene la organización."""
    if org_name:
        org = db.query(Organization).filter(Organization.name.ilike(f"%{org_name}%")).first()
    else:
        org = db.query(Organization).first()

    if not org:
        print(f"[ERROR] Organización '{org_name}' no encontrada.")
        sys.exit(1)

    return org


def cleanup_empty_vlans(db: Session, org_id, dry_run: bool):
    """
    Elimina VLANs que no tienen ninguna workstation asignada.
    """
    print("=" * 60)
    print("Eliminar VLANs sin workstations asignadas")
    print("=" * 60)

    # IDs de VLANs que tienen al menos una workstation
    vlans_with_ws = (
        db.query(Workstation.vlan_id)
        .filter(Workstation.vlan_id.isnot(None), Workstation.organization_id == org_id)
        .distinct()
        .all()
    )
    vlan_ids_with_ws = {row[0] for row in vlans_with_ws}

    # Todas las VLANs de la org
    all_vlans = db.query(VLAN).filter(VLAN.organization_id == org_id).all()

    # Filtrar las vacías
    empty_vlans = [v for v in all_vlans if v.id not in vlan_ids_with_ws]

    if not empty_vlans:
        print("  ✓ No hay VLANs vacías para eliminar")
        return

    for vlan in empty_vlans:
        if dry_run:
            print(f"  [WOULD DELETE] {vlan.name}")
        else:
            print(f"  [DELETE] {vlan.name}")
            db.delete(vlan)

    if not dry_run:
        db.commit()
        print(f"\n  ✓ {len(empty_vlans)} VLANs vacías eliminadas")
    else:
        print(f"\n  (dry-run) {len(empty_vlans)} VLANs se eliminarían")


def main():
    parser = argparse.ArgumentParser(description="Eliminar VLANs sin workstations")
    parser.add_argument("--org", default=None, help="Nombre de la organización")
    parser.add_argument("--dry-run", action="store_true", help="Solo mostrar, no ejecutar")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        org = get_organization(db, args.org)
        cleanup_empty_vlans(db, org.id, args.dry_run)
    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
