"""
Schemas Pydantic para autenticación.

Este módulo define los schemas de validación para login y tokens JWT.
"""

from typing import Optional
from pydantic import BaseModel, Field, EmailStr

from app.models.user import UserRole


# === SCHEMAS DE AUTENTICACIÓN ===

class LoginRequest(BaseModel):
    """Schema para solicitud de login."""
    email: EmailStr = Field(..., description="Email del usuario")
    password: str = Field(..., min_length=8, description="Contraseña del usuario")


class TokenResponse(BaseModel):
    """Schema de respuesta para token JWT."""
    access_token: str = Field(..., description="Token JWT de acceso")
    refresh_token: Optional[str] = Field(None, description="Token de refresco (opcional)")
    token_type: str = Field(default="bearer", description="Tipo de token")
    expires_in: int = Field(..., description="Tiempo de expiración en segundos")


class TokenPayload(BaseModel):
    """Schema para payload del token JWT."""
    sub: str = Field(..., description="Subject (user_id)")
    email: str = Field(..., description="Email del usuario")
    role: UserRole = Field(..., description="Rol del usuario")
    organization_id: Optional[str] = Field(None, description="ID de la organización (solo para operadores)")
    exp: int = Field(..., description="Timestamp de expiración")


class RefreshTokenRequest(BaseModel):
    """Schema para solicitud de refresh token."""
    refresh_token: str = Field(..., description="Token de refresco")


class PasswordResetRequest(BaseModel):
    """Schema para solicitud de reseteo de contraseña."""
    email: EmailStr = Field(..., description="Email del usuario")


class PasswordResetConfirm(BaseModel):
    """Schema para confirmar reseteo de contraseña."""
    token: str = Field(..., description="Token de reseteo")
    new_password: str = Field(..., min_length=8, description="Nueva contraseña")
