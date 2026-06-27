"""
Endpoints para gestión de configuraciones de acciones administrativas.
"""

import logging
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User, UserRole
from app.models.organization import Organization
from app.models.action_config import ActionConfig
from app.schemas.action_config import (
    ActionConfigUpload,
    ActionConfigUpdate,
    ActionConfigInfo,
    ActionConfigDetail,
    ActionConfigDownloadInfo,
)
from app.services.action_config import ActionConfigService, DuplicateConfigError
from app.services.crypto_service import CryptoService

logger = logging.getLogger(__name__)

router = APIRouter()


async def _notify_workstations_config_changed(db: Session, organization_id) -> int:
    """
    Envía mensaje 'action_config_changed' a todas las workstations online de una organización.
    Las workstations al recibir este mensaje re-verifican su configuración de acciones.
    """
    from app.services.websocket_manager import connection_manager
    from app.models.workstation import Workstation

    workstations = db.query(Workstation).filter(
        Workstation.organization_id == organization_id
    ).all()

    message = {"type": "action_config_changed"}
    dispatched = 0

    for ws in workstations:
        ws_id = str(ws.id)
        if connection_manager.is_workstation_online(ws_id):
            await connection_manager.send_to_workstation(ws_id, message)
            dispatched += 1

    if dispatched > 0:
        logger.info(
            "ActionConfig changed: notificadas %d workstations de org %s",
            dispatched, organization_id
        )

    return dispatched


# Caché en memoria de configs firmadas por worker.
# Key: (config_id, config_hash, cert_version) → signed_json string.
# Se invalida naturalmente cuando config cambia (nuevo hash) o cert rota (nueva version).
_signed_config_cache: dict[tuple, str] = {}


def _get_or_build_signed_config(config: ActionConfig, org: Organization) -> str:
    """
    Retorna el JSON firmado para un config, usando caché en memoria del worker.
    Evita re-firmar en cada request (PBKDF2 100K iter + ECDSA es costoso).
    La caché se invalida automáticamente cuando cambia config_hash o cert_version.
    """
    cache_key = (str(config.id), config.config_hash, org.ecdsa_cert_version)

    cached = _signed_config_cache.get(cache_key)
    if cached:
        return cached

    # No está en caché — firmar y cachear
    hash_full, signature_b64 = CryptoService.sign_config(
        org.ecdsa_private_key_encrypted, config.config_json,
        settings.SECRET_KEY, str(org.id)
    )
    signed_json = CryptoService.build_signed_config(
        config.config_json, hash_full, signature_b64, org.ecdsa_cert_version
    )

    # Guardar en caché (bounded: limpiar si crece demasiado)
    if len(_signed_config_cache) > 1000:
        _signed_config_cache.clear()

    _signed_config_cache[cache_key] = signed_json

    logger.debug(
        "Config firmada y cacheada: config_id=%s, hash=%s, cert_version=%d",
        config.id, config.config_hash, org.ecdsa_cert_version
    )

    return signed_json


# === ENDPOINTS PARA ADMINISTRADORES ===

@router.post(
    "/organizations/{organization_id}/config",
    response_model=ActionConfigInfo,
    status_code=status.HTTP_201_CREATED,
    summary="Subir configuración de acciones",
    description="Sube un nuevo archivo de configuración de acciones para una organización, VLAN o workstation"
)
async def upload_action_config(
    organization_id: UUID,
    data: ActionConfigUpload,
    scope: str = "org",
    vlan_id: UUID = None,
    workstation_id: UUID = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Sube una nueva configuración de acciones.
    
    - **scope**: 'org', 'vlan' o 'workstation'
    - **vlan_id**: requerido si scope='vlan'
    - **workstation_id**: requerido si scope='workstation'
    """
    if current_user.role != UserRole.ADMIN and current_user.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para gestionar configuraciones de esta organización"
        )
    
    # Validar scope y parámetros
    if scope not in ("org", "vlan", "workstation"):
        raise HTTPException(status_code=400, detail="scope debe ser 'org', 'vlan' o 'workstation'")
    if scope == "vlan" and not vlan_id:
        raise HTTPException(status_code=400, detail="vlan_id requerido para scope='vlan'")
    if scope == "workstation" and not workstation_id:
        raise HTTPException(status_code=400, detail="workstation_id requerido para scope='workstation'")
    
    try:
        config = ActionConfigService.create_config(
            db=db,
            organization_id=organization_id,
            data=data,
            created_by_id=current_user.id,
            scope=scope,
            vlan_id=str(vlan_id) if vlan_id else None,
            workstation_id=str(workstation_id) if workstation_id else None
        )
        
        # Si se creó activa, notificar a las workstations para que re-descarguen
        if config.is_active:
            await _notify_workstations_config_changed(db, organization_id)
        
        return config
    except DuplicateConfigError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/organizations/{organization_id}/config",
    response_model=ActionConfigInfo,
    summary="Obtener configuración activa",
    description="Obtiene la configuración de acciones activa de un scope"
)
def get_active_action_config(
    organization_id: UUID,
    scope: str = "org",
    vlan_id: UUID = None,
    workstation_id: UUID = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Obtiene la configuración de acciones activa de un scope específico.
    Retorna 404 si no hay configuración activa.
    """
    if current_user.role != UserRole.ADMIN and current_user.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para acceder a configuraciones de esta organización"
        )
    
    config = ActionConfigService.get_active_config(
        db, organization_id, scope=scope,
        vlan_id=str(vlan_id) if vlan_id else None,
        workstation_id=str(workstation_id) if workstation_id else None
    )
    
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hay configuración activa para este scope"
        )
    
    return config


