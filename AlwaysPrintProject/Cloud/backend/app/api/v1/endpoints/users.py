"""
Endpoints de gestión de usuarios.

Este módulo define los endpoints para:
- CRUD de usuarios (Admin y Operadores)
- Cambio de contraseña
"""

from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_admin
from app.models.user import User, UserRole
from app.schemas import (
    UserCreate,
    UserUpdate,
    UserPasswordUpdate,
    UserResponse,
    UserListResponse,
)
from app.services.auth import AuthService
from app.services.audit import AuditService

router = APIRouter()


@router.get("/", response_model=UserListResponse)
async def list_users(
    page: int = Query(1, ge=1, description="Número de página"),
    page_size: int = Query(50, ge=1, le=100, description="Tamaño de página"),
    role: Optional[UserRole] = Query(None, description="Filtrar por rol"),
    account_id: Optional[UUID] = Query(None, description="Filtrar por cuenta"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Listar usuarios.
    
    - Admin: puede ver todos los usuarios
    - Operador: solo puede ver usuarios de su cuenta
    
    Args:
        page: Número de página
        page_size: Tamaño de página (1-100)
        role: Filtrar por rol opcional
        account_id: Filtrar por cuenta opcional
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Returns:
        UserListResponse con lista paginada de usuarios
    """
    query = db.query(User)
    
    # Operadores solo pueden ver usuarios de su cuenta
    if current_user.role == UserRole.OPERATOR:
        if not current_user.account_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operador sin cuenta asignada"
            )
        query = query.filter(User.account_id == current_user.account_id)
    
    # Filtrar por rol si se proporciona
    if role:
        query = query.filter(User.role == role)
    
    # Filtrar por cuenta si se proporciona (solo Admin)
    if account_id:
        if current_user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo Admin puede filtrar por cuenta"
            )
        query = query.filter(User.account_id == account_id)
    
    # Contar total
    total = query.count()
    
    # Paginar
    offset = (page - 1) * page_size
    users = query.offset(offset).limit(page_size).all()
    
    return UserListResponse(
        total=total,
        page=page,
        page_size=page_size,
        users=users
    )


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Crear un nuevo usuario.
    
    - Admin: puede crear cualquier tipo de usuario
    - Operador: solo puede crear operadores de su misma cuenta
    
    Args:
        user_data: Datos del usuario a crear
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Returns:
        UserResponse con el usuario creado
    
    Raises:
        HTTPException 403: Sin permisos
        HTTPException 409: Email ya existe
    """
    auth_service = AuthService()
    
    # Verificar permisos
    if current_user.role == UserRole.OPERATOR:
        # Operadores solo pueden crear operadores de su cuenta
        if user_data.role != UserRole.OPERATOR:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operadores solo pueden crear otros operadores"
            )
        if user_data.account_id != current_user.account_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operadores solo pueden crear usuarios de su misma cuenta"
            )
    
    # Verificar que el email no existe
    existing = await auth_service.get_user_by_email(db, user_data.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe un usuario con el email '{user_data.email}'"
        )
    
    # Crear usuario
    user = await auth_service.create_user(
        db=db,
        email=user_data.email,
        password=user_data.password,
        full_name=user_data.full_name,
        role=user_data.role,
        account_id=user_data.account_id
    )
    
    # Registrar en auditoría
    audit_service = AuditService()
    await audit_service.log_create(
        db=db,
        user_id=current_user.id,
        entity_type="user",
        entity_id=user.id,
        new_values={
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role.value,
            "account_id": str(user.account_id) if user.account_id else None
        }
    )
    
    return user


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtener detalles de un usuario.
    
    - Admin: puede ver cualquier usuario
    - Operador: solo puede ver usuarios de su cuenta o a sí mismo
    
    Args:
        user_id: ID del usuario
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Returns:
        UserResponse con detalles del usuario
    
    Raises:
        HTTPException 403: Sin permisos
        HTTPException 404: Usuario no encontrado
    """
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Usuario con ID {user_id} no encontrado"
        )
    
    # Verificar permisos
    if current_user.role == UserRole.OPERATOR:
        # Operadores solo pueden ver usuarios de su cuenta o a sí mismos
        if user.id != current_user.id and user.account_id != current_user.account_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para ver este usuario"
            )
    
    return user


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    user_data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Actualizar un usuario.
    
    - Admin: puede actualizar cualquier usuario
    - Operador: solo puede actualizar su propio perfil (excepto rol y cuenta)
    
    Args:
        user_id: ID del usuario
        user_data: Datos a actualizar
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Returns:
        UserResponse con el usuario actualizado
    
    Raises:
        HTTPException 403: Sin permisos
        HTTPException 404: Usuario no encontrado
        HTTPException 409: Email ya existe
    """
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Usuario con ID {user_id} no encontrado"
        )
    
    # Verificar permisos
    if current_user.role == UserRole.OPERATOR:
        # Operadores solo pueden actualizar su propio perfil
        if user.id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operadores solo pueden actualizar su propio perfil"
            )
        # Operadores no pueden cambiar rol ni cuenta
        if user_data.role is not None or user_data.account_id is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operadores no pueden cambiar su rol o cuenta"
            )
    
    # Guardar valores anteriores para auditoría
    old_values = {
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role.value,
        "account_id": str(user.account_id) if user.account_id else None
    }
    
    # Actualizar campos
    update_data = user_data.model_dump(exclude_unset=True)
    
    # Verificar email único si se está actualizando
    if "email" in update_data and update_data["email"] != user.email:
        auth_service = AuthService()
        existing = await auth_service.get_user_by_email(db, update_data["email"])
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Ya existe un usuario con el email '{update_data['email']}'"
            )
    
    for field, value in update_data.items():
        setattr(user, field, value)
    
    db.commit()
    db.refresh(user)
    
    # Registrar en auditoría
    audit_service = AuditService()
    await audit_service.log_update(
        db=db,
        user_id=current_user.id,
        entity_type="user",
        entity_id=user.id,
        old_values=old_values,
        new_values=update_data
    )
    
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Eliminar un usuario (solo Admin).
    
    Args:
        user_id: ID del usuario
        current_user: Usuario autenticado (debe ser Admin)
        db: Sesión de base de datos
    
    Raises:
        HTTPException 404: Usuario no encontrado
        HTTPException 409: No se puede eliminar a sí mismo
    """
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Usuario con ID {user_id} no encontrado"
        )
    
    # No permitir que un admin se elimine a sí mismo
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No puedes eliminar tu propio usuario"
        )
    
    # Guardar valores para auditoría
    old_values = {
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role.value
    }
    
    # Eliminar usuario
    db.delete(user)
    db.commit()
    
    # Registrar en auditoría
    audit_service = AuditService()
    await audit_service.log_delete(
        db=db,
        user_id=current_user.id,
        entity_type="user",
        entity_id=user_id,
        old_values=old_values
    )
    
    return None


@router.put("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    user_id: UUID,
    password_data: UserPasswordUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Cambiar contraseña de un usuario.
    
    - Admin: puede cambiar la contraseña de cualquier usuario sin verificar la actual
    - Operador: solo puede cambiar su propia contraseña y debe proporcionar la actual
    
    Args:
        user_id: ID del usuario
        password_data: Contraseña actual y nueva
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Raises:
        HTTPException 403: Sin permisos
        HTTPException 404: Usuario no encontrado
        HTTPException 401: Contraseña actual incorrecta
    """
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Usuario con ID {user_id} no encontrado"
        )
    
    auth_service = AuthService()
    
    # Verificar permisos
    if current_user.role == UserRole.OPERATOR:
        # Operadores solo pueden cambiar su propia contraseña
        if user.id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operadores solo pueden cambiar su propia contraseña"
            )
        # Verificar contraseña actual
        if not auth_service.verify_password(password_data.current_password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Contraseña actual incorrecta"
            )
    
    # Actualizar contraseña
    user.hashed_password = auth_service.hash_password(password_data.new_password)
    db.commit()
    
    # Registrar en auditoría
    audit_service = AuditService()
    await audit_service.log_update(
        db=db,
        user_id=current_user.id,
        entity_type="user",
        entity_id=user.id,
        old_values={"action": "password_change"},
        new_values={"action": "password_changed"}
    )
    
    return None
