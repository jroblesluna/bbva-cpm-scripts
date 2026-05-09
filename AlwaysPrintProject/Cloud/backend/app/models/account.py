"""
Modelos SQLAlchemy para cuentas y direcciones IP públicas.

Este módulo define:
- Account: organización cliente (ej: BBVA)
- PublicIP: direcciones IP públicas autorizadas para una cuenta
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class Account(Base):
    """
    Modelo de cuenta (organización cliente).
    
    Representa una organización que agrupa múltiples estaciones.
    Cada cuenta tiene IPs públicas autorizadas y configuración global.
    """
    __tablename__ = "accounts"
    
    # === CAMPOS PRINCIPALES ===
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(String(1000), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    
    # === TIMESTAMPS ===
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # === RELACIONES ===
    users = relationship("User", back_populates="account", cascade="all, delete-orphan")
    public_ips = relationship("PublicIP", back_populates="account", cascade="all, delete-orphan")
    workstations = relationship("Workstation", back_populates="account", cascade="all, delete-orphan")
    vlans = relationship("VLAN", back_populates="account", cascade="all, delete-orphan")
    global_config = relationship("GlobalConfig", back_populates="account", uselist=False, cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="account", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="account", foreign_keys="AuditLog.account_id")
    
    def __repr__(self):
        return f"<Account(id={self.id}, name={self.name}, is_active={self.is_active})>"


class PublicIP(Base):
    """
    Modelo de dirección IP pública autorizada.
    
    Representa una IP pública desde la cual las estaciones pueden conectarse.
    Una IP solo puede estar asociada a una cuenta simultáneamente.
    """
    __tablename__ = "public_ips"
    
    # === CAMPOS PRINCIPALES ===
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    ip_address = Column(String(45), unique=True, nullable=False, index=True)  # Soporta IPv4 e IPv6
    description = Column(String(500), nullable=True)
    
    # === TIMESTAMPS ===
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # === RELACIONES ===
    account = relationship("Account", back_populates="public_ips")
    
    def __repr__(self):
        return f"<PublicIP(id={self.id}, ip_address={self.ip_address}, account_id={self.account_id})>"
