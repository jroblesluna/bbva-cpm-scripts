# Feature: usage-and-billing, Task 11: Invariantes de la máquina de estados de facturación
"""
Property tests de invariantes de `BillingStateMachine`.

Estos tests recorren TODO el espacio de estados (`VALID_STATES`) y todas las combinaciones
del flag `automatic` y de `is_online` para demostrar, con hypothesis, las garantías de la
máquina de estados de facturación descritas en los requisitos 2.5–2.7 y 3.2/3.3:

    - Invariante A (Req 2.7): ninguna transición válida devuelve una workstation a `new`.
    - Invariante B (Req 2.7): `s → new` es SIEMPRE inválida, para todo estado `s` y ambos
      valores del flag `automatic`.
    - Invariante C (Req 2.6): el proceso automático de cierre NUNCA permite `archived → recycled`,
      y de hecho `archived` no es origen de ninguna transición automática salvo su reactivación
      (`archived → billable`).
    - Invariante D (subconjunto): toda transición permitida en el path automático también lo
      está en el path manual (la matriz automática es un subconjunto de la matriz completa).
    - Invariante E (Req 3.2, 3.3): `assert_archivable` lanza `BillingArchiveError` si y solo si
      la workstation está online; nunca lanza si está offline, sea cual sea su `billing_status`.

**Validates: Requirements 2.5, 2.6, 2.7**
"""

import pytest
from hypothesis import given, settings as hypothesis_settings
from hypothesis import strategies as st

from app.models.workstation import Workstation
from app.services.billing_state_machine import (
    ARCHIVED,
    BILLABLE,
    BillingArchiveError,
    BillingStateMachine,
    NEW,
    RECYCLED,
    VALID_STATES,
    billing_state_machine,
)


# === ESTRATEGIAS DE GENERACIÓN ===

# Muestrea sobre el conjunto real de estados válidos del ciclo de vida.
# Se convierte a lista ordenada para que hypothesis tenga un orden estable de muestreo.
estado_strategy = st.sampled_from(sorted(VALID_STATES))

# Flag de contexto de la transición: automático (cierre) o manual (administrador).
automatic_strategy = st.booleans()

# Estado de conectividad de la workstation para probar `assert_archivable`.
is_online_strategy = st.booleans()


def _make_workstation(is_online: bool, billing_status: str) -> Workstation:
    """
    Construye una `Workstation` en memoria (sin sesión de BD) para los tests de archivado.

    `assert_archivable` solo lee `ws.is_online` (y `ws.ip_private` para el mensaje de error),
    por lo que no se necesita persistencia; basta con setear esos atributos.
    """
    return Workstation(
        ip_private="10.0.0.1",
        is_online=is_online,
        billing_status=billing_status,
    )


# === PROPERTY TESTS ===


@hypothesis_settings(max_examples=200, deadline=None)
@given(old=estado_strategy, new=estado_strategy, automatic=automatic_strategy)
def test_invariante_a_ninguna_transicion_valida_devuelve_a_new(
    old: str, new: str, automatic: bool
):
    """
    Invariante A (Req 2.7): para TODA transición `old → new` que la máquina considere válida,
    el estado destino NUNCA es `new`.

    **Validates: Requirements 2.7**
    """
    sm = BillingStateMachine()
    if sm.can_transition(old, new, automatic=automatic):
        assert new != NEW, (
            f"La transición válida {old!r} → {new!r} (automatic={automatic}) devuelve a "
            f"{NEW!r}, lo que viola el requisito 2.7."
        )


@hypothesis_settings(max_examples=200, deadline=None)
@given(old=estado_strategy, automatic=automatic_strategy)
def test_invariante_b_destino_new_siempre_invalido(old: str, automatic: bool):
    """
    Invariante B (Req 2.7): `s → new` es inválida para TODO estado `s` y ambos contextos
    (`automatic` True/False). Ninguna workstation puede regresar a `new`.

    **Validates: Requirements 2.7**
    """
    sm = BillingStateMachine()
    assert sm.can_transition(old, NEW, automatic=automatic) is False, (
        f"La máquina permitió {old!r} → {NEW!r} (automatic={automatic}); ningún destino "
        f"{NEW!r} debe ser válido (Req 2.7)."
    )