@router.get(
    "/organizations/{organization_id}/configs",
    response_model=List[ActionConfigInfo],
    summary="Listar todas las configuraciones",
    description="Lista configuraciones de acciones filtradas por scope"
)
def list_action_configs(
    organization_id: UUID,
    scope: str = "org",
    vlan_id: UUID = None,
    workstation_id: UUID = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Lista configuraciones de acciones filtradas por scope.
    
    - **scope**: 'org', 'vlan' o 'workstation' (default: 'org')
    - **vlan_id**: filtrar por VLAN (solo si scope='vlan')
    - **workstation_id**: filtrar por workstation (solo si scope='workstation')
    """
    if current_user.role != UserRole.ADMIN and current_user.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para acceder a configuraciones de esta organización"
        )
    
    configs = ActionConfigService.get_all_configs(
        db, organization_id, scope=scope,
        vlan_id=str(vlan_id) if vlan_id else None,
        workstation_id=str(workstation_id) if workstation_id else None
    )
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
async def update_action_config(
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
    
    # Validar que la organización tiene certificado ECDSA antes de activar
    if data.is_active:
        org = db.query(Organization).filter(Organization.id == organization_id).first()
        if not org or not org.ecdsa_private_key_encrypted or not org.ecdsa_cert_version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No se puede activar la configuración sin un certificado ECDSA generado para la organización. Genere uno primero desde la página de organización."
            )
    
    updated_config = ActionConfigService.update_config(db, config, data)
    
    # Si se activó una config, notificar a las workstations de la org para que re-descarguen
    if data.is_active and updated_config.is_active:
        await _notify_workstations_config_changed(db, organization_id)
    
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
    description="Obtiene información de la configuración efectiva para una workstation (con herencia jerárquica)"
)
def get_workstation_config_info(
    workstation_id: str,
    db: Session = Depends(get_db)
):
    """
    Obtiene información de la configuración efectiva para una workstation.
    
    Aplica resolución jerárquica: Org (mandatory) > Workstation > VLAN > Org (default).
    Este endpoint NO requiere autenticación (usa workstation_id como identificación).
    """
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
        f"organization_id={workstation.organization_id}, vlan_id={workstation.vlan_id}"
    )
    
    # Resolver configuración efectiva con herencia jerárquica
    config = ActionConfigService.resolve_effective_config(db, workstation.id)
    
    if not config:
        from sqlalchemy import func
        total_configs = db.query(func.count(ActionConfig.id)).filter(
            ActionConfig.organization_id == workstation.organization_id
        ).scalar()
        
        logger.warning(
            f"[ACTION_CONFIG] No hay configuración efectiva para workstation={workstation_id}. "
            f"Total configs en org: {total_configs}"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No hay configuración activa. org_id={workstation.organization_id}"
        )
    
    logger.info(
        f"[ACTION_CONFIG] Configuración efectiva: id={config.id}, scope={config.scope}, "
        f"name={config.name}, hash={config.config_hash}"
    )
    
    # Obtener cert_version y cert_url de la organización (si tiene certificado)
    org = db.query(Organization).filter(Organization.id == workstation.organization_id).first()
    cert_version = org.ecdsa_cert_version if org and org.ecdsa_cert_version else None
    cert_url = None
    if cert_version and org.ecdsa_cert_s3_key:
        from app.services.s3_config_service import S3ConfigService
        cert_url = S3ConfigService().get_public_url(org.ecdsa_cert_s3_key)
    
    return ActionConfigDownloadInfo(
        hash=config.config_hash,
        download_url=f"/api/v1/workstations/{workstation_id}/config/download",
        name=config.name,
        version=config.version,
        cert_version=cert_version,
        cert_url=cert_url
    )


@router.get(
    "/workstations/{workstation_id}/config/download",
    summary="Descargar configuración",
    description="Descarga el JSON de la configuración efectiva (con herencia jerárquica)"
)
def download_workstation_config(
    workstation_id: str,
    db: Session = Depends(get_db)
):
    """
    Descarga el JSON de la configuración efectiva para una workstation.
    Aplica resolución jerárquica: Org (mandatory) > Workstation > VLAN > Org (default).
    """
    from app.models.workstation import Workstation
    workstation = db.query(Workstation).filter(
        Workstation.id == workstation_id
    ).first()
    
    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workstation no encontrada"
        )
    
    # Resolver configuración efectiva con herencia jerárquica
    config = ActionConfigService.resolve_effective_config(db, workstation.id)
    
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hay configuración activa"
        )
    
    # Si la org tiene certificado ECDSA, retornar JSON firmado (con caché en memoria)
    org = db.query(Organization).filter(Organization.id == workstation.organization_id).first()

    if org and org.ecdsa_cert_version and org.ecdsa_cert_version > 0 and org.ecdsa_private_key_encrypted:
        try:
            # Usar config firmada pre-calculada si existe en caché
            signed_json = _get_or_build_signed_config(config, org)
            return Response(
                content=signed_json,
                media_type="application/json",
                headers={
                    "Content-Disposition": f'attachment; filename="{config.name}.alwaysconfig"',
                    "X-Config-Hash": config.config_hash,
                    "X-Config-Version": config.version,
                    "X-Config-Scope": config.scope if isinstance(config.scope, str) else config.scope.value,
                    "X-Cert-Version": str(org.ecdsa_cert_version),
                }
            )
        except Exception as e:
            # Si falla, retornar sin firmar como fallback
            logger.error("Error al obtener config firmada: %s", str(e))

    # Fallback: retornar config sin firmar (org sin certificado o error de firma)
    return Response(
        content=config.config_json,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{config.name}.alwaysconfig"',
            "X-Config-Hash": config.config_hash,
            "X-Config-Version": config.version,
            "X-Config-Scope": config.scope if isinstance(config.scope, str) else config.scope.value
        }
    )
