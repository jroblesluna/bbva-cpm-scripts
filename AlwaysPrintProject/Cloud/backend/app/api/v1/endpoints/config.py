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
async def get_global_config(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtener configuración global de la cuenta.
    
    - Admin: puede ver configuración de cualquier cuenta
    - Operador: solo puede ver configuración de su cuenta
    
    Args:
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Returns:
        GlobalConfigResponse con la configuración global
    
    Raises:
        HTTPException 403: Sin permisos
        HTTPException 404: Configuración no encontrada
    """
    if current_user.role == UserRole.OPERATOR and not current_user.account_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operador sin cuenta asignada"
        )
    
    account_id = current_user.account_id if current_user.role == UserRole.OPERATOR else None
    
    if not account_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="account_id requerido"
        )
    
    config = db.query(GlobalConfig).filter(GlobalConfig.account_id == account_id).first()
    
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Configuración global no encontrada para esta cuenta"
        )
    
    return config


@router.put("/global", response_model=GlobalConfigResponse)
async def update_global_config(
    config_data: GlobalConfigUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Actualizar configuración global de la cuenta.
    
    - Admin: puede actualizar configuración de cualquier cuenta
    - Operador: solo puede actualizar configuración de su cuenta
    
    Args:
        config_data: Datos de configuración a actualizar
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Returns:
        GlobalConfigResponse con la configuración actualizada
    
    Raises:
        HTTPException 403: Sin permisos
        HTTPException 404: Configuración no encontrada
    """
    if current_user.role == UserRole.OPERATOR and not current_user.account_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operador sin cuenta asignada"
        )
    
    account_id = current_user.account_id if current_user.role == UserRole.OPERATOR else None
    
    if not account_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="account_id requerido"
        )
    
    config_service = ConfigService()
    
    # Obtener configuración actual
    config = db.query(GlobalConfig).filter(GlobalConfig.account_id == account_id).first()
    
    if not config:
        # Crear configuración si no existe
        config = await config_service.create_global_config(
            db=db,
            account_id=account_id,
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
        
        config = await config_service.update_global_config(
            db=db,
            account_id=account_id,
            **config_data.model_dump(exclude_unset=True)
        )
        
        # Registrar en auditoría
        audit_service = AuditService()
        await audit_service.log_config_change(
            db=db,
            user_id=current_user.id,
            workstation_id=None,
            account_id=account_id,
            config_level="global",
            old_values=old_values,
            new_values=config_data.model_dump(exclude_unset=True)
        )
    
    return config
