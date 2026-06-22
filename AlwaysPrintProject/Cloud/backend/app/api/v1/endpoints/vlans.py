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
    VLANGeoResponse,
    VLANConfigUpdate,
    VLANConfigResponse,
    WorkstationListResponse,
)
from app.models.organization import Organization
from app.models.workstation import Workstation
from app.services.config import ConfigService
from app.services.workstation import WorkstationService
from app.services.audit import AuditService

router = APIRouter()


@router.get("/", response_model=VLANListResponse)
def list_vlans(
    organization_id: Optional[str] = Query(None, description="Filtrar por ID de organización (solo Admin)"),
    search: Optional[str] = Query(None, description="Buscar por nombre de VLAN"),
    skip: int = Query(0, ge=0, description="Número de registros a saltar (paginación)"),
    limit: int = Query(0, ge=0, description="Número máximo de registros a retornar (0 = sin límite)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Listar VLANs con soporte de paginación y búsqueda.
    
    - Admin: puede ver todas las VLANs o filtrar por organization_id
    - Operador: solo puede ver VLANs de su cuenta
    
    Args:
        organization_id: ID de organización para filtrar (opcional, solo Admin)
        search: Término de búsqueda por nombre (opcional)
        skip: Offset para paginación (default: 0)
        limit: Límite de resultados (default: 0 = sin límite, para compatibilidad)
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Returns:
        VLANListResponse con lista de VLANs
    """
    if current_user.role == UserRole.OPERATOR and not current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operador sin cuenta asignada")
    
    query = db.query(VLAN)
    
    # Aplicar filtros según rol
    if current_user.role == UserRole.OPERATOR:
        # Operadores solo ven su cuenta
        query = query.filter(VLAN.organization_id == current_user.organization_id)
    elif current_user.role == UserRole.ADMIN and organization_id:
        # Admins pueden filtrar por organización específica
        query = query.filter(VLAN.organization_id == organization_id)
    # Si es Admin sin filtro, ve todas las VLANs
    
    # Filtro de búsqueda por nombre
    if search:
        query = query.filter(VLAN.name.ilike(f"%{search}%"))
    
    # Contar total antes de paginar
    total_count = query.count()
    
    # Ordenar
    query = query.order_by(VLAN.name)
    
    # Aplicar paginación solo si limit > 0
    if limit > 0:
        query = query.offset(skip).limit(limit)
    
    vlans = query.all()
    
    # Calcular estadísticas
    from app.models.device import Device
    from app.schemas.vlan import VLANListStats
    
    without_devices = 0
    with_config = 0
    in_contingency = 0
    
    for vlan in vlans:
        # Contar dispositivos activos en la VLAN
        device_count = db.query(Device).filter(
            Device.vlan_id == vlan.id,
            Device.is_active == True
        ).count()
        if device_count == 0:
            without_devices += 1
        
        # Verificar si tiene metadata/config
        if vlan.vlan_metadata and len(vlan.vlan_metadata) > 0:
            with_config += 1
        
        # Contingencia forzada
        if vlan.forced_contingency:
            in_contingency += 1
    
    stats = VLANListStats(
        without_devices=without_devices,
        with_config=with_config,
        in_contingency=in_contingency,
    )
    
    return VLANListResponse(total=total_count, vlans=vlans, stats=stats)


@router.post("/", response_model=VLANResponse, status_code=status.HTTP_201_CREATED)
def create_vlan(
    request: Request,
    vlan_data: VLANCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Crear una nueva VLAN."""
    # Determinar organization_id
    if current_user.role == UserRole.OPERATOR:
        # Operadores solo pueden crear VLANs en su propia cuenta
        org_id = current_user.organization_id
        if not org_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operador sin cuenta asignada")
    else:
        # Admins deben especificar el organization_id
        org_id = vlan_data.organization_id
        if not org_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="organization_id requerido para administradores")
    
    # Validar unicidad de CIDR por organización antes de crear
    workstation_service = WorkstationService()
    conflict = workstation_service.validate_cidr_uniqueness(
        db=db,
        organization_id=str(org_id),
        cidrs=vlan_data.cidr_ranges
    )
    if conflict:
        cidr_dup, vlan_name = conflict
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El CIDR {cidr_dup} ya está asignado a la VLAN '{vlan_name}' en esta organización"
        )
    
    vlan = VLAN(
        organization_id=org_id,
        name=vlan_data.name,
        description=vlan_data.description,
        cidr_ranges=vlan_data.cidr_ranges,
        vlan_metadata=vlan_data.metadata,
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
        organization_id=str(vlan.organization_id),
        entity_data={"name": vlan.name},
        ip_address=get_client_ip(request)
    )
    
    return vlan


