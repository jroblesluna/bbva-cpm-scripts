"""
Middleware de rate limiting.

Este módulo implementa rate limiting para proteger la API contra:
- Ataques de fuerza bruta en login
- Abuso de API
- DDoS
"""

import time
from typing import Dict, Tuple
from collections import defaultdict
from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response, JSONResponse

from app.core.config import settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware de rate limiting basado en IP.
    
    Implementa dos niveles de rate limiting:
    1. Login endpoints: 5 intentos por minuto
    2. API general: 100 peticiones por minuto
    
    Usa memoria para almacenar contadores (considerar Redis en producción).
    """
    
    def __init__(self, app):
        super().__init__(app)
        # Estructura: {ip: {endpoint: [(timestamp, count)]}}
        self.requests: Dict[str, Dict[str, list]] = defaultdict(lambda: defaultdict(list))
        self.cleanup_interval = 60  # Limpiar cada 60 segundos
        self.last_cleanup = time.time()
    
    def _get_client_ip(self, request: Request) -> str:
        """
        Obtener IP del cliente.
        
        Considera headers de proxy (X-Forwarded-For, X-Real-IP).
        """
        # Intentar obtener IP real desde headers de proxy
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            # X-Forwarded-For puede contener múltiples IPs
            return forwarded.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        # Fallback a IP del cliente directo
        if request.client:
            return request.client.host
        
        return "unknown"
    
    def _get_rate_limit(self, path: str) -> Tuple[int, int]:
        """
        Obtener límite de rate para un path.
        
        Returns:
            Tuple[int, int]: (max_requests, window_seconds)
        """
        # Login endpoints: 5 intentos por minuto
        if "/auth/login" in path or "/auth/password-reset" in path:
            return (settings.RATE_LIMIT_LOGIN, 60)
        
        # API general: 100 peticiones por minuto
        if path.startswith("/api/"):
            return (settings.RATE_LIMIT_API, 60)
        
        # Sin límite para otros endpoints (health, docs, etc.)
        return (10000, 60)
    
    def _cleanup_old_requests(self):
        """
        Limpiar requests antiguos de memoria.
        
        Se ejecuta cada 60 segundos para evitar memory leaks.
        """
        current_time = time.time()
        
        # Solo limpiar si ha pasado el intervalo
        if current_time - self.last_cleanup < self.cleanup_interval:
            return
        
        # Limpiar requests más antiguos de 2 minutos
        cutoff_time = current_time - 120
        
        for ip in list(self.requests.keys()):
            for endpoint in list(self.requests[ip].keys()):
                # Filtrar requests antiguos
                self.requests[ip][endpoint] = [
                    (ts, count) for ts, count in self.requests[ip][endpoint]
                    if ts > cutoff_time
                ]
                
                # Eliminar endpoint si está vacío
                if not self.requests[ip][endpoint]:
                    del self.requests[ip][endpoint]
            
            # Eliminar IP si está vacía
            if not self.requests[ip]:
                del self.requests[ip]
        
        self.last_cleanup = current_time
    
    def _check_rate_limit(self, ip: str, path: str) -> bool:
        """
        Verificar si el cliente ha excedido el rate limit.
        
        Args:
            ip: IP del cliente
            path: Path del endpoint
        
        Returns:
            bool: True si está dentro del límite, False si lo excedió
        """
        max_requests, window_seconds = self._get_rate_limit(path)
        current_time = time.time()
        cutoff_time = current_time - window_seconds
        
        # Obtener requests del cliente en esta ventana de tiempo
        requests = self.requests[ip][path]
        
        # Filtrar requests dentro de la ventana
        recent_requests = [
            (ts, count) for ts, count in requests
            if ts > cutoff_time
        ]
        
        # Contar total de requests
        total_requests = sum(count for _, count in recent_requests)
        
        # Verificar límite
        if total_requests >= max_requests:
            return False
        
        # Agregar este request
        recent_requests.append((current_time, 1))
        self.requests[ip][path] = recent_requests
        
        return True
    
    async def dispatch(self, request: Request, call_next) -> Response:
        """
        Procesar request y aplicar rate limiting.
        
        Args:
            request: Request de FastAPI
            call_next: Siguiente middleware/handler
        
        Returns:
            Response
        
        Raises:
            HTTPException 429: Too Many Requests
        """
        # Limpiar requests antiguos periódicamente
        self._cleanup_old_requests()
        
        # Obtener IP del cliente
        client_ip = self._get_client_ip(request)
        path = request.url.path
        
        # Verificar rate limit
        if not self._check_rate_limit(client_ip, path):
            max_requests, window_seconds = self._get_rate_limit(path)
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": f"Demasiadas peticiones. Límite: {max_requests} por {window_seconds} segundos"},
                headers={"Retry-After": str(window_seconds)}
            )
        
        # Continuar con el request
        response = await call_next(request)
        
        # Agregar headers de rate limit a la respuesta
        max_requests, window_seconds = self._get_rate_limit(path)
        cutoff_time = time.time() - window_seconds
        recent_requests = [
            (ts, count) for ts, count in self.requests[client_ip][path]
            if ts > cutoff_time
        ]
        total_requests = sum(count for _, count in recent_requests)
        remaining = max(0, max_requests - total_requests)
        
        response.headers["X-RateLimit-Limit"] = str(max_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(time.time() + window_seconds))
        
        return response
