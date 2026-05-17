"""
Schemas Pydantic para configuración jerárquica.

Este módulo define los schemas de validación para los tres niveles de configuración:
- GlobalConfig: configuración a nivel de cuenta
- VLANConfig: configuración a nivel de VLAN
- WorkstationConfig: configuración a nivel de estación

Incluye ConnectivityCheckItem con validación condicional por tipo (HTTP/TCP/Ping/DNS)
y EffectiveConfigResponse con config_hash SHA-256.
"""

from datetime import datetime
from typing import Optional, Literal, List
from uuid import UUID
from pydantic import BaseModel, Field, field_validator, model_validator


# === SCHEMA DE CONNECTIVITY CHECK ===

class ConnectivityCheckItem(BaseModel):
    """
    Schema para un elemento de verificación de conectividad.
    
    Cada item define un endpoint a verificar con su tipo de protocolo.
    Los campos requeridos varían según el tipo:
    - http: requiere url
    - tcp: requiere host y port
    - ping: requiere host
    - dns: requiere hostname
    
    Campos no aplicables al tipo seleccionado se ignoran sin error.
    """
    id: str = Field(..., max_length=64, description="Identificador único del check (máx 64 caracteres)")
    type: Literal["http", "tcp", "ping", "dns"] = Field(..., description="Tipo de protocolo: http, tcp, ping o dns")
    url: Optional[str] = Field(None, max_length=2048, description="URL destino del check (requerido para tipo http)")
    host: Optional[str] = Field(None, max_length=255, description="Host destino (requerido para tipo tcp y ping)")
    hostname: Optional[str] = Field(None, max_length=255, description="Nombre de host DNS (requerido para tipo dns)")
    port: Optional[int] = Field(None, ge=1, le=65535, description="Puerto destino (requerido para tipo tcp)")
    timeout_ms: int = Field(5000, ge=100, le=30000, description="Timeout en milisegundos (100-30000, default 5000)")

    @model_validator(mode="after")
    def validate_type_fields(self) -> "ConnectivityCheckItem":
        """Valida que los campos requeridos estén presentes según el tipo seleccionado."""
        if self.type == "http" and not self.url:
            raise ValueError("Campo 'url' requerido para tipo 'http'")
        if self.type == "tcp" and (not self.host or self.port is None):
            raise ValueError("Campos 'host' y 'port' requeridos para tipo 'tcp'")
        if self.type == "ping" and not self.host:
            raise ValueError("Campo 'host' requerido para tipo 'ping'")
        if self.type == "dns" and not self.hostname:
            raise ValueError("Campo 'hostname' requerido para tipo 'dns'")
        return self


# === SCHEMAS DE CONFIGURACIÓN GLOBAL ===

class GlobalConfigUpdate(BaseModel):
    """Schema para actualizar configuración global."""
    corporate_queue_name: Optional[str] = Field(None, min_length=1, max_length=255, description="Nombre de la cola corporativa")
    search_targets: Optional[dict] = Field(None, description="Objetivos de búsqueda de impresoras")
    pending_task_polling_minutes: Optional[int] = Field(None, ge=1, le=1440, description="Intervalo de polling (1-1440 minutos)")
    bootstrap_domains: Optional[str] = Field(None, max_length=1000, description="Dominios de bootstrap separados por comas")
    connectivity_checks: Optional[List[ConnectivityCheckItem]] = Field(
        None,
        max_length=50,
        description="Lista de verificaciones de conectividad (máximo 50 elementos)"
    )
    locale: Optional[str] = Field(None, max_length=10, description="Locale para override de idioma (máx 10 caracteres)")
    telemetry_enabled: Optional[bool] = Field(None, description="Indica si la telemetría está habilitada")
    telemetry_interval_seconds: Optional[int] = Field(
        None, ge=10, le=86400, description="Intervalo de envío de telemetría en segundos (10-86400)"
    )
    
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
    organization_id: UUID
    corporate_queue_name: str
    search_targets: Optional[dict] = None
    pending_task_polling_minutes: int
    bootstrap_domains: str
    created_at: datetime
    updated_at: datetime
    
    model_config = {"from_attributes": True}


