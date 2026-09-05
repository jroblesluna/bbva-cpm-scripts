"""
Schemas Pydantic para tarifas y planes de facturación (task 17).

Definen la validación de entrada/salida de los endpoints de tarifas (solo superadmin):
- Planes por defecto del sistema (`billing_rate_plans`).
- Planes tarifarios individuales por organización (`billing_org_plans`).

Los tramos (tiers) se validan de forma mínima: una lista no vacía de objetos con `from`
(entero >= 1), `to` (entero > from, o null en el último tramo) y `rate` (numérico >= 0). Se
admiten campos adicionales de la modalidad anual (p.ej. `free_growth_to`) sin rechazarlos, ya
que el cálculo real vive en `BillingService`.

Nota de dinero: las tarifas pueden tener hasta 3 decimales; se representan como float en el
JSON de entrada/salida, pero el cálculo del monto se hace con Decimal en `BillingService`.
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# Modalidades válidas de facturación (coincide con el CHECK de la BD).
_VALID_MODES = ("monthly", "annual")


def _validate_tiers(tiers: List[dict]) -> List[dict]:
    """
    Valida mínimamente la estructura de los tramos (tiers).

    Reglas (Req 8.1, 8.2):
        - Lista no vacía.
        - Cada tramo es un objeto con `from` (int >= 1), `to` (int > from o null) y
          `rate` (numérico >= 0).
        - `from` debe ser estrictamente creciente entre tramos y no solaparse con el `to`
          del tramo anterior (los tramos van ordenados y son contiguos/crecientes).
        - Solo el último tramo puede tener `to = null` (tramo sin tope superior).

    No se valida la coherencia comercial de las tarifas (eso es decisión del superadmin);
    solo la forma para evitar que el motor de cálculo reciba datos corruptos.
    """
    if not isinstance(tiers, list) or len(tiers) == 0:
        raise ValueError("Los tramos (tiers) deben ser una lista no vacía")

    prev_to: Optional[int] = None
    for index, tier in enumerate(tiers):
        if not isinstance(tier, dict):
            raise ValueError(f"El tramo #{index} debe ser un objeto {{from, to, rate}}")

        if "from" not in tier or "rate" not in tier:
            raise ValueError(f"El tramo #{index} debe incluir 'from' y 'rate'")

        # 'from' entero >= 1
        try:
            tier_from = int(tier["from"])
        except (TypeError, ValueError):
            raise ValueError(f"El tramo #{index} tiene un 'from' no entero")
        if tier_from < 1:
            raise ValueError(f"El tramo #{index} tiene 'from' < 1")

        # 'to' entero > from, o null (solo permitido en el último tramo)
        tier_to = tier.get("to")
        is_last = index == len(tiers) - 1
        if tier_to is None:
            if not is_last:
                raise ValueError(
                    f"El tramo #{index} tiene 'to' = null pero no es el último tramo"
                )
        else:
            try:
                tier_to = int(tier_to)
            except (TypeError, ValueError):
                raise ValueError(f"El tramo #{index} tiene un 'to' no entero")
            if tier_to < tier_from:
                raise ValueError(f"El tramo #{index} tiene 'to' < 'from'")

        # 'rate' numérico >= 0
        try:
            rate = float(tier["rate"])
        except (TypeError, ValueError):
            raise ValueError(f"El tramo #{index} tiene un 'rate' no numérico")
        if rate < 0:
            raise ValueError(f"El tramo #{index} tiene 'rate' < 0")

        # Orden/contigüidad: cada 'from' debe superar el 'to' del tramo anterior.
        if prev_to is not None and tier_from <= prev_to:
            raise ValueError(
                f"El tramo #{index} tiene 'from' ({tier_from}) que no supera el 'to' "
                f"del tramo anterior ({prev_to}); los tramos deben ser crecientes"
            )
        prev_to = tier_to  # puede ser None solo en el último tramo

    return tiers


def _validate_mode(mode: str) -> str:
    """Valida que la modalidad sea 'monthly' o 'annual'."""
    if mode not in _VALID_MODES:
        raise ValueError(f"Modalidad inválida: {mode!r}. Debe ser uno de {_VALID_MODES}")
    return mode


# ── Planes por defecto del sistema (billing_rate_plans) ──────────────────────


class RatePlanUpdate(BaseModel):
    """
    Payload para editar/programar un plan por defecto del sistema (PUT /rate-plans/{id}).

    Todos los campos son opcionales: solo se actualizan los enviados. Las tarifas mensuales
    son editables y aplican a cierres futuros (Req 8.5). La tarifa anual también se puede
    editar aquí, pero por diseño solo debe aplicarse antes de una renovación (Req 8.6); la
    congelación durante una suscripción anual vigente se enforcea en las tasks 19-21.
    """

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    tiers: Optional[List[dict]] = Field(
        None, description="Tramos {from, to|null, rate, ...} ordenados por rango"
    )
    currency: Optional[str] = Field(None, min_length=3, max_length=3)
    effective_from: Optional[datetime] = Field(
        None, description="Vigencia programada (null = vigente de inmediato)"
    )

    @field_validator("tiers")
    @classmethod
    def _check_tiers(cls, v):
        if v is None:
            return v
        return _validate_tiers(v)


class RatePlanResponse(BaseModel):
    """Respuesta con un plan por defecto del sistema."""

    id: UUID
    mode: str
    is_default: bool
    name: str
    tiers: List[dict]
    currency: str
    effective_from: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Planes individuales por organización (billing_org_plans) ─────────────────


class OrgPlanUpsert(BaseModel):
    """
    Payload para crear/actualizar el plan individual de una organización por modalidad
    (PUT /organizations/{org_id}/plan).

    La modalidad determina a qué plan de la org se aplica (una fila por modalidad). Editar
    este plan NUNCA toca los planes por defecto del sistema ni los planes de otras orgs
    (Req 8.8: los defaults tampoco sobrescriben este plan, por ser filas separadas).
    """

    mode: str = Field(..., description="Modalidad del plan: 'monthly' | 'annual'")
    tiers: List[dict] = Field(..., description="Tramos {from, to|null, rate, ...}")
    currency: str = Field("USD", min_length=3, max_length=3)
    effective_from: Optional[datetime] = Field(
        None, description="Vigencia programada (null = vigente de inmediato)"
    )

    @field_validator("mode")
    @classmethod
    def _check_mode(cls, v):
        return _validate_mode(v)

    @field_validator("tiers")
    @classmethod
    def _check_tiers(cls, v):
        return _validate_tiers(v)


class OrgPlanResponse(BaseModel):
    """Respuesta con un plan individual de organización."""

    id: UUID
    organization_id: UUID
    mode: str
    tiers: List[dict]
    currency: str
    effective_from: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Modalidad de facturación de la organización (billing_mode) ───────────────


class OrgModeUpdate(BaseModel):
    """
    Payload para fijar la modalidad de facturación de una organización
    (PUT /billing/organizations/{org_id}/mode).

    La modalidad determina cómo se factura la organización (Req 4.1):
        - 'monthly': tarifa incremental por tramos, reportada en cada cierre mensual.
        - 'annual': tarifa preferencial anual; los invoices mensuales se emiten en 0.00
          durante la vigencia y la liquidación se gestiona por separado (tasks 19-20).

    Se valida el enum en el schema para rechazar valores fuera de ('monthly', 'annual')
    con un 422 antes de llegar a la lógica del endpoint.
    """

    mode: str = Field(..., description="Modalidad de facturación: 'monthly' | 'annual'")

    @field_validator("mode")
    @classmethod
    def _check_mode(cls, v):
        return _validate_mode(v)


class OrgModeResponse(BaseModel):
    """Respuesta con la modalidad de facturación vigente de una organización."""

    organization_id: UUID
    billing_mode: str

    model_config = {"from_attributes": True}
