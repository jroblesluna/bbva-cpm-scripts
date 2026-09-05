"""
Máquina de estados del `billing_status` del módulo Usage and Billing.

Centraliza la validación de las transiciones del ciclo de vida de facturación de una
IP registrada (`workstations.billing_status`) para que ningún flujo (cierre mensual,
reactivación por actividad, archivado manual) invente transiciones fuera de la matriz
definida en el diseño y en los requisitos 2.5–2.7.

Estados posibles (CHECK constraint del modelo): `new`, `billable`, `recycled`, `archived`.

Matriz de transiciones válidas (Req 2.5):
    - new       → billable    (cierre mensual, paso 1)
    - billable  → recycled     (cierre mensual, reglas de reciclaje)
    - billable  → archived     (archivado manual; solo si la ws está offline)
    - recycled  → billable     (actividad; reactivación inmediata)
    - recycled  → archived     (archivado manual; solo si la ws está offline)
    - archived  → billable     (actividad; reactivación inmediata)

Reglas de prohibición:
    - `archived → recycled` NO se permite por el proceso automático de cierre (Req 2.6).
    - Ninguna transición devuelve una ws al estado `new` (Req 2.7).

Nota sobre borrado físico: `new → (eliminación física del registro)` (Req 2.5) no es una
transición de `billing_status` sino un borrado de la fila; lo maneja el servicio de
eliminación (`BillingDeletionService`, task 22), no esta máquina de estados.

Distinción manual vs automático (Req 2.6):
    Algunas transiciones solo son válidas por acción manual del administrador y NO por el
    proceso automático de cierre. En concreto, el paso a `archived` es siempre manual, y
    `archived → recycled` está prohibido justamente para el path automático. Por eso
    `can_transition` acepta un flag `automatic` que, cuando es True (contexto del cierre),
    restringe la matriz a las transiciones que el cierre puede ejecutar.
"""

from typing import FrozenSet, Tuple

from app.core.logging import get_logger
from app.models.workstation import Workstation

logger = get_logger(__name__)


class BillingTransitionError(ValueError):
    """Se intentó una transición de `billing_status` no permitida por la matriz."""


class BillingArchiveError(ValueError):
    """Se intentó archivar una workstation que no está offline (Req 3.2, 3.3)."""


# Estados válidos del ciclo de vida (coherentes con el CHECK del modelo).
NEW = "new"
BILLABLE = "billable"
RECYCLED = "recycled"
ARCHIVED = "archived"

VALID_STATES: FrozenSet[str] = frozenset((NEW, BILLABLE, RECYCLED, ARCHIVED))


class BillingStateMachine:
    """
    Valida las transiciones del `billing_status` y la precondición de archivado.

    Es un componente sin estado (stateless): expone la matriz como constantes de clase y
    métodos que solo consultan esa matriz. Puede usarse vía instancia o directamente por
    los métodos, ya que no guarda contexto entre llamadas.
    """

    # Transiciones válidas por CUALQUIER vía (manual o automática).
    # Cada tupla es (estado_origen, estado_destino).
    _ALL_TRANSITIONS: FrozenSet[Tuple[str, str]] = frozenset(
        {
            (NEW, BILLABLE),       # cierre mensual, paso 1
            (BILLABLE, RECYCLED),  # cierre mensual, reglas de reciclaje
            (BILLABLE, ARCHIVED),  # archivado manual (offline)
            (RECYCLED, BILLABLE),  # actividad
            (RECYCLED, ARCHIVED),  # archivado manual (offline)
            (ARCHIVED, BILLABLE),  # actividad
        }
    )

    # Subconjunto que el proceso AUTOMÁTICO de cierre puede ejecutar.
    # El archivado es siempre manual, por lo que se excluyen las transiciones a `archived`.
    # Esto implementa explícitamente la prohibición `archived → recycled` automática (Req 2.6):
    # `archived` no es origen de ninguna transición automática.
    _AUTOMATIC_TRANSITIONS: FrozenSet[Tuple[str, str]] = frozenset(
        {
            (NEW, BILLABLE),
            (BILLABLE, RECYCLED),
            (RECYCLED, BILLABLE),
            (ARCHIVED, BILLABLE),
        }
    )

    def can_transition(self, old: str, new: str, automatic: bool = False) -> bool:
        """
        Indica si la transición `old → new` está permitida por la matriz.

        Args:
            old: estado actual (`new`, `billable`, `recycled`, `archived`).
            new: estado destino.
            automatic: si True, se evalúa contra la matriz del proceso automático de cierre
                (excluye archivado manual y prohíbe `archived → recycled`). Si False
                (por defecto), se evalúa contra la matriz completa (incluye acciones
                manuales del administrador).

        Returns:
            True si la transición es válida en el contexto indicado; False en caso contrario.

        Notas:
            - Una "transición" a sí mismo (`old == new`) se considera NO válida: no es un
              cambio de estado y ningún flujo debe llamar a la máquina para no hacer nada.
              Los callers deben comprobar la igualdad antes si el no-op es aceptable.
            - Cualquier destino `new` es siempre inválido (Req 2.7): no está en la matriz.
            - Estados desconocidos devuelven False (fail-closed).
        """
        if old not in VALID_STATES or new not in VALID_STATES:
            return False

        matrix = self._AUTOMATIC_TRANSITIONS if automatic else self._ALL_TRANSITIONS
        return (old, new) in matrix

    def assert_can_transition(self, old: str, new: str, automatic: bool = False) -> None:
        """
        Igual que `can_transition` pero lanza `BillingTransitionError` si no es válida.

        Útil en los flujos que deben fallar de forma ruidosa ante una transición ilegal
        (fail-closed) en lugar de silenciarla.
        """
        if not self.can_transition(old, new, automatic=automatic):
            contexto = "automática" if automatic else "manual"
            raise BillingTransitionError(
                f"Transición de billing_status no permitida ({contexto}): "
                f"'{old}' → '{new}'"
            )

    def assert_archivable(self, ws: Workstation) -> None:
        """
        Verifica que una workstation pueda archivarse: exige `is_online == False` (Req 3.2, 3.3).

        El archivado es una eliminación lógica manual. El requisito exige que la workstation
        esté offline para poder archivarla; si está online, se rechaza (fail-closed).

        No valida aquí el estado de origen (eso lo hace `can_transition` con destino
        `archived`); su única responsabilidad es la precondición de conectividad.

        Args:
            ws: instancia de `Workstation` a archivar.

        Raises:
            BillingArchiveError: si `ws.is_online` es verdadero.
        """
        if ws.is_online:
            raise BillingArchiveError(
                f"No se puede archivar la workstation {ws.ip_private}: debe estar offline "
                f"(is_online=True)."
            )


# Instancia compartida sin estado, reutilizable por los servicios (cierre, tracker, borrado).
billing_state_machine = BillingStateMachine()
