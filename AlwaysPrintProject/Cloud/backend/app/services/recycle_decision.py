"""
Núcleo puro de decisión de reciclaje del módulo Usage and Billing (recycle-policy-config).

Este módulo extrae la decisión de reciclaje del motor de cierre a una función pura y
determinista, `decide_recycle`, cuya firma restringe los insumos a los CINCO permitidos
(Req 10.3). Al no recibir ni la `Workstation` ni la `Session`, es imposible —a nivel de
interfaz, no solo de documentación— que la decisión dependa de la base de datos o de un
"reloj de pared": solo depende de los datos crudos de la workstation, la timezone de la
organización y la política congelada del cierre.

Semántica de la decisión (idéntica al `_should_recycle` histórico, pero parametrizada por
la política resuelta/congelada en vez de las constantes hardcodeadas):

- Caso 2 — abandono (Req 14.x): `last_seen < cut2`. Recicla independientemente del uso.
- Caso 1 — poco uso (Req 13.x): `last_seen < cut1` Y el uso del ciclo de actividad vigente
  `(last_seen - billing_cycle_started_at)` es menor que `ephemeral_hours * 3600` segundos.
  El uso se mide contra `billing_cycle_started_at` (Req 18.4), NO contra `created_at`.

Los tres cortes (`cutoff`, `cut1`, `cut2`) se derivan de los offsets de la política vía las
mismas primitivas de `billing_time` que usa `compute_cuts`, por lo que el resultado es
consistente byte-a-byte con el motor de cierre para la misma política y timezone.

Notas de acoplamiento (ordering de tareas):
- `ResolvedRecyclePolicy` (task 3.1) y la parametrización de `compute_cuts`/`RecycleRule`
  (task 4.1) aterrizan DESPUÉS de este módulo. Para que el módulo importe y compile antes
  de que existan, el tipo de la política se referencia solo bajo `TYPE_CHECKING` y los
  cortes se reconstruyen dentro de la función con imports diferidos de `billing_time`,
  accediendo a los atributos de la política por duck typing (`cutoff`, `cut1`, `cut2`,
  `ephemeral_hours`). Cuando `compute_cuts` quede parametrizado (task 4.1), este módulo
  puede migrar a usarlo directamente sin cambiar su contrato público.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Solo para type-checking: evita un import circular / de ordenamiento en runtime.
    # La política real la aporta task 3.1; aquí se usa por duck typing (ver decide_recycle).
    from app.services.recycle_policy_service import ResolvedRecyclePolicy


@dataclass(frozen=True)
class RecycleInputs:
    """
    Los CINCO —y únicos— insumos permitidos para decidir el reciclaje (Req 10.3).

    Al ser un `dataclass` congelado con exactamente estos campos, la firma de
    `decide_recycle` restringe los insumos a nivel de interfaz: no hay forma de colar la
    `Workstation` completa, la `Session` de BD ni `datetime.now()`.

    Attributes:
        created_at: alta histórica de la workstation. Se conserva por su semántica de
            auditoría/alcance del cierre; NO se usa para medir el uso efímero (Req 18.4).
        billing_cycle_started_at: inicio del ciclo de actividad vigente (se reinicia al
            reactivar desde `recycled`/`archived`). Base para medir el uso efímero (Req 18.4).
        last_seen: última actividad, CRUDA (sin capar; Req 10.1).
        timezone: nombre IANA de la zona horaria de la organización (para calcular cortes).
        policy: política congelada del cierre (offsets + umbral efímero).
    """

    created_at: datetime
    billing_cycle_started_at: datetime
    last_seen: datetime
    timezone: str
    policy: "ResolvedRecyclePolicy"


def decide_recycle(inputs: RecycleInputs, year: int, month: int) -> bool:
    """
    Decisión pura y determinista de reciclaje para el cierre del mes M=`month`, año `year`.

    NO recibe la `Workstation` ni la `Session`: la firma restringe los insumos a los cinco
    permitidos (Req 10.3). No accede a la base de datos ni al "reloj de pared" — el resultado
    depende únicamente de `inputs` y del periodo `(year, month)`, lo que hace la decisión
    reproducible y verificable por property-based testing (Req 10.2).

    Args:
        inputs: los cinco insumos permitidos (ver `RecycleInputs`).
        year: año del mes a cerrar (M).
        month: mes a cerrar (1..12).

    Returns:
        `True` si la workstation debe reciclarse (Caso 1 poco uso o Caso 2 abandono),
        `False` en caso contrario.

    Raises:
        ValueError: si `month` no está en 1..12 (propagado desde el cálculo de cortes).
        zoneinfo.ZoneInfoNotFoundError: si `inputs.timezone` no es una zona IANA válida.
    """
    # Import diferido: `billing_time` provee las primitivas de fecha (estables, no cambian
    # de firma). Se importan aquí para no acoplar la carga del módulo al ordenamiento de
    # tareas y para reconstruir los cortes con los offsets de la política congelada.
    from app.services.billing_time import (
        _local_month_start_utc_naive,
        _shift_month,
    )

    policy = inputs.policy

    if not 1 <= month <= 12:
        raise ValueError(f"month debe estar en 1..12, se recibió {month}")

    # Cortes derivados de los offsets de la política (duck typing sobre `policy`):
    # cut1 (Caso 1, poco uso) y cut2 (Caso 2, abandono). El cutoff no interviene en la
    # decisión de reciclaje (define el alcance del cierre, resuelto por el caller).
    cut1_year, cut1_month = _shift_month(year, month, policy.cut1)
    cut2_year, cut2_month = _shift_month(year, month, policy.cut2)
    cut1 = _local_month_start_utc_naive(inputs.timezone, cut1_year, cut1_month)
    cut2 = _local_month_start_utc_naive(inputs.timezone, cut2_year, cut2_month)

    last_seen = inputs.last_seen  # crudo (Req 10.1)

    # Caso 2 — abandono: last_seen anterior a cut2, independiente del uso (Req 14.x).
    if last_seen < cut2:
        return True

    # Caso 1 — poco uso: last_seen anterior a cut1 y uso del ciclo vigente < umbral (Req 13.x).
    if last_seen < cut1:
        # Uso medido contra billing_cycle_started_at, NO created_at (Req 18.4).
        uso = (last_seen - inputs.billing_cycle_started_at).total_seconds()
        return uso < policy.ephemeral_hours * 3600

    return False
