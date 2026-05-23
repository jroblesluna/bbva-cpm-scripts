"""
Modelo SQLAlchemy para análisis de logs de workstations.

Este módulo define:
- LogAnalysis: registro de un análisis de log generado por el LLM,
  asociado a una workstation y organización específicas.
"""

import uuid

from sqlalchemy import Column, String, Text, DateTime, Integer, Date, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.organization import GUID


class LogAnalysis(Base):
    """
    Modelo de análisis de log de una workstation.

    Almacena el resultado del análisis LLM de un log de workstation,
    incluyendo metadata del procesamiento (ruta, tamaño, duración).
    Se permite máximo un análisis por workstation por día (overwrite con confirmación).
    """
    __tablename__ = "log_analyses"

    # === CAMPOS PRINCIPALES ===
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    workstation_id = Column(GUID, ForeignKey("workstations.id", ondelete="CASCADE"), nullable=False)
    organization_id = Column(GUID, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)

    # Fecha del análisis (solo fecha, sin hora) para control de unicidad diaria
    analysis_date = Column(Date, nullable=False)

    # Texto del análisis generado por el LLM
    analysis_text = Column(Text, nullable=False)

    # Metadata del procesamiento
    processing_path = Column(String(20), nullable=False, comment="Ruta de procesamiento: 'direct' o 'structural'")
    log_size_bytes = Column(Integer, nullable=False, comment="Tamaño del log en bytes")
    processing_duration_ms = Column(Integer, nullable=False, comment="Duración del procesamiento en milisegundos")
    original_filename = Column(String(255), nullable=False, comment="Nombre original del archivo de log")

    # === TIMESTAMPS ===
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    # === RELACIONES ===
    workstation = relationship("Workstation", backref="log_analyses")
    organization = relationship("Organization", backref="log_analyses")

    # === ÍNDICES ===
    __table_args__ = (
        Index("ix_log_analyses_workstation_date", "workstation_id", "analysis_date"),
        Index("ix_log_analyses_organization", "organization_id"),
    )

    def __repr__(self):
        return (
            f"<LogAnalysis(id={self.id}, workstation_id={self.workstation_id}, "
            f"date={self.analysis_date}, path={self.processing_path})>"
        )
