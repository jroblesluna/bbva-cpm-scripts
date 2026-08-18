#!/usr/bin/env python3
"""
Script para mover CIDRs no-118.x a la VLAN ZZZ.

En VLANs de agencia con nombre normalizado (XXX - Nombre),
excepto 999, 000 y ZZZ:
- Identifica CIDRs que NO empiecen con "118."
- Los mueve a la VLAN "ZZZ - UBICACION DESCONOCIDA"
- Evita duplicados en ZZZ

Diseñado para ejecutarse dentro del container Docker del backend.

Uso:
    python /tmp/cleanup_non118_cidrs.py [--org BBVA] [--dry-run]
"""

import sys
import re
import argparse

sys.path.insert(0, '/app')

from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.vlan import VLAN
from app.models.organization import Organization


UNKNOWN_VLAN_NAME = "ZZZ - UBICACION DESCONOCIDA"
EXCLUDED_CODES = {"999", "000"}
VALID_CIDR_PREFIX = "118."


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


def cleanup_non118_cidrs(db: Session, org_id, dry_run: bool):
    """
    Para VLANs de agencia (XXX - Nombre), excepto 999, 000 y ZZZ:
    - Quita CIDRs que no empiecen con 118.
    - Los agrega a la VLAN ZZZ (sin duplicados).
    """
    print("=" * 60)
    print("Mover CIDRs no-118.x de agencias a ZZZ")
    print("=" * 60)

    # Obtener o verificar la VLAN ZZZ
    zzz_vlan = db.query(VLAN).filter(
        VLAN.organization_id == org_id,
        VLAN.name == UNKNOWN_VLAN_NAME
    ).first()

    if not zzz_vlan:
        print(f"  [CREATE] '{UNKNOWN_VLAN_NAME}'")
        if not dry_run:
            zzz_vlan = VLAN(
                organization_id=org_id,
                name=UNKNOWN_VLAN_NAME,
                cidr_ranges=[],
            )
            db.add(zzz_vlan)
            db.flush()
            print(f"  ✓ Creada con id={zzz_vlan.id}")
        else:
            print("  (dry-run) Se crearía la VLAN")
    else:
        print(f"  VLAN ZZZ: '{zzz_vlan.name}' (id={zzz_vlan.id})")

    # CIDRs actuales de ZZZ (para evitar duplicados)
    zzz_cidrs = set(zzz_vlan.cidr_ranges or []) if zzz_vlan else set()
    cidrs_added_to_zzz = set()

    # Patrón de VLAN de agencia normalizada: "XXX - Nombre"
    agency_pattern = re.compile(r'^(\d{3})\s*-\s*.+')

    # Obtener todas las VLANs de la org
    all_vlans = db.query(VLAN).filter(VLAN.organization_id == org_id).all()

    vlans_cleaned = 0
    total_cidrs_moved = 0

    for vlan in all_vlans:
        # Solo VLANs con formato "XXX - Nombre"
        match = agency_pattern.match(vlan.name)
        if not match:
            continue

        code = match.group(1)

        # Excluir 999, 000 y ZZZ
        if code in EXCLUDED_CODES:
            continue
        if vlan.name == UNKNOWN_VLAN_NAME:
            continue

        current_cidrs = vlan.cidr_ranges or []
        if not current_cidrs:
            continue

        # Separar: CIDRs que empiezan con 118. vs los demás
        keep_cidrs = [c for c in current_cidrs if c.startswith(VALID_CIDR_PREFIX)]
        move_cidrs = [c for c in current_cidrs if not c.startswith(VALID_CIDR_PREFIX)]

        if not move_cidrs:
            continue

        # Reportar
        if dry_run:
            print(f"  [WOULD CLEAN] '{vlan.name}' — mover a ZZZ: {move_cidrs}")
        else:
            print(f"  [CLEAN] '{vlan.name}' — moviendo a ZZZ: {move_cidrs}")
            vlan.cidr_ranges = keep_cidrs

        # Acumular CIDRs para ZZZ (sin duplicados)
        for cidr in move_cidrs:
            if cidr not in zzz_cidrs:
                cidrs_added_to_zzz.add(cidr)
                zzz_cidrs.add(cidr)

        vlans_cleaned += 1
        total_cidrs_moved += len(move_cidrs)

    # Actualizar CIDRs de ZZZ
    if cidrs_added_to_zzz:
        if dry_run:
            print(f"\n  [WOULD ADD to ZZZ] {len(cidrs_added_to_zzz)} CIDRs nuevos: {sorted(cidrs_added_to_zzz)}")
        else:
            if zzz_vlan:
                merged = sorted(zzz_cidrs)
                zzz_vlan.cidr_ranges = merged
                print(f"\n  [ADD to ZZZ] {len(cidrs_added_to_zzz)} CIDRs nuevos agregados")

    if not dry_run:
        db.commit()

    print(f"\n  Resumen:")
    print(f"    VLANs de agencia limpiadas: {vlans_cleaned}")
    print(f"    CIDRs movidos a ZZZ: {total_cidrs_moved}")
    print(f"    CIDRs nuevos en ZZZ (sin duplicados): {len(cidrs_added_to_zzz)}")


def main():
    parser = argparse.ArgumentParser(description="Mover CIDRs no-118.x de agencias a ZZZ")
    parser.add_argument("--org", default=None, help="Nombre de la organización")
    parser.add_argument("--dry-run", action="store_true", help="Solo mostrar, no ejecutar")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        org = get_organization(db, args.org)
        cleanup_non118_cidrs(db, org.id, args.dry_run)

        print("\n" + "=" * 60)
        print("✅ Limpieza de CIDRs completada.")
        print("=" * 60)
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
