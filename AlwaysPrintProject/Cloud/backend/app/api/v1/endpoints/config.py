"""
Endpoints de gestión de configuración global y configuración efectiva.

Este módulo define los endpoints para:
- Obtener configuración global
- Actualizar configuración global
- Obtener configuración efectiva de una workstation (autenticación por IP pública)
"""

import json
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.utils import get_client_ip
from app.models.organization import PublicIP
from app.models.config import GlobalConfig, VLANConfig, WorkstationConfig
from app.models.user import User, UserRole
from app.models.workstation import Workstation
from app.schemas import GlobalConfigUpdate, GlobalConfigResponse
from app.services.config import ConfigService
from app.services.audit import AuditService

router = APIRouter()

# Router para el endpoint de configuración efectiva autenticado por IP pública
workstation_config_router = APIRouter()


# === FUNCIONES AUXILIARES PARA CONFIGURACIÓN EFECTIVA ===


def _resolve_effective_config(
    global_config: GlobalConfig,
    vlan_config: Optional[VLANConfig],
    workstation_config: Optional[WorkstationConfig],
) -> dict:
    """
    Resuelve la configuración efectiva aplicando la jerarquía de precedencia.

    Orden de precedencia: WorkstationConfig > VLANConfig > GlobalConfig.
    Para cada campo, se usa el valor del nivel más específico que no sea None.

    Args:
        global_config: Configuración global (siempre existe, valores por defecto)
        vlan_config: Configuración de VLAN (puede ser None)
        workstation_config: Configuración de workstation (puede ser None)

    Returns:
        Diccionario con la configuración efectiva resuelta
    """
    # Campos a resolver con la jerarquía
    fields = [
        "corporate_queue_name",
        "search_targets",
        "pending_task_polling_minutes",
        "bootstrap_domains",
        "connectivity_checks",
        "locale",
        "telemetry_enabled",
        "telemetry_interval_seconds",
    ]

    config = {}
    sources = {}

    for field in fields:
        # 1. WorkstationConfig tiene mayor precedencia
        if workstation_config and getattr(workstation_config, field, None) is not None:
            config[field] = getattr(workstation_config, field)
            sources[field] = "workstation"
        # 2. VLANConfig tiene precedencia intermedia
        elif vlan_config and getattr(vlan_config, field, None) is not None:
            config[field] = getattr(vlan_config, field)
            sources[field] = "vlan"
        # 3. GlobalConfig es el fallback
        else:
            config[field] = getattr(global_config, field)
            sources[field] = "global"

    # Aplicar valores por defecto cuando el campo resuelto es None
    if config.get("connectivity_checks") is None:
        config["connectivity_checks"] = []
    if config.get("locale") is None:
        config["locale"] = ""
    if config.get("telemetry_enabled") is None:
        config["telemetry_enabled"] = True
    if config.get("telemetry_interval_seconds") is None:
        config["telemetry_interval_seconds"] = 300
    if config.get("search_targets") is None:
        config["search_targets"] = None

    config["source"] = sources
    return config


# === ENDPOINT DE CONFIGURACIÓN EFECTIVA (AUTENTICACIÓN POR IP PÚBLICA) ===


