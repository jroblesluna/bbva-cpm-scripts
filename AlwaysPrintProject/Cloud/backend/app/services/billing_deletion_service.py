"""
Servicio de eliminación/archivado de workstations del módulo Usage and Billing (task 22).

Centraliza la restricción de eliminación (Req 3.1–3.4) para que TODOS los flujos de borrado
(individual y masivo) apliquen exactamente la misma regla:

    - `billing_status == 'new'`  → eliminación física de la fila (`db.delete(ws)`).
    - `billing_status != 'new'`:
        - workstation ONLINE   → RECHAZO (debe estar offline para archivar) — Req 3.2, 3.3.
        - workstation OFFLINE  → archivado lógico (`billing_status = 'archived'`) — Req 3.2.

El diseño (ver `design.md`, sección "Restricción de eliminación") pide centralizar esta lógica
en `BillingDeletionService.delete_or_archive(db, ws)` reutilizada por el borrado individual
(`DELETE /workstations/{id}`, task 23) y por el borrado masivo (`POST /workstations/bulk-delete`,
task 23), que construye un reporte por-workstation con el desglose deleted/archived/rejected
(Req 3.5).

Decisiones de diseño (para integración limpia con la task 23):

1. NO se hace `commit` dentro del servicio. La mutación (`db.delete(ws)` o setear el campo) se
   aplica sobre la sesión del caller, y el caller (endpoint) controla la transacción. Esto es
   coherente con el resto de servicios de billing que mutan estado vivo sin commitear
   (`mark_activity` en `last_seen_tracker.py`); el endpoint individual actual ya hacía
   `db.delete(...)` + `db.commit()`, por lo que trasladar el commit al caller no cambia el
   comportamiento observable y permite al endpoint masivo procesar un lote y commitear una vez.

2. `delete_or_archive` NO lanza excepción para el caso de rechazo (online). Devuelve un
   `DeletionResult` con `outcome="rejected"` y `reason="online"`. Esto simplifica el borrado
   masivo (task 23), que necesita un resultado por-workstation (incluidos los rechazos) para
   armar el reporte sin envolver cada elemento en try/except. Las precondiciones de la máquina
   de estados (`assert_archivable`, `assert_can_transition`) se usan internamente y su fallo se
   traduce a un resultado "rejected" en lugar de propagarse.

3. Tenant isolation (Req 3.4, 11.3) la garantiza el CALLER: el endpoint recupera la workstation
   ya filtrada por `organization_id`. El servicio opera sobre la instancia ya autorizada.

Validación de transición vía máquina de estados (`billing_state_machine`):
    - Para el path de archivado se invoca `assert_archivable(ws)` (exige offline) y se valida la
      transición `billing_status → 'archived'` con `assert_can_transition(...)`. Las transiciones
      `billable → archived` y `recycled → archived` son válidas (manuales) en la matriz; un
      origen inesperado (p. ej. `new` ya se maneja por el path de delete; `archived → archived`
      es no-op inválido) se traduce a un rechazo con la razón correspondiente.
    - El caso `new → (eliminación física)` NO es una transición de `billing_status` sino un
      borrado de fila; se maneja directamente sin pasar por la matriz (ver nota en
      `billing_state_machine.py`).
"""

from dataclasses import dataclass
from typing import Optional

from app.core.logging import get_logger
from app.models.workstation import Workstation
from app.services.billing_state_machine import (
    ARCHIVED,
    NEW,
    BillingArchiveError,
    BillingTransitionError,
    billing_state_machine,
)

logger = get_logger(__name__)


# Resultados posibles de una operación de eliminación/archivado.
OUTCOME_DELETED = "deleted"
OUTCOME_ARCHIVED = "archived"
OUTCOME_REJECTED = "rejected"

# Razón de rechazo cuando la workstation no-`new` está online.
REASON_ONLINE = "online"


