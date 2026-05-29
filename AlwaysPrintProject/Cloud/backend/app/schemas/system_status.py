"""
Schemas Pydantic para monitoreo de estado del sistema.

Este módulo define los schemas de validación y serialización para:
- Snapshots de estado del sistema (OS, Docker, health checks)
- Historial de métricas con estadísticas
- Alertas de umbrales excedidos
- Uptime de servicios
"""

from datetime import datetime
from typing import Optional, List, Literal
from uuid import UUID
from pydantic import BaseModel, Field


# === SCHEMAS DE REQUEST ===

class HistoryQueryParams(BaseModel):
    """
    Parámetros de consulta para el endpoint de historial de métricas.

    Permite filtrar por período de días y tipo de métrica específica.
    """
    days: int = Field(
        default=30,
        description="Período de días a consultar: 7, 14 o 30"
    )
    metric: Optional[str] = Field(
        default=None,
        description="Métrica específica a consultar: cpu, memory, disk, swap"
    )


# === SCHEMAS DE RESPUESTA — MÉTRICAS DEL SISTEMA OPERATIVO ===

class OsMetricsResponse(BaseModel):
    """
    Métricas del sistema operativo del servidor.

    Incluye información de memoria, disco, CPU y swap.
    """
    memory_total_mb: float = Field(..., description="Memoria RAM total en MB")
    memory_used_mb: float = Field(..., description="Memoria RAM usada en MB")
    memory_available_mb: float = Field(..., description="Memoria RAM disponible en MB")
    memory_percent: float = Field(..., description="Porcentaje de memoria RAM en uso")
    disk_total_mb: float = Field(..., description="Espacio total en disco en MB")
    disk_used_mb: float = Field(..., description="Espacio usado en disco en MB")
    disk_available_mb: float = Field(..., description="Espacio disponible en disco en MB")
    disk_percent: float = Field(..., description="Porcentaje de disco en uso")
    cpu_percent: float = Field(..., description="Porcentaje de uso de CPU")
    swap_total_mb: float = Field(..., description="Swap total en MB")
    swap_used_mb: float = Field(..., description="Swap usado en MB")
    swap_available_mb: float = Field(..., description="Swap disponible en MB")
    uptime_seconds: int = Field(..., description="Tiempo de actividad del servidor en segundos")

    model_config = {"from_attributes": True}


# === SCHEMAS DE RESPUESTA — MÉTRICAS DE CONTENEDORES DOCKER ===

class ContainerMetricsResponse(BaseModel):
    """
    Métricas de un contenedor Docker individual.

    Incluye estado, uso de recursos y tráfico de red.
    """
    name: str = Field(..., description="Nombre del contenedor")
    status: str = Field(..., description="Estado del contenedor: running, stopped, restarting")
    cpu_percent: float = Field(..., description="Porcentaje de uso de CPU del contenedor")
    memory_used_mb: float = Field(..., description="Memoria usada por el contenedor en MB")
    memory_limit_mb: float = Field(..., description="Límite de memoria del contenedor en MB")
    network_rx_bytes: int = Field(..., description="Bytes recibidos por red")
    network_tx_bytes: int = Field(..., description="Bytes transmitidos por red")
    uptime_seconds: int = Field(..., description="Tiempo de actividad del contenedor en segundos")

    model_config = {"from_attributes": True}


# === SCHEMAS DE RESPUESTA — HEALTH CHECKS ===

class HealthCheckResponse(BaseModel):
    """
    Resultado de un health check de un servicio externo.

    Incluye disponibilidad, latencia y detalles adicionales (ej: días SSL restantes).
    """
    service_name: str = Field(..., description="Nombre del servicio verificado")
    is_available: bool = Field(..., description="Si el servicio está disponible")
    latency_ms: Optional[float] = Field(None, description="Latencia de respuesta en milisegundos")
    error_message: Optional[str] = Field(None, description="Mensaje de error si el servicio no responde")
    details: Optional[dict] = Field(None, description="Detalles adicionales (ej: días SSL restantes)")

    model_config = {"from_attributes": True}


# === SCHEMAS DE RESPUESTA — ALERTAS ===

class AlertResponse(BaseModel):
    """
    Alerta generada cuando una métrica excede su umbral configurado.

    Incluye el valor actual, el umbral y la severidad.
    """
    metric_name: str = Field(..., description="Nombre de la métrica que generó la alerta")
    current_value: float = Field(..., description="Valor actual de la métrica")
    threshold: float = Field(..., description="Umbral configurado que fue excedido")
    severity: str = Field(..., description="Severidad de la alerta: warning, critical")

    model_config = {"from_attributes": True}


# === SCHEMAS DE RESPUESTA — SNAPSHOT COMPLETO ===

class StatusSnapshotResponse(BaseModel):
    """
    Snapshot completo del estado del sistema en un momento dado.

    Agrupa métricas del OS, contenedores Docker, health checks y alertas activas.
    """
    id: UUID = Field(..., description="Identificador único del snapshot")
    timestamp: datetime = Field(..., description="Timestamp UTC del snapshot")
    overall_status: str = Field(
        ...,
        description="Estado general del sistema: healthy, degraded, critical"
    )
    os_metrics: OsMetricsResponse = Field(..., description="Métricas del sistema operativo")
    docker_metrics: List[ContainerMetricsResponse] = Field(
        ...,
        description="Métricas de contenedores Docker"
    )
    health_checks: List[HealthCheckResponse] = Field(
        ...,
        description="Resultados de health checks de servicios"
    )
    alerts: List[AlertResponse] = Field(
        ...,
        description="Alertas activas por umbrales excedidos"
    )

    model_config = {"from_attributes": True}


# === SCHEMAS DE RESPUESTA — HISTORIAL DE MÉTRICAS ===

class HistoryDataPoint(BaseModel):
    """
    Punto de datos individual en el historial de una métrica.

    Representa un valor registrado en un momento específico.
    """
    timestamp: datetime = Field(..., description="Timestamp UTC del punto de datos")
    value: float = Field(..., description="Valor de la métrica en ese momento")


class MetricStats(BaseModel):
    """
    Estadísticas agregadas de una métrica en el período consultado.

    Incluye promedio, máximo, mínimo y cobertura de datos.
    """
    average: float = Field(..., description="Valor promedio en el período")
    maximum: float = Field(..., description="Valor máximo en el período")
    minimum: float = Field(..., description="Valor mínimo en el período")
    data_coverage_percent: float = Field(
        ...,
        description="Porcentaje de cobertura de datos en el período (0-100)"
    )


class HistoryResponse(BaseModel):
    """
    Respuesta del endpoint de historial de métricas.

    Incluye los puntos de datos y estadísticas agregadas del período.
    """
    metric: str = Field(..., description="Nombre de la métrica consultada")
    unit: str = Field(..., description="Unidad de medida de la métrica")
    data_points: List[HistoryDataPoint] = Field(
        ...,
        description="Lista de puntos de datos en el período"
    )
    stats: MetricStats = Field(..., description="Estadísticas agregadas del período")


# === SCHEMAS DE RESPUESTA — UPTIME DE SERVICIOS ===

class ServiceUptimeResponse(BaseModel):
    """
    Información de uptime de un servicio monitoreado.

    Calcula el porcentaje de disponibilidad basado en checks exitosos.
    """
    service_name: str = Field(..., description="Nombre del servicio")
    uptime_percent: float = Field(..., description="Porcentaje de disponibilidad (0-100)")
    total_checks: int = Field(..., description="Total de checks realizados")
    successful_checks: int = Field(..., description="Cantidad de checks exitosos")

    model_config = {"from_attributes": True}
