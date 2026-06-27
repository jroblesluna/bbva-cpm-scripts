"""
Endpoints para gestión de configuraciones de acciones administrativas.
"""

import logging
import time
import threading
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

# Caché de config_info por workstation_id con TTL de 30 segundos.
# Evita queries repetitivas cuando 66+ workstations pollen cada 30s.
# Key: workstation_id → (timestamp, response_dict)
_config_info_cache: dict[str, tuple[float, dict]] = {}
_CONFIG_INFO_TTL = 30.0  # segundos


async def _notify_workstations_config_changed(db: Session, organization_id) -> int:
    """
    Envía mensaje 'action_config_changed' a todas las workstations online de una organización.
    Las workstations al recibir este mensaje re-verifican su configuración de acciones
    con jitter aleatorio del lado cliente (1-10s) para evitar thundering herd.
    También invalida el caché de config_info para las workstations de la organización.
    """
    from app.services.websocket_manager import connection_manager
    from app.models.workstation import Workstation

    workstations = db.query(Workstation).filter(
        Workstation.organization_id == organization_id
    ).all()

    # Invalidar caché de config_info para todas las workstations de esta org
    for ws in workstations:
        _config_info_cache.pop(str(ws.id), None)

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

# Locks por cache_key para evitar thundering herd (múltiples threads computando lo mismo).
# Solo 1 thread computa la firma; los demás esperan el resultado del caché.
_signed_config_locks: dict[tuple, threading.Lock] = {}
_locks_mutex = threading.Lock()  # Protege acceso al dict de locks

_CACHE_LOCK_TIMEOUT = 10.0  # Segundos máximos de espera por el lock


def _get_lock_for_key(cache_key: tuple) -> threading.Lock:
    """Obtiene o crea un lock específico para una cache_key."""
    with _locks_mutex:
        if cache_key not in _signed_config_locks:
            _signed_config_locks[cache_key] = threading.Lock()
        return _signed_config_locks[cache_key]


