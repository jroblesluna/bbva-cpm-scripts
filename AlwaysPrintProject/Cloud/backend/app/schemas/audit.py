"""
Schemas Pydantic para auditoría.

Este módulo define los schemas de validación para registros de auditoría.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field

from app.models.audit import ActionType


# === SCHEMAS DE AUDIT LOG ===

class AuditLogResponse(BaseModel):
    """Schema de respuesta para registro de auditoría."""
    id: UUID
    user_id: Optional[UUID] = None
    workstation_id: Optional[UUID] = None
    account_id: Optional[UUID] = None
    action_type: ActionType
    entity_type: str
    entity_id: UUID
    old_values: Optional[dict] = None
    new_values: Optional[dict] = None
    ip_address: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class AuditLogDetailResponse(AuditLogResponse):
    """Schema de respuesta detallada para registro de auditoría (incluye información del usuario)."""
    user_name: Optional[str] = Field(None, description="Nombre del usuario que realizó la acción")
    user_email: Optional[str] = Field(None, description="Email del usuario que realizó la acción")
    workstation_ip: Optional[str] = Field(None, description="IP de la workstation afectada")
    
    class Config:
        from_attributes = True


class AuditLogSearch(BaseModel):
    """Schema para búsqueda avanzada de registros de auditoría."""
    user_id: Optional[UUID] = Field(None, description="Filtrar por usuario")
    workstation_id: Optional[UUID] = Field(None, description="Filtrar por workstation")
    account_id: Optional[UUID] = Field(None, description="Filtrar por cuenta")
    action_type: Optional[ActionType] = Field(None, description="Filtrar por tipo de acción")
    entity_type: Optional[str] = Field(None, description="Filtrar por tipo de entidad")
    entity_id: Optional[UUID] = Field(None, description="Filtrar por ID de entidad")
    start_date: Optional[datetime] = Field(None, description="Fecha de inicio")
    end_date: Optional[datetime] = Field(None, description="Fecha de fin")
    page: int = Field(1, ge=1, description="Número de página")
    page_size: int = Field(50, ge=1, le=100, description="Tamaño de página (1-100)")


class AuditLogListResponse(BaseModel):
    """Schema de respuesta para lista paginada de registros de auditoría."""
    total: int
    page: int
    page_size: int
    logs: list[AuditLogResponse]


class AuditLogStatsResponse(BaseModel):
    """Schema de respuesta para estadísticas de auditoría."""
    total_actions: int
    actions_by_type: dict[str, int] = Field(..., description="Conteo de acciones por tipo")
    most_active_users: list[dict] = Field(..., description="Usuarios más activos (top 10)")
    recent_activity_count: int = Field(..., description="Acciones en las últimas 24 horas")
