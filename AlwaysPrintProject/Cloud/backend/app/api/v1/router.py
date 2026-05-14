"""
Router principal de la API v1.

Este módulo integra todos los routers de endpoints y WebSocket.
"""

import os
from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    accounts,
    users,
    workstations,
    vlans,
    config,
    messages,
    audit,
    setup,
    telemetry,
    connectivity,
)

# Router principal de la API v1
api_router = APIRouter()

# === ENDPOINTS REST ===

# Setup inicial (sin autenticación)
api_router.include_router(
    setup.router,
    prefix="/setup",
    tags=["Setup"]
)

# Autenticación (sin prefijo adicional, ya está en /api/v1/auth)
api_router.include_router(
    auth.router,
    prefix="/auth",
    tags=["Autenticación"]
)

# Cuentas (solo Admin)
api_router.include_router(
    accounts.router,
    prefix="/accounts",
    tags=["Cuentas"]
)

# Usuarios
api_router.include_router(
    users.router,
    prefix="/users",
    tags=["Usuarios"]
)

# Configuración efectiva de workstation (autenticación por IP pública o token Bearer)
# Registrado ANTES del router de workstations para que tome precedencia en GET /{id}/config
api_router.include_router(
    config.workstation_config_router,
    prefix="/workstations",
    tags=["Configuración Efectiva"]
)

# Workstations
api_router.include_router(
    workstations.router,
    prefix="/workstations",
    tags=["Workstations"]
)

# Telemetría (historial por workstation)
api_router.include_router(
    telemetry.router,
    tags=["Telemetría"]
)

# Telemetría (estadísticas por cuenta)
api_router.include_router(
    telemetry.accounts_router,
    tags=["Telemetría"]
)

# Conectividad (historial de resultados por workstation)
api_router.include_router(
    connectivity.router,
    tags=["Conectividad"]
)

# VLANs
api_router.include_router(
    vlans.router,
    prefix="/vlans",
    tags=["VLANs"]
)

# Configuración global
api_router.include_router(
    config.router,
    prefix="/config",
    tags=["Configuración"]
)

# Mensajes
api_router.include_router(
    messages.router,
    prefix="/messages",
    tags=["Mensajes"]
)

# Auditoría
api_router.include_router(
    audit.router,
    prefix="/audit",
    tags=["Auditoría"]
)


@api_router.get("/version", tags=["Sistema"])
async def version():
    return {"build_tag": os.environ.get("BUILD_TAG", "dev")}


@api_router.get("/health", tags=["Sistema"])
async def health():
    """Health check accesible desde el Client Tray y monitoreo externo."""
    return {
        "status": "healthy",
        "build_tag": os.environ.get("BUILD_TAG", "dev"),
    }
