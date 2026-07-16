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
from app.services.status_scheduler import status_scheduler
from app.services.scalability_metrics import scalability_collector
from app.services.status_batch_writer import status_batch_writer
from app.services.push_services import get_state_map_service
from app.api.v1.router import api_router
from app.api.v1.websocket import workstation, operator, rv_stream
from app.middleware import RateLimitMiddleware, SecurityHeadersMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gestor de ciclo de vida de la aplicación.
    
    En desarrollo (SQLite): crea las tablas automáticamente si no existen.
    Inicia el ping loop al arrancar y lo detiene al cerrar.
    """
    # Startup: Crear tablas en SQLite si no existen (desarrollo)
    if settings.is_sqlite:
        import app.models  # noqa: F401 — Registrar modelos en Base.metadata
        from app.core.database import init_db
        init_db()

    # Startup: Capturar baseline de memoria RSS del proceso
    # (antes de iniciar ping loop y aceptar conexiones WS)
    scalability_collector.capture_baseline()

    # Startup: Inicializar Redis si el manager lo requiere
    if hasattr(connection_manager, 'initialize'):
        await connection_manager.initialize()

    # Startup: Inicializar StateMapService (carga estado desde BD + suscripción Redis)
    state_map = get_state_map_service()
    await state_map.initialize(SessionLocal)

    # Startup: Iniciar ping loop
    ping_task = asyncio.create_task(
        connection_manager.start_ping_loop(SessionLocal)
    )

    # Startup: Iniciar scheduler de recolección de métricas
    status_scheduler.start()

    # Startup: Iniciar batch writer de status_update (flush cada 5s)
    status_batch_writer.start()
    
    yield
    
    # Shutdown: Detener StateMapService (listener Redis + conexión)
    await state_map.shutdown()

    # Shutdown: Detener batch writer de status_update
    status_batch_writer.stop()

    # Shutdown: Detener scheduler de recolección de métricas
    status_scheduler.stop()

    # Shutdown: Notificar a todas las workstations conectadas antes de cerrar
    # Envía close frame con razón explícita para que los clientes distingan
    # un reciclaje/deploy de un corte inesperado de red/proxy
    await connection_manager.graceful_shutdown_workstations(
        reason="Servidor reiniciando (deploy/reciclaje)"
    )

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
app.include_router(rv_stream.router, tags=["WebSocket - RV Stream"])


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

