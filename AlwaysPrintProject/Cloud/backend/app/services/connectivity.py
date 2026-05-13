"""
Servicio de persistencia y consulta de resultados de conectividad.

Este servicio implementa la lógica de negocio para:
- Persistir resultados de checks de conectividad recibidos por WebSocket
- Consultar historial de conectividad con filtrado temporal y por check_id
- Verificar tenant isolation en todas las operaciones
"""

import logging
from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.telemetry import ConnectivityResult
from app.models.workstation import Workstation
from app.schemas.telemetry import ConnectivityResultPayload

# Logger del módulo
logger = logging.getLogger(__name__)


class ConnectivityService:
    """
    Servicio para gestión de resultados de conectividad.

    Proporciona métodos para:
    - Persistir resultados individuales de checks de conectividad
    - Consultar historial con filtrado por check_id, rango temporal y límite
    - Garantizar tenant isolation en todas las queries
    """

    def persist_connectivity_result(
        self,
        db: Session,
        workstation_id: str,
        account_id: str,
        payload: ConnectivityResultPayload
    ) -> Optional[ConnectivityResult]:
        """
        Persiste un resultado de check de conectividad en la base de datos.

        Verifica que la workstation exista y pertenezca a la cuenta indicada
        (tenant isolation) antes de crear el registro.

        Args:
            db: Sesión de base de datos
            workstation_id: UUID de la workstation que reporta el resultado
            account_id: UUID de la cuenta del sender (para tenant isolation)
            payload: Payload validado con los datos del resultado de conectividad

        Returns:
            ConnectivityResult creado si la operación fue exitosa, None si la
            workstation no existe o no pertenece a la cuenta

        Raises:
            Exception: Si ocurre un error de escritura en BD (se propaga al caller)
        """
        # Verificar tenant isolation: workstation debe existir para la cuenta
        workstation = db.query(Workstation).filter(
            Workstation.id == workstation_id,
            Workstation.account_id == account_id
        ).first()

        if not workstation:
            logger.warning(
                "Workstation %s no encontrada para cuenta %s. "
                "Descartando resultado de conectividad.",
                workstation_id,
                account_id
            )
            return None

        # Crear registro de resultado de conectividad
        connectivity_result = ConnectivityResult(
            workstation_id=workstation_id,
            account_id=account_id,
            check_id=payload.check_id,
            check_type=payload.check_type,
            success=payload.success,
            latency_ms=payload.latency_ms,
            error=payload.error,
            recorded_at=datetime.utcnow()
        )

        db.add(connectivity_result)
        db.commit()
        db.refresh(connectivity_result)

        logger.info(
            "Resultado de conectividad persistido: workstation=%s, check_id=%s, "
            "check_type=%s, success=%s",
            workstation_id,
            payload.check_id,
            payload.check_type,
            payload.success
        )

        return connectivity_result

    def get_connectivity_history(
        self,
        db: Session,
        workstation_id: str,
        account_id: str,
        check_id: Optional[str] = None,
        from_dt: Optional[datetime] = None,
        to_dt: Optional[datetime] = None,
        limit: int = 100
    ) -> List[ConnectivityResult]:
        """
        Consulta el historial de resultados de conectividad con filtrado.

        Aplica tenant isolation filtrando por workstation_id Y account_id.
        Soporta filtrado opcional por check_id, rango temporal y límite.
        Los resultados se ordenan por recorded_at en orden descendente.

        Args:
            db: Sesión de base de datos
            workstation_id: UUID de la workstation a consultar
            account_id: UUID de la cuenta (tenant isolation)
            check_id: Filtrar por identificador de check específico (opcional)
            from_dt: Fecha/hora mínima de recorded_at (opcional, inclusivo)
            to_dt: Fecha/hora máxima de recorded_at (opcional, inclusivo)
            limit: Número máximo de registros a devolver (default 100)

        Returns:
            Lista de ConnectivityResult ordenados por recorded_at DESC,
            limitados al número especificado
        """
        # Query base con tenant isolation: filtrar por workstation_id Y account_id
        query = db.query(ConnectivityResult).filter(
            ConnectivityResult.workstation_id == workstation_id,
            ConnectivityResult.account_id == account_id
        )

        # Filtro opcional por check_id
        if check_id is not None:
            query = query.filter(ConnectivityResult.check_id == check_id)

        # Filtro temporal: desde (inclusivo)
        if from_dt is not None:
            query = query.filter(ConnectivityResult.recorded_at >= from_dt)

        # Filtro temporal: hasta (inclusivo)
        if to_dt is not None:
            query = query.filter(ConnectivityResult.recorded_at <= to_dt)

        # Ordenar por recorded_at descendente y aplicar límite
        results = query.order_by(
            ConnectivityResult.recorded_at.desc()
        ).limit(limit).all()

        return results
