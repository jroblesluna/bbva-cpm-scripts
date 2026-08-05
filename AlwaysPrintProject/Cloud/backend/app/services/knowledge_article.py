"""
Servicio de gestión de artículos de conocimiento.

Proporciona operaciones CRUD y gestión de asociaciones many-to-many
entre artículos de conocimiento y perfiles de debugging.
Los artículos se inyectan como contexto en el prompt LLM durante el análisis.
"""

import logging
from typing import List, Optional
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.knowledge_article import KnowledgeArticle, profile_knowledge_articles
from app.models.debugging import DebuggingProfile

logger = logging.getLogger(__name__)

# Límites configurables
MAX_ARTICLES_PER_ORG = 50
MAX_ARTICLES_PER_PROFILE = 10


class KnowledgeArticleService:
    """Servicio CRUD y asociaciones para artículos de conocimiento."""

    def create_article(
        self, db: Session, org_id: UUID, title: str, description: str, content: str
    ) -> KnowledgeArticle:
        """Crea un artículo verificando límite por organización."""
        count = db.query(func.count(KnowledgeArticle.id)).filter(
            KnowledgeArticle.organization_id == org_id
        ).scalar()
        if count >= MAX_ARTICLES_PER_ORG:
            raise ValueError(
                f"Límite alcanzado: máximo {MAX_ARTICLES_PER_ORG} artículos por organización"
            )
        article = KnowledgeArticle(
            organization_id=org_id, title=title, description=description, content=content
        )
        db.add(article)
        db.commit()
        db.refresh(article)
        return article

    def list_articles(self, db: Session, org_id: UUID) -> List[KnowledgeArticle]:
        """Lista todos los artículos de una organización."""
        return db.query(KnowledgeArticle).filter(
            KnowledgeArticle.organization_id == org_id
        ).order_by(KnowledgeArticle.updated_at.desc()).all()

    def get_article(self, db: Session, article_id: UUID, org_id: UUID) -> Optional[KnowledgeArticle]:
        """Obtiene un artículo verificando tenant isolation."""
        return db.query(KnowledgeArticle).filter(
            KnowledgeArticle.id == article_id,
            KnowledgeArticle.organization_id == org_id,
        ).first()

    def update_article(
        self, db: Session, article: KnowledgeArticle,
        title: Optional[str] = None, description: Optional[str] = None, content: Optional[str] = None
    ) -> KnowledgeArticle:
        """Actualiza campos de un artículo."""
        if title is not None:
            article.title = title
        if description is not None:
            article.description = description
        if content is not None:
            article.content = content
        db.commit()
        db.refresh(article)
        return article

    def delete_article(self, db: Session, article: KnowledgeArticle) -> None:
        """Elimina un artículo y sus asociaciones (cascade)."""
        db.delete(article)
        db.commit()

    def associate_articles_to_profile(
        self, db: Session, profile: DebuggingProfile, article_ids: List[UUID], org_id: UUID
    ) -> None:
        """
        Asocia artículos a un perfil, verificando:
        - Que los artículos pertenezcan a la misma organización
        - Que no se exceda el límite de 10 artículos por perfil
        - Que duplicados se ignoran silenciosamente
        """
        # Verificar artículos existen y pertenecen a la org
        articles = db.query(KnowledgeArticle).filter(
            KnowledgeArticle.id.in_(article_ids),
            KnowledgeArticle.organization_id == org_id,
        ).all()

        if len(articles) != len(article_ids):
            raise LookupError("Uno o más artículos no encontrados")

        # Contar asociaciones actuales
        current_count = db.query(func.count()).select_from(
            profile_knowledge_articles
        ).filter(
            profile_knowledge_articles.c.profile_id == profile.id
        ).scalar()

        # Filtrar duplicados
        existing_ids = {
            row[0] for row in db.query(profile_knowledge_articles.c.article_id).filter(
                profile_knowledge_articles.c.profile_id == profile.id
            ).all()
        }
        new_ids = [aid for aid in article_ids if aid not in existing_ids]

        if current_count + len(new_ids) > MAX_ARTICLES_PER_PROFILE:
            raise ValueError(
                f"Límite alcanzado: máximo {MAX_ARTICLES_PER_PROFILE} artículos por perfil"
            )

        # Insertar asociaciones nuevas
        for aid in new_ids:
            db.execute(
                profile_knowledge_articles.insert().values(profile_id=profile.id, article_id=aid)
            )
        db.commit()

    def remove_article_from_profile(
        self, db: Session, profile_id: UUID, article_id: UUID
    ) -> None:
        """Elimina una asociación artículo-perfil."""
        db.execute(
            profile_knowledge_articles.delete().where(
                profile_knowledge_articles.c.profile_id == profile_id,
                profile_knowledge_articles.c.article_id == article_id,
            )
        )
        db.commit()

    def get_articles_for_profile(
        self, db: Session, profile_id: UUID, org_id: UUID
    ) -> List[KnowledgeArticle]:
        """
        Obtiene todos los artículos asociados a un perfil.
        Usado por DebuggingAnalysisService para inyectar en el prompt.
        """
        return db.query(KnowledgeArticle).join(
            profile_knowledge_articles,
            profile_knowledge_articles.c.article_id == KnowledgeArticle.id,
        ).filter(
            profile_knowledge_articles.c.profile_id == profile_id,
            KnowledgeArticle.organization_id == org_id,
        ).all()
