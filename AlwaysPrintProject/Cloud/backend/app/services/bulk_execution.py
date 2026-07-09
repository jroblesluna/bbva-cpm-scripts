"""
Servicio de ejecución masiva de acciones OnDemand.

Orquesta la ejecución masiva de comandos execute_on_demand contra todas las
workstations online de una organización, con throttling configurable, progreso
en tiempo real vía WebSocket, y cancelación.

Métodos del servicio:
    - get_available_actions: Extrae acciones OnDemand del alwaysconfig activo
    - validate_label: Valida que un label OnDemand existe en la config activa
    - get_preview: Preview con conteo de workstations y tiempo estimado (Task 3.1)
    - start_session: Inicia ejecución masiva con mutex Redis (Task 3.1)
    - cancel_session: Cancela ejecución en curso (Task 3.3)
    - get_session_status: Consulta estado de una Bulk_Session (Task 3.1)
    - _execute_bulk: Background task de ejecución throttled (Task 3.2)
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Tuple
from uuid import UUID, uuid4

import redis.asyncio as aioredis
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.audit import ActionType
from app.schemas.bulk_actions import (
    BulkPreview,
    BulkSessionStatus,
    BulkStartResponse,
    OnDemandAction,
)
from app.services.action_config import ActionConfigService
from app.services.audit import AuditService

logger = logging.getLogger(__name__)


class BulkExecutionService:
    """
    Orquesta la ejecución masiva de acciones OnDemand con throttling.

    Responsabilidades:
        - Extraer acciones OnDemand disponibles del alwaysconfig activo de la org
        - Validar que un label existe en la configuración activa
        - Gestionar sesiones de ejecución masiva (inicio, progreso, cancelación)
        - Enviar comandos execute_on_demand con delay configurable entre envíos
        - Reportar progreso en tiempo real vía WebSocket a operadores
        - Registrar auditoría de cada sesión
    """

    def get_available_actions(self, org_id: UUID, db: Session) -> list[OnDemandAction]:
        """
        Extrae las acciones OnDemand disponibles del alwaysconfig activo de la organización.

        Parsea el campo config_json de la configuración activa (scope=org) y retorna
        los triggers con event == "OnDemand" y label no vacío.

        Args:
            org_id: ID de la organización
            db: Sesión de base de datos

        Returns:
            Lista de OnDemandAction con label y description

        Raises:
            HTTPException 404: Si la organización no tiene configuración activa
        """
        # Obtener configuración activa de la organización (scope=org)
        active_config = ActionConfigService.get_active_config(
            db, organization_id=org_id, scope="org"
        )

        if active_config is None:
            logger.warning(
                f"Organización {org_id} no tiene configuración activa (scope=org)"
            )
            raise HTTPException(
                status_code=404,
                detail="No hay configuración activa para la organización",
            )

        # Extraer acciones OnDemand del JSON de configuración
        return self._extract_ondemand_actions(active_config.config_json)

    def validate_label(self, org_id: UUID, label: str, db: Session) -> OnDemandAction:
        """
        Valida que un label de acción OnDemand existe en el alwaysconfig activo.

        Args:
            org_id: ID de la organización
            label: Label de la acción OnDemand a validar
            db: Sesión de base de datos

        Returns:
            OnDemandAction correspondiente al label validado

        Raises:
            HTTPException 404: Si la organización no tiene config activa
            HTTPException 422: Si el label no existe en la configuración activa
        """
        available_actions = self.get_available_actions(org_id, db)

        for action in available_actions:
            if action.label == label:
                return action

        raise HTTPException(
            status_code=422,
            detail=f"La acción OnDemand '{label}' no existe en la configuración activa",
        )

    @staticmethod
    def _extract_ondemand_actions(config_json: str) -> list[OnDemandAction]:
        """
        Extrae las acciones OnDemand de un JSON de configuración alwaysconfig.

        Filtra triggers donde event == "OnDemand" y label es un string no vacío.

        Args:
            config_json: JSON string del alwaysconfig

        Returns:
            Lista de OnDemandAction extraídas
        """
        try:
            config_data = json.loads(config_json)
        except (json.JSONDecodeError, TypeError):
            logger.warning("No se pudo parsear el JSON del alwaysconfig")
            return []

        triggers = config_data.get("triggers", [])
        if not isinstance(triggers, list):
            return []

        actions: list[OnDemandAction] = []
        for trigger in triggers:
            if not isinstance(trigger, dict):
                continue

            event = trigger.get("event")
            label = trigger.get("label")

            # Solo incluir triggers OnDemand con label definido y no vacío
            if event == "OnDemand" and isinstance(label, str) and label.strip():
                actions.append(
                    OnDemandAction(
                        label=label,
                        description=trigger.get("description"),
                    )
                )

        return actions

    # =========================================================================
    # PREVIEW, SESIÓN Y ESTADO (Task 3.1)
    # =========================================================================

    async def get_preview(
        self, org_id: UUID, label: str, delay_ms: int, db: Session
    ) -> BulkPreview:
        """
        Genera un preview de la ejecución masiva.

        Calcula el tiempo estimado basado en la fórmula:
        (workstations_online - 1) * delay_ms

        Args:
            org_id: ID de la organización
            label: Label de la acción OnDemand a ejecutar
            delay_ms: Delay en milisegundos entre envíos
            db: Sesión de base de datos

        Returns:
            BulkPreview con información estimada

        Raises:
            HTTPException 404: Si no hay config activa
            HTTPException 422: Si el label no existe
        """
        # Validar que el label existe en la config activa
        action = self.validate_label(org_id, label, db)

        # Contar workstations online de la organización
        from app.services.websocket_manager import connection_manager

        workstations_online = await self._count_online_workstations(
            org_id, connection_manager, db
        )

        # Calcular tiempo estimado: (workstations_online - 1) * delay_ms
        estimated_time_ms = max(0, (workstations_online - 1)) * delay_ms

        return BulkPreview(
            action_label=action.label,
            action_description=action.description,
            workstations_online=workstations_online,
            estimated_time_ms=estimated_time_ms,
        )

    async def start_session(
        self,
        org_id: UUID,
        label: str,
        delay_ms: int,
        user_id: UUID,
        db: Session,
    ) -> Tuple[BulkStartResponse, list[str]]:
        """
        Inicia una sesión de ejecución masiva.

        1. Verifica mutex (solo una sesión running por org)
        2. Valida el label contra config activa
        3. Crea hash Redis con estado running
        4. Retorna BulkStartResponse y lista de workstation_ids

        Args:
            org_id: ID de la organización
            label: Label de la acción OnDemand a ejecutar
            delay_ms: Delay en milisegundos entre envíos
            user_id: ID del usuario que inicia la sesión
            db: Sesión de base de datos

        Returns:
            Tupla (BulkStartResponse, lista de workstation_ids para el background task)

        Raises:
            HTTPException 409: Si ya existe una sesión running para la org
            HTTPException 404: Si no hay config activa
            HTTPException 422: Si el label no existe
            HTTPException 503: Si Redis no está disponible
        """
        redis_client = self._get_redis_client()

        try:
            mutex_key = f"bulk:running:{org_id}"

            # Verificar mutex — si existe, otra sesión está en curso
            existing = await redis_client.get(mutex_key)
            if existing:
                raise HTTPException(
                    status_code=409,
                    detail="Ya existe una ejecución masiva en curso para esta organización",
                )

            # Validar label contra config activa
            self.validate_label(org_id, label, db)

            # Obtener IDs de workstations online de la organización
            from app.services.websocket_manager import connection_manager

            workstation_ids = await self._get_online_workstation_ids(
                org_id, connection_manager, db
            )
            total = len(workstation_ids)

            # No permitir iniciar si no hay workstations online
            if total == 0:
                raise HTTPException(
                    status_code=422,
                    detail="No hay workstations online en la organización para ejecutar la acción",
                )

            # Crear sesión
            session_id = uuid4()
            started_at = datetime.now(timezone.utc).replace(tzinfo=None)

            # Establecer mutex con TTL de 30 minutos
            await redis_client.set(mutex_key, str(session_id), ex=1800)

            # Crear hash de sesión en Redis
            session_key = f"bulk:session:{session_id}"
            session_data = {
                "status": "running",
                "total": str(total),
                "sent": "0",
                "success": "0",
                "errors": "0",
                "failed_workstations": "[]",
                "org_id": str(org_id),
                "label": label,
                "delay_ms": str(delay_ms),
                "started_at": started_at.isoformat(),
                "user_id": str(user_id),
            }
            await redis_client.hset(session_key, mapping=session_data)
            # TTL de 1 hora para la sesión
            await redis_client.expire(session_key, 3600)

            response = BulkStartResponse(
                session_id=session_id,
                total=total,
                started_at=started_at,
            )

            # --- Registro de auditoría al inicio de sesión bulk ---
            try:
                audit_service = AuditService()
                audit_service.log_action(
                    db=db,
                    action_type=ActionType.ONDEMAND_EXECUTED,
                    entity_type="BulkSession",
                    entity_id=str(session_id),
                    user_id=str(user_id),
                    organization_id=str(org_id),
                    new_values={
                        "action": "bulk_start",
                        "label": label,
                        "delay_ms": delay_ms,
                        "total_workstations": total,
                    },
                )
            except Exception as e:
                logger.error(
                    f"Error registrando auditoría de inicio de sesión bulk: {e}"
                )

            return response, workstation_ids

        finally:
            await redis_client.aclose()

    async def get_session_status(
        self, session_id: UUID, org_id: UUID = None
    ) -> BulkSessionStatus:
        """
        Obtiene el estado actual de una Bulk_Session desde Redis.

        Args:
            session_id: ID de la sesión a consultar
            org_id: ID de la organización (para validación de tenant).
                    Si es None, se omite la verificación (admin access).

        Returns:
            BulkSessionStatus con métricas actuales

        Raises:
            HTTPException 404: Si la sesión no existe
            HTTPException 403: Si la organización no coincide (tenant isolation)
            HTTPException 503: Si Redis no está disponible
        """
        redis_client = self._get_redis_client()

        try:
            session_key = f"bulk:session:{session_id}"
            data = await redis_client.hgetall(session_key)

            if not data:
                raise HTTPException(
                    status_code=404, detail="Sesión no encontrada"
                )

            # Verificar tenant isolation — solo si org_id se proporciona
            if org_id is not None and data.get("org_id") != str(org_id):
                raise HTTPException(
                    status_code=403,
                    detail="No tienes permisos para esta organización",
                )

            # Calcular tiempo transcurrido
            started_at = datetime.fromisoformat(data["started_at"])
            elapsed_ms = int(
                (
                    datetime.now(timezone.utc).replace(tzinfo=None) - started_at
                ).total_seconds()
                * 1000
            )

            return BulkSessionStatus(
                session_id=session_id,
                status=data["status"],
                total=int(data["total"]),
                sent=int(data["sent"]),
                success=int(data["success"]),
                errors=int(data["errors"]),
                failed_workstations=json.loads(
                    data.get("failed_workstations", "[]")
                ),
                started_at=started_at,
                elapsed_ms=elapsed_ms,
            )

        finally:
            await redis_client.aclose()

    async def cancel_session(
        self, session_id: UUID, org_id: UUID = None
    ) -> BulkSessionStatus:
        """
        Cancela una sesión de ejecución masiva en curso.

        Establece un flag de cancelación en Redis que el background task
        verifica antes de cada envío. La transición de estado real a 'cancelled'
        la realiza _execute_bulk al detectar el flag.

        Args:
            session_id: ID de la sesión a cancelar
            org_id: ID de la organización (tenant isolation).
                    Si es None, se omite la verificación (admin access).

        Returns:
            BulkSessionStatus con el estado actual de la sesión

        Raises:
            HTTPException 404: Si la sesión no existe
            HTTPException 403: Si la organización no coincide
            HTTPException 409: Si la sesión no está en estado 'running'
        """
        redis_client = self._get_redis_client()

        try:
            session_key = f"bulk:session:{session_id}"
            data = await redis_client.hgetall(session_key)

            # Verificar que la sesión existe
            if not data:
                raise HTTPException(
                    status_code=404, detail="Sesión no encontrada"
                )

            # Verificar tenant isolation — solo si org_id se proporciona
            if org_id is not None and data.get("org_id") != str(org_id):
                raise HTTPException(
                    status_code=403,
                    detail="No tienes permisos para esta organización",
                )

            # Verificar que la sesión está en estado 'running'
            if data.get("status") != "running":
                raise HTTPException(
                    status_code=409,
                    detail="La sesión no está en estado ejecutable",
                )

            # Establecer flag de cancelación con TTL de 5 minutos
            cancel_key = f"bulk:cancel:{session_id}"
            await redis_client.set(cancel_key, "1", ex=300)

            logger.info(
                f"Señal de cancelación enviada para sesión {session_id} "
                f"(org={org_id})"
            )

            # Retornar estado actual (aún puede mostrar 'running' hasta que
            # el background task procese la cancelación)
            started_at = datetime.fromisoformat(data["started_at"])
            elapsed_ms = int(
                (
                    datetime.now(timezone.utc).replace(tzinfo=None) - started_at
                ).total_seconds()
                * 1000
            )

            return BulkSessionStatus(
                session_id=session_id,
                status=data["status"],
                total=int(data["total"]),
                sent=int(data["sent"]),
                success=int(data["success"]),
                errors=int(data["errors"]),
                failed_workstations=json.loads(
                    data.get("failed_workstations", "[]")
                ),
                started_at=started_at,
                elapsed_ms=elapsed_ms,
            )

        finally:
            await redis_client.aclose()

    # =========================================================================
    # MÉTODOS INTERNOS
    # =========================================================================

    @staticmethod
    def _get_redis_client() -> aioredis.Redis:
        """
        Crea un cliente Redis async para operaciones de bulk.

        Returns:
            Cliente Redis configurado

        Raises:
            HTTPException 503: Si REDIS_URL no está configurado
        """
        if not settings.REDIS_URL:
            raise HTTPException(
                status_code=503,
                detail="Servicio temporalmente no disponible",
            )
        return aioredis.from_url(settings.REDIS_URL, decode_responses=True)

    @staticmethod
    async def _count_online_workstations(org_id: UUID, connection_manager, db: Session = None) -> int:
        """
        Cuenta workstations online de una organización (cross-worker).

        Usa get_global_online_snapshot_async() para obtener todas las WS online
        de todos los workers, luego filtra por organización consultando la BD.

        Args:
            org_id: ID de la organización
            connection_manager: Instancia del ConnectionManager/RedisConnectionManager
            db: Sesión de BD para filtrar por org (opcional, usa query si disponible)

        Returns:
            Cantidad de workstations online de la organización
        """
        # Obtener snapshot global de WS online (todos los workers)
        all_online = await connection_manager.get_global_online_snapshot_async()

        if not all_online:
            return 0

        # Filtrar por organización usando la BD
        if db:
            from app.models.workstation import Workstation
            count = db.query(Workstation).filter(
                Workstation.organization_id == org_id,
                Workstation.id.in_(list(all_online)),
            ).count()
            return count

        # Fallback: usar org_ids local (puede ser incompleto en multi-worker)
        org_id_str = str(org_id)
        count = 0
        for ws_id in all_online:
            if connection_manager.org_ids.get(ws_id) == org_id_str:
                count += 1
        return count

    @staticmethod
    async def _get_online_workstation_ids(org_id: UUID, connection_manager, db: Session = None) -> list[str]:
        """
        Obtiene IDs de workstations online de una organización (cross-worker).

        Usa get_global_online_snapshot_async() para obtener todas las WS online
        de todos los workers, luego filtra por organización consultando la BD.

        Args:
            org_id: ID de la organización
            connection_manager: Instancia del ConnectionManager/RedisConnectionManager
            db: Sesión de BD para filtrar por org

        Returns:
            Lista de workstation_ids online de la organización
        """
        # Obtener snapshot global de WS online (todos los workers)
        all_online = await connection_manager.get_global_online_snapshot_async()

        if not all_online:
            return []

        # Filtrar por organización usando la BD
        if db:
            from app.models.workstation import Workstation
            rows = db.query(Workstation.id).filter(
                Workstation.organization_id == org_id,
                Workstation.id.in_(list(all_online)),
            ).all()
            return [str(row[0]) for row in rows]

        # Fallback: usar org_ids local (puede ser incompleto en multi-worker)
        org_id_str = str(org_id)
        return [ws_id for ws_id in all_online if connection_manager.org_ids.get(ws_id) == org_id_str]

    # =========================================================================
    # BACKGROUND TASK DE EJECUCIÓN THROTTLED (Task 3.2)
    # =========================================================================

    async def _execute_bulk(
        self,
        session_id: UUID,
        org_id: UUID,
        label: str,
        delay_ms: int,
        workstation_ids: list[str],
    ) -> None:
        """
        Background task que ejecuta la ejecución masiva throttled.

        Este método es diseñado para ejecutarse como asyncio.Task en el worker
        que recibe la solicitud de inicio. No se distribuye entre workers porque
        el throttling exige control secuencial.

        Itera la lista de workstations enviando execute_on_demand con delay
        configurable, actualizando métricas en Redis y reportando progreso
        vía WebSocket a operadores.

        Args:
            session_id: ID de la sesión bulk
            org_id: ID de la organización
            label: Label de la acción OnDemand a ejecutar
            delay_ms: Delay en milisegundos entre envíos
            workstation_ids: Lista de IDs de workstations a procesar
        """
        from app.services.websocket_manager import connection_manager

        redis_client = self._get_redis_client()
        session_key = f"bulk:session:{session_id}"
        mutex_key = f"bulk:running:{org_id}"
        cancel_key = f"bulk:cancel:{session_id}"

        # Contadores de progreso
        total = len(workstation_ids)
        sent = 0
        success = 0
        errors = 0
        failed_ws: list[str] = []

        # Timestamp de inicio para calcular elapsed_ms
        started_at = time.time()
        # Última renovación de mutex (cada 5 minutos)
        last_mutex_renewal = time.time()
        # Intervalo de renovación de mutex: 5 minutos
        mutex_renewal_interval = 300

        cancelled = False

        try:
            for idx, ws_id in enumerate(workstation_ids):
                # --- Verificar flag de cancelación antes de cada envío ---
                cancel_flag = await redis_client.get(cancel_key)
                if cancel_flag:
                    cancelled = True
                    # Actualizar estado a cancelled en Redis
                    await redis_client.hset(session_key, "status", "cancelled")
                    logger.info(
                        f"Bulk session {session_id} cancelada en envío "
                        f"{sent}/{total}"
                    )
                    break

                # --- Enviar comando execute_on_demand a la workstation ---
                command_message = {
                    "type": "command",
                    "command_id": str(uuid4()),
                    "command": "execute_on_demand",
                    "params": {"label": label},
                }

                try:
                    send_result = await connection_manager.send_to_workstation(
                        ws_id, command_message
                    )
                    if send_result:
                        success += 1
                    else:
                        errors += 1
                        failed_ws.append(ws_id)
                except Exception as e:
                    logger.warning(
                        f"Error enviando a workstation {ws_id}: {e}"
                    )
                    errors += 1
                    failed_ws.append(ws_id)

                sent += 1

                # --- Actualizar métricas en Redis ---
                elapsed_ms = int((time.time() - started_at) * 1000)
                await redis_client.hset(
                    session_key,
                    mapping={
                        "sent": str(sent),
                        "success": str(success),
                        "errors": str(errors),
                        "failed_workstations": json.dumps(failed_ws),
                    },
                )

                # --- Enviar progress report vía WebSocket a operadores ---
                progress_report = {
                    "type": "bulk_progress",
                    "session_id": str(session_id),
                    "status": "running",
                    "total": total,
                    "sent": sent,
                    "success": success,
                    "errors": errors,
                    "failed_workstations": failed_ws,
                    "elapsed_ms": elapsed_ms,
                }
                await connection_manager.broadcast_to_organization(
                    str(org_id), progress_report
                )

                # --- Renovar TTL del mutex si han pasado 5 minutos ---
                now = time.time()
                if (now - last_mutex_renewal) >= mutex_renewal_interval:
                    await redis_client.expire(mutex_key, 1800)
                    last_mutex_renewal = now
                    logger.debug(
                        f"Bulk session {session_id}: mutex TTL renovado"
                    )

                # --- Aplicar delay entre envíos (excepto después del último) ---
                if idx < total - 1:
                    await asyncio.sleep(delay_ms / 1000)

            # --- Finalización del loop ---
            elapsed_ms = int((time.time() - started_at) * 1000)

            if not cancelled:
                # Marcar sesión como completada
                await redis_client.hset(session_key, "status", "completed")
                final_status = "completed"
            else:
                final_status = "cancelled"

            # Eliminar mutex — liberar para futuras sesiones
            await redis_client.delete(mutex_key)

            # Enviar progress report final
            final_report = {
                "type": "bulk_progress",
                "session_id": str(session_id),
                "status": final_status,
                "total": total,
                "sent": sent,
                "success": success,
                "errors": errors,
                "failed_workstations": failed_ws,
                "elapsed_ms": elapsed_ms,
            }
            await connection_manager.broadcast_to_organization(
                str(org_id), final_report
            )

            logger.info(
                f"Bulk session {session_id} finalizada: status={final_status}, "
                f"sent={sent}/{total}, success={success}, errors={errors}, "
                f"elapsed={elapsed_ms}ms"
            )

            # --- Registro de auditoría al finalizar sesión bulk ---
            try:
                audit_db = SessionLocal()
                try:
                    audit_service = AuditService()
                    # Recuperar user_id del hash Redis de la sesión
                    data = await redis_client.hgetall(session_key)
                    session_user_id = data.get("user_id", "")

                    audit_service.log_action(
                        db=audit_db,
                        action_type=ActionType.ONDEMAND_EXECUTED,
                        entity_type="BulkSession",
                        entity_id=str(session_id),
                        user_id=session_user_id,
                        organization_id=str(org_id),
                        new_values={
                            "action": "bulk_complete",
                            "final_status": final_status,
                            "duration_ms": elapsed_ms,
                            "success": success,
                            "errors": errors,
                            "total": total,
                        },
                    )
                finally:
                    audit_db.close()
            except Exception as e:
                logger.error(
                    f"Error registrando auditoría de fin de sesión bulk: {e}"
                )

        except Exception as e:
            # Error inesperado — intentar marcar como failed y liberar mutex
            logger.error(
                f"Error inesperado en bulk session {session_id}: {e}",
                exc_info=True,
            )
            try:
                await redis_client.hset(session_key, "status", "failed")
                await redis_client.delete(mutex_key)
            except Exception:
                logger.error(
                    f"No se pudo actualizar estado de sesión {session_id} "
                    f"tras error inesperado"
                )

        finally:
            await redis_client.aclose()
