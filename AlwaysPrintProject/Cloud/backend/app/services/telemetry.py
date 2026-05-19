"""
Servicio de persistencia y consulta de telemetría.

Este servicio implementa la lógica de negocio para:
- Persistir registros de telemetría recibidos por WebSocket
- Consultar historial de telemetría por workstation con filtrado temporal
- Computar estadísticas agregadas de telemetría por organización (últimas 24h)

Todas las queries aplican tenant isolation filtrando por organization_id.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct, desc

from app.models.telemetry import TelemetryLog
from app.models.workstation import Workstation
from app.schemas.telemetry import (
    TelemetryMessagePayload,
    TelemetryStatsResponse,
    TelemetryLatestBatchResponse,
    TelemetryLatestBatchRequest,
    TelemetryLogResponse,
    QueueStatusSummary,
)


class TelemetryService:
    """
    Servicio para gestión de telemetría de workstations.

    Proporciona métodos para:
    - Persistir registros de telemetría con validación de tenant
    - Consultar historial con filtrado temporal y paginación
    - Computar estadísticas agregadas de las últimas 24 horas UTC
    """

    def persist_telemetry(
        self,
        db: Session,
        workstation_id: str,
        organization_id: str,
        payload: TelemetryMessagePayload
    ) -> Optional[TelemetryLog]:
        """
        Persiste un registro de telemetría en la base de datos.

        Verifica que la workstation exista y pertenezca a la organización indicada
        (tenant isolation) antes de crear el registro.

        El campo disconnection_count se calcula como la longitud del array
        disconnection_log del payload.

        Args:
            db: Sesión de base de datos
            workstation_id: UUID de la workstation que envía la telemetría
            organization_id: UUID de la organización del sender (tenant isolation)
            payload: Payload validado con los datos de telemetría

        Returns:
            TelemetryLog creado si la persistencia fue exitosa, None si la
            workstation no existe o no pertenece a la organización
        """
        # Verificar que la workstation existe para esta organización (tenant isolation)
        workstation = db.query(Workstation).filter(
            Workstation.id == workstation_id,
            Workstation.organization_id == organization_id
        ).first()

        if not workstation:
            return None

        # Calcular disconnection_count como longitud del array disconnection_log
        disconnection_count = len(payload.disconnection_log)

        # Crear registro de telemetría
        telemetry_log = TelemetryLog(
            workstation_id=workstation_id,
            organization_id=organization_id,
            queue_status=payload.queue_status,
            contingency_active=payload.contingency_active,
            jobs_identified=payload.jobs_identified,
            avg_release_time_ms=payload.avg_release_time_ms,
            disconnection_count=disconnection_count,
            recorded_at=datetime.now(timezone.utc).replace(tzinfo=None)
        )

        db.add(telemetry_log)
        db.commit()
        db.refresh(telemetry_log)

        return telemetry_log

    def get_telemetry_history(
        self,
        db: Session,
        workstation_id: str,
        organization_id: str,
        from_dt: Optional[datetime] = None,
        to_dt: Optional[datetime] = None,
        limit: int = 100
    ) -> List[TelemetryLog]:
        """
        Consulta el historial de telemetría de una workstation.

        Filtra por workstation_id Y organization_id (tenant isolation).
        Soporta filtrado temporal opcional con from_dt y to_dt.
        Ordena por recorded_at descendente (más reciente primero).

        Args:
            db: Sesión de base de datos
            workstation_id: UUID de la workstation a consultar
            organization_id: UUID de la organización del usuario autenticado (tenant isolation)
            from_dt: Fecha/hora mínima de filtrado (opcional, inclusivo)
            to_dt: Fecha/hora máxima de filtrado (opcional, inclusivo)
            limit: Número máximo de registros a devolver (default 100)

        Returns:
            Lista de TelemetryLog ordenados por recorded_at DESC, limitados a `limit`
        """
        # Query base con tenant isolation
        query = db.query(TelemetryLog).filter(
            TelemetryLog.workstation_id == workstation_id,
            TelemetryLog.organization_id == organization_id
        )

        # Aplicar filtros temporales opcionales
        if from_dt is not None:
            query = query.filter(TelemetryLog.recorded_at >= from_dt)

        if to_dt is not None:
            query = query.filter(TelemetryLog.recorded_at <= to_dt)

        # Ordenar por recorded_at descendente y aplicar límite
        query = query.order_by(desc(TelemetryLog.recorded_at)).limit(limit)

        return query.all()

    def get_telemetry_stats(
        self,
        db: Session,
        organization_id: str
    ) -> TelemetryStatsResponse:
        """
        Computa estadísticas agregadas de telemetría para una organización.

        Todas las estadísticas se calculan sobre registros de las últimas
        24 horas UTC. Incluye:
        - total_workstations: todas las workstations registradas para la organización
        - workstations_reporting: workstations con al menos un registro en 24h
        - avg_jobs_identified: promedio aritmético de jobs_identified en 24h
        - contingency_active_count: workstations cuyo registro más reciente
          en 24h tiene contingency_active=True
        - queue_status_summary: conteo por estado de cola del registro más
          reciente por workstation en 24h
        - last_updated: timestamp del registro más reciente o null

        Args:
            db: Sesión de base de datos
            organization_id: UUID de la organización (tenant isolation)

        Returns:
            TelemetryStatsResponse con las estadísticas agregadas
        """
        # Ventana temporal: últimas 24 horas UTC
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        since = now - timedelta(hours=24)

        # Total de workstations registradas para la organización
        total_workstations = db.query(Workstation).filter(
            Workstation.organization_id == organization_id
        ).count()

        # Registros de telemetría en las últimas 24h para esta organización
        recent_logs = db.query(TelemetryLog).filter(
            TelemetryLog.organization_id == organization_id,
            TelemetryLog.recorded_at >= since
        )

        # Workstations con al menos un registro en 24h
        workstations_reporting = db.query(
            distinct(TelemetryLog.workstation_id)
        ).filter(
            TelemetryLog.organization_id == organization_id,
            TelemetryLog.recorded_at >= since
        ).count()

        # Promedio de jobs_identified en 24h (todos los registros)
        avg_result = db.query(
            func.avg(TelemetryLog.jobs_identified)
        ).filter(
            TelemetryLog.organization_id == organization_id,
            TelemetryLog.recorded_at >= since,
            TelemetryLog.jobs_identified.isnot(None)
        ).scalar()

        avg_jobs_identified = round(float(avg_result), 2) if avg_result is not None else 0.0

        # Timestamp del registro más reciente
        last_updated = db.query(
            func.max(TelemetryLog.recorded_at)
        ).filter(
            TelemetryLog.organization_id == organization_id,
            TelemetryLog.recorded_at >= since
        ).scalar()

        # Para contingency_active_count y queue_status_summary necesitamos
        # el registro más reciente por workstation en las últimas 24h
        # Subconsulta: obtener el recorded_at máximo por workstation en 24h
        latest_per_ws = db.query(
            TelemetryLog.workstation_id,
            func.max(TelemetryLog.recorded_at).label("max_recorded_at")
        ).filter(
            TelemetryLog.organization_id == organization_id,
            TelemetryLog.recorded_at >= since
        ).group_by(TelemetryLog.workstation_id).subquery()

        # Obtener los registros más recientes por workstation
        most_recent_logs = db.query(TelemetryLog).join(
            latest_per_ws,
            (TelemetryLog.workstation_id == latest_per_ws.c.workstation_id) &
            (TelemetryLog.recorded_at == latest_per_ws.c.max_recorded_at)
        ).filter(
            TelemetryLog.organization_id == organization_id
        ).all()

        # Contar workstations con contingency_active=True en su registro más reciente
        contingency_active_count = sum(
            1 for log in most_recent_logs
            if log.contingency_active is True
        )

        # Resumen de queue_status del registro más reciente por workstation
        queue_summary = {"ok": 0, "missing": 0, "error": 0}
        for log in most_recent_logs:
            status = log.queue_status
            if status in queue_summary:
                queue_summary[status] += 1

        return TelemetryStatsResponse(
            total_workstations=total_workstations,
            workstations_reporting=workstations_reporting,
            avg_jobs_identified=avg_jobs_identified,
            contingency_active_count=contingency_active_count,
            queue_status_summary=QueueStatusSummary(**queue_summary),
            last_updated=last_updated
        )

    def get_latest_telemetry_batch(
        self,
        db: Session,
        workstation_ids: List[str],
        organization_id: Optional[str] = None
    ) -> TelemetryLatestBatchResponse:
        """
        Obtiene la última telemetría de un conjunto de workstations.

        Si organization_id se proporciona (usuario Operador), verifica que
        las workstations pertenezcan a esa organización (tenant isolation).
        Si organization_id es None (usuario Admin), consulta sin restricción.

        Args:
            db: Sesión de base de datos
            workstation_ids: Lista de UUIDs de workstations a consultar (máx 100)
            organization_id: UUID de la organización para tenant isolation (None para Admin)

        Returns:
            TelemetryLatestBatchResponse con el mapa de última telemetría por workstation
        """
        if not workstation_ids:
            return TelemetryLatestBatchResponse(items={})

        # Verificar que las workstations existen (y pertenecen a la organización si aplica)
        ws_query = db.query(Workstation).filter(
            Workstation.id.in_(workstation_ids)
        )
        if organization_id:
            ws_query = ws_query.filter(Workstation.organization_id == organization_id)

        valid_workstations = ws_query.all()
        valid_ids = [str(ws.id) for ws in valid_workstations]

        if not valid_ids:
            # Retornar null para todos los IDs solicitados
            return TelemetryLatestBatchResponse(
                items={ws_id: None for ws_id in workstation_ids}
            )

        # Subconsulta: obtener el recorded_at máximo por workstation
        latest_per_ws = db.query(
            TelemetryLog.workstation_id,
            func.max(TelemetryLog.recorded_at).label("max_recorded_at")
        ).filter(
            TelemetryLog.workstation_id.in_(valid_ids)
        ).group_by(TelemetryLog.workstation_id).subquery()

        # Obtener los registros más recientes por workstation
        most_recent_logs = db.query(TelemetryLog).join(
            latest_per_ws,
            (TelemetryLog.workstation_id == latest_per_ws.c.workstation_id) &
            (TelemetryLog.recorded_at == latest_per_ws.c.max_recorded_at)
        ).all()

        # Construir mapa workstation_id → último registro
        logs_by_ws = {str(log.workstation_id): log for log in most_recent_logs}

        items = {}
        for ws_id in workstation_ids:
            log = logs_by_ws.get(ws_id)
            if log:
                items[ws_id] = TelemetryLogResponse.model_validate(log)
            else:
                items[ws_id] = None

        return TelemetryLatestBatchResponse(items=items)
