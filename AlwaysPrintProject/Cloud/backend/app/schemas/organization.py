"""
Schemas Pydantic para endpoints de organizaciones.

Define los schemas de request/response para la gestión de
actualizaciones automáticas a nivel de organización.
"""

from datetime import datetime
from pydantic import BaseModel, Field


class AutoUpdateToggleRequest(BaseModel):
    """Schema de request para activar/desactivar auto-actualización."""
    enabled: bool = Field(..., description="Habilitar o deshabilitar actualizaciones automáticas")


class AutoUpdateToggleResponse(BaseModel):
    """Schema de response para el toggle de auto-actualización."""
    auto_update_enabled: bool = Field(..., description="Estado actual del flag de auto-actualización")
    organization_id: str = Field(..., description="ID de la organización")
    updated_at: datetime = Field(..., description="Fecha de última actualización")

    model_config = {"from_attributes": True}
