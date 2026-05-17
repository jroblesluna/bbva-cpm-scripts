"""
Módulo de compatibilidad: re-exporta desde organization.py.

Este archivo existe para mantener compatibilidad con imports existentes
que usan `from app.models.account import Account, PublicIP, GUID`.
La implementación real está en app.models.organization.
"""

from app.models.organization import Organization as Account, Organization, PublicIP, GUID

__all__ = ["Account", "Organization", "PublicIP", "GUID"]
