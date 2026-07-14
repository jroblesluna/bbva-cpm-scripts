"""
Servicio de limpieza periódica de sesiones de vista remota expiradas.

Este módulo implementa RemoteViewCleanup que programa la limpieza
automática de sesiones cada 60 segundos usando APScheduler (AsyncIOScheduler).

Lógica:
- Sesiones 'active' con last_activity_at < NOW() - 5 min → expired (timeout)
- Sesiones 'pending_consent' con started_at < NOW() - 35s → rejected (user_timeout)
- Para cada sesión afectada, envía remote_view_stop a la workstation vía WebSocket

Características:
- Integración con el lifespan de FastAPI (start/stop)
- Protección contra ejecuciones concurrentes (asyncio.Lock)
- Singleton a nivel de módulo
"""

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.database import SessionLocal
from app.services.remote_view_session import SessionManager
from app.services.websocket_manager import connection_manager

# Configurar logger para el módulo
logger = logging.getLogger(__name__)

# Intervalo de limpieza en segundos
CLEANUP_INTERVAL_SECONDS = 60


class RemoteViewCleanup:
    """
    Programa limpieza periódica de sesiones de vista remota expiradas.

    Utiliza APScheduler (AsyncIOScheduler) para ejecutar la limpieza
    cada 60 segundos. Protege contra ejecuciones concurrentes usando
    asyncio.Lock.
    """

    def __init__(self):
        """Inicializa el scheduler con lock de concurrencia."""
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._lock = asyncio.Lock()
        self._session_manager = SessionManager()

    def start(self) -> None:
        """
        Registra el job de limpieza y arranca el scheduler.

        Programa ejecución cada 60 segundos.
        """
        self._scheduler.add_job(
            self._run_cleanup,
            "interval",
            seconds=CLEANUP_INTERVAL_SECONDS,
            id="remote_view_cleanup",
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info("Scheduler de limpieza de vista remota iniciado (cada %ds)", CLEANUP_INTERVAL_SECONDS)

    def stop(self) -> None:
        """Detiene el scheduler de limpieza."""
        self._scheduler.shutdown(wait=False)
        logger.info("Scheduler de limpieza de vista remota detenido")

    async def _run_cleanup(self) -> None:
        """
        Ejecuta la limpieza de sesiones expiradas.

        Protegido con asyncio.Lock para evitar ejecuciones concurrentes.
        Para cada sesión afectada, envía remote_view_stop a la workstation.
        """
        if self._lock.locked():
            logger.debug("Limpieza de vista remota ya en ejecución, omitiendo ciclo")
            return

        async with self._lock:
            db = SessionLocal()
            try:
                affected_sessions = self._session_manager.cleanup_expired(db)

                if affected_sessions:
                    logger.info(
                        "Limpieza de vista remota: %d sesiones expiradas/rechazadas",
                        len(affected_sessions),
                    )

                    # Enviar remote_view_stop a cada workstation afectada
                    for session in affected_sessions:
                        try:
                            message = {
                                "type": "remote_view_stop",
                                "session_id": str(session.id),
                                "reason": session.end_reason or "timeout",
                            }
                            await connection_manager.send_to_workstation(
                                str(session.workstation_id), message
                            )
                            logger.debug(
                                "Enviado remote_view_stop a workstation %s (sesión %s, razón: %s)",
                                session.workstation_id,
                                session.id,
                                session.end_reason,
                            )
                        except Exception as e:
                            logger.warning(
                                "Error al enviar remote_view_stop a workstation %s: %s",
                                session.workstation_id,
                                str(e),
                            )
                else:
                    logger.debug("Limpieza de vista remota: sin sesiones expiradas")

            except Exception as e:
                logger.error("Error durante limpieza de sesiones de vista remota: %s", str(e))
            finally:
                db.close()


# Singleton a nivel de módulo
remote_view_cleanup = RemoteViewCleanup()
