"""
Endpoints para restauración de backup desde la pantalla de setup.

Estos endpoints son PÚBLICOS (sin autenticación) pero solo funcionan
cuando la base de datos está vacía (user_count == 0). Esto permite
restaurar un backup en una instalación nueva sin necesidad de login.

Funcionalidad:
- Generar presigned URLs de upload para subir ZIPs a S3
- Iniciar proceso de restauración asíncrono
- Consultar estado del proceso de restauración
"""

import asyncio
import io
import json
import logging
from datetime import datetime, timezone
from typing import Literal, Optional

import boto3
import pyzipper
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.user import User

logger = logging.getLogger(__name__)


# === DEPENDENCIA: VERIFICAR BD VACÍA ===

def require_empty_db(db: Session = Depends(get_db)) -> Session:
    """
    Verifica que la base de datos esté vacía (sin usuarios).

    Este guard asegura que los endpoints de restore solo estén disponibles
    durante la configuración inicial (BD vacía). Una vez que hay al menos
    un usuario, los endpoints se desactivan.

    Returns:
        La sesión de BD si está vacía.

    Raises:
        HTTPException 403: Si la BD ya tiene usuarios.
    """
    user_count = db.query(User).count()
    if user_count > 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La restauración solo está disponible cuando la base de datos está vacía.",
        )
    return db


# === SCHEMAS ===

class RestorePresignedUrlsRequest(BaseModel):
    """Request para generar presigned URLs de upload."""
    db_zip_size: int = Field(
        ..., gt=0, description="Tamaño del archivo db.zip en bytes"
    )
    images_zip_size: int = Field(
        ..., gt=0, description="Tamaño del archivo images.zip en bytes"
    )


class RestorePresignedUrlsResponse(BaseModel):
    """Respuesta con presigned URLs para upload directo a S3."""
    db_upload_url: str
    images_upload_url: str
    expires_in: int  # seconds (1800 = 30 min)


class RestoreStartRequest(BaseModel):
    """Request para iniciar el proceso de restauración."""
    password: Optional[str] = Field(
        None, description="Password si los ZIPs están protegidos"
    )


class RestoreStatusResponse(BaseModel):
    """Estado actual del proceso de restauración."""
    status: Literal["idle", "restoring", "completed", "failed"]
    stage: Optional[str] = None
    progress: Optional[int] = None
    error: Optional[str] = None
    completed_at: Optional[str] = None


# === HELPERS ===

def _get_s3_client():
    """Crea cliente S3 con la configuración del proyecto."""
    session = boto3.Session(
        region_name=settings.AWS_REGION,
        profile_name=settings.AWS_PROFILE or None,
    )
    return session.client("s3")


# Timeout en minutos para considerar un restore como zombie/failed
RESTORE_TIMEOUT_MINUTES = 5


def _read_restore_status() -> dict:
    """
    Lee backups/restore_status.json desde S3.

    Si el status es "restoring" pero updated_at tiene más de RESTORE_TIMEOUT_MINUTES
    sin actualización, se considera "failed" automáticamente (zombie detection).

    Retorna el contenido del archivo JSON, o un dict con status "idle"
    si el archivo no existe.
    """
    s3 = _get_s3_client()
    try:
        response = s3.get_object(
            Bucket=settings.S3_ARTIFACTS_BUCKET,
            Key="backups/restore_status.json",
        )
        status_data = json.loads(response["Body"].read().decode("utf-8"))

        # Zombie detection: si está "restoring" pero no se actualizó en los últimos N minutos
        if status_data.get("status") == "restoring":
            updated_at_str = status_data.get("updated_at")
            if updated_at_str:
                try:
                    updated_at = datetime.fromisoformat(updated_at_str)
                    now = datetime.now(timezone.utc)
                    elapsed_minutes = (now - updated_at).total_seconds() / 60
                    if elapsed_minutes > RESTORE_TIMEOUT_MINUTES:
                        logger.warning(
                            "Restore zombie detectado: último update hace %.1f minutos (timeout=%d)",
                            elapsed_minutes, RESTORE_TIMEOUT_MINUTES,
                        )
                        return {
                            "status": "failed",
                            "error": f"Timeout — la restauración no respondió en {RESTORE_TIMEOUT_MINUTES} minutos",
                        }
                except (ValueError, TypeError):
                    pass  # Si no se puede parsear, no aplicar timeout

        return status_data
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code in ("NoSuchKey", "404"):
            return {"status": "idle"}
        logger.error("Error leyendo restore status de S3: %s", str(e))
        return {"status": "idle"}


