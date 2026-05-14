"""
Endpoints de gestión de VLANs.

Este módulo define los endpoints para:
- CRUD de VLANs
- Gestión de configuración de VLAN
- Listado de workstations por VLAN
"""

from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.utils import get_client_ip
from app.models.user import User, UserRole
from app.models.vlan import VLAN
from app.schemas import (
    VLANCreate,
    VLANUpdate,
    VLANResponse,
    VLANDetailResponse,
    VLANListResponse,
    VLANConfigUpdate,
    VLANConfigResponse,
    WorkstationListResponse,
)
from app.services.config import ConfigService
from app.services.workstation import WorkstationService
from app.services.audit import AuditService

router = APIRouter()


@router.get("/", response_model=VLANListResponse)
def list_vlans(
    account_id: Optional[str] = Query(None, description="Filtrar por ID de cuenta (solo Admin)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Listar VLANs.
    
    - Admin: puede ver todas las VLANs o filtrar por account_id
    - Operador: solo puede ver VLANs de su cuenta
    
    Args:
        account_id: ID de cuenta para filtrar (opcional, solo Admin)
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Returns:
        VLANListResponse con lista de VLANs
    """
    if current_user.role == UserRole.OPERATOR and not current_user.account_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operador sin cuenta asignada")
    
    query = db.query(VLAN)
    
    # Aplicar filtros según rol
    if current_user.role == UserRole.OPERATOR:
        # Operadores solo ven su cuenta
        query = query.filter(VLAN.account_id == current_user.account_id)
    elif current_user.role == UserRole.ADMIN and account_id:
        # Admins pueden filtrar por cuenta específica
        query = query.filter(VLAN.account_id == account_id)
    # Si es Admin sin filtro, ve todas las VLANs
    
    vlans = query.all()
    return VLANListResponse(total=len(vlans), vlans=vlans)


@router.post("/", response_model=VLANResponse, status_code=status.HTTP_201_CREATED)
def create_vlan(
    request: Request,
    vlan_data: VLANCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Crear una nueva VLAN."""
    # Determinar account_id
    if current_user.role == UserRole.OPERATOR:
        # Operadores solo pueden crear VLANs en su propia cuenta
        account_id = current_user.account_id
        if not account_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operador sin cuenta asignada")
    else:
        # Admins deben especificar el account_id
        account_id = vlan_data.account_id
        if not account_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="account_id requerido para administradores")
    
    vlan = VLAN(
        account_id=account_id,
        name=vlan_data.name,
        description=vlan_data.description,
        cidr_ranges=vlan_data.cidr_ranges
    )
    db.add(vlan)
    db.commit()
    db.refresh(vlan)
    
    audit_service = AuditService()
    audit_service.log_create(
        db=db,
        entity_type="vlan",
        entity_id=str(vlan.id),
        user_id=str(current_user.id),
        account_id=str(vlan.account_id),
        entity_data={"name": vlan.name},
        ip_address=get_client_ip(request)
    )
    
    return vlan


@router.get("/{vlan_id}", response_model=VLANDetailResponse)
def get_vlan(
    vlan_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Obtener detalles de una VLAN."""
    vlan = db.query(VLAN).filter(VLAN.id == vlan_id).first()
    if not vlan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VLAN no encontrada")
    
    if current_user.role == UserRole.OPERATOR and vlan.account_id != current_user.account_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos")
    
    workstation_count = len(vlan.workstations)
    return VLANDetailResponse(**vlan.__dict__, workstation_count=workstation_count)


@router.put("/{vlan_id}", response_model=VLANResponse)
def update_vlan(
    request: Request,
    vlan_id: UUID,
    vlan_data: VLANUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Actualizar una VLAN."""
    vlan = db.query(VLAN).filter(VLAN.id == vlan_id).first()
    if not vlan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VLAN no encontrada")
    
    if current_user.role == UserRole.OPERATOR and vlan.account_id != current_user.account_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos")
    
    old_values = {"name": vlan.name, "cidr_ranges": vlan.cidr_ranges}
    update_data = vlan_data.model_dump(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(vlan, field, value)
    
    db.commit()
    db.refresh(vlan)
    
    audit_service = AuditService()
    audit_service.log_update(
        db=db,
        entity_type="vlan",
        entity_id=str(vlan.id),
        user_id=str(current_user.id),
        account_id=str(vlan.account_id),
        old_data=old_values,
        new_data=update_data,
        ip_address=get_client_ip(request)
    )
    
    return vlan


@router.delete("/{vlan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_vlan(
    request: Request,
    vlan_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Eliminar una VLAN."""
    vlan = db.query(VLAN).filter(VLAN.id == vlan_id).first()
    if not vlan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VLAN no encontrada")
    
    if current_user.role == UserRole.OPERATOR and vlan.account_id != current_user.account_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos")
    
    db.delete(vlan)
    db.commit()
    
    audit_service = AuditService()
    audit_service.log_delete(
        db=db,
        entity_type="vlan",
        entity_id=str(vlan_id),
        user_id=str(current_user.id),
        account_id=str(vlan.account_id),
        entity_data={"name": vlan.name},
        ip_address=get_client_ip(request)
    )
    
    return None


@router.get("/{vlan_id}/workstations", response_model=WorkstationListResponse)
def list_vlan_workstations(
    vlan_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Listar workstations de una VLAN."""
    vlan = db.query(VLAN).filter(VLAN.id == vlan_id).first()
    if not vlan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VLAN no encontrada")
    
    if current_user.role == UserRole.OPERATOR and vlan.account_id != current_user.account_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos")
    
    workstation_service = WorkstationService()
    return workstation_service.get_workstations_by_vlan(db, vlan_id, page, page_size)


@router.get("/{vlan_id}/config", response_model=VLANConfigResponse)
def get_vlan_config(
    vlan_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Obtener configuración de una VLAN."""
    vlan = db.query(VLAN).filter(VLAN.id == vlan_id).first()
    if not vlan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VLAN no encontrada")
    
    if current_user.role == UserRole.OPERATOR and vlan.account_id != current_user.account_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos")
    
    return vlan.vlan_config if vlan.vlan_config else VLANConfigResponse(vlan_id=vlan_id)


@router.put("/{vlan_id}/config", response_model=VLANConfigResponse)
def update_vlan_config(
    request: Request,
    vlan_id: UUID,
    config_data: VLANConfigUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Actualizar configuración de una VLAN."""
    vlan = db.query(VLAN).filter(VLAN.id == vlan_id).first()
    if not vlan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VLAN no encontrada")
    
    if current_user.role == UserRole.OPERATOR and vlan.account_id != current_user.account_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos")
    
    config_service = ConfigService()
    config = config_service.create_or_update_vlan_config(
        db, vlan_id, **config_data.model_dump(exclude_unset=True)
    )
    
    audit_service = AuditService()
    audit_service.log_config_change(
        db=db,
        entity_type="vlan_config",
        entity_id=str(vlan_id),
        user_id=str(current_user.id),
        account_id=str(vlan.account_id),
        old_config={},
        new_config=config_data.model_dump(exclude_unset=True),
        ip_address=get_client_ip(request)
    )
    
    return config


@router.delete("/{vlan_id}/config", status_code=status.HTTP_204_NO_CONTENT)
def delete_vlan_config(
    request: Request,
    vlan_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Eliminar override de configuración de una VLAN."""
    vlan = db.query(VLAN).filter(VLAN.id == vlan_id).first()
    if not vlan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VLAN no encontrada")
    
    if current_user.role == UserRole.OPERATOR and vlan.account_id != current_user.account_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos")
    
    config_service = ConfigService()
    config_service.delete_vlan_config(db, vlan_id)
    
    audit_service = AuditService()
    audit_service.log_config_change(
        db=db,
        entity_type="vlan_config",
        entity_id=str(vlan_id),
        user_id=str(current_user.id),
        account_id=str(vlan.account_id),
        old_config={"action": "config_deleted"},
        new_config={},
        ip_address=get_client_ip(request)
    )
    
    return None
