"""
Endpoints para gestión de configuraciones de acciones administrativas.
"""

import logging
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User, UserRole
from app.models.action_config import ActionConfig
from app.schemas.action_config import (
    ActionConfigUpload,
    ActionConfigUpdate,
    ActionConfigInfo,
    ActionConfigDetail,
    ActionConfigDownloadInfo,
)
from app.services.action_config import ActionConfigService, DuplicateConfigError

logger = logging.getLogger(__name__)

router = APIRouter()


# === ENDPOINTS PARA ADMINISTRADORES ===

@router.post(
    "/organizations/{organization_id}/config",
    response_model=ActionConfigInfo,
    status_code=status.HTTP_201_CREATED,
    summary="Subir configuración de acciones",
    description="Sube un nuevo archivo de configuración de acciones para una organización"
)
def upload_action_config(
    organization_id: UUID,
    data: ActionConfigUpload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Sube una nueva configuración de acciones para una organización.
    
    - **organization_id**: ID de la organización
    - **config_json**: JSON completo del archivo .alwaysconfig
    - **is_active**: Si la configuración debe estar activa (default: True)
    
    Si is_active=True, desactiva automáticamente cualquier configuración activa previa.
    """
    # Verificar que el usuario pertenece a la organización (admins pueden gestionar cualquiera)
    if current_user.role != UserRole.ADMIN and current_user.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para gestionar configuraciones de esta organización"
        )
    
    try:
        config = ActionConfigService.create_config(
            db=db,
            organization_id=organization_id,
            data=data,
            created_by_id=current_user.id,
            storage_path=None  # TODO: Implementar almacenamiento en S3
        )
        
        return config
    except DuplicateConfigError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get(
    "/organizations/{organization_id}/config",
    response_model=ActionConfigInfo,
    summary="Obtener configuración activa",
    description="Obtiene la configuración de acciones activa de una organización"
)
def get_active_action_config(
    organization_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Obtiene la configuración de acciones activa de una organización.
    
    Retorna 404 si no hay configuración activa.
    """
    # Verificar que el usuario pertenece a la organización (admins pueden acceder a cualquiera)
    if current_user.role != UserRole.ADMIN and current_user.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para acceder a configuraciones de esta organización"
        )
    
    config = ActionConfigService.get_active_config(db, organization_id)
    
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hay configuración activa para esta organización"
        )
    
    return config


@router.get(
    "/organizations/{organization_id}/configs",
    response_model=List[ActionConfigInfo],
    summary="Listar todas las configuraciones",
    description="Lista todas las configuraciones de acciones de una organización"
)
def list_action_configs(
    organization_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Lista todas las configuraciones de acciones de una organización.
    
    Incluye tanto activas como inactivas, ordenadas por fecha de creación descendente.
    """
    # Verificar que el usuario pertenece a la organización (admins pueden acceder a cualquiera)
    if current_user.role != UserRole.ADMIN and current_user.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para acceder a configuraciones de esta organización"
        )
    
    configs = ActionConfigService.get_all_configs(db, organization_id)
    return configs


@router.get(
    "/organizations/{organization_id}/config/{config_id}",
    response_model=ActionConfigDetail,
    summary="Obtener configuración por ID",
    description="Obtiene una configuración específica con todos sus detalles"
)
def get_action_config_detail(
    organization_id: UUID,
    config_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Obtiene una configuración específica con todos sus detalles incluyendo el JSON completo.
    """
    # Verificar que el usuario pertenece a la organización (admins pueden acceder a cualquiera)
    if current_user.role != UserRole.ADMIN and current_user.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para acceder a configuraciones de esta organización"
        )
    
    config = ActionConfigService.get_config_by_id(db, config_id, organization_id)
    
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Configuración no encontrada"
        )
    
    return config


