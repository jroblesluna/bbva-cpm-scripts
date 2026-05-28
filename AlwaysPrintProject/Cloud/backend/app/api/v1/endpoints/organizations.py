"""
Endpoints de gestión de organizaciones (solo Admin).

Este módulo define los endpoints para:
- CRUD de organizaciones
- Gestión de IPs públicas
- Toggle de actualizaciones automáticas
"""

import logging
from typing import Optional
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_admin, require_operator_or_admin
from app.core.utils import get_client_ip
from app.models.user import User, UserRole
from app.models.organization import Organization, PublicIP
from app.models.workstation import Workstation
from app.services.websocket_manager import connection_manager
from app.schemas.organization import (
    OrganizationCreate,
    OrganizationUpdate,
    OrganizationResponse,
    OrganizationDetailResponse,
    OrganizationListResponse,
    PublicIPCreate,
    PublicIPResponse,
    PublicIPPendingResponse,
    PublicIPAuthorizeRequest,
    AutoUpdateToggleRequest,
    AutoUpdateToggleResponse,
    TargetVersionRequest,
    TargetVersionResponse,
)
from app.services.audit import AuditService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_model=OrganizationListResponse)
def list_organizations(
    page: int = Query(1, ge=1, description="Número de página"),
    page_size: int = Query(50, ge=1, le=100, description="Tamaño de página"),
    search: Optional[str] = Query(None, description="Buscar por nombre"),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Listar todas las organizaciones (solo Admin).
    
    Args:
        page: Número de página
        page_size: Tamaño de página (1-100)
        search: Término de búsqueda opcional
        current_user: Usuario autenticado (debe ser Admin)
        db: Sesión de base de datos
    
    Returns:
        OrganizationListResponse con lista paginada de organizaciones
    """
    query = db.query(Organization)
    
    # Filtrar por búsqueda si se proporciona
    if search:
        query = query.filter(Organization.name.ilike(f"%{search}%"))
    
    # Contar total
    total = query.count()
    
    # Paginar con eager loading de public_ips (solo autorizadas)
    from sqlalchemy.orm import joinedload
    offset = (page - 1) * page_size
    organizations = (
        query
        .options(joinedload(Organization.public_ips.and_(PublicIP.is_authorized == True)))
        .offset(offset)
        .limit(page_size)
        .all()
    )
    
    return OrganizationListResponse(
        items=organizations,
        total=total,
        skip=offset,
        limit=page_size
    )


# === ENDPOINTS PARA OPERADORES (su propia organización) ===


@router.get("/me", response_model=OrganizationDetailResponse)
def get_my_organization(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtener la organización del usuario autenticado.
    
    Disponible para operadores y admins. Los operadores solo pueden ver
    su propia organización asignada.
    """
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario sin organización asignada"
        )
    
    organization = db.query(Organization).filter(
        Organization.id == current_user.organization_id
    ).first()
    
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organización no encontrada"
        )
    
    # Contar usuarios y workstations
    user_count = len(organization.users)
    workstation_count = len(organization.workstations)
    online_count = sum(1 for ws in organization.workstations if ws.is_online)
    
    response = OrganizationDetailResponse(
        **organization.__dict__,
        public_ips=[PublicIPResponse(**ip.__dict__) for ip in organization.public_ips if ip.is_authorized],
        user_count=user_count,
        workstation_count=workstation_count,
        online_count=online_count,
    )
    
    return response


