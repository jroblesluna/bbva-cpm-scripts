"""
Schemas Pydantic para Device (dispositivos/impresoras).

Este módulo define los schemas de validación para dispositivos de impresión.
"""

import ipaddress
from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field, field_validator


# === SCHEMAS DE DEVICE ===

class DeviceCreate(BaseModel):
    """Schema para crear un dispositivo."""
    organization_id: Optional[UUID] = Field(None, description="ID de la organización (opcional para operadores)")
    vlan_id: Optional[UUID] = Field(None, description="ID de la VLAN asociada")
    name: str = Field(..., min_length=1, max_length=255, description="Nombre del dispositivo")
    ip_address: str = Field(..., description="Dirección IP del dispositivo")
    description: Optional[str] = Field(None, max_length=1000, description="Descripción del dispositivo")
    model: Optional[str] = Field(None, max_length=255, description="Modelo de la impresora")
    location: Optional[str] = Field(None, max_length=500, description="Ubicación física")
    port: int = Field(9100, ge=1, le=65535, description="Puerto de impresión")
    is_active: bool = Field(True, description="Si el dispositivo está activo")

    @field_validator("ip_address")
    @classmethod
    def validate_ip(cls, v: str) -> str:
        """Valida que sea una dirección IP válida."""
        try:
            ipaddress.ip_address(v)
            return v
        except ValueError:
            raise ValueError(f"Dirección IP inválida: {v}")


class DeviceUpdate(BaseModel):
    """Schema para actualizar un dispositivo."""
    vlan_id: Optional[UUID] = Field(None, description="ID de la VLAN asociada")
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    ip_address: Optional[str] = Field(None)
    description: Optional[str] = Field(None, max_length=1000)
    model: Optional[str] = Field(None, max_length=255)
    location: Optional[str] = Field(None, max_length=500)
    port: Optional[int] = Field(None, ge=1, le=65535)
    is_active: Optional[bool] = None

    @field_validator("ip_address")
    @classmethod
    def validate_ip(cls, v: Optional[str]) -> Optional[str]:
        """Valida que sea una dirección IP válida."""
        if v is None:
            return None
        try:
            ipaddress.ip_address(v)
            return v
        except ValueError:
            raise ValueError(f"Dirección IP inválida: {v}")


class DeviceResponse(BaseModel):
    """Schema de respuesta para dispositivo."""
    id: UUID
    organization_id: UUID
    vlan_id: Optional[UUID] = None
    name: str
    ip_address: str
    description: Optional[str] = None
    model: Optional[str] = None
    location: Optional[str] = None
    port: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    
    # Nombre de VLAN (para mostrar en UI)
    vlan_name: Optional[str] = None
    
    model_config = {"from_attributes": True}


class DeviceListResponse(BaseModel):
    """Schema de respuesta para lista de dispositivos."""
    total: int
    devices: list[DeviceResponse]
