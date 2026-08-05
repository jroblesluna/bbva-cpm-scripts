"""
Endpoints de asociación entre perfiles de debugging y artículos de conocimiento.

Permite asociar, desasociar y listar artículos de conocimiento vinculados
a un perfil de debugging específico. La validación de tenant isolation
garantiza que tanto el perfil como los artículos pertenezcan a la misma organización.
"""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.debugging import DebuggingProfile
from app.models.user import User
from app.schemas.knowledge_article import KnowledgeArticleListItem, ProfileArticleAssociation
from app.services.knowledge_article import KnowledgeArticleService

router = APIRouter()

# Instancia del servicio
_service = KnowledgeArticleService()


# === HELPERS ===


def _get_profile_or_404(db: Session, profile_id: UUID, org_id: UUID) -> DebuggingProfile:
    """
    Obtiene un perfil verificando que pertenece a la organización del usuario.
    Retorna 404 si no existe o pertenece a otra organización (tenant isolation).
    """
    profile = db.query(DebuggingProfile).filter(
        DebuggingProfile.id == profile_id,
        DebuggingProfile.organization_id == org_id,
    ).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    return profile


# === ENDPOINTS DE ASOCIACIÓN ===


@router.post(
    "/debugging-profiles/{profile_id}/knowledge-articles",
    status_code=status.HTTP_201_CREATED,
    summary="Asociar artículos de conocimiento a un perfil",
)
async def associate_articles(
    profile_id: UUID,
    body: ProfileArticleAssociation,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Asocia una lista de artículos de conocimiento a un perfil de debugging.

    - Verifica que el perfil pertenece a la organización del usuario
    - Verifica que todos los artículos pertenecen a la misma organización
    - Ignora duplicados silenciosamente (no genera error)
    - Retorna 404 si algún artículo no existe o es de otra organización
    - Retorna 409 si se excede el límite de 10 artículos por perfil
    """
    org_id = current_user.organization_id

    # Verificar que el perfil existe y pertenece a la org del usuario
    profile = _get_profile_or_404(db, profile_id, org_id)

    # Intentar asociar artículos
    try:
        _service.associate_articles_to_profile(
            db=db,
            profile=profile,
            article_ids=body.article_ids,
            org_id=org_id,
        )
    except LookupError as e:
        # Artículo no encontrado o de otra organización
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        # Límite de artículos por perfil alcanzado
        raise HTTPException(status_code=409, detail=str(e))

    return {"message": "Artículos asociados exitosamente"}


@router.delete(
    "/debugging-profiles/{profile_id}/knowledge-articles/{article_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Desasociar un artículo de conocimiento de un perfil",
)
async def remove_article(
    profile_id: UUID,
    article_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Elimina la asociación entre un artículo y un perfil de debugging.

    - Verifica que el perfil pertenece a la organización del usuario
    - Si la asociación no existe, no genera error (operación idempotente)
    """
    org_id = current_user.organization_id

    # Verificar que el perfil existe y pertenece a la org del usuario
    _get_profile_or_404(db, profile_id, org_id)

    # Eliminar asociación (silencioso si no existe)
    _service.remove_article_from_profile(db=db, profile_id=profile_id, article_id=article_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/debugging-profiles/{profile_id}/knowledge-articles",
    response_model=List[KnowledgeArticleListItem],
    summary="Listar artículos de conocimiento asociados a un perfil",
)
async def list_profile_articles(
    profile_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Retorna todos los artículos de conocimiento asociados a un perfil.

    - Verifica que el perfil pertenece a la organización del usuario
    - Retorna lista resumida (sin contenido completo) de artículos asociados
    """
    org_id = current_user.organization_id

    # Verificar que el perfil existe y pertenece a la org del usuario
    _get_profile_or_404(db, profile_id, org_id)

    # Obtener artículos asociados
    articles = _service.get_articles_for_profile(db=db, profile_id=profile_id, org_id=org_id)

    return articles