@router.patch(
    "/organizations/{organization_id}/config/{config_id}",
    response_model=ActionConfigInfo,
    summary="Actualizar configuración",
    description="Actualiza una configuración existente (activar/desactivar)"
)
def update_action_config(
    organization_id: UUID,
    config_id: UUID,
    data: ActionConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Actualiza una configuración existente.
    
    Actualmente solo permite activar/desactivar la propagación.
    Si se activa una configuración, las demás se desactivan automáticamente.
    """
    # Verificar que el usuario pertenece a la organización (admins pueden gestionar cualquiera)
    if current_user.role != UserRole.ADMIN and current_user.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para gestionar configuraciones de esta organización"
        )
    
    config = ActionConfigService.get_config_by_id(db, config_id, organization_id)
    
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Configuración no encontrada"
        )
    
    updated_config = ActionConfigService.update_config(db, config, data)
    return updated_config


@router.delete(
    "/organizations/{organization_id}/config/{config_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar configuración",
    description="Elimina una configuración de acciones"
)
def delete_action_config(
    organization_id: UUID,
    config_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Elimina una configuración de acciones.
    
    Esta operación es irreversible.
    """
    # Verificar que el usuario pertenece a la organización (admins pueden gestionar cualquiera)
    if current_user.role != UserRole.ADMIN and current_user.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para gestionar configuraciones de esta organización"
        )
    
    config = ActionConfigService.get_config_by_id(db, config_id, organization_id)
    
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Configuración no encontrada"
        )
    
    ActionConfigService.delete_config(db, config)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# === ENDPOINTS PARA WORKSTATIONS ===

@router.get(
    "/workstations/{workstation_id}/config/info",
    response_model=ActionConfigDownloadInfo,
    summary="Info de configuración para workstation",
    description="Obtiene información de la configuración activa para una workstation"
)
def get_workstation_config_info(
    workstation_id: str,
    db: Session = Depends(get_db)
):
    """
    Obtiene información de la configuración activa para una workstation.
    
    Este endpoint NO requiere autenticación (usa workstation_id como identificación).
    Retorna 404 si no hay configuración activa.
    
    La workstation usa esta información para verificar si necesita descargar
    una nueva configuración comparando el hash.
    """
    # Obtener workstation
    from app.models.workstation import Workstation
    
    logger.info(f"[ACTION_CONFIG] Buscando workstation con id={workstation_id}")
    
    workstation = db.query(Workstation).filter(
        Workstation.id == workstation_id
    ).first()
    
    if not workstation:
        logger.warning(f"[ACTION_CONFIG] Workstation no encontrada: id={workstation_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workstation no encontrada"
        )
    
    logger.info(
        f"[ACTION_CONFIG] Workstation encontrada: id={workstation.id}, "
        f"organization_id={workstation.organization_id}"
    )
    
    # Obtener configuración activa de la organización
    config = ActionConfigService.get_active_config(db, workstation.organization_id)
    
    if not config:
        # Diagnóstico adicional: verificar si hay ALGUNA config para esta org
        from sqlalchemy import func
        total_configs = db.query(func.count(ActionConfig.id)).filter(
            ActionConfig.organization_id == workstation.organization_id
        ).scalar()
        active_configs = db.query(func.count(ActionConfig.id)).filter(
            ActionConfig.organization_id == workstation.organization_id,
            ActionConfig.is_active == True
        ).scalar()
        
        logger.warning(
            f"[ACTION_CONFIG] No hay configuración activa para organization_id={workstation.organization_id}. "
            f"Total configs en org: {total_configs}, activas: {active_configs}"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No hay configuración activa. "
                f"org_id={workstation.organization_id}, "
                f"configs_total={total_configs}, configs_activas={active_configs}"
            )
        )
    
    logger.info(
        f"[ACTION_CONFIG] Configuración activa encontrada: id={config.id}, "
        f"name={config.name}, hash={config.config_hash}"
    )
    
    return ActionConfigDownloadInfo(
        hash=config.config_hash,
        download_url=f"/api/v1/workstations/{workstation_id}/config/download",
        name=config.name,
        version=config.version
    )


@router.get(
    "/workstations/{workstation_id}/config/download",
    summary="Descargar configuración",
    description="Descarga el JSON completo de la configuración activa"
)
def download_workstation_config(
    workstation_id: str,
    db: Session = Depends(get_db)
):
    """
    Descarga el JSON completo de la configuración activa para una workstation.
    
    Este endpoint NO requiere autenticación (usa workstation_id como identificación).
    Retorna el JSON crudo del archivo .alwaysconfig.
    """
    # Obtener workstation
    from app.models.workstation import Workstation
    workstation = db.query(Workstation).filter(
        Workstation.id == workstation_id
    ).first()
    
    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workstation no encontrada"
        )
    
    # Obtener configuración activa de la organización
    config = ActionConfigService.get_active_config(db, workstation.organization_id)
    
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hay configuración activa"
        )
    
    # Retornar JSON crudo
    return Response(
        content=config.config_json,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{config.name}.alwaysconfig"',
            "X-Config-Hash": config.config_hash,
            "X-Config-Version": config.version
        }
    )