def _validate_and_extract_manifests(
    s3, password: Optional[str]
) -> tuple[dict, dict]:
    """
    Descarga ambos ZIPs de S3, valida password y estructura de manifest.

    Retorna tupla (db_manifest, images_manifest) si ambos son válidos.
    Lanza HTTPException 400 si alguno es inválido.
    """
    # --- Validar DB ZIP ---
    try:
        response = s3.get_object(
            Bucket=settings.S3_ARTIFACTS_BUCKET,
            Key="backups/restore-upload/db.zip",
        )
        db_zip_bytes = response["Body"].read()
    except ClientError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo descargar db.zip de S3.",
        )

    try:
        buffer = io.BytesIO(db_zip_bytes)
        with pyzipper.AESZipFile(buffer, "r") as zf:
            if password:
                zf.setpassword(password.encode("utf-8"))

            # Verificar que manifest.json existe
            if "manifest.json" not in zf.namelist():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="db.zip inválido: no contiene manifest.json. ¿Está seguro de que es un archivo de backup de base de datos?",
                )

            # Leer y parsear manifest
            manifest_bytes = zf.read("manifest.json")
            db_manifest = json.loads(manifest_bytes.decode("utf-8"))

            # Validar campos requeridos del DB manifest
            if not isinstance(db_manifest.get("version"), str):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="db.zip inválido: manifest.json no tiene campo 'version' válido.",
                )
            if not isinstance(db_manifest.get("tables"), dict):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="db.zip inválido: manifest.json no tiene campo 'tables' válido. No es un backup de base de datos.",
                )
            if not isinstance(db_manifest.get("total_records"), int):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="db.zip inválido: manifest.json no tiene campo 'total_records' válido.",
                )
    except HTTPException:
        raise
    except RuntimeError as e:
        if "password" in str(e).lower() or "Bad password" in str(e):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Contraseña incorrecta para db.zip.",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error leyendo db.zip: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"db.zip corrupto o ilegible: {str(e)}",
        )

    # --- Validar Images ZIP ---
    try:
        response = s3.get_object(
            Bucket=settings.S3_ARTIFACTS_BUCKET,
            Key="backups/restore-upload/images.zip",
        )
        images_zip_bytes = response["Body"].read()
    except ClientError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo descargar images.zip de S3.",
        )

    try:
        buffer = io.BytesIO(images_zip_bytes)
        with pyzipper.AESZipFile(buffer, "r") as zf:
            if password:
                zf.setpassword(password.encode("utf-8"))

            # Verificar que manifest.json existe
            if "manifest.json" not in zf.namelist():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="images.zip inválido: no contiene manifest.json. ¿Está seguro de que es un archivo de backup de imágenes?",
                )

            # Leer y parsear manifest
            manifest_bytes = zf.read("manifest.json")
            images_manifest = json.loads(manifest_bytes.decode("utf-8"))

            # Validar campos requeridos del Images manifest
            if not isinstance(images_manifest.get("version"), str):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="images.zip inválido: manifest.json no tiene campo 'version' válido.",
                )
            if not isinstance(images_manifest.get("files"), list):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="images.zip inválido: manifest.json no tiene campo 'files' válido. No es un backup de imágenes.",
                )
    except HTTPException:
        raise
    except RuntimeError as e:
        if "password" in str(e).lower() or "Bad password" in str(e):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Contraseña incorrecta para images.zip.",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error leyendo images.zip: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"images.zip corrupto o ilegible: {str(e)}",
        )

    return db_manifest, images_manifest


# === ROUTER ===

router = APIRouter(prefix="/setup/restore")


