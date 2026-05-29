"""
Endpoints para monitoreo de estado del sistema.

Expone 5 endpoints protegidos con require_admin:
- GET /system-status/current — último snapshot completo
- GET /system-status/history — serie temporal con estadísticas
- GET /system-status/services — historial de disponibilidad (uptime %)
- POST /system-status/collect — trigger recolección manual
- GET /system-status/alerts — alertas activas por umbrales
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Integer, desc, func
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.security import require_admin
from app.models.system_status import (
    ContainerMetric,
    HealthCheckResult,
    MetricRecord,
    StatusSnapshot,
)
from app.models.user import User
from app.schemas.system_status import (
    AlertResponse,
    ContainerMetricsResponse,
    HealthCheckResponse,
    HistoryDataPoint,
    HistoryResponse,
    MetricStats,
    OsMetricsResponse,
    ServiceUptimeResponse,
    StatusSnapshotResponse,
)
from app.services.status_scheduler import status_scheduler

logger = logging.getLogger(__name__)

router = APIRouter()


# === FUNCIONES AUXILIARES ===


def _snapshot_to_response(
    snapshot: StatusSnapshot, alerts: List[AlertResponse]
) -> StatusSnapshotResponse:
    """
    Convierte un modelo StatusSnapshot a su schema de respuesta.

    Transforma las relaciones del snapshot (métricas OS, Docker, health checks)
    en los schemas Pydantic correspondientes.
    """
    # Construir métricas del sistema operativo desde el snapshot
    os_metrics = OsMetricsResponse(
        memory_total_mb=snapshot.memory_total_mb,
        memory_used_mb=snapshot.memory_used_mb,
        memory_available_mb=snapshot.memory_available_mb,
        memory_percent=snapshot.memory_percent,
        disk_total_mb=snapshot.disk_total_mb,
        disk_used_mb=snapshot.disk_used_mb,
        disk_available_mb=snapshot.disk_available_mb,
        disk_percent=snapshot.disk_percent,
        cpu_percent=snapshot.cpu_percent,
        swap_total_mb=snapshot.swap_total_mb,
        swap_used_mb=snapshot.swap_used_mb,
        swap_available_mb=snapshot.swap_available_mb,
        uptime_seconds=snapshot.uptime_seconds,
    )

    # Construir métricas de contenedores Docker
    # Mostrar todos los contenedores (running y stopped)
    docker_metrics = [
        ContainerMetricsResponse(
            name=cm.container_name,
            status=cm.status,
            cpu_percent=cm.cpu_percent,
            memory_used_mb=cm.memory_used_mb,
            memory_limit_mb=cm.memory_limit_mb,
            network_rx_bytes=cm.network_rx_bytes,
            network_tx_bytes=cm.network_tx_bytes,
            uptime_seconds=cm.uptime_seconds,
        )
        for cm in snapshot.container_metrics
    ]

    # Construir resultados de health checks
    health_checks = [
        HealthCheckResponse(
            service_name=hc.service_name,
            is_available=hc.is_available,
            latency_ms=hc.latency_ms,
            error_message=hc.error_message,
            details=json.loads(hc.details_json) if hc.details_json else None,
        )
        for hc in snapshot.health_check_results
    ]

    return StatusSnapshotResponse(
        id=snapshot.id,
        timestamp=snapshot.timestamp,
        overall_status=snapshot.overall_status.value
        if hasattr(snapshot.overall_status, "value")
        else snapshot.overall_status,
        os_metrics=os_metrics,
        docker_metrics=docker_metrics,
        health_checks=health_checks,
        alerts=alerts,
    )


def _get_metric_name_for_query(metric: str) -> str:
    """
    Mapea el nombre de métrica del query param al nombre almacenado en BD.

    Args:
        metric: Nombre corto de la métrica (cpu, memory, disk, swap)

    Returns:
        Nombre de la métrica como se almacena en metric_records
    """
    metric_map = {
        "cpu": "cpu_percent",
        "memory": "memory_percent",
        "disk": "disk_percent",
        "swap": "swap_percent",
    }
    return metric_map.get(metric, metric)


def _get_metric_unit(metric_name: str) -> str:
    """
    Obtiene la unidad de medida para una métrica dada.

    Args:
        metric_name: Nombre de la métrica almacenada

    Returns:
        Unidad de medida (percent, mb)
    """
    if metric_name.endswith("_percent"):
        return "percent"
    if metric_name.endswith("_mb"):
        return "mb"
    return "percent"


# === ENDPOINTS ===


@router.get(
    "/current",
    response_model=None,
    summary="Estado actual del sistema",
    description="Retorna el último snapshot completo con métricas, Docker, health checks y alertas",
)
async def get_current_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """
    Obtiene el último snapshot de estado del sistema.

    Carga el snapshot más reciente con todas sus relaciones (métricas,
    contenedores Docker, health checks) y calcula las alertas activas
    según los umbrales definidos.

    Retorna null si no hay snapshots disponibles.
    """
    # Obtener el último snapshot con sus relaciones cargadas
    snapshot = (
        db.query(StatusSnapshot)
        .options(
            joinedload(StatusSnapshot.metric_records),
            joinedload(StatusSnapshot.health_check_results),
            joinedload(StatusSnapshot.container_metrics),
        )
        .order_by(desc(StatusSnapshot.timestamp))
        .first()
    )

    if not snapshot:
        logger.info("No hay snapshots disponibles para mostrar estado actual")
        return {"data": None, "message": "No hay datos disponibles"}

    # Calcular alertas usando el collector
    from app.services.system_status import SystemStatusCollector

    collector = SystemStatusCollector()

    # Construir schemas necesarios para calcular alertas
    os_metrics = OsMetricsResponse(
        memory_total_mb=snapshot.memory_total_mb,
        memory_used_mb=snapshot.memory_used_mb,
        memory_available_mb=snapshot.memory_available_mb,
        memory_percent=snapshot.memory_percent,
        disk_total_mb=snapshot.disk_total_mb,
        disk_used_mb=snapshot.disk_used_mb,
        disk_available_mb=snapshot.disk_available_mb,
        disk_percent=snapshot.disk_percent,
        cpu_percent=snapshot.cpu_percent,
        swap_total_mb=snapshot.swap_total_mb,
        swap_used_mb=snapshot.swap_used_mb,
        swap_available_mb=snapshot.swap_available_mb,
        uptime_seconds=snapshot.uptime_seconds,
    )

    health_checks = [
        HealthCheckResponse(
            service_name=hc.service_name,
            is_available=hc.is_available,
            latency_ms=hc.latency_ms,
            error_message=hc.error_message,
            details=json.loads(hc.details_json) if hc.details_json else None,
        )
        for hc in snapshot.health_check_results
    ]

    docker_metrics = [
        ContainerMetricsResponse(
            name=cm.container_name,
            status=cm.status,
            cpu_percent=cm.cpu_percent,
            memory_used_mb=cm.memory_used_mb,
            memory_limit_mb=cm.memory_limit_mb,
            network_rx_bytes=cm.network_rx_bytes,
            network_tx_bytes=cm.network_tx_bytes,
            uptime_seconds=cm.uptime_seconds,
        )
        for cm in snapshot.container_metrics
    ]

    _, alerts = collector.calculate_overall_status(
        os_metrics, health_checks, docker_metrics
    )

    return _snapshot_to_response(snapshot, alerts)


@router.get(
    "/history",
    response_model=HistoryResponse,
    summary="Historial de métricas",
    description="Retorna serie temporal de una métrica con estadísticas agregadas",
)
async def get_metric_history(
    days: int = Query(
        default=30,
        description="Período en días: 7, 14 o 30",
    ),
    metric: Optional[str] = Query(
        default=None,
        description="Métrica a consultar: cpu, memory, disk, swap",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """
    Obtiene el historial de una métrica específica con estadísticas.

    Filtra los MetricRecords por rango temporal y calcula estadísticas
    agregadas (promedio, máximo, mínimo) y cobertura de datos.

    Si no se especifica métrica, se usa cpu_percent por defecto.
    """
    # Determinar métrica a consultar
    metric_name = _get_metric_name_for_query(metric) if metric else "cpu_percent"
    unit = _get_metric_unit(metric_name)

    # Calcular rango temporal
    now = datetime.now(timezone.utc)
    start_date = now - timedelta(days=days)

    # Consultar puntos de datos en el rango
    records = (
        db.query(MetricRecord)
        .filter(
            MetricRecord.metric_name == metric_name,
            MetricRecord.timestamp >= start_date,
            MetricRecord.timestamp <= now,
        )
        .order_by(MetricRecord.timestamp)
        .all()
    )

    # Construir puntos de datos
    data_points = [
        HistoryDataPoint(timestamp=record.timestamp, value=record.value)
        for record in records
    ]

    # Calcular estadísticas agregadas
    if records:
        values = [record.value for record in records]
        average = round(sum(values) / len(values), 1)
        maximum = round(max(values), 1)
        minimum = round(min(values), 1)
    else:
        average = 0.0
        maximum = 0.0
        minimum = 0.0

    # Calcular cobertura de datos
    # Se esperan 4 recolecciones por día (cada 6 horas)
    expected_points = days * 4
    actual_points = len(records)
    data_coverage_percent = round(
        (actual_points / expected_points) * 100, 1
    ) if expected_points > 0 else 0.0

    # Limitar cobertura a 100% máximo
    data_coverage_percent = min(data_coverage_percent, 100.0)

    stats = MetricStats(
        average=average,
        maximum=maximum,
        minimum=minimum,
        data_coverage_percent=data_coverage_percent,
    )

    return HistoryResponse(
        metric=metric_name,
        unit=unit,
        data_points=data_points,
        stats=stats,
    )


@router.get(
    "/services",
    response_model=List[ServiceUptimeResponse],
    summary="Disponibilidad de servicios",
    description="Retorna el historial de uptime por servicio en el período seleccionado",
)
async def get_services_uptime(
    days: int = Query(
        default=30,
        description="Período en días: 7, 14 o 30",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """
    Calcula el porcentaje de disponibilidad de cada servicio monitoreado.

    Para cada servicio, calcula:
    uptime_percent = (checks_disponibles / total_checks) * 100

    Filtra los HealthCheckResults por rango temporal.
    """
    # Calcular rango temporal
    now = datetime.now(timezone.utc)
    start_date = now - timedelta(days=days)

    # Consultar resultados de health checks agrupados por servicio
    results = (
        db.query(
            HealthCheckResult.service_name,
            func.count(HealthCheckResult.id).label("total_checks"),
            func.sum(
                func.cast(HealthCheckResult.is_available, Integer)
            ).label("successful_checks"),
        )
        .filter(
            HealthCheckResult.timestamp >= start_date,
            HealthCheckResult.timestamp <= now,
        )
        .group_by(HealthCheckResult.service_name)
        .all()
    )

    # Construir respuesta con cálculo de uptime
    services = []
    for row in results:
        total = row.total_checks
        successful = row.successful_checks or 0
        uptime_percent = round((successful / total) * 100, 2) if total > 0 else 0.0

        services.append(
            ServiceUptimeResponse(
                service_name=row.service_name,
                uptime_percent=uptime_percent,
                total_checks=total,
                successful_checks=successful,
            )
        )

    return services


@router.post(
    "/collect",
    response_model=None,
    summary="Recolección manual",
    description="Dispara una recolección manual de métricas del sistema",
)
async def trigger_collection(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """
    Ejecuta una recolección manual de métricas.

    Llama al scheduler para ejecutar la recolección bajo demanda.
    Retorna HTTP 409 si ya hay una recolección en curso.
    """
    logger.info(
        f"Recolección manual solicitada por usuario: {current_user.email}"
    )

    # Ejecutar recolección manual via scheduler
    snapshot = await status_scheduler.trigger_manual_collection(db)

    # Recargar el snapshot con sus relaciones
    snapshot_loaded = (
        db.query(StatusSnapshot)
        .options(
            joinedload(StatusSnapshot.metric_records),
            joinedload(StatusSnapshot.health_check_results),
            joinedload(StatusSnapshot.container_metrics),
        )
        .filter(StatusSnapshot.id == snapshot.id)
        .first()
    )

    # Calcular alertas para la respuesta
    from app.services.system_status import SystemStatusCollector

    collector = SystemStatusCollector()

    os_metrics = OsMetricsResponse(
        memory_total_mb=snapshot_loaded.memory_total_mb,
        memory_used_mb=snapshot_loaded.memory_used_mb,
        memory_available_mb=snapshot_loaded.memory_available_mb,
        memory_percent=snapshot_loaded.memory_percent,
        disk_total_mb=snapshot_loaded.disk_total_mb,
        disk_used_mb=snapshot_loaded.disk_used_mb,
        disk_available_mb=snapshot_loaded.disk_available_mb,
        disk_percent=snapshot_loaded.disk_percent,
        cpu_percent=snapshot_loaded.cpu_percent,
        swap_total_mb=snapshot_loaded.swap_total_mb,
        swap_used_mb=snapshot_loaded.swap_used_mb,
        swap_available_mb=snapshot_loaded.swap_available_mb,
        uptime_seconds=snapshot_loaded.uptime_seconds,
    )

    health_checks = [
        HealthCheckResponse(
            service_name=hc.service_name,
            is_available=hc.is_available,
            latency_ms=hc.latency_ms,
            error_message=hc.error_message,
            details=json.loads(hc.details_json) if hc.details_json else None,
        )
        for hc in snapshot_loaded.health_check_results
    ]

    docker_metrics = [
        ContainerMetricsResponse(
            name=cm.container_name,
            status=cm.status,
            cpu_percent=cm.cpu_percent,
            memory_used_mb=cm.memory_used_mb,
            memory_limit_mb=cm.memory_limit_mb,
            network_rx_bytes=cm.network_rx_bytes,
            network_tx_bytes=cm.network_tx_bytes,
            uptime_seconds=cm.uptime_seconds,
        )
        for cm in snapshot_loaded.container_metrics
    ]

    _, alerts = collector.calculate_overall_status(
        os_metrics, health_checks, docker_metrics
    )

    return _snapshot_to_response(snapshot_loaded, alerts)


@router.get(
    "/alerts",
    response_model=List[AlertResponse],
    summary="Alertas activas",
    description="Retorna las alertas activas basadas en el último snapshot",
)
async def get_active_alerts(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """
    Obtiene las alertas activas del último snapshot.

    Carga el snapshot más reciente y calcula las alertas según
    los umbrales definidos. Si no hay snapshots, retorna lista vacía.
    """
    # Obtener el último snapshot con sus relaciones
    snapshot = (
        db.query(StatusSnapshot)
        .options(
            joinedload(StatusSnapshot.health_check_results),
            joinedload(StatusSnapshot.container_metrics),
        )
        .order_by(desc(StatusSnapshot.timestamp))
        .first()
    )

    if not snapshot:
        logger.info("No hay snapshots disponibles para calcular alertas")
        return []

    # Calcular alertas usando el collector
    from app.services.system_status import SystemStatusCollector

    collector = SystemStatusCollector()

    os_metrics = OsMetricsResponse(
        memory_total_mb=snapshot.memory_total_mb,
        memory_used_mb=snapshot.memory_used_mb,
        memory_available_mb=snapshot.memory_available_mb,
        memory_percent=snapshot.memory_percent,
        disk_total_mb=snapshot.disk_total_mb,
        disk_used_mb=snapshot.disk_used_mb,
        disk_available_mb=snapshot.disk_available_mb,
        disk_percent=snapshot.disk_percent,
        cpu_percent=snapshot.cpu_percent,
        swap_total_mb=snapshot.swap_total_mb,
        swap_used_mb=snapshot.swap_used_mb,
        swap_available_mb=snapshot.swap_available_mb,
        uptime_seconds=snapshot.uptime_seconds,
    )

    health_checks = [
        HealthCheckResponse(
            service_name=hc.service_name,
            is_available=hc.is_available,
            latency_ms=hc.latency_ms,
            error_message=hc.error_message,
            details=json.loads(hc.details_json) if hc.details_json else None,
        )
        for hc in snapshot.health_check_results
    ]

    docker_metrics = [
        ContainerMetricsResponse(
            name=cm.container_name,
            status=cm.status,
            cpu_percent=cm.cpu_percent,
            memory_used_mb=cm.memory_used_mb,
            memory_limit_mb=cm.memory_limit_mb,
            network_rx_bytes=cm.network_rx_bytes,
            network_tx_bytes=cm.network_tx_bytes,
            uptime_seconds=cm.uptime_seconds,
        )
        for cm in snapshot.container_metrics
    ]

    _, alerts = collector.calculate_overall_status(
        os_metrics, health_checks, docker_metrics
    )

    return alerts
