"""
Endpoints de gestión de configuración global.

Este módulo define los endpoints para:
- Obtener configuración global
- Actualizar configuración global
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User, UserRole
from app.models.config import GlobalConfig
from app.schemas import GlobalConfigUpdate, GlobalConfigResponse
from app.services.config import ConfigService
from app.services.audit import AuditService

router = APIRouter()


@router.get("/global", response_model=GlobalConfigResponse)
def get_global_config(
    account_id: str = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtener configuración global de la cuenta.
    
    Si no existe configuración, retorna valores por defecto en lugar de 404.
    
    - Admin: puede ver configuración de cualquier cuenta (debe especificar account_id)
    - Operador: solo puede ver configuración de su cuenta
    
    Args:
        account_id: ID de la cuenta (requerido para Admin, ignorado para Operador)
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Returns:
        GlobalConfigResponse con la configuración global o valores por defecto
    
    Raises:
        HTTPException 400: account_id requerido para Admin
        HTTPException 403: Sin permisos
    """
    # Determinar qué cuenta usar
    if current_user.role == UserRole.ADMIN:
        if not account_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="account_id requerido para administradores"
            )
        target_account_id = account_id
    else:
        # Operador o ReadOnly: usar su cuenta asignada
        if not current_user.account_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Usuario sin cuenta asignada"
            )
        target_account_id = str(current_user.account_id)
    
    config = db.query(GlobalConfig).filter(GlobalConfig.account_id == target_account_id).first()
    
    if not config:
        # Retornar configuración con valores por defecto en lugar de 404
        # Esto evita errores en consola del navegador
        from datetime import datetime
        return GlobalConfigResponse(
            id=None,  # Indica que no existe en BD
            account_id=target_account_id,
            corporate_queue_name="",
            search_targets=None,
            pending_task_polling_minutes=5,
            bootstrap_domains="",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
    
    return config


@router.put("/global", response_model=GlobalConfigResponse)
def update_global_config(
    config_data: GlobalConfigUpdate,
    account_id: str = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Actualizar configuración global de la cuenta.
    
    - Admin: puede actualizar configuración de cualquier cuenta (debe especificar account_id)
    - Operador: solo puede actualizar configuración de su cuenta
    
    Args:
        config_data: Datos de configuración a actualizar
        account_id: ID de la cuenta (requerido para Admin, ignorado para Operador)
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Returns:
        GlobalConfigResponse con la configuración actualizada
    
    Raises:
        HTTPException 400: account_id requerido para Admin
        HTTPException 403: Sin permisos
    """
    # Determinar qué cuenta usar
    if current_user.role == UserRole.ADMIN:
        if not account_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="account_id requerido para administradores"
            )
        target_account_id = account_id
    else:
        # Operador o ReadOnly: usar su cuenta asignada
        if not current_user.account_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Usuario sin cuenta asignada"
            )
        target_account_id = str(current_user.account_id)
    
    config_service = ConfigService()
    
    # Obtener configuración actual
    config = db.query(GlobalConfig).filter(GlobalConfig.account_id == target_account_id).first()
    
    if not config:
        # Crear configuración si no existe
        config = config_service.create_global_config(
            db=db,
            account_id=target_account_id,
            **config_data.model_dump(exclude_unset=True)
        )
    else:
        # Actualizar configuración existente
        old_values = {
            "corporate_queue_name": config.corporate_queue_name,
            "search_targets": config.search_targets,
            "pending_task_polling_minutes": config.pending_task_polling_minutes,
            "bootstrap_domains": config.bootstrap_domains
        }
        
        config = config_service.update_global_config(
            db=db,
            account_id=target_account_id,
            **config_data.model_dump(exclude_unset=True)
        )
        
        # Registrar en auditoría
        audit_service = AuditService()
        audit_service.log_config_change(
            db=db,
            user_id=current_user.id,
            workstation_id=None,
            account_id=target_account_id,
            config_level="global",
            old_values=old_values,
            new_values=config_data.model_dump(exclude_unset=True)
        )
    
    return config
