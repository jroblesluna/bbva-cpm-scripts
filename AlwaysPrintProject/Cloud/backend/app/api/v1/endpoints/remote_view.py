"""
Endpoints REST para vista remota de workstations.

Este módulo define los endpoints para:
- Iniciar sesión de vista remota (con verificación de permisos, org config, exclusividad)
- Detener sesión de vista remota
- Consultar estado de sesión activa para una workstation
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User, UserRole
from app.models.workstation import Workstation
from app.models.organization import Organization
from app.schemas.remote_view import RemoteViewConfig
from app.services.remote_view_session import SessionManager
from app.services.websocket_manager import connection_manager
from app.models.audit import ActionType
from app.services.audit import AuditService

router = APIRouter()
logger = logging.getLogger(__name__)

# Instancias de servicios
_session_manager = SessionManager()
_audit_service = AuditService()


# === SCHEMAS DE REQUEST/RESPONSE ===


class RemoteViewStartRequest(BaseModel):
    """Schema de solicitud para iniciar sesión de vista remota."""
    mode: Optional[str] = Field(
        default=None,
        description="Modo de sesión (override de default_mode de org config): screenshot, stream, interactive"
    )
    monitor: int = Field(
        default=0,
        ge=0,
        description="Índice del monitor a capturar"
    )
    viewport_width: Optional[int] = Field(
        default=None,
        ge=100,
        le=7680,
        description="Ancho del viewport del admin para adaptive downscale"
    )
    viewport_height: Optional[int] = Field(
        default=None,
        ge=100,
        le=4320,
        description="Alto del viewport del admin para adaptive downscale"
    )


class RemoteViewStartResponse(BaseModel):
    """Schema de respuesta al iniciar sesión."""
    session_id: str = Field(..., description="UUID de la sesión creada")
    status: str = Field(..., description="Estado inicial: pending_consent")


class RemoteViewStopResponse(BaseModel):
    """Schema de respuesta al detener sesión."""
    session_id: str = Field(..., description="UUID de la sesión cerrada")
    status: str = Field(..., description="Estado final: closed")


class RemoteViewStatusResponse(BaseModel):
    """Schema de respuesta del estado de una sesión activa."""
    active: bool = Field(..., description="Si hay sesión activa/pending para esta workstation")
    session_id: Optional[str] = Field(default=None, description="UUID de la sesión")
    user_id: Optional[str] = Field(default=None, description="UUID del usuario que inició la sesión")
    user_name: Optional[str] = Field(default=None, description="Nombre completo del usuario")
    user_email: Optional[str] = Field(default=None, description="Email del usuario")
    mode: Optional[str] = Field(default=None, description="Modo actual: screenshot, stream, interactive")
    started_at: Optional[str] = Field(default=None, description="Timestamp ISO de inicio de sesión")
    monitor_index: Optional[int] = Field(default=None, description="Índice del monitor capturado")
    resolution: Optional[str] = Field(default=None, description="Resolución de captura actual")


# === ENDPOINTS ===


@router.post(
    "/{workstation_id}/remote-view/start",
    response_model=RemoteViewStartResponse,
    status_code=status.HTTP_200_OK,
    responses={
        403: {"description": "Feature deshabilitado o sin permisos"},
        404: {"description": "Workstation no encontrada"},
        409: {"description": "Workstation offline o sesión ya activa"},
        429: {"description": "Límite de sesiones simultáneas alcanzado"},
    },
)
async def start_remote_view(
    workstation_id: UUID,
    request_body: RemoteViewStartRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Iniciar una sesión de vista remota para una workstation.

    Verificaciones:
    1. Workstation existe y pertenece a la org del usuario (o admin ve todas)
    2. Feature remote_view habilitado en la organización
    3. Workstation online (conexión WebSocket activa)
    4. No existe sesión activa/pending para esta workstation (exclusividad)
    5. Usuario no excede max_concurrent_sessions de la org

    Al pasar todas las verificaciones:
    - Crea sesión en BD con estado pending_consent
    - Envía mensaje remote_view_start a la workstation via WebSocket
    - Retorna session_id con estado pending_consent
    """
    # 1. Verificar que la workstation existe
    workstation = db.query(Workstation).filter(Workstation.id == workstation_id).first()
    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workstation no encontrada",
        )

    # Tenant isolation: operadores solo su org, admins todo
    if current_user.role != UserRole.ADMIN:
        if current_user.organization_id != workstation.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Sin permiso para acceder a esta workstation",
            )

    # 2. Verificar que remote_view está habilitado en la organización
    org = db.query(Organization).filter(Organization.id == workstation.organization_id).first()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organización no encontrada",
        )

    # Parsear configuración remote_view de la org
    rv_config_data = org.remote_view or {"enabled": False}
    try:
        rv_config = RemoteViewConfig(**rv_config_data)
    except Exception:
        rv_config = RemoteViewConfig()

    if not rv_config.enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La vista remota no está habilitada para esta organización",
        )

    # 3. Verificar que la workstation está online
    workstation_id_str = str(workstation_id)
    if not connection_manager.is_workstation_online(workstation_id_str):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La workstation está offline. No se puede iniciar vista remota.",
        )

    # 4. Verificar exclusividad: no debe existir sesión activa/pending para esta WS
    existing_session = _session_manager.get_active_for_workstation(db, workstation_id_str)
    if existing_session is not None:
        # Obtener info del usuario que tiene la sesión activa
        session_user = db.query(User).filter(User.id == existing_session.user_id).first()
        user_display = session_user.full_name if session_user else "otro usuario"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Esta workstation está siendo monitoreada por {user_display}",
        )

    # 5. Verificar límite de sesiones concurrentes del usuario
    max_sessions = rv_config.max_concurrent_sessions
    if max_sessions > 0:
        user_active_sessions = _session_manager.get_active_for_user(db, str(current_user.id))
        if len(user_active_sessions) >= max_sessions:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Límite de sesiones simultáneas alcanzado ({len(user_active_sessions)}/{max_sessions})",
            )

    # Determinar modo de sesión (override del request o default de org)
    mode = request_body.mode or rv_config.default_mode
    # Validar que el modo esté permitido
    if mode not in rv_config.modes_allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Modo '{mode}' no permitido. Modos disponibles: {rv_config.modes_allowed}",
        )

    # Crear sesión en BD
    session = _session_manager.create_session(
        db=db,
        workstation_id=workstation_id_str,
        user_id=str(current_user.id),
        org_id=str(workstation.organization_id),
        mode=mode,
    )

    if session is None:
        # Race condition: otra sesión se creó entre la verificación y la creación
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se pudo crear la sesión. Ya existe una sesión activa para esta workstation.",
        )

    # Si no se requiere consentimiento, activar la sesión inmediatamente
    if not rv_config.require_user_consent:
        _session_manager.accept_session(db, str(session.id))
        # Registrar en relay para routing de frames
        from app.services.remote_view_relay import remote_view_relay
        remote_view_relay.register_session(
            session_id=str(session.id),
            workstation_id=workstation_id_str,
            user_id=str(current_user.id),
        )

    logger.info(
        "Sesión de vista remota iniciada: session_id=%s, workstation=%s, user=%s, mode=%s",
        session.id, workstation_id_str, current_user.email, mode,
    )

    # Determinar resolución y calidad a enviar
    resolution = rv_config.capture_resolution if rv_config.quality_mode == "manual" else "1280x720"
    quality = rv_config.compression_quality if rv_config.quality_mode == "manual" else 70

    # Enviar mensaje remote_view_start a la workstation via WebSocket
    ws_message = {
        "type": "remote_view_start",
        "session_id": str(session.id),
        "mode": mode,
        "resolution": resolution,
        "quality": quality,
        "monitor": request_body.monitor,
        "user_name": current_user.full_name,
        "viewport_width": request_body.viewport_width,
        "viewport_height": request_body.viewport_height,
    }

    await connection_manager.send_to_workstation(workstation_id_str, ws_message)

    # Auditoría: si no se requiere consentimiento, la sesión arranca directamente
    # TODO: Para flujos con consentimiento, el REMOTE_VIEW_START se registra cuando
    # la sesión transiciona a 'active' (vía accept_session en WebSocket handlers)
    if not rv_config.require_user_consent:
        _audit_service.log_action(
            db=db,
            action_type=ActionType.REMOTE_VIEW_START,
            entity_type="RemoteViewSession",
            entity_id=str(session.id),
            user_id=str(current_user.id),
            workstation_id=str(workstation_id),
            organization_id=str(workstation.organization_id),
            new_values={"mode": mode, "consent_given": None},
        )

    return RemoteViewStartResponse(
        session_id=str(session.id),
        status="active" if not rv_config.require_user_consent else "pending_consent",
    )


