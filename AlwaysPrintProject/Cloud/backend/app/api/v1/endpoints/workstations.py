"""
Endpoints de gestión de workstations.

Este módulo define los endpoints para:
- Listado de workstations con filtros
- Actualización de workstations
- Gestión de configuración específica
- Estadísticas
"""

from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User, UserRole
from app.models.workstation import Workstation
from app.schemas import (
    WorkstationResponse,
    WorkstationDetailResponse,
    WorkstationUpdate,
    WorkstationStatusUpdate,
    WorkstationListResponse,
    WorkstationStatsResponse,
    WorkstationConfigUpdate,
    WorkstationConfigResponse,
    EffectiveConfigResponse,
)
from app.services.workstation import WorkstationService
from app.services.config import ConfigService
from app.services.audit import AuditService

router = APIRouter()


@router.get("/", response_model=WorkstationListResponse)
async def list_workstations(
    page: int = Query(1, ge=1, description="Número de página"),
    page_size: int = Query(50, ge=1, le=100, description="Tamaño de página"),
    vlan_id: Optional[UUID] = Query(None, description="Filtrar por VLAN"),
    is_online: Optional[bool] = Query(None, description="Filtrar por estado online"),
    contingency_active: Optional[bool] = Query(None, description="Filtrar por contingencia activa"),
    search: Optional[str] = Query(None, description="Buscar por IP o hostname"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Listar workstations con filtros.
    
    - Admin: puede ver workstations de todas las cuentas
    - Operador: solo puede ver workstations de su cuenta
    
    Args:
        page: Número de página
        page_size: Tamaño de página (1-100)
        vlan_id: Filtrar por VLAN opcional
        is_online: Filtrar por estado online opcional
        contingency_active: Filtrar por contingencia activa opcional
        search: Buscar por IP o hostname opcional
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Returns:
        WorkstationListResponse con lista paginada de workstations
    """
    workstation_service = WorkstationService()
    
    # Determinar account_id según rol
    account_id = None
    if current_user.role == UserRole.OPERATOR:
        if not current_user.account_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operador sin cuenta asignada"
            )
        account_id = current_user.account_id
    
    # Obtener workstations con filtros
    result = await workstation_service.get_workstations_by_account(
        db=db,
        account_id=account_id,
        vlan_id=vlan_id,
        is_online=is_online,
        contingency_active=contingency_active,
        search=search,
        page=page,
        page_size=page_size
    )
    
    return result


@router.get("/stats", response_model=WorkstationStatsResponse)
async def get_workstation_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtener estadísticas de workstations.
    
    - Admin: estadísticas de todas las cuentas
    - Operador: estadísticas de su cuenta
    
    Args:
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Returns:
        WorkstationStatsResponse con estadísticas
    """
    workstation_service = WorkstationService()
    
    # Determinar account_id según rol
    account_id = None
    if current_user.role == UserRole.OPERATOR:
        if not current_user.account_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operador sin cuenta asignada"
            )
        account_id = current_user.account_id
    
    # Obtener estadísticas
    total = await workstation_service.get_total_count(db, account_id)
    online = await workstation_service.get_online_count(db, account_id)
    contingency = await workstation_service.get_contingency_count(db, account_id)
    
    return WorkstationStatsResponse(
        total=total,
        online=online,
        offline=total - online,
        contingency_active=contingency
    )


@router.get("/{workstation_id}", response_model=WorkstationDetailResponse)
async def get_workstation(
    workstation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtener detalles de una workstation.
    
    - Admin: puede ver cualquier workstation
    - Operador: solo puede ver workstations de su cuenta
    
    Args:
        workstation_id: ID de la workstation
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Returns:
        WorkstationDetailResponse con detalles completos
    
    Raises:
        HTTPException 403: Sin permisos
        HTTPException 404: Workstation no encontrada
    """
    workstation_service = WorkstationService()
    
    workstation = await workstation_service.get_workstation_by_id(db, workstation_id)
    
    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workstation con ID {workstation_id} no encontrada"
        )
    
    # Verificar permisos
    if current_user.role == UserRole.OPERATOR:
        if workstation.account_id != current_user.account_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para ver esta workstation"
            )
    
    # Obtener licencia activa
    active_license = await workstation_service.get_active_license(db, workstation_id)
    
    # Crear respuesta detallada
    response = WorkstationDetailResponse(
        **workstation.__dict__,
        active_license=active_license
    )
    
    return response


@router.put("/{workstation_id}", response_model=WorkstationResponse)
async def update_workstation(
    workstation_id: UUID,
    workstation_data: WorkstationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Actualizar información de una workstation.
    
    - Admin: puede actualizar cualquier workstation
    - Operador: solo puede actualizar workstations de su cuenta
    
    Args:
        workstation_id: ID de la workstation
        workstation_data: Datos a actualizar
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Returns:
        WorkstationResponse con la workstation actualizada
    
    Raises:
        HTTPException 403: Sin permisos
        HTTPException 404: Workstation no encontrada
    """
    workstation_service = WorkstationService()
    
    workstation = await workstation_service.get_workstation_by_id(db, workstation_id)
    
    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workstation con ID {workstation_id} no encontrada"
        )
    
    # Verificar permisos
    if current_user.role == UserRole.OPERATOR:
        if workstation.account_id != current_user.account_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para actualizar esta workstation"
            )
    
    # Guardar valores anteriores para auditoría
    old_values = {
        "hostname": workstation.hostname,
        "os_serial": workstation.os_serial,
        "current_user": workstation.current_user,
        "vlan_id": str(workstation.vlan_id) if workstation.vlan_id else None
    }
    
    # Actualizar campos
    update_data = workstation_data.model_dump(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(workstation, field, value)
    
    db.commit()
    db.refresh(workstation)
    
    # Registrar en auditoría
    audit_service = AuditService()
    await audit_service.log_update(
        db=db,
        user_id=current_user.id,
        workstation_id=workstation.id,
        account_id=workstation.account_id,
        entity_type="workstation",
        entity_id=workstation.id,
        old_values=old_values,
        new_values=update_data
    )
    
    return workstation


# === ENDPOINTS DE CONFIGURACIÓN ===

@router.get("/{workstation_id}/config", response_model=EffectiveConfigResponse)
async def get_workstation_config(
    workstation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtener configuración efectiva de una workstation.
    
    Resuelve la jerarquía: WorkstationConfig > VLANConfig > GlobalConfig
    
    Args:
        workstation_id: ID de la workstation
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Returns:
        EffectiveConfigResponse con configuración resuelta
    
    Raises:
        HTTPException 403: Sin permisos
        HTTPException 404: Workstation no encontrada
    """
    workstation_service = WorkstationService()
    config_service = ConfigService()
    
    workstation = await workstation_service.get_workstation_by_id(db, workstation_id)
    
    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workstation con ID {workstation_id} no encontrada"
        )
    
    # Verificar permisos
    if current_user.role == UserRole.OPERATOR:
        if workstation.account_id != current_user.account_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para ver la configuración de esta workstation"
            )
    
    # Obtener configuración efectiva
    config = await config_service.get_effective_config(db, workstation_id)
    
    return config


@router.put("/{workstation_id}/config", response_model=WorkstationConfigResponse)
async def update_workstation_config(
    workstation_id: UUID,
    config_data: WorkstationConfigUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Actualizar configuración específica de una workstation.
    
    Crea o actualiza un override de configuración para esta workstation.
    Los campos NULL heredan de VLANConfig o GlobalConfig.
    
    Args:
        workstation_id: ID de la workstation
        config_data: Datos de configuración a actualizar
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Returns:
        WorkstationConfigResponse con la configuración actualizada
    
    Raises:
        HTTPException 403: Sin permisos
        HTTPException 404: Workstation no encontrada
    """
    workstation_service = WorkstationService()
    config_service = ConfigService()
    
    workstation = await workstation_service.get_workstation_by_id(db, workstation_id)
    
    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workstation con ID {workstation_id} no encontrada"
        )
    
    # Verificar permisos
    if current_user.role == UserRole.OPERATOR:
        if workstation.account_id != current_user.account_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para actualizar la configuración de esta workstation"
            )
    
    # Actualizar configuración
    config = await config_service.create_or_update_workstation_config(
        db=db,
        workstation_id=workstation_id,
        **config_data.model_dump(exclude_unset=True)
    )
    
    # Registrar en auditoría
    audit_service = AuditService()
    await audit_service.log_config_change(
        db=db,
        user_id=current_user.id,
        workstation_id=workstation_id,
        account_id=workstation.account_id,
        config_level="workstation",
        old_values={},
        new_values=config_data.model_dump(exclude_unset=True)
    )
    
    return config


@router.delete("/{workstation_id}/config", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workstation_config(
    workstation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Eliminar override de configuración de una workstation.
    
    Después de eliminar, la workstation heredará configuración de VLAN o Global.
    
    Args:
        workstation_id: ID de la workstation
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Raises:
        HTTPException 403: Sin permisos
        HTTPException 404: Workstation no encontrada
    """
    workstation_service = WorkstationService()
    config_service = ConfigService()
    
    workstation = await workstation_service.get_workstation_by_id(db, workstation_id)
    
    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workstation con ID {workstation_id} no encontrada"
        )
    
    # Verificar permisos
    if current_user.role == UserRole.OPERATOR:
        if workstation.account_id != current_user.account_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para eliminar la configuración de esta workstation"
            )
    
    # Eliminar configuración
    await config_service.delete_workstation_config(db, workstation_id)
    
    # Registrar en auditoría
    audit_service = AuditService()
    await audit_service.log_config_change(
        db=db,
        user_id=current_user.id,
        workstation_id=workstation_id,
        account_id=workstation.account_id,
        config_level="workstation",
        old_values={"action": "config_deleted"},
        new_values={}
    )
    
    return None