@router.put("/me", response_model=OrganizationResponse)
def update_my_organization(
    request: Request,
    org_data: OrganizationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Actualizar la organización del usuario autenticado.
    
    Disponible para operadores. Permite editar configuración básica
    de su propia organización (nombre, descripción, timezone, idioma).
    No permite cambiar is_active ni campos sensibles de admin.
    """
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario sin organización asignada"
        )
    
    organization = db.query(Organization).filter(
        Organization.id == current_user.organization_id
    ).first()
    
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organización no encontrada"
        )
    
    # Guardar valores anteriores para auditoría
    old_values = {
        "name": organization.name,
        "description": organization.description,
        "timezone": organization.timezone
    }
    
    # Operadores no pueden cambiar campos sensibles de activación
    update_data = org_data.model_dump(exclude_unset=True)
    if current_user.role == UserRole.OPERATOR:
        # Remover campos que solo admin puede modificar
        sensitive_fields = ["is_active"]
        for field in sensitive_fields:
            update_data.pop(field, None)
    
    # Verificar nombre único si se está actualizando
    if "name" in update_data and update_data["name"] != organization.name:
        existing = db.query(Organization).filter(Organization.name == update_data["name"]).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Ya existe una organización con el nombre '{update_data['name']}'"
            )
    
    for field, value in update_data.items():
        setattr(organization, field, value)
    
    db.commit()
    db.refresh(organization)
    
    # Registrar en auditoría
    audit_service = AuditService()
    audit_service.log_update(
        db=db,
        entity_type="organization",
        entity_id=str(organization.id),
        user_id=str(current_user.id),
        organization_id=str(organization.id),
        old_data=old_values,
        new_data=update_data,
        ip_address=get_client_ip(request)
    )
    
    return organization


@router.patch("/me/auto-update", response_model=AutoUpdateToggleResponse)
async def toggle_my_auto_update(
    body: AutoUpdateToggleRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Activar/desactivar actualizaciones automáticas de la organización del operador.
    Al habilitar, envía check_update a todas las workstations online de la org.
    """
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario sin organización asignada"
        )
    
    organization = db.query(Organization).filter(
        Organization.id == current_user.organization_id
    ).first()
    
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organización no encontrada"
        )
    
    organization.auto_update_enabled = body.enabled
    db.commit()
    db.refresh(organization)
    
    logger.info(
        "Auto-update actualizado (operador): org_id=%s, enabled=%s, user_id=%s",
        organization.id, body.enabled, current_user.id,
    )
    
    # Si se habilita, enviar check_update a workstations online
    if body.enabled:
        workstations = db.query(Workstation).filter(
            Workstation.organization_id == organization.id
        ).all()
        
        import uuid as uuid_module
        for ws in workstations:
            ws_id = str(ws.id)
            if connection_manager.is_workstation_online(ws_id):
                await connection_manager.send_to_workstation(ws_id, {
                    "type": "command",
                    "command_id": str(uuid_module.uuid4()),
                    "command_type": "check_update",
                    "params": {},
                })
    
    return AutoUpdateToggleResponse(
        auto_update_enabled=organization.auto_update_enabled,
        organization_id=str(organization.id),
        updated_at=organization.updated_at,
    )