# === SCHEMAS DE CONFIGURACIÓN DE VLAN ===

class VLANConfigUpdate(BaseModel):
    """Schema para actualizar configuración de VLAN (override selectivo)."""
    corporate_queue_name: Optional[str] = Field(None, min_length=1, max_length=255)
    search_targets: Optional[dict] = None
    pending_task_polling_minutes: Optional[int] = Field(None, ge=1, le=1440)
    bootstrap_domains: Optional[str] = Field(None, max_length=1000)
    connectivity_checks: Optional[List[ConnectivityCheckItem]] = Field(
        None,
        max_length=50,
        description="Lista de verificaciones de conectividad (máximo 50 elementos)"
    )
    locale: Optional[str] = Field(None, max_length=10, description="Locale para override de idioma (máx 10 caracteres)")
    telemetry_enabled: Optional[bool] = Field(None, description="Indica si la telemetría está habilitada")
    telemetry_interval_seconds: Optional[int] = Field(
        None, ge=10, le=86400, description="Intervalo de envío de telemetría en segundos (10-86400)"
    )
    
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
    
    model_config = {"from_attributes": True}


# === SCHEMAS DE CONFIGURACIÓN DE WORKSTATION ===

class WorkstationConfigUpdate(BaseModel):
    """Schema para actualizar configuración de workstation (override selectivo)."""
    corporate_queue_name: Optional[str] = Field(None, min_length=1, max_length=255)
    search_targets: Optional[dict] = None
    pending_task_polling_minutes: Optional[int] = Field(None, ge=1, le=1440)
    bootstrap_domains: Optional[str] = Field(None, max_length=1000)
    connectivity_checks: Optional[List[ConnectivityCheckItem]] = Field(
        None,
        max_length=50,
        description="Lista de verificaciones de conectividad (máximo 50 elementos)"
    )
    locale: Optional[str] = Field(None, max_length=10, description="Locale para override de idioma (máx 10 caracteres)")
    telemetry_enabled: Optional[bool] = Field(None, description="Indica si la telemetría está habilitada")
    telemetry_interval_seconds: Optional[int] = Field(
        None, ge=10, le=86400, description="Intervalo de envío de telemetría en segundos (10-86400)"
    )
    
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
    
    model_config = {"from_attributes": True}


# === SCHEMA DE CONFIGURACIÓN EFECTIVA ===

class EffectiveConfigResponse(BaseModel):
    """
    Schema de respuesta para configuración efectiva (resuelta).
    
    Incluye los valores finales después de aplicar la jerarquía:
    WorkstationConfig > VLANConfig > GlobalConfig
    
    El campo config_hash es el SHA-256 del JSON serializado con sort_keys=True,
    excluyendo los campos 'source' y 'config_hash' del cómputo.
    Permite al Client C# detectar cambios sin comparar campo a campo.
    """
    corporate_queue_name: str
    search_targets: Optional[dict] = None
    pending_task_polling_minutes: int
    bootstrap_domains: str
    connectivity_checks: List[ConnectivityCheckItem] = Field(
        default_factory=list,
        max_length=50,
        description="Lista de verificaciones de conectividad (máximo 50 elementos)"
    )
    locale: str = Field(
        default="",
        max_length=10,
        description="Locale para override de idioma (máx 10 caracteres, ej: 'es', 'en', 'es-PE')"
    )
    telemetry_enabled: bool = Field(
        default=True,
        description="Indica si la telemetría está habilitada"
    )
    telemetry_interval_seconds: int = Field(
        default=300,
        ge=10,
        le=86400,
        description="Intervalo de envío de telemetría en segundos (10-86400)"
    )
    source: dict[str, Literal["global", "vlan", "workstation"]] = Field(
        ...,
        description="Origen de cada campo (global, vlan, workstation)"
    )
    config_hash: str = Field(
        ...,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
        description="Hash SHA-256 de la configuración efectiva (64 caracteres hexadecimales en minúsculas)"
    )
