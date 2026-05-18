"""
Modelos SQLAlchemy para telemetría y resultados de conectividad.

Este módulo define:
- TelemetryLog: registro periódico de telemetría enviado por las workstations
- ConnectivityResult: resultado individual de un check de conectividad
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, Integer, BigInteger, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.organization import GUID  # Importar tipo GUID para consistencia


class TelemetryLog(Base):
    """
    Modelo de registro de telemetría.
    
    Almacena snapshots periódicos del estado operativo de una workstation:
    estado de cola, contingencia, jobs identificados, tiempos de liberación
    y conteo de desconexiones.
    """
    __tablename__ = "telemetry_logs"
    
    # === CAMPOS PRINCIPALES ===
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    workstation_id = Column(
        GUID,
        ForeignKey("workstations.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    organization_id = Column(
        GUID,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    # Datos de telemetría
    queue_status = Column(String(20), nullable=True)  # "ok" | "missing" | "error"
    contingency_active = Column(Boolean, nullable=True)
    jobs_identified = Column(Integer, nullable=True)
    avg_release_time_ms = Column(BigInteger, nullable=True)
    disconnection_count = Column(Integer, nullable=True)
    
    # === TIMESTAMPS ===
    recorded_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    # === RELACIONES ===
    workstation = relationship("Workstation", back_populates="telemetry_logs")
    organization = relationship("Organization", back_populates="telemetry_logs")
    
    def __repr__(self):
        return (
            f"<TelemetryLog(id={self.id}, workstation_id={self.workstation_id}, "
            f"queue_status={self.queue_status}, recorded_at={self.recorded_at})>"
        )


class ConnectivityResult(Base):
    """
    Modelo de resultado de check de conectividad.
    
    Almacena el resultado individual de un check de conectividad ejecutado
    por una workstation contra un endpoint configurado (HTTP, TCP, Ping o DNS).
    """
    __tablename__ = "connectivity_results"
    
    # === CAMPOS PRINCIPALES ===
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    workstation_id = Column(
        GUID,
        ForeignKey("workstations.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    organization_id = Column(
        GUID,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    # Datos del check de conectividad
    check_id = Column(String(100), nullable=False)
    check_type = Column(String(20), nullable=False)  # "http" | "tcp" | "ping" | "dns"
    success = Column(Boolean, nullable=False)
    latency_ms = Column(BigInteger, nullable=True)
    error = Column(String(500), nullable=True)
    
    # === TIMESTAMPS ===
    recorded_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    # === RELACIONES ===
    workstation = relationship("Workstation", back_populates="connectivity_results")
    organization = relationship("Organization", back_populates="connectivity_results")
    
    def __repr__(self):
        return (
            f"<ConnectivityResult(id={self.id}, workstation_id={self.workstation_id}, "
            f"check_id={self.check_id}, success={self.success}, recorded_at={self.recorded_at})>"
        )