@router.put("/me/pin-version")
async def pin_my_version(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Pinear una versión específica para la organización del operador.
    Body: { "version": "1.x.x.x" } o { "version": null } para despinear.
    """
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario sin organización asignada"
        )
    
    organization = db.query(Organization).filter(
        Organization.id == current_user.organization_id
    ).first()
    
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organización no encontrada"
        )
    
    body = await request.json()
    version = body.get("version")
    
    organization.target_version = version if version else None
    db.commit()
    db.refresh(organization)
    
    logger.info(
        "Versión pineada (operador): org_id=%s, version=%s, user_id=%s",
        organization.id, version, current_user.id,
    )
    
    return {
        "target_version": organization.target_version,
        "organization_id": str(organization.id),
        "updated_at": str(organization.updated_at),
    }


@router.post("/me/public-ips", response_model=PublicIPResponse, status_code=status.HTTP_201_CREATED)
def add_my_public_ip(
    request: Request,
    ip_data: PublicIPCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Agregar una IP pública a la organización del operador.
    """
    if not current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario sin organización asignada")
    
    org_id = current_user.organization_id
    organization = db.query(Organization).filter(Organization.id == org_id).first()
    if not organization:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organización no encontrada")
    
    # Verificar que la IP no existe
    existing = db.query(PublicIP).filter(PublicIP.ip_address == ip_data.ip_address).first()
    if existing:
        if existing.is_authorized:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"La IP {ip_data.ip_address} ya está registrada")
        # Si existe como pendiente, autorizarla para esta org
        existing.organization_id = org_id
        existing.is_authorized = True
        existing.description = ip_data.description
        from datetime import datetime, timezone
        existing.authorized_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        db.refresh(existing)
        return existing
    
    from datetime import datetime, timezone
    new_ip = PublicIP(
        ip_address=ip_data.ip_address,
        description=ip_data.description,
        organization_id=org_id,
        is_authorized=True,
        first_seen=datetime.now(timezone.utc).replace(tzinfo=None),
        authorized_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(new_ip)
    db.commit()
    db.refresh(new_ip)
    
    audit_service = AuditService()
    audit_service.log_create(
        db=db,
        entity_type="public_ip",
        entity_id=str(new_ip.id),
        user_id=str(current_user.id),
        organization_id=str(org_id),
        entity_data={"ip_address": new_ip.ip_address},
        ip_address=get_client_ip(request)
    )
    
    return new_ip


@router.delete("/me/public-ips/{ip_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_my_public_ip(
    request: Request,
    ip_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Eliminar una IP pública de la organización del operador.
    """
    if not current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario sin organización asignada")
    
    org_id = current_user.organization_id
    
    public_ip = db.query(PublicIP).filter(
        PublicIP.id == ip_id,
        PublicIP.organization_id == org_id
    ).first()
    
    if not public_ip:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IP pública no encontrada")
    
    db.delete(public_ip)
    db.commit()
    
    audit_service = AuditService()
    audit_service.log_delete(
        db=db,
        entity_type="public_ip",
        entity_id=str(ip_id),
        user_id=str(current_user.id),
        organization_id=str(org_id),
        entity_data={"ip_address": public_ip.ip_address},
        ip_address=get_client_ip(request)
    )
    
    return None


@router.post("/", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
def create_organization(
    request: Request,
    org_data: OrganizationCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Crear una nueva organización (solo Admin).
    """
    # Verificar que no exista una organización con el mismo nombre
    existing = db.query(Organization).filter(Organization.name == org_data.name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe una organización con el nombre '{org_data.name}'"
        )
    
    # Crear organización
    organization = Organization(
        name=org_data.name,
        description=org_data.description,
        timezone=org_data.timezone,
        language=org_data.language if org_data.language in ('en', 'es') else 'en',
    )
    db.add(organization)
    db.commit()
    db.refresh(organization)
    
    # Registrar en auditoría
    audit_service = AuditService()
    audit_service.log_create(
        db=db,
        entity_type="organization",
        entity_id=str(organization.id),
        user_id=str(current_user.id),
        organization_id=str(organization.id),
        entity_data={
            "name": organization.name,
            "description": organization.description,
            "timezone": organization.timezone
        },
        ip_address=get_client_ip(request)
    )
    
    return organization


@router.get("/{org_id}", response_model=OrganizationDetailResponse)
def get_organization(
    org_id: UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Obtener detalles de una organización (solo Admin).
    """
    organization = db.query(Organization).filter(Organization.id == org_id).first()
    
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organización con ID {org_id} no encontrada"
        )
    
    # Contar usuarios y workstations
    user_count = len(organization.users)
    workstation_count = len(organization.workstations)
    
    # Crear respuesta detallada
    response = OrganizationDetailResponse(
        **organization.__dict__,
        public_ips=[PublicIPResponse(**ip.__dict__) for ip in organization.public_ips],
        user_count=user_count,
        workstation_count=workstation_count
    )
    
    return response


@router.put("/{org_id}", response_model=OrganizationResponse)
def update_organization(
    request: Request,
    org_id: UUID,
    org_data: OrganizationUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Actualizar una organización (solo Admin).
    """
    organization = db.query(Organization).filter(Organization.id == org_id).first()
    
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organización con ID {org_id} no encontrada"
        )
    
    # Guardar valores anteriores para auditoría
    old_values = {
        "name": organization.name,
        "description": organization.description,
        "timezone": organization.timezone
    }
    
    # Actualizar campos
    update_data = org_data.model_dump(exclude_unset=True)
    
    # Verificar nombre único si se está actualizando
    if "name" in update_data and update_data["name"] != organization.name:
        existing = db.query(Organization).filter(Organization.name == update_data["name"]).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Ya existe una organización con el nombre '{update_data['name']}'"
            )
    
    for field, value in update_data.items():
        setattr(organization, field, value)
    
    db.commit()
    db.refresh(organization)
    
    # Registrar en auditoría
    audit_service = AuditService()
    audit_service.log_update(
        db=db,
        entity_type="organization",
        entity_id=str(organization.id),
        user_id=str(current_user.id),
        organization_id=str(organization.id),
        old_data=old_values,
        new_data=update_data,
        ip_address=get_client_ip(request)
    )
    
    return organization


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_organization(
    request: Request,
    org_id: UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Eliminar una organización (solo Admin).
    
    ADVERTENCIA: Esto eliminará en cascada todos los usuarios, workstations,
    VLANs y configuraciones asociadas a la organización.
    """
    organization = db.query(Organization).filter(Organization.id == org_id).first()
    
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organización con ID {org_id} no encontrada"
        )
    
    # Guardar valores para auditoría
    old_values = {
        "name": organization.name,
        "description": organization.description,
        "timezone": organization.timezone
    }
    
    # Registrar en auditoría antes de eliminar para que el FK sea válido al insertar
    audit_service = AuditService()
    audit_service.log_delete(
        db=db,
        entity_type="organization",
        entity_id=str(org_id),
        user_id=str(current_user.id),
        organization_id=str(org_id),
        entity_data=old_values,
        ip_address=get_client_ip(request)
    )

    # Eliminar organización (cascada automática; SET NULL en audit_logs)
    db.delete(organization)
    db.commit()
    
    return None


# === ENDPOINTS DE IPS PÚBLICAS ===

@router.post("/{org_id}/public-ips", response_model=PublicIPResponse, status_code=status.HTTP_201_CREATED)
def add_public_ip(
    request: Request,
    org_id: UUID,
    ip_data: PublicIPCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Agregar una IP pública a una organización (solo Admin).
    """
    # Verificar que la organización existe
    organization = db.query(Organization).filter(Organization.id == org_id).first()
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organización con ID {org_id} no encontrada"
        )
    
    # Verificar que la IP no existe
    existing = db.query(PublicIP).filter(PublicIP.ip_address == ip_data.ip_address).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"La IP {ip_data.ip_address} ya está registrada"
        )
    
    # Crear IP pública
    public_ip = PublicIP(
        organization_id=org_id,
        ip_address=ip_data.ip_address,
        description=ip_data.description
    )
    db.add(public_ip)
    db.commit()
    db.refresh(public_ip)
    
    # Registrar en auditoría
    audit_service = AuditService()
    audit_service.log_create(
        db=db,
        entity_type="public_ip",
        entity_id=str(public_ip.id),
        user_id=str(current_user.id),
        organization_id=str(org_id),
        entity_data={
            "ip_address": public_ip.ip_address,
            "description": public_ip.description
        },
        ip_address=get_client_ip(request)
    )
    
    return public_ip


