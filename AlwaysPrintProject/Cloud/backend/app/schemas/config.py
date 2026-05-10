"""
Schemas Pydantic para configuración jerárquica.

Este módulo define los schemas de validación para los tres niveles de configuración:
- GlobalConfig: configuración a nivel de cuenta
- VLANConfig: configuración a nivel de VLAN
- WorkstationConfig: configuración a nivel de estación
"""

from datetime import datetime
from typing import Optional, Literal
from uuid import UUID
from pydantic import BaseModel, Field, field_validator


# === SCHEMAS DE CONFIGURACIÓN GLOBAL ===

class GlobalConfigUpdate(BaseModel):
    """Schema para actualizar configuración global."""
    corporate_queue_name: Optional[str] = Field(None, min_length=1, max_length=255, description="Nombre de la cola corporativa")
    search_targets: Optional[dict] = Field(None, description="Objetivos de búsqueda de impresoras")
    pending_task_polling_minutes: Optional[int] = Field(None, ge=1, le=1440, description="Intervalo de polling (1-1440 minutos)")
    bootstrap_domains: Optional[str] = Field(None, max_length=1000, description="Dominios de bootstrap separados por comas")
    
    @field_validator("search_targets")
    @classmethod
    def validate_search_targets(cls, v: Optional[dict]) -> Optional[dict]:
        """Valida que search_targets tenga la estructura correcta."""
        if v is None:
            return None
        # Debe tener al menos una de las claves: ips, ranges
        if not isinstance(v, dict):
            raise ValueError("search_targets debe ser un diccionario")
        if "ips" not in v and "ranges" not in v:
            raise ValueError("search_targets debe contener al menos 'ips' o 'ranges'")
        return v


class GlobalConfigResponse(BaseModel):
    """Schema de respuesta para configuración global."""
    id: Optional[UUID] = None  # None indica que no existe en BD (valores por defecto)
    account_id: UUID
    corporate_queue_name: str
    search_targets: Optional[dict] = None
    pending_task_polling_minutes: int
    bootstrap_domains: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# === SCHEMAS DE CONFIGURACIÓN DE VLAN ===

class VLANConfigUpdate(BaseModel):
    """Schema para actualizar configuración de VLAN (override selectivo)."""
    corporate_queue_name: Optional[str] = Field(None, min_length=1, max_length=255)
    search_targets: Optional[dict] = None
    pending_task_polling_minutes: Optional[int] = Field(None, ge=1, le=1440)
    bootstrap_domains: Optional[str] = Field(None, max_length=1000)
    
    @field_validator("search_targets")
    @classmethod
    def validate_search_targets(cls, v: Optional[dict]) -> Optional[dict]:
        """Valida que search_targets tenga la estructura correcta."""
        if v is None:
            return None
        if not isinstance(v, dict):
            raise ValueError("search_targets debe ser un diccionario")
        if "ips" not in v and "ranges" not in v:
            raise ValueError("search_targets debe contener al menos 'ips' o 'ranges'")
        return v


class VLANConfigResponse(BaseModel):
    """Schema de respuesta para configuración de VLAN."""
    id: UUID
    vlan_id: UUID
    corporate_queue_name: Optional[str] = None
    search_targets: Optional[dict] = None
    pending_task_polling_minutes: Optional[int] = None
    bootstrap_domains: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# === SCHEMAS DE CONFIGURACIÓN DE WORKSTATION ===

class WorkstationConfigUpdate(BaseModel):
    """Schema para actualizar configuración de workstation (override selectivo)."""
    corporate_queue_name: Optional[str] = Field(None, min_length=1, max_length=255)
    search_targets: Optional[dict] = None
    pending_task_polling_minutes: Optional[int] = Field(None, ge=1, le=1440)
    bootstrap_domains: Optional[str] = Field(None, max_length=1000)
    
    @field_validator("search_targets")
    @classmethod
    def validate_search_targets(cls, v: Optional[dict]) -> Optional[dict]:
        """Valida que search_targets tenga la estructura correcta."""
        if v is None:
            return None
        if not isinstance(v, dict):
            raise ValueError("search_targets debe ser un diccionario")
        if "ips" not in v and "ranges" not in v:
            raise ValueError("search_targets debe contener al menos 'ips' o 'ranges'")
        return v


class WorkstationConfigResponse(BaseModel):
    """Schema de respuesta para configuración de workstation."""
    id: UUID
    workstation_id: UUID
    corporate_queue_name: Optional[str] = None
    search_targets: Optional[dict] = None
    pending_task_polling_minutes: Optional[int] = None
    bootstrap_domains: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# === SCHEMA DE CONFIGURACIÓN EFECTIVA ===

class EffectiveConfigResponse(BaseModel):
    """
    Schema de respuesta para configuración efectiva (resuelta).
    
    Incluye los valores finales después de aplicar la jerarquía:
    WorkstationConfig > VLANConfig > GlobalConfig
    """
    corporate_queue_name: str
    search_targets: Optional[dict] = None
    pending_task_polling_minutes: int
    bootstrap_domains: str
    source: dict[str, Literal["global", "vlan", "workstation"]] = Field(
        ...,
        description="Origen de cada campo (global, vlan, workstation)"
    )
