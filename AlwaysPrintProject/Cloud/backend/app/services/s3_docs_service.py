"""
Servicio de integración con S3 para documentos públicos.

Interactúa con el bucket S3 de documentación para:
- Subir PDFs
- Generar URLs públicas de descarga
- Eliminar documentos
"""

import logging
import uuid

import boto3
from botocore.exceptions import ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)


class S3DocsService:
    """
    Servicio para interactuar con el bucket S3 de documentación pública.

    Los documentos se almacenan en: s3://{bucket}/documents/{uuid}.pdf
    El bucket tiene política pública de lectura, por lo que la URL directa
    permite descarga sin credenciales.
    """

    def __init__(self):
        """Inicializa el cliente S3 con la región configurada."""
        session = boto3.Session(
            region_name=settings.AWS_REGION,
            profile_name=settings.AWS_PROFILE or None,
        )
        self._client = session.client('s3')
        self._bucket = settings.S3_DOCS_BUCKET

    def upload_document(self, file_data: bytes, original_filename: str) -> dict:
        """
        Sube un PDF al bucket de documentación.

        Args:
            file_data: Contenido binario del archivo PDF
            original_filename: Nombre original del archivo

        Returns:
            dict con: s3_key, download_url, file_size
        """
        # Generar clave única para evitar colisiones
        file_id = str(uuid.uuid4())
        s3_key = f"documents/{file_id}.pdf"
        file_size = len(file_data)

        try:
            logger.info(
                "Subiendo documento a S3: bucket=%s, key=%s, tamaño=%d bytes",
                self._bucket, s3_key, file_size
            )

            self._client.put_object(
                Bucket=self._bucket,
                Key=s3_key,
                Body=file_data,
                ContentType='application/pdf',
                ContentDisposition=f'inline; filename="{original_filename}"',
                Metadata={
                    'original-filename': original_filename,
                },
            )

            download_url = self._get_public_url(s3_key)

            logger.info(
                "Documento subido exitosamente: key=%s, url=%s",
                s3_key, download_url
            )

            return {
                's3_key': s3_key,
                'download_url': download_url,
                'file_size': file_size,
            }

        except ClientError as e:
            logger.error("Error al subir documento a S3: %s", str(e))
            raise

    def delete_document(self, s3_key: str) -> bool:
        """
        Elimina un documento del bucket S3.

        Args:
            s3_key: Clave del objeto en S3

        Returns:
            True si se eliminó correctamente
        """
        try:
            logger.info("Eliminando documento de S3: bucket=%s, key=%s", self._bucket, s3_key)

            self._client.delete_object(
                Bucket=self._bucket,
                Key=s3_key,
            )

            logger.info("Documento eliminado exitosamente: key=%s", s3_key)
            return True

        except ClientError as e:
            logger.error("Error al eliminar documento de S3: %s", str(e))
            raise

    def get_download_url(self, s3_key: str) -> str:
        """
        Obtiene la URL pública de descarga de un documento.

        Como el bucket tiene política pública de lectura,
        la URL es directa sin necesidad de presigned.

        Args:
            s3_key: Clave del objeto en S3

        Returns:
            URL pública de descarga
        """
        return self._get_public_url(s3_key)

    def _get_public_url(self, s3_key: str) -> str:
        """Construye la URL pública del objeto en S3."""
        return f"https://{self._bucket}.s3.{settings.AWS_REGION}.amazonaws.com/{s3_key}"
