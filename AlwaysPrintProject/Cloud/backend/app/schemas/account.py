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
    account_id: UUID
    created_at: datetime
    
    class Config:
        from_attributes = True


class AccountBase(BaseModel):
    """Schema base para Account."""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)


class AccountCreate(AccountBase):
    """Schema para crear una cuenta."""
    pass


class AccountUpdate(BaseModel):
    """Schema para actualizar una cuenta."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    is_active: Optional[bool] = None


class AccountResponse(AccountBase):
    """Schema para respuesta de cuenta."""
    id: UUID
    is_active: bool
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

