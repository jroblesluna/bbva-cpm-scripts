"""
Punto de entrada principal de la aplicación FastAPI
"""

import asyncio
import os
import signal
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import configure_structlog, get_logger
from app.core.database import SessionLocal
from app.services.websocket_manager import connection_manager
from app.services.status_scheduler import status_scheduler
from app.services.scalability_metrics import scalability_collector
from app.api.v1.router import api_router
from app.api.v1.websocket import workstation, operator
from app.middleware import RateLimitMiddleware, SecurityHeadersMiddleware

# Configurar structlog lo antes posible para que todos los logs usen formato estructurado
configure_structlog()

logger = get_logger(__name__)


async def _handle_sigterm() -> None:
    """
    Handler asíncrono para SIGTERM.

    Ejecuta el graceful shutdown del connection_manager: cierra WebSockets
    con código 1001, limpia registros en Redis (WorkerRegistry) y cancela
    tasks de background (listener, heartbeat).
    """
    logger.info("sigterm.received", msg="Señal SIGTERM recibida, iniciando graceful shutdown")
    await connection_manager.graceful_shutdown_workstations(
        reason="Servidor apagándose por SIGTERM"
    )
    logger.info("sigterm.shutdown_complete", msg="Graceful shutdown completado por SIGTERM")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gestor de ciclo de vida de la aplicación.
    
    En desarrollo (SQLite): crea las tablas automáticamente si no existen.
    Inicializa el connection_manager (Redis pub/sub + suscripción global:broadcast),
    inicia el ping loop (solo pings a workstations locales) y registra el handler
    de SIGTERM para graceful shutdown.
    """
    # Startup: Crear tablas en SQLite si no existen (desarrollo)
    if settings.is_sqlite:
        import app.models  # noqa: F401 — Registrar modelos en Base.metadata
        from app.core.database import init_db
        init_db()

    # Startup: Inicializar connection_manager (conectar Redis, suscribir
    # global:broadcast, iniciar listener task). En modo in-memory es no-op.
    await connection_manager.initialize()
    logger.info(
        "startup.connection_manager_initialized",
        msg="ConnectionManager inicializado correctamente",
    )

    # Startup: Registrar handler de SIGTERM para graceful shutdown
    # Usa asyncio add_signal_handler para invocar el shutdown asíncrono
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(
        signal.SIGTERM,
        lambda: asyncio.ensure_future(_handle_sigterm()),
    )
    logger.info("startup.sigterm_handler_registered", msg="Handler SIGTERM registrado")

    # Startup: Capturar baseline de memoria RSS del proceso
    # (antes de iniciar ping loop y aceptar conexiones WS)
    scalability_collector.capture_baseline()

    # Startup: Iniciar ping loop (solo envía pings a workstations locales
    # conectadas a este worker — no afecta otros workers)
    ping_task = asyncio.create_task(
        connection_manager.start_ping_loop(SessionLocal)
    )

    # Startup: Iniciar scheduler de recolección de métricas
    status_scheduler.start()
    
    yield
    
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

