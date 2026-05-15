"""
Endpoints REST de conectividad.

Este módulo define los endpoints para:
- Consulta de historial de resultados de conectividad por workstation
"""

from datetime import datetime
from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.workstation import Workstation
from app.schemas.telemetry import ConnectivityResultResponse
from app.services.connectivity import ConnectivityService

# Router con prefijo /workstations para el endpoint de conectividad por workstation
router = APIRouter(prefix="/workstations", tags=["connectivity"])


@router.get(
    "/{workstation_id}/connectivity",
    response_model=List[ConnectivityResultResponse],
    summary="Obtener historial de conectividad de una workstation",
    description="Retorna resultados de checks de conectividad ordenados por recorded_at DESC con filtrado opcional."
)
async def get_workstation_connectivity(
    workstation_id: UUID,
    check_id: Optional[str] = Query(
        None,
        max_length=255,
        description="Filtrar por identificador de check específico (máx 255 caracteres)"
    ),
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
    Consultar historial de resultados de conectividad de una workstation.

    Verifica tenant isolation: la workstation debe pertenecer a la cuenta
    del usuario autenticado. Soporta filtrado por check_id, rango temporal
    con parámetros 'from' y 'to' (ISO 8601), y paginación con 'limit'.

    Retorna:
        - 200: Array JSON de ConnectivityResult (vacío si no hay registros)
        - 401: Token ausente o inválido
        - 404: Workstation no encontrada o no pertenece a la cuenta
        - 422: Parámetros inválidos (from > to, limit fuera de rango, check_id > 255 chars)
    """
    # Validar que from no sea posterior a to
    if from_dt is not None and to_dt is not None and from_dt > to_dt:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Parámetro 'from' no puede ser posterior a 'to'"
        )

    # Verificar tenant isolation: workstation debe pertenecer a la cuenta del usuario
    # Admin puede ver cualquier workstation
    if current_user.account_id:
        workstation = db.query(Workstation).filter(
            Workstation.id == workstation_id,
            Workstation.account_id == current_user.account_id
        ).first()
    else:
        # Admin sin account_id puede ver todas las workstations
        workstation = db.query(Workstation).filter(
            Workstation.id == workstation_id
        ).first()

    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workstation no encontrada"
        )

    # Consultar historial de conectividad usando el servicio
    connectivity_service = ConnectivityService()
    records = connectivity_service.get_connectivity_history(
        db=db,
        workstation_id=str(workstation_id),
        account_id=str(workstation.account_id) if workstation.account_id else str(current_user.account_id or ""),
        check_id=check_id,
        from_dt=from_dt,
        to_dt=to_dt,
        limit=limit
    )

    return records
