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
)
from app.services.workstation import WorkstationService
from app.services.config import ConfigService
from app.services.audit import AuditService

router = APIRouter()


@router.get("/", response_model=WorkstationListResponse)
def list_workstations(
    page: int = Query(1, ge=1, description="Número de página"),
    page_size: int = Query(50, ge=1, le=100, description="Tamaño de página"),
    vlan_id: Optional[UUID] = Query(None, description="Filtrar por VLAN"),
    account_id: Optional[UUID] = Query(None, description="Filtrar por cuenta"),
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
        account_id: Filtrar por cuenta opcional
        is_online: Filtrar por estado online opcional
        contingency_active: Filtrar por contingencia activa opcional
        search: Buscar por IP o hostname opcional
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Returns:
        WorkstationListResponse con lista paginada de workstations
    """
    from sqlalchemy.orm import joinedload
    
    query = db.query(Workstation).options(joinedload(Workstation.account))
    
    # Operadores solo pueden ver workstations de su cuenta
    if current_user.role == UserRole.OPERATOR:
        if not current_user.account_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operador sin cuenta asignada"
            )
        query = query.filter(Workstation.account_id == current_user.account_id)
    
    # Filtrar por cuenta si se proporciona (solo Admin)
    if account_id:
        if current_user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo Admin puede filtrar por cuenta"
            )
        query = query.filter(Workstation.account_id == account_id)
    
    # Filtrar por VLAN si se proporciona
    if vlan_id:
        query = query.filter(Workstation.vlan_id == vlan_id)
    
    # Filtrar por estado online si se proporciona
    if is_online is not None:
        query = query.filter(Workstation.is_online == is_online)
    
    # Filtrar por contingencia activa si se proporciona
    if contingency_active is not None:
        query = query.filter(Workstation.contingency_active == contingency_active)
    
    # Buscar por IP o hostname si se proporciona
    if search:
        query = query.filter(
            (Workstation.ip_private.ilike(f"%{search}%")) |
            (Workstation.hostname.ilike(f"%{search}%"))
        )
    
    # Contar total
    total = query.count()
    
    # Paginar
    offset = (page - 1) * page_size
    workstations = query.offset(offset).limit(page_size).all()
    
    return WorkstationListResponse(
        items=workstations,
        total=total,
        skip=offset,
        limit=page_size
    )


@router.get("/stats", response_model=WorkstationStatsResponse)
def get_workstation_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtener estadísticas de workstations.
    
    - Admin: estadísticas de todas las cuentas + desglose por cuenta
    - Operador: estadísticas de su cuenta
    
    Args:
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Returns:
        WorkstationStatsResponse con estadísticas
    """
    try:
        workstation_service = WorkstationService()
        
        # Determinar account_id según rol
        account_id = None
        if current_user.role == UserRole.OPERATOR:
            if not current_user.account_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Operador sin cuenta asignada"
                )
            account_id = str(current_user.account_id) if current_user.account_id else None
        
        # Obtener estadísticas generales
        total = workstation_service.get_total_count(db, account_id)
        online = workstation_service.get_online_count(db, account_id)
        contingency = workstation_service.get_contingency_count(db, account_id)
        
        # Preparar respuesta base
        response = WorkstationStatsResponse(
            total=total,
            online=online,
            offline=total - online,
            contingency_active=contingency
        )
        
        # Si es admin, agregar estadísticas por cuenta
        if current_user.role == UserRole.ADMIN:
            from app.models.account import Account
            import uuid
            
            # Obtener todas las cuentas
            accounts = db.query(Account).all()
            
            by_account = {}
            for account in accounts:
                try:
                    # Convertir account.id a string de manera segura
                    # El tipo GUID puede devolver UUID o str dependiendo del dialecto
                    if isinstance(account.id, uuid.UUID):
                        account_id_str = str(account.id)
                    elif isinstance(account.id, str):
                        account_id_str = account.id
                    else:
                        account_id_str = str(account.id)
                    
                    account_total = workstation_service.get_total_count(db, account_id_str)
                    account_online = workstation_service.get_online_count(db, account_id_str)
                    account_contingency = workstation_service.get_contingency_count(db, account_id_str)
                    
                    by_account[account_id_str] = {
                        "name": account.name,
                        "total": account_total,
                        "online": account_online,
                        "offline": account_total - account_online,
                        "contingency": account_contingency
                    }
                except Exception as e:
                    # Si falla para una cuenta específica, continuar con las demás
                    print(f"Error al obtener estadísticas para cuenta {account.id}: {e}")
                    import traceback
                    traceback.print_exc()
                    continue
            
            response.by_account = by_account
        
        return response
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # Log el error y devolver un error 500 con detalles
        print(f"Error en get_workstation_stats: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al obtener estadísticas: {str(e)}"
        )


@router.get("/{workstation_id}", response_model=WorkstationDetailResponse)
def get_workstation(
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
    from sqlalchemy.orm import joinedload
    
    workstation = db.query(Workstation).options(joinedload(Workstation.account)).filter(Workstation.id == workstation_id).first()
    
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
    
    return workstation


@router.put("/{workstation_id}", response_model=WorkstationResponse)
def update_workstation(
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
    workstation = db.query(Workstation).filter(Workstation.id == workstation_id).first()
    
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
        "account_id": str(workstation.account_id) if workstation.account_id else None
    }
    
    # Actualizar campos
    update_data = workstation_data.model_dump(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(workstation, field, value)
    
    db.commit()
    db.refresh(workstation)
    
    # Registrar en auditoría
    audit_service = AuditService()
    audit_service.log_update(
        db=db,
        entity_type="workstation",
        entity_id=str(workstation.id),
        user_id=str(current_user.id),
        account_id=str(workstation.account_id) if workstation.account_id else None,
        old_data=old_values,
        new_data=update_data
    )
    
    return workstation


# === ENDPOINTS DE CONFIGURACIÓN ===


@router.put("/{workstation_id}/config", response_model=WorkstationConfigResponse)
def update_workstation_config(
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
    
    workstation = workstation_service.get_workstation_by_id(db, workstation_id)
    
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
    config = config_service.create_or_update_workstation_config(
        db=db,
        workstation_id=workstation_id,
        **config_data.model_dump(exclude_unset=True)
    )
    
    # Registrar en auditoría
    audit_service = AuditService()
    audit_service.log_config_change(
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
def delete_workstation_config(
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
    
    workstation = workstation_service.get_workstation_by_id(db, workstation_id)
    
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
    config_service.delete_workstation_config(db, workstation_id)
    
    # Registrar en auditoría
    audit_service = AuditService()
    audit_service.log_config_change(
        db=db,
        user_id=current_user.id,
        workstation_id=workstation_id,
        account_id=workstation.account_id,
        config_level="workstation",
        old_values={"action": "config_deleted"},
        new_values={}
    )
    
    return None
