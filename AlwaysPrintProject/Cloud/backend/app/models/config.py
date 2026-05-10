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
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.account import GUID  # Importar tipo GUID para consistencia


class GlobalConfig(Base):
    """
    Modelo de configuración global (nivel cuenta).
    
    Configuración que aplica a todas las estaciones de una cuenta.
    Cada cuenta tiene exactamente una GlobalConfig.
    """
    __tablename__ = "global_configs"
    
    # === CAMPOS PRINCIPALES ===
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    account_id = Column(GUID, ForeignKey("accounts.id", ondelete="CASCADE"), unique=True, nullable=False)
    
    # === PARÁMETROS DE CONFIGURACIÓN ===
    # Nombre de la cola corporativa (default: "LexmarkRoblesAI")
    corporate_queue_name = Column(String(255), nullable=False, default="LexmarkRoblesAI")
    
    # Objetivos de búsqueda de impresoras: {"ips": "...", "ranges": "..."}
    search_targets = Column(JSON, nullable=True)
    
    # Intervalo de polling de tareas pendientes en minutos (rango: 1-1440, default: 3)
    pending_task_polling_minutes = Column(Integer, nullable=False, default=3)
    
    # Dominios de bootstrap separados por comas (default: "robles.ai,iol.pe,sistemas.com.pe")
    bootstrap_domains = Column(String(1000), nullable=False, default="robles.ai,iol.pe,sistemas.com.pe")
    
    # === TIMESTAMPS ===
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # === RELACIONES ===
    account = relationship("Account", back_populates="global_config")
    
    def __repr__(self):
        return f"<GlobalConfig(id={self.id}, account_id={self.account_id})>"


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
    
    # === TIMESTAMPS ===
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # === RELACIONES ===
    workstation = relationship("Workstation", back_populates="workstation_config")
    
    def __repr__(self):
        return f"<WorkstationConfig(id={self.id}, workstation_id={self.workstation_id})>"
