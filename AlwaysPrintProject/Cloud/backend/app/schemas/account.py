"""
Schemas Pydantic para Account y PublicIP.

Define los esquemas de validación para operaciones con cuentas e IPs públicas.
"""

from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, validator
from uuid import UUID
import ipaddress


class PublicIPBase(BaseModel):
    """Schema base para PublicIP."""
    ip_address: str
    description: Optional[str] = None
    
    @validator('ip_address')
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
    account_id: Optional[UUID] = None  # Puede ser NULL si está pendiente
    is_authorized: bool
    created_at: datetime
    first_seen: datetime
    authorized_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class PublicIPPendingResponse(BaseModel):
    """Schema para IP pública pendiente de autorización."""
    id: UUID
    ip_address: str
    description: Optional[str] = None
    first_seen: datetime
    created_at: datetime
    
    class Config:
        from_attributes = True


class PublicIPAuthorizeRequest(BaseModel):
    """Schema para autorizar una IP pública."""
    account_id: UUID = Field(..., description="ID de la cuenta a la que se asignará la IP")
    description: Optional[str] = Field(None, max_length=500, description="Descripción opcional")


class AccountBase(BaseModel):
    """Schema base para Account."""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    timezone: str = Field(default="UTC", max_length=50, description="Zona horaria de la organización (ej: UTC, America/Lima)")
    language: str = Field(default="en", max_length=2, description="Idioma por defecto de la organización (en, es)")


class AccountCreate(AccountBase):
    """Schema para crear una cuenta."""
    pass


class AccountUpdate(BaseModel):
    """Schema para actualizar una cuenta."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    is_active: Optional[bool] = None
    timezone: Optional[str] = Field(None, max_length=50, description="Zona horaria de la organización")
    language: Optional[str] = Field(None, max_length=2, description="Idioma por defecto de la organización")


class AccountResponse(AccountBase):
    """Schema para respuesta de cuenta."""
    id: UUID
    is_active: bool
    timezone: str
    language: str
    public_ips: list[PublicIPResponse] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AccountDetailResponse(AccountResponse):
    """Schema para respuesta detallada de cuenta."""
    public_ips: list[PublicIPResponse] = []
    workstation_count: int = 0
    online_count: int = 0


class AccountListResponse(BaseModel):
    """Schema para lista paginada de cuentas."""
    items: list[AccountResponse]
    total: int
    skip: int
    limit: int

