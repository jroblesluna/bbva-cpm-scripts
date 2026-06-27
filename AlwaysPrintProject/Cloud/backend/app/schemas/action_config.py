"""
Schemas Pydantic para configuración de acciones administrativas.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field, field_validator
import hashlib


# === SCHEMAS DE REQUEST ===

class ActionConfigUpload(BaseModel):
    """Schema para subir una nueva configuración de acciones."""
    
    config_json: str = Field(..., description="JSON completo del archivo .alwaysconfig")
    is_active: bool = Field(default=True, description="Si la configuración debe estar activa")
    
    @field_validator('config_json')
    @classmethod
    def validate_json_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("config_json no puede estar vacío")
        return v
    
    model_config = {
        "json_schema_extra": {
            "examples": [{
                "config_json": '{"version": "1.0", "name": "CPM_Compliant", ...}',
                "is_active": True
            }]
        }
    }


class ActionConfigUpdate(BaseModel):
    """Schema para actualizar una configuración existente."""
    
    is_active: Optional[bool] = Field(None, description="Activar/desactivar propagación")
    
    model_config = {
        "json_schema_extra": {
            "examples": [{
                "is_active": False
            }]
        }
    }


# === SCHEMAS DE RESPONSE ===

class ActionConfigInfo(BaseModel):
    """Schema con información básica de la configuración (sin JSON completo)."""
    
    id: UUID
    organization_id: UUID
    name: str
    version: str
    description: Optional[str] = None
    config_hash: str
    is_active: bool
    scope: str = "org"
    vlan_id: Optional[UUID] = None
    workstation_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    created_by_id: Optional[UUID] = None
    
    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [{
                "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "organization_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
                "name": "CPM_Compliant",
                "version": "1.0",
                "description": "Configuración de cumplimiento para Lexmark CPM",
                "config_hash": "a3f5c8d2",
                "is_active": True,
                "created_at": "2026-05-15T15:00:00Z",
                "updated_at": "2026-05-15T15:00:00Z",
                "created_by_id": "c3d4e5f6-a7b8-9012-cdef-123456789012"
            }]
        }
    }


class ActionConfigDetail(ActionConfigInfo):
    """Schema con todos los detalles incluyendo el JSON completo."""
    
    config_json: str
    storage_path: Optional[str] = None


class ActionConfigDownloadInfo(BaseModel):
    """Schema con información para descargar la configuración."""
    
    hash: str = Field(..., description="Hash SHA256 corto (8 chars)")
    download_url: str = Field(..., description="URL relativa para descargar")
    name: str
    version: str
    cert_version: Optional[int] = Field(None, description="Versión del certificado ECDSA de la org (null si no tiene)")
    cert_url: Optional[str] = Field(None, description="URL pública del certificado .cer en S3 (null si no tiene)")
    
    model_config = {
        "json_schema_extra": {
            "examples": [{
                "hash": "a3f5c8d2",
                "download_url": "/api/v1/workstations/ws-123/config/download",
                "name": "CPM_Compliant",
                "version": "1.0",
                "cert_version": 1,
                "cert_url": "https://s3.amazonaws.com/bucket/certs/org-id/v1.cer"
            }]
        }
    }


class ActionConfigSyncStatus(BaseModel):
    """Schema con estado de sincronización de una workstation."""
    
    workstation_id: str
    has_config: bool = Field(..., description="Si la workstation tiene configuración local")
    local_hash: Optional[str] = Field(None, description="Hash de la configuración local")
    cloud_hash: Optional[str] = Field(None, description="Hash de la configuración en Cloud")
    is_synced: bool = Field(..., description="Si el hash local coincide con el de Cloud")
    
    model_config = {
        "json_schema_extra": {
            "examples": [{
                "workstation_id": "ws-abc123",
                "has_config": True,
                "local_hash": "a3f5c8d2",
                "cloud_hash": "a3f5c8d2",
                "is_synced": True
            }]
        }
    }


# === UTILIDADES ===

def calculate_config_hash(config_json: str) -> str:
    """
    Calcula el hash SHA256 de un JSON de configuración.
    Normaliza el JSON (parse + re-serialize compacto) antes de hashear para
    garantizar que el resultado sea determinístico independientemente del
    formato original (espacios, orden, etc.) y coincida con el hash del envelope firmado.
    Retorna los primeros 8 caracteres en hexadecimal minúsculas.
    """
    import json
    # Normalizar: parsear y re-serializar con formato compacto
    # Mismo formato que CryptoService.sign_config usa para calcular el hash
    config_obj = json.loads(config_json)
    normalized = json.dumps(config_obj, ensure_ascii=False, separators=(',', ':'))
    hash_obj = hashlib.sha256(normalized.encode('utf-8'))
    full_hash = hash_obj.hexdigest()
    return full_hash[:8]
