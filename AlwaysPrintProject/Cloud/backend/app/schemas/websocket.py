"""
Schemas Pydantic para mensajes WebSocket.

Este módulo define los schemas de validación para mensajes
intercambiados a través de WebSocket entre Tray Clients, Backend y Frontend.
"""

from datetime import datetime
from typing import Optional, List, Literal, Any
from uuid import UUID
import ipaddress
from pydantic import BaseModel, Field, field_validator


# === SCHEMAS DE MENSAJES WORKSTATION → BACKEND ===

class RegisterMessage(BaseModel):
    """Mensaje de registro inicial de Tray Client."""
    type: Literal["register"] = "register"
    ip_private: str = Field(..., description="IP privada de la workstation")
    hostname: Optional[str] = None
    os_serial: Optional[str] = None
    current_user: Optional[str] = None
    contingency_active: bool = False
    cidr: str = Field(..., description="CIDR de la subred de la workstation (ej: 192.168.1.0/24)")
    tray_version: Optional[str] = Field(None, max_length=50, description="Versión del AlwaysPrintTray")

    @field_validator('cidr')
    @classmethod
    def validar_cidr(cls, v: str) -> str:
        """Valida y normaliza el CIDR a su forma canónica.

        - Verifica que sea una notación IPv4 CIDR válida
        - Verifica que el prefix length esté en rango 8-30
        - Normaliza a forma canónica (ej: 192.168.1.50/24 → 192.168.1.0/24)
        """
        try:
            red = ipaddress.ip_network(v, strict=False)
        except ValueError:
            raise ValueError(f"CIDR inválido: '{v}'. Debe ser una notación IPv4 CIDR válida (ej: 192.168.1.0/24)")

        # Verificar que sea IPv4
        if red.version != 4:
            raise ValueError(f"CIDR inválido: '{v}'. Solo se admiten redes IPv4")

        # Verificar que el prefix length esté en rango 8-30
        if red.prefixlen < 8 or red.prefixlen > 30:
            raise ValueError(
                f"CIDR inválido: '{v}'. El prefix length debe estar entre 8 y 30 (recibido: {red.prefixlen})"
            )

        # Retornar forma canónica normalizada
        return str(red)


class PongMessage(BaseModel):
    """Respuesta a ping del servidor."""
    type: Literal["pong"] = "pong"


class StatusUpdateMessage(BaseModel):
    """Actualización de estado de la workstation."""
    type: Literal["status_update"] = "status_update"
    contingency_active: bool
    current_user: Optional[str] = None


class ConfigChangeReportMessage(BaseModel):
    """Reporte de cambio de configuración aplicado."""
    type: Literal["config_change_report"] = "config_change_report"
    success: bool
    error_message: Optional[str] = None


class CommandResultMessage(BaseModel):
    """Resultado de ejecución de comando."""
    type: Literal["command_result"] = "command_result"
    command_id: str = Field(..., description="ID del comando ejecutado")
    success: bool
    result: Optional[str] = None
    error_message: Optional[str] = None


# === SCHEMAS DE MENSAJES BACKEND → WORKSTATION ===

class PingMessage(BaseModel):
    """Ping del servidor para verificar conexión."""
    type: Literal["ping"] = "ping"


class ConfigChangeMessage(BaseModel):
    """Notificación de cambio de configuración."""
    type: Literal["config_change"] = "config_change"
    config: dict = Field(..., description="Nueva configuración efectiva")


class CommandMessage(BaseModel):
    """Comando a ejecutar en la workstation."""
    type: Literal["command"] = "command"
    command_id: str = Field(..., description="ID único del comando")
    command_type: str = Field(..., description="Tipo de comando (restart_service, clear_cache, etc.)")
    parameters: Optional[dict] = None


class NotificationMessage(BaseModel):
    """Notificación para mostrar al usuario."""
    type: Literal["notification"] = "notification"
    title: str = Field(..., max_length=255)
    message: str = Field(..., max_length=5000)
    severity: Literal["info", "warning", "error"] = "info"


