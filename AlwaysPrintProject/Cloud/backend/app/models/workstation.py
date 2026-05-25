"""
Modelos SQLAlchemy para estaciones y licencias.

Este módulo define:
- Workstation: estación Windows que ejecuta AlwaysPrint
- License: licencia activa para una estación
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship, foreign

from app.core.database import Base
from app.models.organization import GUID  # Importar tipo GUID para consistencia


class Workstation(Base):
    """
    Modelo de estación Windows.
    
    Representa una workstation que ejecuta AlwaysPrint Service y Tray Client.
    La IP privada es el identificador único de la estación.
    """
    __tablename__ = "workstations"
    
    # === CAMPOS PRINCIPALES ===
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    organization_id = Column(GUID, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    vlan_id = Column(GUID, ForeignKey("vlans.id", ondelete="SET NULL"), nullable=True)
    
    # IP privada es el identificador único de la estación
    ip_private = Column(String(45), unique=True, nullable=False, index=True)
    
    # Información de la estación
    hostname = Column(String(255), nullable=True)
    os_serial = Column(String(255), nullable=True)
    current_user = Column(String(255), nullable=True)
    
    # Información de red y versión del Tray
    cidr = Column(String(45), nullable=True)  # CIDR reportado por la workstation (ej: "192.168.1.0/24")
    tray_version = Column(String(50), nullable=True)  # Versión del Tray instalado (ej: "2.1.0.0")
    
    # Estado de la estación
    is_online = Column(Boolean, nullable=False, default=False)
    contingency_active = Column(Boolean, nullable=False, default=False)
    contingency_ip = Column(String(45), nullable=True)  # IP de contingencia actual
    contingency_started_at = Column(DateTime, nullable=True)  # Cuándo se activó la contingencia

    # Flag de contingencia forzada a nivel individual de workstation
    # Cuando está activo, esta workstation entra en modo contingencia independientemente del estado real
    forced_contingency = Column(Boolean, nullable=False, default=False, server_default='false')

    # Flag de mandatory para action config: si True, esta workstation usa su propia config
    # (solo aplica si ningún padre —org o vlan— tiene mandatory habilitado)
    action_config_mandatory = Column(Boolean, nullable=False, default=False, server_default='false')
    
    # Impresora predeterminada asignada
    default_printer_id = Column(GUID, ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)
    
    # === TIMESTAMPS ===
    last_connection = Column(DateTime, nullable=True)
    first_seen = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # === RELACIONES ===
    organization = relationship("Organization", back_populates="workstations")
    vlan = relationship("VLAN", back_populates="workstations")
    default_printer = relationship("Device", foreign_keys="Workstation.default_printer_id")
    licenses = relationship("License", back_populates="workstation", cascade="all, delete-orphan")
    workstation_config = relationship("WorkstationConfig", back_populates="workstation", uselist=False, cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="workstation", foreign_keys="AuditLog.workstation_id")
    telemetry_logs = relationship("TelemetryLog", back_populates="workstation", cascade="all, delete-orphan")
    connectivity_results = relationship("ConnectivityResult", back_populates="workstation", cascade="all, delete-orphan")
    message_deliveries = relationship("MessageDelivery", back_populates="workstation", cascade="all, delete-orphan")
    
    # Relación con mensajes (solo cuando target_type=workstation)
    messages = relationship(
        "Message",
        back_populates="target_workstation",
        foreign_keys="Message.target_id",
        primaryjoin="and_(Workstation.id==foreign(Message.target_id), Message.target_type=='workstation')",
        viewonly=True
    )
    
    def __repr__(self):
        return f"<Workstation(id={self.id}, ip_private={self.ip_private}, is_online={self.is_online})>"


class License(Base):
    """
    Modelo de licencia de estación.
    
    Representa una licencia activa o histórica para una estación.
    El número de serie se calcula como los últimos 8 caracteres del MD5 de la IP privada.
    """
    __tablename__ = "licenses"
    
    # === CAMPOS PRINCIPALES ===
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    workstation_id = Column(GUID, ForeignKey("workstations.id", ondelete="CASCADE"), nullable=False)
    
    # Número de serie: últimos 8 caracteres del MD5 de ip_private
    serial_number = Column(String(8), nullable=False, index=True)
    
    # Estado de la licencia
    is_active = Column(Boolean, nullable=False, default=True)
    
    # === TIMESTAMPS ===
    activated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    deactivated_at = Column(DateTime, nullable=True)
    
    # === RELACIONES ===
    workstation = relationship("Workstation", back_populates="licenses")
    
    def __repr__(self):
        return f"<License(id={self.id}, serial_number={self.serial_number}, is_active={self.is_active})>"