@workstation_config_router.get("/{workstation_id}/config")
def get_effective_config_by_ip(
    workstation_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Obtener configuración efectiva de una workstation.

    Soporta dos métodos de autenticación:
    - Token Bearer (para dashboard): usa la cuenta del usuario autenticado
    - IP pública (para Tray clients): sin headers de autorización

    La respuesta JSON se serializa con claves en orden alfabético fijo para garantizar
    un hash SHA-256 estable en el cliente.

    Args:
        workstation_id: UUID de la workstation
        request: Objeto Request para obtener la IP del cliente
        db: Sesión de base de datos

    Returns:
        Response JSON con configuración efectiva (claves en orden alfabético)

    Raises:
        HTTPException 404: Workstation no encontrada o no pertenece a la cuenta
    """
    # Resolver organization_id según método de autenticación disponible
    organization_id = _authenticate_request(request, db)

    if organization_id == "__admin__":
        # Admin autenticado: buscar workstation sin filtro de organización
        workstation = db.query(Workstation).filter(
            Workstation.id == workstation_id,
        ).first()
    elif organization_id:
        # Buscar la workstation verificando que pertenece a la organización
        workstation = db.query(Workstation).filter(
            Workstation.id == workstation_id,
            Workstation.organization_id == organization_id,
        ).first()
    else:
        # Sin organización resuelta → 404
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workstation con ID {workstation_id} no encontrada"
        )

    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workstation con ID {workstation_id} no encontrada"
        )

    # Obtener configuración global de la cuenta (siempre debe existir)
    global_config = db.query(GlobalConfig).filter(
        GlobalConfig.organization_id == workstation.organization_id
    ).first()

    if not global_config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workstation con ID {workstation_id} no encontrada"
        )

    # Obtener VLANConfig si la workstation pertenece a una VLAN
    vlan_config = None
    if workstation.vlan_id:
        vlan_config = db.query(VLANConfig).filter(
            VLANConfig.vlan_id == workstation.vlan_id
        ).first()

    # Obtener WorkstationConfig si existe
    ws_config = db.query(WorkstationConfig).filter(
        WorkstationConfig.workstation_id == workstation_id
    ).first()

    # Resolver configuración efectiva con jerarquía de precedencia
    effective_config = _resolve_effective_config(global_config, vlan_config, ws_config)

    # Eliminar campo 'source' de la respuesta al cliente (solo uso interno del dashboard)
    effective_config.pop("source", None)

    # Serializar con claves en orden alfabético para hash SHA-256 estable
    response_json = json.dumps(effective_config, sort_keys=True, ensure_ascii=False)

    return Response(
        content=response_json,
        media_type="application/json",
    )


def _authenticate_request(request: Request, db: Session):
    """
    Resuelve el organization_id del cliente usando token Bearer o IP pública.

    Intenta primero autenticación por token Bearer (para dashboard).
    Si no hay token o es inválido, usa la IP pública del cliente (para Tray).

    Args:
        request: Objeto Request de FastAPI
        db: Sesión de base de datos

    Returns:
        UUID del organization_id o None si no se puede autenticar
    """
    from app.core.security import decode_access_token

    # Intentar autenticación por token Bearer (dashboard)
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        try:
            token = auth_header[7:]
            payload = decode_access_token(token)
            user_id = payload.get("sub")
            if user_id:
                user = db.query(User).filter(User.id == user_id).first()
                if user:
                    if user.role == UserRole.ADMIN:
                        # Admin: buscar la workstation sin filtro de organización
                        # Retornar un valor especial que indica "sin filtro"
                        return "__admin__"
                    elif user.organization_id:
                        return user.organization_id
        except Exception:
            pass  # Si falla el token, intentar por IP

    # Autenticación por IP pública (Tray clients)
    client_ip = get_client_ip(request)

    public_ip_record = db.query(PublicIP).filter(
        PublicIP.ip_address == client_ip,
        PublicIP.is_authorized == True,
    ).first()

    if public_ip_record and public_ip_record.organization_id:
        return public_ip_record.organization_id

    return None


# === ENDPOINTS DE CONFIGURACIÓN GLOBAL (AUTENTICACIÓN POR TOKEN) ===


@router.get("/global", response_model=GlobalConfigResponse)
def get_global_config(
    organization_id: str = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtener configuración global de la organización.

    Si no existe configuración, retorna valores por defecto en lugar de 404.

    - Admin: puede ver configuración de cualquier organización (debe especificar organization_id)
    - Operador: solo puede ver configuración de su organización

    Args:
        organization_id: ID de la organización (requerido para Admin, ignorado para Operador)
        current_user: Usuario autenticado
        db: Sesión de base de datos

    Returns:
        GlobalConfigResponse con la configuración global o valores por defecto

    Raises:
        HTTPException 400: organization_id requerido para Admin
        HTTPException 403: Sin permisos
    """
    # Determinar qué organización usar
    if current_user.role == UserRole.ADMIN:
        if not organization_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="organization_id requerido para administradores"
            )
        target_organization_id = organization_id
    else:
        # Operador o ReadOnly: usar su organización asignada
        if not current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Usuario sin cuenta asignada"
            )
        target_organization_id = str(current_user.organization_id)

    config = db.query(GlobalConfig).filter(GlobalConfig.organization_id == target_organization_id).first()

    if not config:
        # Retornar configuración con valores por defecto en lugar de 404
        # Esto evita errores en consola del navegador
        from datetime import datetime, timezone
        return GlobalConfigResponse(
            id=None,  # Indica que no existe en BD
            organization_id=target_organization_id,
            corporate_queue_name="",
            search_targets=None,
            pending_task_polling_minutes=5,
            bootstrap_domains="",
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None)
        )

    return config


@router.put("/global", response_model=GlobalConfigResponse)
def update_global_config(
    request: Request,
    config_data: GlobalConfigUpdate,
    organization_id: str = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Actualizar configuración global de la organización.

    - Admin: puede actualizar configuración de cualquier organización (debe especificar organization_id)
    - Operador: solo puede actualizar configuración de su organización

    Args:
        config_data: Datos de configuración a actualizar
        organization_id: ID de la organización (requerido para Admin, ignorado para Operador)
        current_user: Usuario autenticado
        db: Sesión de base de datos

    Returns:
        GlobalConfigResponse con la configuración actualizada

    Raises:
        HTTPException 400: organization_id requerido para Admin
        HTTPException 403: Sin permisos
    """
    # Determinar qué organización usar
    if current_user.role == UserRole.ADMIN:
        if not organization_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="organization_id requerido para administradores"
            )
        target_organization_id = organization_id
    else:
        # Operador o ReadOnly: usar su organización asignada
        if not current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Usuario sin cuenta asignada"
            )
        target_organization_id = str(current_user.organization_id)

    config_service = ConfigService()

    # Obtener configuración actual
    config = db.query(GlobalConfig).filter(GlobalConfig.organization_id == target_organization_id).first()

    if not config:
        # Crear configuración si no existe
        config = config_service.create_global_config(
            db=db,
            organization_id=target_organization_id,
            **config_data.model_dump(exclude_unset=True)
        )
    else:
        # Actualizar configuración existente
        old_values = {
            "corporate_queue_name": config.corporate_queue_name,
            "search_targets": config.search_targets,
            "pending_task_polling_minutes": config.pending_task_polling_minutes,
            "bootstrap_domains": config.bootstrap_domains
        }

        config = config_service.update_global_config(
            db=db,
            organization_id=target_organization_id,
            **config_data.model_dump(exclude_unset=True)
        )

        # Registrar en auditoría
        audit_service = AuditService()
        audit_service.log_config_change(
            db=db,
            entity_type="global_config",
            entity_id=str(config.id),
            user_id=str(current_user.id),
            organization_id=str(target_organization_id),
            old_config=old_values,
            new_config=config_data.model_dump(exclude_unset=True),
            ip_address=get_client_ip(request)
        )

    return config
