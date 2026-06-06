"""
Modelos SQLAlchemy para monitoreo de estado del sistema.

Este módulo define las tablas para almacenar snapshots de métricas del sistema,
registros individuales de métricas, resultados de health checks y métricas
de contenedores Docker.

Tablas:
- status_snapshots: Registro completo de una ejecución de recolección
- metric_records: Métricas individuales asociadas a un snapshot
- health_check_results: Resultados de verificación de servicios
- container_metrics: Métricas de contenedores Docker
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Float, Boolean, Integer, BigInteger,
    DateTime, Text, ForeignKey, Index, Enum as SQLEnum
)
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.organization import GUID


# === ENUMERACIONES ===

class OverallStatus(str, enum.Enum):
    """Estado general del sistema calculado según umbrales."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"


# === TABLA: status_snapshots ===

class StatusSnapshot(Base):
    """
    Registro completo de una ejecución de recolección de métricas.

    Almacena las métricas principales del sistema operativo y el estado
    general calculado según los umbrales definidos.
    """
    __tablename__ = "status_snapshots"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    timestamp = Column(
        DateTime(timezone=True),
        nullable=False,
        comment="Momento de la recolección (UTC)"
    )
    overall_status = Column(
        SQLEnum(
            OverallStatus,
            name="overallstatus",
            create_type=False,
            values_callable=lambda x: [e.value for e in x]
        ),
        nullable=False,
        comment="Estado general: healthy, degraded, critical"
    )

    # Métricas de memoria
    memory_percent = Column(Float, nullable=False, comment="Porcentaje de memoria usada")
    memory_total_mb = Column(Float, nullable=False, comment="RAM total en MB")
    memory_used_mb = Column(Float, nullable=False, comment="RAM usada en MB")
    memory_available_mb = Column(Float, nullable=False, comment="RAM disponible en MB")

    # Métricas de disco
    disk_percent = Column(Float, nullable=False, comment="Porcentaje de disco usado")
    disk_total_mb = Column(Float, nullable=False, comment="Disco total en MB")
    disk_used_mb = Column(Float, nullable=False, comment="Disco usado en MB")
    disk_available_mb = Column(Float, nullable=False, comment="Disco disponible en MB")

    # Métricas de CPU
    cpu_percent = Column(Float, nullable=False, comment="Porcentaje de CPU promedio")

    # Métricas de swap
    swap_used_mb = Column(Float, nullable=False, comment="Swap usado en MB")
    swap_total_mb = Column(Float, nullable=False, comment="Swap total en MB")
    swap_available_mb = Column(Float, nullable=False, comment="Swap disponible en MB")

    # Sistema
    uptime_seconds = Column(Integer, nullable=False, comment="Uptime del SO en segundos")
    docker_available = Column(Boolean, nullable=False, comment="Si Docker respondió correctamente")

    # Métricas de escalabilidad (JSON serializado)
    scalability_metrics_json = Column(
        Text,
        nullable=True,
        comment="JSON serializado de métricas de escalabilidad"
    )

    # Auditoría
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment="Timestamp de inserción en BD"
    )

    # Relaciones (hijos con CASCADE)
    metric_records = relationship(
        "MetricRecord",
        back_populates="snapshot",
        cascade="all, delete-orphan",
        passive_deletes=True
    )
    health_check_results = relationship(
        "HealthCheckResult",
        back_populates="snapshot",
        cascade="all, delete-orphan",
        passive_deletes=True
    )
    container_metrics = relationship(
        "ContainerMetric",
        back_populates="snapshot",
        cascade="all, delete-orphan",
        passive_deletes=True
    )

    # Índices
    __table_args__ = (
        Index("ix_status_snapshots_timestamp", "timestamp"),
        Index("ix_status_snapshots_overall_status", "overall_status"),
    )

    def __repr__(self):
        return (
            f"<StatusSnapshot(id={self.id}, timestamp={self.timestamp}, "
            f"status={self.overall_status})>"
        )


# === TABLA: metric_records ===

