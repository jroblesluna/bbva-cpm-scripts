"""
Servicio de integración con S3 para actualizaciones automáticas.

Este servicio interactúa con el bucket S3 'alwaysprint-artifacts' para:
- Obtener metadata del MSI más reciente (versión, fecha de build, commit hash, tamaño)
- Generar URLs presigned para descarga segura del MSI por las workstations
"""

import logging

import boto3
from botocore.exceptions import ClientError

from app.core.config import settings

# Logger del módulo
logger = logging.getLogger(__name__)


class S3UpdateService:
    """
    Servicio para interactuar con el bucket de artefactos S3.

    Proporciona métodos para:
    - Consultar metadata del MSI disponible en S3
    - Generar URLs presigned temporales para descarga segura

    El MSI se almacena en: s3://alwaysprint-artifacts/latest/AlwaysPrint.msi
    con metadata personalizada (version, build-date, commit-hash).
    """

    def __init__(self):
        """Inicializa el cliente S3 con la región configurada."""
        self._client = boto3.client('s3', region_name=settings.AWS_REGION)
        self._bucket = 'alwaysprint-artifacts'
        self._key = 'latest/AlwaysPrint.msi'

    def get_msi_metadata(self, key: str = None) -> dict:
        """
        Obtiene metadata del MSI desde S3 usando HeadObject.

        Extrae la metadata personalizada del objeto S3 (version, build-date,
        commit-hash) y el tamaño del archivo (ContentLength).

        Args:
            key: Clave S3 del objeto. Si es None, usa la clave por defecto (latest/AlwaysPrint.msi)

        Returns:
            dict con claves: version, build_date, commit_hash, file_size

        Raises:
            ClientError: Si el objeto no existe o S3 no está disponible.
                Se loggea el error antes de propagar la excepción.
        """
        # Usar la clave proporcionada o la clave por defecto
        effective_key = key if key is not None else self._key

        try:
            logger.info(
                "Consultando metadata del MSI en S3: bucket=%s, key=%s",
                self._bucket,
                effective_key
            )

            response = self._client.head_object(
                Bucket=self._bucket,
                Key=effective_key
            )

            metadata = response.get('Metadata', {})

            resultado = {
                'version': metadata.get('version', 'unknown'),
                'build_date': metadata.get('build-date', ''),
                'commit_hash': metadata.get('commit-hash', ''),
                'file_size': response.get('ContentLength', 0),
            }

            logger.info(
                "Metadata del MSI obtenida exitosamente: version=%s, "
                "tamaño=%d bytes, fecha_build=%s",
                resultado['version'],
                resultado['file_size'],
                resultado['build_date']
            )

            return resultado

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            logger.error(
                "Error al consultar metadata del MSI en S3: "
                "código=%s, mensaje=%s, bucket=%s, key=%s",
                error_code,
                error_message,
                self._bucket,
                effective_key
            )
            raise

    def generate_download_url(self, key: str = None, expires_in: int = 3600) -> str:
        """
        Genera una URL presigned para descargar el MSI desde S3.

        La URL generada permite descarga directa sin credenciales AWS,
        con una expiración configurable (por defecto 1 hora).

        Args:
            key: Clave S3 del objeto. Si es None, usa la clave por defecto (latest/AlwaysPrint.msi)
            expires_in: Tiempo de expiración en segundos (default: 3600 = 1 hora)

        Returns:
            URL presigned como string

        Raises:
            ClientError: Si no se puede generar la URL presigned.
                Se loggea el error antes de propagar la excepción.
        """
        # Usar la clave proporcionada o la clave por defecto
        effective_key = key if key is not None else self._key

        try:
            logger.info(
                "Generando URL presigned para descarga del MSI: "
                "bucket=%s, key=%s, expiración=%d segundos",
                self._bucket,
                effective_key,
                expires_in
            )

            url = self._client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self._bucket, 'Key': effective_key},
                ExpiresIn=expires_in
            )

            logger.info(
                "URL presigned generada exitosamente (expira en %d segundos)",
                expires_in
            )

            return url

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            logger.error(
                "Error al generar URL presigned para descarga del MSI: "
                "código=%s, mensaje=%s, bucket=%s, key=%s",
                error_code,
                error_message,
                self._bucket,
                effective_key
            )
            raise
