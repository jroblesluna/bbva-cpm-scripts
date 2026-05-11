"""
Modelo SQLAlchemy para usuarios del sistema.

Este módulo define el modelo User que representa usuarios con diferentes roles:
- Admin: acceso global a todo el sistema
- Operador: acceso limitado a su cuenta asignada
- Usuario_Solo_Lectura: acceso de solo lectura a su cuenta
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum, TypeDecorator
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
                return str(uuid.UUID(value))
    
    def process_result_value(self, value, dialect):
        if value is None:
            return value
        else:
            if isinstance(value, uuid.UUID):
                return value
            else:
                return uuid.UUID(value)


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
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(SQLEnum(UserRole), nullable=False, default=UserRole.READONLY)
    is_active = Column(Boolean, nullable=False, default=True)
    
    # === RELACIÓN CON CUENTA ===
    # NULL para Admin (acceso global), requerido para Operador/ReadOnly
    account_id = Column(GUID, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True)
    
    timezone = Column(String(50), nullable=True)
    language = Column(String(2), nullable=False, server_default='en')

    # === PASSWORD RESET ===
    password_reset_token   = Column(String(255), nullable=True, index=True)
    password_reset_expires = Column(DateTime, nullable=True)
    
    # === TIMESTAMPS ===
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # === RELACIONES ===
    account = relationship("Account", back_populates="users")
    sent_messages = relationship("Message", back_populates="sender", foreign_keys="Message.sender_id")
    audit_logs = relationship("AuditLog", back_populates="user", foreign_keys="AuditLog.user_id")
    
    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, role={self.role})>"
