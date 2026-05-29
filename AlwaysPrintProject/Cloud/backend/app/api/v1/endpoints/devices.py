"""
Endpoints de gestión de Dispositivos (impresoras).

Este módulo define los endpoints para:
- CRUD de dispositivos
- Listado de dispositivos por VLAN
- Listado de dispositivos por organización
"""

from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.utils import get_client_ip
from app.models.user import User, UserRole
from app.models.device import Device
from app.models.vlan import VLAN
from app.schemas.device import (
    DeviceCreate,
    DeviceUpdate,
    DeviceResponse,
    DeviceListResponse,
)
from app.services.audit import AuditService

router = APIRouter()


def _device_to_response(device: Device) -> DeviceResponse:
    """Convierte un modelo Device a DeviceResponse con vlan_name."""
    return DeviceResponse(
        id=device.id,
        organization_id=device.organization_id,
        vlan_id=device.vlan_id,
        name=device.name,
        ip_address=device.ip_address,
        description=device.description,
        model=device.model,
        location=device.location,
        port=device.port,
        is_active=device.is_active,
        created_at=device.created_at,
        updated_at=device.updated_at,
        vlan_name=device.vlan.name if device.vlan else None,
    )


@router.get("/", response_model=DeviceListResponse)
def list_devices(
    organization_id: Optional[str] = Query(None, description="Filtrar por ID de organización (solo Admin)"),
    vlan_id: Optional[str] = Query(None, description="Filtrar por ID de VLAN"),
    is_active: Optional[bool] = Query(None, description="Filtrar por estado activo/inactivo"),
    search: Optional[str] = Query(None, description="Buscar por nombre, IP o descripción"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Listar dispositivos.
    
    - Admin: puede ver todos los dispositivos o filtrar por organization_id
    - Operador: solo puede ver dispositivos de su organización
    """
    if current_user.role == UserRole.OPERATOR and not current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operador sin cuenta asignada")
    
    query = db.query(Device)
    
    # Aplicar filtros según rol
    if current_user.role == UserRole.OPERATOR:
        query = query.filter(Device.organization_id == current_user.organization_id)
    elif current_user.role == UserRole.ADMIN and organization_id:
        query = query.filter(Device.organization_id == organization_id)
    
    # Filtro por VLAN
    if vlan_id:
        query = query.filter(Device.vlan_id == vlan_id)
    
    # Filtro por estado
    if is_active is not None:
        query = query.filter(Device.is_active == is_active)
    
    # Búsqueda por texto
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (Device.name.ilike(search_term)) |
            (Device.ip_address.ilike(search_term)) |
            (Device.description.ilike(search_term)) |
            (Device.model.ilike(search_term)) |
            (Device.location.ilike(search_term))
        )
    
    devices = query.order_by(Device.name).all()
    device_responses = [_device_to_response(d) for d in devices]
    return DeviceListResponse(total=len(device_responses), devices=device_responses)


@router.post("/", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
def create_device(
    request: Request,
    device_data: DeviceCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Crear un nuevo dispositivo."""
    # Determinar organization_id
    if current_user.role == UserRole.OPERATOR:
        org_id = current_user.organization_id
        if not org_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operador sin cuenta asignada")
    else:
        org_id = device_data.organization_id
        if not org_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="organization_id requerido para administradores")
    
    # Validar que la VLAN pertenece a la misma organización
    if device_data.vlan_id:
        vlan = db.query(VLAN).filter(VLAN.id == device_data.vlan_id).first()
        if not vlan:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VLAN no encontrada")
        if str(vlan.organization_id) != str(org_id):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La VLAN no pertenece a la organización especificada")
    
    # Verificar unicidad de IP dentro de la organización
    existing = db.query(Device).filter(
        Device.organization_id == org_id,
        Device.ip_address == device_data.ip_address
    ).first()
    if existing:
        existing_vlan = db.query(VLAN).filter(VLAN.id == existing.vlan_id).first() if existing.vlan_id else None
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "IP_DUPLICATE",
                "ip": str(device_data.ip_address),
                "vlan_name": existing_vlan.name if existing_vlan else None,
            }
        )
    
    device = Device(
        organization_id=org_id,
        vlan_id=device_data.vlan_id,
        name=device_data.name,
        ip_address=device_data.ip_address,
        description=device_data.description,
        model=device_data.model,
        location=device_data.location,
        port=device_data.port,
        is_active=device_data.is_active,
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    
    audit_service = AuditService()
    audit_service.log_create(
        db=db,
        entity_type="device",
        entity_id=str(device.id),
        user_id=str(current_user.id),
        organization_id=str(device.organization_id),
        entity_data={"name": device.name, "ip_address": device.ip_address},
        ip_address=get_client_ip(request)
    )
    
    return _device_to_response(device)


@router.get("/{device_id}", response_model=DeviceResponse)
def get_device(
    device_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Obtener detalles de un dispositivo."""
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispositivo no encontrado")
    
    if current_user.role == UserRole.OPERATOR and device.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos")
    
    return _device_to_response(device)


@router.put("/{device_id}", response_model=DeviceResponse)
def update_device(
    request: Request,
    device_id: UUID,
    device_data: DeviceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Actualizar un dispositivo."""
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispositivo no encontrado")
    
    if current_user.role == UserRole.OPERATOR and device.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos")
    
    # Validar VLAN si se está actualizando
    if device_data.vlan_id is not None:
        vlan = db.query(VLAN).filter(VLAN.id == device_data.vlan_id).first()
        if not vlan:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VLAN no encontrada")
        if str(vlan.organization_id) != str(device.organization_id):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La VLAN no pertenece a la organización del dispositivo")
    
    # Validar unicidad de IP si se está actualizando
    if device_data.ip_address and device_data.ip_address != device.ip_address:
        existing = db.query(Device).filter(
            Device.organization_id == device.organization_id,
            Device.ip_address == device_data.ip_address,
            Device.id != device_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Ya existe un dispositivo con la IP {device_data.ip_address} en esta organización"
            )
    
    old_values = {"name": device.name, "ip_address": device.ip_address}
    update_data = device_data.model_dump(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(device, field, value)
    
    db.commit()
    db.refresh(device)
    
    audit_service = AuditService()
    audit_service.log_update(
        db=db,
        entity_type="device",
        entity_id=str(device.id),
        user_id=str(current_user.id),
        organization_id=str(device.organization_id),
        old_data=old_values,
        new_data=update_data,
        ip_address=get_client_ip(request)
    )
    
    return _device_to_response(device)


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_device(
    request: Request,
    device_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Eliminar un dispositivo."""
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispositivo no encontrado")
    
    if current_user.role == UserRole.OPERATOR and device.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos")
    
    db.delete(device)
    db.commit()
    
    audit_service = AuditService()
    audit_service.log_delete(
        db=db,
        entity_type="device",
        entity_id=str(device_id),
        user_id=str(current_user.id),
        organization_id=str(device.organization_id),
        entity_data={"name": device.name, "ip_address": device.ip_address},
        ip_address=get_client_ip(request)
    )
    
    return None


# === ENDPOINTS PARA WORKSTATIONS (autenticación por IP pública) ===

@router.get("/workstation/{workstation_id}/my-printers")
def get_my_printers(
    workstation_id: UUID,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Obtener las impresoras disponibles para una workstation (misma VLAN).
    
    Este endpoint es accesible por las workstations sin autenticación JWT.
    Retorna las impresoras activas que pertenecen a la misma VLAN que la workstation.
    Si la workstation no tiene VLAN asignada, retorna todas las impresoras activas
    de la organización.
    
    Incluye información sobre cuál es la impresora favorita (default_printer_id)
    y cuál sería la impresora por defecto (menor IP en la VLAN).
    """
    from app.models.workstation import Workstation
    
    # Buscar la workstation
    workstation = db.query(Workstation).filter(Workstation.id == workstation_id).first()
    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workstation con ID {workstation_id} no encontrada"
        )
    
    # Obtener dispositivos activos de la misma VLAN (o de la organización si no tiene VLAN)
    query = db.query(Device).filter(
        Device.organization_id == workstation.organization_id,
        Device.is_active == True
    )
    
    if workstation.vlan_id:
        query = query.filter(Device.vlan_id == workstation.vlan_id)
    
    devices = query.order_by(Device.ip_address).all()
    
    # Determinar impresora por defecto:
    # 1. default_device_id de la VLAN (configurado por admin)
    # 2. Fallback: menor IP en la VLAN
    default_device_id = None
    if workstation.vlan_id and workstation.vlan and workstation.vlan.default_device_id:
        default_device_id = str(workstation.vlan.default_device_id)
    if not default_device_id and devices:
        default_device_id = str(devices[0].id)
    
    # Construir respuesta
    printers = []
    for device in devices:
        printers.append({
            "id": str(device.id),
            "name": device.name,
            "ip_address": device.ip_address,
            "port": device.port,
            "model": device.model,
            "location": device.location,
            "is_favorite": str(device.id) == str(workstation.default_printer_id) if workstation.default_printer_id else False,
            "is_default": str(device.id) == default_device_id,
        })
    
    return {
        "workstation_id": str(workstation.id),
        "vlan_id": str(workstation.vlan_id) if workstation.vlan_id else None,
        "vlan_name": workstation.vlan.name if workstation.vlan else None,
        "favorite_printer_id": str(workstation.default_printer_id) if workstation.default_printer_id else None,
        "default_printer_id": default_device_id,
        "printers": printers,
        "total": len(printers),
    }


@router.put("/workstation/{workstation_id}/favorite-printer")
def set_favorite_printer(
    workstation_id: UUID,
    body: dict,
    db: Session = Depends(get_db)
):
    """
    Establecer la impresora favorita de contingencia para una workstation.
    
    Body JSON: { "device_id": "uuid" | null }
    - Si device_id es un UUID válido: establece esa impresora como favorita
    - Si device_id es null: elimina la favorita (usará la de menor IP por defecto)
    """
    from app.models.workstation import Workstation
    
    # Buscar la workstation
    workstation = db.query(Workstation).filter(Workstation.id == workstation_id).first()
    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workstation con ID {workstation_id} no encontrada"
        )
    
    device_id = body.get("device_id")
    
    if device_id:
        # Validar que el dispositivo existe y pertenece a la misma organización
        device = db.query(Device).filter(
            Device.id == device_id,
            Device.organization_id == workstation.organization_id,
            Device.is_active == True
        ).first()
        if not device:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dispositivo no encontrado o no pertenece a la organización"
            )
        workstation.default_printer_id = device.id
    else:
        workstation.default_printer_id = None
    
    db.commit()
    db.refresh(workstation)
    
    return {
        "success": True,
        "workstation_id": str(workstation.id),
        "favorite_printer_id": str(workstation.default_printer_id) if workstation.default_printer_id else None,
    }
