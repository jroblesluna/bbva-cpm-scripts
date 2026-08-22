"""
Endpoints para generación y descarga de backups del sistema.

Restringido a Corporate Admins (misma lógica de dominios que ssl.py y sync_inventory.py).

Funcionalidad:
- Generar backup completo (BD + imágenes) de forma asíncrona
- Consultar estado del proceso de backup
- Descargar archivos ZIP via presigned URLs de S3
- Eliminar backup existente
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Literal, Optional

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.security import require_admin
from app.models.user import User

logger = logging.getLogger(__name__)


# === DOMINIOS CORPORATIVOS AUTORIZADOS ===

ALLOWED_DOMAINS = ["@robles.ai", "@sistemas.com.pe"]


# === DEPENDENCIA DE AUTORIZACIÓN ===

async def require_corporate_admin(
    current_user: User = Depends(require_admin),
) -> User:
    """Verifica que el admin pertenezca a un dominio corporativo autorizado."""
    email = (current_user.email or "").lower()
    if not any(email.endswith(domain) for domain in ALLOWED_DOMAINS):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo administradores corporativos pueden gestionar backups.",
        )
    return current_user


# === SCHEMAS ===

class BackupGenerateRequest(BaseModel):
    """Request para iniciar generación de backup."""
    password: Optional[str] = Field(
        None,
        min_length=4,
        max_length=128,
        description="Password para cifrar ZIPs con AES-256 (opcional)",
    )


class BackupStatusResponse(BaseModel):
    """Estado actual del proceso de backup."""
    status: Literal["idle", "generating", "completed", "failed"]
    stage: Optional[str] = None
    progress: Optional[int] = None
    error: Optional[str] = None
    # Solo cuando status == "completed":
    db_zip_size: Optional[int] = None
    images_zip_size: Optional[int] = None
    generated_at: Optional[str] = None
    has_password: Optional[bool] = None


class BackupDownloadResponse(BaseModel):
    """Respuesta con presigned URL de descarga."""
    presigned_url: str
    file_name: str
    file_size: int
    expires_in: int  # segundos


# === HELPERS ===

def _get_s3_client():
    """Crea cliente S3 con la configuración del proyecto."""
    session = boto3.Session(
        region_name=settings.AWS_REGION,
        profile_name=settings.AWS_PROFILE or None,
    )
    return session.client("s3")


def _read_backup_status() -> dict:
    """
    Lee backups/status.json desde S3.

    Retorna el contenido del archivo JSON, o un dict con status "idle"
    si el archivo no existe.
    """
    s3 = _get_s3_client()
    try:
        response = s3.get_object(
            Bucket=settings.S3_ARTIFACTS_BUCKET,
            Key="backups/status.json",
        )
        return json.loads(response["Body"].read().decode("utf-8"))
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code in ("NoSuchKey", "404"):
            return {"status": "idle"}
        logger.error("Error leyendo backup status de S3: %s", str(e))
        return {"status": "idle"}


# === ROUTER ===

router = APIRouter(prefix="/admin/backup")


@router.post(
    "/generate",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Iniciar generación de backup",
)
async def generate_backup(
    request: BackupGenerateRequest,
    current_user: User = Depends(require_corporate_admin),
):
    """
    Inicia la generación asíncrona de un backup completo.

    Verifica que no haya un backup en generación actualmente.
    Lanza el proceso de BackupService.generate() como asyncio task.
    Retorna 202 Accepted inmediatamente.
    """
    # Verificar que no hay backup en generación
    current_status = _read_backup_status()
    if current_status.get("status") == "generating":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya hay un backup en proceso de generación. Espere a que finalice.",
        )

    # Importar aquí para evitar circular imports
    from app.services.backup_service import BackupService

    # Lanzar generación como task asíncrono
    service = BackupService()
    asyncio.create_task(service.generate(password=request.password))

    logger.info(
        "Backup solicitado por %s (con password: %s)",
        current_user.email,
        request.password is not None,
    )

    return {
        "message": "Generación de backup iniciada",
        "status": "generating",
    }


@router.get(
    "/status",
    response_model=BackupStatusResponse,
    summary="Obtener estado del backup",
)
async def get_backup_status(
    current_user: User = Depends(require_corporate_admin),
):
    """
    Retorna el estado actual del proceso de backup.

    Lee backups/status.json desde S3. Si no existe, retorna status "idle".
    El frontend usa este endpoint para polling cada 5 segundos durante la generación.
    """
    status_data = _read_backup_status()

    return BackupStatusResponse(
        status=status_data.get("status", "idle"),
        stage=status_data.get("stage"),
        progress=status_data.get("progress"),
        error=status_data.get("error"),
        db_zip_size=status_data.get("db_zip_size"),
        images_zip_size=status_data.get("images_zip_size"),
        generated_at=status_data.get("generated_at"),
        has_password=status_data.get("has_password"),
    )


@router.get(
    "/download/{file_type}",
    response_model=BackupDownloadResponse,
    summary="Obtener URL de descarga del backup",
)
async def download_backup(
    file_type: Literal["db", "images"],
    current_user: User = Depends(require_corporate_admin),
):
    """
    Genera una presigned URL de descarga para un archivo del backup.

    El file_type determina qué archivo descargar:
    - "db" → backups/latest/db.zip (dump de base de datos)
    - "images" → backups/latest/images.zip (imágenes de VLANs)

    La URL expira en 1 hora (3600 segundos).
    """
    # Verificar que hay un backup completado
    current_status = _read_backup_status()
    if current_status.get("status") != "completed":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hay backup disponible para descargar.",
        )

    # Determinar key en S3 y nombre de archivo
    if file_type == "db":
        s3_key = "backups/latest/db.zip"
        file_name = "alwaysprint_backup_db.zip"
        file_size = current_status.get("db_zip_size", 0)
    else:
        s3_key = "backups/latest/images.zip"
        file_name = "alwaysprint_backup_images.zip"
        file_size = current_status.get("images_zip_size", 0)

    # Verificar que el archivo existe en S3
    s3 = _get_s3_client()
    try:
        s3.head_object(
            Bucket=settings.S3_ARTIFACTS_BUCKET,
            Key=s3_key,
        )
    except ClientError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Archivo de backup no encontrado en S3: {file_type}.zip",
        )

    # Generar presigned URL de descarga (expira en 1 hora)
    expires_in = 3600
    presigned_url = s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": settings.S3_ARTIFACTS_BUCKET,
            "Key": s3_key,
        },
        ExpiresIn=expires_in,
    )

    return BackupDownloadResponse(
        presigned_url=presigned_url,
        file_name=file_name,
        file_size=file_size,
        expires_in=expires_in,
    )


@router.delete(
    "/delete",
    summary="Eliminar backup actual",
)
async def delete_backup(
    current_user: User = Depends(require_corporate_admin),
):
    """
    Elimina los archivos del backup actual y resetea el status a idle.

    Elimina:
    - backups/latest/db.zip
    - backups/latest/images.zip
    - Escribe backups/status.json con status "idle"
    """
    # Verificar que no hay backup en generación
    current_status = _read_backup_status()
    if current_status.get("status") == "generating":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede eliminar mientras se genera un backup.",
        )

    s3 = _get_s3_client()

    # Eliminar archivos ZIP del backup
    keys_to_delete = [
        "backups/latest/db.zip",
        "backups/latest/images.zip",
    ]

    for key in keys_to_delete:
        try:
            s3.delete_object(
                Bucket=settings.S3_ARTIFACTS_BUCKET,
                Key=key,
            )
        except ClientError as e:
            # Si el archivo no existe, no es un error
            logger.warning("Error eliminando %s: %s", key, str(e))

    # Resetear status a idle
    idle_status = {
        "status": "idle",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        s3.put_object(
            Bucket=settings.S3_ARTIFACTS_BUCKET,
            Key="backups/status.json",
            Body=json.dumps(idle_status, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )
    except ClientError as e:
        logger.error("Error escribiendo status idle en S3: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error actualizando estado del backup.",
        )

    logger.info("Backup eliminado por %s", current_user.email)

    return {"message": "Backup eliminado exitosamente", "status": "idle"}


@router.post(
    "/factory-reset",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Resetear sistema a estado inicial (factory reset)",
)
async def factory_reset(
    current_user: User = Depends(require_corporate_admin),
):
    """
    Resetea el sistema completo a estado de fábrica (fire-and-forget).

    Retorna 202 inmediatamente y ejecuta la limpieza en background.
    El frontend redirige a /setup inmediatamente tras recibir 202.

    Operaciones (en background):
    1. Termina conexiones PostgreSQL + TRUNCATE CASCADE instantáneo (mantiene alembic_version)
    2. Limpia TODOS los objetos del bucket S3_DOCS_BUCKET (imágenes de VLANs, etc.)
    3. Limpia archivos de backup del bucket S3_ARTIFACTS_BUCKET

    ADVERTENCIA: Esta operación es IRREVERSIBLE.
    """
    logger.warning("FACTORY RESET solicitado por %s — lanzando en background", current_user.email)

    async def _run_factory_reset():
        """Ejecuta el factory reset en background."""
        import time
        from sqlalchemy import text
        from app.core.database import SessionLocal
        from app.services.restore_service import TABLE_ORDER

        # 1. Limpiar todas las tablas (mantener alembic_version)
        # PostgreSQL: pg_terminate_backend + TRUNCATE (instantáneo sin importar volumen)
        # SQLite: DELETE en orden inverso de FK
        db = SessionLocal()
        try:
            if settings.is_sqlite:
                db.execute(text("PRAGMA foreign_keys=OFF"))
                for table_name in reversed(TABLE_ORDER):
                    db.execute(text(f"DELETE FROM {table_name}"))
                db.execute(text("PRAGMA foreign_keys=ON"))
            else:
                # Terminar todas las conexiones excepto la actual para liberar locks
                db.execute(text(
                    "SELECT pg_terminate_backend(pid) "
                    "FROM pg_stat_activity "
                    "WHERE datname = current_database() AND pid != pg_backend_pid()"
                ))
                db.commit()
                # Pausa para que PostgreSQL limpie las conexiones terminadas
                time.sleep(0.5)
                # TRUNCATE instantáneo — funciona sin bloqueo ahora
                tables_str = ", ".join(TABLE_ORDER)
                db.execute(text(f"TRUNCATE TABLE {tables_str} CASCADE"))
            db.commit()
            logger.info("FACTORY RESET: BD limpiada (%d tablas)", len(TABLE_ORDER))
        except Exception as e:
            db.rollback()
            logger.error("FACTORY RESET: Error limpiando BD: %s", str(e))
            return
        finally:
            db.close()

        # 2. Limpiar bucket de docs (imágenes de VLANs, etc.)
        s3 = _get_s3_client()
        docs_deleted = 0
        try:
            paginator = s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=settings.S3_DOCS_BUCKET):
                objects = page.get("Contents", [])
                if objects:
                    delete_keys = [{"Key": obj["Key"]} for obj in objects]
                    s3.delete_objects(
                        Bucket=settings.S3_DOCS_BUCKET,
                        Delete={"Objects": delete_keys},
                    )
                    docs_deleted += len(delete_keys)
            logger.info("FACTORY RESET: S3 docs limpiado (%d objetos)", docs_deleted)
        except Exception as e:
            logger.warning("FACTORY RESET: Error parcial limpiando S3 docs: %s", str(e))

        # 3. Limpiar archivos de backup del bucket de artifacts
        artifacts_deleted = 0
        try:
            paginator = s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=settings.S3_ARTIFACTS_BUCKET, Prefix="backups/"):
                objects = page.get("Contents", [])
                if objects:
                    delete_keys = [{"Key": obj["Key"]} for obj in objects]
                    s3.delete_objects(
                        Bucket=settings.S3_ARTIFACTS_BUCKET,
                        Delete={"Objects": delete_keys},
                    )
                    artifacts_deleted += len(delete_keys)
            logger.info("FACTORY RESET: S3 artifacts limpiado (%d objetos)", artifacts_deleted)
        except Exception as e:
            logger.warning("FACTORY RESET: Error parcial limpiando S3 artifacts: %s", str(e))

        logger.warning(
            "FACTORY RESET completado: %d tablas, %d docs, %d artifacts eliminados",
            len(TABLE_ORDER), docs_deleted, artifacts_deleted,
        )

    # Lanzar como task en background — retornar 202 inmediatamente
    asyncio.create_task(_run_factory_reset())

    return {
        "message": "Factory reset iniciado. El sistema se limpiará en segundos.",
    }
