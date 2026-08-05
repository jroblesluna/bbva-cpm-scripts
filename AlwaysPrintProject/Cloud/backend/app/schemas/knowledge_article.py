"""
Schemas Pydantic para artículos de conocimiento.

Estos schemas validan la entrada/salida de la API de artículos técnicos
que se inyectan como contexto adicional en el prompt del LLM durante
el análisis de sesiones de debugging.
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field, field_validator


# === SCHEMAS DE REQUEST ===


class KnowledgeArticleCreate(BaseModel):
    """Schema para crear un artículo de conocimiento."""

    title: str = Field(
        ..., min_length=3, max_length=200, description="Título del artículo"
    )
    description: str = Field(
        ..., min_length=10, max_length=500, description="Descripción breve"
    )
    content: str = Field(
        ..., min_length=1, max_length=500_000, description="Contenido Markdown"
    )

    @field_validator("content")
    @classmethod
    def validate_content_not_empty(cls, v: str) -> str:
        """Validar que el contenido no sea solo espacios en blanco."""
        if not v.strip():
            raise ValueError("El contenido no puede estar vacío")
        return v


class KnowledgeArticleUpdate(BaseModel):
    """Schema para actualizar un artículo existente (campos opcionales)."""

    title: Optional[str] = Field(None, min_length=3, max_length=200)
    description: Optional[str] = Field(None, min_length=10, max_length=500)
    content: Optional[str] = Field(None, min_length=1, max_length=500_000)

    @field_validator("content")
    @classmethod
    def validate_content_not_empty(cls, v: Optional[str]) -> Optional[str]:
        """Validar que el contenido no sea solo espacios en blanco (si se proporciona)."""
        if v is not None and not v.strip():
            raise ValueError("El contenido no puede estar vacío")
        return v


# === SCHEMAS DE RESPONSE ===


class KnowledgeArticleResponse(BaseModel):
    """Schema de respuesta completa de un artículo."""

    id: UUID
    organization_id: UUID
    title: str
    description: str
    content: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class KnowledgeArticleListItem(BaseModel):
    """Schema resumido para listados (sin contenido completo)."""

    id: UUID
    title: str
    description: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# === SCHEMAS DE ASOCIACIÓN ===


class ProfileArticleAssociation(BaseModel):
    """Schema para asociar artículos a un perfil de debugging."""

    article_ids: List[UUID] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="Lista de IDs de artículos a asociar (máximo 10)",
    )
