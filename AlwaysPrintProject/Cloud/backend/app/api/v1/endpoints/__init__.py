"""
Endpoints de la API v1.

Este módulo exporta todos los routers de endpoints.
"""

from app.api.v1.endpoints import (
    auth,
    organizations,
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

__all__ = [
    "auth",
    "organizations",
    "users",
    "workstations",
    "vlans",
    "config",
    "messages",
    "audit",
    "setup",
    "telemetry",
    "connectivity",
]
