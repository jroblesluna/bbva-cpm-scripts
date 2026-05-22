"""
Endpoints REST de telemetría.

Este módulo define los endpoints para:
- Consulta de historial de telemetría por workstation
- Estadísticas agregadas de telemetría por cuenta
"""

from datetime import datetime
from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User, UserRole
from app.models.workstation import Workstation
from app.schemas.telemetry import (
    TelemetryLogResponse,
    TelemetryStatsResponse,
    TelemetryLatestBatchResponse,
    TelemetryLatestBatchRequest,
)
from app.services.telemetry import TelemetryService

# Router con prefijo /workstations para el endpoint de telemetría por workstation
router = APIRouter(prefix="/workstations", tags=["telemetry"])

# Router separado para endpoints a nivel de organización
organizations_telemetry_router = APIRouter(prefix="/organizations", tags=["telemetry"])


@router.get(
    "/{workstation_id}/telemetry",
    response_model=List[TelemetryLogResponse],
    summary="Obtener historial de telemetría de una workstation",
    description="Retorna registros de telemetría ordenados por recorded_at DESC con filtrado temporal opcional."
)
async def get_workstation_telemetry(
    workstation_id: UUID,
    from_dt: Optional[datetime] = Query(
        None,
        alias="from",
        description="Fecha/hora mínima de filtrado (ISO 8601)"
    ),
    to_dt: Optional[datetime] = Query(
        None,
        alias="to",
        description="Fecha/hora máxima de filtrado (ISO 8601)"
    ),
    limit: int = Query(
        100,
        ge=1,
        le=1000,
        description="Número máximo de registros a devolver (1-1000, default 100)"
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Consultar historial de telemetría de una workstation.

    Verifica tenant isolation: la workstation debe pertenecer a la cuenta
    del usuario autenticado. Soporta filtrado temporal con parámetros
    'from' y 'to' (ISO 8601) y paginación con 'limit'.

    Retorna:
        - 200: Array JSON de TelemetryLog (vacío si no hay registros)
        - 401: Token ausente o inválido
        - 404: Workstation no encontrada o no pertenece a la cuenta
        - 422: Parámetros inválidos (from > to, limit fuera de rango)
    """
    # Validar que from no sea posterior a to
    if from_dt is not None and to_dt is not None and from_dt > to_dt:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Parámetro 'from' no puede ser posterior a 'to'"
        )

    # Verificar tenant isolation: workstation debe pertenecer a la cuenta del usuario
    # Admin puede ver cualquier workstation; operador solo las de su organización
    if current_user.role == UserRole.ADMIN:
        workstation = db.query(Workstation).filter(
            Workstation.id == workstation_id
        ).first()
    else:
        workstation = db.query(Workstation).filter(
            Workstation.id == workstation_id,
            Workstation.organization_id == current_user.organization_id
        ).first()

    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workstation no encontrada"
        )

    # Consultar historial de telemetría usando el servicio
    telemetry_service = TelemetryService()
    org_id = str(workstation.organization_id) if workstation.organization_id else str(current_user.organization_id or "")
    records = telemetry_service.get_telemetry_history(
        db=db,
        workstation_id=str(workstation_id),
        organization_id=org_id,
        from_dt=from_dt,
        to_dt=to_dt,
        limit=limit
    )

    return records



# === ENDPOINT DE ESTADÍSTICAS POR CUENTA ===

@organizations_telemetry_router.get(
    "/{organization_id}/telemetry/stats",
    response_model=TelemetryStatsResponse,
    summary="Obtener estadísticas de telemetría de una organización",
    description="Retorna estadísticas agregadas de telemetría de las últimas 24 horas UTC para la organización especificada."
)
async def get_organization_telemetry_stats(
    organization_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Consultar estadísticas agregadas de telemetría por organización.

    Verifica tenant isolation: el organization_id del token debe coincidir
    con el {organization_id} solicitado, o el usuario debe tener rol admin.
    No revela la existencia de organizaciones ajenas (retorna 404 genérico).

    Estadísticas computadas sobre registros de las últimas 24 horas UTC:
    - total_workstations: workstations registradas para la organización
    - workstations_reporting: con al menos un registro en 24h
    - avg_jobs_identified: promedio aritmético de jobs_identified
    - contingency_active_count: workstations con contingency_active=True
      en su registro más reciente
    - queue_status_summary: conteo por estado de cola del registro más
      reciente por workstation
    - last_updated: timestamp del registro más reciente o null

    Retorna:
        - 200: Objeto TelemetryStatsResponse con estadísticas
        - 401: Token ausente o inválido
        - 404: Organización no encontrada o no coincide con el token
    """
    # Verificar tenant isolation: organization_id del token debe coincidir con {id}
    # Los usuarios admin pueden consultar cualquier organización
    if current_user.role != UserRole.ADMIN:
        # Para usuarios no-admin, su organization_id debe coincidir con el solicitado
        if current_user.organization_id is None or str(current_user.organization_id) != str(organization_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organización no encontrada"
            )

    # Computar estadísticas usando el servicio de telemetría
    telemetry_service = TelemetryService()
    stats = telemetry_service.get_telemetry_stats(
        db=db,
        organization_id=str(organization_id)
    )

    return stats


# === ENDPOINT DE ESTADÍSTICAS GLOBALES (ADMIN) ===

@router.get(
    "/telemetry/stats",
    response_model=TelemetryStatsResponse,
    summary="Obtener estadísticas globales de telemetría (Admin)",
    description="Retorna estadísticas agregadas de telemetría de todas las organizaciones. Solo accesible para administradores."
)
async def get_global_telemetry_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo los administradores pueden acceder a estadísticas globales"
        )

    telemetry_service = TelemetryService()
    return telemetry_service.get_global_telemetry_stats(db=db)


# === ENDPOINT BATCH: ÚLTIMA TELEMETRÍA POR WORKSTATION ===

@router.post(
    "/telemetry/latest-batch",
    response_model=TelemetryLatestBatchResponse,
    summary="Obtener última telemetría de un conjunto de workstations",
    description="Recibe una lista de workstation_ids (máx 100) y retorna la última telemetría de cada una."
)
async def get_telemetry_latest_batch(
    body: TelemetryLatestBatchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtener la última telemetría de un conjunto de workstations (batch).

    Endpoint que elimina la necesidad de hacer N llamadas individuales
    GET /workstations/{id}/telemetry?limit=1 desde el frontend.

    - Admin: puede consultar cualquier workstation (sin filtro de organización)
    - Operador: solo puede consultar workstations de su organización

    Acepta máximo 100 workstation_ids por llamada para mantener rendimiento
    con escalas de 10,000+ workstations (el frontend pagina y solo consulta
    las workstations visibles en la página actual).

    Retorna:
        - 200: Objeto con mapa {workstation_id: última_telemetría | null}
        - 401: Token ausente o inválido
    """
    # Determinar organization_id para tenant isolation según rol
    org_id = None
    if current_user.role != UserRole.ADMIN:
        org_id = str(current_user.organization_id) if current_user.organization_id else None

    # Obtener última telemetría batch usando el servicio
    telemetry_service = TelemetryService()
    result = telemetry_service.get_latest_telemetry_batch(
        db=db,
        workstation_ids=body.workstation_ids,
        organization_id=org_id
    )

    return result
