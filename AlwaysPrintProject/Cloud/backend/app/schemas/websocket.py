"""
Schemas Pydantic para mensajes WebSocket.

Este módulo define los schemas de validación para mensajes
intercambiados a través de WebSocket entre Tray Clients, Backend y Frontend.
"""

from datetime import datetime
from typing import Optional, Literal, Any
from uuid import UUID
from pydantic import BaseModel, Field


# === SCHEMAS DE MENSAJES WORKSTATION → BACKEND ===

class RegisterMessage(BaseModel):
    """Mensaje de registro inicial de Tray Client."""
    type: Literal["register"] = "register"
    ip_private: str = Field(..., description="IP privada de la workstation")
    hostname: Optional[str] = None
    os_serial: Optional[str] = None
    current_user: Optional[str] = None
    contingency_active: bool = False


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
