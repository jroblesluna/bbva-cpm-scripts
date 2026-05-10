"""
Script para corregir endpoints que usan async def incorrectamente.

Este script:
1. Busca todos los archivos de endpoints
2. Reemplaza 'async def' por 'def' (excepto en WebSockets)
3. Elimina 'await' de llamadas a servicios síncronos
"""

import os
import re
from pathlib import Path

# Directorios a procesar
ENDPOINTS_DIR = Path("app/api/v1/endpoints")
WEBSOCKET_DIR = Path("app/api/v1/websocket")

# Archivos a excluir (WebSockets deben mantener async)
EXCLUDE_FILES = []

def fix_async_in_file(filepath: Path):
    """Corrige async/await en un archivo de endpoints."""
    print(f"Procesando: {filepath}")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    changes = []
    
    # 1. Reemplazar 'async def' por 'def' en decoradores de router
    # Patrón: @router.METHOD(...)\nasync def function_name
    pattern = r'(@router\.(get|post|put|delete|patch)\([^)]*\)\s*)\nasync def '
    if re.search(pattern, content):
        content = re.sub(pattern, r'\1\ndef ', content)
        changes.append("Eliminado 'async' de definiciones de endpoints")
    
    # 2. Eliminar 'await' de llamadas a servicios conocidos
    # Servicios síncronos comunes
    sync_services = [
        'audit_service',
        'auth_service',
        'db.query',
        'db.add',
        'db.commit',
        'db.delete',
        'db.refresh',
    ]
    
    for service in sync_services:
        pattern = rf'await\s+{re.escape(service)}'
        if re.search(pattern, content):
            content = re.sub(pattern, service, content)
            changes.append(f"Eliminado 'await' de '{service}'")
    
    # 3. Eliminar 'await' de llamadas a métodos de servicios
    # Patrón: await service.method(...)
    pattern = r'await\s+(\w+_service\.\w+)\('
    if re.search(pattern, content):
        content = re.sub(pattern, r'\1(', content)
        changes.append("Eliminado 'await' de llamadas a métodos de servicios")
    
    # Guardar si hubo cambios
    if content != original_content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"  ✅ Corregido: {', '.join(changes)}")
        return True
    else:
        print(f"  ℹ️  Sin cambios necesarios")
        return False

def main():
    """Procesa todos los archivos de endpoints."""
    print("=" * 60)
    print("Corrigiendo uso incorrecto de async/await en endpoints")
    print("=" * 60)
    print()
    
    files_processed = 0
    files_changed = 0
    
    # Procesar archivos de endpoints
    if ENDPOINTS_DIR.exists():
        for filepath in ENDPOINTS_DIR.glob("*.py"):
            if filepath.name in EXCLUDE_FILES:
                print(f"Omitiendo: {filepath} (excluido)")
                continue
            
            files_processed += 1
            if fix_async_in_file(filepath):
                files_changed += 1
            print()
    
    print("=" * 60)
    print(f"Resumen:")
    print(f"  Archivos procesados: {files_processed}")
    print(f"  Archivos modificados: {files_changed}")
    print("=" * 60)
    print()
    print("⚠️  IMPORTANTE: Revisa los cambios antes de commitear")
    print("⚠️  Los WebSockets NO fueron modificados (deben mantener async)")

if __name__ == "__main__":
    main()
