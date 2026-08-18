#!/usr/bin/env python3
"""
Script para reubicar workstations con hostname no-estándar.

Pasos:
1. Crear la VLAN "ZZZ - UBICACION DESCONOCIDA" si no existe.
2. Identificar workstations con hostname que NO empiece con W10 o W11
   (ej: P0***, DESKTOP***, etc.) y que NO estén en la VLAN "999".
3. Mover esas workstations a la VLAN "ZZZ - UBICACION DESCONOCIDA".

Diseñado para ejecutarse dentro del container Docker del backend.

Uso:
    python /tmp/relocate_unknown_workstations.py [--org BBVA] [--dry-run]
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
EXCLUDED_VLAN_CODE = "999"


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


def step1_ensure_unknown_vlan(db: Session, org_id, dry_run: bool):
    """
    Crea la VLAN "ZZZ - UBICACION DESCONOCIDA" si no existe.
    Retorna el ID de la VLAN.
    """
    print("=" * 60)
    print("STEP 1: Asegurar VLAN 'ZZZ - UBICACION DESCONOCIDA'")
    print("=" * 60)

    vlan = db.query(VLAN).filter(
        VLAN.organization_id == org_id,
        VLAN.name == UNKNOWN_VLAN_NAME
    ).first()

    if vlan:
        print(f"  ✓ VLAN ya existe: '{vlan.name}' (id={vlan.id})")
        return vlan.id

    print(f"  [CREATE] '{UNKNOWN_VLAN_NAME}'")
    if not dry_run:
        vlan = VLAN(
            organization_id=org_id,
            name=UNKNOWN_VLAN_NAME,
            cidr_ranges=[],
        )
        db.add(vlan)
        db.flush()
        db.commit()
        print(f"  ✓ Creada con id={vlan.id}")
        return vlan.id
    else:
        print("  (dry-run) Se crearía la VLAN")
        return "DRY-RUN"


def step2_relocate_non_standard_workstations(db: Session, org_id, target_vlan_id, dry_run: bool):
    """
    Identifica workstations con hostname que NO empiece con W10 o W11
    y que NO estén en la VLAN "999", y las mueve a la VLAN target.
    """
    print("\n" + "=" * 60)
    print("STEP 2: Reubicar workstations con hostname no-estándar")
    print("=" * 60)

    # Encontrar la VLAN "999" para excluirla
    excluded_vlan = db.query(VLAN).filter(
        VLAN.organization_id == org_id,
        VLAN.name.like(f"{EXCLUDED_VLAN_CODE} -%")
    ).first()

    # También buscar por nombre exacto que contenga "999"
    if not excluded_vlan:
        excluded_vlan = db.query(VLAN).filter(
            VLAN.organization_id == org_id,
            VLAN.name.like(f"{EXCLUDED_VLAN_CODE}%")
        ).first()

    excluded_vlan_id = excluded_vlan.id if excluded_vlan else None
    if excluded_vlan:
        print(f"  VLAN excluida: '{excluded_vlan.name}' (id={excluded_vlan_id})")
    else:
        print(f"  ⚠️  VLAN '{EXCLUDED_VLAN_CODE}' no encontrada — no se excluirá ninguna")

    # También excluir la VLAN target (no mover las que ya están ahí)
    excluded_ids = set()
    if excluded_vlan_id:
        excluded_ids.add(str(excluded_vlan_id))
    if target_vlan_id and target_vlan_id != "DRY-RUN":
        excluded_ids.add(str(target_vlan_id))

    # Obtener todas las workstations de la org
    workstations = db.query(Workstation).filter(
        Workstation.organization_id == org_id
    ).all()

    print(f"  Workstations totales: {len(workstations)}")

    # Patrón estándar: hostname empieza con W10 o W11 (case-insensitive)
    standard_pattern = re.compile(r'^W1[01]', re.IGNORECASE)

    # Identificar workstations no-estándar
    to_move = []
    for ws in workstations:
        hostname = ws.hostname or ""

        # Si el hostname es estándar (W10* o W11*), saltear
        if standard_pattern.match(hostname):
            continue

        # Si no tiene hostname, también mover
        if not hostname.strip():
            continue

        # Si ya está en la VLAN excluida (999) o en la target, saltear
        ws_vlan_id = str(ws.vlan_id) if ws.vlan_id else None
        if ws_vlan_id in excluded_ids:
            continue

        to_move.append(ws)

    print(f"  Workstations con hostname no-estándar (fuera de 999): {len(to_move)}")

    if not to_move:
        print("  ✓ No hay workstations para reubicar")
        return

    # Mostrar y mover
    moved = 0
    for ws in to_move:
        vlan_name = ""
        if ws.vlan_id:
            current_vlan = db.query(VLAN).filter(VLAN.id == ws.vlan_id).first()
            vlan_name = current_vlan.name if current_vlan else "?"

        if dry_run:
            print(f"  [WOULD MOVE] {ws.hostname} ({ws.ip_private}) — VLAN actual: '{vlan_name}'")
        else:
            ws.vlan_id = target_vlan_id
            moved += 1

    if not dry_run:
        db.commit()
        print(f"\n  ✓ {moved} workstations movidas a '{UNKNOWN_VLAN_NAME}'")
    else:
        print(f"\n  (dry-run) {len(to_move)} workstations se moverían")


def main():
    parser = argparse.ArgumentParser(description="Reubicar workstations con hostname no-estándar")
    parser.add_argument("--org", default=None, help="Nombre de la organización")
    parser.add_argument("--dry-run", action="store_true", help="Solo mostrar, no ejecutar")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        org = get_organization(db, args.org)

        target_vlan_id = step1_ensure_unknown_vlan(db, org.id, args.dry_run)
        step2_relocate_non_standard_workstations(db, org.id, target_vlan_id, args.dry_run)

        print("\n" + "=" * 60)
        print("✅ Reubicación completada.")
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
