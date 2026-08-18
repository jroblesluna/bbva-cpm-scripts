#!/usr/bin/env python3
"""
Script para reasignar workstations desde VLANs especiales (VLAN_xxxx) a agencias.

Para cada VLAN con nombre "VLAN_xxxx":
1. Ubica workstations con hostname W10xxx0yPzz o W11xxx0yPzz (donde xxx son dígitos).
2. Extrae el código de agencia xxx del hostname.
3. Si existe una VLAN "xxx - Nombre", mueve la workstation ahí.
4. Si no existe, crea "xxx - Ag. xxx" y mueve la workstation ahí.
5. Las workstations restantes (hostnames no-estándar) se mueven a
   "ZZZ - UBICACION DESCONOCIDA".

Diseñado para ejecutarse dentro del container Docker del backend.

Uso:
    python /tmp/reassign_from_special_vlans.py [--org BBVA] [--dry-run]
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


# Patrón de hostname estándar: W10xxx0yPzz o W11xxx0yPzz
# xxx = código de agencia (3 dígitos), posiciones [3:6]
HOSTNAME_PATTERN = re.compile(r'^W1[01](\d{3})\d.+', re.IGNORECASE)

# Patrón de VLAN especial: VLAN_xxxx (ej: VLAN_10, VLAN_192, VLAN_172)
SPECIAL_VLAN_PATTERN = re.compile(r'^VLAN_\d+', re.IGNORECASE)

# Patrón de VLAN de agencia: "XXX - Nombre"
AGENCY_VLAN_PATTERN = re.compile(r'^(\d{3})\s*-\s*.+')

# VLAN para workstations con hostname no-estándar
UNKNOWN_VLAN_NAME = "ZZZ - UBICACION DESCONOCIDA"


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


def reassign_from_special_vlans(db: Session, org_id, dry_run: bool):
    """
    Reasigna workstations con hostname estándar desde VLANs VLAN_xxxx
    a sus VLANs de agencia correspondientes.
    Mueve el resto (hostnames no-estándar) a ZZZ.
    """
    print("=" * 60)
    print("Reasignar workstations de VLAN_xxxx a agencias")
    print("=" * 60)

    # Obtener todas las VLANs de la org
    all_vlans = db.query(VLAN).filter(VLAN.organization_id == org_id).all()

    # Asegurar VLAN ZZZ existe
    zzz_vlan = None
    for v in all_vlans:
        if v.name == UNKNOWN_VLAN_NAME:
            zzz_vlan = v
            break

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

    # Indexar VLANs especiales (VLAN_xxxx)
    special_vlans = [v for v in all_vlans if SPECIAL_VLAN_PATTERN.match(v.name)]
    print(f"  VLANs especiales encontradas: {len(special_vlans)}")
    for sv in special_vlans:
        print(f"    - {sv.name}")

    if not special_vlans:
        print("  ✓ No hay VLANs especiales para procesar")
        return

    # Indexar VLANs de agencia por código: {"010": VLAN, "123": VLAN, ...}
    agency_vlans_by_code = {}
    for v in all_vlans:
        match = AGENCY_VLAN_PATTERN.match(v.name)
        if match:
            code = match.group(1)
            agency_vlans_by_code[code] = v

    print(f"  VLANs de agencia existentes: {len(agency_vlans_by_code)}")

    moved_to_agency = 0
    moved_to_zzz = 0
    created_vlans = 0

    for special_vlan in special_vlans:
        # Obtener workstations de esta VLAN especial
        workstations = db.query(Workstation).filter(
            Workstation.organization_id == org_id,
            Workstation.vlan_id == special_vlan.id
        ).all()

        if not workstations:
            continue

        print(f"\n  Procesando '{special_vlan.name}' ({len(workstations)} workstations):")

        for ws in workstations:
            hostname = ws.hostname or ""
            match = HOSTNAME_PATTERN.match(hostname)

            if match:
                # === Hostname estándar → mover a agencia ===
                agency_code = match.group(1)  # 3 dígitos

                # Buscar VLAN de agencia existente
                target_vlan = agency_vlans_by_code.get(agency_code)

                if not target_vlan:
                    # Crear nueva VLAN de agencia
                    new_name = f"{agency_code} - Ag. {agency_code}"
                    if dry_run:
                        print(f"    [WOULD CREATE] VLAN '{new_name}'")
                    else:
                        target_vlan = VLAN(
                            organization_id=org_id,
                            name=new_name,
                            cidr_ranges=[],
                        )
                        db.add(target_vlan)
                        db.flush()
                        print(f"    [CREATE] VLAN '{new_name}' (id={target_vlan.id})")
                        agency_vlans_by_code[agency_code] = target_vlan
                    created_vlans += 1

                # Mover workstation a agencia
                if dry_run:
                    target_name = target_vlan.name if target_vlan else f"{agency_code} - Ag. {agency_code}"
                    print(f"    [WOULD MOVE→AGENCIA] {hostname} ({ws.ip_private}) → '{target_name}'")
                else:
                    if target_vlan:
                        ws.vlan_id = target_vlan.id
                        print(f"    [MOVE→AGENCIA] {hostname} ({ws.ip_private}) → '{target_vlan.name}'")
                moved_to_agency += 1

            else:
                # === Hostname no-estándar → mover a ZZZ ===
                if dry_run:
                    print(f"    [WOULD MOVE→ZZZ] {hostname or '(vacío)'} ({ws.ip_private})")
                else:
                    if zzz_vlan:
                        ws.vlan_id = zzz_vlan.id
                        print(f"    [MOVE→ZZZ] {hostname or '(vacío)'} ({ws.ip_private})")
                moved_to_zzz += 1

    if not dry_run:
        db.commit()

    print(f"\n  Resumen:")
    print(f"    VLANs de agencia creadas: {created_vlans}")
    print(f"    Workstations movidas a agencia: {moved_to_agency}")
    print(f"    Workstations movidas a ZZZ: {moved_to_zzz}")


def main():
    parser = argparse.ArgumentParser(
        description="Reasignar workstations de VLAN_xxxx a agencias"
    )
    parser.add_argument("--org", default=None, help="Nombre de la organización")
    parser.add_argument("--dry-run", action="store_true", help="Solo mostrar, no ejecutar")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        org = get_organization(db, args.org)
        reassign_from_special_vlans(db, org.id, args.dry_run)

        print("\n" + "=" * 60)
        print("✅ Reasignación completada.")
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
