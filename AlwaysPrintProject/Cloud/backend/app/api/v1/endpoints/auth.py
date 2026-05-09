"""
Endpoints de autenticación.

Este módulo define los endpoints para:
- Login de usuarios
- Refresh de tokens
- Logout
- Reset de contraseña
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
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

router = APIRouter()


@router.post("/login", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def login(
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
    auth_service = AuthService()
    
    # Autenticar usuario
    user = await auth_service.authenticate_user(db, credentials.email, credentials.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Generar token JWT
    access_token = auth_service.create_access_token(
        user_id=str(user.id),
        email=user.email,
        role=user.role,
        account_id=str(user.account_id) if user.account_id else None
    )
    
    # Registrar login en auditoría
    audit_service = AuditService()
    await audit_service.log_action(
        db=db,
        user_id=user.id,
        action_type="create",
        entity_type="session",
        entity_id=user.id,
        new_values={"action": "login", "email": user.email}
    )
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=3600  # 1 hora
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Cerrar sesión del usuario actual.
    
    Nota: Con JWT stateless, el logout es principalmente del lado del cliente
    (eliminar el token). Este endpoint registra el evento en auditoría.
    
    Args:
        current_user: Usuario autenticado actual
        db: Sesión de base de datos
    """
    # Registrar logout en auditoría
    audit_service = AuditService()
    await audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action_type="delete",
        entity_type="session",
        entity_id=current_user.id,
        old_values={"action": "logout", "email": current_user.email}
    )
    
    return None


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """
    Obtener información del usuario autenticado actual.
    
    Args:
        current_user: Usuario autenticado actual
    
    Returns:
        UserResponse con información del usuario
    """
    return current_user


@router.post("/password-reset", status_code=status.HTTP_202_ACCEPTED)
async def request_password_reset(
    request: PasswordResetRequest,
    db: Session = Depends(get_db)
):
    """
    Solicitar reset de contraseña.
    
    Envía un email con un token para resetear la contraseña.
    Siempre retorna 202 Accepted, incluso si el email no existe
    (para evitar enumeración de usuarios).
    
    Args:
        request: Email del usuario
        db: Sesión de base de datos
    
    Returns:
        Mensaje de confirmación
    """
    auth_service = AuthService()
    
    # Buscar usuario por email
    user = await auth_service.get_user_by_email(db, request.email)
    
    if user:
        # TODO: Generar token de reset y enviar email
        # Por ahora solo registramos en auditoría
        audit_service = AuditService()
        await audit_service.log_action(
            db=db,
            user_id=user.id,
            action_type="update",
            entity_type="user",
            entity_id=user.id,
            new_values={"action": "password_reset_requested"}
        )
    
    # Siempre retornar el mismo mensaje (seguridad)
    return {
        "message": "Si el email existe, recibirás instrucciones para resetear tu contraseña"
    }


@router.post("/password-reset/confirm", status_code=status.HTTP_200_OK)
async def confirm_password_reset(
    confirmation: PasswordResetConfirm,
    db: Session = Depends(get_db)
):
    """
    Confirmar reset de contraseña con token.
    
    Args:
        confirmation: Token de reset y nueva contraseña
        db: Sesión de base de datos
    
    Returns:
        Mensaje de confirmación
    
    Raises:
        HTTPException 400: Token inválido o expirado
    """
    # TODO: Validar token y actualizar contraseña
    # Por ahora retornamos error
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Funcionalidad de reset de contraseña pendiente de implementación"
    )
