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
    
    NOTA: Esta función retorna la IP PÚBLICA para identificar la organización.
    Para obtener la IP privada de la workstation, usar get_workstation_local_ip().
    
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


def get_workstation_local_ip(request: Request) -> str:
    """
    Obtiene la IP PRIVADA de la workstation desde el header X-Workstation-Local-IP.
    
    Esta IP es enviada por el cliente Windows y representa la IP privada de la
    interfaz de red (Ethernet/WiFi) que la workstation usó para conectarse a Internet.
    
    Es útil para:
    - Identificar la workstation dentro de la red corporativa
    - Distinguir entre múltiples workstations detrás de la misma IP pública
    - Logs y auditoría interna
    
    Args:
        request: Objeto Request de FastAPI
        
    Returns:
        IP privada de la workstation, o "unknown" si no está presente
    """
    workstation_ip = request.headers.get("X-Workstation-Local-IP")
    if workstation_ip:
        return workstation_ip.strip()
    
    return "unknown"