@router.get("/geo", response_model=list[VLANGeoResponse])
def list_vlans_geo(
    organization_id: Optional[str] = Query(None, description="Filtrar por ID de organización (solo Admin)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Listar VLANs geolocalizadas con estadísticas de workstations.
    
    Retorna solo VLANs con latitude y longitude no-null, junto con
    el conteo de workstations (total, online, offline, contingencia)
    para renderizar marcadores en el mapa.
    
    - Admin: puede ver todas o filtrar por organization_id
    - Operador: solo ve VLANs de su organización (tenant isolation)
    
    Args:
        organization_id: ID de organización para filtrar (opcional, solo Admin)
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Returns:
        Lista de VLANGeoResponse con coordenadas y stats de WS
    """
    # Validar que operador tenga organización asignada
    if current_user.role == UserRole.OPERATOR and not current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operador sin cuenta asignada")
    
    # Query base: VLANs con coordenadas no-null, join con Organization para obtener nombre
    query = db.query(VLAN, Organization.name.label("organization_name")).join(
        Organization, VLAN.organization_id == Organization.id
    ).filter(
        VLAN.latitude.isnot(None),
        VLAN.longitude.isnot(None)
    )
    
    # Aplicar tenant isolation según rol
    if current_user.role == UserRole.OPERATOR:
        # Operadores solo ven su organización
        query = query.filter(VLAN.organization_id == current_user.organization_id)
    elif current_user.role == UserRole.ADMIN and organization_id:
        # Admins pueden filtrar por organización específica
        query = query.filter(VLAN.organization_id == organization_id)
    # Si es Admin sin filtro, ve todas las VLANs geolocalizadas
    
    results = query.order_by(VLAN.name).all()
    
    # Construir respuesta con estadísticas de workstations por VLAN
    geo_responses = []
    for vlan, org_name in results:
        # Contar workstations de esta VLAN
        ws_total = db.query(Workstation).filter(Workstation.vlan_id == vlan.id).count()
        ws_online = db.query(Workstation).filter(
            Workstation.vlan_id == vlan.id,
            Workstation.is_online == True
        ).count()
        ws_contingency = db.query(Workstation).filter(
            Workstation.vlan_id == vlan.id,
            Workstation.forced_contingency == True
        ).count()
        # Offline = no online y no en contingencia forzada
        ws_offline = db.query(Workstation).filter(
            Workstation.vlan_id == vlan.id,
            Workstation.is_online == False,
            Workstation.forced_contingency == False
        ).count()
        
        geo_responses.append(VLANGeoResponse(
            id=str(vlan.id),
            name=vlan.name,
            organization_id=str(vlan.organization_id),
            organization_name=org_name,
            address=vlan.address or "",
            latitude=vlan.latitude,
            longitude=vlan.longitude,
            location_image_url=vlan.location_image_url,
            ws_total=ws_total,
            ws_online=ws_online,
            ws_offline=ws_offline,
            ws_contingency=ws_contingency,
        ))
    
    return geo_responses


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
    
    if current_user.role == UserRole.OPERATOR and vlan.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos")
    
    workstation_count = len(vlan.workstations)
    # Construir dict mapeando vlan_metadata al campo del schema
    vlan_data = {
        "id": vlan.id,
        "organization_id": vlan.organization_id,
        "name": vlan.name,
        "description": vlan.description,
        "cidr_ranges": vlan.cidr_ranges,
        "forced_contingency": vlan.forced_contingency,
        "default_device_id": vlan.default_device_id,
        "vlan_metadata": vlan.vlan_metadata,
        "action_config_mandatory": vlan.action_config_mandatory,
        "created_at": vlan.created_at,
        "updated_at": vlan.updated_at,
        "workstation_count": workstation_count,
    }
    return VLANDetailResponse(**vlan_data)


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
    
    if current_user.role == UserRole.OPERATOR and vlan.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos")
    
    # Validar unicidad de CIDR si se están actualizando los cidr_ranges
    if vlan_data.cidr_ranges is not None:
        workstation_service = WorkstationService()
        conflict = workstation_service.validate_cidr_uniqueness(
            db=db,
            organization_id=str(vlan.organization_id),
            cidrs=vlan_data.cidr_ranges,
            exclude_vlan_id=str(vlan.id)
        )
        if conflict:
            cidr_dup, vlan_name = conflict
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"El CIDR {cidr_dup} ya está asignado a la VLAN '{vlan_name}' en esta organización"
            )
    
    old_values = {"name": vlan.name, "cidr_ranges": vlan.cidr_ranges}
    update_data = vlan_data.model_dump(exclude_unset=True)
    
    # Mapear 'metadata' del schema a 'vlan_metadata' del modelo ORM
    if "metadata" in update_data:
        update_data["vlan_metadata"] = update_data.pop("metadata")
    
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
        organization_id=str(vlan.organization_id),
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
    
    if current_user.role == UserRole.OPERATOR and vlan.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos")
    
    db.delete(vlan)
    db.commit()
    
    audit_service = AuditService()
    audit_service.log_delete(
        db=db,
        entity_type="vlan",
        entity_id=str(vlan_id),
        user_id=str(current_user.id),
        organization_id=str(vlan.organization_id),
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
    
    if current_user.role == UserRole.OPERATOR and vlan.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos")
    
    workstation_service = WorkstationService()
    return workstation_service.get_workstations_by_vlan(db, vlan_id, page, page_size)


@router.patch("/{vlan_id}/forced-contingency")
async def toggle_vlan_forced_contingency(
    vlan_id: UUID,
    enabled: bool = Query(..., description="Activar o desactivar contingencia forzada"),
    force_all: bool = Query(False, description="Si True al desactivar, afecta a TODAS las workstations de la VLAN independientemente de su estado individual"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Activar o desactivar contingencia forzada para una VLAN.
    Todas las workstations de la VLAN heredan este estado.
    """
    from app.services.websocket_manager import connection_manager
    from app.models.workstation import Workstation
    from app.models.device import Device
    import logging as log_module

    vlan = db.query(VLAN).filter(VLAN.id == vlan_id).first()
    if not vlan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VLAN no encontrada")

    if current_user.role == UserRole.OPERATOR and vlan.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos")

    # Obtener dispositivos activos de la VLAN (solo relevante al activar)
    active_devices = []
    no_devices_warning = False
    if enabled:
        active_devices = db.query(Device).filter(
            Device.vlan_id == vlan_id,
            Device.organization_id == vlan.organization_id,
            Device.is_active == True
        ).all()
        if not active_devices:
            no_devices_warning = True

    vlan.forced_contingency = enabled
    if not enabled and force_all:
        # Forzar desactivación total: también limpiar forced_contingency individual de workstations
        db.query(Workstation).filter(Workstation.vlan_id == vlan_id).update(
            {"forced_contingency": False}, synchronize_session=False
        )
    db.commit()
    db.refresh(vlan)

    log_module.getLogger(__name__).info(
        "Contingencia forzada VLAN actualizada: vlan_id=%s, enabled=%s, force_all=%s, user_id=%s",
        vlan_id, enabled, force_all, current_user.id,
    )

    # Seleccionar workstations a notificar según el modo de desactivación
    if not enabled and not force_all:
        # Smart: solo workstations sin contingencia individual propia
        workstations = db.query(Workstation).filter(
            Workstation.vlan_id == vlan_id,
            Workstation.forced_contingency == False,
        ).all()
    else:
        workstations = db.query(Workstation).filter(Workstation.vlan_id == vlan_id).all()

    for ws in workstations:
        # Resolver printer_ip para cada workstation:
        # 1. Desde default_printer_id de la workstation (favorita individual)
        # 2. Desde default_device_id de la VLAN (predeterminada de VLAN)
        # 3. Fallback: primer dispositivo activo de la VLAN
        printer_ip = None
        if enabled:
            if ws.default_printer_id:
                printer = db.query(Device).filter(Device.id == ws.default_printer_id).first()
                if printer:
                    printer_ip = printer.ip_address
            if not printer_ip and vlan.default_device_id:
                default_dev = db.query(Device).filter(Device.id == vlan.default_device_id).first()
                if default_dev:
                    printer_ip = default_dev.ip_address
            if not printer_ip and active_devices:
                printer_ip = active_devices[0].ip_address

        message = {
            "type": "forced_contingency",
            "enabled": enabled,
            "source": "vlan",
            "source_name": vlan.name,
            "printer_ip": printer_ip,
        }

        ws_id_str = str(ws.id)
        if connection_manager.is_workstation_online(ws_id_str):
            await connection_manager.send_to_workstation(ws_id_str, message)

    return {
        "forced_contingency": vlan.forced_contingency,
        "vlan_id": str(vlan.id),
        "updated_at": vlan.updated_at,
        "warning": "no_devices" if no_devices_warning else None,
    }


@router.post("/{vlan_id}/command")
async def send_vlan_command(
    vlan_id: UUID,
    command_type: str = Query(..., description="Tipo de comando: restart_service, restart_tray, check_update"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Enviar un comando remoto a todas las workstations online de una VLAN.

    Comandos soportados:
    - restart_service: Reinicia el servicio AlwaysPrintService
    - restart_tray: Reinicia la aplicación Tray
    - check_update: Fuerza verificación de actualización
    """
    import logging as log_module
    from uuid import uuid4
    from app.services.websocket_manager import connection_manager
    from app.models.workstation import Workstation

    vlan = db.query(VLAN).filter(VLAN.id == vlan_id).first()
    if not vlan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VLAN no encontrada")

    if current_user.role == UserRole.OPERATOR and vlan.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos")

    valid_commands = ["restart_service", "restart_tray", "check_update"]
    if command_type not in valid_commands:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Comando inválido: {command_type}. Válidos: {', '.join(valid_commands)}"
        )

    workstations = db.query(Workstation).filter(Workstation.vlan_id == vlan_id).all()

    # Generar params para el comando
    params = {}
    if command_type == "check_update":
        # Enriquecer con presigned URL para zero-query updates
        from app.models.organization import Organization
        from app.services.s3_update_service import S3UpdateService

        organization = db.query(Organization).filter(Organization.id == vlan.organization_id).first()
        if organization and organization.auto_update_enabled:
            try:
                update_info = S3UpdateService().get_broadcast_update_info(
                    target_version=organization.target_version
                )
                if update_info:
                    params = {
                        "download_url": update_info["download_url"],
                        "version": update_info["version"],
                        "file_size": update_info["file_size"],
                        "auto_update_enabled": True,
                    }
                else:
                    log_module.getLogger(__name__).warning(
                        "S3 no disponible para broadcast check_update VLAN %s, "
                        "usando fallback legacy (params vacío)", vlan_id
                    )
            except Exception as e:
                log_module.getLogger(__name__).warning(
                    "Error inesperado al generar presigned URL para VLAN %s: %s. "
                    "Usando fallback legacy.", vlan_id, str(e)
                )

    dispatched = 0
    for ws in workstations:
        ws_id = str(ws.id)
        if connection_manager.is_workstation_online(ws_id):
            await connection_manager.send_to_workstation(ws_id, {
                "type": "command",
                "command_id": str(uuid4()),
                "command_type": command_type,
                "params": params,
            })
            dispatched += 1

    log_module.getLogger(__name__).info(
        "Comando VLAN enviado: vlan_id=%s, command_type=%s, dispatched=%d, user_id=%s",
        vlan_id, command_type, dispatched, current_user.id,
    )

    return {"command_type": command_type, "vlan_id": str(vlan_id), "dispatched": dispatched}


@router.patch("/{vlan_id}/default-device")
async def set_vlan_default_device(
    request: Request,
    vlan_id: UUID,
    device_id: Optional[UUID] = Query(None, description="ID del dispositivo a establecer como predeterminado (null para quitar)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Establecer o quitar la impresora predeterminada de una VLAN.
    
    La impresora predeterminada se usa como fallback para workstations
    de esta VLAN que no tengan una impresora favorita individual asignada.
    El dispositivo debe pertenecer a la misma VLAN.
    """
    from app.models.device import Device
    import logging as log_module

    vlan = db.query(VLAN).filter(VLAN.id == vlan_id).first()
    if not vlan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VLAN no encontrada")

    if current_user.role == UserRole.OPERATOR and vlan.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos")

    old_device_id = str(vlan.default_device_id) if vlan.default_device_id else None

    if device_id:
        # Verificar que el dispositivo existe, está activo y pertenece a esta VLAN
        device = db.query(Device).filter(Device.id == device_id).first()
        if not device:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispositivo no encontrado")
        if device.vlan_id != vlan.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El dispositivo no pertenece a esta VLAN"
            )
        if not device.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El dispositivo no está activo"
            )
        vlan.default_device_id = device_id
    else:
        vlan.default_device_id = None

    db.commit()
    db.refresh(vlan)

    log_module.getLogger(__name__).info(
        "Impresora predeterminada de VLAN actualizada: vlan_id=%s, device_id=%s, user_id=%s",
        vlan_id, device_id, current_user.id,
    )

    # Notificar a workstations online de esta VLAN vía WebSocket
    from app.services.websocket_manager import connection_manager
    from app.models.workstation import Workstation
    from app.models.device import Device as DeviceModel

    workstations = db.query(Workstation).filter(Workstation.vlan_id == vlan_id).all()
    
    log_module.getLogger(__name__).info(
        "Notificando %d workstation(s) de VLAN %s sobre cambio de impresora predeterminada",
        len(workstations), vlan_id,
    )

    # Resolver IP de la nueva impresora predeterminada
    new_printer_ip = None
    new_printer_name = None
    if device_id:
        dev = db.query(DeviceModel).filter(DeviceModel.id == device_id).first()
        if dev:
            new_printer_ip = dev.ip_address
            new_printer_name = dev.name

    for ws in workstations:
        message = {
            "type": "default_printer_changed",
            "source": "vlan",
            "vlan_name": vlan.name,
            "default_device_id": str(device_id) if device_id else None,
            "printer_ip": new_printer_ip,
            "printer_name": new_printer_name,
        }

        ws_id_str = str(ws.id)
        is_online = connection_manager.is_workstation_online(ws_id_str)
        log_module.getLogger(__name__).info(
            "  WS %s (ip=%s): online=%s", ws_id_str, ws.ip_private, is_online
        )
        if is_online:
            try:
                await connection_manager.send_to_workstation(ws_id_str, message)
                log_module.getLogger(__name__).info("  → Mensaje enviado a %s", ws_id_str)
            except Exception as e:
                log_module.getLogger(__name__).warning("  → Error enviando a %s: %s", ws_id_str, e)

    audit_service = AuditService()
    audit_service.log_update(
        db=db,
        entity_type="vlan",
        entity_id=str(vlan.id),
        user_id=str(current_user.id),
        organization_id=str(vlan.organization_id),
        old_data={"default_device_id": old_device_id},
        new_data={"default_device_id": str(device_id) if device_id else None},
        ip_address=get_client_ip(request)
    )

    return {
        "default_device_id": str(vlan.default_device_id) if vlan.default_device_id else None,
        "vlan_id": str(vlan.id),
        "updated_at": vlan.updated_at,
    }


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
    
    if current_user.role == UserRole.OPERATOR and vlan.organization_id != current_user.organization_id:
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
    
    if current_user.role == UserRole.OPERATOR and vlan.organization_id != current_user.organization_id:
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
        organization_id=str(vlan.organization_id),
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
    
    if current_user.role == UserRole.OPERATOR and vlan.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos")
    
    config_service = ConfigService()
    config_service.delete_vlan_config(db, vlan_id)
    
    audit_service = AuditService()
    audit_service.log_config_change(
        db=db,
        entity_type="vlan_config",
        entity_id=str(vlan_id),
        user_id=str(current_user.id),
        organization_id=str(vlan.organization_id),
        old_config={"action": "config_deleted"},
        new_config={},
        ip_address=get_client_ip(request)
    )
    
    return None
