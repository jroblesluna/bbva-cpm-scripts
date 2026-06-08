"""
Modelos SQLAlchemy para organizaciones y direcciones IP públicas.

Este módulo define:
- Organization: organización cliente multi-tenant (ej: BBVA)
- PublicIP: direcciones IP públicas autorizadas para una organización
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer, TypeDecorator
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


class Organization(Base):
    """
    Modelo de organización (entidad multi-tenant).
    
    Representa una organización que agrupa múltiples estaciones.
    Cada organización tiene IPs públicas autorizadas y configuración global.
    Ejemplos: BBVA, Ripley, Interbank, etc.
    """
    __tablename__ = "organizations"
    
    # === CAMPOS PRINCIPALES ===
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    name = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(String(1000), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    
    # Zona horaria de la organización (por defecto UTC)
    # Ejemplos: "UTC", "America/Lima", "America/New_York", "Europe/Madrid"
    timezone = Column(String(50), nullable=False, default="UTC")
    language = Column(String(2), nullable=False, server_default='en')

    # Flag de auto-actualización a nivel de organización
    # Controla si las workstations de esta organización pueden actualizarse automáticamente
    auto_update_enabled = Column(Boolean, nullable=False, default=False, server_default='false')

    # Versión objetivo para actualizaciones (nullable = usar latest)
    # Cuando se establece, las workstations se actualizan a esta versión específica
    target_version = Column(String(50), nullable=True)

    # Flag de re-registro automático de workstations eliminadas
    # Si está habilitado, cuando una workstation envía telemetría pero ya no existe en BD,
    # se le solicita re-registrarse automáticamente (obtiene nuevo workstation_id)
    auto_reregister_enabled = Column(Boolean, nullable=False, default=False, server_default='false')

    # Flag de contingencia forzada a nivel de organización
    # Cuando está activo, TODAS las workstations de esta organización entran en modo contingencia
    forced_contingency = Column(Boolean, nullable=False, default=False, server_default='false')

    # Flag que indica si la action config de la organización es obligatoria para todas las VLANs/workstations
    # Si es True, las VLANs y workstations NO pueden tener su propia action config
    action_config_mandatory = Column(Boolean, nullable=False, default=False, server_default='false')

    # Minutos de inactividad antes de enviar Death Ping (default: 10)
    offline_timeout_minutes = Column(Integer, nullable=False, default=10, server_default='10')

    # Modelo LLM asignado a esta organización para análisis de logs
    # Si es NULL, se usa el modelo por defecto global (settings.LOG_ANALYZER_LLM_MODEL_ID)
    llm_model_id = Column(String(100), nullable=True)

    # API Key de OpenAI para esta organización (opcional)
    # Si está configurada, se usa OpenAI en vez de AWS Bedrock para el análisis de logs
    openai_api_key = Column(String(200), nullable=True)

    # === TIMESTAMPS ===
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # === RELACIONES ===
    users = relationship("User", back_populates="organization", cascade="all, delete-orphan")
    public_ips = relationship("PublicIP", back_populates="organization", cascade="all, delete-orphan")
    workstations = relationship("Workstation", back_populates="organization", cascade="all, delete-orphan")
    vlans = relationship("VLAN", back_populates="organization", cascade="all, delete-orphan")
    global_config = relationship("GlobalConfig", back_populates="organization", uselist=False, cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="organization", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="organization", foreign_keys="AuditLog.organization_id")
    telemetry_logs = relationship("TelemetryLog", back_populates="organization", cascade="all, delete-orphan")
    connectivity_results = relationship("ConnectivityResult", back_populates="organization", cascade="all, delete-orphan")
    action_configs = relationship("ActionConfig", back_populates="organization", cascade="all, delete-orphan")
    devices = relationship("Device", back_populates="organization", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Organization(id={self.id}, name={self.name}, is_active={self.is_active})>"



class PublicIP(Base):
    """
    Modelo de dirección IP pública autorizada.
    
    Representa una IP pública desde la cual las estaciones pueden conectarse.
    Una IP solo puede estar asociada a una organización simultáneamente.
    
    Flujo de autorización:
    1. Cliente intenta conectarse desde IP no registrada
    2. Se crea registro con is_authorized=False, organization_id=NULL
    3. Admin revisa IPs pendientes y asigna a una organización
    4. Se actualiza is_authorized=True y organization_id
    """
    __tablename__ = "public_ips"
    
    # === CAMPOS PRINCIPALES ===
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    organization_id = Column(GUID, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True)  # NULL hasta autorizar
    ip_address = Column(String(45), unique=True, nullable=False, index=True)  # Soporta IPv4 e IPv6
    description = Column(String(500), nullable=True)
    
    # Estado de autorización
    is_authorized = Column(Boolean, nullable=False, default=False, index=True)

    # Metadata de la última estación que intentó registrarse desde esta IP
    last_hostname = Column(String(255), nullable=True)
    last_user = Column(String(255), nullable=True)

    # === TIMESTAMPS ===
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    first_seen = Column(DateTime, nullable=False, default=datetime.utcnow)  # Primera vez que intentó conectarse
    authorized_at = Column(DateTime, nullable=True)  # Cuándo fue autorizada
    
    # === RELACIONES ===
    organization = relationship("Organization", back_populates="public_ips")
    
    def __repr__(self):
        return f"<PublicIP(id={self.id}, ip_address={self.ip_address}, is_authorized={self.is_authorized})>"
