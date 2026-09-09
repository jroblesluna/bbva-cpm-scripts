# Feature: recycle-policy-config, Property 3: Resolución es independiente de la fecha de ejecución
"""
Property test de la Property 3 (resolución independiente de la fecha de ejecución).

*For any* organización, periodo `M=(year, month)` y conjunto de filas de política
persistidas, `RecyclePolicyService.resolve_recycle_policy(db, org, year, month)` produce
SIEMPRE el mismo resultado, sin importar el instante de reloj de pared en que se ejecute
(Req 3.4 / 10.1). La resolución versiona por periodo, no por fecha de ejecución: un cierre
retroactivo debe resolver la política vigente ESE mes, no la de hoy.

Estrategia de verificación:
    (a) Se resuelve la política bajo VARIOS relojes de pared muy distintos (año 1999 hasta
        2999, incluyendo instantes anteriores, iguales y posteriores a los periodos efectivos
        de las políticas sembradas). Todos los resultados deben ser idénticos entre sí.
    (b) Además se compara contra una resolución SIN mock del reloj: el resultado real y el
        de cualquier reloj congelado coinciden byte a byte.

El reloj de pared se congela parcheando `datetime.datetime` (now/utcnow/today) a nivel del
módulo `datetime` global, de modo que si alguna ruta del servicio (o de SQLAlchemy en la
query) leyera la hora actual, quedaría fijada al valor congelado. Como la firma de
`resolve_recycle_policy` NO recibe fecha de ejecución, la invariancia observada confirma la
propiedad a nivel de comportamiento.

**Validates: Requirements 3.4, 10.1**
"""

import datetime as real_datetime_module
import uuid
from datetime import datetime
from unittest import mock

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.models.billing import BillingRecyclePolicy
from app.models.organization import Organization
from app.services.recycle_policy_service import (
    ResolvedRecyclePolicy,
    recycle_policy_service,
)


# Relojes de pared representativos: mucho antes de cualquier periodo efectivo, en el medio y
# mucho después. Si la resolución dependiera de "ahora", estos producirían resultados
# distintos entre sí. Debe ser invariante a todos ellos.
FROZEN_CLOCKS = [
    datetime(1999, 1, 1, 0, 0, 0),
    datetime(2024, 6, 15, 12, 30, 0),
    datetime(2026, 9, 1, 0, 0, 0),
    datetime(2500, 12, 31, 23, 59, 59),
    datetime(2999, 12, 1, 8, 0, 0),
]


class _FrozenDateTime(datetime):
    """Subclase de datetime cuyo reloj (now/utcnow/today) devuelve un instante fijo."""

    _frozen = datetime(2000, 1, 1)

    @classmethod
    def now(cls, tz=None):
        if tz is not None:
            return cls._frozen.replace(tzinfo=tz)
        return cls._frozen

    @classmethod
    def utcnow(cls):
        return cls._frozen

    @classmethod
    def today(cls):
        return cls._frozen


def _resolve_with_clock(db, org, year, month, frozen):
    """Resuelve la política con el reloj de pared congelado en `frozen`."""
    _FrozenDateTime._frozen = frozen
    # Parchear datetime.datetime a nivel global: cualquier `from datetime import datetime`
    # ya resuelto sigue apuntando al original, pero rutas que hagan `datetime.datetime.now()`
    # o que el servicio pudiera introducir en el futuro quedan congeladas. El objetivo es
    # demostrar que el resultado no cambia bajo ninguna noción de "ahora".
    with mock.patch.object(real_datetime_module, "datetime", _FrozenDateTime):
        result = recycle_policy_service.resolve_recycle_policy(db, org, year, month)
    # Normalizamos a tupla comparable (los objetos son frozen dataclasses => ya comparables,
    # pero policy_id incluye el uuid como str, estable entre corridas sobre la misma fila).
    return result


def _make_org(db, name):
    org = Organization(id=uuid.uuid4(), name=name, timezone="America/Lima")
    db.add(org)
    db.flush()
    return org


