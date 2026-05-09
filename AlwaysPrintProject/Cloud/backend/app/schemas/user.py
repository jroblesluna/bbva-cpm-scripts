"""
Schemas Pydantic para User.

Define los esquemas de validación para operaciones con usuarios.
"""

from typing import Optional
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, validator
from uuid import UUID

from app.models.user import UserRole


class UserBase(BaseModel):
    """Schema base para User."""
    email: EmailStr
    role: UserRole
    account_id: Optional[UUID] = None


class UserCreate(UserBase):
    """Schema para crear un usuario."""
    password: str = Field(..., min_length=8, max_length=100)
    
    @validator('password')
    def validate_password(cls, v):
        """Valida que la contraseña cumpla requisitos mínimos."""
        if not any(c.isupper() for c in v):
            raise ValueError('La contraseña debe contener al menos una mayúscula')
        if not any(c.islower() for c in v):
            raise ValueError('La contraseña debe contener al menos una minúscula')
        if not any(c.isdigit() for c in v):
            raise ValueError('La contraseña debe contener al menos un número')
        return v
    
    @validator('account_id')
    def validate_account_id(cls, v, values):
        """Valida que Operador y ReadOnly tengan account_id."""
        role = values.get('role')
        if role in [UserRole.OPERATOR, UserRole.READONLY] and v is None:
            raise ValueError(f'Los usuarios con rol {role.value} deben tener account_id')
        if role == UserRole.ADMIN and v is not None:
            raise ValueError('Los usuarios Admin no deben tener account_id')
        return v


class UserUpdate(BaseModel):
    """Schema para actualizar un usuario."""
    email: Optional[EmailStr] = None
    role: Optional[UserRole] = None
    account_id: Optional[UUID] = None
    is_active: Optional[bool] = None


class UserPasswordUpdate(BaseModel):
    """Schema para actualizar contraseña."""
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=100)
    
    @validator('new_password')
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
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    """Schema para lista paginada de usuarios."""
    items: list[UserResponse]
    total: int
    skip: int
    limit: int

