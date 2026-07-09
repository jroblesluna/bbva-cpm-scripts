"""
Endpoints para ejecución masiva de acciones OnDemand.

Permite a operadores y administradores ejecutar una acción OnDemand
del alwaysconfig activo contra todas las workstations online de una
organización, con throttling configurable, progreso en tiempo real
vía WebSocket, y cancelación.
"""

import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User, UserRole
from app.schemas.bulk_actions import (
    BulkPreview,
    BulkPreviewRequest,
    BulkSessionStatus,
    BulkStartRequest,
    BulkStartResponse,
    OnDemandAction,
)
from app.services.bulk_execution import BulkExecutionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bulk-actions", tags=["Acciones Masivas"])

# Instancia del servicio de ejecución masiva
bulk_service = BulkExecutionService()


def _get_org_id(user: User) -> UUID:
    """
    Obtiene el organization_id del usuario con validación de rol.

    - Usuarios readonly: HTTP 403 (permisos insuficientes)
    - Operadores: retorna su organization_id asignado
    - Admins: retorna su organization_id (si tiene)

    Raises:
        HTTPException 403: Si el usuario es readonly
    """
    if user.role == UserRole.READONLY:
        raise HTTPException(status_code=403, detail="Permisos insuficientes")
    return user.organization_id


@router.get("/available-actions", response_model=list[OnDemandAction])
async def get_available_actions(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Lista las acciones OnDemand disponibles del alwaysconfig activo de la organización.

    Extrae los triggers con event == "OnDemand" y label no vacío del
    alwaysconfig activo (scope=org) de la organización del usuario.
    """
    org_id = _get_org_id(user)
    return bulk_service.get_available_actions(org_id, db)


@router.post("/preview", response_model=BulkPreview)
async def preview_bulk_execution(
    request: BulkPreviewRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Preview de la ejecución masiva con conteo de workstations y tiempo estimado.

    Calcula el tiempo estimado como: (workstations_online - 1) * delay_ms.
    Valida que el label existe en el alwaysconfig activo de la organización.
    """
    org_id = _get_org_id(user)
    return await bulk_service.get_preview(org_id, request.label, request.delay_ms, db)


@router.post("/start", response_model=BulkStartResponse, status_code=202)
async def start_bulk_execution(
    request: BulkStartRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Inicia la ejecución masiva de una acción OnDemand (retorna 202 Accepted).

    Crea una Bulk_Session con estado running y lanza el background task
    que itera las workstations online enviando el comando con throttling.
    """
    org_id = _get_org_id(user)
    response, workstation_ids = await bulk_service.start_session(
        org_id, request.label, request.delay_ms, user.id, db
    )

    # Lanzar background task para la ejecución throttled
    asyncio.ensure_future(
        bulk_service._execute_bulk(
            response.session_id,
            org_id,
            request.label,
            request.delay_ms,
            workstation_ids,
        )
    )

    return response


@router.get("/status/{session_id}", response_model=BulkSessionStatus)
async def get_session_status(
    session_id: UUID,
    user: User = Depends(get_current_user),
):
    """
    Consulta el estado actual de una sesión de ejecución masiva.

    Retorna métricas de progreso: total, enviados, éxitos, errores,
    workstations fallidas, y tiempo transcurrido.
    """
    org_id = _get_org_id(user)
    return await bulk_service.get_session_status(session_id, org_id)


@router.post("/cancel/{session_id}", response_model=BulkSessionStatus)
async def cancel_session(
    session_id: UUID,
    user: User = Depends(get_current_user),
):
    """
    Cancela una ejecución masiva en curso.

    Establece un flag de cancelación que el background task verifica
    antes de cada envío. La sesión debe estar en estado 'running'.
    """
    org_id = _get_org_id(user)
    return await bulk_service.cancel_session(session_id, org_id)