def _add_policy(db, *, org_id, cutoff, cut1, cut2, hours, year, month):
    policy = BillingRecyclePolicy(
        id=uuid.uuid4(),
        organization_id=org_id,
        cutoff_offset=cutoff,
        cut1_offset=cut1,
        cut2_offset=cut2,
        ephemeral_hours=hours,
        effective_from_year=year,
        effective_from_month=month,
        effective_key=recycle_policy_service.period_key(year, month),
    )
    db.add(policy)
    db.flush()
    return policy


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    # Periodo M del cierre.
    year=st.integers(min_value=2024, max_value=2030),
    month=st.integers(min_value=1, max_value=12),
    # ¿Sembrar un Global_Default? ¿Y un Org_Override? Cubre las 3 ramas de fallback:
    # override, default y legacy.
    seed_global=st.booleans(),
    seed_override=st.booleans(),
    # Periodos efectivos de las políticas sembradas (pueden quedar antes o después de M,
    # ejercitando la semántica <= y el fallback).
    global_year=st.integers(min_value=2000, max_value=2030),
    global_month=st.integers(min_value=1, max_value=12),
    override_year=st.integers(min_value=2000, max_value=2030),
    override_month=st.integers(min_value=1, max_value=12),
    # Parámetros de las políticas (valores arbitrarios pero válidos como enteros).
    g_hours=st.integers(min_value=1, max_value=168),
    o_hours=st.integers(min_value=1, max_value=168),
)
def test_resolution_is_independent_of_execution_date(
    db,
    year,
    month,
    seed_global,
    seed_override,
    global_year,
    global_month,
    override_year,
    override_month,
    g_hours,
    o_hours,
):
    """
    La política resuelta para un `(org, year, month)` fijo con filas fijas es idéntica bajo
    cualquier reloj de pared. Además coincide con la resolución real sin mock.
    """
    # Aislar el estado por ejemplo de Hypothesis (la fixture db es de función; limpiamos
    # las tablas relevantes entre ejemplos para no acumular filas de iteraciones previas).
    db.query(BillingRecyclePolicy).delete()
    db.query(Organization).delete()
    db.flush()

    org = _make_org(db, name=f"Org-{uuid.uuid4()}")

    if seed_global:
        _add_policy(
            db,
            org_id=None,
            cutoff=1,
            cut1=-2,
            cut2=-3,
            hours=g_hours,
            year=global_year,
            month=global_month,
        )
    if seed_override:
        _add_policy(
            db,
            org_id=org.id,
            cutoff=1,
            cut1=0,
            cut2=-1,
            hours=o_hours,
            year=override_year,
            month=override_month,
        )

    # Resolución real (sin mock del reloj): línea base.
    baseline = recycle_policy_service.resolve_recycle_policy(db, org, year, month)
    assert isinstance(baseline, ResolvedRecyclePolicy)

    # Resolución bajo cada reloj congelado: todas deben ser idénticas a la línea base.
    for frozen in FROZEN_CLOCKS:
        under_clock = _resolve_with_clock(db, org, year, month, frozen)
        assert under_clock == baseline, (
            f"La resolución cambió con el reloj {frozen.isoformat()}: "
            f"{under_clock} != {baseline}"
        )


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    year=st.integers(min_value=2024, max_value=2030),
    month=st.integers(min_value=1, max_value=12),
    clock_a=st.sampled_from(FROZEN_CLOCKS),
    clock_b=st.sampled_from(FROZEN_CLOCKS),
)
def test_repeated_resolution_under_different_clocks_is_stable(
    db, year, month, clock_a, clock_b
):
    """
    Con un Org_Override vigente para M, resolver bajo dos relojes distintos (A y B) devuelve
    exactamente el mismo resultado, y llamadas repetidas también (idempotencia temporal).
    """
    db.query(BillingRecyclePolicy).delete()
    db.query(Organization).delete()
    db.flush()

    org = _make_org(db, name=f"Org-{uuid.uuid4()}")
    # Override vigente para M (effective en el propio periodo, semántica inclusiva).
    _add_policy(
        db,
        org_id=org.id,
        cutoff=1,
        cut1=0,
        cut2=-1,
        hours=24,
        year=year,
        month=month,
    )

    r_a1 = _resolve_with_clock(db, org, year, month, clock_a)
    r_b = _resolve_with_clock(db, org, year, month, clock_b)
    r_a2 = _resolve_with_clock(db, org, year, month, clock_a)

    # Debe resolver al override (source="org"), y ser idéntico bajo A, B y repeticiones.
    assert r_a1.source == "org"
    assert r_a1 == r_b == r_a2
