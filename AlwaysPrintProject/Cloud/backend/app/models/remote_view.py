"""
Modelo SQLAlchemy para sesiones de vista remota.

Define la tabla `remote_view_sessions` que registra cada sesión de visualización
o control remoto iniciada por un operador hacia una workstation.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, Boolean, DateTime, Integer, ForeignKey, Index
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.organization import GUID


class RemoteViewSession(Base):
    """
    Sesión de vista remota entre un operador y una workstation.

    Registra el ciclo de vida completo: desde la solicitud de consentimiento
    hasta el cierre de la sesión, incluyendo modo, resolución y razón de cierre.
    """
    __tablename__ = "remote_view_sessions"

    # === CAMPOS PRINCIPALES ===
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    workstation_id = Column(
        GUID,
        ForeignKey("workstations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        GUID,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id = Column(
        GUID,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Modo de sesión: screenshot, stream, interactive
    mode = Column(String(20), nullable=False, default="screenshot")
    # Estado: pending_consent, active, expired, rejected, closed
    status = Column(String(20), nullable=False, default="pending_consent")

    # === TIMESTAMPS DE SESIÓN ===
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    last_activity_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # === CONFIGURACIÓN DE CAPTURA ===
    monitor_index = Column(Integer, nullable=False, default=0)
    resolution = Column(String(10), nullable=False, default="auto")

    # === CIERRE Y CONSENTIMIENTO ===
    # Razón de cierre: timeout, admin_closed, ws_disconnected, user_rejected, user_timeout, admin_logout
    end_reason = Column(String(30), nullable=True)
    # Consentimiento: true=aceptado, false=rechazado, null=no_requerido
    consent_given = Column(Boolean, nullable=True)

    # === AUDITORÍA ===
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # === ÍNDICES ===
    __table_args__ = (
        # Índice parcial: sesiones activas o pendientes por workstation
        Index(
            "ix_rv_sessions_ws_status",
            "workstation_id",
            "status",
            postgresql_where="status IN ('pending_consent', 'active')",
        ),
        # Índice parcial: sesiones activas por usuario
        Index(
            "ix_rv_sessions_user_status",
            "user_id",
            "status",
            postgresql_where="status = 'active'",
        ),
        # Índice estándar por organización
        Index("ix_rv_sessions_org", "organization_id"),
    )

    # === RELACIONES ===
    workstation = relationship("Workstation", backref="remote_view_sessions")
    user = relationship("User", backref="remote_view_sessions")
    organization = relationship("Organization", backref="remote_view_sessions")

    def __repr__(self):
        return (
            f"<RemoteViewSession(id={self.id}, workstation_id={self.workstation_id}, "
            f"status={self.status}, mode={self.mode})>"
        )
