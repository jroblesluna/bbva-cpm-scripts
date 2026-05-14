"""
Utilidades compartidas del backend.

Funciones auxiliares reutilizables en múltiples módulos.
"""

from fastapi import Request


def get_client_ip(request: Request) -> str:
    """
    Obtiene la IP PÚBLICA del cliente desde la solicitud HTTP.
    
    Prioridad (para identificar la organización por IP pública):
    1. Header X-Forwarded-For (IP pública real cuando hay proxy/load balancer)
    2. Header X-Real-IP (usado por Nginx, contiene IP pública)
    3. IP directa del cliente (request.client.host)
    
    NOTA: X-Client-Private-IP se ignora intencionalmente porque contiene
    la IP privada de la red local del cliente, no la IP pública que
    identifica a la organización.
    
    Args:
        request: Objeto Request de FastAPI
        
    Returns:
        Dirección IP PÚBLICA del cliente como string
    """
    # Verificar header X-Forwarded-For para proxies reversos
    # Este header contiene la IP pública real del cliente
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # El primer valor es la IP original del cliente (IP pública)
        return forwarded_for.split(",")[0].strip()
    
    # Verificar X-Real-IP (usado por Nginx)
    # También contiene la IP pública del cliente
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    
    # IP directa del cliente (cuando no hay proxy)
    return request.client.host if request.client else "unknown"
