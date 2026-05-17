"""
Endpoints de autenticación.

Este módulo define los endpoints para:
- Login de usuarios
- Refresh de tokens
- Logout
- Reset de contraseña
"""

import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.core.utils import get_client_ip
from app.models.user import User
from app.schemas import (
    LoginRequest,
    TokenResponse,
    PasswordResetRequest,
    PasswordResetConfirm,
    UserResponse,
)
from app.services.auth import AuthService
from app.services.audit import AuditService
from app.services.email import send_password_reset_email

router = APIRouter()


@router.post("/login", response_model=TokenResponse, status_code=status.HTTP_200_OK)
def login(
    credentials: LoginRequest,
    db: Session = Depends(get_db)
):
    """
    Autenticar usuario y obtener token JWT.
    
    Args:
        credentials: Email y contraseña del usuario
        db: Sesión de base de datos
    
    Returns:
        TokenResponse con access_token, token_type y expires_in
    
    Raises:
        HTTPException 401: Credenciales inválidas
    """
    # Autenticar usuario
    user = AuthService.authenticate_user(db, credentials.email, credentials.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Crear tokens para el usuario
    tokens = AuthService.create_tokens_for_user(user)
    
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Cerrar sesión del usuario actual.
    
    Nota: Con JWT stateless, el logout es principalmente del lado del cliente
    (eliminar el token). Este endpoint registra el evento en auditoría.
    
    Args:
        request: Objeto Request de FastAPI
        current_user: Usuario autenticado actual
        db: Sesión de base de datos
    """
    # Registrar logout en auditoría
    from app.models.audit import ActionType
    
    audit_service = AuditService()
    audit_service.log_action(
        db=db,
        action_type=ActionType.DELETE,
        entity_type="session",
        entity_id=str(current_user.id),
        user_id=str(current_user.id),
        account_id=str(current_user.organization_id) if current_user.organization_id else None,
        old_values={"action": "logout", "email": current_user.email},
        ip_address=get_client_ip(request)
    )
    
    return None


@router.get("/me", response_model=UserResponse)
def get_current_user_info(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtener información del usuario autenticado actual.
    
    Args:
        current_user: Usuario autenticado actual
        db: Sesión de base de datos
    
    Returns:
        UserResponse con información del usuario (incluye relación con account)
    """
    from sqlalchemy.orm import joinedload
    
    # Recargar usuario con la relación account
    user = db.query(User).options(joinedload(User.account)).filter(User.id == current_user.id).first()
    
    return user


@router.post("/password-reset", status_code=status.HTTP_202_ACCEPTED)
def request_password_reset(
    request: PasswordResetRequest,
    db: Session = Depends(get_db)
):
    """
    Solicitar reset de contraseña.

    Siempre retorna 202 aunque el email no exista (evita enumeración de usuarios).
    """
    user = db.query(User).filter(User.email == request.email).first()

    if user and user.is_active:
        token = secrets.token_urlsafe(32)
        user.password_reset_token = token
        user.password_reset_expires = datetime.utcnow() + timedelta(hours=1)
        db.commit()

        reset_url = f"{settings.FRONTEND_URL}/reset-password?token={token}"
        send_password_reset_email(user.email, reset_url)

    return {"message": "Si el email existe, recibirás instrucciones para restablecer tu contraseña."}


@router.post("/password-reset/confirm", status_code=status.HTTP_200_OK)
def confirm_password_reset(
    confirmation: PasswordResetConfirm,
    db: Session = Depends(get_db)
):
    """
    Confirmar reset de contraseña con el token recibido por email.

    Raises:
        HTTPException 400: Token inválido o expirado
    """
    user = db.query(User).filter(
        User.password_reset_token == confirmation.token
    ).first()

    if not user or not user.password_reset_expires:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token inválido.")

    if datetime.utcnow() > user.password_reset_expires:
        user.password_reset_token = None
        user.password_reset_expires = None
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token expirado.")

    user.password_hash = AuthService.hash_password(confirmation.new_password)
    user.password_reset_token = None
    user.password_reset_expires = None
    db.commit()

    return {"message": "Contraseña actualizada correctamente."}
