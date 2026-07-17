#!/usr/bin/env python3
"""
Script de sincronización de inventario de impresoras.

Lee un CSV canónico y sincroniza VLANs, workstations y dispositivos
con la base de datos. Diseñado para ejecutarse dentro del container
Docker del backend.

Uso:
    python -m app.scripts.sync_inventory /path/to/Inventario_Canonico.csv [--org BBVA] [--dry-run]

CSV canónico esperado (columnas):
    VLAN_CODE, VLAN_NAME, IP, MODELO, SERIE, UBICACION, DIRECCION, DISTRITO, PROVINCIA, DEPARTAMENTO, TIPO
"""

import sys
import csv
import argparse
import ipaddress
from collections import defaultdict
from typing import Optional

# Asegurar que el path del backend está disponible
sys.path.insert(0, '/app')

from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.vlan import VLAN
from app.models.device import Device
from app.models.workstation import Workstation
from app.models.organization import Organization


# ============================================================================
# UTILIDADES
# ============================================================================

def get_organization(db: Session, org_name: Optional[str] = None) -> Organization:
    """Obtiene la organización. Si no se especifica nombre, usa la primera."""
    if org_name:
        org = db.query(Organization).filter(Organization.name.ilike(f"%{org_name}%")).first()
    else:
        org = db.query(Organization).first()
    
    if not org:
        print(f"[ERROR] Organización '{org_name}' no encontrada.")
        sys.exit(1)
    
    print(f"[INFO] Organización: {org.name} (id={org.id})")
    return org


def extract_vlan_code_from_hostname(hostname: str) -> Optional[str]:
    """
    Extrae el código de agencia del hostname.
    Formato: w1XXXYYP## → posiciones [3:6] = código de agencia.
    Retorna código zero-padded a 3 dígitos, o None si no se puede extraer.
    """
    if not hostname or len(hostname) < 6:
        return None
    
    code_str = hostname[3:6]
    
    # Verificar que sea numérico
    if not code_str.isdigit():
        return None
    
    return code_str.zfill(3)


def extract_vlan_code_from_name(vlan_name: str) -> Optional[str]:
    """
    Extrae el código numérico del nombre de VLAN.
    Formato: "010 - Ag. Andahuaylas" → "010"
    """
    parts = vlan_name.split(" - ")
    if parts:
        code = parts[0].strip()
        if code.isdigit():
            return code.zfill(3)
    return None


# ============================================================================
# STEP 1: VLANS — Crear faltantes + Renombrar existentes
# ============================================================================

def step1_sync_vlans(db: Session, org_id, csv_vlans: dict[str, str], dry_run: bool) -> dict[str, str]:
    """
    Sincroniza VLANs: crea faltantes, renombra existentes.
    
    Args:
        csv_vlans: {VLAN_CODE: VLAN_NAME} del CSV canónico
    
    Returns:
        Mapa {VLAN_CODE: vlan_id} para uso en pasos posteriores
    """
    print("\n" + "=" * 60)
    print("STEP 1: Sincronizar VLANs")
    print("=" * 60)
    
    # Obtener VLANs existentes
    existing_vlans = db.query(VLAN).filter(VLAN.organization_id == org_id).all()
    
    # Construir mapa: código → VLAN existente
    code_to_existing: dict[str, VLAN] = {}
    for vlan in existing_vlans:
        code = extract_vlan_code_from_name(vlan.name)
        if code:
            if code in code_to_existing:
                # Duplicado — mantener el que tiene más workstations
                existing_ws = db.query(Workstation).filter(Workstation.vlan_id == code_to_existing[code].id).count()
                new_ws = db.query(Workstation).filter(Workstation.vlan_id == vlan.id).count()
                if new_ws > existing_ws:
                    code_to_existing[code] = vlan
            else:
                code_to_existing[code] = vlan
    
    # Mapa resultado: VLAN_CODE → vlan_id
    code_to_id: dict[str, str] = {}
    
    created = 0
    renamed = 0
    unchanged = 0
    
    for code, expected_name in csv_vlans.items():
        if code in code_to_existing:
            vlan = code_to_existing[code]
            code_to_id[code] = str(vlan.id)
            
            if vlan.name != expected_name:
                print(f"  [RENAME] '{vlan.name}' → '{expected_name}'")
                if not dry_run:
                    vlan.name = expected_name
                renamed += 1
            else:
                unchanged += 1
        else:
            # Crear nueva VLAN
            print(f"  [CREATE] '{expected_name}'")
            if not dry_run:
                new_vlan = VLAN(
                    organization_id=org_id,
                    name=expected_name,
                    cidr_ranges=[],
                )
                db.add(new_vlan)
                db.flush()  # Para obtener el ID
                code_to_id[code] = str(new_vlan.id)
            else:
                code_to_id[code] = "DRY-RUN"
            created += 1
    
    if not dry_run:
        db.commit()
    
    print(f"\n  Resumen: {created} creadas, {renamed} renombradas, {unchanged} sin cambios")
    print(f"  Total VLANs en mapa: {len(code_to_id)}")
    
    return code_to_id


