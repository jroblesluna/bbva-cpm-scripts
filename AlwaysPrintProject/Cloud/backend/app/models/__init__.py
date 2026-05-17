"""
Módulo de modelos SQLAlchemy.

Este módulo exporta todos los modelos de datos del sistema para facilitar
su importación desde otros módulos.
"""

from app.models.user import User, UserRole
from app.models.organization import Organization, Account, PublicIP
from app.models.vlan import VLAN
from app.models.workstation import Workstation, License
from app.models.config import GlobalConfig, VLANConfig, WorkstationConfig
from app.models.audit import AuditLog, ActionType
from app.models.message import Message, TargetType
from app.models.telemetry import TelemetryLog, ConnectivityResult
from app.models.action_config import ActionConfig

__all__ = [
    # User models
    "User",
    "UserRole",
    
    # Organization models
    "Organization",
    "Account",  # Alias de compatibilidad
    "PublicIP",
    
    # VLAN models
    "VLAN",
    
    # Workstation models
    "Workstation",
    "License",
    
    # Config models
    "GlobalConfig",
    "VLANConfig",
    "WorkstationConfig",
    
    # Audit models
    "AuditLog",
    "ActionType",
    
    # Message models
    "Message",
    "TargetType",
    
    # Telemetry models
    "TelemetryLog",
    "ConnectivityResult",
    
    # Action config models
    "ActionConfig",
]
