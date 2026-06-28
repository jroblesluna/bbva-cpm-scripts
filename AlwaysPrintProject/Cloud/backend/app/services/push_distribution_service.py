"""
Servicio de distribución push-based vía WebSocket.

Coordina el envío de mensajes push a workstations online cuando ocurren
cambios de estado (configuración, certificado, MSI). NO realiza queries
a BD — toda la información proviene del StateMapService y del caller.

El filtrado de workstations se basa en los dicts del connection_manager:
- org_ids: {ws_id: org_id} — para filtrar por organización
- _ws_vlan_ids: {ws_id: vlan_id} — para filtrar por VLAN (RedisConnectionManager)
- workstation_connections: {ws_id: WebSocket} — para saber si está online

Uso:
    from app.services.push_distribution_service import PushDistributionService

    push_service = PushDistributionService(connection_manager, state_map_service)
    enviados = await push_service.push_config_change(org_id, hash, url, "org", None)
"""

from app.core.logging import get_logger
from app.services.state_map_service import StateMapService

logger = get_logger(__name__)


class PushDistributionService:
    """
    Coordina el envío de push messages a workstations tras cambios de estado.

    Zero queries a BD — los datos de workstations online provienen del
    connection_manager y los datos de estado del StateMapService/caller.
    """

    def __init__(self, connection_manager, state_map_service: StateMapService):
        """
        Inicializa el servicio de distribución push.

        Args:
            connection_manager: ConnectionManager o RedisConnectionManager
                que gestiona las conexiones WebSocket activas.
            state_map_service: StateMapService con el mapa de estado en memoria.
        """
        self._connection_manager = connection_manager
        self._state_map = state_map_service

    def _get_target_workstations(
        self, org_id: str, scope: str, scope_id: str | None
    ) -> list[str]:
        """
        Determina qué workstations online deben recibir un push message.

        Filtra las workstations conectadas según el scope:
        - "org": todas las workstations online de la organización.
        - "vlan": solo workstations online de la VLAN específica.
        - "workstation": solo esa workstation si está online.

        No realiza queries a BD. Usa los dicts internos del connection_manager:
        - org_ids: {ws_id: org_id}
        - _ws_vlan_ids: {ws_id: vlan_id} (solo en RedisConnectionManager)

        Args:
            org_id: UUID de la organización.
            scope: Scope del cambio ("org", "vlan", "workstation").
            scope_id: ID del scope (vlan_id o workstation_id). None para "org".

        Returns:
            Lista de workstation_ids que deben recibir el mensaje.
        """
        cm = self._connection_manager

        if scope == "workstation":
            # Solo enviar a esa workstation específica si está online
            if scope_id and cm.is_workstation_online(scope_id):
                return [scope_id]
            return []

        if scope == "vlan":
            # Filtrar workstations online de la org que pertenecen a la VLAN
            # _ws_vlan_ids solo existe en RedisConnectionManager
            ws_vlan_ids = getattr(cm, "_ws_vlan_ids", {})
            targets = [
                ws_id
                for ws_id, ws_org_id in cm.org_ids.items()
                if ws_org_id == org_id
                and ws_id in cm.workstation_connections
                and ws_vlan_ids.get(ws_id) == scope_id
            ]
            return targets

        # scope == "org": todas las workstations online de la organización
        targets = [
            ws_id
            for ws_id, ws_org_id in cm.org_ids.items()
            if ws_org_id == org_id and ws_id in cm.workstation_connections
        ]
        return targets

    async def push_config_change(
        self,
        org_id: str,
        config_hash: str,
        download_url: str,
        scope: str,
        scope_id: str | None,
    ) -> int:
        """
        Envía Config_Push_Message a workstations afectadas por un cambio de config.

        El mensaje sigue el formato Config_Push_Message del diseño:
        {
            "type": "action_config_changed",
            "data": {
                "config_hash": "a1b2c3d4",
                "download_url": "https://bucket.s3.amazonaws.com/configs/org/hash.signed"
            }
        }

        Zero queries a BD — config_hash y download_url provienen del caller,
        las workstations destino se obtienen del connection_manager en memoria.

        Args:
            org_id: UUID de la organización afectada.
            config_hash: Hash SHA256 corto (8 chars) de la config activada.
            download_url: URL pública S3 del archivo .signed para descarga directa.
            scope: Scope del cambio ("org", "vlan", "workstation").
            scope_id: ID del scope (vlan_id o workstation_id). None para scope "org".

        Returns:
            Número de workstations a las que se envió el mensaje.
        """
        # Obtener workstations destino según scope (sin queries a BD)
        target_ws_ids = self._get_target_workstations(org_id, scope, scope_id)

        if not target_ws_ids:
            logger.info(
                "push.config_sin_destinos",
                org_id=org_id,
                scope=scope,
                scope_id=scope_id,
                config_hash=config_hash,
                msg="No hay workstations online para este scope",
            )
            return 0

        # Construir mensaje Config_Push_Message
        message = {
            "type": "action_config_changed",
            "data": {
                "config_hash": config_hash,
                "download_url": download_url,
            },
        }

        # Enviar a cada workstation destino (fire-and-forget)
        enviados = 0
        for ws_id in target_ws_ids:
            try:
                sent = await self._connection_manager.send_to_workstation(ws_id, message)
                if sent:
                    enviados += 1
            except Exception as e:
                logger.warning(
                    "push.config_envio_fallido",
                    workstation_id=ws_id,
                    org_id=org_id,
                    error=str(e),
                )

        logger.info(
            "push.config_enviado",
            org_id=org_id,
            scope=scope,
            scope_id=scope_id,
            config_hash=config_hash,
            total_destinos=len(target_ws_ids),
            enviados=enviados,
        )

        return enviados

    async def push_msi_update(
        self,
        org_id: str,
        msi_version: str,
        download_url: str,
        file_size: int,
    ) -> int:
        """
        Envía MSI_Push_Message a todas las workstations online de la organización.

        El mensaje sigue el formato MSI_Push_Message del diseño:
        {
            "type": "check_update",
            "data": {
                "version": "2.1.0",
                "download_url": "https://bucket.s3.amazonaws.com/versions/2.1.0/AlwaysPrint.msi?presigned",
                "file_size": 15728640
            }
        }

        MSI siempre se distribuye a nivel org (todas las WS online reciben el push).
        Zero queries a BD — los datos provienen del caller y las workstations
        destino se obtienen del connection_manager en memoria.

        Args:
            org_id: UUID de la organización.
            msi_version: Versión del MSI a distribuir (ej: "2.1.0").
            download_url: Presigned URL de S3 para descarga del MSI.
            file_size: Tamaño del archivo MSI en bytes.

        Returns:
            Número de workstations a las que se envió el mensaje exitosamente.
        """
        # MSI siempre a nivel org
        target_ws_ids = self._get_target_workstations(org_id, "org", None)

        if not target_ws_ids:
            logger.info(
                "push.msi_sin_destinos",
                org_id=org_id,
                msi_version=msi_version,
                msg="No hay workstations online para recibir actualización MSI",
            )
            return 0

        # Construir mensaje MSI_Push_Message
        message = {
            "type": "check_update",
            "data": {
                "version": msi_version,
                "download_url": download_url,
                "file_size": file_size,
            },
        }

        # Enviar a cada workstation destino (tolerante a fallos parciales)
        enviados = 0
        for ws_id in target_ws_ids:
            try:
                sent = await self._connection_manager.send_to_workstation(ws_id, message)
                if sent:
                    enviados += 1
            except Exception as e:
                logger.warning(
                    "push.msi_envio_fallido",
                    workstation_id=ws_id,
                    org_id=org_id,
                    msi_version=msi_version,
                    error=str(e),
                )

        logger.info(
            "push.msi_enviado",
            org_id=org_id,
            msi_version=msi_version,
            file_size=file_size,
            total_destinos=len(target_ws_ids),
            enviados=enviados,
        )

        return enviados

    async def push_cert_rotation(
        self,
        org_id: str,
        cert_version: int,
        cert_url: str,
    ) -> int:
        """
        Envía Cert_Push_Message a todas las workstations online de la organización.

        El mensaje sigue el formato Cert_Push_Message del diseño:
        {
            "type": "cert_rotated",
            "data": {
                "cert_version": 3,
                "cert_url": "https://bucket.s3.amazonaws.com/certs/org/v3.cer"
            }
        }

        La rotación de certificado siempre es a nivel org (todas las WS online
        reciben el nuevo certificado). Zero queries a BD — los datos provienen
        del caller y las workstations destino se obtienen del connection_manager.

        Args:
            org_id: UUID de la organización.
            cert_version: Versión del certificado rotado.
            cert_url: URL pública S3 del nuevo certificado .cer.

        Returns:
            Número de workstations a las que se envió el mensaje exitosamente.
        """
        # Certificado siempre a nivel org
        target_ws_ids = self._get_target_workstations(org_id, "org", None)

        if not target_ws_ids:
            logger.info(
                "push.cert_sin_destinos",
                org_id=org_id,
                cert_version=cert_version,
                msg="No hay workstations online para recibir rotación de certificado",
            )
            return 0

        # Construir mensaje Cert_Push_Message
        message = {
            "type": "cert_rotated",
            "data": {
                "cert_version": cert_version,
                "cert_url": cert_url,
            },
        }

        # Enviar a cada workstation destino (tolerante a fallos parciales)
        enviados = 0
        for ws_id in target_ws_ids:
            try:
                sent = await self._connection_manager.send_to_workstation(ws_id, message)
                if sent:
                    enviados += 1
            except Exception as e:
                logger.warning(
                    "push.cert_envio_fallido",
                    workstation_id=ws_id,
                    org_id=org_id,
                    cert_version=cert_version,
                    error=str(e),
                )

        logger.info(
            "push.cert_enviado",
            org_id=org_id,
            cert_version=cert_version,
            cert_url=cert_url,
            total_destinos=len(target_ws_ids),
            enviados=enviados,
        )

        return enviados
