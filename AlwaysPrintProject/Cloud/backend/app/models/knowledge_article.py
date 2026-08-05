"""
Modelo SQLAlchemy para artículos de conocimiento técnico.

Este módulo define:
- KnowledgeArticle: artículo de conocimiento para inyección en prompts LLM
- profile_knowledge_articles: tabla de asociación many-to-many con DebuggingProfile

Los artículos contienen documentación en Markdown (flujos de impresión, patrones
de fallo, secuencias de autenticación, etc.) que se inyectan como contexto adicional
al prompt del LLM durante el análisis de sesiones de debugging.
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index, Table
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.organization import GUID


# === TABLA DE ASOCIACIÓN MANY-TO-MANY ===
# Relaciona artículos de conocimiento con perfiles de debugging.
# Un artículo puede servir a múltiples perfiles y viceversa.
profile_knowledge_articles = Table(
    "profile_knowledge_articles",
    Base.metadata,
    Column(
        "profile_id",
        GUID,
        ForeignKey("debugging_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "article_id",
        GUID,
        ForeignKey("knowledge_articles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class KnowledgeArticle(Base):
    """
    Artículo de conocimiento técnico para inyección en prompts LLM.

    Almacena documentación en Markdown (flujos de impresión, patrones de fallo,
    secuencias de autenticación, etc.) que se inyecta como contexto adicional
    al prompt del LLM durante el análisis de sesiones de debugging.

    Límites:
    - Máximo 50 artículos por organización
    - Máximo 10 artículos asociados por perfil de debugging
    - Contenido máximo: 500KB por artículo
    """
    __tablename__ = "knowledge_articles"

    # === CAMPOS PRINCIPALES ===
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        GUID, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )

    title = Column(String(200), nullable=False, comment="Título del artículo (3-200 chars)")
    description = Column(String(500), nullable=False, comment="Descripción breve (10-500 chars)")
    content = Column(Text, nullable=False, comment="Contenido Markdown (max 500KB)")

    # === AUDITORÍA ===
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # === RELACIONES ===
    organization = relationship("Organization", backref="knowledge_articles")
    profiles = relationship(
        "DebuggingProfile",
        secondary=profile_knowledge_articles,
        back_populates="knowledge_articles",
    )

    # === ÍNDICES ===
    __table_args__ = (
        Index("ix_knowledge_articles_org", "organization_id"),
    )

    def __repr__(self):
        return (
            f"<KnowledgeArticle(id={self.id}, title='{self.title}', "
            f"org={self.organization_id})>"
        )
