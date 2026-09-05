"""
Servicio de tarifas y cálculo de facturación mensual del módulo Usage and Billing (task 15).

`BillingService` resuelve el plan tarifario aplicable a una organización y calcula el monto
mensual por tramos (incremental). Es un componente sin estado: cada método opera sobre la
sesión y la organización recibidas. La integración con el motor de cierre (poblar `amount`,
`tiers_applied` y el aporte por IP) se hace en la task 16; aquí solo se proveen los helpers.

Diseño (ver `design.md`, secciones "billing_org_plans", "billing_rate_plans" y
"Cálculo de monto mensual (incremental por tramos)"):

Resolución de plan (Req 8.2, 8.8):
    - Si la organización tiene un `billing_org_plans` para la modalidad → se usa su `tiers`.
    - Si no → se usa el `billing_rate_plans` por defecto vigente (`is_default = True`,
      misma `mode`) con el mayor `effective_from` que sea <= ahora (un `effective_from` NULL
      se considera vigente de inmediato). Los cambios de defaults NO sobrescriben planes de
      organización.
    - Tenant isolation: la búsqueda del plan de org filtra por `organization_id`.

Cálculo mensual (Req 8.3, 8.7):
    - Incremental por tramos: cada tramo `[from, to, rate]` factura solo las IPs contenidas
      en él → `ips_in_tier = max(0, min(count, to) - from + 1)` (con `to = None` = tramo sin
      tope superior, es decir `to = +infinito` → `min(count, inf) = count`).
    - Las tarifas unitarias pueden tener hasta 3 decimales; el TOTAL final se redondea a 2
      decimales con redondeo half-up (`Decimal.ROUND_HALF_UP`).
    - Ejemplo: 3,136 IPs = 100×0.50 + 1,900×0.25 + 1,136×0.20 = 752.20.

Principios del repo (impact-analysis):
    - Todo el dinero se maneja con `Decimal` (nunca `float`) para evitar errores de redondeo.
    - Tenant isolation: toda query filtra por `organization_id`.
    - Fail-closed: si no hay plan por defecto vigente para la modalidad, se lanza un error
      explícito en lugar de facturar con una tarifa desconocida.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.billing import BillingOrgPlan, BillingRatePlan
from app.models.organization import Organization

logger = get_logger(__name__)

# Cuantización objetivo del monto final: 2 decimales (Req 8.7).
_MONEY_QUANTUM = Decimal("0.01")


class BillingRateResolutionError(Exception):
    """
    No se pudo resolver un plan tarifario para la organización/modalidad (fail-closed).

    Se lanza cuando la organización no tiene plan individual y tampoco existe un plan por
    defecto vigente para la modalidad solicitada. Facturar sin tarifa conocida sería
    incorrecto, por lo que se aborta en lugar de asumir un valor.
    """


@dataclass
class ResolvedPlan:
    """
    Plan tarifario resuelto para una organización y modalidad.

    Contiene los `tiers` que el motor de cierre usará para calcular el monto y para poblar
    `tiers_applied`, junto con metadatos del plan de origen (útiles para el sustento y la UI).

    Atributos:
        tiers: lista de tramos (dicts) en formato `{"from", "to", "rate", ...}`.
        currency: moneda del plan (p.ej. "USD").
        source: "org" si proviene de un `billing_org_plans`; "default" si del plan por defecto.
        plan_id: id del plan de origen (BillingOrgPlan.id o BillingRatePlan.id), como str.
        mode: modalidad del plan ("monthly" | "annual").
    """

    tiers: List[dict] = field(default_factory=list)
    currency: str = "USD"
    source: str = "default"
    plan_id: Optional[str] = None
    mode: str = "monthly"


@dataclass
class TierBreakdown:
    """
    Aporte de un tramo al monto mensual, apto para almacenar en `tiers_applied` y para
    derivar el `tier_index` de cada IP en el detalle del cierre.

    Atributos:
        tier_index: índice del tramo (0-based) dentro de la lista de tramos del plan.
        tier_from: límite inferior del tramo (inclusive).
        tier_to: límite superior del tramo (inclusive) o None si es el último tramo (sin tope).
        rate: tarifa unitaria del tramo (Decimal, hasta 3 decimales).
        ips_in_tier: cantidad de IPs contabilizadas en este tramo.
        subtotal: aporte del tramo = `ips_in_tier * rate` (Decimal, SIN redondear a 2 dec.).
    """

    tier_index: int
    tier_from: int
    tier_to: Optional[int]
    rate: Decimal
    ips_in_tier: int
    subtotal: Decimal

    def to_dict(self) -> dict:
        """Serializa el desglose a un dict JSON-friendly (para `tiers_applied`)."""
        return {
            "tier_index": self.tier_index,
            "from": self.tier_from,
            "to": self.tier_to,
            # Las tarifas y subtotales se serializan como string para no perder precisión
            # decimal al pasar por JSON (evita el float binario).
            "rate": str(self.rate),
            "ips_in_tier": self.ips_in_tier,
            "subtotal": str(self.subtotal),
        }


class BillingService:
    """
    Servicio de resolución de plan tarifario y cálculo de facturación mensual.

    Sin estado: cada método recibe la sesión y/o la organización sobre las que opera. La
    instancia compartida `billing_service` se reutiliza desde el motor de cierre (task 16)
    y los endpoints de tarifas (task 17).
    """

    # ── Resolución de plan (Req 8.2, 8.8) ─────────────────────────────────────

    def resolve_plan(
        self,
        db: Session,
        org: Organization,
        mode: Optional[str] = None,
    ) -> ResolvedPlan:
        """
        Resuelve el plan tarifario aplicable a `org` para la modalidad `mode`.

        Prioridad:
            1. Plan individual de la organización (`billing_org_plans`) para esa modalidad
               (tenant isolation por `organization_id`). Si hay varios, se toma el de mayor
               `effective_from` vigente (<= ahora; NULL = vigente de inmediato).
            2. Plan por defecto del sistema (`billing_rate_plans` con `is_default = True`) de
               esa modalidad, con el mayor `effective_from` vigente (<= ahora; NULL vigente).

        Args:
            db: sesión SQLAlchemy activa.
            org: organización objetivo.
            mode: modalidad ("monthly" | "annual"). Si es None, se usa `org.billing_mode`.

        Returns:
            ResolvedPlan con los `tiers`, la moneda y los metadatos del plan de origen.

        Raises:
            BillingRateResolutionError: si no hay plan de org ni plan por defecto vigente para
                la modalidad (fail-closed).
        """
        effective_mode = mode or org.billing_mode
        now = datetime.utcnow()

        # 1) Plan individual de la organización (Req 8.2). Filtrado por organization_id
        #    (tenant isolation) y por modalidad. Se prefiere el más reciente vigente.
        org_plan = (
            db.query(BillingOrgPlan)
            .filter(
                BillingOrgPlan.organization_id == org.id,
                BillingOrgPlan.mode == effective_mode,
                or_(
                    BillingOrgPlan.effective_from.is_(None),
                    BillingOrgPlan.effective_from <= now,
                ),
            )
            # NULLs (vigente de inmediato) al final del ORDER BY DESC; para desempatar de
            # forma estable priorizamos el mayor effective_from y, si empatan, el más nuevo.
            .order_by(
                BillingOrgPlan.effective_from.desc().nullslast(),
                BillingOrgPlan.created_at.desc(),
            )
            .first()
        )
        if org_plan is not None:
            return ResolvedPlan(
                tiers=list(org_plan.tiers or []),
                currency=org_plan.currency or "USD",
                source="org",
                plan_id=str(org_plan.id),
                mode=effective_mode,
            )

        # 2) Plan por defecto del sistema vigente (Req 8.8: los defaults no sobrescriben
        #    planes de org, por eso solo se llega aquí si la org no tiene plan propio).
        default_plan = (
            db.query(BillingRatePlan)
            .filter(
                BillingRatePlan.mode == effective_mode,
                BillingRatePlan.is_default.is_(True),
                or_(
                    BillingRatePlan.effective_from.is_(None),
                    BillingRatePlan.effective_from <= now,
                ),
            )
            .order_by(
                BillingRatePlan.effective_from.desc().nullslast(),
                BillingRatePlan.created_at.desc(),
            )
            .first()
        )
        if default_plan is not None:
            return ResolvedPlan(
                tiers=list(default_plan.tiers or []),
                currency=default_plan.currency or "USD",
                source="default",
                plan_id=str(default_plan.id),
                mode=effective_mode,
            )

        # Fail-closed: no hay tarifa conocida para la modalidad → no facturar a ciegas.
        raise BillingRateResolutionError(
            f"No hay plan tarifario resoluble para la organización {org.id} en la modalidad "
            f"'{effective_mode}': la organización no tiene plan individual y no existe un plan "
            f"por defecto vigente. Verifique el seed de tarifas (billing_seed)."
        )

    # ── Cálculo de monto mensual (Req 8.3, 8.7) ───────────────────────────────

    def compute_amount_monthly(
        self,
        count: int,
        tiers: List[dict],
    ) -> "tuple[Decimal, List[TierBreakdown]]":
        """
        Calcula el monto mensual incremental por tramos para `count` IPs facturables.

        Para cada tramo `[from, to, rate]`, las IPs contabilizadas en él son:
            `ips_in_tier = max(0, min(count, to) - from + 1)`
        donde `to = None` representa un tramo sin tope superior (`min(count, inf) = count`).
        El aporte del tramo es `ips_in_tier * rate`. El TOTAL se acumula sin redondear y solo
        al final se redondea a 2 decimales con half-up (Req 8.7), aunque las tarifas tengan
        hasta 3 decimales.

        Args:
            count: número de IPs facturables (base `billable` tras el cierre, Req 8.4).
                Un `count <= 0` produce monto 0.00 y desglose vacío.
            tiers: lista de tramos ordenada por `from`, cada uno `{"from", "to", "rate"}`.

        Returns:
            (amount, breakdown):
                - amount: Decimal cuantizado a 2 decimales (half-up).
                - breakdown: lista de `TierBreakdown` (solo tramos con `ips_in_tier > 0`),
                  apta para `tiers_applied` y para derivar el `tier_index` por IP.
        """
        breakdown: List[TierBreakdown] = []

        if count <= 0 or not tiers:
            return Decimal("0").quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP), breakdown

        total = Decimal("0")

        for index, tier in enumerate(tiers):
            lo = int(tier["from"])
            hi = tier.get("to")  # None = tramo sin tope superior
            # La tarifa puede venir como float/int/str en el JSON; se convierte a Decimal vía
            # str() para preservar los decimales tal cual (evita el ruido del float binario).
            rate = Decimal(str(tier["rate"]))

            # Si el conteo aún no alcanza el inicio del tramo, este y los siguientes no aportan
            # (los tramos vienen ordenados por `from`).
            if count < lo:
                break

            # Límite superior efectivo: el tope del tramo o el propio count si es el último
            # tramo (to = None → sin tope).
            upper = count if hi is None else min(count, int(hi))
            ips_in_tier = max(0, upper - lo + 1)
            if ips_in_tier == 0:
                continue

            subtotal = Decimal(ips_in_tier) * rate
            total += subtotal

            breakdown.append(
                TierBreakdown(
                    tier_index=index,
                    tier_from=lo,
                    tier_to=(None if hi is None else int(hi)),
                    rate=rate,
                    ips_in_tier=ips_in_tier,
                    subtotal=subtotal,
                )
            )

        # Redondeo final half-up a 2 decimales (Req 8.7).
        amount = total.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)
        return amount, breakdown


# Instancia compartida sin estado, reutilizable por el motor de cierre (task 16) y los
# endpoints de tarifas (task 17).
billing_service = BillingService()
