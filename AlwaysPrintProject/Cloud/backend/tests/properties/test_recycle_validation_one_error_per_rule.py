# Feature: recycle-policy-config, Property 8: Se reporta un error por cada regla violada
"""
Property test de la Property 8 (se reporta exactamente un error por cada regla violada).

*For any* política que viola un CONJUNTO CONOCIDO de reglas simultáneamente,
`validate_policy(...)` DEBE lanzar `RecyclePolicyValidationException` cuya lista `errors`
contenga EXACTAMENTE un `PolicyValidationError` por cada regla violada (Req 7.7), ni más ni
menos, identificados por su campo `.rule`.

Reglas semánticas evaluadas por `validate_policy` (identificadores estables del diseño):
    "order" | "cutoff_min" | "offset_range" | "ephemeral_range" | "period".

(El identificador "format" NO lo produce `validate_policy`: lo valida `parse_recycle_rule`
aguas arriba, sobre el string, antes de que los offsets lleguen aquí ya parseados a enteros.)

Estrategia de generación:
    - Se elige un subconjunto NO vacío de reglas objetivo a violar.
    - Se construyen los parámetros de forma que se viole EXACTAMENTE ese subconjunto y ninguna
      otra regla (control fino de cada dimensión). Como algunas reglas están acopladas (violar
      `order` o `cutoff_min` puede depender de los mismos offsets, y offsets fuera de `[-24,+1]`
      implican `offset_range`), se recomputa el conjunto REALMENTE violado con un oráculo
      independiente y se compara contra los `.rule` devueltos. Así el test es robusto aunque el
      subconjunto objetivo no sea perfectamente aislable.

**Validates: Requirements 7.2, 7.3, 7.4, 7.5, 7.7, 7.8**
"""

from collections import Counter

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.services.recycle_policy_service import (
    RecyclePolicyValidationException,
    validate_policy,
)

# Límites de las reglas (deben coincidir con recycle_policy_service).
_OFFSET_MIN, _OFFSET_MAX = -24, 1
_CUTOFF_MIN = 1
_EPH_MIN, _EPH_MAX = 1, 168
_YEAR_MIN, _YEAR_MAX = 2000, 2999
_MONTH_MIN, _MONTH_MAX = 1, 12

_ALL_RULES = {"order", "cutoff_min", "offset_range", "ephemeral_range", "period"}


def _violated_rules(cutoff, cut1, cut2, ephemeral_hours, eff_year, eff_month):
    """
    Oráculo independiente: conjunto EXACTO de reglas semánticas violadas por una entrada.

    Replica la semántica de `validate_policy` sin reutilizar su código, para servir de
    referencia contra la que comparar los `.rule` devueltos por la excepción.
    """
    rules = set()
    if not (cutoff > cut1 >= cut2):
        rules.add("order")
    if cutoff < _CUTOFF_MIN:
        rules.add("cutoff_min")
    if any(not (_OFFSET_MIN <= v <= _OFFSET_MAX) for v in (cutoff, cut1, cut2)):
        rules.add("offset_range")
    if not (_EPH_MIN <= ephemeral_hours <= _EPH_MAX):
        rules.add("ephemeral_range")
    if not (_MONTH_MIN <= eff_month <= _MONTH_MAX) or not (
        _YEAR_MIN <= eff_year <= _YEAR_MAX
    ):
        rules.add("period")
    return rules


# Estrategias por dimensión: cada una permite forzar "válido" o "inválido" para su regla.
_offset_wide = st.integers(min_value=-40, max_value=10)
_ephemeral_wide = st.integers(min_value=-50, max_value=400)
_year_wide = st.integers(min_value=1800, max_value=3200)
_month_wide = st.integers(min_value=-3, max_value=20)


@settings(max_examples=100)
@given(
    cutoff=_offset_wide,
    cut1=_offset_wide,
    cut2=_offset_wide,
    ephemeral_hours=_ephemeral_wide,
    eff_year=_year_wide,
    eff_month=_month_wide,
)
def test_exactly_one_error_per_violated_rule(
    cutoff, cut1, cut2, ephemeral_hours, eff_year, eff_month
):
    """
    Para una política que viola un conjunto conocido de reglas, la excepción reporta
    EXACTAMENTE un error por regla violada (Req 7.7), identificados por `.rule`.
    """
    expected = _violated_rules(cutoff, cut1, cut2, ephemeral_hours, eff_year, eff_month)

    # Property 8 aplica a políticas inválidas (>=1 regla violada). Las válidas no reportan
    # errores y quedan fuera del alcance de esta property.
    assume(expected)

    try:
        validate_policy(cutoff, cut1, cut2, ephemeral_hours, eff_year, eff_month)
        raised = False
        errors = []
    except RecyclePolicyValidationException as exc:
        raised = True
        errors = exc.errors

    assert raised, (
        "validate_policy debió lanzar RecyclePolicyValidationException para una política que "
        f"viola {sorted(expected)}."
    )

    reported = [e.rule for e in errors]
    reported_set = set(reported)
    counts = Counter(reported)

    # 1) El conjunto de reglas reportadas coincide EXACTAMENTE con el de reglas violadas.
    assert reported_set == expected, (
        f"Las reglas reportadas {sorted(reported_set)} no coinciden con las violadas "
        f"{sorted(expected)} (cutoff={cutoff}, cut1={cut1}, cut2={cut2}, "
        f"eph={ephemeral_hours}, eff={eff_year}-{eff_month})."
    )

    # 2) UN solo error por regla violada (sin duplicados, Req 7.7).
    duplicadas = {rule: n for rule, n in counts.items() if n > 1}
    assert not duplicadas, (
        f"Se reportó más de un error para la(s) misma(s) regla(s): {duplicadas}. "
        "Debe haber exactamente un error por regla violada (Req 7.7)."
    )

    # 3) Ningún identificador de regla espurio (fuera del catálogo semántico conocido).
    assert reported_set <= _ALL_RULES, (
        f"Identificadores de regla desconocidos: {sorted(reported_set - _ALL_RULES)}."
    )

    # 4) El total de errores == número de reglas violadas (redundante con 1+2, pero explícito).
    assert len(errors) == len(expected)
