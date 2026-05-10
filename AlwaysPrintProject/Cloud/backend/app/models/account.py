"""
Modelos SQLAlchemy para cuentas y direcciones IP públicas.

Este módulo define:
- Account: organización cliente (ej: BBVA)
- PublicIP: direcciones IP públicas autorizadas para una cuenta
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, TypeDecorator
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


# === TIPO UUID COMPATIBLE CON SQLITE Y POSTGRESQL ===
class GUID(TypeDecorator):
    """
    Tipo UUID que funciona tanto en SQLite como en PostgreSQL.
    
    En PostgreSQL usa el tipo UUID nativo.
    En SQLite usa String(36) y convierte automáticamente.
    """
    impl = String
    cache_ok = True
    
    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        else:
            return dialect.type_descriptor(String(36))
    
    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        elif dialect.name == 'postgresql':
            return value
        else:
            if isinstance(value, uuid.UUID):
                return str(value)
            else:
                return str(uuid.UUID(value)) if value else None
    
    def process_result_value(self, value, dialect):
        if value is None:
            return value
        else:
            if isinstance(value, uuid.UUID):
                return value
            else:
                return uuid.UUID(value)


class Account(Base):
    """
    Modelo de cuenta (organización).
    
    Representa una organización que agrupa múltiples estaciones.
    Cada organización tiene IPs públicas autorizadas y configuración global.
    Ejemplos: BBVA, Ripley, Interbank, etc.
    """
    __tablename__ = "accounts"
    
    # === CAMPOS PRINCIPALES ===
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    name = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(String(1000), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    
    # Zona horaria de la organización (por defecto UTC)
    # Ejemplos: "UTC", "America/Lima", "America/New_York", "Europe/Madrid"
    timezone = Column(String(50), nullable=False, default="UTC")
    
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
    
    Flujo de autorización:
    1. Cliente intenta conectarse desde IP no registrada
    2. Se crea registro con is_authorized=False, account_id=NULL
    3. Admin revisa IPs pendientes y asigna a una cuenta
    4. Se actualiza is_authorized=True y account_id
    """
    __tablename__ = "public_ips"
    
    # === CAMPOS PRINCIPALES ===
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    account_id = Column(GUID, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True)  # NULL hasta autorizar
    ip_address = Column(String(45), unique=True, nullable=False, index=True)  # Soporta IPv4 e IPv6
    description = Column(String(500), nullable=True)
    
    # Estado de autorización
    is_authorized = Column(Boolean, nullable=False, default=False, index=True)
    
    # === TIMESTAMPS ===
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    first_seen = Column(DateTime, nullable=False, default=datetime.utcnow)  # Primera vez que intentó conectarse
    authorized_at = Column(DateTime, nullable=True)  # Cuándo fue autorizada
    
    # === RELACIONES ===
    account = relationship("Account", back_populates="public_ips")
    
    def __repr__(self):
        return f"<PublicIP(id={self.id}, ip_address={self.ip_address}, is_authorized={self.is_authorized})>"
