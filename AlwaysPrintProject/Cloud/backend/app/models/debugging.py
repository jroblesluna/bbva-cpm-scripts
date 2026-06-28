"""
Modelos SQLAlchemy para capturas de debugging a nivel de organización.

Este módulo define:
- DebuggingProfile: perfil de monitoreo definido por el admin a nivel de org
- DebuggingSession: instancia de ejecución de un perfil sobre una workstation
- DebuggingSessionStatus: enum con los estados posibles de una sesión
"""

import enum
import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Text, DateTime, Boolean, ForeignKey,
    Integer, BigInteger, Index, Enum as SQLEnum
)
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.organization import GUID


class DebuggingSessionStatus(str, enum.Enum):
    """Estados posibles de una sesión de debugging."""
    ACTIVE = "active"
    READY = "ready"
    UPLOADING = "uploading"
    ANALYZING = "analyzing"
    ANALYZED = "analyzed"
    ANALYSIS_FAILED = "analysis_failed"
    DELETED = "deleted"
    FAILED = "failed"


class DebuggingProfile(Base):
    """
    Perfil de debugging definido a nivel de organización.
    
    Define qué monitorear durante una sesión de debugging:
    - Archivos de log externos (rutas absolutas o patrones glob)
    - Grupos de eventos Windows (System, Application, Security)
    - Llaves de registro Windows (single level, no recursivo)
    - Servicios Windows monitoreados
    
    El admin crea perfiles y el LLM sugiere nombre y mensaje de confirmación.
    Solo disponible si la organización tiene LLM habilitado.
    """
    __tablename__ = "debugging_profiles"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        GUID, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )

    # Metadata del perfil (nombre sugerido por LLM, editable por admin)
    name = Column(String(60), nullable=False, comment="Nombre del perfil (max 60 chars)")
    description = Column(Text, nullable=False, comment="Descripción de qué se monitorea y objetivo")
    confirmation_message = Column(
        String(200), nullable=False,
        comment="Mensaje de confirmación mostrado al iniciar (sugerido por LLM)"
    )

    # Targets de monitoreo (almacenados como JSON arrays en texto)
    external_logs = Column(
        Text, nullable=False, server_default="[]",
        comment="JSON array de rutas/patrones de logs externos"
    )
    eventlog_groups = Column(
        Text, nullable=False, server_default="[]",
        comment="JSON array de grupos de eventos: System, Application, Security"
    )
    registry_keys = Column(
        Text, nullable=False, server_default="[]",
        comment="JSON array de llaves de registro a monitorear (single level)"
    )
    monitored_services = Column(
        Text, nullable=False, server_default="[]",
        comment="JSON array de nombres de servicios Windows"
    )

    # Estado
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")

    # Auditoría
    created_by = Column(GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    organization = relationship("Organization", backref="debugging_profiles")
    creator = relationship("User", foreign_keys=[created_by])
    sessions = relationship("DebuggingSession", back_populates="profile", cascade="all, delete-orphan")

    # Índices
    __table_args__ = (
        Index("ix_debugging_profiles_org_active", "organization_id", "is_active"),
    )

    def __repr__(self):
        return (
            f"<DebuggingProfile(id={self.id}, name='{self.name}', "
            f"org={self.organization_id}, active={self.is_active})>"
        )


class DebuggingSession(Base):
    """
    Sesión de debugging ejecutada sobre una workstation específica.
    
    Representa una instancia de ejecución de un DebuggingProfile.
    El debugging_id es el propio id de la sesión (UUID).
    
    Ciclo de vida:
    - active: captura en progreso en el cliente
    - ready: datos listos para recolección en el cliente
    - uploading: ZIP siendo subido al backend
    - analyzing: LLM procesando los datos
    - analyzed: PDF generado y disponible en S3
    - analysis_failed: error durante el análisis
    - deleted: datos eliminados del cliente
    - failed: error al iniciar o desconexión
    """
    __tablename__ = "debugging_sessions"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        GUID, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    profile_id = Column(
        GUID, ForeignKey("debugging_profiles.id", ondelete="SET NULL"), nullable=True
    )
    workstation_id = Column(
        GUID, ForeignKey("workstations.id", ondelete="CASCADE"), nullable=False
    )

    # Estado de la sesión
    status = Column(
        SQLEnum(
            DebuggingSessionStatus,
            name="debuggingsessionstatus",
            create_type=False,
            values_callable=lambda x: [e.value for e in x]
        ),
        nullable=False,
        server_default="active"
    )

    # Parámetros de captura
    duration_seconds = Column(Integer, nullable=False, comment="Duración configurada (15-300s)")
    start_time = Column(DateTime, nullable=False, default=datetime.utcnow)
    end_time = Column(DateTime, nullable=True)

    # Contexto del admin/operador (solo para el prompt LLM)
    motivo = Column(Text, nullable=True, comment="Motivo del debugging (para contexto LLM)")
    additional_instructions = Column(
        Text, nullable=True,
        comment="Instrucciones adicionales para el análisis LLM"
    )

    # Resultados
    total_data_size_bytes = Column(
        BigInteger, nullable=True,
        comment="Tamaño total de datos reportado por el cliente"
    )
    s3_report_key = Column(
        String(500), nullable=True,
        comment="S3 key del PDF de reporte generado"
    )

    # Trazabilidad
    initiated_by = Column(GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relaciones
    organization = relationship("Organization", backref="debugging_sessions")
    profile = relationship("DebuggingProfile", back_populates="sessions")
    workstation = relationship("Workstation", backref="debugging_sessions")
    initiator = relationship("User", foreign_keys=[initiated_by])

    # Índices
    __table_args__ = (
        Index("ix_debugging_sessions_org_status", "organization_id", "status"),
        Index("ix_debugging_sessions_ws_status", "workstation_id", "status"),
    )

    def __repr__(self):
        return (
            f"<DebuggingSession(id={self.id}, ws={self.workstation_id}, "
            f"status={self.status}, profile={self.profile_id})>"
        )
