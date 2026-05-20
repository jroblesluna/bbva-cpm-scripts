"""
Modelo SQLAlchemy para mensajes enviados a estaciones.

Este módulo define el modelo Message que representa mensajes
enviados por operadores a estaciones individuales, VLANs o cuentas completas.
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base
from app.models.organization import GUID  # Importar tipo GUID para consistencia


class TargetType(str, enum.Enum):
    """Tipos de destinatarios de mensajes."""
    WORKSTATION = "workstation"
    VLAN = "vlan"
    ACCOUNT = "account"


class DeliveryMode(str, enum.Enum):
    """Modos de entrega para mensajes broadcast (VLAN/account)."""
    ALL = "all"                      # Todas las workstations (offline reciben al reconectar)
    ONLY_CONNECTED = "only_connected"  # Solo las conectadas en el momento del envío


class Message(Base):
    """
    Modelo de mensaje enviado a estaciones.
    
    Representa mensajes enviados por operadores a estaciones.
    Los mensajes pueden dirigirse a:
    - Una estación específica (target_type=workstation, target_id=workstation_id)
    - Todas las estaciones de una VLAN (target_type=vlan, target_id=vlan_id)
    - Todas las estaciones de una organización (target_type=account, target_id=NULL)
    """
    __tablename__ = "messages"
    
    # === CAMPOS PRINCIPALES ===
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    organization_id = Column(GUID, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    sender_id = Column(GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # === DESTINATARIO ===
    target_type = Column(SQLEnum(TargetType, name='targettype', create_type=False), nullable=False, index=True)
    # target_id puede ser workstation_id, vlan_id, o NULL (para broadcast a cuenta)
    target_id = Column(GUID, nullable=True, index=True)
    
    # === MODO DE ENTREGA ===
    # all = todas las workstations (offline reciben al reconectar)
    # only_connected = solo las conectadas en el momento del envío
    delivery_mode = Column(
        SQLEnum(DeliveryMode, name='deliverymode', create_type=False),
        nullable=False,
        default=DeliveryMode.ALL,
        server_default="all"
    )
    
    # === CONTENIDO ===
    content = Column(String(5000), nullable=False)
    
    # === ESTADO DE ENTREGA (resumen) ===
    is_delivered = Column(Boolean, nullable=False, default=False)
    
    # === TIMESTAMPS ===
    sent_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    delivered_at = Column(DateTime, nullable=True)
    
    # === RELACIONES ===
    organization = relationship("Organization", back_populates="messages")
    sender = relationship("User", back_populates="sent_messages", foreign_keys=[sender_id])
    deliveries = relationship("MessageDelivery", back_populates="message", cascade="all, delete-orphan")
    
    # Relación condicional con Workstation (solo cuando target_type=workstation)
    target_workstation = relationship(
        "Workstation",
        back_populates="messages",
        foreign_keys=[target_id],
        primaryjoin="and_(Message.target_id==Workstation.id, Message.target_type=='workstation')",
        viewonly=True
    )
    
    def __repr__(self):
        return f"<Message(id={self.id}, target_type={self.target_type}, is_delivered={self.is_delivered})>"