@router.delete("/{org_id}/public-ips/{ip_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_public_ip(
    request: Request,
    org_id: UUID,
    ip_id: UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Eliminar una IP pública de una organización (solo Admin).
    """
    # Verificar que la organización existe
    organization = db.query(Organization).filter(Organization.id == org_id).first()
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organización con ID {org_id} no encontrada"
        )
    
    # Buscar IP pública
    public_ip = db.query(PublicIP).filter(
        PublicIP.id == ip_id,
        PublicIP.organization_id == org_id
    ).first()
    
    if not public_ip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"IP pública con ID {ip_id} no encontrada en la organización"
        )
    
    # Guardar valores para auditoría
    old_values = {
        "ip_address": public_ip.ip_address,
        "description": public_ip.description
    }
    
    # Eliminar IP
    db.delete(public_ip)
    db.commit()
    
    # Registrar en auditoría
    audit_service = AuditService()
    audit_service.log_delete(
        db=db,
        entity_type="public_ip",
        entity_id=str(ip_id),
        user_id=str(current_user.id),
        organization_id=str(org_id),
        entity_data=old_values,
        ip_address=get_client_ip(request)
    )
    
    return None


# === ENDPOINTS DE IPS PÚBLICAS PENDIENTES ===

@router.get("/public-ips/pending", response_model=list[PublicIPPendingResponse])
def list_pending_public_ips(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Listar IPs públicas pendientes de autorización (solo Admin).
    """
    pending_ips = db.query(PublicIP).filter(
        PublicIP.is_authorized == False
    ).order_by(PublicIP.first_seen.desc()).all()
    
    return pending_ips


@router.post("/public-ips/{ip_id}/authorize", response_model=PublicIPResponse)
def authorize_public_ip(
    request: Request,
    ip_id: UUID,
    authorize_data: PublicIPAuthorizeRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Autorizar una IP pública y asignarla a una organización (solo Admin).
    """
    from datetime import datetime, timezone
    
    # Buscar IP
    public_ip = db.query(PublicIP).filter(PublicIP.id == ip_id).first()
    
    if not public_ip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"IP pública con ID {ip_id} no encontrada"
        )
    
    if public_ip.is_authorized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta IP ya está autorizada"
        )
    
    # Verificar que la organización existe
    organization = db.query(Organization).filter(Organization.id == authorize_data.organization_id).first()
    
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organización con ID {authorize_data.organization_id} no encontrada"
        )
    
    # Autorizar IP
    public_ip.is_authorized = True
    public_ip.organization_id = authorize_data.organization_id
    public_ip.authorized_at = datetime.now(timezone.utc).replace(tzinfo=None)
    
    if authorize_data.description:
        public_ip.description = authorize_data.description
    
    db.commit()
    db.refresh(public_ip)
    
    # Registrar en auditoría
    audit_service = AuditService()
    audit_service.log_action(
        db=db,
        action_type="update",
        entity_type="PublicIP",
        entity_id=str(public_ip.id),
        user_id=str(current_user.id),
        organization_id=str(authorize_data.organization_id),
        old_values={"is_authorized": False, "organization_id": None},
        new_values={"is_authorized": True, "organization_id": str(authorize_data.organization_id)},
        ip_address=get_client_ip(request)
    )
    
    return public_ip


@router.delete("/public-ips/{ip_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
def reject_public_ip(
    request: Request,
    ip_id: UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Rechazar y eliminar una IP pública pendiente (solo Admin).
    """
    # Buscar IP
    public_ip = db.query(PublicIP).filter(PublicIP.id == ip_id).first()
    
    if not public_ip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"IP pública con ID {ip_id} no encontrada"
        )
    
    if public_ip.is_authorized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se puede rechazar una IP ya autorizada. Usa DELETE para eliminarla."
        )
    
    # Eliminar IP
    db.delete(public_ip)
    db.commit()
    
    # Registrar en auditoría
    audit_service = AuditService()
    audit_service.log_action(
        db=db,
        action_type="delete",
        entity_type="PublicIP",
        entity_id=str(public_ip.id),
        user_id=str(current_user.id),
        organization_id=None,
        old_values={"ip_address": public_ip.ip_address, "is_authorized": False},
        new_values={},
        ip_address=get_client_ip(request)
    )
    
    return None