# ============================================================================
# STEP 2: REASIGNAR WORKSTATIONS + CIDRs
# ============================================================================

def step2_reassign_workstations(db: Session, org_id, code_to_id: dict[str, str], dry_run: bool):
    """
    Reasigna workstations a VLANs según hostname y actualiza cidr_ranges.
    """
    print("\n" + "=" * 60)
    print("STEP 2: Reasignar Workstations + CIDRs")
    print("=" * 60)
    
    # Obtener todas las workstations de la org
    workstations = db.query(Workstation).filter(Workstation.organization_id == org_id).all()
    print(f"  Workstations totales: {len(workstations)}")
    
    # Buscar o crear VLANs especiales para redes privadas
    special_vlans = {}
    for prefix, vlan_name in [("10.", "VLAN_10"), ("192.", "VLAN_192"), ("172.", "VLAN_172")]:
        vlan = db.query(VLAN).filter(
            VLAN.organization_id == org_id,
            VLAN.name.like(f"{vlan_name}%")
        ).first()
        
        if not vlan:
            # Verificar si hay WS con este prefijo antes de crear
            has_ws = any(ws.ip_private and ws.ip_private.startswith(prefix) for ws in workstations)
            if has_ws:
                print(f"  [CREATE] VLAN especial '{vlan_name}' (WS con IP {prefix}x detectadas)")
                if not dry_run:
                    vlan = VLAN(organization_id=org_id, name=vlan_name, cidr_ranges=[])
                    db.add(vlan)
                    db.flush()
        
        if vlan:
            special_vlans[prefix] = str(vlan.id)
    
    # Reasignar workstations
    reassigned = 0
    skipped = 0
    no_vlan_found = 0
    
    # Acumular CIDRs por VLAN
    vlan_cidrs: dict[str, set] = defaultdict(set)
    
    for ws in workstations:
        ip = ws.ip_private or ""
        hostname = ws.hostname or ""
        target_vlan_id = None
        
        if ip.startswith("118."):
            # Extraer código de agencia del hostname
            code = extract_vlan_code_from_hostname(hostname)
            if code and code in code_to_id:
                target_vlan_id = code_to_id[code]
            else:
                no_vlan_found += 1
                continue
        elif ip.startswith("10."):
            target_vlan_id = special_vlans.get("10.")
        elif ip.startswith("192."):
            target_vlan_id = special_vlans.get("192.")
        elif ip.startswith("172."):
            target_vlan_id = special_vlans.get("172.")
        else:
            skipped += 1
            continue
        
        if not target_vlan_id:
            skipped += 1
            continue
        
        # Reasignar si difiere
        current_vlan_id = str(ws.vlan_id) if ws.vlan_id else None
        if current_vlan_id != target_vlan_id:
            if not dry_run:
                ws.vlan_id = target_vlan_id
            reassigned += 1
        
        # Acumular CIDR de esta WS para la VLAN target
        if ws.cidr:
            vlan_cidrs[target_vlan_id].add(ws.cidr)
    
    # Actualizar cidr_ranges de cada VLAN
    cidrs_updated = 0
    for vlan_id, cidrs in vlan_cidrs.items():
        vlan = db.query(VLAN).filter(VLAN.id == vlan_id).first()
        if vlan:
            new_cidrs = sorted(list(cidrs))
            current_cidrs = sorted(vlan.cidr_ranges or [])
            if new_cidrs != current_cidrs:
                if not dry_run:
                    vlan.cidr_ranges = new_cidrs
                cidrs_updated += 1
    
    if not dry_run:
        db.commit()
    
    print(f"\n  Resumen:")
    print(f"    Reasignadas: {reassigned}")
    print(f"    Sin VLAN encontrada (hostname no matchea): {no_vlan_found}")
    print(f"    Omitidas (IP no reconocida): {skipped}")
    print(f"    VLANs con CIDRs actualizados: {cidrs_updated}")


# ============================================================================
# STEP 3: UPSERT DEVICES (impresoras) desde CSV
# ============================================================================

