"""
Modelos SQLAlchemy para configuración jerárquica.

Este módulo define los tres niveles de configuración:
- GlobalConfig: configuración a nivel de cuenta (aplica a todas las estaciones)
- VLANConfig: configuración a nivel de VLAN (sobrescribe GlobalConfig)
- WorkstationConfig: configuración a nivel de estación (sobrescribe VLANConfig y GlobalConfig)

La resolución de configuración sigue el orden: WorkstationConfig > VLANConfig > GlobalConfig
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.organization import GUID  # Importar tipo GUID para consistencia


class GlobalConfig(Base):
    """
    Modelo de configuración global (nivel cuenta).
    
    Configuración que aplica a todas las estaciones de una cuenta.
    Cada cuenta tiene exactamente una GlobalConfig.
    """
    __tablename__ = "global_configs"
    
    # === CAMPOS PRINCIPALES ===
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    organization_id = Column(GUID, ForeignKey("organizations.id", ondelete="CASCADE"), unique=True, nullable=False)
    
    # === PARÁMETROS DE CONFIGURACIÓN ===
    # Nombre de la cola corporativa (default: "LexmarkRoblesAI")
    corporate_queue_name = Column(String(255), nullable=False, default="LexmarkRoblesAI")
    
    # Objetivos de búsqueda de impresoras: {"ips": "...", "ranges": "..."}
    search_targets = Column(JSON, nullable=True)
    
    # Intervalo de polling de tareas pendientes en minutos (rango: 1-1440, default: 3)
    pending_task_polling_minutes = Column(Integer, nullable=False, default=3)
    
    # Dominios de bootstrap separados por comas (default: "apps.iol.pe,iol.pe,sistemas.com.pe,robles.ai)
    bootstrap_domains = Column(String(1000), nullable=False, default="apps.iol.pe,iol.pe,sistemas.com.pe,robles.ai")
    language = Column(String(2), nullable=False, server_default='en')

    # === CAMPOS FASE 3: CONFIGURACIÓN EXTENDIDA ===
    # Verificaciones de conectividad (lista JSON de objetos con id, type, url, timeout_ms)
    connectivity_checks = Column(JSON, nullable=False, default=list)
    # Locale para override de idioma en el Tray (ISO 639-1 o BCP 47, max 10 chars)
    locale = Column(String(10), nullable=False, default="")
    # Habilitar telemetría en la workstation
    telemetry_enabled = Column(Boolean, nullable=False, default=True)
    # Intervalo de envío de telemetría en segundos (rango: 10-86400)
    telemetry_interval_seconds = Column(Integer, nullable=False, default=300)

    # === TIMESTAMPS ===
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # === RELACIONES ===
    organization = relationship("Organization", back_populates="global_config")
    
    def __repr__(self):
        return f"<GlobalConfig(id={self.id}, organization_id={self.organization_id})>"


class VLANConfig(Base):
    """
    Modelo de configuración de VLAN.
    
    Configuración que sobrescribe GlobalConfig para estaciones en una VLAN específica.
    Los campos nullable permiten override selectivo (NULL = usar valor de GlobalConfig).
    """
    __tablename__ = "vlan_configs"
    
    # === CAMPOS PRINCIPALES ===
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    vlan_id = Column(GUID, ForeignKey("vlans.id", ondelete="CASCADE"), unique=True, nullable=False)
    
    # === PARÁMETROS DE CONFIGURACIÓN (NULLABLE PARA OVERRIDE SELECTIVO) ===
    corporate_queue_name = Column(String(255), nullable=True)
    search_targets = Column(JSON, nullable=True)
    pending_task_polling_minutes = Column(Integer, nullable=True)
    bootstrap_domains = Column(String(1000), nullable=True)
    
    # === CAMPOS FASE 3: CONFIGURACIÓN EXTENDIDA (NULLABLE PARA OVERRIDE SELECTIVO) ===
    # Verificaciones de conectividad (NULL = usar valor de GlobalConfig)
    connectivity_checks = Column(JSON, nullable=True)
    # Locale para override de idioma (NULL = usar valor de GlobalConfig)
    locale = Column(String(10), nullable=True)
    # Habilitar telemetría (NULL = usar valor de GlobalConfig)
    telemetry_enabled = Column(Boolean, nullable=True)
    # Intervalo de telemetría en segundos (NULL = usar valor de GlobalConfig)
    telemetry_interval_seconds = Column(Integer, nullable=True)

    # === TIMESTAMPS ===
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # === RELACIONES ===
    vlan = relationship("VLAN", back_populates="vlan_config")
    
    def __repr__(self):
        return f"<VLANConfig(id={self.id}, vlan_id={self.vlan_id})>"


class WorkstationConfig(Base):
    """
    Modelo de configuración de estación específica.
    
    Configuración que sobrescribe VLANConfig y GlobalConfig para una estación específica.
    Los campos nullable permiten override selectivo (NULL = usar valor de VLANConfig o GlobalConfig).
    """
    __tablename__ = "workstation_configs"
    
    # === CAMPOS PRINCIPALES ===
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    workstation_id = Column(GUID, ForeignKey("workstations.id", ondelete="CASCADE"), unique=True, nullable=False)
    
    # === PARÁMETROS DE CONFIGURACIÓN (NULLABLE PARA OVERRIDE SELECTIVO) ===
    corporate_queue_name = Column(String(255), nullable=True)
    search_targets = Column(JSON, nullable=True)
    pending_task_polling_minutes = Column(Integer, nullable=True)
    bootstrap_domains = Column(String(1000), nullable=True)
    
    # === CAMPOS FASE 3: CONFIGURACIÓN EXTENDIDA (NULLABLE PARA OVERRIDE SELECTIVO) ===
    # Verificaciones de conectividad (NULL = usar valor de VLANConfig o GlobalConfig)
    connectivity_checks = Column(JSON, nullable=True)
    # Locale para override de idioma (NULL = usar valor de VLANConfig o GlobalConfig)
    locale = Column(String(10), nullable=True)
    # Habilitar telemetría (NULL = usar valor de VLANConfig o GlobalConfig)
    telemetry_enabled = Column(Boolean, nullable=True)
    # Intervalo de telemetría en segundos (NULL = usar valor de VLANConfig o GlobalConfig)
    telemetry_interval_seconds = Column(Integer, nullable=True)

    # === TIMESTAMPS ===
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # === RELACIONES ===
    workstation = relationship("Workstation", back_populates="workstation_config")
    
    def __repr__(self):
        return f"<WorkstationConfig(id={self.id}, workstation_id={self.workstation_id})>"
