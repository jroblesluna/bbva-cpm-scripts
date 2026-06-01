"""
Schemas Pydantic para documentos del sistema.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field


# === SCHEMAS DE REQUEST ===

class DocumentCreate(BaseModel):
    """Schema para crear un documento (título y descripción; el archivo se sube aparte)."""
    title: str = Field(..., min_length=1, max_length=500, description="Título del documento")
    description: Optional[str] = Field(None, max_length=2000, description="Descripción del documento")


class DocumentUpdate(BaseModel):
    """Schema para actualizar un documento existente."""
    title: Optional[str] = Field(None, min_length=1, max_length=500, description="Nuevo título")
    description: Optional[str] = Field(None, max_length=2000, description="Nueva descripción")


# === SCHEMAS DE RESPONSE ===

class DocumentInfo(BaseModel):
    """Schema con información del documento."""
    id: UUID
    title: str
    description: Optional[str] = None
    file_name: str
    file_size: int
    download_url: str
    created_by_id: Optional[UUID] = None
    created_by_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    """Schema para listado paginado de documentos."""
    items: list[DocumentInfo]
    total: int
    page: int
    page_size: int
