"""
Endpoints para gestión de documentos del sistema.

- Admin: CRUD completo (crear, leer, actualizar, eliminar)
- Operario: solo lectura y descarga
"""

import logging
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.core.security import get_current_user, require_admin
from app.models.user import User, UserRole
from app.models.document import Document
from app.schemas.document import (
    DocumentInfo,
    DocumentUpdate,
    DocumentListResponse,
)
from app.services.s3_docs_service import S3DocsService

logger = logging.getLogger(__name__)

router = APIRouter()

# Tamaño máximo de archivo: 50 MB
MAX_FILE_SIZE = 50 * 1024 * 1024


def _build_document_info(doc: Document, s3_service: S3DocsService) -> DocumentInfo:
    """Construye el schema de respuesta a partir del modelo."""
    return DocumentInfo(
        id=doc.id,
        title=doc.title,
        description=doc.description,
        file_name=doc.file_name,
        file_size=doc.file_size,
        download_url=s3_service.get_download_url(doc.s3_key),
        created_by_id=doc.created_by_id,
        created_by_name=doc.created_by.full_name if doc.created_by else None,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


# === ENDPOINTS DE LECTURA (todos los usuarios autenticados) ===

@router.get(
    "/",
    response_model=DocumentListResponse,
    summary="Listar documentos",
    description="Lista todos los documentos del sistema con paginación"
)
def list_documents(
    page: int = 1,
    page_size: int = 20,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Lista documentos con paginación y búsqueda opcional.
    Accesible para todos los usuarios autenticados.
    """
    query = db.query(Document)

    # Filtro de búsqueda por título o descripción
    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            (Document.title.ilike(search_filter)) |
            (Document.description.ilike(search_filter))
        )

    # Contar total
    total = query.count()

    # Paginación
    offset = (page - 1) * page_size
    documents = (
        query
        .order_by(Document.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    s3_service = S3DocsService()
    items = [_build_document_info(doc, s3_service) for doc in documents]

    return DocumentListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{document_id}",
    response_model=DocumentInfo,
    summary="Obtener documento por ID",
    description="Obtiene los detalles de un documento específico"
)
def get_document(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Obtiene un documento por su ID."""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Documento no encontrado"
        )

    s3_service = S3DocsService()
    return _build_document_info(doc, s3_service)


# === ENDPOINTS DE ESCRITURA (solo Admin) ===

@router.post(
    "/",
    response_model=DocumentInfo,
    status_code=status.HTTP_201_CREATED,
    summary="Crear documento",
    description="Sube un nuevo documento PDF (solo Admin)"
)
async def create_document(
    title: str = Form(..., min_length=1, max_length=500),
    description: Optional[str] = Form(None, max_length=2000),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """
    Crea un nuevo documento subiendo un PDF a S3.
    Solo accesible para administradores.
    """
    # Validar tipo de archivo
    if not file.content_type or 'pdf' not in file.content_type.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se permiten archivos PDF"
        )

    # Leer contenido del archivo
    file_data = await file.read()

    # Validar tamaño
    if len(file_data) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo excede el tamaño máximo de 50 MB"
        )

    if len(file_data) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo está vacío"
        )

    # Subir a S3
    s3_service = S3DocsService()
    try:
        s3_result = s3_service.upload_document(file_data, file.filename or "documento.pdf")
    except Exception as e:
        logger.error("Error al subir documento a S3: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al subir el archivo. Intente nuevamente."
        )

    # Crear registro en BD
    doc = Document(
        title=title,
        description=description,
        file_name=file.filename or "documento.pdf",
        s3_key=s3_result['s3_key'],
        file_size=s3_result['file_size'],
        created_by_id=current_user.id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    logger.info(
        "Documento creado: id=%s, título='%s', por usuario=%s",
        doc.id, doc.title, current_user.email
    )

    return _build_document_info(doc, s3_service)


@router.patch(
    "/{document_id}",
    response_model=DocumentInfo,
    summary="Actualizar documento",
    description="Actualiza título y/o descripción de un documento (solo Admin)"
)
def update_document(
    document_id: UUID,
    data: DocumentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """
    Actualiza los metadatos de un documento (título, descripción).
    Solo accesible para administradores.
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Documento no encontrado"
        )

    if data.title is not None:
        doc.title = data.title
    if data.description is not None:
        doc.description = data.description

    db.commit()
    db.refresh(doc)

    logger.info(
        "Documento actualizado: id=%s, título='%s', por usuario=%s",
        doc.id, doc.title, current_user.email
    )

    s3_service = S3DocsService()
    return _build_document_info(doc, s3_service)


@router.put(
    "/{document_id}/file",
    response_model=DocumentInfo,
    summary="Reemplazar archivo PDF",
    description="Reemplaza el archivo PDF de un documento existente (solo Admin)"
)
async def replace_document_file(
    document_id: UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """
    Reemplaza el archivo PDF de un documento existente.
    Elimina el archivo anterior de S3 y sube el nuevo.
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Documento no encontrado"
        )

    # Validar tipo de archivo
    if not file.content_type or 'pdf' not in file.content_type.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se permiten archivos PDF"
        )

    file_data = await file.read()

    if len(file_data) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo excede el tamaño máximo de 50 MB"
        )

    if len(file_data) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo está vacío"
        )

    s3_service = S3DocsService()

    # Eliminar archivo anterior
    try:
        s3_service.delete_document(doc.s3_key)
    except Exception as e:
        logger.warning("No se pudo eliminar archivo anterior de S3: %s", str(e))

    # Subir nuevo archivo
    try:
        s3_result = s3_service.upload_document(file_data, file.filename or "documento.pdf")
    except Exception as e:
        logger.error("Error al subir nuevo archivo a S3: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al subir el archivo. Intente nuevamente."
        )

    # Actualizar registro
    doc.s3_key = s3_result['s3_key']
    doc.file_name = file.filename or "documento.pdf"
    doc.file_size = s3_result['file_size']
    db.commit()
    db.refresh(doc)

    logger.info(
        "Archivo de documento reemplazado: id=%s, nuevo_key=%s",
        doc.id, doc.s3_key
    )

    return _build_document_info(doc, s3_service)


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar documento",
    description="Elimina un documento y su archivo PDF de S3 (solo Admin)"
)
def delete_document(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """
    Elimina un documento del sistema y su archivo de S3.
    Solo accesible para administradores.
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Documento no encontrado"
        )

    # Eliminar de S3
    s3_service = S3DocsService()
    try:
        s3_service.delete_document(doc.s3_key)
    except Exception as e:
        logger.warning("No se pudo eliminar archivo de S3: %s (continuando con eliminación de BD)", str(e))

    # Eliminar de BD
    db.delete(doc)
    db.commit()

    logger.info(
        "Documento eliminado: id=%s, título='%s', por usuario=%s",
        document_id, doc.title, current_user.email
    )
