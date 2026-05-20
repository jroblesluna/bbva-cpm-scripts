"""
Modelo SQLAlchemy para entregas individuales de mensajes a workstations.

Cada registro representa la entrega de un mensaje a una workstation específica.
Permite tracking granular de entrega para mensajes broadcast (VLAN/account).
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base
from app.models.organization import GUID


class DeliveryStatus(str, enum.Enum):
    """Estados posibles de entrega de un mensaje."""
    PENDING = "pending"          # Esperando entrega (workstation offline)
    SENT = "sent"                # Enviado por WebSocket (sin confirmación del Tray)
    SKIPPED = "skipped"          # No se envió (delivery_mode=only_connected y estaba offline)


class MessageDelivery(Base):
    """
    Modelo de entrega individual de un mensaje a una workstation.

    Cada mensaje (especialmente los de tipo VLAN/ACCOUNT) genera N registros
    de delivery, uno por cada workstation destinataria.
    Esto permite:
    - Tracking individual de entrega por workstation
    - Soporte para delivery_mode (all vs only_connected)
    - Entrega diferida a workstations que se reconectan
    """
    __tablename__ = "message_deliveries"

    # === CAMPOS PRINCIPALES ===
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    message_id = Column(GUID, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True)
    workstation_id = Column(GUID, ForeignKey("workstations.id", ondelete="CASCADE"), nullable=False, index=True)

    # === ESTADO DE ENTREGA ===
    status = Column(SQLEnum(DeliveryStatus), nullable=False, default=DeliveryStatus.PENDING, index=True)
    delivered_at = Column(DateTime, nullable=True)

    # === RELACIONES ===
    message = relationship("Message", back_populates="deliveries")
    workstation = relationship("Workstation", back_populates="message_deliveries")

    def __repr__(self):
        return (
            f"<MessageDelivery(id={self.id}, message_id={self.message_id}, "
            f"workstation_id={self.workstation_id}, status={self.status})>"
        )
