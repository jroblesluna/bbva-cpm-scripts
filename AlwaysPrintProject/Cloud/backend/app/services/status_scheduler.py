"""
Scheduler para la recolección periódica de métricas del sistema.

Este módulo implementa la clase StatusScheduler que programa la ejecución
automática del SystemStatusCollector cada 6 horas (0:00, 6:00, 12:00, 18:00 UTC)
usando APScheduler (AsyncIOScheduler).

Características:
- Integración con el lifespan de FastAPI (start/stop)
- Protección contra ejecuciones concurrentes (asyncio.Lock)
- Reintento: si falla, reintentar una vez después de 5 minutos
- Timeout de 10 minutos por ejecución
- Método trigger_manual_collection() para ejecución bajo demanda
- Retorna HTTP 409 si ya hay ejecución en curso
- Singleton a nivel de módulo
"""

import asyncio
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.system_status import StatusSnapshot
from app.services.system_status import SystemStatusCollector

# Configurar logger para el módulo
logger = logging.getLogger(__name__)

# Timeout de 10 minutos para cada ejecución (en segundos)
EXECUTION_TIMEOUT = 600

# Tiempo de espera antes de reintentar (en segundos)
RETRY_DELAY = 300  # 5 minutos


class StatusScheduler:
    """
    Programa ejecuciones cada 6 horas y gestiona ejecuciones manuales.

    Utiliza APScheduler (AsyncIOScheduler) para programar la recolección
    automática de métricas. Protege contra ejecuciones concurrentes usando
    asyncio.Lock y soporta reintentos en caso de fallo.
    """

    def __init__(self):
        """Inicializa el scheduler con lock de concurrencia y estado."""
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._lock = asyncio.Lock()
        self._is_running = False
        self._collector = SystemStatusCollector()

    def start(self) -> None:
        """
        Registra los jobs cron y arranca el scheduler.

        Programa ejecuciones a las 0:00, 6:00, 12:00 y 18:00 UTC cada día.
        """
        # Programar ejecución cada 6 horas en las horas fijas
        self._scheduler.add_job(
            self._scheduled_collection,
            "cron",
            hour="0,6,12,18",
            minute=0,
            id="system_status_collection",
            replace_existing=True,
            name="Recolección programada de métricas del sistema",
        )

        self._scheduler.start()
        logger.info(
            "StatusScheduler iniciado. Ejecuciones programadas: 0:00, 6:00, 12:00, 18:00 UTC"
        )

    def stop(self) -> None:
        """Detiene el scheduler de forma limpia."""
        self._scheduler.shutdown(wait=False)
        logger.info("StatusScheduler detenido")

    @property
    def is_running(self) -> bool:
        """Indica si hay una recolección en progreso."""
        return self._is_running

    async def trigger_manual_collection(self, db: Session) -> StatusSnapshot:
        """
        Ejecuta una recolección manual bajo demanda.

        Adquiere el lock de concurrencia. Si ya hay una ejecución en curso,
        lanza HTTP 409 Conflict. Aplica timeout de 10 minutos.

        Args:
            db: Sesión de SQLAlchemy para persistencia

        Returns:
            StatusSnapshot creado con los datos recolectados

        Raises:
            HTTPException: 409 si ya hay una ejecución en curso
            HTTPException: 500 si la recolección falla o excede el timeout
        """
        # Verificar si ya hay una ejecución en curso sin bloquear
        if self._lock.locked():
            logger.info(
                "Solicitud de recolección manual rechazada: ya hay una ejecución en curso"
            )
            raise HTTPException(
                status_code=409,
                detail="Ya hay una recolección en curso. Intente nuevamente más tarde.",
            )

        async with self._lock:
            self._is_running = True
            try:
                snapshot = await asyncio.wait_for(
                    self._execute_collection(db),
                    timeout=EXECUTION_TIMEOUT,
                )
                return snapshot
            except asyncio.TimeoutError:
                logger.error(
                    "Recolección manual cancelada: excedió el timeout de 10 minutos"
                )
                raise HTTPException(
                    status_code=500,
                    detail="La recolección excedió el tiempo máximo de 10 minutos.",
                )
            except HTTPException:
                # Re-lanzar HTTPExceptions sin envolver
                raise
            except Exception as e:
                logger.error(f"Error en recolección manual: {e}")
                raise HTTPException(
                    status_code=500,
                    detail="Error en la recolección de métricas.",
                )
            finally:
                self._is_running = False

    async def _scheduled_collection(self) -> None:
        """
        Ejecuta la recolección programada con protección de concurrencia y reintento.

        Si ya hay una ejecución en curso, se descarta la ejecución programada.
        Si la ejecución falla o excede el timeout, se reintenta una vez después
        de 5 minutos. Si el reintento también falla, se espera a la siguiente
        ejecución programada.
        """
        # Si ya hay una ejecución en curso, descartar
        if self._lock.locked():
            logger.info(
                "Ejecución programada descartada: ya hay una recolección en curso"
            )
            return

        # Primer intento
        success = await self._attempt_scheduled_collection()

        if not success:
            # Esperar 5 minutos y reintentar una vez
            logger.info(
                f"Reintentando recolección programada en {RETRY_DELAY // 60} minutos..."
            )
            await asyncio.sleep(RETRY_DELAY)

            # Verificar de nuevo si hay ejecución en curso antes del reintento
            if self._lock.locked():
                logger.info(
                    "Reintento de recolección descartado: ya hay una ejecución en curso"
                )
                return

            retry_success = await self._attempt_scheduled_collection()
            if not retry_success:
                logger.critical(
                    "Recolección programada falló después del reintento. "
                    "Esperando siguiente ejecución programada."
                )

    async def _attempt_scheduled_collection(self) -> bool:
        """
        Intenta ejecutar una recolección programada.

        Crea su propia sesión de base de datos ya que las ejecuciones
        programadas no tienen acceso al contexto de request de FastAPI.

        Returns:
            True si la recolección fue exitosa, False en caso contrario
        """
        async with self._lock:
            self._is_running = True
            db = SessionLocal()
            try:
                await asyncio.wait_for(
                    self._execute_collection(db),
                    timeout=EXECUTION_TIMEOUT,
                )
                logger.info("Recolección programada completada exitosamente")
                return True
            except asyncio.TimeoutError:
                logger.error(
                    "Recolección programada cancelada: excedió el timeout de 10 minutos"
                )
                return False
            except Exception as e:
                logger.error(f"Error en recolección programada: {e}")
                return False
            finally:
                self._is_running = False
                db.close()

    async def _execute_collection(self, db: Session) -> StatusSnapshot:
        """
        Ejecuta la recolección completa y persiste el resultado.

        Orquesta el collector para obtener todas las métricas y luego
        persiste el snapshot en la base de datos. También ejecuta la
        limpieza de datos antiguos (>90 días).

        Args:
            db: Sesión de SQLAlchemy para persistencia

        Returns:
            StatusSnapshot creado con los datos recolectados

        Raises:
            Exception: Si la recolección o persistencia falla
        """
        timestamp = datetime.now(timezone.utc)

        # Ejecutar recolección completa
        result = await self._collector.collect_all(db)

        # Persistir snapshot en la base de datos
        snapshot = self._collector.save_snapshot(
            db=db,
            os_metrics=result["os_metrics"],
            docker_available=result["docker_available"],
            docker_metrics=result["docker_metrics"],
            health_checks=result["health_checks"],
            overall_status=result["overall_status"],
            alerts=result["alerts"],
            timestamp=timestamp,
        )

        if snapshot is None:
            raise Exception(
                "No se pudo persistir el snapshot después de agotar los reintentos"
            )

        # Limpieza de datos antiguos (>90 días)
        deleted = self._collector.cleanup_old_snapshots(db)
        if deleted > 0:
            logger.info(f"Limpieza automática: {deleted} snapshots antiguos eliminados")

        return snapshot


# === SINGLETON A NIVEL DE MÓDULO ===
# Instancia única del scheduler para toda la aplicación
status_scheduler = StatusScheduler()
