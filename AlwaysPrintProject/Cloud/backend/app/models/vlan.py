"""
Modelo SQLAlchemy para VLANs (segmentos de red).

Este módulo define el modelo VLAN que representa segmentos de red
dentro de una cuenta, identificados por rangos CIDR.
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class VLAN(Base):
    """
    Modelo de VLAN (segmento de red).
    
    Representa un segmento de red dentro de una cuenta, identificado
    por uno o más rangos CIDR. Permite aplicar configuración específica
    a grupos de estaciones.
    """
    __tablename__ = "vlans"
    
    # === CAMPOS PRINCIPALES ===
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(String(1000), nullable=True)
    
    # Rangos CIDR como array JSON: ["192.168.1.0/24", "10.0.0.0/16"]
    cidr_ranges = Column(JSON, nullable=False, default=list)
    
    # === TIMESTAMPS ===
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # === RELACIONES ===
    account = relationship("Account", back_populates="vlans")
    workstations = relationship("Workstation", back_populates="vlan")
    vlan_config = relationship("VLANConfig", back_populates="vlan", uselist=False, cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<VLAN(id={self.id}, name={self.name}, account_id={self.account_id})>"
