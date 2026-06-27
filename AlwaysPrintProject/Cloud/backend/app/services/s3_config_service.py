"""
Servicio de integración con S3 para configs firmados y certificados ECDSA.

Interactúa con el bucket S3 de documentación para:
- Subir configs firmados (.signed)
- Subir certificados públicos (.cer)
- Eliminar configs/certs de S3
- Generar URLs públicas de descarga
"""

import logging

import boto3
from botocore.exceptions import ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)


class S3ConfigService:
    """
    Servicio para interactuar con el bucket S3 para configs firmados y certificados.

    Los configs firmados se almacenan en: s3://{bucket}/configs/{org_id}/{hash_short}.signed
    Los certificados públicos en: s3://{bucket}/certs/{org_id}/v{version}.cer
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

    def upload_signed_config(self, org_id: str, hash_short: str, signed_json: str) -> str:
        """
        Sube un config firmado al bucket S3.

        Args:
            org_id: Identificador de la organización
            hash_short: Hash corto (8 chars) del config para la clave S3
            signed_json: JSON firmado (string) con config + hash + signature + cert_version

        Returns:
            La clave S3 del objeto subido
        """
        s3_key = f"configs/{org_id}/{hash_short}.signed"

        try:
            logger.info(
                "Subiendo config firmado a S3: bucket=%s, key=%s, tamaño=%d bytes",
                self._bucket, s3_key, len(signed_json)
            )

            self._client.put_object(
                Bucket=self._bucket,
                Key=s3_key,
                Body=signed_json.encode('utf-8'),
                ContentType='application/json',
            )

            logger.info("Config firmado subido exitosamente: key=%s", s3_key)
            return s3_key

        except ClientError as e:
            logger.error("Error al subir config firmado a S3: %s", str(e))
            raise

    def upload_cert(self, org_id: str, cert_version: int, cert_pem: bytes) -> str:
        """
        Sube un certificado público al bucket S3.

        Args:
            org_id: Identificador de la organización
            cert_version: Versión del certificado (entero incremental)
            cert_pem: Contenido binario del certificado en formato PEM/DER

        Returns:
            URL pública del certificado para descarga por workstations
        """
        s3_key = f"certs/{org_id}/v{cert_version}.cer"

        try:
            logger.info(
                "Subiendo certificado a S3: bucket=%s, key=%s, versión=%d, tamaño=%d bytes",
                self._bucket, s3_key, cert_version, len(cert_pem)
            )

            self._client.put_object(
                Bucket=self._bucket,
                Key=s3_key,
                Body=cert_pem,
                ContentType='application/x-x509-ca-cert',
            )

            public_url = self.get_public_url(s3_key)
            logger.info(
                "Certificado subido exitosamente: key=%s, url=%s",
                s3_key, public_url
            )
            return public_url

        except ClientError as e:
            logger.error("Error al subir certificado a S3: %s", str(e))
            raise

    def delete_signed_config(self, s3_key: str) -> bool:
        """
        Elimina un config firmado del bucket S3.

        Args:
            s3_key: Clave del objeto en S3 (e.g. configs/{org_id}/{hash}.signed)

        Returns:
            True si se eliminó correctamente
        """
        try:
            logger.info("Eliminando config firmado de S3: bucket=%s, key=%s", self._bucket, s3_key)

            self._client.delete_object(
                Bucket=self._bucket,
                Key=s3_key,
            )

            logger.info("Config firmado eliminado exitosamente: key=%s", s3_key)
            return True

        except ClientError as e:
            logger.error("Error al eliminar config firmado de S3: %s", str(e))
            raise

    def delete_cert(self, s3_key: str) -> bool:
        """
        Elimina un certificado del bucket S3.

        Args:
            s3_key: Clave del objeto en S3 (e.g. certs/{org_id}/v{n}.cer)

        Returns:
            True si se eliminó correctamente
        """
        try:
            logger.info("Eliminando certificado de S3: bucket=%s, key=%s", self._bucket, s3_key)

            self._client.delete_object(
                Bucket=self._bucket,
                Key=s3_key,
            )

            logger.info("Certificado eliminado exitosamente: key=%s", s3_key)
            return True

        except ClientError as e:
            logger.error("Error al eliminar certificado de S3: %s", str(e))
            raise

    def get_public_url(self, s3_key: str) -> str:
        """
        Construye la URL pública del objeto en S3.

        Como el bucket tiene política pública de lectura,
        la URL es directa sin necesidad de presigned.

        Args:
            s3_key: Clave del objeto en S3

        Returns:
            URL pública en formato https://{bucket}.s3.{region}.amazonaws.com/{s3_key}
        """
        return f"https://{self._bucket}.s3.{settings.AWS_REGION}.amazonaws.com/{s3_key}"
