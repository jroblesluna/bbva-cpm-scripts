"""
Endpoints de gestión de organizaciones (solo Admin).

Este módulo define los endpoints para:
- CRUD de organizaciones
- Gestión de IPs públicas
- Toggle de actualizaciones automáticas
"""

import logging
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_admin
from app.core.utils import get_client_ip
from app.models.user import User, UserRole
from app.models.organization import Organization, PublicIP
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
        account_id=str(organization.id),
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
        account_id=str(organization.id),
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
    
    # Eliminar organización (cascada automática)
    db.delete(organization)
    db.commit()
    
    # Registrar en auditoría
    audit_service = AuditService()
    audit_service.log_delete(
        db=db,
        entity_type="organization",
        entity_id=str(org_id),
        user_id=str(current_user.id),
        account_id=str(org_id),
        entity_data=old_values,
        ip_address=get_client_ip(request)
    )
    
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
        account_id=str(org_id),
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
        account_id=str(org_id),
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
    from datetime import datetime
    
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
    public_ip.authorized_at = datetime.utcnow()
    
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
        account_id=str(authorize_data.organization_id),
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
        account_id=None,
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
def toggle_auto_update(
    org_id: UUID,
    body: AutoUpdateToggleRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Activar o desactivar actualizaciones automáticas para una organización.
    """
    # Buscar la organización por ID
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

    # Actualizar el flag de auto-actualización
    organization.auto_update_enabled = body.enabled
    db.commit()
    db.refresh(organization)

    logger.info(
        "Auto-update actualizado: org_id=%s, enabled=%s, admin_id=%s",
        org_id,
        body.enabled,
        current_user.id,
    )

    return AutoUpdateToggleResponse(
        auto_update_enabled=organization.auto_update_enabled,
        organization_id=str(organization.id),
        updated_at=organization.updated_at,
    )
