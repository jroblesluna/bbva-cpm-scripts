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
from app.schemas.telemetry import TelemetryLogResponse, TelemetryStatsResponse
from app.services.telemetry import TelemetryService

# Router con prefijo /workstations para el endpoint de telemetría por workstation
router = APIRouter(prefix="/workstations", tags=["telemetry"])

# Router separado para endpoints a nivel de cuenta
accounts_router = APIRouter(prefix="/accounts", tags=["telemetry"])


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
    workstation = db.query(Workstation).filter(
        Workstation.id == workstation_id,
        Workstation.account_id == current_user.account_id
    ).first()

    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workstation no encontrada"
        )

    # Consultar historial de telemetría usando el servicio
    telemetry_service = TelemetryService()
    records = telemetry_service.get_telemetry_history(
        db=db,
        workstation_id=str(workstation_id),
        account_id=str(current_user.account_id),
        from_dt=from_dt,
        to_dt=to_dt,
        limit=limit
    )

    return records



# === ENDPOINT DE ESTADÍSTICAS POR CUENTA ===

@accounts_router.get(
    "/{account_id}/telemetry/stats",
    response_model=TelemetryStatsResponse,
    summary="Obtener estadísticas de telemetría de una cuenta",
    description="Retorna estadísticas agregadas de telemetría de las últimas 24 horas UTC para la cuenta especificada."
)
async def get_account_telemetry_stats(
    account_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Consultar estadísticas agregadas de telemetría por cuenta.

    Verifica tenant isolation: el account_id del token debe coincidir
    con el {account_id} solicitado, o el usuario debe tener rol admin.
    No revela la existencia de cuentas ajenas (retorna 404 genérico).

    Estadísticas computadas sobre registros de las últimas 24 horas UTC:
    - total_workstations: workstations registradas para la cuenta
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
        - 404: Cuenta no encontrada o no coincide con el token
    """
    # Verificar tenant isolation: account_id del token debe coincidir con {id}
    # Los usuarios admin pueden consultar cualquier cuenta
    if current_user.role != UserRole.ADMIN:
        # Para usuarios no-admin, su account_id debe coincidir con el solicitado
        if current_user.account_id is None or str(current_user.account_id) != str(account_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cuenta no encontrada"
            )

    # Computar estadísticas usando el servicio de telemetría
    telemetry_service = TelemetryService()
    stats = telemetry_service.get_telemetry_stats(
        db=db,
        account_id=str(account_id)
    )

    return stats
