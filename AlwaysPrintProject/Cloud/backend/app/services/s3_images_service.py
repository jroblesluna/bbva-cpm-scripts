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
        place_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Descarga la imagen de ubicación y la sube a S3.

        Orden de prioridad:
        1. Google Places Photo (la misma foto que muestra Google Maps)
        2. Street View Static API (panorámica más cercana)
        3. Maps Static API (mapa satélite con marcador)

        Args:
            vlan_id: UUID de la VLAN (se usa como nombre de archivo)
            latitude: Latitud de la ubicación
            longitude: Longitud de la ubicación
            api_key: Google Maps API key de la organización
            place_id: Google Place ID (opcional, mejora la calidad de la foto)

        Returns:
            URL pública de la imagen en S3, o None si falla
        """
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                image_data = None

                # Intento 1: Street View Static API (vista exterior del edificio)
                image_data = await self._try_street_view(client, latitude, longitude, api_key, vlan_id)

                # Intento 2: Maps Static API (mapa satélite con marcador)
                if not image_data:
                    image_data = await self._try_static_map(client, latitude, longitude, api_key, vlan_id)

            if not image_data:
                logger.warning(
                    "No se pudo obtener ninguna imagen para vlan_id=%s", vlan_id
                )
                return None

            # Subir a S3
            s3_key = f"vlan-images/{vlan_id}.jpg"
            self._client.put_object(
                Bucket=self._bucket,
                Key=s3_key,
                Body=image_data,
                ContentType="image/jpeg",
                CacheControl="no-cache",
            )

            public_url = self._get_public_url(s3_key)

            # Agregar cache-buster para forzar recarga en el navegador
            import time
            cache_buster = int(time.time())
            public_url_with_cb = f"{public_url}?v={cache_buster}"

            logger.info(
                "Imagen subida a S3: vlan_id=%s, size=%d bytes, url=%s",
                vlan_id, len(image_data), public_url_with_cb
            )

            return public_url_with_cb

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

    async def _try_places_photo(
        self, client: httpx.AsyncClient, place_id: str, api_key: str, vlan_id: str
    ) -> Optional[bytes]:
        """
        Intenta obtener la foto del lugar desde Google Places API.
        Usa Place Details para obtener photo_reference, luego descarga la foto.
        """
        try:
            # Paso 1: Obtener photo_reference del place
            details_url = (
                f"https://maps.googleapis.com/maps/api/place/details/json"
                f"?place_id={place_id}"
                f"&fields=photos"
                f"&key={api_key}"
            )
            details_resp = await client.get(details_url)
            if details_resp.status_code != 200:
                logger.info(
                    "Places Details falló (status=%d): vlan_id=%s",
                    details_resp.status_code, vlan_id
                )
                return None

            details_data = details_resp.json()
            photos = details_data.get("result", {}).get("photos", [])
            if not photos:
                logger.info("No hay fotos en Places para vlan_id=%s", vlan_id)
                return None

            # Usar la primera foto (la más relevante según Google)
            photo_reference = photos[0].get("photo_reference")
            if not photo_reference:
                return None

            # Paso 2: Descargar la foto usando photo_reference
            photo_url = (
                f"https://maps.googleapis.com/maps/api/place/photo"
                f"?maxwidth=600"
                f"&photo_reference={photo_reference}"
                f"&key={api_key}"
            )
            photo_resp = await client.get(photo_url)

            if photo_resp.status_code == 200 and "image" in photo_resp.headers.get("content-type", ""):
                logger.info(
                    "Places Photo obtenida: vlan_id=%s, size=%d bytes",
                    vlan_id, len(photo_resp.content)
                )
                return photo_resp.content

            logger.info(
                "Places Photo falló (status=%d): vlan_id=%s",
                photo_resp.status_code, vlan_id
            )
            return None
        except Exception as e:
            logger.info("Error en Places Photo: vlan_id=%s, error=%s", vlan_id, str(e))
            return None

    async def _try_street_view(
        self, client: httpx.AsyncClient, latitude: float, longitude: float, api_key: str, vlan_id: str
    ) -> Optional[bytes]:
        """Intenta obtener imagen de Street View Static API."""
        try:
            # Verificar primero si hay cobertura con metadata endpoint
            metadata_url = (
                f"https://maps.googleapis.com/maps/api/streetview/metadata"
                f"?location={latitude},{longitude}"
                f"&key={api_key}"
            )
            meta_resp = await client.get(metadata_url)
            if meta_resp.status_code == 200:
                meta_data = meta_resp.json()
                if meta_data.get("status") != "OK":
                    logger.info(
                        "Street View sin cobertura (status=%s): vlan_id=%s",
                        meta_data.get("status"), vlan_id
                    )
                    return None

            # Descargar la imagen
            url = (
                f"https://maps.googleapis.com/maps/api/streetview"
                f"?size=600x400"
                f"&location={latitude},{longitude}"
                f"&key={api_key}"
            )
            resp = await client.get(url)
            if resp.status_code == 200 and "image" in resp.headers.get("content-type", ""):
                logger.info("Street View obtenida: vlan_id=%s, size=%d", vlan_id, len(resp.content))
                return resp.content
            logger.info(
                "Street View no disponible (status=%d): vlan_id=%s",
                resp.status_code, vlan_id
            )
            return None
        except Exception as e:
            logger.info("Error en Street View: vlan_id=%s, error=%s", vlan_id, str(e))
            return None

    async def _try_static_map(
        self, client: httpx.AsyncClient, latitude: float, longitude: float, api_key: str, vlan_id: str
    ) -> Optional[bytes]:
        """Fallback: genera mapa estático satélite con marcador."""
        try:
            url = (
                f"https://maps.googleapis.com/maps/api/staticmap"
                f"?center={latitude},{longitude}"
                f"&zoom=17"
                f"&size=600x400"
                f"&maptype=hybrid"
                f"&markers=color:red%7C{latitude},{longitude}"
                f"&key={api_key}"
            )
            resp = await client.get(url)
            if resp.status_code == 200 and "image" in resp.headers.get("content-type", ""):
                logger.info("Static Map obtenida: vlan_id=%s", vlan_id)
                return resp.content
            logger.info(
                "Static Map falló (status=%d): vlan_id=%s",
                resp.status_code, vlan_id
            )
            return None
        except Exception as e:
            logger.info("Error en Static Map: vlan_id=%s, error=%s", vlan_id, str(e))
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
