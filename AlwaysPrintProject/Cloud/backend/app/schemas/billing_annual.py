"""
Schemas Pydantic para la suscripción anual (task 19) — solo superadministrador.

Definen la validación de entrada/salida del endpoint de creación de suscripción anual del
módulo Usage and Billing:
- POST /billing/organizations/{org_id}/annual-subscription

La suscripción congela la tarifa/tramo/tope declarados (Req 8.6) y registra el volumen
declarado (input manual del superadmin, Req 9.1). Las fechas de inicio/fin las calcula el
servicio (no las envía el cliente): inicio = `created_at` del primer registro,
fin = aniversario − 1 día.

Nota de dinero: `tier_rate` puede tener hasta 3-4 decimales; se acepta como Decimal para no
perder precisión (el cálculo se hace con Decimal en el servicio).
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class AnnualSubscriptionCreate(BaseModel):
    """
    Payload para crear una suscripción anual (POST .../annual-subscription).

    El cliente NO envía las fechas: el servicio deriva `start_date` del primer `created_at`
    de la organización y `end_date` como el aniversario − 1 día. Solo se envían el volumen
    declarado y los parámetros del tramo contratado (que se congelan).
    """

    declared_volume: int = Field(
        ...,
        ge=0,
        description="Volumen declarado por el superadministrador (número de IPs contratadas)",
    )
    tier_from: int = Field(
        ...,
        ge=1,
        description="Límite inferior del tramo contratado (inclusive)",
    )
    tier_rate: Decimal = Field(
        ...,
        ge=0,
        description="Tarifa unitaria del tramo (US$/IP/año), congelada durante la vigencia",
    )
    tier_to: Optional[int] = Field(
        None,
        ge=1,
        description="Límite superior del tramo (inclusive) o null si es el último tramo",
    )
    tier_cap: Optional[int] = Field(
        None,
        ge=0,
        description="Tope contabilizable de la liquidación (ej. 10000) o null",
    )

    @model_validator(mode="after")
    def _check_tier_bounds(self):
        """Valida que `tier_to`, si se envía, no sea menor que `tier_from`."""
        if self.tier_to is not None and self.tier_to < self.tier_from:
            raise ValueError("'tier_to' no puede ser menor que 'tier_from'")
        return self


class AnnualSubscriptionResponse(BaseModel):
    """Respuesta con una suscripción anual creada."""

    id: UUID
    organization_id: UUID
    start_date: datetime
    end_date: datetime
    declared_volume: int
    tier_rate: Decimal
    tier_from: int
    tier_to: Optional[int] = None
    tier_cap: Optional[int] = None
    status: str
    settlement: Optional[dict] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AnnualFreeGrowth(BaseModel):
    """
    Indicador informativo de "crecimiento libre" del tramo contratado (Req 9.6).

    Es puramente informativo: NO reclasifica automáticamente. Indica si el uso real permanece
    dentro del margen `free_growth_to` del tramo o si requeriría reclasificación.
    """

    within_free_growth: bool = Field(
        ...,
        description="True si el uso real permanece dentro del margen de crecimiento libre",
    )
    free_growth_to: Optional[int] = Field(
        None,
        description="Límite de crecimiento libre del tramo contratado (o null si no aplica)",
    )
    requires_reclassification: bool = Field(
        ...,
        description="True si el uso real excede el margen y requeriría reclasificación (informativo)",
    )


class AnnualSettlementResponse(BaseModel):
    """
    Respuesta con la liquidación anual (informativa) en el aniversario (Req 9.3-9.6).

    `credit`/`charge`/`tier_rate` se exponen como Decimal (dinero) con precisión preservada.
    El GET la calcula en vivo (no persiste); el POST /confirm la aplica (status='settled').
    """

    declared: int = Field(..., description="Volumen declarado en la suscripción")
    real: int = Field(..., description="Uso real contabilizado (min(billable, tier_cap))")
    billable_count: int = Field(
        ..., description="IPs 'billable' de la organización al momento de la liquidación"
    )
    tier_cap: Optional[int] = Field(
        None, description="Tope contabilizable del tramo contratado (o null)"
    )
    diff: int = Field(..., description="Diferencia declarado − real (Req 9.4)")
    credit: Decimal = Field(..., description="Crédito sugerido si real < declarado")
    charge: Decimal = Field(..., description="Cargo sugerido si real > declarado")
    tier_rate: Decimal = Field(..., description="Tarifa unitaria congelada del tramo")
    free_growth: AnnualFreeGrowth = Field(
        ..., description="Indicador informativo de crecimiento libre / reclasificación"
    )
