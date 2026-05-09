"""
Modelo SQLAlchemy para auditoría de operaciones.

Este módulo define el modelo AuditLog que registra todas las operaciones
críticas del sistema para trazabilidad y cumplimiento.
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, JSON, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


class ActionType(str, enum.Enum):
    """Tipos de acciones auditables en el sistema."""
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    CONFIG_CHANGE = "config_change"
    CONTINGENCY_TOGGLE = "contingency_toggle"
    MESSAGE_SENT = "message_sent"
    COMMAND_SENT = "command_sent"


class AuditLog(Base):
    """
    Modelo de registro de auditoría.
    
    Registra todas las operaciones críticas del sistema con información
    completa para trazabilidad. Los registros son inmutables.
    """
    __tablename__ = "audit_logs"
    
    # === CAMPOS PRINCIPALES ===
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Usuario que realizó la acción (NULL para acciones del sistema)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # Estación afectada (si aplica)
    workstation_id = Column(UUID(as_uuid=True), ForeignKey("workstations.id", ondelete="SET NULL"), nullable=True)
    
    # Cuenta afectada (si aplica)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    
    # === INFORMACIÓN DE LA ACCIÓN ===
    action_type = Column(SQLEnum(ActionType), nullable=False, index=True)
    entity_type = Column(String(100), nullable=False, index=True)  # Tipo de entidad afectada
    entity_id = Column(UUID(as_uuid=True), nullable=False, index=True)  # ID de la entidad afectada
    
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
    account = relationship("Account", back_populates="audit_logs", foreign_keys=[account_id])
    
    def __repr__(self):
        return f"<AuditLog(id={self.id}, action_type={self.action_type}, entity_type={self.entity_type})>"
