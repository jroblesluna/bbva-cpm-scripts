"""
Tests unitarios de `BillingStateMachine` (Usage and Billing, task 10).

Cubren la matriz de transiciones (Req 2.5), las prohibiciones (Req 2.6, 2.7) y la
precondición de archivado que exige offline (Req 3.2, 3.3). Los tests property-based de
invariantes viven en task 11 (`test_billing_state_invariants.py`); aquí solo hay ejemplos
directos que documentan casos concretos y de borde.

Trabajan con objetos ORM en memoria (sin sesión de BD), igual que
`tests/unit/test_last_seen_tracker.py`.

_Requirements: 2.5, 2.6, 2.7_
"""

import pytest

from app.models.workstation import Workstation
from app.services.billing_state_machine import (
    ARCHIVED,
    BILLABLE,
    NEW,
    RECYCLED,
    BillingArchiveError,
    BillingStateMachine,
    BillingTransitionError,
    billing_state_machine,
)


def _ws(billing_status: str = BILLABLE, is_online: bool = False) -> Workstation:
    return Workstation(
        ip_private="10.0.0.1",
        billing_status=billing_status,
        is_online=is_online,
    )


class TestCanTransitionManual:
    """Matriz completa (acciones manuales + automáticas), Req 2.5."""

    @pytest.mark.parametrize(
        "old,new",
        [
            (NEW, BILLABLE),
            (BILLABLE, RECYCLED),
            (BILLABLE, ARCHIVED),
            (RECYCLED, BILLABLE),
            (RECYCLED, ARCHIVED),
            (ARCHIVED, BILLABLE),
        ],
    )
    def test_transiciones_validas(self, old, new):
        assert billing_state_machine.can_transition(old, new) is True

    @pytest.mark.parametrize(
        "old,new",
        [
            # Nadie vuelve a `new` (Req 2.7).
            (BILLABLE, NEW),
            (RECYCLED, NEW),
            (ARCHIVED, NEW),
            # `archived → recycled` prohibido incluso manualmente (no está en la matriz).
            (ARCHIVED, RECYCLED),
            # Saltos no contemplados.
            (NEW, RECYCLED),
            (NEW, ARCHIVED),
            (RECYCLED, ARCHIVED),  # este SÍ es válido; se re-verifica abajo
        ],
    )
    def test_transiciones_invalidas_o_prohibidas(self, old, new):
        # `recycled → archived` es válido; los demás no. Filtramos ese caso concreto.
        if (old, new) == (RECYCLED, ARCHIVED):
            assert billing_state_machine.can_transition(old, new) is True
        else:
            assert billing_state_machine.can_transition(old, new) is False

    def test_transicion_a_si_mismo_no_valida(self):
        assert billing_state_machine.can_transition(BILLABLE, BILLABLE) is False

    def test_estado_desconocido_fail_closed(self):
        assert billing_state_machine.can_transition("foo", BILLABLE) is False
        assert billing_state_machine.can_transition(BILLABLE, "bar") is False


class TestCanTransitionAutomatic:
    """Matriz del proceso automático de cierre, Req 2.6."""

    @pytest.mark.parametrize(
        "old,new",
        [
            (NEW, BILLABLE),
            (BILLABLE, RECYCLED),
            (RECYCLED, BILLABLE),
            (ARCHIVED, BILLABLE),
        ],
    )
    def test_automaticas_validas(self, old, new):
        assert billing_state_machine.can_transition(old, new, automatic=True) is True

    @pytest.mark.parametrize(
        "old,new",
        [
            # Archivado es SIEMPRE manual: prohibido por el path automático.
            (BILLABLE, ARCHIVED),
            (RECYCLED, ARCHIVED),
            # `archived → recycled` automático explícitamente prohibido (Req 2.6).
            (ARCHIVED, RECYCLED),
        ],
    )
    def test_automaticas_prohibidas(self, old, new):
        assert billing_state_machine.can_transition(old, new, automatic=True) is False


class TestAssertHelpers:
    """`assert_can_transition` y `assert_archivable`."""

    def test_assert_can_transition_ok(self):
        # No lanza.
        billing_state_machine.assert_can_transition(NEW, BILLABLE)

    def test_assert_can_transition_falla(self):
        with pytest.raises(BillingTransitionError):
            billing_state_machine.assert_can_transition(ARCHIVED, RECYCLED)

    def test_assert_archivable_offline_ok(self):
        # No lanza si está offline.
        billing_state_machine.assert_archivable(_ws(is_online=False))

    def test_assert_archivable_online_falla(self):
        with pytest.raises(BillingArchiveError):
            billing_state_machine.assert_archivable(_ws(is_online=True))


def test_instancia_compartida_es_billing_state_machine():
    assert isinstance(billing_state_machine, BillingStateMachine)
