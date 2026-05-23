"""
Schemas Pydantic para análisis de logs de workstations.

Define los schemas de respuesta para:
- LogAnalysisResponse: resultado completo de un análisis
- LogAnalysisTodayCheckResponse: verificación de análisis existente del día
- LogAnalysisListResponse: lista paginada de análisis
"""

from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# === SCHEMAS DE RESPONSE ===


class LogAnalysisResponse(BaseModel):
    """Schema de respuesta para un análisis de log individual."""

    id: UUID
    workstation_id: UUID
    organization_id: UUID
    analysis_date: date = Field(..., description="Fecha del análisis (día del log)")
    analysis_text: str = Field(..., description="Texto de respuesta del LLM con el análisis")
    processing_path: str = Field(
        ..., description="Ruta de procesamiento utilizada: 'direct' o 'structural'"
    )
    log_size_bytes: int = Field(..., description="Tamaño del log procesado en bytes")
    processing_duration_ms: int = Field(
        ..., description="Duración total del procesamiento en milisegundos"
    )
    original_filename: str = Field(..., description="Nombre original del archivo de log")
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LogAnalysisTodayCheckResponse(BaseModel):
    """Schema de respuesta para verificar si existe un análisis del día actual."""

    exists: bool = Field(..., description="Si existe un análisis para hoy")
    analysis_id: Optional[UUID] = Field(
        None, description="ID del análisis existente, None si no existe"
    )


class LogAnalysisListResponse(BaseModel):
    """Schema de respuesta para lista paginada de análisis de una workstation."""

    items: list[LogAnalysisResponse]
    total: int = Field(..., description="Total de análisis disponibles")
    page: int = Field(..., description="Página actual (1-based)")
    page_size: int = Field(..., description="Tamaño de página")
