"""
Endpoints de gestión de VLANs.

Este módulo define los endpoints para:
- CRUD de VLANs
- Gestión de configuración de VLAN
- Listado de workstations por VLAN
"""

from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
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
async def list_vlans(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Listar VLANs de la cuenta del usuario."""
    if current_user.role == UserRole.OPERATOR and not current_user.account_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operador sin cuenta asignada")
    
    query = db.query(VLAN)
    if current_user.role == UserRole.OPERATOR:
        query = query.filter(VLAN.account_id == current_user.account_id)
    
    vlans = query.all()
    return VLANListResponse(total=len(vlans), vlans=vlans)


@router.post("/", response_model=VLANResponse, status_code=status.HTTP_201_CREATED)
async def create_vlan(
    vlan_data: VLANCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Crear una nueva VLAN."""
    account_id = current_user.account_id if current_user.role == UserRole.OPERATOR else None
    if not account_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="account_id requerido")
    
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
    await audit_service.log_create(db, current_user.id, "vlan", vlan.id, {"name": vlan.name})
    
    return vlan


@router.get("/{vlan_id}", response_model=VLANDetailResponse)
async def get_vlan(
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
async def update_vlan(
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
    await audit_service.log_update(db, current_user.id, "vlan", vlan.id, old_values, update_data)
    
    return vlan


@router.delete("/{vlan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vlan(
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
    await audit_service.log_delete(db, current_user.id, "vlan", vlan_id, {"name": vlan.name})
    
    return None


@router.get("/{vlan_id}/workstations", response_model=WorkstationListResponse)
async def list_vlan_workstations(
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
    return await workstation_service.get_workstations_by_vlan(db, vlan_id, page, page_size)


@router.get("/{vlan_id}/config", response_model=VLANConfigResponse)
async def get_vlan_config(
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
async def update_vlan_config(
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
    config = await config_service.create_or_update_vlan_config(
        db, vlan_id, **config_data.model_dump(exclude_unset=True)
    )
    
    audit_service = AuditService()
    await audit_service.log_config_change(
        db, current_user.id, None, vlan.account_id, "vlan", {}, config_data.model_dump(exclude_unset=True)
    )
    
    return config


@router.delete("/{vlan_id}/config", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vlan_config(
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
    await config_service.delete_vlan_config(db, vlan_id)
    
    audit_service = AuditService()
    await audit_service.log_config_change(
        db, current_user.id, None, vlan.account_id, "vlan", {"action": "config_deleted"}, {}
    )
    
    return None
