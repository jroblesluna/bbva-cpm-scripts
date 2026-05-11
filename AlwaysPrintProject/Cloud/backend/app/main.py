"""
Punto de entrada principal de la aplicación FastAPI
"""

import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import SessionLocal
from app.services.websocket_manager import connection_manager
from app.api.v1.router import api_router
from app.api.v1.websocket import workstation, operator
from app.middleware import RateLimitMiddleware, SecurityHeadersMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gestor de ciclo de vida de la aplicación.
    
    Inicia el ping loop al arrancar y lo detiene al cerrar.
    """
    # Startup: Iniciar ping loop
    ping_task = asyncio.create_task(
        connection_manager.start_ping_loop(SessionLocal)
    )
    
    yield
    
    # Shutdown: Detener ping loop
    connection_manager.stop_ping_loop()
    ping_task.cancel()
    try:
        await ping_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="AlwaysPrint Cloud Management API",
    description="Sistema de gestión centralizada de estaciones AlwaysPrint",
    version="1.0.0",
    lifespan=lifespan
)

# === MIDDLEWARE ===

# 1. Configuración CORS (debe ir primero)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Headers de seguridad
app.add_middleware(SecurityHeadersMiddleware)

# 3. Rate limiting
app.add_middleware(RateLimitMiddleware)

# === ROUTERS ===

# Incluir router principal de API REST
app.include_router(api_router, prefix=settings.API_V1_STR)

# Incluir routers WebSocket
app.include_router(workstation.router, tags=["WebSocket - Workstations"])
app.include_router(operator.router, tags=["WebSocket - Operators"])


@app.get("/")
async def root():
    """Endpoint raíz para verificar que el servidor está funcionando"""
    return {
        "message": "AlwaysPrint Cloud Management API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "api": settings.API_V1_STR
    }


@app.get("/health")
async def health_check():
    """Endpoint de health check"""
    return {
        "status": "healthy",
        "build_tag": os.environ.get("BUILD_TAG", "dev"),
    }



@app.get("/ws/status")
async def websocket_status():
    """Endpoint para verificar estado de conexiones WebSocket"""
    return {
        "connections": connection_manager.get_connection_count(),
        "online_workstations": len(connection_manager.get_online_workstations()),
        "online_operators": len(connection_manager.get_online_operators())
    }

