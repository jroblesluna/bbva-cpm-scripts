"""
Utilidades de tiempo por organización del módulo Usage and Billing (task 12).

El motor de cierre mensual (`BillingCloseService`, task 13) necesita traducir un mes
lógico M (año Y) a tres instantes de corte concretos, calculados SIEMPRE en la zona
horaria de la organización y luego convertidos a UTC para persistir/comparar:

- `cutoff`  = 00:00 del día 1 de (M+1)  → fin del mes cerrado (Req 5.1).
- `cut1`    = 00:00 del día 1 de (M−2)  → corte de inactividad, Caso 1 (Req 5.4).
- `cut2`    = 00:00 del día 1 de (M−3)  → corte de abandono,   Caso 2 (Req 5.5).

Ejemplo del requisito (cerrando noviembre, M=11): `cut1` = 00:00 del 1 de septiembre
y `cut2` = 00:00 del 1 de agosto. Es decir, `cut1` es el primer día de dos meses antes
de M, y `cut2` el primer día de tres meses antes de M.

Diseño de fechas:
- Se construye la medianoche local (00:00 del día 1 del mes objetivo) con
  `zoneinfo.ZoneInfo(timezone)` y luego se convierte a UTC con `astimezone`. Delegar en
  `zoneinfo` garantiza que los cruces de DST se resuelvan con la base de datos de zonas
  del sistema (p. ej. Europe/Madrid: verano UTC+2, invierno UTC+1). America/Lima no tiene
  DST, pero el mismo código es correcto para zonas que sí lo tienen.
- El día 1 a las 00:00 nunca cae dentro de una transición DST ambigua/inexistente en las
  zonas reales de uso, por lo que no se necesita `fold`; aun así se documenta el supuesto.
- Los tres cortes se devuelven como `datetime` NAIVE en UTC (sin `tzinfo`), coherente con
  el resto del modelo, que almacena timestamps naive en UTC
  (`datetime.now(timezone.utc).replace(tzinfo=None)`; ver `services/workstation.py`,
  `services/telemetry.py`, etc.). Así `cutoff`/`cut1`/`cut2` son directamente comparables
  con `workstations.created_at` y `workstations.last_seen`.

Manejo de rollover:
- El aritmético de meses se hace sobre un contador absoluto de meses
  (`Y*12 + (M-1)`), de modo que los cruces de año (Dic→Ene hacia delante, y Ene→meses del
  año anterior hacia atrás para M−2/M−3) se resuelven sin casos especiales.
"""

from datetime import datetime, timezone
from typing import NamedTuple
from zoneinfo import ZoneInfo


class BillingCuts(NamedTuple):
    """
    Los tres cortes de un cierre mensual, como `datetime` naive en UTC.

    Attributes:
        cutoff: 00:00 del día 1 de (M+1) en la tz de la org, en UTC (fin del mes M).
        cut1:   00:00 del día 1 de (M−2) en la tz de la org, en UTC (Caso 1, inactividad).
        cut2:   00:00 del día 1 de (M−3) en la tz de la org, en UTC (Caso 2, abandono).
    """

    cutoff: datetime
    cut1: datetime
    cut2: datetime


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    """
    Desplaza `delta` meses (positivo o negativo) sobre `(year, month)`.

    Usa un contador absoluto de meses (0-based sobre el mes) para que los cruces de año
    se resuelvan sin casos especiales. `month` es 1..12.

    Returns:
        La tupla `(año, mes)` resultante, con `mes` en 1..12.
    """
    # Índice absoluto 0-based del mes (enero del año 0 = 0).
    absolute = year * 12 + (month - 1) + delta
    new_year, new_month_index = divmod(absolute, 12)
    return new_year, new_month_index + 1


def _local_month_start_utc_naive(timezone_name: str, year: int, month: int) -> datetime:
    """
    Construye las 00:00 del día 1 de `(year, month)` en `timezone_name` y las devuelve
    como `datetime` naive en UTC.

    Args:
        timezone_name: nombre IANA de la zona (p. ej. `America/Lima`, `Europe/Madrid`, `UTC`).
        year: año del mes objetivo.
        month: mes objetivo (1..12).

    Returns:
        `datetime` naive (sin tzinfo) equivalente a esa medianoche local, expresada en UTC.
    """
    tz = ZoneInfo(timezone_name)
    # Medianoche local del día 1 del mes objetivo (aware en la tz de la org).
    local_midnight = datetime(year, month, 1, 0, 0, 0, tzinfo=tz)
    # Convertir a UTC y quitar tzinfo para dejarlo naive-UTC (convención del modelo).
    return local_midnight.astimezone(timezone.utc).replace(tzinfo=None)


def compute_cuts(timezone_name: str, year: int, month: int) -> BillingCuts:
    """
    Calcula los tres cortes de un cierre mensual para el mes M=`month` del año Y=`year`.

    Todos los cortes se construyen como 00:00 del día 1 del mes correspondiente en la zona
    horaria de la organización (`timezone_name`) y se devuelven como `datetime` naive en UTC.

    Args:
        timezone_name: nombre IANA de la zona horaria de la organización.
        year: año del mes a cerrar (M).
        month: mes a cerrar (1..12).

    Returns:
        `BillingCuts(cutoff, cut1, cut2)`:
        - cutoff = 00:00 día 1 de (M+1)  (Req 5.1)
        - cut1   = 00:00 día 1 de (M−2)  (Req 5.4, Caso 1)
        - cut2   = 00:00 día 1 de (M−3)  (Req 5.5, Caso 2)

    Raises:
        ValueError: si `month` no está en 1..12.
        zoneinfo.ZoneInfoNotFoundError: si `timezone_name` no es una zona IANA válida.
    """
    if not 1 <= month <= 12:
        raise ValueError(f"month debe estar en 1..12, se recibió {month}")

    cutoff_year, cutoff_month = _shift_month(year, month, +1)  # M+1
    cut1_year, cut1_month = _shift_month(year, month, -2)      # M−2
    cut2_year, cut2_month = _shift_month(year, month, -3)      # M−3

    return BillingCuts(
        cutoff=_local_month_start_utc_naive(timezone_name, cutoff_year, cutoff_month),
        cut1=_local_month_start_utc_naive(timezone_name, cut1_year, cut1_month),
        cut2=_local_month_start_utc_naive(timezone_name, cut2_year, cut2_month),
    )
