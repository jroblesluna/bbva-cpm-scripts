"""
Servicio de integración con S3 para actualizaciones automáticas.

Este servicio interactúa con el bucket S3 de artefactos para:
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

    El MSI se almacena en: s3://{bucket}/latest/AlwaysPrint.msi
    con metadata personalizada (version, build-date, commit-hash).
    El nombre del bucket se configura vía la variable S3_ARTIFACTS_BUCKET.
    """

    def __init__(self):
        """Inicializa el cliente S3 con la región configurada."""
        self._client = boto3.client('s3', region_name=settings.AWS_REGION)
        self._bucket = settings.S3_ARTIFACTS_BUCKET
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

    def list_versions(self) -> list:
        """
        Lista todas las versiones disponibles en el bucket S3.

        Escanea el prefijo 'versions/' y retorna metadata de cada versión encontrada.

        Returns:
            Lista de dicts con: version, build_date, commit_hash, file_size
        """
        versions = []
        try:
            logger.info("Listando versiones disponibles en S3: bucket=%s, prefix=versions/", self._bucket)

            paginator = self._client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=self._bucket, Prefix='versions/', Delimiter='/')

            for page in pages:
                for prefix in page.get('CommonPrefixes', []):
                    # prefix es algo como 'versions/1.26.518.2152/'
                    version_str = prefix['Prefix'].replace('versions/', '').rstrip('/')
                    if not version_str:
                        continue

                    # Obtener metadata de cada versión
                    try:
                        key = f"versions/{version_str}/AlwaysPrint.msi"
                        meta = self.get_msi_metadata(key=key)
                        meta['version'] = version_str  # Usar el nombre del directorio como versión
                        versions.append(meta)
                    except ClientError:
                        # Si no se puede leer metadata de una versión, omitirla
                        logger.warning("No se pudo leer metadata de versión: %s", version_str)
                        continue

            # Ordenar por fecha de build descendente (más reciente primero)
            # Si build_date no está disponible, usar versión como fallback
            versions.sort(key=lambda v: v.get('build_date', '') or '', reverse=True)
            logger.info("Versiones encontradas: %d", len(versions))

        except ClientError as e:
            logger.error("Error listando versiones en S3: %s", str(e))
            raise

        return versions

    def delete_version(self, version: str) -> bool:
        """
        Elimina todos los objetos bajo el prefijo versions/{version}/ en S3.

        Borra recursivamente todos los archivos asociados a una versión específica.

        Args:
            version: String de versión a eliminar (ej: "1.26.518.2152")

        Returns:
            True si se eliminaron objetos, False si no había nada que eliminar

        Raises:
            ClientError: Si ocurre un error al interactuar con S3.
        """
        prefix = f"versions/{version}/"
        try:
            logger.info(
                "Eliminando versión de S3 (con versionado): bucket=%s, prefix=%s",
                self._bucket,
                prefix
            )

            # Listar TODAS las versiones de los objetos bajo el prefijo
            # (necesario porque el bucket tiene versionado habilitado —
            # un simple DeleteObjects solo agrega delete markers sin eliminar realmente)
            objects_to_delete = []
            paginator = self._client.get_paginator('list_object_versions')
            pages = paginator.paginate(Bucket=self._bucket, Prefix=prefix)

            for page in pages:
                # Versiones reales del objeto
                for v in page.get('Versions', []):
                    objects_to_delete.append({
                        'Key': v['Key'],
                        'VersionId': v['VersionId']
                    })
                # Delete markers existentes (también deben eliminarse)
                for dm in page.get('DeleteMarkers', []):
                    objects_to_delete.append({
                        'Key': dm['Key'],
                        'VersionId': dm['VersionId']
                    })

            if not objects_to_delete:
                logger.warning(
                    "No se encontraron objetos ni versiones para eliminar: prefix=%s", prefix
                )
                return False

            # Eliminar permanentemente en lotes (máximo 1000 por request de S3)
            for i in range(0, len(objects_to_delete), 1000):
                batch = objects_to_delete[i:i + 1000]
                self._client.delete_objects(
                    Bucket=self._bucket,
                    Delete={'Objects': batch}
                )

            logger.info(
                "Versión eliminada permanentemente: version=%s, objetos_eliminados=%d",
                version,
                len(objects_to_delete)
            )
            return True

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            logger.error(
                "Error al eliminar versión de S3: "
                "código=%s, mensaje=%s, prefix=%s",
                error_code,
                error_message,
                prefix
            )
            raise

    def get_object(self, key: str = None) -> dict:
        """
        Obtiene el objeto MSI completo desde S3 (para streaming directo).

        Args:
            key: Clave S3 del objeto. Si es None, usa la clave por defecto (latest/AlwaysPrint.msi)

        Returns:
            Respuesta de S3 GetObject con Body (StreamingBody) y ContentLength

        Raises:
            ClientError: Si el objeto no existe o S3 no está disponible.
        """
        effective_key = key if key is not None else self._key

        logger.info(
            "Descargando objeto de S3: bucket=%s, key=%s",
            self._bucket,
            effective_key
        )

        response = self._client.get_object(
            Bucket=self._bucket,
            Key=effective_key
        )

        logger.info(
            "Objeto obtenido de S3: key=%s, tamaño=%d bytes",
            effective_key,
            response.get('ContentLength', 0)
        )

        return response

    def upload_msi(self, file_data: bytes, version: str, build_date: str, commit_hash: str) -> dict:
        """
        Sube un MSI al bucket S3 como latest y como versión específica.

        Almacena el archivo en dos ubicaciones:
        - latest/AlwaysPrint.msi (siempre la versión más reciente)
        - versions/{version}/AlwaysPrint.msi (historial)

        Args:
            file_data: Contenido binario del archivo MSI
            version: Versión del MSI (ej: "1.26.518.2152")
            build_date: Fecha de build en formato ISO
            commit_hash: Hash del commit de git

        Returns:
            dict con: version, build_date, commit_hash, file_size

        Raises:
            ClientError: Si ocurre un error al subir a S3.
        """
        metadata = {
            'version': version,
            'build-date': build_date,
            'commit-hash': commit_hash,
        }
        file_size = len(file_data)

        try:
            # Subir como latest
            logger.info(
                "Subiendo MSI a S3: bucket=%s, version=%s, tamaño=%d bytes",
                self._bucket, version, file_size
            )
            self._client.put_object(
                Bucket=self._bucket,
                Key=self._key,
                Body=file_data,
                ContentType='application/x-msi',
                Metadata=metadata,
            )

            # Subir como versión específica
            version_key = f"versions/{version}/AlwaysPrint.msi"
            self._client.put_object(
                Bucket=self._bucket,
                Key=version_key,
                Body=file_data,
                ContentType='application/x-msi',
                Metadata=metadata,
            )

            logger.info(
                "MSI subido exitosamente: version=%s, latest=%s, versioned=%s",
                version, self._key, version_key
            )

            return {
                'version': version,
                'build_date': build_date,
                'commit_hash': commit_hash,
                'file_size': file_size,
            }

        except ClientError as e:
            logger.error("Error al subir MSI a S3: %s", str(e))
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
