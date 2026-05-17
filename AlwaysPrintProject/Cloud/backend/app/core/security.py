"""
Módulo de seguridad y autenticación.

Este módulo define:
- Dependencias de FastAPI para autenticación
- Funciones de verificación de permisos
- Utilidades de seguridad
"""

from typing import Optional
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import settings
from app.models.user import User, UserRole

# Esquema de seguridad HTTP Bearer
security = HTTPBearer()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Crear un token JWT de acceso.
    
    Args:
        data: Datos a incluir en el token
        expires_delta: Tiempo de expiración opcional
    
    Returns:
        Token JWT codificado
    """
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.now(timezone.utc).replace(tzinfo=None) + expires_delta
    else:
        expire = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
    
    to_encode.update({"exp": expire})
    
    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM
    )
    
    return encoded_jwt


def decode_access_token(token: str) -> dict:
    """
    Decodificar un token JWT.
    
    Args:
        token: Token JWT a decodificar
    
    Returns:
        Payload del token
    
    Raises:
        HTTPException 401: Token inválido o expirado
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """
    Obtener el usuario autenticado actual desde el token JWT.
    
    Args:
        credentials: Credenciales HTTP Bearer
        db: Sesión de base de datos
    
    Returns:
        Usuario autenticado
    
    Raises:
        HTTPException 401: Token inválido o usuario no encontrado
    """
    token = credentials.credentials
    
    # Decodificar token
    payload = decode_access_token(token)
    
    # Extraer user_id del payload
    user_id: str = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido: falta user_id",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Buscar usuario en base de datos
    user = db.query(User).filter(User.id == user_id).first()
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user


async def require_admin(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Verificar que el usuario actual sea Admin.
    
    Args:
        current_user: Usuario autenticado actual
    
    Returns:
        Usuario autenticado (si es Admin)
    
    Raises:
        HTTPException 403: Usuario no es Admin
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requieren permisos de administrador"
        )
    
    return current_user


async def require_operator_or_admin(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Verificar que el usuario actual sea Operador o Admin.
    
    Args:
        current_user: Usuario autenticado actual
    
    Returns:
        Usuario autenticado (si es Operador o Admin)
    
    Raises:
        HTTPException 403: Usuario no tiene permisos
    """
    if current_user.role not in (UserRole.ADMIN, UserRole.OPERATOR):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requieren permisos de operador o administrador"
        )
    
    return current_user
