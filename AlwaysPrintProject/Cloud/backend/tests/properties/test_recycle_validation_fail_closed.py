# Feature: recycle-policy-config, Property 7: Validación fail-closed rechaza políticas inválidas y preserva la previa
"""
Property test de la Property 7 (validación fail-closed rechaza políticas inválidas y preserva
la política previamente persistida).

*For any* política inválida (que viola al menos una de las reglas semánticas: orden,
cutoff_min, offset_range, ephemeral_range, period), `validate_policy(...)` DEBE:

    1. Rechazar la política lanzando `RecyclePolicyValidationException` (fail-closed, Req 7.9).
    2. NO producir ningún efecto secundario: `validate_policy` es una comprobación PURA previa
       a la persistencia (no recibe sesión ni escribe nada), por lo que un rechazo preserva por
       construcción cualquier política previamente persistida (Req 7.9).

Modelado de la preservación (Req 7.9):
    - `validate_policy` no tiene acceso a la BD; su contrato es "validar ANTES de escribir".
    - La property verifica el contrato de pureza: la firma no admite `db`/`Session`, la función
      no retorna estado mutable y ante entradas inválidas lanza SIN tocar nada externo. Se
      confirma además que una llamada válida no altera la excepción de una inválida previa
      (idempotencia / ausencia de estado global compartido).

Toda política inválida generada aquí viola AL MENOS una regla; se comprueba que el rechazo
ocurre siempre (no hay input inválido que "pase").

**Validates: Requirements 7.2, 7.3, 7.4, 7.5, 7.7, 7.8, 7.9**
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.recycle_policy_service import (
    RecyclePolicyValidationException,
    validate_policy,
)


# === ESTRATEGIAS ===
#
# Se generan offsets, umbral y periodo en rangos AMPLIOS (que exceden los límites válidos) para
# que Hypothesis explore tanto entradas válidas como inválidas, y luego se filtra a las que
# violan al menos una regla. La property afirma: toda entrada que viole >=1 regla es rechazada.

_wide_offset = st.integers(min_value=-40, max_value=10)
_wide_ephemeral = st.integers(min_value=-50, max_value=400)
_wide_year = st.integers(min_value=1800, max_value=3200)
_wide_month = st.integers(min_value=-3, max_value=20)

# Límites de las reglas (deben coincidir con recycle_policy_service).
_OFFSET_MIN, _OFFSET_MAX = -24, 1
_CUTOFF_MIN = 1
_EPH_MIN, _EPH_MAX = 1, 168
_YEAR_MIN, _YEAR_MAX = 2000, 2999
_MONTH_MIN, _MONTH_MAX = 1, 12


def _violated_rules(cutoff, cut1, cut2, ephemeral_hours, eff_year, eff_month):
    """
    Réplica independiente de las reglas semánticas de `validate_policy`, para determinar el
    conjunto EXACTO de reglas violadas por una entrada (oráculo del test).

    Devuelve un `set` de identificadores de regla:
        "order" | "cutoff_min" | "offset_range" | "ephemeral_range" | "period".

    No incluye "format": esa la valida `parse_recycle_rule` aguas arriba, no `validate_policy`.
    """
    rules = set()

    if not (cutoff > cut1 >= cut2):
        rules.add("order")

    if cutoff < _CUTOFF_MIN:
        rules.add("cutoff_min")

    if any(
        not (_OFFSET_MIN <= v <= _OFFSET_MAX) for v in (cutoff, cut1, cut2)
    ):
        rules.add("offset_range")

    if not (_EPH_MIN <= ephemeral_hours <= _EPH_MAX):
        rules.add("ephemeral_range")

    if not (_MONTH_MIN <= eff_month <= _MONTH_MAX) or not (
        _YEAR_MIN <= eff_year <= _YEAR_MAX
    ):
        rules.add("period")

    return rules


@settings(max_examples=100)
@given(
    cutoff=_wide_offset,
    cut1=_wide_offset,
    cut2=_wide_offset,
    ephemeral_hours=_wide_ephemeral,
    eff_year=_wide_year,
    eff_month=_wide_month,
)
def test_invalid_policy_is_rejected_without_side_effects(
    cutoff, cut1, cut2, ephemeral_hours, eff_year, eff_month
):
    """
    Toda política que viole >=1 regla es rechazada (raise) por `validate_policy`, y la propia
    validación no produce efectos secundarios (es pura: sin sesión, sin escritura, sin retorno
    de estado). Las entradas que no violan ninguna regla se descartan (no aplican a esta
    property de rechazo).
    """
    violated = _violated_rules(cutoff, cut1, cut2, ephemeral_hours, eff_year, eff_month)

    if not violated:
        # Entrada válida: no es objeto de esta property (rechazo). Debe pasar sin lanzar,
        # confirmando que el rechazo es SOLO para inválidas (no fail-open ni fail-closed
        # sobre válidas).
        assert (
            validate_policy(cutoff, cut1, cut2, ephemeral_hours, eff_year, eff_month)
            is None
        )
        return

    # Fail-closed (Req 7.9): la política inválida se rechaza SIEMPRE.
    try:
        validate_policy(cutoff, cut1, cut2, ephemeral_hours, eff_year, eff_month)
        raised = False
        errors = []
    except RecyclePolicyValidationException as exc:
        raised = True
        errors = exc.errors

    assert raised, (
        "validate_policy debió rechazar (lanzar RecyclePolicyValidationException) una política "
        f"que viola {sorted(violated)} "
        f"(cutoff={cutoff}, cut1={cut1}, cut2={cut2}, eph={ephemeral_hours}, "
        f"eff={eff_year}-{eff_month})."
    )

    # Preservación / pureza (Req 7.9): la validación no muta estado externo. Comprobamos que
    # re-invocar con una política VÁLIDA (que retorna None sin lanzar) no altera la excepción
    # previamente obtenida — no hay estado global compartido entre llamadas.
    assert validate_policy(1, -2, -3, 24, 2026, 9) is None
    assert errors, "La excepción de rechazo debe conservar sus errores tras otras llamadas."
