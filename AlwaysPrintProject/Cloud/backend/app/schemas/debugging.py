"""
Schemas Pydantic para capturas de debugging a nivel de organización.

Incluye schemas para perfiles (CRUD), sesiones (lifecycle), y validadores
para los targets de monitoreo y parámetros de captura.
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field, field_validator, model_validator


# === CONSTANTES DE VALIDACIÓN ===

VALID_EVENTLOG_GROUPS = {"System", "Application", "Security"}
MIN_DURATION_SECONDS = 15
MAX_DURATION_SECONDS = 300
DEFAULT_DURATION_SECONDS = 60


# === SCHEMAS DE REQUEST — PERFILES ===

class DebuggingProfileCreate(BaseModel):
    """Schema para crear un perfil de debugging."""

    external_logs: List[str] = Field(
        default=[],
        description="Rutas absolutas o patrones glob de logs externos a monitorear"
    )
    eventlog_groups: List[str] = Field(
        default=[],
        description="Grupos de eventos Windows: System, Application, Security"
    )
    registry_keys: List[str] = Field(
        default=[],
        description="Llaves de registro Windows a monitorear (single level)"
    )
    monitored_services: List[str] = Field(
        default=[],
        description="Nombres de servicios Windows a monitorear"
    )
    description: str = Field(
        ..., min_length=10, max_length=2000,
        description="Descripción de qué se monitorea y el objetivo del debugging"
    )

    @field_validator('eventlog_groups', mode='before')
    @classmethod
    def validate_eventlog_groups(cls, v):
        """Validar que solo se usen grupos de eventos permitidos."""
        if not isinstance(v, list):
            raise ValueError("eventlog_groups debe ser una lista")
        for group in v:
            if group not in VALID_EVENTLOG_GROUPS:
                raise ValueError(
                    f"Grupo de eventos inválido: '{group}'. "
                    f"Permitidos: {sorted(VALID_EVENTLOG_GROUPS)}"
                )
        return v

    @field_validator('external_logs', mode='before')
    @classmethod
    def validate_external_logs(cls, v):
        """Validar que las rutas no estén vacías."""
        if not isinstance(v, list):
            raise ValueError("external_logs debe ser una lista")
        for path in v:
            if not path or not path.strip():
                raise ValueError("Las rutas de log no pueden estar vacías")
        return [p.strip() for p in v]

    @field_validator('registry_keys', mode='before')
    @classmethod
    def validate_registry_keys(cls, v):
        """Validar formato básico de llaves de registro."""
        if not isinstance(v, list):
            raise ValueError("registry_keys debe ser una lista")
        for key in v:
            if not key or not key.strip():
                raise ValueError("Las llaves de registro no pueden estar vacías")
            # Validar que comience con un root key válido
            valid_roots = ("HKLM", "HKCU", "HKCR", "HKU", "HKCC")
            if not any(key.strip().upper().startswith(root) for root in valid_roots):
                raise ValueError(
                    f"Llave de registro inválida: '{key}'. "
                    f"Debe comenzar con: {', '.join(valid_roots)}"
                )
        return [k.strip() for k in v]

    @field_validator('monitored_services', mode='before')
    @classmethod
    def validate_monitored_services(cls, v):
        """Validar que los nombres de servicio no estén vacíos."""
        if not isinstance(v, list):
            raise ValueError("monitored_services debe ser una lista")
        for svc in v:
            if not svc or not svc.strip():
                raise ValueError("Los nombres de servicio no pueden estar vacíos")
        return [s.strip() for s in v]

    @model_validator(mode='after')
    def validate_at_least_one_target(self):
        """Verificar que al menos un target de monitoreo está definido."""
        has_targets = (
            len(self.external_logs) > 0
            or len(self.eventlog_groups) > 0
            or len(self.registry_keys) > 0
            or len(self.monitored_services) > 0
        )
        if not has_targets:
            raise ValueError(
                "Debe definir al menos un target de monitoreo: "
                "external_logs, eventlog_groups, registry_keys, o monitored_services"
            )
        return self

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "external_logs": ["C:\\ProgramData\\LPMC\\Logs\\*.log"],
                "eventlog_groups": ["System", "Application"],
                "registry_keys": ["HKLM\\SOFTWARE\\Lexmark\\UniversalPrintDriver"],
                "monitored_services": ["Spooler", "LPDSVC", "lpmc_universal_service"],
                "description": "Monitoreo de servicios de impresión y logs del driver Lexmark para diagnóstico de problemas de cola de impresión"
            }]
        }
    }


class DebuggingProfileUpdate(BaseModel):
    """Schema para actualizar un perfil de debugging existente."""

    external_logs: Optional[List[str]] = None
    eventlog_groups: Optional[List[str]] = None
    registry_keys: Optional[List[str]] = None
    monitored_services: Optional[List[str]] = None
    description: Optional[str] = Field(None, min_length=10, max_length=2000)
    is_active: Optional[bool] = None

    @field_validator('eventlog_groups', mode='before')
    @classmethod
    def validate_eventlog_groups(cls, v):
        """Validar grupos de eventos si se proporcionan."""
        if v is None:
            return v
        if not isinstance(v, list):
            raise ValueError("eventlog_groups debe ser una lista")
        for group in v:
            if group not in VALID_EVENTLOG_GROUPS:
                raise ValueError(
                    f"Grupo de eventos inválido: '{group}'. "
                    f"Permitidos: {sorted(VALID_EVENTLOG_GROUPS)}"
                )
        return v

    @field_validator('external_logs', mode='before')
    @classmethod
    def validate_external_logs(cls, v):
        """Validar rutas si se proporcionan."""
        if v is None:
            return v
        if not isinstance(v, list):
            raise ValueError("external_logs debe ser una lista")
        for path in v:
            if not path or not path.strip():
                raise ValueError("Las rutas de log no pueden estar vacías")
        return [p.strip() for p in v]

    @field_validator('registry_keys', mode='before')
    @classmethod
    def validate_registry_keys(cls, v):
        """Validar llaves de registro si se proporcionan."""
        if v is None:
            return v
        if not isinstance(v, list):
            raise ValueError("registry_keys debe ser una lista")
        for key in v:
            if not key or not key.strip():
                raise ValueError("Las llaves de registro no pueden estar vacías")
            valid_roots = ("HKLM", "HKCU", "HKCR", "HKU", "HKCC")
            if not any(key.strip().upper().startswith(root) for root in valid_roots):
                raise ValueError(
                    f"Llave de registro inválida: '{key}'. "
                    f"Debe comenzar con: {', '.join(valid_roots)}"
                )
        return [k.strip() for k in v]

    @field_validator('monitored_services', mode='before')
    @classmethod
    def validate_monitored_services(cls, v):
        """Validar nombres de servicio si se proporcionan."""
        if v is None:
            return v
        if not isinstance(v, list):
            raise ValueError("monitored_services debe ser una lista")
        for svc in v:
            if not svc or not svc.strip():
                raise ValueError("Los nombres de servicio no pueden estar vacíos")
        return [s.strip() for s in v]

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "monitored_services": ["Spooler", "LPDSVC"],
                "is_active": False
            }]
        }
    }


class DebuggingProfileConfirmSave(BaseModel):
    """Schema para confirmar el guardado con nombre y mensaje (tras sugerencia LLM)."""

    name: str = Field(
        ..., min_length=3, max_length=60,
        description="Nombre del perfil (sugerido por LLM, editable por admin)"
    )
    confirmation_message: str = Field(
        ..., min_length=10, max_length=200,
        description="Mensaje de confirmación al iniciar (sugerido por LLM, editable)"
    )


# === SCHEMAS DE REQUEST — SESIONES ===

class DebuggingSessionCreate(BaseModel):
    """Schema para iniciar una sesión de debugging en una workstation."""

    profile_id: UUID = Field(..., description="ID del perfil de debugging a ejecutar")
    workstation_id: UUID = Field(..., description="ID de la workstation objetivo")
    duration_seconds: int = Field(
        default=DEFAULT_DURATION_SECONDS,
        ge=MIN_DURATION_SECONDS,
        le=MAX_DURATION_SECONDS,
        description=f"Duración de la captura ({MIN_DURATION_SECONDS}-{MAX_DURATION_SECONDS}s, default {DEFAULT_DURATION_SECONDS}s)"
    )
    motivo: Optional[str] = Field(
        None, max_length=500,
        description="Motivo por el que se solicita el debugging (para contexto LLM)"
    )
    additional_instructions: Optional[str] = Field(
        None, max_length=2000,
        description="Instrucciones adicionales para guiar el análisis del LLM"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "profile_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "workstation_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
                "duration_seconds": 60,
                "motivo": "La workstation reporta que el servicio Spooler se reinicia frecuentemente",
                "additional_instructions": "Verificar si hay conflicto entre LPMC y Spooler al reiniciarse"
            }]
        }
    }


# === SCHEMAS DE RESPONSE ===

class DebuggingProfileResponse(BaseModel):
    """Schema de respuesta con información completa del perfil."""

    id: UUID
    organization_id: UUID
    name: str
    description: str
    confirmation_message: str
    external_logs: List[str]
    eventlog_groups: List[str]
    registry_keys: List[str]
    monitored_services: List[str]
    is_active: bool
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DebuggingProfileListItem(BaseModel):
    """Schema resumido para listados de perfiles."""

    id: UUID
    name: str
    description: str
    confirmation_message: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class DebuggingSessionResponse(BaseModel):
    """Schema de respuesta con información completa de la sesión."""

    id: UUID  # Este es el debugging_id
    organization_id: UUID
    profile_id: Optional[UUID] = None
    workstation_id: UUID
    status: str
    duration_seconds: int
    start_time: datetime
    end_time: Optional[datetime] = None
    motivo: Optional[str] = None
    additional_instructions: Optional[str] = None
    total_data_size_bytes: Optional[int] = None
    s3_report_key: Optional[str] = None
    initiated_by: Optional[UUID] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DebuggingSessionListItem(BaseModel):
    """Schema resumido para listados de sesiones."""

    id: UUID
    profile_id: Optional[UUID] = None
    workstation_id: UUID
    status: str
    duration_seconds: int
    start_time: datetime
    end_time: Optional[datetime] = None
    total_data_size_bytes: Optional[int] = None
    initiated_by: Optional[UUID] = None

    model_config = {"from_attributes": True}


# === SCHEMAS DE LLM SUGGESTION ===

class LLMProfileSuggestion(BaseModel):
    """Schema para la sugerencia del LLM al crear/editar un perfil."""

    suggested_name: str = Field(
        ..., max_length=60,
        description="Nombre sugerido por el LLM para el perfil"
    )
    suggested_message: str = Field(
        ..., max_length=200,
        description="Mensaje de confirmación sugerido por el LLM"
    )


# === SCHEMAS AUXILIARES ===

class DebuggingReportURL(BaseModel):
    """Schema para la URL de descarga del reporte PDF."""

    report_url: str = Field(..., description="URL presigned de S3 para descargar el PDF")
    expires_in_seconds: int = Field(
        default=3600,
        description="Tiempo de expiración de la URL en segundos"
    )