@hypothesis_settings(max_examples=100, deadline=None)
@given(new=estado_strategy)
def test_invariante_c_archived_no_recicla_por_cierre(new: str):
    """
    Invariante C (Req 2.6): el proceso automático de cierre NUNCA permite que una `archived`
    pase a `recycled`, ni a ningún otro estado salvo su reactivación por actividad
    (`archived → billable`).

    Se recorre todo el espacio de destinos: bajo `automatic=True`, el único destino permitido
    desde `archived` es `billable`. En particular `archived → recycled` es siempre False.

    **Validates: Requirements 2.6**
    """
    sm = BillingStateMachine()
    permitido = sm.can_transition(ARCHIVED, new, automatic=True)

    if new == BILLABLE:
        # Única salida automática de `archived`: reactivación por actividad.
        assert permitido is True, (
            f"El path automático debería permitir {ARCHIVED!r} → {BILLABLE!r} (reactivación)."
        )
    else:
        # Cualquier otro destino automático desde `archived` está prohibido,
        # incluyendo explícitamente `recycled` (Req 2.6).
        assert permitido is False, (
            f"El path automático permitió {ARCHIVED!r} → {new!r}; solo se admite la "
            f"reactivación a {BILLABLE!r} (Req 2.6)."
        )

    # Aserción explícita del caso central del requisito, independiente del muestreo.
    assert sm.can_transition(ARCHIVED, RECYCLED, automatic=True) is False, (
        f"El cierre automático nunca debe permitir {ARCHIVED!r} → {RECYCLED!r} (Req 2.6)."
    )


@hypothesis_settings(max_examples=200, deadline=None)
@given(old=estado_strategy, new=estado_strategy)
def test_invariante_d_automatico_es_subconjunto_del_manual(old: str, new: str):
    """
    Invariante D: la matriz automática es un subconjunto de la matriz completa. Toda transición
    permitida en el path automático (cierre) también lo está en el path manual.

    Coherente con Req 2.5/2.6: el cierre solo puede ejecutar un subconjunto de las transiciones
    (las que no requieren acción manual del administrador).

    **Validates: Requirements 2.5, 2.6**
    """
    sm = BillingStateMachine()
    if sm.can_transition(old, new, automatic=True):
        assert sm.can_transition(old, new, automatic=False) is True, (
            f"La transición {old!r} → {new!r} es válida en automático pero no en manual; "
            f"la matriz automática debe ser un subconjunto de la manual."
        )


@hypothesis_settings(max_examples=200, deadline=None)
@given(is_online=is_online_strategy, billing_status=estado_strategy)
def test_invariante_e_solo_offline_se_archiva(is_online: bool, billing_status: str):
    """
    Invariante E (Req 3.2, 3.3): `assert_archivable` lanza `BillingArchiveError` si y solo si
    la workstation está online. Si está offline, nunca lanza, independientemente de su
    `billing_status`.

    Enlaza con la política "solo offline se archiva": el archivado es una eliminación lógica
    manual que exige `is_online == False` (fail-closed cuando está online).

    **Validates: Requirements 2.5, 2.6, 2.7**
    """
    sm = BillingStateMachine()
    ws = _make_workstation(is_online=is_online, billing_status=billing_status)

    if is_online:
        with pytest.raises(BillingArchiveError):
            sm.assert_archivable(ws)
    else:
        # Offline: no debe lanzar en ningún caso, sea cual sea el estado de facturación.
        sm.assert_archivable(ws)


@hypothesis_settings(max_examples=100, deadline=None)
@given(billing_status=estado_strategy)
def test_instancia_compartida_coherente_con_clase(billing_status: str):
    """
    La instancia compartida `billing_state_machine` se comporta igual que una instancia nueva
    para `assert_archivable` cuando la workstation está offline (no lanza).

    Sirve de verificación de que el singleton sin estado es intercambiable con `BillingStateMachine()`.
    """
    ws = _make_workstation(is_online=False, billing_status=billing_status)
    # Ninguna de las dos vías debe lanzar con la ws offline.
    billing_state_machine.assert_archivable(ws)
    BillingStateMachine().assert_archivable(ws)
