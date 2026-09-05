"""
Servicio de suscripción anual del módulo Usage and Billing (task 19).

`BillingAnnualService.create_subscription` registra una suscripción anual para una
organización, congelando la tarifa/tramo/tope declarados al inicio de la vigencia.
`compute_settlement` calcula la liquidación (crédito/cargo) en el aniversario de forma
informativa (no persiste) y `confirm_settlement` la aplica manualmente (status='settled',
Req 9.3-9.6).

Diseño (ver `design.md`, sección "Suscripción y liquidación anual (informativa)" y el modelo
`BillingAnnualSubscription`):

Reglas (Req 9.1, 9.2, 8.6):
- `start_date` = `created_at` del PRIMER registro (workstation) de la organización. Sin un
  primer registro no hay inicio posible → se rechaza (no se puede iniciar una suscripción sin
  una primera IP registrada). Ejemplo Req 9.1: primer registro 5-may-2026 ⇒ inicio 5-may-2026.
- `end_date` = un día antes del aniversario. Aniversario = `start_date + 1 año`;
  `end_date = aniversario − 1 día`. Ejemplo Req 9.1: fin 4-may-2027. Se usa
  `dateutil.relativedelta` para manejar años bisiestos correctamente (29-feb → 28-feb).
- La tarifa (`tier_rate`), el tramo (`tier_from`/`tier_to`) y el tope (`tier_cap`) se CONGELAN
  al momento de la creación (Req 8.6: la tarifa anual se congela durante la vigencia).
- Se persiste el `declared_volume` (input manual del superadministrador) y `status='active'`.

Principios del repo (impact-analysis):
- Tenant isolation: toda query filtra por `organization_id`.
- Fail-closed en dinero: se usa `Decimal` para la tarifa; no se crea una segunda suscripción
  activa solapada para la misma organización (guard razonable).
- Congelación (Req 8.6): los valores tarifarios se guardan en la propia suscripción y no se
  releen del plan durante la vigencia.

Relación con el cierre mensual (Req 9.2): mientras una organización está en modalidad anual
(`org.billing_mode == 'annual'`), el motor de cierre mensual (`BillingCloseService`) genera el
invoice mensual en US$ 0.00 (ver `billing_close_service.py`, sección 8.a). Esta suscripción
NO cambia por sí sola el `billing_mode` de la organización; para que el invoice mensual sea
0.00 la organización debe estar en modalidad anual. Este servicio verifica esa coherencia (ver
`create_subscription`) para evitar una suscripción anual "huérfana" que igual facture mensual.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.billing import BillingAnnualSubscription
from app.models.organization import Organization
from app.models.workstation import Workstation
from app.services.billing_service import BillingRateResolutionError, billing_service

logger = get_logger(__name__)

# Estado de una suscripción vigente (coincide con el server_default del modelo).
_STATUS_ACTIVE = "active"

# Estado de una suscripción ya liquidada (aplicada manualmente por el superadmin, Req 9.5).
_STATUS_SETTLED = "settled"

# Modalidad anual: durante su vigencia el invoice mensual es 0.00 (Req 9.2 / 8.6).
_ANNUAL_MODE = "annual"

# Estado 'billable': IPs activas que se cuentan como uso real en la liquidación (Req 9.3).
_STATUS_BILLABLE = "billable"

# Cuantización del dinero: 2 decimales, half-up (consistente con el cálculo mensual, Req 8.7).
_MONEY_QUANTUM = Decimal("0.01")


class BillingAnnualError(Exception):
    """Error de negocio de la suscripción anual (sin primer registro, solape, etc.)."""


class BillingNoFirstRegistrationError(BillingAnnualError):
    """La organización no tiene ninguna IP registrada: no hay fecha de inicio posible (Req 9.1)."""


class BillingSubscriptionOverlapError(BillingAnnualError):
    """Ya existe una suscripción anual activa para la organización (guard de solape)."""


class BillingSubscriptionAlreadySettledError(BillingAnnualError):
    """La suscripción ya fue liquidada (status='settled'): no se puede confirmar dos veces."""


class BillingAnnualService:
    """
    Servicio de creación de suscripciones anuales por organización.

    Sin estado: cada llamada opera sobre la sesión y la organización recibidas. La instancia
    compartida `billing_annual_service` se reutiliza desde el endpoint (`billing_annual.py`).
    """

    def create_subscription(
        self,
        db: Session,
        org: Organization,
        declared_volume: int,
        tier_from: int,
        tier_rate: Decimal,
        tier_to: Optional[int] = None,
        tier_cap: Optional[int] = None,
        actor_id: Optional[str] = None,
    ) -> BillingAnnualSubscription:
        """
        Crea una suscripción anual para la organización `org`, congelando tarifa/tramo/tope.

        Args:
            db: sesión SQLAlchemy activa (la transacción la confirma este método).
            org: organización objetivo (tenant scope por `org.id`).
            declared_volume: volumen declarado por el superadministrador (input manual).
            tier_from: límite inferior del tramo contratado (congelado).
            tier_rate: tarifa unitaria del tramo (Decimal, congelada).
            tier_to: límite superior del tramo o None si es el último tramo (congelado).
            tier_cap: tope contabilizable de la liquidación (ej. 10000) o None (congelado).
            actor_id: id del superadministrador que crea la suscripción (auditoría), opcional.

        Returns:
            La `BillingAnnualSubscription` persistida.

        Raises:
            BillingNoFirstRegistrationError: la org no tiene IPs registradas (Req 9.1).
            BillingSubscriptionOverlapError: ya existe una suscripción activa para la org.
            ValueError: `declared_volume` o `tier_from` inválidos.
        """
        # ── Validación de entrada mínima (fail-closed) ───────────────────────
        if declared_volume < 0:
            raise ValueError("El volumen declarado no puede ser negativo")
        if tier_from < 1:
            raise ValueError("El 'tier_from' del tramo contratado debe ser >= 1")
        if tier_to is not None and tier_to < tier_from:
            raise ValueError("El 'tier_to' no puede ser menor que 'tier_from'")
        if tier_cap is not None and tier_cap < 0:
            raise ValueError("El 'tier_cap' no puede ser negativo")

        # ── Guard de solape (una suscripción activa por org) ─────────────────
        # Evita crear una segunda suscripción activa solapada para la misma organización.
        existing_active = (
            db.query(BillingAnnualSubscription)
            .filter(
                BillingAnnualSubscription.organization_id == org.id,
                BillingAnnualSubscription.status == _STATUS_ACTIVE,
            )
            .first()
        )
        if existing_active is not None:
            raise BillingSubscriptionOverlapError(
                f"La organización {org.id} ya tiene una suscripción anual activa "
                f"({existing_active.id}); confírmela/liquídela antes de crear otra."
            )

        # ── start_date = created_at del PRIMER registro (Req 9.1) ────────────
        # Tenant isolation: se busca el created_at más antiguo de una IP de la org.
        first_created = (
            db.query(Workstation.created_at)
            .filter(Workstation.organization_id == org.id)
            .order_by(Workstation.created_at.asc())
            .first()
        )
        if first_created is None or first_created[0] is None:
            raise BillingNoFirstRegistrationError(
                f"La organización {org.id} no tiene ninguna IP registrada: no se puede "
                f"iniciar una suscripción anual sin una primera fecha de registro (Req 9.1)."
            )
        start_date = first_created[0]

        # ── end_date = aniversario − 1 día (Req 9.1) ─────────────────────────
        # Aniversario = start_date + 1 año (relativedelta maneja bisiestos: 29-feb → 28-feb).
        # end_date = aniversario − 1 día. Ejemplo: 5-may-2026 ⇒ aniversario 5-may-2027 ⇒
        # fin 4-may-2027.
        anniversary = start_date + relativedelta(years=1)
        end_date = anniversary - relativedelta(days=1)

        # ── Congelación de tarifa/tramo/tope (Req 8.6) ───────────────────────
        # Se guarda `tier_rate` como Decimal (dinero) y el tramo/tope declarados. Estos valores
        # NO se releen del plan durante la vigencia: quedan congelados en la propia suscripción.
        subscription = BillingAnnualSubscription(
            organization_id=org.id,
            start_date=start_date,
            end_date=end_date,
            declared_volume=declared_volume,
            tier_rate=Decimal(str(tier_rate)),
            tier_from=tier_from,
            tier_to=tier_to,
            tier_cap=tier_cap,
            status=_STATUS_ACTIVE,
        )
        db.add(subscription)

        # ── Coherencia con el invoice mensual 0.00 (Req 9.2) ─────────────────
        # El invoice mensual es 0.00 mientras `org.billing_mode == 'annual'` (lo enforcea el
        # motor de cierre). Al crear la suscripción, alineamos la modalidad de la organización
        # a 'annual' para que la relación sea consistente (una suscripción activa ⇒ invoice
        # mensual 0.00). Si ya estaba en anual, es idempotente.
        if org.billing_mode != _ANNUAL_MODE:
            logger.info(
                "billing.anual_modalidad_alineada",
                organization_id=str(org.id),
                modalidad_anterior=org.billing_mode,
            )
            org.billing_mode = _ANNUAL_MODE

        db.commit()
        db.refresh(subscription)

        logger.info(
            "billing.suscripcion_anual_creada",
            organization_id=str(org.id),
            subscription_id=str(subscription.id),
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            declared_volume=declared_volume,
            tier_from=tier_from,
            tier_to=tier_to,
            tier_cap=tier_cap,
            actor_id=str(actor_id) if actor_id else None,
        )

        return subscription

    # ── Liquidación en el aniversario (informativa, Req 9.3-9.6) ──────────────

    def _count_billable(self, db: Session, organization_id) -> int:
        """
        Cuenta las IPs activas ('billable') de la organización al momento de la liquidación.

        Base de la liquidación (Req 9.3): IPs en estado 'billable' de la org. Tenant isolation
        por `organization_id`.
        """
        return (
            db.query(Workstation)
            .filter(
                Workstation.organization_id == organization_id,
                Workstation.billing_status == _STATUS_BILLABLE,
            )
            .count()
        )

    def _resolve_free_growth_to(
        self,
        db: Session,
        org: Organization,
        tier_from: int,
    ) -> Optional[int]:
        """
        Resuelve el margen de "crecimiento libre" (`free_growth_to`) del tramo contratado.

        Busca el plan anual aplicable a la organización (plan de org o default vigente) y, entre
        sus tramos, el que coincide con el `tier_from` contratado; devuelve su `free_growth_to`
        si está definido. Es informativo (Req 9.6): si no hay plan anual resoluble o el tramo no
        declara `free_growth_to`, devuelve None (no se marca crecimiento libre).
        """
        try:
            plan = billing_service.resolve_plan(db, org, mode=_ANNUAL_MODE)
        except BillingRateResolutionError:
            # Sin plan anual resoluble no hay margen que reportar (solo informativo).
            return None

        for tier in plan.tiers or []:
            try:
                if int(tier["from"]) == int(tier_from):
                    fg = tier.get("free_growth_to")
                    return int(fg) if fg is not None else None
            except (KeyError, TypeError, ValueError):
                # Tramo malformado: se ignora para el cálculo informativo.
                continue
        return None

    def compute_settlement(
        self,
        db: Session,
        subscription: BillingAnnualSubscription,
    ) -> dict:
        """
        Calcula la liquidación anual de forma INFORMATIVA (no persiste nada).

        Reglas (Req 9.3-9.6, ver `design.md`):
            - base = IPs 'billable' de la org al aniversario (`billable_count`).
            - `real = min(billable_count, tier_cap)` si hay tope; si no, `billable_count`
              (ej. Req 9.3: 10,500 con tope 10,000 ⇒ real 10,000).
            - `diff = declared_volume − real` (Req 9.4).
            - `credit = max(diff, 0) × tier_rate` (real < declarado ⇒ crédito).
            - `charge = max(−diff, 0) × tier_rate` (real > declarado ⇒ cargo).
            - Dinero con `Decimal`, redondeo half-up a 2 decimales (consistente con el mensual).
            - Indicador de "crecimiento libre" (Req 9.6, informativo, sin reclasificar):
              `within_free_growth` = real dentro del `free_growth_to` del tramo contratado;
              `requires_reclassification` = real excede ese margen. Nunca reclasifica.

        Args:
            db: sesión SQLAlchemy activa (solo lectura; este método no confirma nada).
            subscription: suscripción anual sobre la que se calcula la liquidación.

        Returns:
            dict con la liquidación informativa (dinero como `Decimal`):
            {declared, real, billable_count, tier_cap, diff, credit, charge, tier_rate,
             free_growth: {within_free_growth, free_growth_to, requires_reclassification}}.
        """
        # ── Base: IPs 'billable' de la org (Req 9.3), tenant isolation por org ──
        billable_count = self._count_billable(db, subscription.organization_id)

        # ── real = min(billable_count, tier_cap) si hay tope (Req 9.3) ──────────
        if subscription.tier_cap is not None:
            real = min(billable_count, int(subscription.tier_cap))
        else:
            real = billable_count

        # ── diff = declarado − real (Req 9.4) ───────────────────────────────────
        declared = int(subscription.declared_volume)
        diff = declared - real

        # ── crédito / cargo (Req 9.4) ────────────────────────────────────────────
        # tier_rate se maneja como Decimal (dinero); el redondeo final es half-up a 2 dec.
        tier_rate = Decimal(str(subscription.tier_rate))
        credit = (Decimal(max(diff, 0)) * tier_rate).quantize(
            _MONEY_QUANTUM, rounding=ROUND_HALF_UP
        )
        charge = (Decimal(max(-diff, 0)) * tier_rate).quantize(
            _MONEY_QUANTUM, rounding=ROUND_HALF_UP
        )

        # ── Indicador de "crecimiento libre" (Req 9.6, informativo) ─────────────
        # Se resuelve el `free_growth_to` del tramo contratado desde el plan anual. Si real se
        # mantiene dentro de ese margen → within_free_growth; si lo excede → requiere
        # reclasificación (NO se reclasifica automáticamente en esta spec — solo se informa).
        organization = (
            db.query(Organization)
            .filter(Organization.id == subscription.organization_id)
            .first()
        )
        free_growth_to = (
            self._resolve_free_growth_to(db, organization, subscription.tier_from)
            if organization is not None
            else None
        )
        if free_growth_to is None:
            within_free_growth = False
            requires_reclassification = False
        else:
            within_free_growth = real <= free_growth_to
            requires_reclassification = real > free_growth_to

        return {
            "declared": declared,
            "real": real,
            "billable_count": billable_count,
            "tier_cap": (int(subscription.tier_cap) if subscription.tier_cap is not None else None),
            "diff": diff,
            "credit": credit,
            "charge": charge,
            "tier_rate": tier_rate,
            "free_growth": {
                "within_free_growth": within_free_growth,
                "free_growth_to": free_growth_to,
                "requires_reclassification": requires_reclassification,
            },
        }

    def confirm_settlement(
        self,
        db: Session,
        subscription: BillingAnnualSubscription,
        actor_id: Optional[str] = None,
    ) -> BillingAnnualSubscription:
        """
        Aplica la liquidación anual manualmente (Req 9.5): calcula, persiste y pasa a 'settled'.

        Recalcula la liquidación con `compute_settlement`, la guarda en `subscription.settlement`
        (JSON con el dinero como string para no perder precisión decimal) y cambia el estado a
        'settled'. La aplicación requiere confirmación manual del superadministrador (no es
        automática): por eso este método existe aparte del GET informativo.

        Args:
            db: sesión SQLAlchemy activa (la transacción la confirma este método).
            subscription: suscripción anual a liquidar (debe estar 'active').
            actor_id: id del superadministrador que confirma (auditoría), opcional.

        Returns:
            La `BillingAnnualSubscription` actualizada (status='settled', settlement poblado).

        Raises:
            BillingSubscriptionAlreadySettledError: la suscripción ya fue liquidada (guard).
        """
        # ── Guard: no confirmar dos veces (fail-closed) ─────────────────────────
        if subscription.status == _STATUS_SETTLED:
            raise BillingSubscriptionAlreadySettledError(
                f"La suscripción anual {subscription.id} ya fue liquidada (status='settled'); "
                f"no se puede confirmar nuevamente."
            )

        # ── Cálculo de la liquidación (misma lógica que el GET informativo) ─────
        settlement = self.compute_settlement(db, subscription)

        # ── Persistencia: dinero como string en el JSON (precisión decimal) ─────
        subscription.settlement = {
            "declared": settlement["declared"],
            "real": settlement["real"],
            "billable_count": settlement["billable_count"],
            "tier_cap": settlement["tier_cap"],
            "diff": settlement["diff"],
            "credit": str(settlement["credit"]),
            "charge": str(settlement["charge"]),
            "tier_rate": str(settlement["tier_rate"]),
            "free_growth": settlement["free_growth"],
        }
        subscription.status = _STATUS_SETTLED

        db.commit()
        db.refresh(subscription)

        logger.info(
            "billing.liquidacion_anual_confirmada",
            organization_id=str(subscription.organization_id),
            subscription_id=str(subscription.id),
            declared=settlement["declared"],
            real=settlement["real"],
            diff=settlement["diff"],
            credit=str(settlement["credit"]),
            charge=str(settlement["charge"]),
            actor_id=str(actor_id) if actor_id else None,
        )

        return subscription


# Instancia compartida sin estado, reutilizable por el endpoint de suscripción (billing_annual.py).
billing_annual_service = BillingAnnualService()
