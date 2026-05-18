"""
Schemas Pydantic para Organization y PublicIP.

Define los esquemas de validación para operaciones con organizaciones e IPs públicas.
"""

from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from uuid import UUID
import ipaddress


class PublicIPBase(BaseModel):
    """Schema base para PublicIP."""
    ip_address: str
    description: Optional[str] = None
    
    @field_validator('ip_address')
    @classmethod
    def validate_ip(cls, v):
        """Valida que sea una IP válida."""
        try:
            ipaddress.ip_address(v)
        except ValueError:
            raise ValueError(f'IP inválida: {v}')
        return v


class PublicIPCreate(PublicIPBase):
    """Schema para crear una IP pública."""
    pass


class PublicIPResponse(PublicIPBase):
    """Schema para respuesta de IP pública."""
    id: UUID
    organization_id: Optional[UUID] = None  # Puede ser NULL si está pendiente
    is_authorized: bool
    created_at: datetime
    first_seen: datetime
    authorized_at: Optional[datetime] = None
    
    model_config = {"from_attributes": True}


class PublicIPPendingResponse(BaseModel):
    """Schema para IP pública pendiente de autorización."""
    id: UUID
    ip_address: str
    description: Optional[str] = None
    first_seen: datetime
    created_at: datetime
    
    model_config = {"from_attributes": True}


class PublicIPAuthorizeRequest(BaseModel):
    """Schema para autorizar una IP pública."""
    organization_id: UUID = Field(..., description="ID de la organización a la que se asignará la IP")
    description: Optional[str] = Field(None, max_length=500, description="Descripción opcional")


class OrganizationBase(BaseModel):
    """Schema base para Organization."""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    timezone: str = Field(default="UTC", max_length=50, description="Zona horaria de la organización (ej: UTC, America/Lima)")
    language: str = Field(default="en", max_length=2, description="Idioma por defecto de la organización (en, es)")


class OrganizationCreate(OrganizationBase):
    """Schema para crear una organización."""
    pass


class OrganizationUpdate(BaseModel):
    """Schema para actualizar una organización."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    is_active: Optional[bool] = None
    timezone: Optional[str] = Field(None, max_length=50, description="Zona horaria de la organización")
    language: Optional[str] = Field(None, max_length=2, description="Idioma por defecto de la organización")


class OrganizationResponse(OrganizationBase):
    """Schema para respuesta de organización."""
    id: UUID
    is_active: bool
    timezone: str
    language: str
    auto_update_enabled: bool
    target_version: Optional[str] = None
    public_ips: list[PublicIPResponse] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OrganizationDetailResponse(OrganizationResponse):
    """Schema para respuesta detallada de organización."""
    public_ips: list[PublicIPResponse] = []
    workstation_count: int = 0
    online_count: int = 0


class OrganizationListResponse(BaseModel):
    """Schema para lista paginada de organizaciones."""
    items: list[OrganizationResponse]
    total: int
    skip: int
    limit: int


class TargetVersionRequest(BaseModel):
    """Schema de request para establecer la versión objetivo de actualización."""
    version: Optional[str] = Field(None, max_length=50, description="Versión objetivo (null para usar latest)")


class TargetVersionResponse(BaseModel):
    """Schema de response para la versión objetivo de actualización."""
    target_version: Optional[str] = Field(None, description="Versión objetivo actual (null = latest)")
    organization_id: str = Field(..., description="ID de la organización")
    updated_at: datetime = Field(..., description="Fecha de última actualización")

    model_config = {"from_attributes": True}


class AutoUpdateToggleRequest(BaseModel):
    """Schema de request para activar/desactivar auto-actualización."""
    enabled: bool = Field(..., description="Habilitar o deshabilitar actualizaciones automáticas")


class AutoUpdateToggleResponse(BaseModel):
    """Schema de response para el toggle de auto-actualización."""
    auto_update_enabled: bool = Field(..., description="Estado actual del flag de auto-actualización")
    organization_id: str = Field(..., description="ID de la organización")
    updated_at: datetime = Field(..., description="Fecha de última actualización")

    model_config = {"from_attributes": True}