class MetricRecord(Base):
    """
    Registro individual de una métrica específica dentro de un snapshot.

    Permite queries de serie temporal por nombre de métrica.
    """
    __tablename__ = "metric_records"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    snapshot_id = Column(
        GUID,
        ForeignKey("status_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        comment="Snapshot padre"
    )
    metric_name = Column(
        String(100),
        nullable=False,
        comment="Nombre de la métrica (cpu_percent, memory_percent, etc.)"
    )
    value = Column(Float, nullable=False, comment="Valor numérico de la métrica")
    unit = Column(
        String(20),
        nullable=False,
        comment="Unidad de medida (percent, mb, seconds, bytes)"
    )
    timestamp = Column(
        DateTime(timezone=True),
        nullable=False,
        comment="Momento de recolección (UTC)"
    )

    # Relación con snapshot padre
    snapshot = relationship("StatusSnapshot", back_populates="metric_records")

    # Índices
    __table_args__ = (
        Index("ix_metric_records_snapshot_id", "snapshot_id"),
        Index("ix_metric_records_name_timestamp", "metric_name", "timestamp"),
    )

    def __repr__(self):
        return (
            f"<MetricRecord(id={self.id}, name={self.metric_name}, "
            f"value={self.value} {self.unit})>"
        )


# === TABLA: health_check_results ===

class HealthCheckResult(Base):
    """
    Resultado de verificación de disponibilidad de un servicio.

    Almacena si el servicio está disponible, su latencia y cualquier
    error encontrado durante la verificación.
    """
    __tablename__ = "health_check_results"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    snapshot_id = Column(
        GUID,
        ForeignKey("status_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        comment="Snapshot padre"
    )
    service_name = Column(
        String(100),
        nullable=False,
        comment="Nombre del servicio verificado"
    )
    is_available = Column(
        Boolean,
        nullable=False,
        comment="Si el servicio está disponible"
    )
    latency_ms = Column(
        Float,
        nullable=True,
        comment="Latencia de respuesta en milisegundos"
    )
    error_message = Column(
        Text,
        nullable=True,
        comment="Mensaje de error si el servicio no está disponible"
    )
    details_json = Column(
        Text,
        nullable=True,
        comment="JSON con detalles extra (días SSL restantes, etc.)"
    )
    timestamp = Column(
        DateTime(timezone=True),
        nullable=False,
        comment="Momento de verificación (UTC)"
    )

    # Relación con snapshot padre
    snapshot = relationship("StatusSnapshot", back_populates="health_check_results")

    # Índices
    __table_args__ = (
        Index("ix_health_checks_snapshot_id", "snapshot_id"),
        Index("ix_health_checks_service_timestamp", "service_name", "timestamp"),
    )

    def __repr__(self):
        return (
            f"<HealthCheckResult(id={self.id}, service={self.service_name}, "
            f"available={self.is_available})>"
        )


# === TABLA: container_metrics ===

class ContainerMetric(Base):
    """
    Métricas de un contenedor Docker en un momento dado.

    Almacena CPU, memoria, red y estado de cada contenedor.
    """
    __tablename__ = "container_metrics"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    snapshot_id = Column(
        GUID,
        ForeignKey("status_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        comment="Snapshot padre"
    )
    container_name = Column(
        String(100),
        nullable=False,
        comment="Nombre del contenedor Docker"
    )
    status = Column(
        String(20),
        nullable=False,
        comment="Estado: running, stopped, restarting"
    )
    cpu_percent = Column(Float, nullable=False, comment="Porcentaje de CPU del contenedor")
    memory_used_mb = Column(Float, nullable=False, comment="Memoria usada en MB")
    memory_limit_mb = Column(Float, nullable=False, comment="Límite de memoria en MB")
    network_rx_bytes = Column(
        BigInteger,
        nullable=False,
        comment="Bytes recibidos por red"
    )
    network_tx_bytes = Column(
        BigInteger,
        nullable=False,
        comment="Bytes enviados por red"
    )
    uptime_seconds = Column(
        Integer,
        nullable=False,
        comment="Tiempo activo del contenedor en segundos"
    )

    # Relación con snapshot padre
    snapshot = relationship("StatusSnapshot", back_populates="container_metrics")

    # Índices
    __table_args__ = (
        Index("ix_container_metrics_snapshot_id", "snapshot_id"),
    )

    def __repr__(self):
        return (
            f"<ContainerMetric(id={self.id}, container={self.container_name}, "
            f"status={self.status})>"
        )
