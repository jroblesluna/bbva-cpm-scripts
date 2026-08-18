#!/usr/bin/env python3
"""
Script para rescatar workstations de ZZZ hacia agencias por coincidencia de CIDR.

Lógica:
1. Obtiene workstations en "ZZZ - UBICACION DESCONOCIDA" con IP que empiece con 118.
2. Para cada una, extrae los primeros 3 octetos de su IP (ej: 118.45.67).
3. Busca VLANs de agencia normales (XXX - Nombre, donde XXX != 000, 999, ZZZ)
   que tengan exactamente 1 CIDR y ese CIDR coincida con los 3 primeros octetos.
4. Si hay match único, mueve la workstation a esa VLAN.

Diseñado para ejecutarse dentro del container Docker del backend.

Uso:
    python /tmp/rescue_zzz_by_cidr.py [--org BBVA] [--dry-run]
"""

import sys
import re
import argparse

sys.path.insert(0, '/app')

from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.vlan import VLAN
from app.models.workstation import Workstation
from app.models.organization import Organization


UNKNOWN_VLAN_NAME = "ZZZ - UBICACION DESCONOCIDA"
EXCLUDED_CODES = {"999", "000"}
AGENCY_VLAN_PATTERN = re.compile(r'^(\d{3})\s*-\s*.+')


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


def rescue_zzz_by_cidr(db: Session, org_id, dry_run: bool):
    """
    Rescata workstations de ZZZ a agencias por coincidencia de CIDR.
    """
    print("=" * 60)
    print("Rescatar workstations de ZZZ por coincidencia CIDR")
    print("=" * 60)

    # Obtener VLAN ZZZ
    zzz_vlan = db.query(VLAN).filter(
        VLAN.organization_id == org_id,
        VLAN.name == UNKNOWN_VLAN_NAME
    ).first()

    if not zzz_vlan:
        print("  ⚠️  VLAN ZZZ no existe. Nada que hacer.")
        return

    # Obtener workstations en ZZZ con IP que empiece con 118.
    zzz_workstations = db.query(Workstation).filter(
        Workstation.organization_id == org_id,
        Workstation.vlan_id == zzz_vlan.id,
        Workstation.ip_private.like("118.%")
    ).all()

    print(f"  Workstations en ZZZ con IP 118.x: {len(zzz_workstations)}")

    if not zzz_workstations:
        print("  ✓ No hay workstations candidatas para rescatar")
        return

    # Obtener VLANs de agencia normales (excluir 000, 999, ZZZ)
    all_vlans = db.query(VLAN).filter(VLAN.organization_id == org_id).all()

    # Indexar VLANs de agencia con exactamente 1 CIDR, por prefijo de 3 octetos
    # Estructura: {"118.45.67": VLAN} (solo si tiene 1 único CIDR)
    prefix_to_vlan = {}
    for vlan in all_vlans:
        match = AGENCY_VLAN_PATTERN.match(vlan.name)
        if not match:
            continue

        code = match.group(1)
        if code in EXCLUDED_CODES:
            continue
        if vlan.name == UNKNOWN_VLAN_NAME:
            continue

        cidrs = vlan.cidr_ranges or []
        if len(cidrs) != 1:
            continue

        # Extraer prefijo del CIDR (ej: "118.45.67.0/24" → "118.45.67")
        cidr = cidrs[0]
        parts = cidr.split("/")[0].split(".")
        if len(parts) >= 3:
            prefix = f"{parts[0]}.{parts[1]}.{parts[2]}"
            # Solo considerar CIDRs que empiecen con 118.
            if prefix.startswith("118."):
                if prefix not in prefix_to_vlan:
                    prefix_to_vlan[prefix] = vlan
                else:
                    # Múltiples VLANs con mismo prefijo → no es match único, excluir
                    prefix_to_vlan[prefix] = None

    # Limpiar entradas con múltiples matches
    prefix_to_vlan = {k: v for k, v in prefix_to_vlan.items() if v is not None}

    print(f"  Prefijos CIDR únicos en agencias: {len(prefix_to_vlan)}")

    # Intentar rescatar cada workstation
    moved = 0
    no_match = 0

    for ws in zzz_workstations:
        ip = ws.ip_private or ""
        parts = ip.split(".")
        if len(parts) < 3:
            no_match += 1
            continue

        ws_prefix = f"{parts[0]}.{parts[1]}.{parts[2]}"
        target_vlan = prefix_to_vlan.get(ws_prefix)

        if not target_vlan:
            no_match += 1
            continue

        if dry_run:
            print(f"  [WOULD MOVE] {ws.hostname or '?'} ({ws.ip_private}) → '{target_vlan.name}'")
        else:
            ws.vlan_id = target_vlan.id
            print(f"  [MOVE] {ws.hostname or '?'} ({ws.ip_private}) → '{target_vlan.name}'")
        moved += 1

    if not dry_run:
        db.commit()

    print(f"\n  Resumen:")
    print(f"    Workstations rescatadas: {moved}")
    print(f"    Sin match de CIDR: {no_match}")


def main():
    parser = argparse.ArgumentParser(description="Rescatar workstations de ZZZ por CIDR")
    parser.add_argument("--org", default=None, help="Nombre de la organización")
    parser.add_argument("--dry-run", action="store_true", help="Solo mostrar, no ejecutar")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        org = get_organization(db, args.org)
        rescue_zzz_by_cidr(db, org.id, args.dry_run)

        print("\n" + "=" * 60)
        print("✅ Rescate por CIDR completado.")
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
