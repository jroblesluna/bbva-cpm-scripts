"""
Modelo de configuración de acciones administrativas.

Este modelo almacena archivos de configuración (.alwaysconfig) que definen
acciones administrativas a ejecutar en las workstations en respuesta a eventos.
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Boolean, ForeignKey, Index
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.account import GUID


class ActionConfig(Base):
    """
    Configuración de acciones administrativas para una organización.
    
    Una organización puede tener máximo 1 configuración activa.
    Las workstations descargan y ejecutan esta configuración automáticamente.
    """
    __tablename__ = "action_configs"
    
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    
    # Relación con organización (Account)
    organization_id = Column(GUID, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    
    # Metadatos de la configuración
    name = Column(String(255), nullable=False, comment="Nombre de la configuración (ej: CPM_Compliant)")
    version = Column(String(50), nullable=False, comment="Versión de la configuración (ej: 1.0)")
    description = Column(Text, nullable=True, comment="Descripción de la configuración")
    
    # Contenido JSON de la configuración
    config_json = Column(Text, nullable=False, comment="JSON completo del archivo .alwaysconfig")
    
    # Hash SHA256 (primeros 8 caracteres) para verificación de integridad
    config_hash = Column(String(8), nullable=False, index=True, comment="Hash SHA256 corto (8 chars)")
    
    # Estado de activación
    is_active = Column(Boolean, default=True, nullable=False, comment="Si está activa para propagación")
    
    # Ruta de almacenamiento (S3 o local)
    storage_path = Column(String(500), nullable=True, comment="Ruta en S3 o filesystem local")
    
    # Auditoría
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by_id = Column(GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # Relaciones
    organization = relationship("Account", back_populates="action_configs")
    created_by = relationship("User", foreign_keys=[created_by_id])
    
    # Índices compuestos
    __table_args__ = (
        Index("ix_action_configs_org_active", "organization_id", "is_active"),
        Index("ix_action_configs_org_hash", "organization_id", "config_hash"),
    )
    
    def __repr__(self):
        return f"<ActionConfig(id={self.id}, org={self.organization_id}, name='{self.name}', active={self.is_active})>"
