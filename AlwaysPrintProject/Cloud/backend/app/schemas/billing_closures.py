"""
Schemas Pydantic para cierres mensuales (task 27) del módulo Usage and Billing.

Definen la validación de salida de los endpoints de cierres:
- Cabecera de cierre (`BillingClosure`): totales por estado, monto, tramos y metadatos.
- Detalle por IP (`BillingClosureItem`): sustento inmutable de cada workstation en el corte.
- Respuesta del cierre retroactivo: la cabecera creada o una señal de "sin meses pendientes".
- Página de ítems: detalle por IP paginado.

Todos los cierres se leen filtrando por `organization_id` (tenant isolation, Req 11.3). Estos
schemas son de solo lectura (el snapshot es inmutable, Req 6.4): no hay payloads de escritura.
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel


class ClosureHeaderResponse(BaseModel):
    """
    Cabecera de un cierre mensual (una por organización/año/mes).

    Refleja el sustento inmutable del cierre (Req 6.1): periodo, corte, modalidad/tz usadas,
    totales por estado, monto calculado y desglose por tramo. `is_retroactive` indica si el
    cierre se generó de forma retroactiva (histórico).
    """

    id: UUID
    organization_id: UUID
    period_year: int
    period_month: int
    cutoff_at: datetime
    mode: str
    timezone: str
    total_billable: int
    total_recycled: int
    total_archived: int
    amount: Decimal
    tiers_applied: list
    is_retroactive: bool
    created_by_id: Optional[UUID] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class RetroactiveCloseResponse(BaseModel):
    """
    Respuesta del endpoint de cierre retroactivo (Req 7.2, 7.3).

    Semántica:
    - `closed = True` con `closure` poblado: se cerró el mes pendiente más antiguo.
    - `closed = False` con `closure = None`: no había meses pendientes por cerrar (todos los
      meses finalizados ya tenían cierre, o la organización no tiene IPs). En ese caso `detail`
      explica el motivo y `closure` queda en None (respuesta 200 idempotente, no un error).
    """

    closed: bool
    detail: str
    closure: Optional[ClosureHeaderResponse] = None


class ClosureItemResponse(BaseModel):
    """
    Detalle por IP de un cierre (una fila por workstation en el corte, Req 6.2).

    `last_seen_capped` es el `last_seen` capado a `cutoff` (Req 5.7); `billing_status` es el
    estado histórico de ESA IP en ESE cierre. `tier_index`/`amount` son el tramo y aporte de
    monto asignados a la IP (solo para las facturables; el resto en None/0).
    """

    id: UUID
    closure_id: UUID
    workstation_id: Optional[UUID] = None
    ip_private: str
    created_at_ws: datetime
    last_seen_capped: datetime
    billing_status: str
    tier_index: Optional[int] = None
    amount: Decimal

    model_config = {"from_attributes": True}


class ClosureItemsPage(BaseModel):
    """
    Página del detalle por IP de un cierre (paginación por `page`/`page_size`).

    `total` es el número total de ítems del cierre (para calcular el número de páginas en la
    UI); `items` es la página solicitada.
    """

    total: int
    page: int
    page_size: int
    items: List[ClosureItemResponse]
