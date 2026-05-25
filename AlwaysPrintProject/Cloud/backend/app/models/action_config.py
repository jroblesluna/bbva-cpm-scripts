"""
Modelo de configuración de acciones administrativas.

Este modelo almacena archivos de configuración (.alwaysconfig) que definen
acciones administrativas a ejecutar en las workstations en respuesta a eventos.

Soporta herencia jerárquica: Organización → VLAN → Workstation.
- scope='org': aplica a toda la organización (default o mandatory)
- scope='vlan': aplica a una VLAN específica
- scope='workstation': aplica a una workstation específica

La resolución sigue: Workstation > VLAN > Org, respetando flags mandatory.
"""

import enum
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Boolean, ForeignKey, Index, Enum as SQLEnum
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.organization import GUID


class ActionConfigScope(str, enum.Enum):
    """Nivel jerárquico de la configuración de acciones."""
    ORG = "org"
    VLAN = "vlan"
    WORKSTATION = "workstation"


class ActionConfig(Base):
    """
    Configuración de acciones administrativas.
    
    Soporta tres niveles jerárquicos:
    - org: aplica a toda la organización (puede ser mandatory)
    - vlan: aplica a una VLAN específica (puede ser mandatory para sus workstations)
    - workstation: aplica a una workstation específica
    
    Resolución: si org.mandatory → usa org. Si no, busca VLAN. Si VLAN.mandatory → usa VLAN.
    Si no, busca workstation. Fallback: VLAN → Org.
    """
    __tablename__ = "action_configs"
    
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    
    # Relación con organización (siempre presente para tenant isolation)
    organization_id = Column(GUID, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    
    # Nivel jerárquico
    scope = Column(
        SQLEnum(ActionConfigScope, name='actionconfigscope', create_type=False,
                values_callable=lambda x: [e.value for e in x]),
        nullable=False, server_default='org',
        comment="Nivel de la configuración: org, vlan o workstation"
    )
    
    # FK opcionales según scope
    vlan_id = Column(GUID, ForeignKey("vlans.id", ondelete="CASCADE"), nullable=True,
                     comment="VLAN a la que aplica (solo si scope=vlan)")
    workstation_id = Column(GUID, ForeignKey("workstations.id", ondelete="CASCADE"), nullable=True,
                            comment="Workstation a la que aplica (solo si scope=workstation)")
    
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
    organization = relationship("Organization", back_populates="action_configs")
    vlan = relationship("VLAN", foreign_keys=[vlan_id])
    workstation = relationship("Workstation", foreign_keys=[workstation_id])
    created_by = relationship("User", foreign_keys=[created_by_id])
    
    # Índices compuestos
    __table_args__ = (
        Index("ix_action_configs_org_active", "organization_id", "is_active"),
        Index("ix_action_configs_org_hash", "organization_id", "config_hash"),
        Index("ix_action_configs_vlan_active", "vlan_id", "is_active"),
        Index("ix_action_configs_ws_active", "workstation_id", "is_active"),
    )
    
    def __repr__(self):
        return (
            f"<ActionConfig(id={self.id}, scope={self.scope}, org={self.organization_id}, "
            f"name='{self.name}', active={self.is_active})>"
        )
