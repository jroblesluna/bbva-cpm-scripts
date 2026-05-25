"""
Modelo SQLAlchemy para VLANs (segmentos de red).

Este módulo define el modelo VLAN que representa segmentos de red
dentro de una cuenta, identificados por rangos CIDR.
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.organization import GUID  # Importar tipo GUID para consistencia


class VLAN(Base):
    """
    Modelo de VLAN (segmento de red).
    
    Representa un segmento de red dentro de una cuenta, identificado
    por uno o más rangos CIDR. Permite aplicar configuración específica
    a grupos de estaciones.
    """
    __tablename__ = "vlans"
    
    # === CAMPOS PRINCIPALES ===
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    organization_id = Column(GUID, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(String(1000), nullable=True)
    
    # Rangos CIDR como array JSON: ["192.168.1.0/24", "10.0.0.0/16"]
    cidr_ranges = Column(JSON, nullable=False, default=list)

    # Flag de contingencia forzada a nivel de VLAN
    # Cuando está activo, TODAS las workstations de esta VLAN entran en modo contingencia
    forced_contingency = Column(Boolean, nullable=False, default=False, server_default='false')

    # Impresora predeterminada de la VLAN
    # Las workstations de esta VLAN que no tengan impresora favorita individual usarán esta.
    default_device_id = Column(GUID, ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)

    # Flag que indica si la action config de la VLAN es obligatoria para todas sus workstations
    # Si es True, las workstations de esta VLAN NO pueden tener su propia action config
    action_config_mandatory = Column(Boolean, nullable=False, default=False, server_default='false')
    
    # === TIMESTAMPS ===
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # === RELACIONES ===
    organization = relationship("Organization", back_populates="vlans")
    workstations = relationship("Workstation", back_populates="vlan")
    devices = relationship("Device", back_populates="vlan", foreign_keys="Device.vlan_id")
    default_device = relationship("Device", foreign_keys="VLAN.default_device_id")
    vlan_config = relationship("VLANConfig", back_populates="vlan", uselist=False, cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<VLAN(id={self.id}, name={self.name}, organization_id={self.organization_id})>"
