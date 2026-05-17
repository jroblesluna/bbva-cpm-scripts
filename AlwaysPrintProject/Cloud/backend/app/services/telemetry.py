"""
Servicio de persistencia y consulta de telemetría.

Este servicio implementa la lógica de negocio para:
- Persistir registros de telemetría recibidos por WebSocket
- Consultar historial de telemetría por workstation con filtrado temporal
- Computar estadísticas agregadas de telemetría por cuenta (últimas 24h)

Todas las queries aplican tenant isolation filtrando por account_id.
"""

from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct, desc

from app.models.telemetry import TelemetryLog
from app.models.workstation import Workstation
from app.schemas.telemetry import TelemetryMessagePayload, TelemetryStatsResponse, QueueStatusSummary


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
        account_id: str,
        payload: TelemetryMessagePayload
    ) -> Optional[TelemetryLog]:
        """
        Persiste un registro de telemetría en la base de datos.

        Verifica que la workstation exista y pertenezca a la cuenta indicada
        (tenant isolation) antes de crear el registro.

        El campo disconnection_count se calcula como la longitud del array
        disconnection_log del payload.

        Args:
            db: Sesión de base de datos
            workstation_id: UUID de la workstation que envía la telemetría
            account_id: UUID de la cuenta del sender (tenant isolation)
            payload: Payload validado con los datos de telemetría

        Returns:
            TelemetryLog creado si la persistencia fue exitosa, None si la
            workstation no existe o no pertenece a la cuenta
        """
        # Verificar que la workstation existe para esta cuenta (tenant isolation)
        workstation = db.query(Workstation).filter(
            Workstation.id == workstation_id,
            Workstation.organization_id == account_id
        ).first()

        if not workstation:
            return None

        # Calcular disconnection_count como longitud del array disconnection_log
        disconnection_count = len(payload.disconnection_log)

        # Crear registro de telemetría
        telemetry_log = TelemetryLog(
            workstation_id=workstation_id,
            organization_id=account_id,
            queue_status=payload.queue_status,
            contingency_active=payload.contingency_active,
            jobs_identified=payload.jobs_identified,
            avg_release_time_ms=payload.avg_release_time_ms,
            disconnection_count=disconnection_count,
            recorded_at=datetime.utcnow()
        )

        db.add(telemetry_log)
        db.commit()
        db.refresh(telemetry_log)

        return telemetry_log

    def get_telemetry_history(
        self,
        db: Session,
        workstation_id: str,
        account_id: str,
        from_dt: Optional[datetime] = None,
        to_dt: Optional[datetime] = None,
        limit: int = 100
    ) -> List[TelemetryLog]:
        """
        Consulta el historial de telemetría de una workstation.

        Filtra por workstation_id Y account_id (tenant isolation).
        Soporta filtrado temporal opcional con from_dt y to_dt.
        Ordena por recorded_at descendente (más reciente primero).

        Args:
            db: Sesión de base de datos
            workstation_id: UUID de la workstation a consultar
            account_id: UUID de la cuenta del usuario autenticado (tenant isolation)
            from_dt: Fecha/hora mínima de filtrado (opcional, inclusivo)
            to_dt: Fecha/hora máxima de filtrado (opcional, inclusivo)
            limit: Número máximo de registros a devolver (default 100)

        Returns:
            Lista de TelemetryLog ordenados por recorded_at DESC, limitados a `limit`
        """
        # Query base con tenant isolation
        query = db.query(TelemetryLog).filter(
            TelemetryLog.workstation_id == workstation_id,
            TelemetryLog.organization_id == account_id
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
        account_id: str
    ) -> TelemetryStatsResponse:
        """
        Computa estadísticas agregadas de telemetría para una cuenta.

        Todas las estadísticas se calculan sobre registros de las últimas
        24 horas UTC. Incluye:
        - total_workstations: todas las workstations registradas para la cuenta
        - workstations_reporting: workstations con al menos un registro en 24h
        - avg_jobs_identified: promedio aritmético de jobs_identified en 24h
        - contingency_active_count: workstations cuyo registro más reciente
          en 24h tiene contingency_active=True
        - queue_status_summary: conteo por estado de cola del registro más
          reciente por workstation en 24h
        - last_updated: timestamp del registro más reciente o null

        Args:
            db: Sesión de base de datos
            account_id: UUID de la cuenta (tenant isolation)

        Returns:
            TelemetryStatsResponse con las estadísticas agregadas
        """
        # Ventana temporal: últimas 24 horas UTC
        now = datetime.utcnow()
        since = now - timedelta(hours=24)

        # Total de workstations registradas para la cuenta
        total_workstations = db.query(Workstation).filter(
            Workstation.organization_id == account_id
        ).count()

        # Registros de telemetría en las últimas 24h para esta cuenta
        recent_logs = db.query(TelemetryLog).filter(
            TelemetryLog.organization_id == account_id,
            TelemetryLog.recorded_at >= since
        )

        # Workstations con al menos un registro en 24h
        workstations_reporting = db.query(
            distinct(TelemetryLog.workstation_id)
        ).filter(
            TelemetryLog.organization_id == account_id,
            TelemetryLog.recorded_at >= since
        ).count()

        # Promedio de jobs_identified en 24h (todos los registros)
        avg_result = db.query(
            func.avg(TelemetryLog.jobs_identified)
        ).filter(
            TelemetryLog.organization_id == account_id,
            TelemetryLog.recorded_at >= since,
            TelemetryLog.jobs_identified.isnot(None)
        ).scalar()

        avg_jobs_identified = round(float(avg_result), 2) if avg_result is not None else 0.0

        # Timestamp del registro más reciente
        last_updated = db.query(
            func.max(TelemetryLog.recorded_at)
        ).filter(
            TelemetryLog.organization_id == account_id,
            TelemetryLog.recorded_at >= since
        ).scalar()

        # Para contingency_active_count y queue_status_summary necesitamos
        # el registro más reciente por workstation en las últimas 24h
        # Subconsulta: obtener el recorded_at máximo por workstation en 24h
        latest_per_ws = db.query(
            TelemetryLog.workstation_id,
            func.max(TelemetryLog.recorded_at).label("max_recorded_at")
        ).filter(
            TelemetryLog.organization_id == account_id,
            TelemetryLog.recorded_at >= since
        ).group_by(TelemetryLog.workstation_id).subquery()

        # Obtener los registros más recientes por workstation
        most_recent_logs = db.query(TelemetryLog).join(
            latest_per_ws,
            (TelemetryLog.workstation_id == latest_per_ws.c.workstation_id) &
            (TelemetryLog.recorded_at == latest_per_ws.c.max_recorded_at)
        ).filter(
            TelemetryLog.organization_id == account_id
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
