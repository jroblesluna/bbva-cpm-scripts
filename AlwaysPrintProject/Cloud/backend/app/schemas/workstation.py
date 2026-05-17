"""
Schemas Pydantic para Workstation y License.

Este módulo define los schemas de validación para:
- Workstation: estación Windows que ejecuta AlwaysPrint
- License: licencia activa para una estación
"""

from datetime import datetime
from typing import Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel, Field


# === SCHEMAS DE LICENSE ===

class LicenseResponse(BaseModel):
    """Schema de respuesta para licencia."""
    id: UUID
    workstation_id: UUID
    serial_number: str = Field(..., min_length=8, max_length=8, description="Número de serie (últimos 8 caracteres del MD5)")
    is_active: bool
    activated_at: datetime
    deactivated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


# === SCHEMAS DE WORKSTATION ===

class WorkstationRegisterRequest(BaseModel):
    """Schema para solicitud de registro de workstation (sin autenticación)."""
    ip_private: str = Field(..., description="IP privada de la workstation")
    hostname: Optional[str] = Field(None, max_length=255, description="Nombre del host Windows")
    os_serial: Optional[str] = Field(None, max_length=255, description="Serial del sistema operativo")
    current_user: Optional[str] = Field(None, max_length=255, description="Usuario actualmente logueado")


class WorkstationRegisterResponse(BaseModel):
    """Schema de respuesta para registro exitoso de workstation."""
    workstation_id: UUID = Field(..., description="ID de la workstation registrada")
    organization_id: UUID = Field(..., description="ID de la organización asociada")
    organization_name: str = Field(..., description="Nombre de la organización")
    message: str = Field(..., description="Mensaje de confirmación")
    cloud_api_url: str = Field(..., description="URL del servidor cloud para uso futuro")


class WorkstationRegisterPendingResponse(BaseModel):
    """Schema de respuesta cuando la IP pública está pendiente de autorización."""
    status: str = Field("pending", description="Estado del registro")
    public_ip: str = Field(..., description="IP pública detectada")
    message: str = Field(..., description="Mensaje explicativo")
    retry_after_seconds: int = Field(300, description="Segundos recomendados antes de reintentar")


class WorkstationResponse(BaseModel):
    """Schema de respuesta para workstation."""
    id: UUID
    organization_id: UUID
    vlan_id: Optional[UUID] = None
    ip_private: str = Field(..., description="IP privada (identificador único)")
    hostname: Optional[str] = None
    os_serial: Optional[str] = None
    current_user: Optional[str] = None
    is_online: bool
    contingency_active: bool
    last_connection: Optional[datetime] = None
    first_seen: datetime
    created_at: datetime
    updated_at: datetime
    
    # Relación con organización (anidada)
    organization: Optional['OrganizationBasicResponse'] = None
    
    class Config:
        from_attributes = True


# Schema básico de organización para relaciones anidadas
class OrganizationBasicResponse(BaseModel):
    """Schema básico de organización para relaciones anidadas."""
    id: UUID
    name: str
    is_active: bool
    timezone: str = "UTC"
    
    class Config:
        from_attributes = True


# Actualizar forward reference
WorkstationResponse.model_rebuild()


class WorkstationDetailResponse(WorkstationResponse):
    """Schema de respuesta detallada para workstation (incluye licencia activa)."""
    active_license: Optional[LicenseResponse] = None
    
    class Config:
        from_attributes = True


class WorkstationUpdate(BaseModel):
    """Schema para actualizar información de workstation."""
    hostname: Optional[str] = Field(None, max_length=255)
    os_serial: Optional[str] = Field(None, max_length=255)
    current_user: Optional[str] = Field(None, max_length=255)
    vlan_id: Optional[UUID] = None


class WorkstationStatusUpdate(BaseModel):
    """Schema para actualizar estado de workstation."""
    is_online: Optional[bool] = None
    contingency_active: Optional[bool] = None


class WorkstationListResponse(BaseModel):
    """Schema de respuesta para lista paginada de workstations."""
    items: list[WorkstationResponse]
    total: int
    skip: int
    limit: int


class WorkstationStatsResponse(BaseModel):
    """Schema de respuesta para estadísticas de workstations."""
    total: int
    online: int
    offline: int
    contingency_active: int
    total_vlans: int = Field(0, description="Total de VLANs creadas en la organización")
    by_vlan: Optional[Dict[str, int]] = Field(None, description="Distribución por VLAN")
    by_organization: Optional[Dict[str, Dict[str, Any]]] = Field(None, description="Distribución por organización (solo admin)")