@dataclass
class DeletionResult:
    """
    Resultado de aplicar la restricción de eliminación a una workstation.

    Sirve tanto para el borrado individual (task 23) como para armar el reporte por-workstation
    del borrado masivo (Req 3.5). No incluye información de otras workstations: es el resultado
    de UNA sola.

    Attributes:
        ip_private: IP privada de la workstation (identificador de negocio para el reporte).
        outcome: uno de `deleted` | `archived` | `rejected`.
        reason: motivo del resultado. Para `rejected` describe por qué (p. ej. `online`); para
            `deleted`/`archived` es una descripción breve del camino tomado (útil para logs/UI).
    """

    ip_private: str
    outcome: str
    reason: Optional[str] = None


class BillingDeletionService:
    """
    Aplica la restricción de eliminación de workstations (Req 3.1–3.4).

    Componente sin estado: puede usarse vía la instancia compartida `billing_deletion_service`.
    NO commitea; deja el control de la transacción al caller (endpoint).
    """

    def delete_or_archive(self, db, ws: Workstation) -> DeletionResult:
        """
        Elimina físicamente o archiva una workstation según su `billing_status` y conectividad.

        Reglas (Req 3.1–3.3):
            - `billing_status == 'new'`      → `db.delete(ws)` (eliminación física).
            - `billing_status != 'new'` y online   → rechazo (`outcome="rejected"`, `reason="online"`).
            - `billing_status != 'new'` y offline  → `billing_status = 'archived'` (soft-delete).

        No hace `commit`: la mutación se aplica sobre la sesión del caller, que controla la
        transacción (permite al borrado masivo procesar un lote y commitear una sola vez).

        Args:
            db: sesión SQLAlchemy activa (transacción del caller). La workstation ya debe venir
                autorizada/filtrada por `organization_id` por el caller (tenant isolation).
            ws: instancia de `Workstation` gestionada por `db`.

        Returns:
            DeletionResult con `outcome` en {`deleted`, `archived`, `rejected`} y la razón.
        """
        ip_private = ws.ip_private

        # ── Caso 1: nunca facturada → eliminación física (Req 3.1) ──────────────
        # `new` no forma parte de ningún cierre, por lo que se puede borrar la fila sin
        # afectar la integridad del histórico. No es una transición de billing_status.
        if ws.billing_status == NEW:
            db.delete(ws)
            logger.info(
                "billing.workstation_eliminada",
                ip_private=ip_private,
                billing_status=NEW,
            )
            return DeletionResult(
                ip_private=ip_private,
                outcome=OUTCOME_DELETED,
                reason="billing_status=new (nunca facturada)",
            )

        # ── Caso 2: ya facturada (no-`new`) → archivar, exige offline (Req 3.2, 3.3) ──
        # Precondición de conectividad: solo se archiva si está offline (fail-closed).
        try:
            billing_state_machine.assert_archivable(ws)
        except BillingArchiveError:
            logger.info(
                "billing.archivado_rechazado_online",
                ip_private=ip_private,
                billing_status=ws.billing_status,
            )
            return DeletionResult(
                ip_private=ip_private,
                outcome=OUTCOME_REJECTED,
                reason=REASON_ONLINE,
            )

        # Validación de la transición viva → 'archived' (manual). `billable`/`recycled` →
        # 'archived' son válidas; un origen inesperado se traduce a rechazo (fail-closed).
        try:
            billing_state_machine.assert_can_transition(ws.billing_status, ARCHIVED)
        except BillingTransitionError as exc:
            logger.warning(
                "billing.transicion_archivado_invalida",
                ip_private=ip_private,
                billing_status=ws.billing_status,
                error=str(exc),
            )
            return DeletionResult(
                ip_private=ip_private,
                outcome=OUTCOME_REJECTED,
                reason=f"transicion_invalida:{ws.billing_status}->{ARCHIVED}",
            )

        ws.billing_status = ARCHIVED
        logger.info(
            "billing.workstation_archivada",
            ip_private=ip_private,
            nuevo_estado=ARCHIVED,
        )
        return DeletionResult(
            ip_private=ip_private,
            outcome=OUTCOME_ARCHIVED,
            reason="soft-delete (offline)",
        )


# Instancia compartida sin estado, reutilizable por los endpoints de borrado (individual y masivo).
billing_deletion_service = BillingDeletionService()
