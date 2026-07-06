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
from app.models.action_config import ActionConfig, ActionConfigScope
from app.schemas import WorkstationListResponse
from app.services.websocket_manager import connection_manager
from app.schemas.organization import (
    OrganizationCreate,
    OrganizationUpdate,
    OrganizationResponse,
    OrganizationDetailResponse,
    OrganizationListResponse,
    OrganizationStats,
    PublicIPCreate,
    PublicIPResponse,
    PublicIPPendingResponse,
    PublicIPAuthorizeRequest,
    AutoUpdateToggleRequest,
    AutoUpdateToggleResponse,
    ForcedContingencyRequest,
    TargetVersionRequest,
    TargetVersionResponse,
)
from app.core.config import settings
from app.services.audit import AuditService
from app.services.config import ConfigService
from app.services.crypto_service import CryptoService
from app.services.s3_config_service import S3ConfigService
from app.services.s3_update_service import S3UpdateService
from app.services.push_services import get_state_map_service, get_push_distribution_service

logger = logging.getLogger(__name__)

router = APIRouter()

# Instancia del servicio de configuración para broadcast
_config_service = ConfigService()


async def _broadcast_config_update_to_org(db: Session, organization_id: str) -> int:
    """
    Envía config_update a todas las workstations conectadas de una organización.
    
    Se invoca cuando jitter_window_seconds cambia para propagar la nueva
    configuración efectiva a las workstations en tiempo real.
    
    Args:
        db: Sesión de base de datos
        organization_id: UUID de la organización como string
        
    Returns:
        Cantidad de workstations a las que se envió el mensaje
    """
    workstations = db.query(Workstation).filter(
        Workstation.organization_id == organization_id
    ).all()
    
    dispatched = 0
    for ws in workstations:
        ws_id = str(ws.id)
        if connection_manager.is_workstation_online(ws_id):
            config = _config_service.get_effective_config(db, ws_id)
            await connection_manager.send_to_workstation(ws_id, {
                "type": "config_update",
                "config": config,
            })
            dispatched += 1
    
    logger.info(
        "config_update broadcast (jitter_window_seconds): org_id=%s, dispatched=%d",
        organization_id, dispatched,
    )
    
    return dispatched


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


@router.get("/stats", response_model=OrganizationStats)
def get_organization_stats(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Estadísticas agregadas de organizaciones para el dashboard (solo Admin)."""
    from sqlalchemy import func

    total = db.query(func.count(Organization.id)).scalar()

    with_config = db.query(func.count(Organization.id)).filter(
        Organization.action_configs.any(ActionConfig.scope == ActionConfigScope.ORG)
    ).scalar()

    applying_mandatory = db.query(func.count(Organization.id)).filter(
        Organization.action_config_mandatory == True
    ).scalar()

    in_contingency = db.query(func.count(Organization.id)).filter(
        Organization.forced_contingency == True
    ).scalar()

    return OrganizationStats(
        total=total or 0,
        with_config=with_config or 0,
        applying_mandatory=applying_mandatory or 0,
        in_contingency=in_contingency or 0,
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


@router.get("/me/workstations", response_model=WorkstationListResponse)
def list_my_workstations(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    search: Optional[str] = Query(None, description="Buscar por hostname o IP"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Listar workstations de la organización del usuario autenticado.
    Disponible para operadores y admins.
    """
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario sin organización asignada"
        )

    query = db.query(Workstation).filter(
        Workstation.organization_id == current_user.organization_id
    )

    if search:
        query = query.filter(
            Workstation.hostname.ilike(f"%{search}%") |
            Workstation.ip_private.ilike(f"%{search}%")
        )

    total = query.count()
    offset = (page - 1) * page_size
    workstations = query.offset(offset).limit(page_size).all()

    return WorkstationListResponse(
        items=workstations,
        total=total,
        skip=offset,
        limit=page_size
    )


