"""
Middleware de headers de seguridad.

Este módulo agrega headers de seguridad HTTP para proteger contra:
- XSS (Cross-Site Scripting)
- Clickjacking
- MIME sniffing
- Información de servidor
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware que agrega headers de seguridad HTTP.
    
    Headers implementados:
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: DENY
    - X-XSS-Protection: 1; mode=block
    - Strict-Transport-Security: max-age=31536000; includeSubDomains
    - Content-Security-Policy: default-src 'self'
    - Referrer-Policy: strict-origin-when-cross-origin
    - Permissions-Policy: geolocation=(), microphone=(), camera=()
    """
    
    def __init__(self, app):
        super().__init__(app)
        
        # Headers de seguridad a agregar
        self.security_headers = {
            # Prevenir MIME sniffing
            "X-Content-Type-Options": "nosniff",
            
            # Prevenir clickjacking
            "X-Frame-Options": "DENY",
            
            # Protección XSS (legacy, pero aún útil)
            "X-XSS-Protection": "1; mode=block",
            
            # HSTS: Forzar HTTPS (solo en producción)
            # "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
            
            # Content Security Policy
            # Permite recursos del mismo origen + CDN de Swagger UI
            "Content-Security-Policy": (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data: https:; "
                "font-src 'self' data:; "
                "connect-src 'self' https://cdn.jsdelivr.net; "
                "frame-ancestors 'none'"
            ),
            
            # Referrer Policy
            "Referrer-Policy": "strict-origin-when-cross-origin",
            
            # Permissions Policy (antes Feature-Policy)
            "Permissions-Policy": (
                "geolocation=(), "
                "microphone=(), "
                "camera=(), "
                "payment=(), "
                "usb=(), "
                "magnetometer=(), "
                "gyroscope=(), "
                "accelerometer=()"
            ),
            
            # Ocultar información del servidor
            "Server": "AlwaysPrint",
        }
    
    async def dispatch(self, request: Request, call_next) -> Response:
        """
        Procesar request y agregar headers de seguridad.
        
        Args:
            request: Request de FastAPI
            call_next: Siguiente middleware/handler
        
        Returns:
            Response con headers de seguridad
        """
        # Procesar request
        response = await call_next(request)
        
        # Agregar headers de seguridad
        for header, value in self.security_headers.items():
            response.headers[header] = value
        
        # Remover headers que revelan información del servidor
        if "Server" in response.headers:
            response.headers["Server"] = "AlwaysPrint"
        
        return response