@router.post(
    "/presigned-urls",
    response_model=RestorePresignedUrlsResponse,
    summary="Generar presigned URLs para upload de backup",
)
async def get_presigned_urls(
    request: RestorePresignedUrlsRequest,
    db: Session = Depends(require_empty_db),
):
    """
    Genera 2 presigned PUT URLs para que el frontend suba los ZIPs directamente a S3.

    Solo disponible cuando la BD está vacía (setup inicial).
    Las URLs expiran en 30 minutos (1800 segundos).
    """
    s3 = _get_s3_client()
    expires_in = 1800  # 30 minutos

    try:
        db_upload_url = s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.S3_ARTIFACTS_BUCKET,
                "Key": "backups/restore-upload/db.zip",
                "ContentType": "application/zip",
            },
            ExpiresIn=expires_in,
        )

        images_upload_url = s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.S3_ARTIFACTS_BUCKET,
                "Key": "backups/restore-upload/images.zip",
                "ContentType": "application/zip",
            },
            ExpiresIn=expires_in,
        )
    except ClientError as e:
        logger.error("Error generando presigned URLs de upload: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error generando URLs de upload.",
        )

    logger.info(
        "Presigned URLs generadas para restore (db_size=%d, images_size=%d)",
        request.db_zip_size,
        request.images_zip_size,
    )

    return RestorePresignedUrlsResponse(
        db_upload_url=db_upload_url,
        images_upload_url=images_upload_url,
        expires_in=expires_in,
    )


@router.post(
    "/start",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Iniciar proceso de restauración",
)
async def start_restore(
    request: RestoreStartRequest,
    db: Session = Depends(require_empty_db),
):
    """
    Inicia el proceso de restauración asíncrono.

    Valida ambos ZIPs (password, manifest estructura y contenido) ANTES de iniciar.
    Si alguno es inválido, retorna 400 con detalle del error.
    Si ambos son válidos, lanza RestoreService.restore() como asyncio task.
    Retorna 202 con resumen de manifests para mostrar en frontend.
    """
    # Verificar que no hay un restore en progreso
    current_status = _read_restore_status()
    if current_status.get("status") == "restoring":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya hay una restauración en proceso. Espere a que finalice.",
        )

    # Validar ambos ZIPs: descargar, verificar password, estructura de manifest
    s3 = _get_s3_client()
    db_manifest, images_manifest = _validate_and_extract_manifests(s3, request.password)

    logger.info(
        "Manifests validados: DB tables=%d, records=%d, images=%d",
        len(db_manifest.get("tables", {})),
        db_manifest.get("total_records", 0),
        images_manifest.get("total_images", 0),
    )

    # Importar aquí para evitar circular imports
    from app.services.restore_service import RestoreService

    # Lanzar restauración como task asíncrono
    service = RestoreService()
    asyncio.create_task(service.restore(password=request.password))

    logger.info(
        "Restauración iniciada (con password: %s)",
        request.password is not None,
    )

    return {
        "message": "Proceso de restauración iniciado",
        "status": "restoring",
        "db_manifest": {
            "version": db_manifest.get("version"),
            "tables": len(db_manifest.get("tables", {})),
            "total_records": db_manifest.get("total_records", 0),
            "generated_at": db_manifest.get("generated_at"),
            "alembic_revision": db_manifest.get("alembic_revision"),
        },
        "images_manifest": {
            "version": images_manifest.get("version"),
            "total_images": images_manifest.get("total_images", 0),
            "total_size": images_manifest.get("total_size", 0),
        },
    }


@router.get(
    "/status",
    response_model=RestoreStatusResponse,
    summary="Obtener estado de la restauración",
)
async def get_restore_status():
    """
    Retorna el estado actual del proceso de restauración.

    Este endpoint es público (sin autenticación ni verificación de BD vacía)
    porque se consulta durante el proceso de restore, cuando la BD puede estar
    en un estado intermedio.

    Lee backups/restore_status.json desde S3. Si no existe, retorna status "idle".
    El frontend usa este endpoint para polling cada 3 segundos durante la restauración.
    """
    status_data = _read_restore_status()

    return RestoreStatusResponse(
        status=status_data.get("status", "idle"),
        stage=status_data.get("stage"),
        progress=status_data.get("progress"),
        error=status_data.get("error"),
        completed_at=status_data.get("completed_at"),
    )
