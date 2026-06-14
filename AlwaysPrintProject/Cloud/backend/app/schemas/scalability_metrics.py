"""
Schemas Pydantic para métricas de escalabilidad del sistema.

Este módulo define los schemas de validación y serialización para las 5 métricas
de escalabilidad orientadas a soportar 5000 workstations concurrentes:
- Conexiones WebSocket activas
- Memoria del proceso Python
- File descriptors
- Tráfico de red
- Estado del pool de base de datos
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# === SCHEMAS DE RESPUESTA — CONEXIONES WEBSOCKET ===

class WebSocketMetricsResponse(BaseModel):
    """
    Métricas de conexiones WebSocket activas.

    Incluye conteo de workstations, operadores y total combinado.
    """
    workstation_count: int = Field(
        ..., ge=0, le=10000,
        description="Conteo de conexiones WebSocket de workstations activas"
    )
    operator_count: int = Field(
        ..., ge=0, le=1000,
        description="Conteo de conexiones WebSocket de operadores únicos"
    )
    total: int = Field(
        ..., ge=0,
        description="Total combinado de conexiones (workstations + operadores)"
    )
    data_available: bool = Field(
        default=True,
        description="Indica si los datos pudieron ser obtenidos del ConnectionManager"
    )

    model_config = {"from_attributes": True}


# === SCHEMAS DE RESPUESTA — MEMORIA DEL PROCESO PYTHON ===

class PythonMemoryResponse(BaseModel):
    """
    Métricas de memoria del proceso Python dentro del contenedor.

    Incluye RSS, memoria total del contenedor y promedio por workstation.
    """
    rss_mb: Optional[float] = Field(
        None,
        description="RSS en MB, 2 decimales"
    )
    container_total_mb: Optional[float] = Field(
        None,
        description="Memoria total contenedor MB"
    )
    avg_per_workstation_mb: Optional[float] = Field(
        None,
        description="Promedio MB/ws"
    )

    model_config = {"from_attributes": True}


# === SCHEMAS DE RESPUESTA — FILE DESCRIPTORS ===

class FileDescriptorResponse(BaseModel):
    """
    Métricas de file descriptors del proceso Python.

    Incluye conteo abierto, límite del sistema y porcentaje de uso.
    """
    open_count: Optional[int] = Field(
        None, ge=0,
        description="Conteo de file descriptors abiertos"
    )
    limit: Optional[int] = Field(
        None, gt=0,
        description="Límite máximo de file descriptors (soft limit)"
    )
    usage_percent: Optional[float] = Field(
        None,
        description="Porcentaje de uso de file descriptors"
    )

    model_config = {"from_attributes": True}


# === SCHEMAS DE RESPUESTA — TRÁFICO DE RED ===

class NetworkTrafficResponse(BaseModel):
    """
    Métricas de tráfico de red del contenedor.

    Incluye bytes totales recibidos/transmitidos y tasas calculadas.
    """
    rx_bytes: Optional[int] = Field(
        None, ge=0,
        description="Bytes totales recibidos (rx)"
    )
    tx_bytes: Optional[int] = Field(
        None, ge=0,
        description="Bytes totales transmitidos (tx)"
    )
    rx_rate_bps: Optional[float] = Field(
        None,
        description="Tasa de recepción en bytes por segundo"
    )
    tx_rate_bps: Optional[float] = Field(
        None,
        description="Tasa de transmisión en bytes por segundo"
    )

    model_config = {"from_attributes": True}


# === SCHEMAS DE RESPUESTA — POOL DE BASE DE DATOS ===

class DbPoolResponse(BaseModel):
    """
    Métricas del pool de conexiones SQLAlchemy y conexiones PostgreSQL.

    Incluye estado del pool local y conteo de conexiones activas en la BD.
    """
    checked_out: Optional[int] = Field(
        None, ge=0,
        description="Conexiones checked_out (en uso)"
    )
    idle: Optional[int] = Field(
        None, ge=0,
        description="Conexiones idle (disponibles)"
    )
    pool_size: Optional[int] = Field(
        None, gt=0,
        description="Tamaño base del pool"
    )
    overflow: Optional[int] = Field(
        None,
        description="Conexiones de overflow actuales (negativo indica capacidad disponible)"
    )
    max_overflow: Optional[int] = Field(
        None, ge=0,
        description="Máximo de overflow permitido"
    )
    pg_active_connections: Optional[int] = Field(
        None, ge=0,
        description="Conexiones activas en PostgreSQL (pg_stat_activity)"
    )
    usage_percent: Optional[float] = Field(
        None,
        description="Porcentaje de uso del pool (checked_out / pool_size * 100)"
    )

    model_config = {"from_attributes": True}


# === SCHEMA DE RESPUESTA PRINCIPAL — MÉTRICAS DE ESCALABILIDAD ===

class ScalabilityMetricsResponse(BaseModel):
    """
    Respuesta completa del endpoint de métricas de escalabilidad.

    Agrupa las 5 métricas de escalabilidad. Cada métrica puede ser null
    si su colector individual falla (degradación parcial).
    """
    websocket: Optional[WebSocketMetricsResponse] = Field(
        None,
        description="Métricas de conexiones WebSocket activas"
    )
    python_memory: Optional[PythonMemoryResponse] = Field(
        None,
        description="Métricas de memoria del proceso Python"
    )
    file_descriptors: Optional[FileDescriptorResponse] = Field(
        None,
        description="Métricas de file descriptors"
    )
    network: Optional[NetworkTrafficResponse] = Field(
        None,
        description="Métricas de tráfico de red"
    )
    db_pool: Optional[DbPoolResponse] = Field(
        None,
        description="Métricas del pool de base de datos"
    )
    collected_at: datetime = Field(
        ...,
        description="Timestamp UTC de la recolección de métricas"
    )

    model_config = {"from_attributes": True}
