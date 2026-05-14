"""
Utilidades compartidas del backend.

Funciones auxiliares reutilizables en múltiples módulos.
"""

from fastapi import Request


def get_client_ip(request: Request) -> str:
    """
    Obtiene la IP del cliente desde la solicitud HTTP.
    
    Prioridad:
    1. Header X-Client-Private-IP (IP privada enviada por el frontend)
    2. Header X-Forwarded-For (para proxies/load balancers)
    3. Header X-Real-IP (usado por Nginx)
    4. IP directa del cliente (request.client.host)
    
    Args:
        request: Objeto Request de FastAPI
        
    Returns:
        Dirección IP del cliente como string
    """
    # Priorizar IP privada enviada por el frontend
    private_ip = request.headers.get("X-Client-Private-IP")
    if private_ip and private_ip.strip():
        return private_ip.strip()
    
    # Verificar header X-Forwarded-For para proxies reversos
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # El primer valor es la IP original del cliente
        return forwarded_for.split(",")[0].strip()
    
    # Verificar X-Real-IP (usado por Nginx)
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    
    # IP directa del cliente
    return request.client.host if request.client else "unknown"