# === SCHEMAS DE MENSAJES BACKEND → OPERATOR (FRONTEND) ===

class WorkstationConnectedNotification(BaseModel):
    """Notificación de workstation conectada."""
    type: Literal["workstation_connected"] = "workstation_connected"
    workstation_id: UUID
    ip_private: str
    hostname: Optional[str] = None
    timestamp: datetime


class WorkstationDisconnectedNotification(BaseModel):
    """Notificación de workstation desconectada."""
    type: Literal["workstation_disconnected"] = "workstation_disconnected"
    workstation_id: UUID
    ip_private: str
    timestamp: datetime


class ContingencyToggleNotification(BaseModel):
    """Notificación de cambio de estado de contingencia."""
    type: Literal["contingency_toggle"] = "contingency_toggle"
    workstation_id: UUID
    ip_private: str
    contingency_active: bool
    timestamp: datetime


class MessageDeliveredNotification(BaseModel):
    """Notificación de mensaje entregado."""
    type: Literal["message_delivered"] = "message_delivered"
    message_id: UUID
    workstation_id: UUID
    timestamp: datetime


class CommandResultNotification(BaseModel):
    """Notificación de resultado de comando."""
    type: Literal["command_result"] = "command_result"
    command_id: str
    workstation_id: UUID
    success: bool
    result: Optional[str] = None
    error_message: Optional[str] = None
    timestamp: datetime


class ConnectionStatsMessage(BaseModel):
    """Estadísticas de conexiones (enviado al conectar operador)."""
    type: Literal["connection_stats"] = "connection_stats"
    total_workstations: int
    online_workstations: int
    contingency_active_count: int
    timestamp: datetime


# === SCHEMAS DE TELEMETRÍA Y CONECTIVIDAD (WORKSTATION → BACKEND) ===

class DisconnectionEventSchema(BaseModel):
    """Evento de desconexión WebSocket registrado por el Tray."""
    started_at: str = Field(..., description="Timestamp UTC de inicio de desconexión (ISO 8601)")
    reconnected_at: Optional[str] = Field(None, description="Timestamp UTC de reconexión (ISO 8601)")
    duration_seconds: Optional[int] = Field(None, description="Duración de la desconexión en segundos")


class TelemetryMessage(BaseModel):
    """Mensaje de telemetría periódica enviado por el Tray."""
    type: Literal["telemetry"] = "telemetry"
    queue_status: str = Field(..., description="Estado de la cola de impresión (ok, missing, error)")
    contingency_active: bool = Field(..., description="Si la contingencia está activa")
    jobs_identified: int = Field(..., description="Cantidad de trabajos identificados en el intervalo")
    avg_release_time_ms: Optional[int] = Field(None, description="Tiempo promedio de liberación en ms (null si no hay trabajos)")
    disconnection_log: List[DisconnectionEventSchema] = Field(
        default_factory=list,
        description="Lista de eventos de desconexión acumulados en el intervalo"
    )


class ConnectivityResultMessage(BaseModel):
    """Resultado individual de un chequeo de conectividad."""
    type: Literal["connectivity_result"] = "connectivity_result"
    check_id: str = Field(..., description="Identificador del chequeo de conectividad")
    success: bool = Field(..., description="Si el chequeo fue exitoso")
    latency_ms: Optional[int] = Field(None, description="Latencia en milisegundos (null si falló)")
    error: Optional[str] = Field(None, description="Mensaje de error (null si fue exitoso)")


# === SCHEMAS GENÉRICOS ===

class WebSocketMessage(BaseModel):
    """Schema genérico para cualquier mensaje WebSocket."""
    type: str
    data: Optional[Any] = None


class WebSocketError(BaseModel):
    """Schema para errores en WebSocket."""
    type: Literal["error"] = "error"
    error_code: str
    error_message: str
    timestamp: datetime
