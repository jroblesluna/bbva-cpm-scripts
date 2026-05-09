"""
Modelo SQLAlchemy para usuarios del sistema.

Este módulo define el modelo User que representa usuarios con diferentes roles:
- Admin: acceso global a todo el sistema
- Operador: acceso limitado a su cuenta asignada
- Usuario_Solo_Lectura: acceso de solo lectura a su cuenta
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


class UserRole(str, enum.Enum):
    """Roles de usuario en el sistema."""
    ADMIN = "admin"
    OPERATOR = "operator"
    READONLY = "readonly"


class User(Base):
    """
    Modelo de usuario del sistema.
    
    Representa usuarios que pueden autenticarse y operar el sistema.
    Los Admin tienen acceso global, mientras que Operadores y ReadOnly
    están limitados a su cuenta asignada.
    """
    __tablename__ = "users"
    
    # === CAMPOS PRINCIPALES ===
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(SQLEnum(UserRole), nullable=False, default=UserRole.READONLY)
    is_active = Column(Boolean, nullable=False, default=True)
    
    # === RELACIÓN CON CUENTA ===
    # NULL para Admin (acceso global), requerido para Operador/ReadOnly
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True)
    
    # === TIMESTAMPS ===
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # === RELACIONES ===
    account = relationship("Account", back_populates="users")
    sent_messages = relationship("Message", back_populates="sender", foreign_keys="Message.sender_id")
    audit_logs = relationship("AuditLog", back_populates="user", foreign_keys="AuditLog.user_id")
    
    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, role={self.role})>"
