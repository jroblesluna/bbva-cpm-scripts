"""
Tracker de `last_seen` (estrategia opción B) del módulo Usage and Billing.

Este módulo implementa dos piezas independientes pero complementarias:

1. `LastSeenTracker`: un buffer en memoria **por worker** que mapea
   `{workstation_id: last_telemetry_ts}`. Se alimenta cuando llega telemetría, SIN
   escribir a BD (Req 1.7, 1.8). La persistencia real ocurre en momentos puntuales
   (transición online↔offline, flush periódico de ~60s, registro/conexión) que se
   cablearán en las tasks 6, 7 y 8. Aquí solo se provee el componente.

2. `mark_activity(db, ws, ts)`: helper que centraliza la actualización de `last_seen`
   por actividad real y, si la workstation está `recycled`/`archived`, la reactiva a
   `billable` en la MISMA transacción (Req 2.8 — reactivación inmediata de estado).
   Este helper es el único punto por el que deben pasar todas las escrituras de
   `last_seen` por actividad (registro, conexión, telemetría estando offline).

Notas de arquitectura:
- El buffer es local al proceso (worker). En despliegue multi-worker cada worker
  mantiene su propio `last_telemetry_ts`; el flush de 60s de cada worker cubre sus
  propias conexiones (coherente con el `WorkerRegistry` existente). No requiere
  coordinación Redis adicional.
- Las operaciones sobre el dict son atómicas en asyncio (single-threaded por worker),
  por lo que no se usan locks en los accesos simples (patrón del `redis_connection_manager`).
- La reactivación `recycled`/`archived` → `billable` por actividad se valida a través de
  `BillingStateMachine.can_transition(...)` (task 10). Es una transición válida de la matriz
  del diseño; enrutar por la máquina de estados centraliza la regla en un solo lugar y evita
  que este seam invente transiciones fuera de la matriz.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import case
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.workstation import Workstation
from app.services.billing_state_machine import billing_state_machine

logger = get_logger(__name__)


# Estados de facturación que se reactivan a `billable` ante cualquier actividad (Req 2.8).
_REACTIVATABLE_STATES = ("recycled", "archived")

# Estado destino de la reactivación por actividad.
_BILLABLE = "billable"


class LastSeenTracker:
    """
    Buffer en memoria por worker de la última telemetría conocida por workstation.

    Mantiene `{workstation_id: last_telemetry_ts}` sin tocar la base de datos. Sirve
    como fuente de "última actividad real" para:
      - la persistencia en transiciones online↔offline (usar el ts real, no el del evento),
      - el flush periódico del loop de ~60s (solo persistir las que avanzaron),
      - la evaluación de inactividad del Death Ping.

    El buffer es local al proceso; no se comparte entre workers.
    """

    def __init__(self) -> None:
        # workstation_id (str) -> last_telemetry_ts (datetime, naive UTC como el resto del modelo)
        self._buffer: Dict[str, datetime] = {}
        # Marca de la última vez que se persistió cada workstation_id, para que el flush
        # periódico solo escriba las que avanzaron respecto al valor ya volcado (Req 1.7).
        self._flushed: Dict[str, datetime] = {}

    # ── Ingesta de telemetría (sin BD) ──────────────────────────────────────

    def record_telemetry(self, workstation_id: str, ts: datetime) -> None:
        """
        Registra en memoria la última telemetría de una workstation.

        No escribe a BD. Solo actualiza el buffer si `ts` es más reciente que el valor
        almacenado (evita retroceder por mensajes fuera de orden).

        Args:
            workstation_id: UUID de la workstation (str).
            ts: timestamp de la telemetría (datetime naive en UTC).
        """
        current = self._buffer.get(workstation_id)
        if current is None or ts > current:
            self._buffer[workstation_id] = ts

    def get_last_activity(self, workstation_id: str) -> Optional[datetime]:
        """
        Devuelve el último `last_telemetry_ts` conocido en memoria, o None si no hay.

        Se usa al marcar offline / al reconectar para persistir el ts de actividad real
        en lugar del momento del evento (Req 1.5, 1.6).
        """
        return self._buffer.get(workstation_id)

    # ── Soporte al flush periódico (~60s) ───────────────────────────────────

    def get_pending_flush(self) -> Dict[str, datetime]:
        """
        Devuelve las workstations cuyo `last_telemetry_ts` en memoria avanzó respecto al
        último valor volcado a BD.

        El caller (task 8, `start_ping_loop`) hará el batch UPDATE de `last_seen` con
        estos valores y luego confirmará con `commit_flush(...)`. No se escribe en cada
        telemetría individual (Req 1.8).

        Returns:
            dict {workstation_id: last_telemetry_ts} pendiente de persistir.
        """
        pending: Dict[str, datetime] = {}
        for ws_id, ts in self._buffer.items():
            flushed = self._flushed.get(ws_id)
            if flushed is None or ts > flushed:
                pending[ws_id] = ts
        return pending

    def commit_flush(self, flushed: Dict[str, datetime]) -> None:
        """
        Marca como persistidos los valores efectivamente volcados a BD por el flush.

        Args:
            flushed: dict {workstation_id: last_telemetry_ts} que ya se escribió en BD.
        """
        for ws_id, ts in flushed.items():
            prev = self._flushed.get(ws_id)
            if prev is None or ts > prev:
                self._flushed[ws_id] = ts

    # ── Limpieza ─────────────────────────────────────────────────────────────

    def forget(self, workstation_id: str) -> None:
        """
        Elimina una workstation del buffer (p. ej. al desconectarse definitivamente).

        Idempotente: no falla si la workstation no está en el buffer.
        """
        self._buffer.pop(workstation_id, None)
        self._flushed.pop(workstation_id, None)


def _reactivate_if_needed(ws: Workstation) -> bool:
    """
    Reactiva a `billable` una workstation en `recycled`/`archived` (Req 2.8).

    La validación de la transición se delega en `BillingStateMachine.can_transition(...)`:
    `recycled → billable` y `archived → billable` son transiciones válidas de la matriz del
    diseño (reactivación por actividad). Enrutar por la máquina de estados mantiene la regla
    en un solo lugar; el comportamiento observable no cambia (sigue reactivando exactamente
    esos dos estados de origen).

    Returns:
        True si cambió el estado; False si no había que reactivar.
    """
    if ws.billing_status in _REACTIVATABLE_STATES and billing_state_machine.can_transition(
        ws.billing_status, _BILLABLE
    ):
        ws.billing_status = _BILLABLE
        return True
    return False


def mark_activity(db: Session, ws: Workstation, ts: datetime) -> None:
    """
    Registra actividad real de una workstation: actualiza `last_seen` y reactiva estado.

    Es el punto único por el que deben pasar todas las escrituras de `last_seen` por
    actividad (registro/re-registro, nueva conexión, telemetría estando offline). Efectos
    en la MISMA transacción (Req 1.4, 1.5, 2.8):

    1. `ws.last_seen = ts`.
    2. Si `ws.billing_status` es `recycled` o `archived` → `billable` (reactivación
       inmediata).

    Este helper NO hace `commit`: respeta la transacción del caller (el mismo patrón que
    el resto de `services/workstation.py`, donde el commit lo controla el flujo de nivel
    superior). El caller es responsable de confirmar/deshacer la transacción.

    Args:
        db: sesión SQLAlchemy activa (parte de la transacción del caller).
        ws: instancia de `Workstation` gestionada por `db`.
        ts: timestamp de la actividad real (datetime naive en UTC).
    """
    ws.last_seen = ts

    if _reactivate_if_needed(ws):
        logger.info(
            "billing.reactivacion_por_actividad",
            workstation_id=str(ws.id),
            ip_private=ws.ip_private,
            nuevo_estado=_BILLABLE,
            last_seen=ts.isoformat(),
        )


def mark_offline_with_last_seen(
    db: Session,
    ws_last_seen: Dict[str, Optional[datetime]],
) -> int:
    """
    Marca un lote de workstations como `is_online=False` y, cuando se conoce el ts de
    actividad real, persiste también `last_seen` con ESE timestamp (no el momento del
    evento de desconexión/muerte) — Req 1.5, 1.6.

    Reglas:
    - `is_online=False` se aplica a TODAS las ws del lote.
    - `last_seen` solo se escribe para las ws con un ts conocido (`ts is not None`). Las
      que no tienen actividad conocida conservan su `last_seen` persistido (no se degrada
      al momento del evento).
    - Ir offline NO reactiva `billing_status`: es un UPDATE masivo directo que NO pasa por
      `mark_activity` (ir offline no es actividad nueva, no debe reactivar recycled/archived).
    - El `last_seen` se escribe por-ws mediante una expresión SQL `CASE`, de modo que un
      único UPDATE batch cubre valores distintos por workstation (sin per-connect tasks ni
      queries individuales — coherente con las reglas multi-worker del repo).

    No hace `commit`: la transacción la controla el caller.

    Args:
        db: sesión SQLAlchemy activa.
        ws_last_seen: dict {workstation_id: last_activity_ts|None} del lote a marcar offline.

    Returns:
        Número de filas actualizadas por el UPDATE (conteo de `is_online`).
    """
    if not ws_last_seen:
        return 0

    all_ids = list(ws_last_seen.keys())
    # Solo las ws con actividad conocida participan en el CASE de last_seen.
    known = {ws_id: ts for ws_id, ts in ws_last_seen.items() if ts is not None}

    values: Dict[Any, Any] = {Workstation.is_online: False}

    if known:
        # CASE por-ws: last_seen = ts conocido; para el resto, conservar el valor actual.
        whens = [(Workstation.id == ws_id, ts) for ws_id, ts in known.items()]
        values[Workstation.last_seen] = case(*whens, else_=Workstation.last_seen)

    updated = db.query(Workstation).filter(
        Workstation.id.in_(all_ids)
    ).update(
        values,
        synchronize_session=False,
    )
    return updated


def batch_update_last_seen(
    db: Session,
    ws_ts_map: Dict[str, datetime],
) -> int:
    """
    Persiste `last_seen` de un lote de workstations ONLINE en un ÚNICO UPDATE batch.

    Es el sustento del flush periódico del loop de ~60s (task 8, `start_ping_loop`): en
    cada ciclo el manager calcula qué workstations conectadas localmente avanzaron su
    `last_telemetry_ts` en memoria respecto al último valor persistido, y las escribe de
    una sola vez con este helper (Req 1.7). NO se escribe en cada telemetría individual
    (Req 1.8).

    Diferencias con `mark_offline_with_last_seen`:
    - NO toca `is_online` (estas ws siguen conectadas/online).
    - NO reactiva `billing_status`: es un simple volcado de actividad de ws que ya están
      online y activas; el path de reactivación (recycled/archived → billable) ya lo cubre
      `mark_activity` en la telemetría-estando-offline / reconexión. Mantener este flush
      como un UPDATE plano de `last_seen` (ver reglas de impact-analysis del repo).
    - Usa una expresión SQL `CASE` por-ws para escribir valores distintos en un solo UPDATE
      (sin per-ws query ni per-connect tasks — coherente con las reglas multi-worker).

    No hace `commit`: la transacción la controla el caller.

    Args:
        db: sesión SQLAlchemy activa.
        ws_ts_map: dict {workstation_id: last_telemetry_ts} a persistir. Se ignoran las
            entradas con ts None (no hay actividad que volcar).

    Returns:
        Número de filas actualizadas por el UPDATE.
    """
    # Solo las ws con ts conocido participan del volcado.
    known = {ws_id: ts for ws_id, ts in ws_ts_map.items() if ts is not None}
    if not known:
        return 0

    # CASE por-ws: cada workstation recibe su propio last_seen en un único UPDATE.
    whens = [(Workstation.id == ws_id, ts) for ws_id, ts in known.items()]
    updated = db.query(Workstation).filter(
        Workstation.id.in_(list(known.keys()))
    ).update(
        {Workstation.last_seen: case(*whens, else_=Workstation.last_seen)},
        synchronize_session=False,
    )
    return updated
