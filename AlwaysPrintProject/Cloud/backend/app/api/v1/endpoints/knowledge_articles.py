"""
Endpoints CRUD para gestión de artículos de conocimiento.

Los artículos almacenan documentación técnica en Markdown que se inyecta
como contexto adicional en el prompt del LLM durante el análisis de debugging.
"""

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User, UserRole
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


def _resolve_org_id(current_user: User, explicit_org_id: Optional[UUID] = None) -> UUID:
    """
    Resuelve la organización del usuario:
    - Admin con org_id explícito → usa el explícito
    - Operador con organization_id asignado → usa el propio
    - Sin organización determinable → HTTP 400
    """
    if explicit_org_id and current_user.role == UserRole.ADMIN:
        return explicit_org_id
    elif current_user.organization_id:
        return current_user.organization_id
    elif explicit_org_id:
        return explicit_org_id
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo determinar la organización. Proporcione organization_id.",
        )


@router.post(
    "/knowledge-articles",
    response_model=KnowledgeArticleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear artículo de conocimiento",
)
def create_article(
    data: KnowledgeArticleCreate,
    organization_id: Optional[UUID] = Query(None, description="ID de la organización (requerido para Admin)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Crea un nuevo artículo de conocimiento para la organización.

    Retorna HTTP 409 si se alcanzó el límite de artículos por organización.
    """
    org_id = _resolve_org_id(current_user, organization_id)
    try:
        article = kb_service.create_article(
            db=db,
            org_id=org_id,
            title=data.title,
            description=data.description,
            content=data.content,
        )
    except ValueError as e:
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
    organization_id: Optional[UUID] = Query(None, description="ID de la organización (requerido para Admin)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Lista todos los artículos de conocimiento de la organización.

    Retorna una lista resumida (sin contenido completo) ordenada por fecha
    de actualización descendente.
    """
    org_id = _resolve_org_id(current_user, organization_id)
    articles = kb_service.list_articles(db=db, org_id=org_id)
    return articles


@router.get(
    "/knowledge-articles/{article_id}",
    response_model=KnowledgeArticleResponse,
    summary="Obtener detalle de artículo",
)
def get_article(
    article_id: UUID,
    organization_id: Optional[UUID] = Query(None, description="ID de la organización (requerido para Admin)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Obtiene el detalle completo de un artículo de conocimiento.

    Retorna HTTP 404 si el artículo no existe o pertenece a otra organización.
    """
    org_id = _resolve_org_id(current_user, organization_id)
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
    organization_id: Optional[UUID] = Query(None, description="ID de la organización (requerido para Admin)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Actualiza los campos de un artículo de conocimiento existente.

    Solo se actualizan los campos proporcionados (actualización parcial).
    Retorna HTTP 404 si el artículo no existe o pertenece a otra organización.
    """
    org_id = _resolve_org_id(current_user, organization_id)
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
    organization_id: Optional[UUID] = Query(None, description="ID de la organización (requerido para Admin)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Elimina un artículo de conocimiento y todas sus asociaciones a perfiles.

    Retorna HTTP 404 si el artículo no existe o pertenece a otra organización.
    """
    org_id = _resolve_org_id(current_user, organization_id)
    article = kb_service.get_article(db=db, article_id=article_id, org_id=org_id)
    if article is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artículo no encontrado",
        )
    kb_service.delete_article(db=db, article=article)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
