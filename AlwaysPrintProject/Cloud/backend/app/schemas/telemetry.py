"""
Schemas Pydantic para telemetría y conectividad.

Este módulo define los schemas de validación para:
- Payloads de mensajes WebSocket entrantes (telemetría y conectividad)
- Respuestas de endpoints REST de historial y estadísticas
"""

from datetime import datetime
from typing import Optional, List, Literal
from uuid import UUID
from pydantic import BaseModel, Field


# === SCHEMAS DE PAYLOADS WEBSOCKET ENTRANTES ===

class DisconnectionEventPayload(BaseModel):
    """Evento de desconexión dentro del payload de telemetría."""
    started_at: str = Field(..., description="Timestamp UTC de inicio de desconexión (ISO 8601)")
    reconnected_at: Optional[str] = Field(None, description="Timestamp UTC de reconexión (ISO 8601)")
    duration_seconds: Optional[int] = Field(None, description="Duración de la desconexión en segundos")


class TelemetryMessagePayload(BaseModel):
    """
    Payload para validar mensajes WebSocket entrantes de telemetría.

    Valida los campos enviados por el Tray Client en cada intervalo
    de telemetría configurado.
    """
    queue_status: Literal["ok", "missing", "error"] = Field(
        ...,
        description="Estado de la cola de impresión: ok, missing o error"
    )
    contingency_active: bool = Field(
        ...,
        description="Indica si la contingencia está activa en la workstation"
    )
    jobs_identified: int = Field(
        ...,
        ge=0,
        le=2147483647,
        description="Cantidad de trabajos identificados (0 a 2,147,483,647)"
    )
    avg_release_time_ms: Optional[int] = Field(
        None,
        ge=0,
        le=9223372036854775807,
        description="Tiempo promedio de liberación en ms (null si no hay trabajos)"
    )
    disconnection_log: List[DisconnectionEventPayload] = Field(
        default_factory=list,
        max_length=1000,
        description="Lista de eventos de desconexión (máximo 1000 elementos)"
    )


class ConnectivityResultPayload(BaseModel):
    """
    Payload para validar mensajes WebSocket entrantes de resultados de conectividad.

    Valida los campos enviados por el Tray Client tras ejecutar un check
    de conectividad configurado.
    """
    check_id: str = Field(
        ...,
        max_length=100,
        description="Identificador del check de conectividad (máx 100 caracteres)"
    )
    check_type: Literal["http", "tcp", "ping", "dns"] = Field(
        ...,
        description="Tipo de check ejecutado: http, tcp, ping o dns"
    )
    success: bool = Field(
        ...,
        description="Indica si el check fue exitoso"
    )
    latency_ms: Optional[int] = Field(
        None,
        ge=0,
        le=2147483647,
        description="Latencia en milisegundos (null si el check falló)"
    )
    error: Optional[str] = Field(
        None,
        max_length=500,
        description="Mensaje de error (null si el check fue exitoso, máx 500 caracteres)"
    )


# === SCHEMAS DE RESPUESTA REST — TELEMETRÍA ===

class TelemetryLogResponse(BaseModel):
    """
    Schema de respuesta para un registro individual de telemetría.

    Usado en el endpoint GET /api/v1/workstations/{id}/telemetry.
    """
    id: UUID
    workstation_id: UUID
    queue_status: Optional[str] = Field(None, description="Estado de la cola: ok, missing o error")
    contingency_active: Optional[bool] = Field(None, description="Si la contingencia estaba activa")
    jobs_identified: Optional[int] = Field(None, description="Cantidad de trabajos identificados")
    avg_release_time_ms: Optional[int] = Field(None, description="Tiempo promedio de liberación en ms")
    disconnection_count: Optional[int] = Field(None, description="Cantidad de desconexiones registradas")
    recorded_at: datetime = Field(..., description="Timestamp UTC del registro")

    model_config = {"from_attributes": True}


# === SCHEMAS DE RESPUESTA REST — CONECTIVIDAD ===

class ConnectivityResultResponse(BaseModel):
    """
    Schema de respuesta para un resultado individual de conectividad.

    Usado en el endpoint GET /api/v1/workstations/{id}/connectivity.
    """
    id: UUID
    check_id: str = Field(..., description="Identificador del check de conectividad")
    check_type: str = Field(..., description="Tipo de check: http, tcp, ping o dns")
    success: bool = Field(..., description="Si el check fue exitoso")
    latency_ms: Optional[int] = Field(None, description="Latencia en milisegundos")
    error: Optional[str] = Field(None, description="Mensaje de error si el check falló")
    recorded_at: datetime = Field(..., description="Timestamp UTC del registro")

    model_config = {"from_attributes": True}


# === SCHEMAS DE RESPUESTA REST — ESTADÍSTICAS ===

class QueueStatusSummary(BaseModel):
    """Resumen de estados de cola por organización."""
    ok: int = Field(0, description="Cantidad de workstations con estado 'ok'")
    missing: int = Field(0, description="Cantidad de workstations con estado 'missing'")
    error: int = Field(0, description="Cantidad de workstations con estado 'error'")


class TelemetryStatsResponse(BaseModel):
    """
    Schema de respuesta para estadísticas agregadas de telemetría por organización.

    Usado en el endpoint GET /api/v1/organizations/{id}/telemetry/stats.
    Todas las estadísticas se computan sobre registros de las últimas 24 horas UTC.
    """
    total_workstations: int = Field(
        ...,
        description="Total de workstations registradas para la organización"
    )
    workstations_reporting: int = Field(
        ...,
        description="Workstations con al menos un registro de telemetría en las últimas 24h"
    )
    avg_jobs_identified: float = Field(
        ...,
        description="Promedio aritmético de jobs_identified en las últimas 24h (2 decimales)"
    )
    contingency_active_count: int = Field(
        ...,
        description="Workstations cuyo registro más reciente en 24h tiene contingency_active=true"
    )
    queue_status_summary: QueueStatusSummary = Field(
        ...,
        description="Conteo por estado de cola del registro más reciente por workstation en 24h"
    )
    last_updated: Optional[datetime] = Field(
        None,
        description="Timestamp UTC del registro de telemetría más reciente (null si no hay datos en 24h)"
    )