def _get_or_build_signed_config_from_data(
    config_id: str, config_hash: str, config_json: str,
    cert_version: int, encrypted_key: str, org_id: str
) -> str:
    """
    Retorna el JSON firmado, usando caché en memoria del worker.
    Acepta datos planos (no objetos ORM) para poder ejecutarse sin sesión de BD activa.

    Usa lock por cache_key para evitar thundering herd: si N requests llegan
    simultáneamente para el mismo config, solo 1 computa la firma y las demás
    esperan el resultado del caché (max 10s de espera).
    """
    cache_key = (config_id, config_hash, cert_version)

    # Fast path: cache hit (sin lock)
    cached = _signed_config_cache.get(cache_key)
    if cached:
        return cached

    # Slow path: cache miss — adquirir lock para esta key
    lock = _get_lock_for_key(cache_key)
    acquired = lock.acquire(timeout=_CACHE_LOCK_TIMEOUT)

    try:
        # Double-check: otro thread pudo haber llenado el caché
        cached = _signed_config_cache.get(cache_key)
        if cached:
            return cached

        if not acquired:
            logger.warning(
                "Cache lock timeout para config_id=%s. Computando firma sin lock (fallback).",
                config_id
            )

        # Computar firma (PBKDF2 + ECDSA ~50ms)
        hash_full, signature_b64 = CryptoService.sign_config(
            encrypted_key, config_json, settings.SECRET_KEY, org_id
        )
        signed_json = CryptoService.build_signed_config(
            config_json, hash_full, signature_b64, cert_version
        )

        # Guardar en caché (bounded: limpiar si crece demasiado)
        if len(_signed_config_cache) > 1000:
            _signed_config_cache.clear()
            with _locks_mutex:
                _signed_config_locks.clear()

        _signed_config_cache[cache_key] = signed_json

        logger.debug(
            "Config firmada y cacheada: config_id=%s, hash=%s, cert_version=%d",
            config_id, config_hash, cert_version
        )

        return signed_json
    finally:
        if acquired:
            lock.release()


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
    
    Usa caché en memoria con TTL de 30s para evitar saturar el pool de conexiones
    cuando 66+ workstations pollen simultáneamente.
    """
    # Check cache first
    cached = _config_info_cache.get(workstation_id)
    if cached:
        cache_time, cache_data = cached
        if time.time() - cache_time < _CONFIG_INFO_TTL:
            # Cache hit — retornar sin tocar BD
            return ActionConfigDownloadInfo(**cache_data)
    
    # Cache miss — proceed with DB queries
    from app.models.workstation import Workstation
    
    workstation = db.query(Workstation).filter(
        Workstation.id == workstation_id
    ).first()
    
    if not workstation:
        logger.warning(f"[ACTION_CONFIG] Workstation no encontrada: id={workstation_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workstation no encontrada"
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
    
    # Obtener cert_version y cert_url de la organización (si tiene certificado)
    org = db.query(Organization).filter(Organization.id == workstation.organization_id).first()
    cert_version = org.ecdsa_cert_version if org and org.ecdsa_cert_version else None
    cert_url = None
    if cert_version and org.ecdsa_cert_s3_key:
        from app.services.s3_config_service import S3ConfigService
        cert_url = S3ConfigService().get_public_url(org.ecdsa_cert_s3_key)
    
    result = ActionConfigDownloadInfo(
        hash=config.config_hash,
        download_url=f"/api/v1/workstations/{workstation_id}/config/download",
        name=config.name,
        version=config.version,
        cert_version=cert_version,
        cert_url=cert_url
    )
    
    # Store in cache
    _config_info_cache[workstation_id] = (time.time(), result.model_dump())
    
    # Cleanup old entries periódicamente (cada 200 entradas)
    if len(_config_info_cache) > 200:
        now = time.time()
        expired = [k for k, (t, _) in _config_info_cache.items() if now - t > _CONFIG_INFO_TTL * 2]
        for k in expired:
            del _config_info_cache[k]
    
    return result


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
    
    La sesión de BD se cierra ANTES del cómputo criptográfico para no retener
    conexiones del pool durante PBKDF2/ECDSA (~50ms).
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
    
    # Extraer todos los datos necesarios ANTES de cerrar la sesión
    config_id = str(config.id)
    config_json = config.config_json
    config_hash = config.config_hash
    config_name = config.name
    config_version = config.version
    config_scope = config.scope if isinstance(config.scope, str) else config.scope.value
    
    org = db.query(Organization).filter(Organization.id == workstation.organization_id).first()
    
    org_has_cert = (
        org is not None
        and org.ecdsa_cert_version is not None
        and org.ecdsa_cert_version > 0
        and org.ecdsa_private_key_encrypted is not None
    )
    
    # Extraer datos de org necesarios para firma (si tiene cert)
    org_id = str(org.id) if org else None
    org_encrypted_key = org.ecdsa_private_key_encrypted if org_has_cert else None
    org_cert_version = org.ecdsa_cert_version if org_has_cert else None
    
    # === CERRAR SESIÓN DE BD — liberar conexión al pool ===
    db.close()
    
    # === A partir de aquí, NO se usa 'db' ni objetos SQLAlchemy ===
    
    if org_has_cert:
        try:
            signed_json = _get_or_build_signed_config_from_data(
                config_id, config_hash, config_json, org_cert_version, org_encrypted_key, org_id
            )
            return Response(
                content=signed_json,
                media_type="application/json",
                headers={
                    "Content-Disposition": f'attachment; filename="{config_name}.alwaysconfig"',
                    "X-Config-Hash": config_hash,
                    "X-Config-Version": config_version,
                    "X-Config-Scope": config_scope,
                    "X-Cert-Version": str(org_cert_version),
                }
            )
        except Exception as e:
            logger.error("Error al obtener config firmada: %s", str(e))

    # Fallback: retornar config sin firmar (org sin certificado o error de firma)
    return Response(
        content=config_json,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{config_name}.alwaysconfig"',
            "X-Config-Hash": config_hash,
            "X-Config-Version": config_version,
            "X-Config-Scope": config_scope
        }
    )
