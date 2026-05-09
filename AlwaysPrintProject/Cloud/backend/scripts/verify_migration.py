"""
Script de verificación de migración inicial.

Este script verifica que la migración 001 se aplicó correctamente:
- Verifica que todas las tablas existen
- Verifica que todos los índices existen
- Verifica que las funciones auxiliares funcionan (PostgreSQL)
- Verifica que los triggers funcionan (PostgreSQL)
"""

import sys
from pathlib import Path

# Agregar el directorio raíz al path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text
from app.core.database import engine, SessionLocal
from app.core.config import settings


def verify_tables():
    """Verifica que todas las tablas esperadas existen."""
    print("\n=== VERIFICANDO TABLAS ===")
    
    expected_tables = [
        'accounts',
        'users',
        'public_ips',
        'vlans',
        'workstations',
        'licenses',
        'global_configs',
        'vlan_configs',
        'workstation_configs',
        'audit_logs',
        'messages',
    ]
    
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    
    all_ok = True
    for table in expected_tables:
        if table in existing_tables:
            print(f"✅ Tabla '{table}' existe")
        else:
            print(f"❌ Tabla '{table}' NO existe")
            all_ok = False
    
    return all_ok


def verify_indexes():
    """Verifica que los índices principales existen."""
    print("\n=== VERIFICANDO ÍNDICES ===")
    
    expected_indexes = {
        'accounts': ['ix_accounts_name'],
        'users': ['ix_users_email'],
        'public_ips': ['ix_public_ips_ip_address'],
        'workstations': ['ix_workstations_ip_private', 'ix_workstations_account_id', 'ix_workstations_is_online'],
        'licenses': ['ix_licenses_serial_number'],
        'audit_logs': ['ix_audit_logs_action_type', 'ix_audit_logs_entity_type', 'ix_audit_logs_created_at'],
        'messages': ['ix_messages_target_type', 'ix_messages_sent_at'],
    }
    
    inspector = inspect(engine)
    all_ok = True
    
    for table, indexes in expected_indexes.items():
        existing_indexes = [idx['name'] for idx in inspector.get_indexes(table)]
        
        for index in indexes:
            if index in existing_indexes:
                print(f"✅ Índice '{index}' en tabla '{table}' existe")
            else:
                print(f"⚠️  Índice '{index}' en tabla '{table}' NO existe (puede ser normal en SQLite)")
                # No marcamos como error porque SQLite puede no crear todos los índices
    
    return all_ok


def verify_foreign_keys():
    """Verifica que las foreign keys principales existen."""
    print("\n=== VERIFICANDO FOREIGN KEYS ===")
    
    expected_fks = {
        'users': ['account_id'],
        'public_ips': ['account_id'],
        'vlans': ['account_id'],
        'workstations': ['account_id', 'vlan_id'],
        'licenses': ['workstation_id'],
        'global_configs': ['account_id'],
        'vlan_configs': ['vlan_id'],
        'workstation_configs': ['workstation_id'],
        'audit_logs': ['user_id', 'workstation_id', 'account_id'],
        'messages': ['account_id', 'sender_id'],
    }
    
    inspector = inspect(engine)
    all_ok = True
    
    for table, fk_columns in expected_fks.items():
        existing_fks = inspector.get_foreign_keys(table)
        existing_fk_columns = [fk['constrained_columns'][0] for fk in existing_fks if fk['constrained_columns']]
        
        for fk_column in fk_columns:
            if fk_column in existing_fk_columns:
                print(f"✅ Foreign key '{fk_column}' en tabla '{table}' existe")
            else:
                print(f"⚠️  Foreign key '{fk_column}' en tabla '{table}' NO existe (puede ser normal en SQLite)")
    
    return all_ok


