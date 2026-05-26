"""
Schemas Pydantic para User.

Define los esquemas de validación para operaciones con usuarios.
"""

from typing import Optional
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from uuid import UUID

from app.models.user import UserRole


# === SCHEMA ANIDADO PARA ORGANIZACIÓN ===
class OrganizationInUser(BaseModel):
    """Schema anidado para mostrar información de la organización en el usuario."""
    id: UUID
    name: str
    timezone: str
    language: str = 'en'

    model_config = {"from_attributes": True}


class UserBase(BaseModel):
    """Schema base para User."""
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=255)
    role: UserRole
    organization_id: Optional[UUID] = None
    timezone: Optional[str] = Field(None, max_length=50, description="Zona horaria del usuario (hereda de la organización si es NULL)")
    language: str = 'en'


class UserCreate(UserBase):
    """Schema para crear un usuario."""
    password: str = Field(..., min_length=8, max_length=100)
    
    @field_validator('password')
    @classmethod
    def validate_password(cls, v):
        """Valida que la contraseña cumpla requisitos mínimos."""
        if not any(c.isupper() for c in v):
            raise ValueError('La contraseña debe contener al menos una mayúscula')
        if not any(c.islower() for c in v):
            raise ValueError('La contraseña debe contener al menos una minúscula')
        if not any(c.isdigit() for c in v):
            raise ValueError('La contraseña debe contener al menos un número')
        return v
    
    @model_validator(mode='after')
    def validate_organization_id(self):
        """Valida que Operador y ReadOnly tengan organization_id."""
        if self.role in [UserRole.OPERATOR, UserRole.READONLY] and self.organization_id is None:
            raise ValueError(f'Los usuarios con rol {self.role.value} deben tener organization_id')
        if self.role == UserRole.ADMIN and self.organization_id is not None:
            raise ValueError('Los usuarios Admin no deben tener organization_id')
        return self


class UserUpdate(BaseModel):
    """Schema para actualizar un usuario."""
    email: Optional[EmailStr] = None
    full_name: Optional[str] = Field(None, min_length=1, max_length=255)
    password: Optional[str] = Field(None, min_length=8, max_length=100, description="Nueva contraseña (dejar vacío para no cambiar)")
    role: Optional[UserRole] = None
    organization_id: Optional[UUID] = None
    is_active: Optional[bool] = None
    timezone: Optional[str] = Field(None, max_length=50, description="Zona horaria del usuario")
    language: Optional[str] = Field(None, max_length=2, description="Idioma del usuario (en, es)")


class UserPasswordUpdate(BaseModel):
    """Schema para actualizar contraseña."""
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=100)
    
    @field_validator('new_password')
    @classmethod
    def validate_password(cls, v):
        """Valida que la contraseña cumpla requisitos mínimos."""
        if not any(c.isupper() for c in v):
            raise ValueError('La contraseña debe contener al menos una mayúscula')
        if not any(c.islower() for c in v):
            raise ValueError('La contraseña debe contener al menos una minúscula')
        if not any(c.isdigit() for c in v):
            raise ValueError('La contraseña debe contener al menos un número')
        return v


class UserResponse(UserBase):
    """Schema para respuesta de usuario."""
    id: UUID
    is_active: bool
    timezone: Optional[str]
    language: str
    created_at: datetime
    updated_at: datetime
    organization: Optional[OrganizationInUser] = None

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    """Schema para lista paginada de usuarios."""
    items: list[UserResponse]
    total: int
    skip: int
    limit: int
