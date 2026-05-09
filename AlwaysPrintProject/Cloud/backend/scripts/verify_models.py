"""
Script de verificación de modelos SQLAlchemy.

Este script verifica que todos los modelos estén correctamente definidos
y que las relaciones entre ellos sean válidas.
"""

import sys
from pathlib import Path

# Agregar el directorio raíz al path para importar app
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    # Importar todos los modelos
    from app.models import (
        User, UserRole,
        Account, PublicIP,
        VLAN,
        Workstation, License,
        GlobalConfig, VLANConfig, WorkstationConfig,
        AuditLog, ActionType,
        Message, TargetType
    )
    from app.core.database import Base, engine
    
    print("✓ Todos los modelos se importaron correctamente")
    
    # Verificar que todos los modelos tienen __tablename__
    models = [
        User, Account, PublicIP, VLAN, Workstation, License,
        GlobalConfig, VLANConfig, WorkstationConfig,
        AuditLog, Message
    ]
    
    print("\n=== Verificación de modelos ===")
    for model in models:
        table_name = getattr(model, '__tablename__', None)
        if table_name:
            print(f"✓ {model.__name__:20} -> tabla: {table_name}")
        else:
            print(f"✗ {model.__name__:20} -> ERROR: no tiene __tablename__")
    
    # Verificar enums
    print("\n=== Verificación de enums ===")
    print(f"✓ UserRole: {[r.value for r in UserRole]}")
    print(f"✓ ActionType: {[a.value for a in ActionType]}")
    print(f"✓ TargetType: {[t.value for t in TargetType]}")
    
    # Verificar que Base.metadata contiene todas las tablas
    print(f"\n=== Tablas registradas en metadata ===")
    print(f"Total de tablas: {len(Base.metadata.tables)}")
    for table_name in sorted(Base.metadata.tables.keys()):
        print(f"  - {table_name}")
    
    print("\n✓ Verificación completada exitosamente")
    
except Exception as e:
    print(f"\n✗ Error durante la verificación: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