@router.put("/me", response_model=OrganizationResponse)
async def update_my_organization(
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
    
    # Guardar valores anteriores para auditoría y detección de cambios
    old_values = {
        "name": organization.name,
        "description": organization.description,
        "timezone": organization.timezone
    }
    old_jitter = organization.jitter_window_seconds
    
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
    
    # Si jitter_window_seconds cambió, broadcast config_update a workstations conectadas
    if "jitter_window_seconds" in update_data and update_data["jitter_window_seconds"] != old_jitter:
        await _broadcast_config_update_to_org(db, str(organization.id))
    
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
        # Generar params enriquecidos para check_update (zero-query)
        update_info = S3UpdateService().get_broadcast_update_info(
            target_version=organization.target_version
        )
        params = {}
        if update_info:
            params = {
                "download_url": update_info["download_url"],
                "version": update_info["version"],
                "file_size": update_info["file_size"],
                "auto_update_enabled": True,
            }

            # Push-based distribution: actualizar state map → Redis
            try:
                state_map = get_state_map_service()
                push_service = get_push_distribution_service()

                await state_map.update_msi(
                    org_id=str(organization.id),
                    msi_version=update_info["version"],
                    msi_url=update_info["download_url"],
                )

                enviados = await push_service.push_msi_update(
                    org_id=str(organization.id),
                    msi_version=update_info["version"],
                    download_url=update_info["download_url"],
                    file_size=update_info["file_size"],
                )

                logger.info(
                    "push.msi_auto_update_operador: org_id=%s, version=%s, ws_notificadas=%d",
                    organization.id, update_info["version"], enviados,
                )
            except Exception as e:
                logger.error(
                    "push.msi_auto_update_operador_error: org_id=%s, error=%s",
                    organization.id, str(e),
                )
        else:
            logger.warning(
                "S3 no disponible para broadcast check_update, "
                "usando fallback legacy (params vacío)"
            )

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
                    "params": params,
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
    
    # Push-based distribution: actualizar state map → Redis → push a workstations
    if version:
        try:
            state_map = get_state_map_service()
            push_service = get_push_distribution_service()

            update_info = S3UpdateService().get_broadcast_update_info(
                target_version=version
            )

            if update_info:
                await state_map.update_msi(
                    org_id=str(organization.id),
                    msi_version=update_info["version"],
                    msi_url=update_info["download_url"],
                )

                enviados = await push_service.push_msi_update(
                    org_id=str(organization.id),
                    msi_version=update_info["version"],
                    download_url=update_info["download_url"],
                    file_size=update_info["file_size"],
                )

                logger.info(
                    "push.msi_pin_version_operador: org_id=%s, version=%s, ws_notificadas=%d",
                    organization.id, version, enviados,
                )
            else:
                logger.warning(
                    "push.msi_pin_version_sin_s3: org_id=%s, version=%s",
                    organization.id, version,
                )
        except Exception as e:
            logger.error(
                "push.msi_pin_version_error: org_id=%s, version=%s, error=%s",
                organization.id, version, str(e),
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
async def update_organization(
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
    
    # Guardar valores anteriores para auditoría y detección de cambios
    old_values = {
        "name": organization.name,
        "description": organization.description,
        "timezone": organization.timezone
    }
    old_jitter = organization.jitter_window_seconds
    
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
    
    # Si jitter_window_seconds cambió, broadcast config_update a workstations conectadas
    if "jitter_window_seconds" in update_data and update_data["jitter_window_seconds"] != old_jitter:
        await _broadcast_config_update_to_org(db, str(organization.id))
    
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
        # Generar params enriquecidos para check_update (zero-query)
        update_info = S3UpdateService().get_broadcast_update_info(
            target_version=organization.target_version
        )
        params = {}
        if update_info:
            params = {
                "download_url": update_info["download_url"],
                "version": update_info["version"],
                "file_size": update_info["file_size"],
                "auto_update_enabled": True,
            }

            # Push-based distribution: actualizar state map → Redis
            try:
                state_map = get_state_map_service()
                push_service = get_push_distribution_service()

                await state_map.update_msi(
                    org_id=str(org_id),
                    msi_version=update_info["version"],
                    msi_url=update_info["download_url"],
                )

                # Push a workstations online vía PushDistributionService
                enviados = await push_service.push_msi_update(
                    org_id=str(org_id),
                    msi_version=update_info["version"],
                    download_url=update_info["download_url"],
                    file_size=update_info["file_size"],
                )

                logger.info(
                    "push.msi_auto_update_completa: org_id=%s, version=%s, ws_notificadas=%d",
                    org_id, update_info["version"], enviados,
                )
            except Exception as e:
                logger.error(
                    "push.msi_auto_update_error: org_id=%s, error=%s",
                    org_id, str(e),
                )
        else:
            logger.warning(
                "S3 no disponible para broadcast check_update, "
                "usando fallback legacy (params vacío)"
            )

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
                    "params": params,
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

@router.get(
    "/{org_id}/vlans-without-devices",
    summary="VLANs sin dispositivos activos",
)
def get_vlans_without_devices(
    org_id: UUID,
    current_user: User = Depends(require_operator_or_admin),
    db: Session = Depends(get_db),
):
    """Retorna las VLANs de la organización que no tienen dispositivos activos asignados."""
    # Operador solo puede consultar su propia organización
    if current_user.role == UserRole.OPERATOR and str(current_user.organization_id) != str(org_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo puede consultar su propia organización",
        )

    from app.models.vlan import VLAN as VLANModel
    from app.models.device import Device

    vlans = db.query(VLANModel).filter(VLANModel.organization_id == org_id).all()

    vlans_without = []
    for vlan in vlans:
        count = db.query(Device).filter(
            Device.vlan_id == vlan.id,
            Device.is_active == True,
        ).count()
        if count == 0:
            vlans_without.append({"id": str(vlan.id), "name": vlan.name})

    return {
        "count": len(vlans_without),
        "total_vlans": len(vlans),
        "vlans": vlans_without,
    }


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
    body: ForcedContingencyRequest,
    current_user: User = Depends(require_operator_or_admin),
    db: Session = Depends(get_db)
):
    """
    Activar o desactivar contingencia forzada para una organización.

    Al ACTIVAR: solo propaga a VLANs que no estaban en contingencia (marca contingency_inherited=True).
    Al DESACTIVAR con force_all=False (default): solo deshabilita VLANs con contingency_inherited=True.
    Al DESACTIVAR con force_all=True: deshabilita TODAS las VLANs y workstations de la org.
    """
    from app.models.vlan import VLAN as VLANModel
    from app.models.workstation import Workstation
    from app.models.device import Device
    from app.services.websocket_manager import connection_manager

    if current_user.role == UserRole.OPERATOR and current_user.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para modificar esta organización"
        )

    organization = db.query(Organization).filter(Organization.id == org_id).first()
    if not organization:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organización no encontrada")

    organization.forced_contingency = body.enabled

    # Determinar qué workstations notificar vía WebSocket
    workstations_to_notify: list[Workstation] = []

    if body.enabled:
        # Activación: solo afecta VLANs que aún no estaban en contingencia
        vlans_to_activate = db.query(VLANModel).filter(
            VLANModel.organization_id == org_id,
            VLANModel.forced_contingency == False,
        ).all()
        for vlan in vlans_to_activate:
            vlan.forced_contingency = True
            vlan.contingency_inherited = True

        # Notificar a TODAS las workstations (el mensaje incluye la IP de impresora)
        workstations_to_notify = db.query(Workstation).filter(
            Workstation.organization_id == org_id
        ).all()

    else:
        if body.force_all:
            # Desactivación forzada: deshabilitar TODAS las VLANs y limpiar flag
            db.query(VLANModel).filter(
                VLANModel.organization_id == org_id
            ).update({"forced_contingency": False, "contingency_inherited": False}, synchronize_session=False)

            # Limpiar forced_contingency individual de todas las workstations de la org
            db.query(Workstation).filter(
                Workstation.organization_id == org_id
            ).update({"forced_contingency": False}, synchronize_session=False)

            workstations_to_notify = db.query(Workstation).filter(
                Workstation.organization_id == org_id
            ).all()
        else:
            # Desactivación inteligente: solo VLANs heredadas por esta org
            inherited_vlans = db.query(VLANModel).filter(
                VLANModel.organization_id == org_id,
                VLANModel.contingency_inherited == True,
            ).all()
            for vlan in inherited_vlans:
                vlan.forced_contingency = False
                vlan.contingency_inherited = False
                # Solo workstations sin contingencia individual propia
                ws_list = db.query(Workstation).filter(
                    Workstation.vlan_id == vlan.id,
                    Workstation.forced_contingency == False,
                ).all()
                workstations_to_notify.extend(ws_list)

    db.commit()
    db.refresh(organization)

    logger.info(
        "Contingencia org actualizada: org_id=%s, enabled=%s, force_all=%s, admin_id=%s",
        org_id, body.enabled, body.force_all, current_user.id,
    )

    # Notificar vía WebSocket
    for ws in workstations_to_notify:
        printer_ip = None
        if body.enabled:
            if ws.default_printer_id:
                printer = db.query(Device).filter(Device.id == ws.default_printer_id).first()
                if printer:
                    printer_ip = printer.ip_address
            if not printer_ip and ws.vlan_id:
                ws_vlan = db.query(VLANModel).filter(VLANModel.id == ws.vlan_id).first()
                if ws_vlan and ws_vlan.default_device_id:
                    default_dev = db.query(Device).filter(Device.id == ws_vlan.default_device_id).first()
                    if default_dev:
                        printer_ip = default_dev.ip_address
            if not printer_ip and ws.vlan_id:
                first_device = db.query(Device).filter(
                    Device.vlan_id == ws.vlan_id,
                    Device.organization_id == org_id,
                    Device.is_active == True,
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
async def set_target_version(
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

    # Push-based distribution: actualizar state map → Redis → push a workstations
    if body.version:
        try:
            state_map = get_state_map_service()
            push_service = get_push_distribution_service()

            # Obtener info de MSI desde S3 para enriquecer el push message
            update_info = S3UpdateService().get_broadcast_update_info(
                target_version=body.version
            )

            if update_info:
                # Actualizar state map (publica automáticamente a Redis)
                await state_map.update_msi(
                    org_id=str(org_id),
                    msi_version=update_info["version"],
                    msi_url=update_info["download_url"],
                )

                # Push a workstations online
                enviados = await push_service.push_msi_update(
                    org_id=str(org_id),
                    msi_version=update_info["version"],
                    download_url=update_info["download_url"],
                    file_size=update_info["file_size"],
                )

                logger.info(
                    "push.msi_target_version_completa: org_id=%s, version=%s, ws_notificadas=%d",
                    org_id, body.version, enviados,
                )
            else:
                logger.warning(
                    "push.msi_target_version_sin_s3: org_id=%s, version=%s, "
                    "S3 no disponible, workstations se sincronizarán en próximo registro",
                    org_id, body.version,
                )
        except Exception as e:
            logger.error(
                "push.msi_target_version_error: org_id=%s, version=%s, error=%s",
                org_id, body.version, str(e),
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

    # Generar params enriquecidos si es check_update con auto_update habilitado (zero-query)
    params = {}
    if command_type == "check_update" and organization.auto_update_enabled:
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
            logger.warning(
                "S3 no disponible para broadcast check_update, "
                "usando fallback legacy (params vacío)"
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

    logger.info(
        "Comando Organización enviado: org_id=%s, command_type=%s, dispatched=%d, admin_id=%s",
        org_id, command_type, dispatched, current_user.id,
    )

    return {"command_type": command_type, "organization_id": str(org_id), "dispatched": dispatched}



# === ENDPOINTS DE CERTIFICADO ECDSA ===

@router.post("/{org_id}/certificate/generate", status_code=status.HTTP_201_CREATED)
def generate_certificate(
    request: Request,
    org_id: UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Generar un certificado ECDSA para una organización (solo Admin).

    Genera un par de claves ECDSA P-256, cifra la clave privada con AES-256-GCM,
    sube el certificado público a S3 y almacena los metadatos en la organización.

    Solo se permite generar si la organización no tiene certificado previo.
    Para renovar un certificado existente, usar el endpoint de rotación.
    """
    # 1. Buscar la organización
    organization = db.query(Organization).filter(Organization.id == org_id).first()

    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organización con ID {org_id} no encontrada"
        )

    # 2. Verificar que no tenga certificado previo
    if organization.ecdsa_cert_version and organization.ecdsa_cert_version > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La organización ya tiene un certificado. Use el endpoint de rotación."
        )

    # 3. Generar par de claves ECDSA
    encrypted_private_key, cert_pem, expires_at = CryptoService.generate_key_pair(
        str(org_id), settings.SECRET_KEY
    )

    # 4. Subir certificado público a S3
    cert_url = S3ConfigService().upload_cert(str(org_id), 1, cert_pem)

    # 5. Actualizar campos de la organización
    organization.ecdsa_private_key_encrypted = encrypted_private_key
    organization.ecdsa_cert_s3_key = f"certs/{org_id}/v1.cer"
    organization.ecdsa_cert_version = 1
    organization.ecdsa_cert_expires_at = expires_at

    # Computar SHA256 del certificado para validación de integridad en workstations
    import hashlib
    cert_hash = hashlib.sha256(cert_pem.encode("utf-8")).hexdigest()
    organization.ecdsa_cert_hash = cert_hash

    # 6. Commit a base de datos
    db.commit()
    db.refresh(organization)

    # 7. Registrar en auditoría
    audit_service = AuditService()
    audit_service.log_action(
        db=db,
        action_type="config_change",
        entity_type="organization",
        entity_id=str(org_id),
        user_id=str(current_user.id),
        organization_id=str(org_id),
        old_values={},
        new_values={
            "cert_version": 1,
            "expires_at": expires_at.isoformat(),
        },
        ip_address=get_client_ip(request)
    )

    logger.info(
        "Certificado ECDSA generado: org_id=%s, cert_version=1, expires_at=%s, admin_id=%s",
        org_id, expires_at.isoformat(), current_user.id,
    )

    # 8. Retornar respuesta
    return {
        "cert_version": 1,
        "cert_url": cert_url,
        "expires_at": expires_at.isoformat(),
        "message": "Certificado generado exitosamente",
    }


@router.post("/{org_id}/certificate/rotate", status_code=status.HTTP_200_OK)
async def rotate_certificate(
    request: Request,
    org_id: UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Rotar el certificado ECDSA de una organización (solo Admin).

    Genera un nuevo par de claves ECDSA P-256, re-firma todos los ActionConfigs
    activos de la organización con la nueva clave, sube el nuevo certificado a S3
    y notifica a las workstations online via WebSocket.

    El certificado anterior se mantiene en S3 (no se elimina) para permitir
    que workstations offline validen configs firmados con la versión previa
    durante un período de transición.
    """
    # 1. Buscar la organización
    organization = db.query(Organization).filter(Organization.id == org_id).first()

    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organización con ID {org_id} no encontrada"
        )

    # 2. Verificar que la organización TIENE un certificado previo
    if not organization.ecdsa_cert_version or organization.ecdsa_cert_version == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La organización no tiene certificado. Genere uno primero."
        )

    old_cert_version = organization.ecdsa_cert_version

    # 3. Generar nuevo par de claves ECDSA
    encrypted_private_key, cert_pem, expires_at = CryptoService.generate_key_pair(
        str(org_id), settings.SECRET_KEY
    )

    # 4. Nueva versión del certificado
    new_version = old_cert_version + 1

    # 5. Subir nuevo certificado público a S3
    cert_url = S3ConfigService().upload_cert(str(org_id), new_version, cert_pem)

    # 6. Actualizar campos de la organización en BD
    organization.ecdsa_private_key_encrypted = encrypted_private_key
    organization.ecdsa_cert_s3_key = f"certs/{org_id}/v{new_version}.cer"
    organization.ecdsa_cert_version = new_version
    organization.ecdsa_cert_expires_at = expires_at

    # 7. Re-firmar TODOS los ActionConfigs activos de la organización
    active_configs = db.query(ActionConfig).filter(
        ActionConfig.organization_id == org_id,
        ActionConfig.is_active == True
    ).all()

    configs_re_signed = 0
    s3_service = S3ConfigService()

    for config in active_configs:
        # Resolver templates de servidor antes de re-firmar
        from app.api.v1.endpoints.action_config import _resolve_server_templates
        resolved_json = _resolve_server_templates(config.config_json, str(org_id))

        # Firmar con la nueva clave privada
        hash_full, signature_b64 = CryptoService.sign_config(
            encrypted_private_key, resolved_json, settings.SECRET_KEY, str(org_id)
        )

        # Construir JSON envolvente firmado
        signed_json = CryptoService.build_signed_config(
            resolved_json, hash_full, signature_b64, new_version
        )

        # Subir config re-firmado a S3
        new_s3_key = s3_service.upload_signed_config(str(org_id), hash_full[:8], signed_json)

        # Actualizar storage_path del config
        config.storage_path = new_s3_key
        configs_re_signed += 1

    # 8. Commit a base de datos
    db.commit()
    db.refresh(organization)

    # 9. WebSocket broadcast a workstations online de la organización
    workstations = db.query(Workstation).filter(
        Workstation.organization_id == org_id
    ).all()

    cert_rotated_message = {
        "type": "cert_rotated",
        "cert_url": cert_url,
        "cert_version": new_version,
    }

    for ws in workstations:
        ws_id = str(ws.id)
        if connection_manager.is_workstation_online(ws_id):
            await connection_manager.send_to_workstation(ws_id, cert_rotated_message)

    # 9.1 Push-based distribution: actualizar state map → Redis → push a workstations
    try:
        state_map = get_state_map_service()
        push_service = get_push_distribution_service()

        # Actualizar state map (publica automáticamente a Redis)
        await state_map.update_cert(
            org_id=str(org_id),
            cert_version=new_version,
            cert_url=cert_url,
        )

        # Push a workstations online vía PushDistributionService
        enviados = await push_service.push_cert_rotation(
            org_id=str(org_id),
            cert_version=new_version,
            cert_url=cert_url,
        )

        logger.info(
            "push.cert_rotacion_completa: org_id=%s, cert_version=%d, ws_notificadas=%d",
            org_id, new_version, enviados,
        )
    except Exception as e:
        logger.error(
            "push.cert_rotacion_error: org_id=%s, cert_version=%d, error=%s",
            org_id, new_version, str(e),
        )

    # 10. Registrar en auditoría
    audit_service = AuditService()
    audit_service.log_action(
        db=db,
        action_type="config_change",
        entity_type="organization",
        entity_id=str(org_id),
        user_id=str(current_user.id),
        organization_id=str(org_id),
        old_values={
            "cert_version": old_cert_version,
        },
        new_values={
            "cert_version": new_version,
            "expires_at": expires_at.isoformat(),
            "configs_re_signed": configs_re_signed,
        },
        ip_address=get_client_ip(request)
    )

    logger.info(
        "Certificado ECDSA rotado: org_id=%s, v%d→v%d, configs_re_signed=%d, admin_id=%s",
        org_id, old_cert_version, new_version, configs_re_signed, current_user.id,
    )

    # 11. Retornar respuesta
    return {
        "cert_version": new_version,
        "cert_url": cert_url,
        "expires_at": expires_at.isoformat(),
        "configs_re_signed": configs_re_signed,
        "message": "Certificado rotado exitosamente",
    }


@router.get("/{org_id}/certificate/info")
def get_certificate_info(
    org_id: UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Obtener información del certificado ECDSA de una organización (solo Admin).
    """
    # 1. Buscar la organización
    organization = db.query(Organization).filter(Organization.id == org_id).first()

    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organización con ID {org_id} no encontrada"
        )

    # 2. Si no tiene certificado generado
    if not organization.ecdsa_cert_version or organization.ecdsa_cert_version == 0:
        return {
            "has_certificate": False,
            "cert_version": 0,
            "cert_url": None,
            "expires_at": None,
            "signature_paused": False,
            "signature_paused_until": None,
        }

    # 3. Construir URL pública del certificado
    cert_url = S3ConfigService().get_public_url(organization.ecdsa_cert_s3_key)

    # 4. Evaluar si la firma está pausada temporalmente
    from datetime import datetime, timezone
    signature_paused = (
        organization.signature_paused_until is not None
        and organization.signature_paused_until > datetime.now(timezone.utc).replace(tzinfo=None)
    )

    return {
        "has_certificate": True,
        "cert_version": organization.ecdsa_cert_version,
        "cert_url": cert_url,
        "expires_at": organization.ecdsa_cert_expires_at.isoformat() if organization.ecdsa_cert_expires_at else None,
        "signature_paused": signature_paused,
        "signature_paused_until": organization.signature_paused_until.isoformat() if signature_paused else None,
    }


# === ENDPOINT DE PAUSA DE FIRMA (MODO COMPATIBILIDAD LEGACY) ===


@router.put("/{org_id}/certificate/signature-pause", status_code=status.HTTP_200_OK)
def toggle_signature_pause(
    request: Request,
    org_id: UUID,
    duration_minutes: int = Query(
        default=30, ge=5, le=120,
        description="Duración de la pausa en minutos (5-120). Ignorado si pause=false."
    ),
    pause: bool = Query(
        default=True,
        description="true para activar pausa, false para desactivar"
    ),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Activa o desactiva temporalmente la pausa de firma ECDSA para una organización.

    Cuando la pausa está activa, el endpoint /config/download sirve configuraciones
    sin firma digital. Esto permite que workstations con versiones legacy descarguen
    la config, apliquen AutoUpdateEnabled=1, y se actualicen automáticamente.

    La pausa auto-expira después de `duration_minutes`. No requiere intervención
    manual para restaurar la firma.

    Solo accesible por Admin.
    """
    from datetime import datetime, timedelta, timezone

    organization = db.query(Organization).filter(Organization.id == org_id).first()

    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organización con ID {org_id} no encontrada"
        )

    # Verificar que la org tiene certificado activo (no tiene sentido pausar si no hay firma)
    if not organization.ecdsa_cert_version or organization.ecdsa_cert_version == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La organización no tiene certificado ECDSA activo. No hay firma que pausar."
        )

    if pause:
        # Activar pausa
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        organization.signature_paused_until = now + timedelta(minutes=duration_minutes)
        db.commit()

        # Auditoría
        from app.services.audit import AuditService
        AuditService().log_action(
            db=db,
            action_type="config_change",
            entity_type="organization",
            entity_id=str(org_id),
            user_id=str(current_user.id),
            organization_id=str(org_id),
            old_values={"signature_paused_until": None},
            new_values={
                "signature_paused_until": organization.signature_paused_until.isoformat(),
                "duration_minutes": duration_minutes,
            },
            ip_address=get_client_ip(request),
        )

        logger.info(
            "[ORG] Firma ECDSA PAUSADA: org_id=%s, hasta=%s (%d min), por user=%s",
            org_id, organization.signature_paused_until.isoformat(),
            duration_minutes, current_user.id,
        )

        return {
            "paused": True,
            "paused_until": organization.signature_paused_until.isoformat(),
            "duration_minutes": duration_minutes,
            "message": f"Firma ECDSA pausada por {duration_minutes} minutos. Auto-expira.",
        }
    else:
        # Desactivar pausa (restaurar firma inmediatamente)
        old_value = organization.signature_paused_until
        organization.signature_paused_until = None
        db.commit()

        # Auditoría
        from app.services.audit import AuditService
        AuditService().log_action(
            db=db,
            action_type="config_change",
            entity_type="organization",
            entity_id=str(org_id),
            user_id=str(current_user.id),
            organization_id=str(org_id),
            old_values={
                "signature_paused_until": old_value.isoformat() if old_value else None,
            },
            new_values={"signature_paused_until": None},
            ip_address=get_client_ip(request),
        )

        logger.info(
            "[ORG] Firma ECDSA RESTAURADA: org_id=%s, por user=%s",
            org_id, current_user.id,
        )

        return {
            "paused": False,
            "paused_until": None,
            "message": "Firma ECDSA restaurada. Todas las configs se sirven firmadas.",
        }
