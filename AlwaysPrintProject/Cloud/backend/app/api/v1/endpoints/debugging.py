"""
Endpoints para capturas de debugging a nivel de organización.

Este módulo implementa:
- CRUD de perfiles de debugging (solo admin)
- Sugerencia de nombre/mensaje por LLM al crear perfil
- Gestión del ciclo de vida de sesiones de debugging (admin + operator)
- Upload de ZIP desde workstation
- Descarga de reporte PDF (presigned S3 URL)
"""

import io
import json
import logging
import uuid
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.debugging import DebuggingProfile, DebuggingSession, DebuggingSessionStatus
from app.models.organization import Organization
from app.models.user import User, UserRole
from app.models.workstation import Workstation
from app.schemas.debugging import (
    DebuggingProfileCreate,
    DebuggingProfileConfirmSave,
    DebuggingProfileListItem,
    DebuggingProfileResponse,
    DebuggingProfileUpdate,
    DebuggingReportURL,
    DebuggingSessionCreate,
    DebuggingSessionListItem,
    DebuggingSessionResponse,
    LLMProfileSuggestion,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# === HELPERS ===


def _verify_llm_enabled(org: Organization) -> None:
    """
    Verifica que la organización tiene LLM habilitado.
    Lanza 403 si no tiene llm_model_id ni openai_api_key.
    """
    if not org.llm_model_id and not org.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "La funcionalidad de debugging requiere LLM habilitado. "
                "Configure llm_model_id u openai_api_key en la organización."
            ),
        )


def _get_user_organization(current_user: User, db: Session) -> Organization:
    """Obtiene la organización del usuario actual."""
    org = db.query(Organization).filter(
        Organization.id == current_user.organization_id
    ).first()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organización del usuario no encontrada",
        )
    return org


def _require_admin(current_user: User) -> None:
    """Verifica que el usuario es admin. Lanza 403 si no."""
    if current_user.role not in (UserRole.ADMIN,):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo administradores pueden gestionar perfiles de debugging",
        )


