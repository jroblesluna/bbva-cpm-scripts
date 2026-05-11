"""
Endpoints para configuración inicial del sistema.

Este módulo proporciona endpoints para:
- Verificar si el sistema necesita configuración inicial
- Crear el primer usuario administrador
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, Field
import uuid

from app.core.database import get_db
from app.models.user import User, UserRole
from app.services.auth import AuthService

router = APIRouter()


# === SCHEMAS ===

class SetupStatusResponse(BaseModel):
    """Respuesta del estado de configuración inicial."""
    needs_setup: bool
    message: str


class SetupRequest(BaseModel):
    """Request para configuración inicial."""
    email: EmailStr = Field(..., description="Email del administrador")
    password: str = Field(
        ...,
        min_length=8,
        max_length=72,
        description="Contraseña (8-72 caracteres)"
    )
    full_name: str = Field(..., min_length=1, max_length=255, description="Nombre completo")
    language: str = Field(default='en', max_length=2, description="Idioma del primer administrador (en, es)")


class SetupResponse(BaseModel):
    """Respuesta de configuración inicial."""
    success: bool
    message: str
    user: dict


# === ENDPOINTS ===

@router.get("/status", response_model=SetupStatusResponse)
def get_setup_status(db: Session = Depends(get_db)):
    """
    Verificar si el sistema necesita configuración inicial.
    
    Retorna:
        - needs_setup: True si no hay usuarios en el sistema
        - message: Mensaje descriptivo
    """
    # Contar usuarios en el sistema
    user_count = db.query(User).count()
    
    if user_count == 0:
        return SetupStatusResponse(
            needs_setup=True,
            message="El sistema necesita configuración inicial. Por favor, crea el primer usuario administrador."
        )
    else:
        return SetupStatusResponse(
            needs_setup=False,
            message=f"El sistema ya está configurado con {user_count} usuario(s)."
        )


@router.post("/initialize", response_model=SetupResponse, status_code=status.HTTP_201_CREATED)
def initialize_system(
    setup_data: SetupRequest,
    db: Session = Depends(get_db)
):
    """
    Crear el primer usuario administrador del sistema.
    
    Este endpoint solo funciona si no hay usuarios en el sistema.
    Una vez creado el primer usuario, este endpoint quedará deshabilitado.
    
    Args:
        setup_data: Datos del usuario administrador
        
    Returns:
        Información del usuario creado
        
    Raises:
        HTTPException 400: Si el sistema ya está configurado
        HTTPException 400: Si el email ya existe
    """
    # Verificar que no haya usuarios en el sistema
    user_count = db.query(User).count()
    if user_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El sistema ya está configurado. No se puede crear otro usuario administrador inicial."
        )
    
    # Verificar que el email no exista (redundante, pero por seguridad)
    existing_user = db.query(User).filter(User.email == setup_data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El email ya está registrado."
        )
    
    try:
        # Crear usuario administrador
        admin_user = User(
            id=uuid.uuid4(),
            email=setup_data.email,
            password_hash=AuthService.hash_password(setup_data.password),
            full_name=setup_data.full_name,
            role=UserRole.ADMIN,
            account_id=None,  # Admin no pertenece a ninguna cuenta
            is_active=True,
            language=setup_data.language if setup_data.language in ('en', 'es') else 'en',
        )
        
        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)
        
        return SetupResponse(
            success=True,
            message="Usuario administrador creado exitosamente. Ahora puedes iniciar sesión.",
            user={
                "id": str(admin_user.id),
                "email": admin_user.email,
                "full_name": admin_user.full_name,
                "role": admin_user.role.value
            }
        )
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al crear usuario administrador: {str(e)}"
        )
