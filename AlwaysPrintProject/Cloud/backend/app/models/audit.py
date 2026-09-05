"""
Modelo SQLAlchemy para auditoría de operaciones.

Este módulo define el modelo AuditLog que registra todas las operaciones
críticas del sistema para trazabilidad y cumplimiento.
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, JSON, Enum as SQLEnum, TypeDecorator
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship
import enum

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


class ActionType(str, enum.Enum):
    """Tipos de acciones auditables en el sistema."""
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    CONFIG_CHANGE = "config_change"
    CONTINGENCY_TOGGLE = "contingency_toggle"
    MESSAGE_SENT = "message_sent"
    COMMAND_SENT = "command_sent"
    CERT_GENERATED = "cert_generated"
    CERT_ROTATED = "cert_rotated"
    ONDEMAND_EXECUTED = "ondemand_executed"
    REMOTE_VIEW_START = "REMOTE_VIEW_START"
    REMOTE_VIEW_STOP = "REMOTE_VIEW_STOP"
    REMOTE_VIEW_MODE_CHANGE = "REMOTE_VIEW_MODE_CHANGE"
    LOGIN = "login"
    LOGIN_FAILED = "login_failed"
    REMOTE_COMMAND_EXECUTED = "REMOTE_COMMAND_EXECUTED"
    # === ACCIONES SENSIBLES DE FACTURACIÓN (Usage and Billing, task 33 / Req 11.4) ===
    # NOTA (mismo criterio que 022/033/035): SQLAlchemy envía el NOMBRE del miembro (no el
    # .value) como etiqueta del enum PostgreSQL. Por eso el valor se define igual al nombre
    # (MAYÚSCULA) para ser consistente, y la migración 037_add_billing_audit_actions agrega
    # estas etiquetas en MAYÚSCULA al tipo `actiontype`.
    BILLING_MODE_CHANGE = "BILLING_MODE_CHANGE"      # Cambio de modalidad (monthly↔annual).
    TIMEZONE_LOCK = "TIMEZONE_LOCK"                  # Bloqueo de timezone tras el primer cierre.
    WORKSTATION_ARCHIVE = "WORKSTATION_ARCHIVE"      # Archivado manual de una workstation.
    RATE_PLAN_EDIT = "RATE_PLAN_EDIT"                # Edición de tarifas (default u org).
    BILLING_CLOSURE = "BILLING_CLOSURE"              # Ejecución de un cierre (auto/retroactivo).
    ANNUAL_SETTLEMENT = "ANNUAL_SETTLEMENT"          # Liquidación anual (creación/confirmación).


class AuditLog(Base):
    """
    Modelo de registro de auditoría.
    
    Registra todas las operaciones críticas del sistema con información
    completa para trazabilidad. Los registros son inmutables.
    """
    __tablename__ = "audit_logs"
    
    # === CAMPOS PRINCIPALES ===
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    
    # Usuario que realizó la acción (NULL para acciones del sistema)
    user_id = Column(GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # Estación afectada (si aplica)
    workstation_id = Column(GUID, ForeignKey("workstations.id", ondelete="SET NULL"), nullable=True)
    
    # Organización afectada (si aplica)
    organization_id = Column(GUID, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    
    # === INFORMACIÓN DE LA ACCIÓN ===
    action_type = Column(SQLEnum(ActionType, name="actiontype", create_type=False), nullable=False, index=True)
    entity_type = Column(String(100), nullable=False, index=True)  # Tipo de entidad afectada
    entity_id = Column(GUID, nullable=False, index=True)  # ID de la entidad afectada
    
    # Valores anteriores y nuevos (JSON)
    old_values = Column(JSON, nullable=True)
    new_values = Column(JSON, nullable=True)
    
    # IP desde donde se realizó la acción
    ip_address = Column(String(45), nullable=True)
    
    # === TIMESTAMPS ===
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    # === RELACIONES ===
    user = relationship("User", back_populates="audit_logs", foreign_keys=[user_id])
    workstation = relationship("Workstation", back_populates="audit_logs", foreign_keys=[workstation_id])
    organization = relationship("Organization", back_populates="audit_logs", foreign_keys=[organization_id])
    
    def __repr__(self):
        return f"<AuditLog(id={self.id}, action_type={self.action_type}, entity_type={self.entity_type})>"
