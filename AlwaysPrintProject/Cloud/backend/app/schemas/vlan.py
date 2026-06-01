"""
Schemas Pydantic para VLAN.

Este módulo define los schemas de validación para VLANs (segmentos de red).
"""

import re
from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field, field_validator
import ipaddress


# === SCHEMAS DE VLAN ===

def _validate_unc_path(value: str) -> str:
    """
    Valida que un valor sea un UNC path válido: \\\\host\\share
    - host debe ser hostname, FQDN o IP (sin espacios)
    - share puede contener espacios (nombre de cola/recurso compartido)
    """
    if not value.startswith('\\\\'):
        raise ValueError(
            f"UNC path inválido: '{value}'. Debe comenzar con \\\\ (ej: \\\\servidor\\cola)"
        )
    # Separar host y share (después de \\)
    parts = value[2:].split('\\', 1)
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ValueError(
            f"UNC path inválido: '{value}'. Formato requerido: \\\\host\\recurso"
        )
    host = parts[0]
    # Validar que el host no tenga espacios
    if ' ' in host:
        raise ValueError(
            f"UNC path inválido: '{value}'. El host '{host}' no puede contener espacios. "
            "Debe ser un hostname, FQDN o dirección IP válida."
        )
    # Validar formato de host (hostname, FQDN o IP)
    host_regex = re.compile(r'^[a-zA-Z0-9]([a-zA-Z0-9._-]*[a-zA-Z0-9])?$')
    if not host_regex.match(host):
        raise ValueError(
            f"UNC path inválido: '{value}'. El host '{host}' no es un hostname, FQDN o IP válido."
        )
    return value


def _validate_metadata_unc_paths(metadata: Optional[dict]) -> Optional[dict]:
    """Valida que los valores de metadata que sean UNC paths tengan formato correcto."""
    if metadata is None:
        return None
    for key, value in metadata.items():
        if not isinstance(value, str):
            continue
        # Si el valor comienza con \\ se asume que es un UNC path y se valida
        if value.startswith('\\\\'):
            _validate_unc_path(value)
    return metadata


class VLANCreate(BaseModel):
    """Schema para crear una VLAN."""
    organization_id: Optional[UUID] = Field(None, description="ID de la organización (opcional para operadores)")
    name: str = Field(..., min_length=1, max_length=255, description="Nombre de la VLAN")
    description: Optional[str] = Field(None, max_length=1000, description="Descripción de la VLAN")
    cidr_ranges: list[str] = Field(..., min_length=1, description="Rangos CIDR (ej: ['192.168.1.0/24'])")
    metadata: Optional[dict] = Field(None, description="Metadatos arbitrarios (ej: remote_queue_path)")
    
    @field_validator("cidr_ranges")
    @classmethod
    def validate_cidr_ranges(cls, v: list[str]) -> list[str]:
        """Valida que todos los rangos CIDR sean válidos."""
        validated = []
        for cidr in v:
            try:
                # Valida que sea un CIDR válido
                ipaddress.ip_network(cidr, strict=False)
                validated.append(cidr)
            except ValueError:
                raise ValueError(f"CIDR inválido: {cidr}")
        return validated

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, v: Optional[dict]) -> Optional[dict]:
        """Valida UNC paths en metadata."""
        return _validate_metadata_unc_paths(v)


class VLANUpdate(BaseModel):
    """Schema para actualizar una VLAN."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    cidr_ranges: Optional[list[str]] = Field(None, min_length=1)
    metadata: Optional[dict] = Field(None, description="Metadatos arbitrarios (ej: remote_queue_path)")
    action_config_mandatory: Optional[bool] = Field(None, description="Si la action config de VLAN es obligatoria para sus workstations")
    
    @field_validator("cidr_ranges")
    @classmethod
    def validate_cidr_ranges(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        """Valida que todos los rangos CIDR sean válidos."""
        if v is None:
            return None
        validated = []
        for cidr in v:
            try:
                ipaddress.ip_network(cidr, strict=False)
                validated.append(cidr)
            except ValueError:
                raise ValueError(f"CIDR inválido: {cidr}")
        return validated

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, v: Optional[dict]) -> Optional[dict]:
        """Valida UNC paths en metadata."""
        return _validate_metadata_unc_paths(v)


class VLANResponse(BaseModel):
    """Schema de respuesta para VLAN."""
    id: UUID
    organization_id: UUID
    name: str
    description: Optional[str] = None
    cidr_ranges: list[str]
    forced_contingency: bool = False
    default_device_id: Optional[UUID] = None
    vlan_metadata: Optional[dict] = Field(None, serialization_alias="metadata")
    action_config_mandatory: bool = False
    created_at: datetime
    updated_at: datetime
    
    model_config = {"from_attributes": True, "populate_by_name": True}


class VLANDetailResponse(VLANResponse):
    """Schema de respuesta detallada para VLAN (incluye conteo de workstations)."""
    workstation_count: int = Field(0, description="Número de workstations en esta VLAN")
    
    model_config = {"from_attributes": True, "populate_by_name": True}


class VLANListStats(BaseModel):
    """Estadísticas calculadas del listado de VLANs."""
    without_devices: int = Field(0, description="VLANs sin dispositivos activos")
    with_config: int = Field(0, description="VLANs con metadata/config")
    in_contingency: int = Field(0, description="VLANs con contingencia forzada")


class VLANListResponse(BaseModel):
    """Schema de respuesta para lista de VLANs."""
    total: int
    vlans: list[VLANResponse]
    stats: Optional[VLANListStats] = None