def step3_upsert_devices(db: Session, org_id, csv_rows: list[dict], code_to_id: dict[str, str], dry_run: bool):
    """
    Crea o actualiza dispositivos (impresoras) desde el CSV canónico.
    """
    print("\n" + "=" * 60)
    print("STEP 3: Upsert Devices (impresoras)")
    print("=" * 60)
    
    # Obtener devices existentes indexados por IP
    existing_devices = db.query(Device).filter(Device.organization_id == org_id).all()
    ip_to_device = {d.ip_address: d for d in existing_devices}
    
    created = 0
    updated = 0
    unchanged = 0
    
    for i, row in enumerate(csv_rows):
        ip = row['IP']
        vlan_code = row['VLAN_CODE']
        vlan_id = code_to_id.get(vlan_code)
        
        expected_name = f"{ip} - {row['MODELO']}"
        expected_description = f"{row['SERIE']} - {row['TIPO']}" if row['SERIE'] else row['TIPO']
        expected_model = row['MODELO']
        expected_location = row['UBICACION']
        
        if ip in ip_to_device:
            device = ip_to_device[ip]
            # Verificar si necesita actualización
            changes = []
            if device.name != expected_name:
                changes.append(f"name: '{device.name}' → '{expected_name}'")
                if not dry_run:
                    device.name = expected_name
            if device.model != expected_model:
                changes.append(f"model")
                if not dry_run:
                    device.model = expected_model
            if device.description != expected_description:
                if not dry_run:
                    device.description = expected_description
                changes.append("description")
            if device.location != expected_location:
                if not dry_run:
                    device.location = expected_location
                changes.append("location")
            if vlan_id and str(device.vlan_id) != vlan_id:
                if not dry_run:
                    device.vlan_id = vlan_id
                changes.append("vlan_id")
            
            if changes:
                updated += 1
            else:
                unchanged += 1
        else:
            # Crear nuevo device
            if not dry_run:
                new_device = Device(
                    organization_id=org_id,
                    vlan_id=vlan_id,
                    name=expected_name,
                    ip_address=ip,
                    description=expected_description,
                    model=expected_model,
                    location=expected_location,
                    port=9100,
                    is_active=True,
                )
                db.add(new_device)
            created += 1
        
        # Commit cada 100 registros para evitar rollback masivo
        if (i + 1) % 100 == 0 and not dry_run:
            db.commit()
    
    if not dry_run:
        db.commit()
    
    print(f"\n  Resumen: {created} creados, {updated} actualizados, {unchanged} sin cambios")


# ============================================================================
# STEP 4: ASIGNAR DEVICES HUÉRFANOS
# ============================================================================

def step4_assign_orphan_devices(db: Session, org_id, dry_run: bool):
    """
    Asigna vlan_id a dispositivos que no tienen VLAN, basándose en su IP
    y los cidr_ranges de las VLANs existentes.
    """
    print("\n" + "=" * 60)
    print("STEP 4: Asignar Devices huérfanos por CIDR")
    print("=" * 60)
    
    # Devices sin VLAN
    orphans = db.query(Device).filter(
        Device.organization_id == org_id,
        Device.vlan_id.is_(None)
    ).all()
    
    if not orphans:
        print("  No hay devices huérfanos.")
        return
    
    print(f"  Devices huérfanos: {len(orphans)}")
    
    # Obtener todas las VLANs con sus CIDRs
    vlans = db.query(VLAN).filter(VLAN.organization_id == org_id).all()
    
    assigned = 0
    for device in orphans:
        if not device.ip_address:
            continue
        
        try:
            device_ip = ipaddress.ip_address(device.ip_address)
        except ValueError:
            continue
        
        for vlan in vlans:
            for cidr in (vlan.cidr_ranges or []):
                try:
                    network = ipaddress.ip_network(cidr, strict=False)
                    if device_ip in network:
                        if not dry_run:
                            device.vlan_id = vlan.id
                        assigned += 1
                        break
                except ValueError:
                    continue
            else:
                continue
            break
    
    if not dry_run:
        db.commit()
    
    print(f"  Asignados: {assigned}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Sincronizar inventario desde CSV canónico")
    parser.add_argument("csv_path", help="Ruta al CSV canónico")
    parser.add_argument("--org", default=None, help="Nombre de la organización (default: primera)")
    parser.add_argument("--dry-run", action="store_true", help="Solo mostrar cambios, no ejecutar")
    args = parser.parse_args()
    
    # Leer CSV
    print(f"[INFO] Leyendo CSV: {args.csv_path}")
    csv_rows = []
    with open(args.csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            csv_rows.append(row)
    print(f"[INFO] Filas leídas: {len(csv_rows)}")
    
    # Extraer VLANs únicas del CSV
    csv_vlans: dict[str, str] = {}
    for row in csv_rows:
        code = row['VLAN_CODE']
        name = row['VLAN_NAME']
        csv_vlans[code] = name
    print(f"[INFO] VLANs únicas en CSV: {len(csv_vlans)}")
    
    if args.dry_run:
        print("\n⚠️  MODO DRY-RUN: No se ejecutarán cambios en la BD\n")
    
    # Conectar a BD
    db = SessionLocal()
    try:
        org = get_organization(db, args.org)
        org_id = org.id
        
        # Ejecutar pasos
        code_to_id = step1_sync_vlans(db, org_id, csv_vlans, args.dry_run)
        step2_reassign_workstations(db, org_id, code_to_id, args.dry_run)
        step3_upsert_devices(db, org_id, csv_rows, code_to_id, args.dry_run)
        step4_assign_orphan_devices(db, org_id, args.dry_run)
        
        print("\n" + "=" * 60)
        print("✅ Sincronización completada.")
        print("=" * 60)
    
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
