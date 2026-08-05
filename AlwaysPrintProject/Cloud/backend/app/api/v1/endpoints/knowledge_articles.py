"""
Endpoints CRUD para gestión de artículos de conocimiento.

Los artículos almacenan documentación técnica en Markdown que se inyecta
como contexto adicional en el prompt del LLM durante el análisis de debugging.
"""

import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.knowledge_article import (
    KnowledgeArticleCreate,
    KnowledgeArticleUpdate,
    KnowledgeArticleResponse,
    KnowledgeArticleListItem,
)
from app.services.knowledge_article import KnowledgeArticleService

logger = logging.getLogger(__name__)

router = APIRouter()

# Instancia del servicio de artículos de conocimiento
kb_service = KnowledgeArticleService()


@router.post(
    "/knowledge-articles",
    response_model=KnowledgeArticleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear artículo de conocimiento",
)
def create_article(
    data: KnowledgeArticleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Crea un nuevo artículo de conocimiento para la organización del usuario.

    Retorna HTTP 409 si se alcanzó el límite de artículos por organización.
    """
    org_id = current_user.organization_id
    try:
        article = kb_service.create_article(
            db=db,
            org_id=org_id,
            title=data.title,
            description=data.description,
            content=data.content,
        )
    except ValueError as e:
        # Límite de artículos por organización alcanzado
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    return article


@router.get(
    "/knowledge-articles",
    response_model=List[KnowledgeArticleListItem],
    summary="Listar artículos de conocimiento",
)
def list_articles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Lista todos los artículos de conocimiento de la organización del usuario.

    Retorna una lista resumida (sin contenido completo) ordenada por fecha
    de actualización descendente.
    """
    org_id = current_user.organization_id
    articles = kb_service.list_articles(db=db, org_id=org_id)
    return articles


@router.get(
    "/knowledge-articles/{article_id}",
    response_model=KnowledgeArticleResponse,
    summary="Obtener detalle de artículo",
)
def get_article(
    article_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Obtiene el detalle completo de un artículo de conocimiento.

    Retorna HTTP 404 si el artículo no existe o pertenece a otra organización.
    """
    org_id = current_user.organization_id
    article = kb_service.get_article(db=db, article_id=article_id, org_id=org_id)
    if article is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artículo no encontrado",
        )
    return article


@router.put(
    "/knowledge-articles/{article_id}",
    response_model=KnowledgeArticleResponse,
    summary="Actualizar artículo de conocimiento",
)
def update_article(
    article_id: UUID,
    data: KnowledgeArticleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Actualiza los campos de un artículo de conocimiento existente.

    Solo se actualizan los campos proporcionados (actualización parcial).
    Retorna HTTP 404 si el artículo no existe o pertenece a otra organización.
    """
    org_id = current_user.organization_id
    article = kb_service.get_article(db=db, article_id=article_id, org_id=org_id)
    if article is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artículo no encontrado",
        )
    updated = kb_service.update_article(
        db=db,
        article=article,
        title=data.title,
        description=data.description,
        content=data.content,
    )
    return updated


@router.delete(
    "/knowledge-articles/{article_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar artículo de conocimiento",
)
def delete_article(
    article_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Elimina un artículo de conocimiento y todas sus asociaciones a perfiles.

    Retorna HTTP 404 si el artículo no existe o pertenece a otra organización.
    """
    org_id = current_user.organization_id
    article = kb_service.get_article(db=db, article_id=article_id, org_id=org_id)
    if article is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artículo no encontrado",
        )
    kb_service.delete_article(db=db, article=article)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
