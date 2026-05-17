"""
Schemas Pydantic para mensajes.

Este módulo define los schemas de validación para mensajes
enviados a workstations, VLANs o cuentas.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field, field_validator

from app.models.message import TargetType


# === SCHEMAS DE MESSAGE ===

class MessageCreate(BaseModel):
    """Schema para crear un mensaje."""
    target_type: TargetType = Field(..., description="Tipo de destinatario (workstation, vlan, account)")
    target_id: Optional[UUID] = Field(None, description="ID del destinatario (NULL para broadcast a cuenta)")
    content: str = Field(..., min_length=1, max_length=5000, description="Contenido del mensaje")
    
    @field_validator("target_id")
    @classmethod
    def validate_target_id(cls, v: Optional[UUID], info) -> Optional[UUID]:
        """Valida que target_id sea consistente con target_type."""
        target_type = info.data.get("target_type")
        
        # Si target_type es account, target_id debe ser None
        if target_type == TargetType.ACCOUNT and v is not None:
            raise ValueError("target_id debe ser None cuando target_type es 'account'")
        
        # Si target_type es workstation o vlan, target_id es requerido
        if target_type in (TargetType.WORKSTATION, TargetType.VLAN) and v is None:
            raise ValueError(f"target_id es requerido cuando target_type es '{target_type.value}'")
        
        return v


class MessageResponse(BaseModel):
    """Schema de respuesta para mensaje."""
    id: UUID
    organization_id: UUID
    sender_id: Optional[UUID] = None
    target_type: TargetType
    target_id: Optional[UUID] = None
    content: str
    is_delivered: bool
    sent_at: datetime
    delivered_at: Optional[datetime] = None
    
    model_config = {"from_attributes": True}


class MessageDetailResponse(MessageResponse):
    """Schema de respuesta detallada para mensaje (incluye información del remitente)."""
    sender_name: Optional[str] = Field(None, description="Nombre del usuario que envió el mensaje")
    sender_email: Optional[str] = Field(None, description="Email del usuario que envió el mensaje")
    
    model_config = {"from_attributes": True}


class MessageListResponse(BaseModel):
    """Schema de respuesta para lista paginada de mensajes."""
    total: int
    page: int
    page_size: int
    messages: list[MessageResponse]


class MessageStatsResponse(BaseModel):
    """Schema de respuesta para estadísticas de mensajes."""
    total_sent: int
    total_delivered: int
    total_pending: int
    delivery_rate: float = Field(..., ge=0.0, le=100.0, description="Porcentaje de entrega (0-100)")
