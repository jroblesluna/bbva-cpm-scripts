"""
Endpoints para configuración inicial del sistema.

Este módulo proporciona endpoints para:
- Verificar si el sistema necesita configuración inicial
- Crear el primer usuario administrador
- Detectar si hay una restauración de backup en progreso
"""

import json
import logging

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, Field
import uuid

from app.core.config import settings
from app.core.database import get_db
from app.models.user import User, UserRole
from app.services.auth import AuthService

logger = logging.getLogger(__name__)

router = APIRouter()


# === HELPERS ===

def _read_restore_status() -> dict:
    """
    Lee backups/restore_status.json desde S3.

    Retorna el contenido del archivo JSON, o un dict con status "idle"
    si el archivo no existe o hay un error de lectura.
    """
    try:
        session = boto3.Session(
            region_name=settings.AWS_REGION,
            profile_name=settings.AWS_PROFILE or None,
        )
        s3 = session.client("s3")
        response = s3.get_object(
            Bucket=settings.S3_ARTIFACTS_BUCKET,
            Key="backups/restore_status.json",
        )
        return json.loads(response["Body"].read().decode("utf-8"))
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code in ("NoSuchKey", "404"):
            return {"status": "idle"}
        logger.error("Error leyendo restore status de S3: %s", str(e))
        return {"status": "idle"}
    except Exception as e:
        logger.error("Error leyendo restore status: %s", str(e))
        return {"status": "idle"}


# === SCHEMAS ===

class SetupStatusResponse(BaseModel):
    """Respuesta del estado de configuración inicial."""
    needs_setup: bool
    message: str
    restore_in_progress: bool = False


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
        - needs_setup: True si no hay usuarios en el sistema y no hay restore en progreso
        - message: Mensaje descriptivo
        - restore_in_progress: True si hay una restauración de backup en curso
    """
    # Contar usuarios en el sistema
    user_count = db.query(User).count()
    
    if user_count == 0:
        # Verificar si hay un restore en progreso
        restore_status = _read_restore_status()
        if restore_status.get("status") == "restoring":
            return SetupStatusResponse(
                needs_setup=False,
                message="Restauración de backup en progreso.",
                restore_in_progress=True,
            )

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
            organization_id=None,  # Admin no pertenece a ninguna organización
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
