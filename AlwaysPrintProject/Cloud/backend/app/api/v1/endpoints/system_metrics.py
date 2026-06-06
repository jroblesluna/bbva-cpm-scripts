"""
Endpoint de métricas de escalabilidad del sistema.

Expone un endpoint protegido (solo Admin) que retorna las 5 métricas
de escalabilidad orientadas a monitorear la capacidad del sistema para
soportar 5000 workstations concurrentes:
- Conexiones WebSocket activas
- Memoria del proceso Python
- File descriptors
- Tráfico de red
- Estado del pool de base de datos
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_admin
from app.models.user import User
from app.schemas.scalability_metrics import ScalabilityMetricsResponse
from app.services.scalability_metrics import scalability_collector

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/metrics",
    response_model=ScalabilityMetricsResponse,
    summary="Métricas de escalabilidad",
    description="Retorna las 5 métricas de escalabilidad del sistema en tiempo real",
)
async def get_system_metrics(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> ScalabilityMetricsResponse:
    """
    Endpoint protegido: solo admin.

    Recolecta y retorna las 5 métricas de escalabilidad del sistema:
    conexiones WebSocket, memoria Python, file descriptors, tráfico de red
    y estado del pool de base de datos.

    Si alguna métrica individual falla, se retorna null para esa métrica
    y se continúan retornando las demás con HTTP 200.
    """
    logger.info(
        "Solicitud de métricas de escalabilidad",
        extra={"user_email": current_user.email},
    )

    # Recolectar todas las métricas pasando la sesión de BD
    metrics = await scalability_collector.collect_all_metrics(db=db)

    return metrics
