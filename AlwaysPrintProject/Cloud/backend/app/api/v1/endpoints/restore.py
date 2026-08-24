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
import json
import logging
from typing import Literal, Optional

import boto3
from botocore.client import Config
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


class TableProgress(BaseModel):
    """Progreso de restauración de una tabla individual."""
    table: str
    count: int


class RestoreStatusResponse(BaseModel):
    """Estado actual del proceso de restauración."""
    status: Literal["idle", "restoring", "completed", "failed"]
    stage: Optional[str] = None
    progress: Optional[int] = None
    error: Optional[str] = None
    completed_at: Optional[str] = None
    # Detalle tabla por tabla durante la etapa "restoring_db"
    tables_total: Optional[int] = None
    tables_done: Optional[int] = None
    current_table: Optional[str] = None
    tables_detail: Optional[list[TableProgress]] = None


# === HELPERS ===

def _get_s3_client():
    """
    Crea cliente S3 con la configuración del proyecto.

    Fuerza SigV4: sin esto, generate_presigned_url para put_object con
    ContentType puede caer en SigV2 (deprecado), que S3 rechaza — el navegador
    lo reporta como error de CORS aunque el bucket ya tenga CORS bien configurado.
    """
    session = boto3.Session(
        region_name=settings.AWS_REGION,
        profile_name=settings.AWS_PROFILE or None,
    )
    return session.client("s3", config=Config(signature_version="s3v4"))


def _read_restore_status() -> dict:
    """
    Lee backups/restore_status.json desde S3.

    Retorna el contenido del archivo JSON, o un dict con status "idle"
    si el archivo no existe.
    """
    s3 = _get_s3_client()
    try:
        response = s3.get_object(
            Bucket=settings.S3_ARTIFACTS_BUCKET,
            Key="backups/restore_status.json",
        )
        return json.loads(response["Body"].read().decode("utf-8"))
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code in ("NoSuchKey", "404"):
            return {"status": "idle"}
        logger.error("Error leyendo restore status de S3: %s", str(e))
        return {"status": "idle"}


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

    Verifica que los archivos ZIP hayan sido subidos a S3 (backups/restore-upload/)
    y lanza RestoreService.restore() (síncrono) en un thread del executor.
    Retorna 202 Accepted inmediatamente.
    """
    # Verificar que no hay un restore en progreso
    current_status = _read_restore_status()
    if current_status.get("status") == "restoring":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya hay una restauración en proceso. Espere a que finalice.",
        )

    # Verificar que los archivos existen en S3
    s3 = _get_s3_client()

    for key, label in [
        ("backups/restore-upload/db.zip", "db.zip"),
        ("backups/restore-upload/images.zip", "images.zip"),
    ]:
        try:
            s3.head_object(
                Bucket=settings.S3_ARTIFACTS_BUCKET,
                Key=key,
            )
        except ClientError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Archivo {label} no encontrado en S3. Suba los archivos antes de iniciar la restauración.",
            )

    # Importar aquí para evitar circular imports
    from app.services.restore_service import RestoreService

    # Lanzar restauración en un thread aparte — restore() es código síncrono
    # (SQLAlchemy/boto3 bloqueantes); con asyncio.create_task() correría sobre
    # el mismo event loop del servidor y lo congelaría entero mientras dura.
    service = RestoreService()
    asyncio.get_running_loop().run_in_executor(None, service.restore, request.password)

    logger.info(
        "Restauración iniciada (con password: %s)",
        request.password is not None,
    )

    return {
        "message": "Proceso de restauración iniciado",
        "status": "restoring",
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
        tables_total=status_data.get("tables_total"),
        tables_done=status_data.get("tables_done"),
        current_table=status_data.get("current_table"),
        tables_detail=status_data.get("tables_detail"),
    )