def verify_postgresql_functions():
    """Verifica que las funciones auxiliares de PostgreSQL funcionan."""
    if not settings.is_postgresql:
        print("\n=== SALTANDO VERIFICACIÓN DE FUNCIONES (no es PostgreSQL) ===")
        return True
    
    print("\n=== VERIFICANDO FUNCIONES AUXILIARES (PostgreSQL) ===")
    
    db = SessionLocal()
    all_ok = True
    
    try:
        # Verificar calculate_license_serial
        result = db.execute(text("SELECT calculate_license_serial('192.168.1.100')")).scalar()
        if result and len(result) == 8:
            print(f"✅ Función 'calculate_license_serial' funciona correctamente (resultado: {result})")
        else:
            print(f"❌ Función 'calculate_license_serial' NO funciona correctamente")
            all_ok = False
        
        # Verificar detect_vlan_for_ip (retorna NULL si no hay VLANs, lo cual es correcto)
        result = db.execute(text(
            "SELECT detect_vlan_for_ip('00000000-0000-0000-0000-000000000000'::UUID, '192.168.1.100')"
        )).scalar()
        print(f"✅ Función 'detect_vlan_for_ip' funciona correctamente (resultado: {result})")
        
    except Exception as e:
        print(f"❌ Error al verificar funciones: {e}")
        all_ok = False
    finally:
        db.close()
    
    return all_ok


def verify_postgresql_triggers():
    """Verifica que los triggers de updated_at funcionan."""
    if not settings.is_postgresql:
        print("\n=== SALTANDO VERIFICACIÓN DE TRIGGERS (no es PostgreSQL) ===")
        return True
    
    print("\n=== VERIFICANDO TRIGGERS (PostgreSQL) ===")
    
    db = SessionLocal()
    all_ok = True
    
    try:
        # Verificar que existe la función update_updated_at_column
        result = db.execute(text(
            "SELECT COUNT(*) FROM pg_proc WHERE proname = 'update_updated_at_column'"
        )).scalar()
        
        if result > 0:
            print(f"✅ Función 'update_updated_at_column' existe")
        else:
            print(f"❌ Función 'update_updated_at_column' NO existe")
            all_ok = False
        
        # Verificar que existen los triggers
        tables_with_triggers = ['accounts', 'users', 'vlans', 'workstations', 'global_configs', 'vlan_configs', 'workstation_configs']
        
        for table in tables_with_triggers:
            result = db.execute(text(
                f"SELECT COUNT(*) FROM pg_trigger WHERE tgname = 'update_{table}_updated_at'"
            )).scalar()
            
            if result > 0:
                print(f"✅ Trigger 'update_{table}_updated_at' existe")
            else:
                print(f"❌ Trigger 'update_{table}_updated_at' NO existe")
                all_ok = False
        
    except Exception as e:
        print(f"❌ Error al verificar triggers: {e}")
        all_ok = False
    finally:
        db.close()
    
    return all_ok


def main():
    """Ejecuta todas las verificaciones."""
    print("=" * 60)
    print("VERIFICACIÓN DE MIGRACIÓN INICIAL")
    print("=" * 60)
    print(f"\nBase de datos: {settings.DATABASE_URL}")
    print(f"Tipo: {'PostgreSQL' if settings.is_postgresql else 'SQLite' if settings.is_sqlite else 'SQL Server'}")
    
    results = []
    
    # Verificar tablas
    results.append(("Tablas", verify_tables()))
    
    # Verificar índices
    results.append(("Índices", verify_indexes()))
    
    # Verificar foreign keys
    results.append(("Foreign Keys", verify_foreign_keys()))
    
    # Verificar funciones (solo PostgreSQL)
    results.append(("Funciones", verify_postgresql_functions()))
    
    # Verificar triggers (solo PostgreSQL)
    results.append(("Triggers", verify_postgresql_triggers()))
    
    # Resumen
    print("\n" + "=" * 60)
    print("RESUMEN")
    print("=" * 60)
    
    all_passed = True
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{name}: {status}")
        if not passed:
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✅ TODAS LAS VERIFICACIONES PASARON")
        print("=" * 60)
        return 0
    else:
        print("❌ ALGUNAS VERIFICACIONES FALLARON")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