def _serialize_profile(profile: DebuggingProfile) -> DebuggingProfileResponse:
    """Convierte un modelo DebuggingProfile a schema de respuesta."""
    return DebuggingProfileResponse(
        id=profile.id,
        organization_id=profile.organization_id,
        name=profile.name,
        description=profile.description,
        confirmation_message=profile.confirmation_message,
        external_logs=json.loads(profile.external_logs) if profile.external_logs else [],
        eventlog_groups=json.loads(profile.eventlog_groups) if profile.eventlog_groups else [],
        registry_keys=json.loads(profile.registry_keys) if profile.registry_keys else [],
        monitored_services=json.loads(profile.monitored_services) if profile.monitored_services else [],
        is_active=profile.is_active,
        created_by=profile.created_by,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


async def _get_llm_suggestion(
    org: Organization, description: str, targets: dict
) -> LLMProfileSuggestion:
    """
    Invoca al LLM para sugerir nombre y mensaje de confirmación para un perfil.
    Usa la configuración LLM de la organización (OpenAI o Bedrock).
    """
    from app.services.llm_service import LLMService, LLMServiceError, OpenAIProvider

    prompt = (
        "Eres un asistente que genera nombres descriptivos cortos y mensajes de confirmación "
        "para perfiles de debugging en sistemas de impresión corporativa.\n\n"
        "Dado el siguiente perfil de debugging:\n"
        f"- Descripción: {description}\n"
        f"- Logs externos: {json.dumps(targets.get('external_logs', []))}\n"
        f"- Eventos Windows: {json.dumps(targets.get('eventlog_groups', []))}\n"
        f"- Llaves de registro: {json.dumps(targets.get('registry_keys', []))}\n"
        f"- Servicios: {json.dumps(targets.get('monitored_services', []))}\n\n"
        "Genera:\n"
        "1. Un nombre corto (máximo 60 caracteres) que describa el propósito del debugging\n"
        "2. Un mensaje de confirmación (máximo 200 caracteres) que explique al admin/operador "
        "qué capturará esta sesión de debugging antes de iniciarla\n\n"
        "Responde SOLO en formato JSON:\n"
        '{"name": "...", "message": "..."}\n'
        "No incluyas explicación adicional, solo el JSON."
    )

    try:
        if org.openai_api_key:
            provider = OpenAIProvider()
            provider.api_key = org.openai_api_key
            if org.llm_model_id and any(
                org.llm_model_id.startswith(p) for p in ("gpt-", "o1-", "o3-", "chatgpt-")
            ):
                provider.model = org.llm_model_id
            response_text, _, _ = await provider.invoke(prompt, 300)
        else:
            llm_service = LLMService()
            response_text, _, _ = await llm_service.invoke(prompt, model_id=org.llm_model_id)

        # Parsear respuesta JSON del LLM
        # Buscar JSON en la respuesta (puede venir con markdown code blocks)
        clean_text = response_text.strip()
        if clean_text.startswith("```"):
            # Remover code blocks
            lines = clean_text.split("\n")
            clean_text = "\n".join(
                l for l in lines if not l.strip().startswith("```")
            )
        suggestion_data = json.loads(clean_text)

        return LLMProfileSuggestion(
            suggested_name=suggestion_data.get("name", "Perfil de Debugging")[:60],
            suggested_message=suggestion_data.get("message", "Se capturarán datos de diagnóstico")[:200],
        )

    except (LLMServiceError, json.JSONDecodeError, KeyError) as e:
        logger.warning(
            "[DEBUGGING] Error obteniendo sugerencia LLM: %s. Usando valores por defecto.", e
        )
        # Fallback: generar nombre básico basado en los targets
        parts = []
        if targets.get("monitored_services"):
            parts.append(f"Servicios: {', '.join(targets['monitored_services'][:2])}")
        if targets.get("eventlog_groups"):
            parts.append(f"Eventos: {', '.join(targets['eventlog_groups'][:2])}")
        fallback_name = " + ".join(parts)[:60] if parts else "Perfil de Debugging"

        return LLMProfileSuggestion(
            suggested_name=fallback_name,
            suggested_message="Se capturarán datos de diagnóstico del sistema durante el período configurado",
        )


# === ENDPOINTS DE PERFILES (ADMIN ONLY) ===


@router.post(
    "/profiles",
    response_model=LLMProfileSuggestion,
    status_code=status.HTTP_200_OK,
    summary="Crear perfil de debugging (paso 1: obtener sugerencia LLM)",
)
async def create_profile_get_suggestion(
    payload: DebuggingProfileCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Paso 1 de creación de perfil: envía los targets al LLM para obtener
    sugerencia de nombre y mensaje de confirmación.

    El admin revisa/edita la sugerencia y luego confirma con POST /profiles/confirm.
    Solo accesible por admins. Requiere LLM habilitado en la organización.
    """
    _require_admin(current_user)
    org = _get_user_organization(current_user, db)
    _verify_llm_enabled(org)

    targets = {
        "external_logs": payload.external_logs,
        "eventlog_groups": payload.eventlog_groups,
        "registry_keys": payload.registry_keys,
        "monitored_services": payload.monitored_services,
    }

    suggestion = await _get_llm_suggestion(org, payload.description, targets)
    return suggestion


@router.post(
    "/profiles/confirm",
    response_model=DebuggingProfileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear perfil de debugging (paso 2: confirmar con nombre y mensaje)",
)
async def create_profile_confirm(
    payload: DebuggingProfileCreate,
    confirm: DebuggingProfileConfirmSave,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Paso 2 de creación de perfil: persiste el perfil con el nombre y mensaje
    confirmados por el admin (pueden ser los sugeridos por LLM o editados).

    Solo accesible por admins. Requiere LLM habilitado en la organización.
    """
    _require_admin(current_user)
    org = _get_user_organization(current_user, db)
    _verify_llm_enabled(org)

    profile = DebuggingProfile(
        id=uuid.uuid4(),
        organization_id=org.id,
        name=confirm.name,
        description=payload.description,
        confirmation_message=confirm.confirmation_message,
        external_logs=json.dumps(payload.external_logs),
        eventlog_groups=json.dumps(payload.eventlog_groups),
        registry_keys=json.dumps(payload.registry_keys),
        monitored_services=json.dumps(payload.monitored_services),
        is_active=True,
        created_by=current_user.id,
    )

    db.add(profile)
    db.commit()
    db.refresh(profile)

    logger.info(
        "[DEBUGGING] Perfil creado: id=%s, name='%s', org=%s, por user=%s",
        profile.id, profile.name, org.id, current_user.id,
    )

    return _serialize_profile(profile)


@router.get(
    "/profiles",
    response_model=List[DebuggingProfileListItem],
    status_code=status.HTTP_200_OK,
    summary="Listar perfiles de debugging de la organización",
)
async def list_profiles(
    include_inactive: bool = Query(False, description="Incluir perfiles desactivados"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Lista los perfiles de debugging de la organización del usuario.
    Por defecto solo muestra perfiles activos.
    Accesible por admin y operadores.
    """
    org = _get_user_organization(current_user, db)
    _verify_llm_enabled(org)

    query = db.query(DebuggingProfile).filter(
        DebuggingProfile.organization_id == org.id
    )

    if not include_inactive:
        query = query.filter(DebuggingProfile.is_active == True)

    profiles = query.order_by(DebuggingProfile.created_at.desc()).all()

    return [
        DebuggingProfileListItem(
            id=p.id,
            name=p.name,
            description=p.description,
            confirmation_message=p.confirmation_message,
            is_active=p.is_active,
            created_at=p.created_at,
        )
        for p in profiles
    ]


@router.get(
    "/profiles/{profile_id}",
    response_model=DebuggingProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener detalle de un perfil de debugging",
)
async def get_profile(
    profile_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Retorna el detalle completo de un perfil de debugging.
    Accesible por admin y operadores.
    """
    org = _get_user_organization(current_user, db)
    _verify_llm_enabled(org)

    profile = db.query(DebuggingProfile).filter(
        DebuggingProfile.id == profile_id,
        DebuggingProfile.organization_id == org.id,
    ).first()

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Perfil de debugging con ID {profile_id} no encontrado",
        )

    return _serialize_profile(profile)


@router.put(
    "/profiles/{profile_id}",
    response_model=DebuggingProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Actualizar un perfil de debugging",
)
async def update_profile(
    profile_id: UUID,
    payload: DebuggingProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Actualiza campos de un perfil de debugging existente.
    Solo accesible por admins.
    """
    _require_admin(current_user)
    org = _get_user_organization(current_user, db)
    _verify_llm_enabled(org)

    profile = db.query(DebuggingProfile).filter(
        DebuggingProfile.id == profile_id,
        DebuggingProfile.organization_id == org.id,
    ).first()

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Perfil de debugging con ID {profile_id} no encontrado",
        )

    # Actualizar solo campos proporcionados
    if payload.external_logs is not None:
        profile.external_logs = json.dumps(payload.external_logs)
    if payload.eventlog_groups is not None:
        profile.eventlog_groups = json.dumps(payload.eventlog_groups)
    if payload.registry_keys is not None:
        profile.registry_keys = json.dumps(payload.registry_keys)
    if payload.monitored_services is not None:
        profile.monitored_services = json.dumps(payload.monitored_services)
    if payload.description is not None:
        profile.description = payload.description
    if payload.is_active is not None:
        profile.is_active = payload.is_active

    profile.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(profile)

    logger.info(
        "[DEBUGGING] Perfil actualizado: id=%s, name='%s', por user=%s",
        profile.id, profile.name, current_user.id,
    )

    return _serialize_profile(profile)


@router.delete(
    "/profiles/{profile_id}",
    status_code=status.HTTP_200_OK,
    summary="Desactivar un perfil de debugging (soft delete)",
)
async def delete_profile(
    profile_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Desactiva un perfil de debugging (soft delete via is_active=False).
    Solo accesible por admins.
    """
    _require_admin(current_user)
    org = _get_user_organization(current_user, db)

    profile = db.query(DebuggingProfile).filter(
        DebuggingProfile.id == profile_id,
        DebuggingProfile.organization_id == org.id,
    ).first()

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Perfil de debugging con ID {profile_id} no encontrado",
        )

    profile.is_active = False
    profile.updated_at = datetime.utcnow()
    db.commit()

    logger.info(
        "[DEBUGGING] Perfil desactivado: id=%s, name='%s', por user=%s",
        profile.id, profile.name, current_user.id,
    )

    return {"detail": f"Perfil '{profile.name}' desactivado correctamente"}



# === ENDPOINTS DE SESIONES (ADMIN + OPERATOR) ===


@router.post(
    "/sessions",
    response_model=DebuggingSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Iniciar sesión de debugging en una workstation",
)
async def create_session(
    payload: DebuggingSessionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Inicia una sesión de debugging en una workstation.

    Genera un debugging_id único, valida que no haya otra sesión activa en la
    workstation, y envía el comando StartDebugging vía WebSocket.

    Accesible por admins y operadores.
    """
    from app.services.websocket_manager import connection_manager

    org = _get_user_organization(current_user, db)
    _verify_llm_enabled(org)

    # Verificar que el perfil existe y pertenece a la organización
    profile = db.query(DebuggingProfile).filter(
        DebuggingProfile.id == payload.profile_id,
        DebuggingProfile.organization_id == org.id,
        DebuggingProfile.is_active == True,
    ).first()

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Perfil de debugging con ID {payload.profile_id} no encontrado o inactivo",
        )

    # Verificar que la workstation existe y pertenece a la organización
    workstation = db.query(Workstation).filter(
        Workstation.id == payload.workstation_id,
        Workstation.organization_id == org.id,
    ).first()

    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workstation con ID {payload.workstation_id} no encontrada",
        )

    # Verificar que la workstation está online
    ws_id_str = str(workstation.id)
    if not connection_manager.is_workstation_online(ws_id_str):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La workstation está offline. No se puede iniciar debugging.",
        )

    # Verificar que no hay otra sesión activa en esta workstation
    active_session = db.query(DebuggingSession).filter(
        DebuggingSession.workstation_id == payload.workstation_id,
        DebuggingSession.status == DebuggingSessionStatus.ACTIVE.value,
    ).first()

    if active_session:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Ya existe una sesión de debugging activa en esta workstation "
                f"(ID: {active_session.id}). Solo se permite una a la vez."
            ),
        )

    # Crear la sesión
    session = DebuggingSession(
        id=uuid.uuid4(),
        organization_id=org.id,
        profile_id=profile.id,
        workstation_id=workstation.id,
        status=DebuggingSessionStatus.ACTIVE.value,
        duration_seconds=payload.duration_seconds,
        start_time=datetime.utcnow(),
        motivo=payload.motivo,
        additional_instructions=payload.additional_instructions,
        initiated_by=current_user.id,
    )

    db.add(session)
    db.commit()
    db.refresh(session)

    # Enviar comando StartDebugging vía WebSocket
    ws_message = {
        "type": "command",
        "command_id": str(session.id),
        "command_type": "start_debugging",
        "params": {
            "debugging_id": str(session.id),
            "profile": {
                "name": profile.name,
                "external_logs": json.loads(profile.external_logs),
                "eventlog_groups": json.loads(profile.eventlog_groups),
                "registry_keys": json.loads(profile.registry_keys),
                "monitored_services": json.loads(profile.monitored_services),
            },
            "duration_seconds": payload.duration_seconds,
        },
    }

    sent = await connection_manager.send_to_workstation(ws_id_str, ws_message)

    if not sent:
        # Si no se pudo enviar, marcar sesión como fallida
        session.status = DebuggingSessionStatus.FAILED.value
        session.end_time = datetime.utcnow()
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La workstation se desconectó antes de recibir el comando.",
        )

    logger.info(
        "[DEBUGGING] Sesión iniciada: id=%s, ws=%s, profile='%s', duration=%ds, por user=%s",
        session.id, workstation.id, profile.name, payload.duration_seconds, current_user.id,
    )

    # Background task: marcar como failed si no recibe ack en 10 segundos
    import asyncio
    from app.core.database import SessionLocal as _SessionLocal

    async def _check_debugging_ack(debugging_id: str, timeout: int = 10):
        """Verifica que el cliente confirmó el inicio del debugging."""
        await asyncio.sleep(timeout)
        check_db = _SessionLocal()
        try:
            s = check_db.query(DebuggingSession).filter(
                DebuggingSession.id == debugging_id,
            ).first()
            # Si después del timeout sigue en 'active' y la ws está offline, marcar como failed
            if s and s.status == DebuggingSessionStatus.ACTIVE.value:
                if not connection_manager.is_workstation_online(str(s.workstation_id)):
                    s.status = DebuggingSessionStatus.FAILED.value
                    s.end_time = datetime.utcnow()
                    check_db.commit()
                    logger.warning(
                        "[DEBUGGING] Timeout ack: session=%s marcada como failed (ws offline)",
                        debugging_id,
                    )
        except Exception as e:
            logger.error("[DEBUGGING] Error en timeout check: %s", e)
        finally:
            check_db.close()

    asyncio.ensure_future(_check_debugging_ack(str(session.id)))

    return DebuggingSessionResponse.model_validate(session)


@router.get(
    "/sessions",
    response_model=List[DebuggingSessionListItem],
    status_code=status.HTTP_200_OK,
    summary="Listar sesiones de debugging",
)
async def list_sessions(
    workstation_id: Optional[UUID] = Query(None, description="Filtrar por workstation"),
    session_status: Optional[str] = Query(None, alias="status", description="Filtrar por estado"),
    limit: int = Query(50, ge=1, le=200, description="Máximo de resultados"),
    offset: int = Query(0, ge=0, description="Offset para paginación"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Lista sesiones de debugging de la organización del usuario.
    Soporta filtros por workstation_id y estado.
    Accesible por admins y operadores.
    """
    org = _get_user_organization(current_user, db)

    query = db.query(DebuggingSession).filter(
        DebuggingSession.organization_id == org.id
    )

    if workstation_id:
        query = query.filter(DebuggingSession.workstation_id == workstation_id)

    if session_status:
        query = query.filter(DebuggingSession.status == session_status)

    sessions = (
        query.order_by(DebuggingSession.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [DebuggingSessionListItem.model_validate(s) for s in sessions]


@router.get(
    "/sessions/{session_id}",
    response_model=DebuggingSessionResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener detalle de una sesión de debugging",
)
async def get_session(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Retorna el detalle completo de una sesión de debugging.
    Accesible por admins y operadores.
    """
    org = _get_user_organization(current_user, db)

    session = db.query(DebuggingSession).filter(
        DebuggingSession.id == session_id,
        DebuggingSession.organization_id == org.id,
    ).first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sesión de debugging con ID {session_id} no encontrada",
        )

    return DebuggingSessionResponse.model_validate(session)


@router.post(
    "/sessions/{session_id}/stop",
    response_model=DebuggingSessionResponse,
    status_code=status.HTTP_200_OK,
    summary="Detener una sesión de debugging activa",
)
async def stop_session(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Detiene una sesión de debugging activa enviando StopDebugging al cliente.
    Solo se puede detener una sesión con status 'active'.
    Accesible por admins y operadores.
    """
    from app.services.websocket_manager import connection_manager

    org = _get_user_organization(current_user, db)

    session = db.query(DebuggingSession).filter(
        DebuggingSession.id == session_id,
        DebuggingSession.organization_id == org.id,
    ).first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sesión de debugging con ID {session_id} no encontrada",
        )

    if session.status != DebuggingSessionStatus.ACTIVE.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Solo se pueden detener sesiones activas. Estado actual: {session.status}",
        )

    # Enviar comando StopDebugging
    ws_id_str = str(session.workstation_id)
    ws_message = {
        "type": "command",
        "command_id": str(uuid.uuid4()),
        "command_type": "stop_debugging",
        "params": {
            "debugging_id": str(session.id),
        },
    }

    await connection_manager.send_to_workstation(ws_id_str, ws_message)

    logger.info(
        "[DEBUGGING] StopDebugging enviado: session=%s, ws=%s, por user=%s",
        session.id, session.workstation_id, current_user.id,
    )

    return DebuggingSessionResponse.model_validate(session)


@router.post(
    "/sessions/{session_id}/analyze",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Solicitar análisis de datos de debugging (trigger upload + LLM)",
)
async def analyze_session(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Solicita el análisis de una sesión con status 'ready'.
    Envía RequestDebugUpload al cliente para que suba el ZIP.
    El análisis LLM se ejecuta asíncronamente tras recibir el upload.
    Accesible por admins y operadores.
    """
    from app.services.websocket_manager import connection_manager

    org = _get_user_organization(current_user, db)
    _verify_llm_enabled(org)

    session = db.query(DebuggingSession).filter(
        DebuggingSession.id == session_id,
        DebuggingSession.organization_id == org.id,
    ).first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sesión de debugging con ID {session_id} no encontrada",
        )

    if session.status != DebuggingSessionStatus.READY.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Solo se pueden analizar sesiones con status 'ready'. "
                f"Estado actual: {session.status}"
            ),
        )

    # Enviar comando RequestDebugUpload
    ws_id_str = str(session.workstation_id)
    ws_message = {
        "type": "command",
        "command_id": str(uuid.uuid4()),
        "command_type": "request_debug_upload",
        "params": {
            "debugging_id": str(session.id),
        },
    }

    sent = await connection_manager.send_to_workstation(ws_id_str, ws_message)

    if not sent:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La workstation está offline. No se puede solicitar el upload.",
        )

    # Marcar como uploading
    session.status = DebuggingSessionStatus.UPLOADING.value
    db.commit()

    logger.info(
        "[DEBUGGING] RequestDebugUpload enviado: session=%s, ws=%s, por user=%s",
        session.id, session.workstation_id, current_user.id,
    )

    return {
        "detail": "Solicitud de upload enviada. El análisis se procesará tras recibir los datos.",
        "session_id": str(session.id),
        "status": session.status,
    }


@router.post(
    "/sessions/{session_id}/delete",
    status_code=status.HTTP_200_OK,
    summary="Solicitar eliminación de datos de debugging del cliente",
)
async def delete_session_data(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Solicita al cliente la eliminación de los datos de debugging.
    Envía DeleteDebugData al cliente vía WebSocket.
    Accesible por admins y operadores.
    """
    from app.services.websocket_manager import connection_manager

    org = _get_user_organization(current_user, db)

    session = db.query(DebuggingSession).filter(
        DebuggingSession.id == session_id,
        DebuggingSession.organization_id == org.id,
    ).first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sesión de debugging con ID {session_id} no encontrada",
        )

    if session.status not in (
        DebuggingSessionStatus.READY.value,
        DebuggingSessionStatus.ANALYZED.value,
        DebuggingSessionStatus.ANALYSIS_FAILED.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Solo se pueden eliminar datos de sesiones con status 'ready', "
                f"'analyzed' o 'analysis_failed'. Estado actual: {session.status}"
            ),
        )

    # Enviar comando DeleteDebugData
    ws_id_str = str(session.workstation_id)
    ws_message = {
        "type": "command",
        "command_id": str(uuid.uuid4()),
        "command_type": "delete_debug_data",
        "params": {
            "debugging_id": str(session.id),
        },
    }

    sent = await connection_manager.send_to_workstation(ws_id_str, ws_message)

    if not sent:
        # Si la workstation está offline, marcar como deleted de todas formas
        # (los datos se limpiarán eventualmente o al reconectar)
        session.status = DebuggingSessionStatus.DELETED.value
        db.commit()
        logger.warning(
            "[DEBUGGING] Workstation offline al eliminar. Marcado como deleted: session=%s",
            session.id,
        )
        return {
            "detail": "Workstation offline. Sesión marcada como eliminada (datos se limpiarán al reconectar).",
            "session_id": str(session.id),
        }

    # Marcar como deleted (el cliente confirmará)
    session.status = DebuggingSessionStatus.DELETED.value
    db.commit()

    logger.info(
        "[DEBUGGING] DeleteDebugData enviado: session=%s, ws=%s, por user=%s",
        session.id, session.workstation_id, current_user.id,
    )

    return {
        "detail": "Solicitud de eliminación enviada al cliente.",
        "session_id": str(session.id),
    }


@router.get(
    "/sessions/{session_id}/report",
    response_model=DebuggingReportURL,
    status_code=status.HTTP_200_OK,
    summary="Obtener URL de descarga del reporte PDF",
)
async def get_session_report(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Genera una URL presigned de S3 para descargar el PDF del reporte.
    Solo disponible para sesiones con status 'analyzed'.
    Accesible por admins y operadores.
    """
    org = _get_user_organization(current_user, db)

    session = db.query(DebuggingSession).filter(
        DebuggingSession.id == session_id,
        DebuggingSession.organization_id == org.id,
    ).first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sesión de debugging con ID {session_id} no encontrada",
        )

    if session.status != DebuggingSessionStatus.ANALYZED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El reporte solo está disponible para sesiones analizadas. Estado actual: {session.status}",
        )

    if not session.s3_report_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontró la referencia al reporte PDF en S3.",
        )

    # Generar presigned URL
    import boto3
    try:
        s3_client = boto3.client("s3", region_name=settings.LOG_ANALYZER_LLM_REGION)
        expires_in = 3600  # 1 hora

        presigned_url = s3_client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": settings.S3_DOCS_BUCKET,
                "Key": session.s3_report_key,
                "ResponseContentDisposition": (
                    f'attachment; filename="debugging_report_{session.id}.pdf"'
                ),
            },
            ExpiresIn=expires_in,
        )

        return DebuggingReportURL(
            report_url=presigned_url,
            expires_in_seconds=expires_in,
        )

    except Exception as e:
        logger.error(
            "[DEBUGGING] Error generando presigned URL: session=%s, key=%s, error=%s",
            session.id, session.s3_report_key, e,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error generando URL de descarga del reporte.",
        )



# === UPLOAD ENDPOINT (WORKSTATION AUTHENTICATED) ===

# Tamaño máximo de upload: 100MB
MAX_DEBUG_UPLOAD_SIZE = 100 * 1024 * 1024


@router.post(
    "/{debugging_id}/upload",
    status_code=status.HTTP_200_OK,
    summary="Upload ZIP de debugging desde workstation",
)
async def upload_debugging_zip(
    debugging_id: UUID,
    file: UploadFile = File(...),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """
    Endpoint dedicado para recibir el ZIP de debugging desde el cliente Windows.

    Autenticación: via header X-Workstation-ID (mismo mecanismo que updates).
    El ZIP se procesa inmediatamente con el pipeline de análisis LLM + PDF.
    """
    import asyncio
    from app.services.debugging_analysis import DebuggingAnalysisService, DebuggingAnalysisError

    # Autenticar workstation via header
    workstation_id_header = request.headers.get("X-Workstation-ID") if request else None
    if not workstation_id_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Header X-Workstation-ID requerido",
        )

    # Verificar que la sesión existe
    session = db.query(DebuggingSession).filter(
        DebuggingSession.id == debugging_id,
    ).first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sesión de debugging con ID {debugging_id} no encontrada",
        )

    # Verificar que la workstation es la correcta
    if str(session.workstation_id) != workstation_id_header:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La workstation no tiene permiso para subir datos de esta sesión",
        )

    # Verificar status (debe ser uploading o ready)
    if session.status not in (
        DebuggingSessionStatus.UPLOADING.value,
        DebuggingSessionStatus.READY.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Estado inválido para upload: {session.status}. Se requiere 'uploading' o 'ready'.",
        )

    # Leer el archivo
    zip_data = await file.read()

    # Validar tamaño
    if len(zip_data) > MAX_DEBUG_UPLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"El archivo excede el tamaño máximo ({MAX_DEBUG_UPLOAD_SIZE // (1024 * 1024)}MB).",
        )

    # Validar que es un ZIP válido
    import zipfile as zf_module
    if not zf_module.is_zipfile(io.BytesIO(zip_data)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El archivo subido no es un ZIP válido",
        )

    # Marcar como analyzing
    session.status = DebuggingSessionStatus.ANALYZING.value
    db.commit()

    logger.info(
        "[DEBUGGING] ZIP recibido: session=%s, size=%d bytes, ws=%s",
        session.id, len(zip_data), workstation_id_header,
    )

    # Obtener la organización para configuración LLM
    org = db.query(Organization).filter(
        Organization.id == session.organization_id
    ).first()

    if not org:
        session.status = DebuggingSessionStatus.ANALYSIS_FAILED.value
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Organización no encontrada",
        )

    # Ejecutar pipeline de análisis
    try:
        analysis_service = DebuggingAnalysisService()
        s3_key = await analysis_service.analyze(session, zip_data, org)

        # Actualizar sesión con resultado
        session.status = DebuggingSessionStatus.ANALYZED.value
        session.s3_report_key = s3_key
        session.end_time = datetime.utcnow()
        db.commit()

        logger.info(
            "[DEBUGGING] Análisis completado: session=%s, s3_key=%s",
            session.id, s3_key,
        )

        return {
            "detail": "Análisis completado. El reporte PDF está disponible.",
            "session_id": str(session.id),
            "status": "analyzed",
            "s3_report_key": s3_key,
        }

    except DebuggingAnalysisError as e:
        session.status = DebuggingSessionStatus.ANALYSIS_FAILED.value
        db.commit()
        logger.error(
            "[DEBUGGING] Análisis fallido: session=%s, error=%s",
            session.id, e,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error durante el análisis: {e}",
        )
