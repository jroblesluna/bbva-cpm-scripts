"""
Servicio de integración con S3 para imágenes de ubicación de VLANs.

Descarga imágenes de Street View desde Google Maps API (usando la API key
de la organización) y las almacena en S3. Retorna la URL pública de S3
para evitar exponer la API key en el frontend.

Estructura en S3: s3://{bucket}/vlan-images/{vlan_id}.jpg
"""

import logging
import uuid
from typing import Optional

import boto3
import httpx
from botocore.exceptions import ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)


class S3ImagesService:
    """
    Servicio para almacenar imágenes de ubicación de VLANs en S3.

    Las imágenes se almacenan en: s3://{bucket}/vlan-images/{vlan_id}.jpg
    El bucket tiene política pública de lectura, por lo que la URL directa
    permite visualización sin credenciales.
    """

    def __init__(self):
        """Inicializa el cliente S3 con la región configurada."""
        session = boto3.Session(
            region_name=settings.AWS_REGION,
            profile_name=settings.AWS_PROFILE or None,
        )
        self._client = session.client('s3')
        self._bucket = settings.S3_DOCS_BUCKET

    async def upload_street_view_image(
        self,
        vlan_id: str,
        latitude: float,
        longitude: float,
        api_key: str,
    ) -> Optional[str]:
        """
        Descarga la imagen de Street View y la sube a S3.

        1. Construye la URL de Google Street View Static API
        2. Descarga la imagen (sin exponer la key al frontend)
        3. La sube a S3 con key: vlan-images/{vlan_id}.jpg
        4. Retorna la URL pública de S3

        Args:
            vlan_id: UUID de la VLAN (se usa como nombre de archivo)
            latitude: Latitud de la ubicación
            longitude: Longitud de la ubicación
            api_key: Google Maps API key de la organización

        Returns:
            URL pública de la imagen en S3, o None si falla
        """
        # Intentar primero Street View, si falla (403/etc), usar Maps Static como fallback
        street_view_url = (
            f"https://maps.googleapis.com/maps/api/streetview"
            f"?size=600x400"
            f"&location={latitude},{longitude}"
            f"&key={api_key}"
        )

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                # Intento 1: Street View Static API
                response = await client.get(street_view_url)

                if response.status_code != 200 or "image" not in response.headers.get("content-type", ""):
                    # Fallback: Maps Static API (mapa satélite con marcador)
                    logger.info(
                        "Street View no disponible (status=%d), usando Maps Static: vlan_id=%s",
                        response.status_code, vlan_id
                    )
                    static_map_url = (
                        f"https://maps.googleapis.com/maps/api/staticmap"
                        f"?center={latitude},{longitude}"
                        f"&zoom=17"
                        f"&size=600x400"
                        f"&maptype=hybrid"
                        f"&markers=color:red%7C{latitude},{longitude}"
                        f"&key={api_key}"
                    )
                    response = await client.get(static_map_url)

            if response.status_code != 200:
                logger.warning(
                    "No se pudo descargar imagen (Street View ni Static Map): status=%d, vlan_id=%s",
                    response.status_code, vlan_id
                )
                return None

            # Verificar que es una imagen real
            content_type = response.headers.get("content-type", "")
            if "image" not in content_type:
                logger.warning(
                    "Respuesta no es imagen: content_type=%s, vlan_id=%s",
                    content_type, vlan_id
                )
                return None

            image_data = response.content

            # Verificar tamaño mínimo (imágenes de "no street view" son muy pequeñas)
            if len(image_data) < 5000:
                logger.info(
                    "Imagen de Street View muy pequeña (probable placeholder): size=%d, vlan_id=%s",
                    len(image_data), vlan_id
                )
                # Aún así la subimos — puede ser una imagen válida de zona sin cobertura

            # Subir a S3
            s3_key = f"vlan-images/{vlan_id}.jpg"
            self._client.put_object(
                Bucket=self._bucket,
                Key=s3_key,
                Body=image_data,
                ContentType="image/jpeg",
                CacheControl="public, max-age=86400",  # Cache 24h
            )

            public_url = self._get_public_url(s3_key)

            logger.info(
                "Imagen de Street View subida a S3: vlan_id=%s, size=%d bytes, url=%s",
                vlan_id, len(image_data), public_url
            )

            return public_url

        except httpx.TimeoutException:
            logger.warning(
                "Timeout descargando imagen de Street View: vlan_id=%s", vlan_id
            )
            return None
        except ClientError as e:
            logger.error(
                "Error al subir imagen a S3: vlan_id=%s, error=%s", vlan_id, str(e)
            )
            return None
        except Exception as e:
            logger.error(
                "Error inesperado en upload_street_view_image: vlan_id=%s, error=%s",
                vlan_id, str(e)
            )
            return None

    def delete_image(self, vlan_id: str) -> bool:
        """
        Elimina la imagen de una VLAN de S3.

        Args:
            vlan_id: UUID de la VLAN

        Returns:
            True si se eliminó correctamente
        """
        s3_key = f"vlan-images/{vlan_id}.jpg"
        try:
            self._client.delete_object(
                Bucket=self._bucket,
                Key=s3_key,
            )
            logger.info("Imagen eliminada de S3: vlan_id=%s", vlan_id)
            return True
        except ClientError as e:
            logger.error(
                "Error al eliminar imagen de S3: vlan_id=%s, error=%s",
                vlan_id, str(e)
            )
            return False

    def _get_public_url(self, s3_key: str) -> str:
        """Construye la URL pública del objeto en S3."""
        return f"https://{self._bucket}.s3.{settings.AWS_REGION}.amazonaws.com/{s3_key}"
