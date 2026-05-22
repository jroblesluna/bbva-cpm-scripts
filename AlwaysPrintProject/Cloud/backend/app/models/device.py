"""
Modelo SQLAlchemy para Dispositivos (impresoras).

Este módulo define el modelo Device que representa una impresora
registrada en el sistema, asociada a una organización y opcionalmente a una VLAN.
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.organization import GUID  # Importar tipo GUID para consistencia


class Device(Base):
    """
    Modelo de dispositivo (impresora).
    
    Representa una impresora registrada en el sistema. Cada dispositivo
    pertenece a una organización y puede estar asociado a una VLAN.
    Múltiples dispositivos pueden pertenecer a la misma VLAN.
    """
    __tablename__ = "devices"
    
    # === CAMPOS PRINCIPALES ===
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    organization_id = Column(GUID, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    vlan_id = Column(GUID, ForeignKey("vlans.id", ondelete="SET NULL"), nullable=True)
    
    # Información del dispositivo
    name = Column(String(255), nullable=False)
    ip_address = Column(String(45), nullable=False)
    description = Column(String(1000), nullable=True)
    
    # Información técnica
    model = Column(String(255), nullable=True)  # Modelo de la impresora (ej: "Lexmark MS826de")
    location = Column(String(500), nullable=True)  # Ubicación física (ej: "Piso 3, Ala Norte")
    port = Column(Integer, nullable=False, default=9100)  # Puerto de impresión (por defecto RAW 9100)
    
    # Estado
    is_active = Column(Boolean, nullable=False, default=True)
    
    # === TIMESTAMPS ===
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # === RELACIONES ===
    organization = relationship("Organization", back_populates="devices")
    vlan = relationship("VLAN", back_populates="devices", foreign_keys="Device.vlan_id")
    
    def __repr__(self):
        return f"<Device(id={self.id}, name={self.name}, ip={self.ip_address})>"
