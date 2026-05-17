"""
Schemas Pydantic para VLAN.

Este módulo define los schemas de validación para VLANs (segmentos de red).
"""

from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field, field_validator
import ipaddress


# === SCHEMAS DE VLAN ===

class VLANCreate(BaseModel):
    """Schema para crear una VLAN."""
    organization_id: Optional[UUID] = Field(None, description="ID de la organización (opcional para operadores)")
    name: str = Field(..., min_length=1, max_length=255, description="Nombre de la VLAN")
    description: Optional[str] = Field(None, max_length=1000, description="Descripción de la VLAN")
    cidr_ranges: list[str] = Field(..., min_length=1, description="Rangos CIDR (ej: ['192.168.1.0/24'])")
    
    @field_validator("cidr_ranges")
    @classmethod
    def validate_cidr_ranges(cls, v: list[str]) -> list[str]:
        """Valida que todos los rangos CIDR sean válidos."""
        validated = []
        for cidr in v:
            try:
                # Valida que sea un CIDR válido
                ipaddress.ip_network(cidr, strict=False)
                validated.append(cidr)
            except ValueError:
                raise ValueError(f"CIDR inválido: {cidr}")
        return validated


class VLANUpdate(BaseModel):
    """Schema para actualizar una VLAN."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    cidr_ranges: Optional[list[str]] = Field(None, min_length=1)
    
    @field_validator("cidr_ranges")
    @classmethod
    def validate_cidr_ranges(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        """Valida que todos los rangos CIDR sean válidos."""
        if v is None:
            return None
        validated = []
        for cidr in v:
            try:
                ipaddress.ip_network(cidr, strict=False)
                validated.append(cidr)
            except ValueError:
                raise ValueError(f"CIDR inválido: {cidr}")
        return validated


class VLANResponse(BaseModel):
    """Schema de respuesta para VLAN."""
    id: UUID
    organization_id: UUID
    name: str
    description: Optional[str] = None
    cidr_ranges: list[str]
    created_at: datetime
    updated_at: datetime
    
    model_config = {"from_attributes": True}


class VLANDetailResponse(VLANResponse):
    """Schema de respuesta detallada para VLAN (incluye conteo de workstations)."""
    workstation_count: int = Field(0, description="Número de workstations en esta VLAN")
    
    model_config = {"from_attributes": True}


class VLANListResponse(BaseModel):
    """Schema de respuesta para lista de VLANs."""
    total: int
    vlans: list[VLANResponse]
