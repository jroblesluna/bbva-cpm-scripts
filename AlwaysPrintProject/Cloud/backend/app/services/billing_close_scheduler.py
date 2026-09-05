"""
Scheduler de cierre mensual automático del módulo Usage and Billing (task 26).

`BillingCloseScheduler` programa un cron HORARIO en UTC (patrón idéntico a
`status_scheduler`, ver `app/services/status_scheduler.py`) que, en cada ejecución,
detecta qué organizaciones acaban de cruzar la medianoche del día 1 en SU zona horaria
y aún no tienen cerrado el mes inmediatamente anterior. Un único scheduler UTC cubre
múltiples timezones sin necesidad de un cron por organización (ver `design.md`, sección
"Scheduler de cierre automático").

Diseño:
- `AsyncIOScheduler(timezone="UTC")`: reloj interno del scheduler en UTC (los cortes por
  organización se calculan en la tz de cada org dentro del handler).
- Cron horario (`minute=5`, cada hora): el margen de 5 minutos sobre la hora en punto evita
  correr justo en el instante de medianoche local de alguna zona y da holgura ante relojes
  ligeramente desfasados.
- Protección de concurrencia con `asyncio.Lock` (como `status_scheduler`): si ya hay una
  corrida en curso, la nueva se descarta (no se encolan cierres).
- Cada corrida crea su propia `SessionLocal`: las ejecuciones programadas no tienen contexto
  de request de FastAPI.
- Se reutiliza `BillingCloseService.close_month`, que ya garantiza idempotencia (Req 7.6) y
  secuencialidad (Req 7.4). El scheduler NO auto-rellena huecos: si detecta un salto
  (`BillingSequenceError`) lo registra y sigue; los cierres retroactivos son responsabilidad
  del endpoint superadmin (task 27).

Determinación del mes a cerrar (por organización, en su tz):
- El cierre del mes X se ejecuta a las 00:00 del día 1 de X+1 en la tz de la org. Por tanto,
  cuando el reloj local de la org ya entró en un nuevo mes, el mes recién terminado (el
  inmediatamente anterior al mes local actual) es el candidato a cerrarse.
- "mes recién terminado" = el mes anterior al mes local actual de la organización.
- Solo se intenta el cierre si ese mes aún no tiene cabecera (`BillingClosure`). El resto de
  guardas (idempotencia real y secuencialidad) las aplica `close_month` (fail-closed).

Principios del repo (impact-analysis):
- Fail-closed heredado del servicio: ante idempotencia/secuencialidad violada, el servicio
  lanza y aborta ese cierre concreto; el scheduler captura y continúa con las demás orgs.
- Tenant isolation: `close_month` opera por organización.
- Aislamiento de fallos: cada organización se envuelve en try/except para que el fallo de
  una no detenga el lote.
"""

import asyncio
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.models.billing import BillingClosure
from app.models.organization import Organization
from app.services.billing_close_service import (
    BillingAlreadyClosedError,
    BillingSequenceError,
    billing_close_service,
)

logger = get_logger(__name__)

# Timeout de 10 minutos para cada corrida completa (todas las orgs), en segundos.
EXECUTION_TIMEOUT = 600


