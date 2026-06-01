"""
Modelo de documentos del sistema.

Almacena metadatos de documentos PDF subidos por administradores.
Los archivos se guardan en S3 (bucket de docs público) y cualquier
usuario autenticado puede verlos/descargarlos.
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Integer, ForeignKey, Index
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.organization import GUID


class Document(Base):
    """
    Documento de actualización del sistema.

    Los administradores pueden crear, editar y eliminar documentos.
    Los operarios solo pueden ver y descargar.
    El PDF se almacena en S3 (bucket docs público).
    """
    __tablename__ = "documents"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)

    # Metadatos del documento
    title = Column(String(500), nullable=False, comment="Título del documento")
    description = Column(Text, nullable=True, comment="Descripción del documento")

    # Información del archivo en S3
    file_name = Column(String(500), nullable=False, comment="Nombre original del archivo PDF")
    s3_key = Column(String(1000), nullable=False, comment="Clave del objeto en S3")
    file_size = Column(Integer, nullable=False, default=0, comment="Tamaño del archivo en bytes")

    # Auditoría
    created_by_id = Column(GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relaciones
    created_by = relationship("User", foreign_keys=[created_by_id])

    # Índices
    __table_args__ = (
        Index("ix_documents_created_at", "created_at"),
    )

    def __repr__(self):
        return f"<Document(id={self.id}, title='{self.title}')>"
