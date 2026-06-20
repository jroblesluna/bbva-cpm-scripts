"""
Verifica que RegistrationCache no se importa ni referencia en el flujo WebSocket.

Este lint guard previene la regresión de exhaustión de pool de conexiones PostgreSQL
causada por RegistrationCache. Todos los archivos del flujo WebSocket deben usar
ConfigService + queries inline en su lugar.
"""

from pathlib import Path

# Importación prohibida que causó exhaustión del pool "idle in transaction"
BANNED_IMPORT = "registration_cache"

# Archivos del flujo WebSocket que NO deben referenciar registration_cache
# Rutas relativas al directorio backend/
WS_FLOW_FILES = [
    "app/api/v1/websocket/workstation.py",
    "app/api/v1/websocket/operator.py",
    "app/services/websocket_manager.py",
    "app/services/redis_connection_manager.py",
    "app/services/worker_registry.py",
]

# Directorio raíz del backend (relativo a la ubicación de este archivo)
BACKEND_DIR = Path(__file__).resolve().parent.parent


def test_no_registration_cache_in_ws_flow():
    """Verifica que ningún archivo del flujo WebSocket importa o referencia registration_cache."""
    for filepath in WS_FLOW_FILES:
        full_path = BACKEND_DIR / filepath
        content = full_path.read_text()
        assert BANNED_IMPORT not in content, (
            f"PROHIBIDO: {filepath} importa o referencia '{BANNED_IMPORT}'. "
            f"Usar ConfigService + queries inline en su lugar."
        )