class BillingCloseScheduler:
    """
    Programa el cierre mensual automático de todas las organizaciones activas.

    Utiliza APScheduler (`AsyncIOScheduler`) con un cron horario en UTC. En cada corrida
    revisa qué organizaciones ya cruzaron la medianoche del día 1 en su propia zona horaria
    y todavía no cerraron el mes anterior, e intenta cerrarlo reutilizando
    `BillingCloseService.close_month` (que impone idempotencia y secuencialidad).

    Es un componente sin estado de negocio: el estado vive en la base de datos. Solo mantiene
    el lock de concurrencia y el scheduler.
    """

    def __init__(self):
        """Inicializa el scheduler UTC y el lock de concurrencia."""
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._lock = asyncio.Lock()

    def start(self) -> None:
        """
        Registra el cron horario y arranca el scheduler.

        El job corre cada hora en el minuto 5 (margen sobre la medianoche local de cualquier
        zona). Un único scheduler UTC cubre todas las timezones.
        """
        self._scheduler.add_job(
            self._scheduled_close,
            "cron",
            minute=5,
            id="billing_close_monthly",
            replace_existing=True,
            name="Cierre mensual automático por organización (multi-timezone)",
        )
        self._scheduler.start()
        logger.info(
            "billing.scheduler_iniciado",
            detalle="Cron horario UTC (minuto 5) para cierres mensuales por timezone",
        )

    def stop(self) -> None:
        """Detiene el scheduler de forma limpia."""
        self._scheduler.shutdown(wait=False)
        logger.info("billing.scheduler_detenido")

    async def _scheduled_close(self) -> None:
        """
        Corrida programada: procesa todas las orgs con protección de concurrencia.

        Si ya hay una corrida en curso, se descarta esta (no se encolan cierres). Aplica un
        timeout global a la corrida; su expiración no deja estado inconsistente porque cada
        organización se cierra en su propia transacción única dentro de `close_month`.
        """
        if self._lock.locked():
            logger.info(
                "billing.scheduler_descartado",
                motivo="Ya hay una corrida de cierre en curso",
            )
            return

        async with self._lock:
            try:
                await asyncio.wait_for(
                    self._process_all_organizations(),
                    timeout=EXECUTION_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "billing.scheduler_timeout",
                    detalle=f"La corrida excedió el timeout de {EXECUTION_TIMEOUT} s",
                )
            except Exception as e:  # noqa: BLE001 — no dejar caer el job del scheduler
                logger.error("billing.scheduler_error", error=str(e))

    async def _process_all_organizations(self) -> None:
        """
        Recorre las organizaciones activas y cierra, si corresponde, su mes recién terminado.

        Crea su propia `SessionLocal` (no hay contexto de request). Cada organización se
        procesa de forma aislada: un fallo puntual se registra y no interrumpe el lote.
        """
        db = SessionLocal()
        try:
            orgs = (
                db.query(Organization)
                .filter(Organization.is_active.is_(True))
                .all()
            )
            total = len(orgs)
            cerrados = 0
            for org in orgs:
                try:
                    if self._close_due_month(db, org):
                        cerrados += 1
                except Exception as e:  # noqa: BLE001 — aislar fallo por organización
                    # Rollback defensivo para que la sesión quede utilizable para la
                    # siguiente organización tras un fallo inesperado.
                    db.rollback()
                    logger.error(
                        "billing.scheduler_org_error",
                        organization_id=str(org.id),
                        error=str(e),
                    )
            logger.info(
                "billing.scheduler_corrida_completada",
                organizaciones=total,
                cerrados=cerrados,
            )
        finally:
            db.close()

    def _close_due_month(self, db, org: Organization) -> bool:
        """
        Cierra el mes recién terminado de `org` si ya cruzó la medianoche del día 1 en su tz
        y aún no está cerrado. Devuelve True si ejecutó un cierre, False en caso contrario.

        Determinación del mes objetivo:
        - Se calcula el "ahora" local de la organización con `zoneinfo.ZoneInfo(org.timezone)`.
        - El mes objetivo es el inmediatamente anterior al mes local actual (el mes recién
          terminado, cuyo corte de cierre es 00:00 del día 1 del mes local actual).

        Guardas:
        - Si ya existe cabecera para ese periodo, no se hace nada (idempotencia rápida).
        - `close_month` vuelve a validar idempotencia y secuencialidad (fail-closed); se
          capturan `BillingAlreadyClosedError` (carrera / ya cerrado → se ignora) y
          `BillingSequenceError` (hay un hueco → se registra y NO se auto-rellena; eso es
          responsabilidad del endpoint retroactivo, task 27).
        """
        target = self._due_period(org)
        if target is None:
            return False
        year, month = target

        # Idempotencia rápida: si ya hay cabecera para el periodo, no reintentar.
        if self._already_closed(db, org, year, month):
            return False

        try:
            billing_close_service.close_month(db, org, year, month, actor_id=None)
            logger.info(
                "billing.scheduler_cierre_ok",
                organization_id=str(org.id),
                period=f"{year}-{month:02d}",
            )
            return True
        except BillingAlreadyClosedError:
            # Otra corrida/worker cerró el periodo entre el chequeo y el intento: no es error.
            logger.info(
                "billing.scheduler_ya_cerrado",
                organization_id=str(org.id),
                period=f"{year}-{month:02d}",
            )
            return False
        except BillingSequenceError:
            # Hay un mes anterior sin cerrar. El scheduler NO auto-rellena huecos: se registra
            # para que un superadministrador ejecute los cierres retroactivos (task 27).
            logger.warning(
                "billing.scheduler_hueco_secuencia",
                organization_id=str(org.id),
                period=f"{year}-{month:02d}",
                detalle="Existe un mes anterior sin cerrar; usar cierre retroactivo (task 27)",
            )
            return False

    def _due_period(self, org: Organization) -> Optional[tuple]:
        """
        Devuelve `(year, month)` del mes recién terminado en la tz de `org`, o None si la
        zona horaria de la organización no es válida.

        El mes recién terminado es el inmediatamente anterior al mes local actual: cuando el
        reloj local ya entró en el mes L, el mes L−1 acaba de terminar y su cierre corre a las
        00:00 del día 1 de L (que ya pasó en tz local).
        """
        try:
            tz = ZoneInfo(org.timezone)
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            logger.error(
                "billing.scheduler_tz_invalida",
                organization_id=str(org.id),
                timezone=org.timezone,
            )
            return None

        ahora_local = datetime.now(tz)
        # Mes inmediatamente anterior al mes local actual (rollover de enero → diciembre).
        if ahora_local.month == 1:
            return (ahora_local.year - 1, 12)
        return (ahora_local.year, ahora_local.month - 1)

    def _already_closed(self, db, org: Organization, year: int, month: int) -> bool:
        """Indica si ya existe una cabecera de cierre para (org, year, month)."""
        return (
            db.query(BillingClosure)
            .filter(
                BillingClosure.organization_id == org.id,
                BillingClosure.period_year == year,
                BillingClosure.period_month == month,
            )
            .first()
            is not None
        )


# === SINGLETON A NIVEL DE MÓDULO ===
# Instancia única del scheduler para toda la aplicación (arrancado/detenido en el lifespan
# de `app/main.py`, junto a `status_scheduler`).
billing_close_scheduler = BillingCloseScheduler()
