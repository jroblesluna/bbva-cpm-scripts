"""
Endpoints de la API v1.

Este módulo exporta todos los routers de endpoints.
"""

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

__all__ = [
    "auth",
    "accounts",
    "users",
    "workstations",
    "vlans",
    "config",
    "messages",
    "audit",
    "setup",
]
