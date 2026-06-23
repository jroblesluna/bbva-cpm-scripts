"""
Servicio de integración con S3 para imágenes de ubicación de VLANs.

Descarga imágenes de Street View desde Google Maps API (usando la API key
de la organización) y las almacena en S3. Retorna la URL pública de S3
para evitar exponer la API key en el frontend.

Estructura en S3: s3://{bucket}/vlan-images/{vlan_id}.jpg
"""

import logging
import time
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
    El bucket tiene política pública de lectura.
    """

    def __init__(self):
        """Inicializa el cliente S3 con la región configurada."""
        session = boto3.Session(
            region_name=settings.AWS_REGION,
            profile_name=settings.AWS_PROFILE or None,
        )
        self._client = session.client('s3')
        self._bucket = settings.S3_DOCS_BUCKET

    # =========================================================================
    # GENERAR OPCIONES (picker de imágenes)
    # =========================================================================

    async def generate_image_options(
        self,
        vlan_id: str,
        latitude: float,
        longitude: float,
        api_key: str,
        place_id: Optional[str] = None,
    ) -> dict:
        """
        Genera múltiples opciones de imagen para que el usuario elija.

        Opciones (en orden):
        1. Google Places Photo (la misma que muestra Google Maps) — si disponible, marcada como recomendada
        2. Street View desde 4 ángulos (heading 0°, 90°, 180°, 270°) con source=outdoor
        3. Mapa satélite con marcador (siempre disponible)

        Retorna dict con:
        - options: lista de URLs públicas de S3
        - recommended_index: índice de la opción recomendada (0 si hay Places Photo)
        """
        options: list[str] = []
        recommended_index: int = 0
        cache_buster = int(time.time())

        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                # 1. Google Places Photo (primera opción, recomendada)
                if place_id:
                    places_photo = await self._try_places_photo(client, place_id, api_key, vlan_id)
                    if places_photo:
                        s3_key = f"vlan-images/{vlan_id}_opt_places.jpg"
                        self._client.put_object(
                            Bucket=self._bucket,
                            Key=s3_key,
                            Body=places_photo,
                            ContentType="image/jpeg",
                            CacheControl="no-cache",
                        )
                        options.append(f"{self._get_public_url(s3_key)}?v={cache_buster}")
                        recommended_index = 0

                # 2. Verificar cobertura outdoor de Street View
                has_outdoor = await self._check_sv_coverage(client, latitude, longitude, api_key)

                # Street View desde distintos ángulos
                if has_outdoor:
                    headings = [0, 90, 180, 270]
                    for idx, heading in enumerate(headings):
                        url = (
                            f"https://maps.googleapis.com/maps/api/streetview"
                            f"?size=600x400"
                            f"&location={latitude},{longitude}"
                            f"&heading={heading}"
                            f"&source=outdoor"
                            f"&key={api_key}"
                        )
                        resp = await client.get(url)
                        if resp.status_code == 200 and "image" in resp.headers.get("content-type", ""):
                            s3_key = f"vlan-images/{vlan_id}_opt{idx}.jpg"
                            self._client.put_object(
                                Bucket=self._bucket,
                                Key=s3_key,
                                Body=resp.content,
                                ContentType="image/jpeg",
                                CacheControl="no-cache",
                            )
                            options.append(f"{self._get_public_url(s3_key)}?v={cache_buster}")

                # Mapa satélite como última opción (siempre disponible)
                static_url = (
                    f"https://maps.googleapis.com/maps/api/staticmap"
                    f"?center={latitude},{longitude}"
                    f"&zoom=18&size=600x400&maptype=hybrid"
                    f"&markers=color:red%7C{latitude},{longitude}"
                    f"&key={api_key}"
                )
                resp = await client.get(static_url)
                if resp.status_code == 200 and "image" in resp.headers.get("content-type", ""):
                    s3_key = f"vlan-images/{vlan_id}_opt_map.jpg"
                    self._client.put_object(
                        Bucket=self._bucket,
                        Key=s3_key,
                        Body=resp.content,
                        ContentType="image/jpeg",
                        CacheControl="no-cache",
                    )
                    options.append(f"{self._get_public_url(s3_key)}?v={cache_buster}")

            logger.info("Opciones generadas: vlan_id=%s, count=%d", vlan_id, len(options))
            return {"options": options, "recommended_index": recommended_index}

        except Exception as e:
            logger.error("Error generando opciones: vlan_id=%s, error=%s", vlan_id, str(e))
            return {"options": options, "recommended_index": recommended_index}

    # =========================================================================
    # SELECCIONAR OPCIÓN
    # =========================================================================

    async def select_image_option(self, vlan_id: str, selected_url: str) -> Optional[str]:
        """
        Copia la opción seleccionada como imagen principal y limpia las temporales.
        """
        try:
            # Extraer s3_key de la URL seleccionada
            base_url = self._get_public_url("")
            relative_key = selected_url.split("?")[0].replace(base_url, "")

            # Copiar como imagen principal
            main_key = f"vlan-images/{vlan_id}.jpg"
            self._client.copy_object(
                Bucket=self._bucket,
                Key=main_key,
                CopySource={"Bucket": self._bucket, "Key": relative_key},
                ContentType="image/jpeg",
                CacheControl="no-cache",
                MetadataDirective="REPLACE",
            )

            # Limpiar opciones temporales
            self._cleanup_options(vlan_id)

            cache_buster = int(time.time())
            final_url = f"{self._get_public_url(main_key)}?v={cache_buster}"
            logger.info("Imagen seleccionada: vlan_id=%s", vlan_id)
            return final_url

        except Exception as e:
            logger.error("Error seleccionando imagen: vlan_id=%s, error=%s", vlan_id, str(e))
            return None

    # =========================================================================
    # CAPTURA PERSONALIZADA (usuario navega Street View interactivo)
    # =========================================================================

    async def capture_custom_street_view(
        self,
        vlan_id: str,
        latitude: float,
        longitude: float,
        heading: float,
        pitch: float,
        fov: float,
        api_key: str,
        pano_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Captura una imagen de Street View con parámetros exactos del usuario.

        Si pano_id está disponible, usa ese panorama exacto (garantiza que la
        imagen capturada sea la misma que el usuario estaba viendo).
        """
        try:
            # Usar pano_id si disponible (garantiza panorama exacto)
            if pano_id:
                url = (
                    f"https://maps.googleapis.com/maps/api/streetview"
                    f"?size=600x400"
                    f"&pano={pano_id}"
                    f"&heading={heading}"
                    f"&pitch={pitch}"
                    f"&fov={fov}"
                    f"&key={api_key}"
                )
            else:
                url = (
                    f"https://maps.googleapis.com/maps/api/streetview"
                    f"?size=600x400"
                    f"&location={latitude},{longitude}"
                    f"&heading={heading}"
                    f"&pitch={pitch}"
                    f"&fov={fov}"
                    f"&source=outdoor"
                    f"&key={api_key}"
                )

            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(url)

            if resp.status_code != 200 or "image" not in resp.headers.get("content-type", ""):
                logger.warning("Captura SV falló: vlan_id=%s, status=%d", vlan_id, resp.status_code)
                return None

            # Subir a S3
            s3_key = f"vlan-images/{vlan_id}.jpg"
            self._client.put_object(
                Bucket=self._bucket,
                Key=s3_key,
                Body=resp.content,
                ContentType="image/jpeg",
                CacheControl="no-cache",
            )

            cache_buster = int(time.time())
            final_url = f"{self._get_public_url(s3_key)}?v={cache_buster}"
            logger.info("Captura personalizada: vlan_id=%s, heading=%.1f, pitch=%.1f, fov=%.1f", vlan_id, heading, pitch, fov)
            return final_url

        except Exception as e:
            logger.error("Error en captura: vlan_id=%s, error=%s", vlan_id, str(e))
            return None

    # =========================================================================
    # ELIMINAR IMAGEN
    # =========================================================================

    def delete_image(self, vlan_id: str) -> bool:
        """Elimina la imagen de una VLAN de S3."""
        s3_key = f"vlan-images/{vlan_id}.jpg"
        try:
            self._client.delete_object(Bucket=self._bucket, Key=s3_key)
            logger.info("Imagen eliminada: vlan_id=%s", vlan_id)
            return True
        except ClientError as e:
            logger.error("Error eliminando imagen: vlan_id=%s, error=%s", vlan_id, str(e))
            return False

    # =========================================================================
    # HELPERS PRIVADOS
    # =========================================================================

    async def _check_sv_coverage(
        self, client: httpx.AsyncClient, latitude: float, longitude: float, api_key: str
    ) -> bool:
        """Verifica si hay cobertura outdoor de Street View."""
        try:
            url = (
                f"https://maps.googleapis.com/maps/api/streetview/metadata"
                f"?location={latitude},{longitude}"
                f"&source=outdoor"
                f"&key={api_key}"
            )
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.json().get("status") == "OK"
            return False
        except Exception:
            return False

    def _cleanup_options(self, vlan_id: str) -> None:
        """Elimina las imágenes de opciones temporales de S3."""
        try:
            for suffix in ["_opt0", "_opt1", "_opt2", "_opt3", "_opt_map", "_opt_places"]:
                key = f"vlan-images/{vlan_id}{suffix}.jpg"
                self._client.delete_object(Bucket=self._bucket, Key=key)
        except Exception:
            pass

    async def _try_places_photo(
        self, client: httpx.AsyncClient, place_id: str, api_key: str, vlan_id: str
    ) -> Optional[bytes]:
        """
        Obtiene la foto principal del lugar desde Google Places API.
        Es la misma foto que muestra Google Maps en el panel izquierdo.
        """
        try:
            # Obtener photo_reference del place
            details_url = (
                f"https://maps.googleapis.com/maps/api/place/details/json"
                f"?place_id={place_id}"
                f"&fields=photos"
                f"&key={api_key}"
            )
            details_resp = await client.get(details_url)
            if details_resp.status_code != 200:
                return None

            details_data = details_resp.json()
            photos = details_data.get("result", {}).get("photos", [])
            if not photos:
                return None

            # Primera foto = la principal (misma que Google Maps)
            photo_reference = photos[0].get("photo_reference")
            if not photo_reference:
                return None

            # Descargar la foto
            photo_url = (
                f"https://maps.googleapis.com/maps/api/place/photo"
                f"?maxwidth=600"
                f"&photo_reference={photo_reference}"
                f"&key={api_key}"
            )
            photo_resp = await client.get(photo_url)
            if photo_resp.status_code == 200 and "image" in photo_resp.headers.get("content-type", ""):
                logger.info("Places Photo obtenida: vlan_id=%s, size=%d", vlan_id, len(photo_resp.content))
                return photo_resp.content

            return None
        except Exception as e:
            logger.info("Error en Places Photo: vlan_id=%s, error=%s", vlan_id, str(e))
            return None

    def _get_public_url(self, s3_key: str) -> str:
        """Construye la URL pública del objeto en S3."""
        return f"https://{self._bucket}.s3.{settings.AWS_REGION}.amazonaws.com/{s3_key}"