@router.post(
    "/{workstation_id}/remote-view/stop",
    response_model=RemoteViewStopResponse,
    status_code=status.HTTP_200_OK,
    responses={
        403: {"description": "Sin permisos para cerrar esta sesión"},
        404: {"description": "Workstation o sesión no encontrada"},
    },
)
async def stop_remote_view(
    workstation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Detener una sesión de vista remota activa para una workstation.

    Verificaciones:
    - Existe una sesión activa/pending para esta workstation
    - El usuario es el owner de la sesión O es admin

    Acciones:
    - Finaliza sesión en BD (status=closed, end_reason=admin_closed)
    - Envía remote_view_stop a la workstation via WebSocket
    """
    workstation_id_str = str(workstation_id)

    # Verificar que la workstation existe
    workstation = db.query(Workstation).filter(Workstation.id == workstation_id).first()
    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workstation no encontrada",
        )

    # Obtener sesión activa para esta workstation
    session = _session_manager.get_active_for_workstation(db, workstation_id_str)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hay sesión de vista remota activa para esta workstation",
        )

    # Verificar ownership: el usuario debe ser el owner o admin
    if current_user.role != UserRole.ADMIN:
        if str(session.user_id) != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para cerrar esta sesión",
            )

    session_id_str = str(session.id)

    # Finalizar sesión en BD
    _session_manager.end_session(db, session_id_str, end_reason="admin_closed")

    # Refrescar para obtener ended_at actualizado por end_session
    db.refresh(session)

    # Auditoría: registrar cierre de sesión con duración
    duration = (session.ended_at - session.started_at).total_seconds() if session.ended_at and session.started_at else 0
    _audit_service.log_action(
        db=db,
        action_type=ActionType.REMOTE_VIEW_STOP,
        entity_type="RemoteViewSession",
        entity_id=session_id_str,
        user_id=str(current_user.id),
        workstation_id=str(workstation_id),
        organization_id=str(workstation.organization_id),
        new_values={"duration_seconds": int(duration), "end_reason": "admin_closed"},
    )

    logger.info(
        "Sesión de vista remota detenida: session_id=%s, workstation=%s, cerrada_por=%s",
        session_id_str, workstation_id_str, current_user.email,
    )

    # Enviar remote_view_stop a la workstation via WebSocket
    ws_message = {
        "type": "remote_view_stop",
        "session_id": session_id_str,
    }

    if connection_manager.is_workstation_online(workstation_id_str):
        await connection_manager.send_to_workstation(workstation_id_str, ws_message)

    return RemoteViewStopResponse(
        session_id=session_id_str,
        status="closed",
    )


@router.get(
    "/{workstation_id}/remote-view/status",
    response_model=RemoteViewStatusResponse,
    status_code=status.HTTP_200_OK,
    responses={
        404: {"description": "Workstation no encontrada"},
    },
)
def get_remote_view_status(
    workstation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Consultar el estado de vista remota de una workstation.

    Retorna información de la sesión activa/pending si existe,
    o {active: false} si no hay sesión.

    Accesible por admin (ve todas) u operador (solo su org).
    """
    # Verificar que la workstation existe
    workstation = db.query(Workstation).filter(Workstation.id == workstation_id).first()
    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workstation no encontrada",
        )

    # Tenant isolation: operadores solo su org
    if current_user.role != UserRole.ADMIN:
        if current_user.organization_id != workstation.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Sin permiso para ver esta workstation",
            )

    workstation_id_str = str(workstation_id)

    # Obtener sesión activa/pending para esta workstation
    session = _session_manager.get_active_for_workstation(db, workstation_id_str)

    if session is None:
        return RemoteViewStatusResponse(active=False)

    # Obtener datos del usuario que tiene la sesión
    session_user = db.query(User).filter(User.id == session.user_id).first()
    user_name = session_user.full_name if session_user else "Desconocido"
    user_email = session_user.email if session_user else ""

    # Formatear started_at como ISO string
    started_at_iso = session.started_at.isoformat() if session.started_at else None

    return RemoteViewStatusResponse(
        active=True,
        session_id=str(session.id),
        user_id=str(session.user_id),
        user_name=user_name,
        user_email=user_email,
        mode=session.mode,
        started_at=started_at_iso,
        monitor_index=session.monitor_index,
        resolution=session.resolution,
    )