# === TOGGLE AUTO-UPDATE ===

@router.patch(
    "/{org_id}/auto-update",
    response_model=AutoUpdateToggleResponse,
    summary="Activar/desactivar actualizaciones automáticas",
    description="Permite a un administrador habilitar o deshabilitar las actualizaciones automáticas para una organización."
)
async def toggle_auto_update(
    org_id: UUID,
    body: AutoUpdateToggleRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Activar o desactivar actualizaciones automáticas para una organización.
    Al habilitar, envía check_update a todas las workstations online de la org.
    """
    organization = db.query(Organization).filter(Organization.id == org_id).first()

    if not organization:
        logger.warning(
            "Intento de toggle auto-update en organización inexistente: org_id=%s, user_id=%s",
            org_id,
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organización no encontrada"
        )

    organization.auto_update_enabled = body.enabled
    db.commit()
    db.refresh(organization)

    logger.info(
        "Auto-update actualizado: org_id=%s, enabled=%s, admin_id=%s",
        org_id,
        body.enabled,
        current_user.id,
    )

    # Al habilitar, disparar check_update en todas las workstations online de la org
    if body.enabled:
        workstations = db.query(Workstation).filter(
            Workstation.organization_id == org_id
        ).all()

        dispatched = 0
        for ws in workstations:
            ws_id = str(ws.id)
            if connection_manager.is_workstation_online(ws_id):
                await connection_manager.send_to_workstation(ws_id, {
                    "type": "command",
                    "command_id": str(uuid4()),
                    "command_type": "check_update",
                    "params": {},
                })
                dispatched += 1

        logger.info(
            "check_update enviado a %d workstations online de org_id=%s",
            dispatched,
            org_id,
        )

    return AutoUpdateToggleResponse(
        auto_update_enabled=organization.auto_update_enabled,
        organization_id=str(organization.id),
        updated_at=organization.updated_at,
    )


# === TARGET VERSION ===

@router.patch(
    "/{org_id}/forced-contingency",
    summary="Activar/desactivar contingencia forzada",
    description=(
        "Permite a un administrador activar o desactivar la contingencia forzada "
        "para toda una organización. Todas las workstations de la organización "
        "heredan este estado."
    )
)
async def toggle_forced_contingency(
    org_id: UUID,
    body: AutoUpdateToggleRequest,
    current_user: User = Depends(require_operator_or_admin),
    db: Session = Depends(get_db)
):
    """
    Activar o desactivar contingencia forzada para una organización.
    Todas las workstations de la organización heredan este estado.
    """
    if current_user.role == UserRole.OPERATOR and current_user.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para modificar esta organización"
        )

    organization = db.query(Organization).filter(Organization.id == org_id).first()

    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organización no encontrada"
        )

    organization.forced_contingency = body.enabled
    db.commit()
    db.refresh(organization)

    logger.info(
        "Contingencia forzada actualizada: org_id=%s, enabled=%s, admin_id=%s",
        org_id,
        body.enabled,
        current_user.id,
    )

    # Notificar a todas las workstations online de esta organización vía WebSocket
    from app.services.websocket_manager import connection_manager
    from app.models.workstation import Workstation
    from app.models.device import Device

    workstations = db.query(Workstation).filter(
        Workstation.organization_id == org_id
    ).all()

    for ws in workstations:
        # Resolver printer_ip para cada workstation:
        # 1. Desde default_printer_id de la workstation (favorita individual)
        # 2. Desde default_device_id de la VLAN (predeterminada de VLAN)
        # 3. Fallback: primer dispositivo activo en la VLAN de la workstation
        printer_ip = None
        if body.enabled:
            if ws.default_printer_id:
                printer = db.query(Device).filter(Device.id == ws.default_printer_id).first()
                if printer:
                    printer_ip = printer.ip_address
            if not printer_ip and ws.vlan_id:
                from app.models.vlan import VLAN as VLANModel
                ws_vlan = db.query(VLANModel).filter(VLANModel.id == ws.vlan_id).first()
                if ws_vlan and ws_vlan.default_device_id:
                    default_dev = db.query(Device).filter(Device.id == ws_vlan.default_device_id).first()
                    if default_dev:
                        printer_ip = default_dev.ip_address
            if not printer_ip and ws.vlan_id:
                first_device = db.query(Device).filter(
                    Device.vlan_id == ws.vlan_id,
                    Device.organization_id == org_id,
                    Device.is_active == True
                ).order_by(Device.ip_address).first()
                if first_device:
                    printer_ip = first_device.ip_address

        message = {
            "type": "forced_contingency",
            "enabled": body.enabled,
            "source": "organization",
            "source_name": organization.name,
            "printer_ip": printer_ip,
        }

        ws_id_str = str(ws.id)
        if connection_manager.is_workstation_online(ws_id_str):
            await connection_manager.send_to_workstation(ws_id_str, message)

    return {
        "forced_contingency": organization.forced_contingency,
        "organization_id": str(organization.id),
        "updated_at": organization.updated_at,
    }


@router.patch(
    "/{org_id}/target-version",
    response_model=TargetVersionResponse,
    summary="Establecer versión objetivo de actualización",
    description=(
        "Permite a un administrador establecer una versión específica a la que "
        "las workstations de la organización deben actualizarse. "
        "Enviar null para volver a usar la última versión disponible (latest)."
    )
)
def set_target_version(
    org_id: UUID,
    body: TargetVersionRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Establecer o limpiar la versión objetivo de actualización para una organización.

    Si version es un string (ej: "1.26.517.1430"), las workstations se actualizarán
    a esa versión específica. Si version es null, se usa la última versión disponible.
    """
    # Buscar la organización por ID
    organization = db.query(Organization).filter(Organization.id == org_id).first()

    if not organization:
        logger.warning(
            "Intento de set target-version en organización inexistente: org_id=%s, user_id=%s",
            org_id,
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organización no encontrada"
        )

    # Actualizar la versión objetivo
    organization.target_version = body.version
    db.commit()
    db.refresh(organization)

    logger.info(
        "Target version actualizada: org_id=%s, target_version=%s, admin_id=%s",
        org_id,
        body.version,
        current_user.id,
    )

    return TargetVersionResponse(
        target_version=organization.target_version,
        organization_id=str(organization.id),
        updated_at=organization.updated_at,
    )


@router.post("/{org_id}/command")
async def send_org_command(
    org_id: UUID,
    command_type: str = Query(..., description="Tipo de comando: restart_service, restart_tray, check_update"),
    current_user: User = Depends(require_operator_or_admin),
    db: Session = Depends(get_db)
):
    """
    Enviar un comando remoto a todas las workstations online de una organización.

    Comandos soportados:
    - restart_service: Reinicia el servicio AlwaysPrintService
    - restart_tray: Reinicia la aplicación Tray
    - check_update: Fuerza verificación de actualización
    """
    if current_user.role == UserRole.OPERATOR and current_user.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para enviar comandos a esta organización"
        )

    organization = db.query(Organization).filter(Organization.id == org_id).first()
    if not organization:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organización no encontrada")

    valid_commands = ["restart_service", "restart_tray", "check_update"]
    if command_type not in valid_commands:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Comando inválido: {command_type}. Válidos: {', '.join(valid_commands)}"
        )

    workstations = db.query(Workstation).filter(Workstation.organization_id == org_id).all()

    dispatched = 0
    for ws in workstations:
        ws_id = str(ws.id)
        if connection_manager.is_workstation_online(ws_id):
            await connection_manager.send_to_workstation(ws_id, {
                "type": "command",
                "command_id": str(uuid4()),
                "command_type": command_type,
                "params": {},
            })
            dispatched += 1

    logger.info(
        "Comando Organización enviado: org_id=%s, command_type=%s, dispatched=%d, admin_id=%s",
        org_id, command_type, dispatched, current_user.id,
    )

    return {"command_type": command_type, "organization_id": str(org_id), "dispatched": dispatched}
