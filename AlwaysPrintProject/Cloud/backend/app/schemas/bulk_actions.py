"""
Schemas Pydantic para ejecución masiva de acciones OnDemand.
"""

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# === SCHEMAS DE REQUEST ===


class BulkStartRequest(BaseModel):
    """Solicitud para iniciar ejecución masiva."""

    label: str = Field(..., min_length=1, max_length=255, description="Label de la acción OnDemand a ejecutar")
    delay_ms: int = Field(default=500, ge=50, le=10000, description="Delay en milisegundos entre envíos (50-10000)")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "label": "ResetPrinterQueues",
                "delay_ms": 500
            }]
        }
    }


class BulkPreviewRequest(BaseModel):
    """Solicitud de preview de ejecución masiva."""

    label: str = Field(..., min_length=1, max_length=255, description="Label de la acción OnDemand a previsualizar")
    delay_ms: int = Field(default=500, ge=50, le=10000, description="Delay en milisegundos entre envíos (50-10000)")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "label": "ResetPrinterQueues",
                "delay_ms": 500
            }]
        }
    }


# === SCHEMAS DE RESPONSE ===


class OnDemandAction(BaseModel):
    """Acción OnDemand disponible en el alwaysconfig activo."""

    label: str = Field(..., description="Identificador de la acción OnDemand")
    description: Optional[str] = Field(default=None, description="Descripción de la acción (si existe)")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "label": "ResetPrinterQueues",
                "description": "Reinicia las colas de impresión de la workstation"
            }]
        }
    }


class BulkPreview(BaseModel):
    """Respuesta de preview con información estimada de la ejecución masiva."""

    action_label: str = Field(..., description="Label de la acción OnDemand seleccionada")
    action_description: Optional[str] = Field(default=None, description="Descripción de la acción")
    workstations_online: int = Field(..., description="Número de workstations online en la organización")
    estimated_time_ms: int = Field(..., description="Tiempo estimado de ejecución: (workstations_online - 1) * delay_ms")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "action_label": "ResetPrinterQueues",
                "action_description": "Reinicia las colas de impresión de la workstation",
                "workstations_online": 150,
                "estimated_time_ms": 74500
            }]
        }
    }


class BulkSessionStatus(BaseModel):
    """Estado de una Bulk_Session con métricas de progreso."""

    session_id: UUID = Field(..., description="Identificador único de la sesión")
    status: Literal["running", "completed", "cancelled", "failed"] = Field(..., description="Estado actual de la sesión")
    total: int = Field(..., description="Total de workstations target")
    sent: int = Field(..., description="Cantidad de envíos completados")
    success: int = Field(..., description="Cantidad de envíos exitosos")
    errors: int = Field(..., description="Cantidad de envíos fallidos")
    failed_workstations: list[str] = Field(default=[], description="IDs de workstations donde falló el envío")
    started_at: datetime = Field(..., description="Timestamp de inicio de la sesión")
    elapsed_ms: Optional[int] = Field(default=None, description="Tiempo transcurrido en milisegundos")

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [{
                "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "status": "running",
                "total": 150,
                "sent": 45,
                "success": 43,
                "errors": 2,
                "failed_workstations": ["ws-001", "ws-042"],
                "started_at": "2026-06-10T10:30:00Z",
                "elapsed_ms": 22500
            }]
        }
    }


class BulkStartResponse(BaseModel):
    """Respuesta al iniciar ejecución masiva (HTTP 202)."""

    session_id: UUID = Field(..., description="Identificador único de la sesión creada")
    total: int = Field(..., description="Total de workstations online que serán procesadas")
    started_at: datetime = Field(..., description="Timestamp de inicio de la sesión")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "total": 150,
                "started_at": "2026-06-10T10:30:00Z"
            }]
        }
    }
