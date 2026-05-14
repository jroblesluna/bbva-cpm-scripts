#!/usr/bin/env python3
"""
Script para limpiar IPs privadas de la tabla public_ips.

Este script elimina registros de IPs privadas (172.x.x.x, 192.168.x.x, 10.x.x.x)
que fueron registradas incorrectamente debido a un bug en la detección de IP del cliente.

Uso:
    python scripts/fix_private_ips.py

Nota: Este script debe ejecutarse una sola vez después del fix del bug.
"""

import sys
import os
from pathlib import Path

# Agregar el directorio raíz al path para importar módulos de la app
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from app.models.account import PublicIP


def is_private_ip(ip: str) -> bool:
    """
    Verifica si una IP es privada.
    
    Rangos privados:
    - 10.0.0.0/8
    - 172.16.0.0/12
    - 192.168.0.0/16
    - 127.0.0.0/8 (loopback)
    """
    parts = ip.split('.')
    if len(parts) != 4:
        return False
    
    try:
        first = int(parts[0])
        second = int(parts[1])
        
        # 10.x.x.x
        if first == 10:
            return True
        
        # 172.16.x.x - 172.31.x.x
        if first == 172 and 16 <= second <= 31:
            return True
        
        # 192.168.x.x
        if first == 192 and second == 168:
            return True
        
        # 127.x.x.x (loopback)
        if first == 127:
            return True
        
        return False
    except ValueError:
        return False


def main():
    """Elimina IPs privadas de la base de datos."""
    print("=== Limpieza de IPs privadas ===\n")
    
    # Crear sesión de base de datos
    engine = create_engine(settings.DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    try:
        # Obtener todas las IPs
        all_ips = db.query(PublicIP).all()
        print(f"Total de IPs en la base de datos: {len(all_ips)}")
        
        # Filtrar IPs privadas
        private_ips = [ip for ip in all_ips if is_private_ip(ip.ip_address)]
        print(f"IPs privadas encontradas: {len(private_ips)}\n")
        
        if not private_ips:
            print("✓ No se encontraron IPs privadas. Base de datos limpia.")
            return
        
        # Mostrar IPs que serán eliminadas
        print("IPs privadas que serán eliminadas:")
        for ip in private_ips:
            status = "Autorizada" if ip.is_authorized else "Pendiente"
            account = f"Account {ip.account_id}" if ip.account_id else "Sin cuenta"
            print(f"  - {ip.ip_address} ({status}, {account})")
        
        # Confirmar eliminación
        print("\n¿Desea eliminar estas IPs? (s/n): ", end='')
        response = input().strip().lower()
        
        if response != 's':
            print("Operación cancelada.")
            return
        
        # Eliminar IPs privadas
        deleted_count = 0
        for ip in private_ips:
            db.delete(ip)
            deleted_count += 1
        
        db.commit()
        print(f"\n✓ {deleted_count} IPs privadas eliminadas correctamente.")
        
    except Exception as e:
        db.rollback()
        print(f"\n✗ Error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
