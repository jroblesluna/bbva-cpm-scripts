"""
Schemas Pydantic para Workstation y License.

Este módulo define los schemas de validación para:
- Workstation: estación Windows que ejecuta AlwaysPrint
- License: licencia activa para una estación
"""

import ipaddress
from datetime import datetime
from typing import Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel, Field, field_validator


# === SCHEMAS DE LICENSE ===

class LicenseResponse(BaseModel):
    """Schema de respuesta para licencia."""
    id: UUID
    workstation_id: UUID
    serial_number: str = Field(..., min_length=8, max_length=8, description="Número de serie (últimos 8 caracteres del MD5)")
    is_active: bool
    activated_at: datetime
    deactivated_at: Optional[datetime] = None
    
    model_config = {"from_attributes": True}


# === SCHEMAS DE WORKSTATION ===

class WorkstationRegisterRequest(BaseModel):
    """Schema para solicitud de registro de workstation (sin autenticación)."""
    ip_private: str = Field(..., description="IP privada de la workstation")
    hostname: Optional[str] = Field(None, max_length=255, description="Nombre del host Windows")
    os_serial: Optional[str] = Field(None, max_length=255, description="Serial del sistema operativo")
    current_user: Optional[str] = Field(None, max_length=255, description="Usuario actualmente logueado")
    cidr: Optional[str] = Field(None, description="CIDR de la subred de la workstation (ej: 192.168.1.0/24)")
    tray_version: Optional[str] = Field(None, max_length=50, description="Versión del AlwaysPrintTray")

    @field_validator('cidr')
    @classmethod
    def validar_cidr(cls, v: Optional[str]) -> Optional[str]:
        """Valida y normaliza el CIDR a su forma canónica.

        - Si es None (clientes antiguos sin soporte CIDR), se permite
        - Verifica que sea una notación IPv4 CIDR válida
        - Verifica que el prefix length esté en rango 8-30
        - Normaliza a forma canónica (ej: 192.168.1.50/24 → 192.168.1.0/24)
        """
        if v is None:
            return None

        try:
            red = ipaddress.ip_network(v, strict=False)
        except ValueError:
            raise ValueError(f"CIDR inválido: '{v}'. Debe ser una notación IPv4 CIDR válida (ej: 192.168.1.0/24)")

        # Verificar que sea IPv4
        if red.version != 4:
            raise ValueError(f"CIDR inválido: '{v}'. Solo se admiten redes IPv4")

        # Verificar que el prefix length esté en rango 8-30
        if red.prefixlen < 8 or red.prefixlen > 30:
            raise ValueError(
                f"CIDR inválido: '{v}'. El prefix length debe estar entre 8 y 30 (recibido: {red.prefixlen})"
            )

        # Retornar forma canónica normalizada
        return str(red)


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
    forced_contingency: bool = False
    action_config_mandatory: bool = False
    last_connection: Optional[datetime] = None
    first_seen: datetime
    created_at: datetime
    updated_at: datetime
    cidr: Optional[str] = Field(None, description="CIDR de la subred reportado por la workstation")
    tray_version: Optional[str] = Field(None, description="Versión del AlwaysPrintTray instalado")
    default_printer_id: Optional[UUID] = Field(None, description="ID del dispositivo (impresora) predeterminado")
    
    # Relación con organización (anidada)
    organization: Optional['OrganizationBasicResponse'] = None
    
    # Relación con VLAN (anidada)
    vlan: Optional['VLANBasicResponse'] = None
    
    model_config = {"from_attributes": True}


# Schema básico de organización para relaciones anidadas
class OrganizationBasicResponse(BaseModel):
    """Schema básico de organización para relaciones anidadas."""
    id: UUID
    name: str
    is_active: bool
    timezone: str = "UTC"
    forced_contingency: bool = False
    
    model_config = {"from_attributes": True}


# Schema básico de VLAN para relaciones anidadas
class VLANBasicResponse(BaseModel):
    """Schema básico de VLAN para relaciones anidadas."""
    id: UUID
    name: str
    forced_contingency: bool = False
    contingency_inherited: Optional[bool] = None
    
    model_config = {"from_attributes": True}


# Actualizar forward references
WorkstationResponse.model_rebuild()


class WorkstationDetailResponse(WorkstationResponse):
    """Schema de respuesta detallada para workstation (incluye licencia activa)."""
    active_license: Optional[LicenseResponse] = None
    
    model_config = {"from_attributes": True}


class WorkstationUpdate(BaseModel):
    """Schema para actualizar información de workstation."""
    hostname: Optional[str] = Field(None, max_length=255)
    os_serial: Optional[str] = Field(None, max_length=255)
    current_user: Optional[str] = Field(None, max_length=255)
    vlan_id: Optional[UUID] = None
    default_printer_id: Optional[UUID] = Field(None, description="ID del dispositivo (impresora) predeterminado")
    action_config_mandatory: Optional[bool] = Field(None, description="Si True, aplica la config de acciones propia de esta workstation")


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


class VLANSummaryItem(BaseModel):
    """Resumen de una VLAN para el dashboard del operador."""
    id: str
    name: str
    has_devices: bool = Field(description="Si la VLAN tiene al menos un dispositivo asignado")
    device_count: int = Field(0, description="Cantidad de dispositivos en la VLAN")
    workstation_count: int = Field(0, description="Cantidad de workstations en la VLAN")
    has_vlan_config: bool = Field(False, description="Si la VLAN tiene action config activa a su nivel")
    workstations_with_config: int = Field(0, description="Cantidad de workstations con action config propia")
    forced_contingency: bool = Field(False, description="Si la VLAN tiene contingencia forzada activa")


class WorkstationConfigItem(BaseModel):
    """Workstation que tiene action config propia."""
    id: str
    ip_private: str
    hostname: Optional[str] = None
    vlan_name: Optional[str] = None
    config_name: str = Field(description="Nombre de la action config asignada")


class OrganizationInfo(BaseModel):
    """Info de la organización del operador para el dashboard."""
    id: str
    name: str
    forced_contingency: bool = Field(False, description="Si la organización tiene contingencia forzada")
    has_org_config: bool = Field(False, description="Si la organización tiene action config activa a nivel org")
    action_config_mandatory: bool = Field(False, description="Si la config de la org es obligatoria para todas las VLANs/WS")


class WorkstationStatsResponse(BaseModel):
    """Schema de respuesta para estadísticas de workstations."""
    total: int
    online: int
    offline: int
    contingency_active: int
    total_vlans: int = Field(0, description="Total de VLANs creadas en la organización")
    vlans_in_contingency: int = Field(0, description="VLANs con forced_contingency activo")
    by_vlan: Optional[Dict[str, int]] = Field(None, description="Distribución por VLAN")
    by_organization: Optional[Dict[str, Dict[str, Any]]] = Field(None, description="Distribución por organización (solo admin)")
    vlan_summary: Optional[list["VLANSummaryItem"]] = Field(None, description="Resumen de VLANs con estado de dispositivos y configs")
    organization_info: Optional["OrganizationInfo"] = Field(None, description="Info de la organización (solo operadores)")
    workstations_with_config: Optional[list["WorkstationConfigItem"]] = Field(None, description="Workstations con action config propia")
