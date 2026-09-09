# Feature: recycle-policy-config, Property 1: Round-trip parse/format de la Recycle_Rule
"""
Property test de la Property 1 (round-trip parse/format de la Recycle_Rule).

`parse_recycle_rule(rule) -> (cutoff, cut1, cut2)` y
`format_recycle_rule(cutoff, cut1, cut2) -> str` son funciones inversas sobre la Recycle_Rule
en su FORMA CANÓNICA con signo explícito (`"+1/-2/-3"`, Req 1.3/1.4). La property afirma las
dos direcciones del round-trip:

    A) *For any* string canónico `s` (tres enteros con signo explícito separados por `/`):
           format_recycle_rule(*parse_recycle_rule(s)) == s

    B) *For any* tripleta de enteros `(c, c1, c2)`:
           parse_recycle_rule(format_recycle_rule(c, c1, c2)) == (c, c1, c2)

Nota de canonicalidad: `parse_recycle_rule` EXIGE signo explícito (`[+-]\\d+`) y
`format_recycle_rule` PRODUCE signo explícito vía `{:+d}`. Por eso el round-trip desde string
(dirección A) solo se cumple para la forma canónica de signo explícito; los strings del test se
CONSTRUYEN a partir de enteros con `{:+d}` para garantizar canonicalidad (un string como
`"1/-2/-3"`, sin signo en el primer componente, no es canónico y no es objeto de esta property).

Esta property NO valida las reglas semánticas (orden, rangos): parse/format solo dependen del
formato, por lo que se generan tripletas de enteros arbitrarios (incluyendo cero, negativos y
magnitudes grandes) para ejercitar el round-trip de forma independiente de `validate_policy`.

**Validates: Requirements 1.3, 1.4**
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.recycle_policy_service import (
    format_recycle_rule,
    parse_recycle_rule,
)


# === ESTRATEGIAS ===
#
# Enteros con signo en un rango amplio (incluye 0, negativos y positivos, con magnitudes que
# exceden los límites semánticos válidos) para ejercitar únicamente el contrato de formato del
# round-trip, no las reglas de validación.
_signed_int = st.integers(min_value=-999, max_value=999)


@st.composite
def _canonical_rule_strings(draw):
    """
    Genera un string de Recycle_Rule en FORMA CANÓNICA (signo explícito) construyéndolo a partir
    de tres enteros con `{:+d}`, garantizando que coincide con lo que produce
    `format_recycle_rule` y que `parse_recycle_rule` acepta.
    """
    cutoff = draw(_signed_int)
    cut1 = draw(_signed_int)
    cut2 = draw(_signed_int)
    return f"{cutoff:+d}/{cut1:+d}/{cut2:+d}"


@settings(max_examples=100)
@given(rule=_canonical_rule_strings())
def test_round_trip_from_canonical_string(rule):
    """
    Dirección A: para todo string canónico `s`, `format_recycle_rule(*parse_recycle_rule(s)) == s`.
    """
    assert format_recycle_rule(*parse_recycle_rule(rule)) == rule


@settings(max_examples=100)
@given(cutoff=_signed_int, cut1=_signed_int, cut2=_signed_int)
def test_round_trip_from_integer_triple(cutoff, cut1, cut2):
    """
    Dirección B: para toda tripleta de enteros, `parse_recycle_rule(format_recycle_rule(...))`
    reconstruye exactamente la tripleta original `(cutoff, cut1, cut2)`.
    """
    assert parse_recycle_rule(format_recycle_rule(cutoff, cut1, cut2)) == (
        cutoff,
        cut1,
        cut2,
    )
