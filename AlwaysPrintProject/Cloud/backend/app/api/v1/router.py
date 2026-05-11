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

# Workstations
api_router.include_router(
    workstations.router,
    prefix="/workstations",
    tags=["Workstations"]
)

# VLANs
api_router.include_router(
    vlans.router,
    prefix="/vlans",
    tags=["VLANs"]
)

# Configuración
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
