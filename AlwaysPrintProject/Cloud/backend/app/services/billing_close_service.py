"""
Motor de cierre mensual del módulo Usage and Billing (task 13).

`BillingCloseService.close_month` ejecuta el cierre de un mes lógico M (año Y) para una
organización: recalcula el `billing_status` de las workstations en alcance, produce el
sustento inmutable (cabecera + detalle por IP) y lo persiste en una transacción única.

Diseño (ver `design.md`, sección "Motor de cierre mensual (`BillingCloseService`)"):

1. Idempotencia (Req 7.6): un mes ya cerrado no puede volver a cerrarse. Se apoya en el
   `UniqueConstraint uq_closure_org_period` del modelo y en una verificación previa que
   falla con un mensaje claro (fail-closed).
2. Secuencialidad (Req 7.4): no se puede cerrar un mes M si existe un mes anterior sin
   cerrar dentro del rango activo de la organización (desde el mes del `created_at` más
   antiguo de una IP hasta M). El mes inmediatamente anterior a M debe tener cierre, salvo
   que M sea el primer mes cerrable de la organización.
3. Cortes (task 12): `compute_cuts(org.timezone, year, month)` → `cutoff` (M+1),
   `cut1` (M−2, Caso 1), `cut2` (M−3, Caso 2).
4. Alcance: `organization_id = org.id AND created_at < cutoff AND billing_status != 'archived'`
   para el RECÁLCULO. Las `archived` no se tocan (Req 5.3), pero SÍ se incluyen en el
   snapshot si `created_at < cutoff` (Req 6.3: registrar todas las creadas antes del corte).
5. Paso 1 (Req 5.3.1): `new → billable`.
6. Paso 2 (Req 5.4/5.5): reglas de reciclaje sobre `billable` usando `last_seen` CRUDO.
7. Snapshot (Req 6.2/5.7): `last_seen_capped = min(last_seen, cutoff)` en cada ítem.
8. Estado vivo (Req 6.5): la columna `billing_status` viva refleja el estado del cierre de
   mayor `(year, month)`. Un cierre retroactivo (para un mes anterior al último ejecutado)
   NO revierte la columna viva; solo registra el estado histórico en los ítems del snapshot.

Principios del repo (impact-analysis):
- Fail-closed: ante idempotencia/secuencialidad violada o transición inválida, se lanza y
  se aborta el cierre; no se produce un sustento parcial.
- Inmutabilidad del sustento: el snapshot no se recalcula ni se sobrescribe.
- Tenant isolation: todas las queries filtran por `organization_id`.
- Transacción única: cabecera + ítems + (posible) actualización de la columna viva se
  confirman o revierten juntos.

Cálculo de monto (task 16): tras el recálculo, la base de facturación mensual es el número
de workstations cuyo estado RESULTANTE es `billable` (Req 8.4). Se resuelve el plan tarifario
de la organización (`BillingService.resolve_plan`) y se calcula `amount` + desglose por tramo
(`BillingService.compute_amount_monthly`). El desglose se persiste en `closure.tiers_applied`
y se usa para asignar a cada IP facturable su tramo (`tier_index`) y su aporte de monto
(`amount`) — ver `_assign_item_amounts`.

Modalidad anual (Req 9.2 / 8.6): durante una suscripción anual vigente, el invoice mensual es
`0.00` (la liquidación anual se hace en las tasks 19-21). Para esta task, si
`org.billing_mode == 'annual'` se fija `amount = 0.00`, `tiers_applied = []` y cada ítem con
`amount = 0` / `tier_index = None`. Se deja el seam claro para la liquidación anual.
"""

from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.audit import ActionType
from app.models.billing import BillingClosure, BillingClosureItem
from app.models.organization import Organization
from app.models.workstation import Workstation
from app.services.billing_service import TierBreakdown, billing_service
from app.services.billing_state_machine import (
    ARCHIVED,
    BILLABLE,
    NEW,
    RECYCLED,
    billing_state_machine,
)
from app.services.billing_time import BillingCuts, compute_cuts

logger = get_logger(__name__)

# 24 horas en segundos: umbral de "poco uso" del Caso 1 (Req 5.4).
_CASE1_MAX_USE_SECONDS = 24 * 60 * 60

# Monto cero (modalidad anual vigente o ausencia de base facturable).
_ZERO_AMOUNT = Decimal("0.00")

# Aporte por IP en 4 decimales (coincide con Numeric(12, 4) del ítem). No se redondea a 2
# decimales por ítem: la suma exacta de los aportes es la base del total de cabecera, que sí
# se redondea half-up a 2 decimales en compute_amount_monthly (ver nota de reconciliación).
_ITEM_QUANTUM = Decimal("0.0001")

# Modalidad anual: el invoice mensual es 0.00 durante la vigencia (Req 9.2 / 8.6).
_ANNUAL_MODE = "annual"


class BillingCloseError(Exception):
    """Error de negocio del cierre mensual (idempotencia, secuencialidad, etc.)."""


class BillingAlreadyClosedError(BillingCloseError):
    """El mes (org, año, mes) ya tiene un cierre (idempotencia, Req 7.6)."""


class BillingSequenceError(BillingCloseError):
    """Existe un mes anterior sin cerrar: los cierres deben ser secuenciales (Req 7.4)."""


class BillingCloseService:
    """
    Servicio de cierre mensual por organización.

    Es un componente sin estado: cada llamada a `close_month` opera sobre la sesión y la
    organización recibidas. La transacción la controla este servicio (un `flush` para
    validar constraints y un `commit` final), pero no abre la sesión (la recibe del caller:
    endpoint retroactivo en task 27 o scheduler en task 26).
    """

    def close_month(
        self,
        db: Session,
        org: Organization,
        year: int,
        month: int,
        actor_id: Optional[str] = None,
        is_retroactive: bool = False,
    ) -> BillingClosure:
        """
        Cierra el mes M=`month` del año Y=`year` para la organización `org`.

        Args:
            db: sesión SQLAlchemy activa (la transacción la confirma este método).
            org: organización a cerrar (se usa su `timezone` y `billing_mode`).
            year: año del mes a cerrar.
            month: mes a cerrar (1..12).
            actor_id: id del usuario que ejecuta el cierre (auditoría/`created_by_id`),
                o None si lo dispara el scheduler automático.
            is_retroactive: True si es un cierre retroactivo (histórico). Se persiste en la
                cabecera y condiciona la actualización de la columna viva (Req 6.5).

        Returns:
            La `BillingClosure` (cabecera) persistida, con sus ítems asociados.

        Raises:
            BillingAlreadyClosedError: si ya existe cierre para (org, year, month) (Req 7.6).
            BillingSequenceError: si hay un mes anterior sin cerrar (Req 7.4).
            ValueError: si `month` no está en 1..12 (propagado desde `compute_cuts`).
        """
        # ── 1. Idempotencia (Req 7.6) ────────────────────────────────────────
        # Verificación previa explícita (fail-closed) además del UniqueConstraint del modelo.
        existing = (
            db.query(BillingClosure)
            .filter(
                BillingClosure.organization_id == org.id,
                BillingClosure.period_year == year,
                BillingClosure.period_month == month,
            )
            .first()
        )
        if existing is not None:
            raise BillingAlreadyClosedError(
                f"La organización {org.id} ya tiene un cierre para {year}-{month:02d}; "
                f"un cierre es inmutable y no puede recalcularse (idempotencia)."
            )

        # ── 2. Secuencialidad (Req 7.4) ──────────────────────────────────────
        # No se puede cerrar M si el mes inmediatamente anterior (dentro del rango activo de
        # la organización) no está cerrado. El rango activo empieza en el mes del created_at
        # más antiguo de una IP de la org.
        self._assert_sequential(db, org, year, month)

        # ── 3. Cortes en la timezone de la organización (task 12) ────────────
        cuts: BillingCuts = compute_cuts(org.timezone, year, month)

        # ── 4. Alcance del recálculo (Req 5.2, 5.3, 5.8) ─────────────────────
        # created_at < cutoff, tenant isolation por organization_id. Se excluyen las
        # `archived` del recálculo (no se tocan), pero se recuperan aparte para el snapshot.
        recalc_scope: List[Workstation] = (
            db.query(Workstation)
            .filter(
                Workstation.organization_id == org.id,
                Workstation.created_at < cuts.cutoff,
                Workstation.billing_status != ARCHIVED,
            )
            .all()
        )

        # Archived dentro del corte: NO se recalculan pero SÍ entran al snapshot (Req 6.3).
        archived_in_scope: List[Workstation] = (
            db.query(Workstation)
            .filter(
                Workstation.organization_id == org.id,
                Workstation.created_at < cuts.cutoff,
                Workstation.billing_status == ARCHIVED,
            )
            .all()
        )

        # ── 5. Paso 1: new → billable (Req 5.3.1) ────────────────────────────
        # Se calcula el estado RESULTANTE de cada ws en un dict {ws: estado}, para no acoplar
        # el snapshot histórico con la actualización de la columna viva (Req 6.5). El estado
        # de partida es el actual de la ws.
        resulting_state = {ws: ws.billing_status for ws in recalc_scope}

        for ws in recalc_scope:
            if resulting_state[ws] == NEW:
                # Validar la transición por la máquina de estados (contexto automático).
                billing_state_machine.assert_can_transition(NEW, BILLABLE, automatic=True)
                resulting_state[ws] = BILLABLE

        # ── 6. Paso 2: reglas de reciclaje sobre billable, last_seen CRUDO ──
        # (Req 5.4 Caso 1, Req 5.5 Caso 2, Req 5.6 crudo).
        for ws in recalc_scope:
            if resulting_state[ws] != BILLABLE:
                continue
            if self._should_recycle(ws, cuts):
                billing_state_machine.assert_can_transition(
                    BILLABLE, RECYCLED, automatic=True
                )
                resulting_state[ws] = RECYCLED

        # ── 7. Determinar si este cierre define el estado vivo (Req 6.5) ─────
        # El estado vivo lo determina siempre el cierre de mayor (year, month). Si existe un
        # cierre posterior a (year, month), este cierre es retroactivo respecto al estado
        # vivo y NO debe revertir la columna; solo registra histórico en el snapshot.
        is_most_recent = self._is_most_recent_period(db, org, year, month)

        # ── 8. Construcción del snapshot (cabecera + ítems) ──────────────────
        # Conteos por estado RESULTANTE (base de facturación mensual = billable, Req 8.4).
        total_billable = sum(1 for s in resulting_state.values() if s == BILLABLE)
        total_recycled = sum(1 for s in resulting_state.values() if s == RECYCLED)
        total_archived = len(archived_in_scope)

        # ── 8.a Cálculo de monto mensual (Req 8.3, 8.4) ──────────────────────
        # Base de facturación = workstations cuyo estado RESULTANTE es billable (total_billable).
        # Se resuelve el plan de la organización para su modalidad y se calcula el monto por
        # tramos incrementales. `breakdown` contiene el aporte de cada tramo (ips_in_tier, rate)
        # y se usa tanto para `tiers_applied` como para asignar el tramo/aporte de cada IP.
        #
        # Modalidad anual (Req 9.2 / 8.6): el invoice mensual es 0.00 durante la vigencia; la
        # liquidación anual (crédito/cargo) se calcula en el aniversario (tasks 19-21). Para
        # anual dejamos amount=0.00 y tiers_applied=[] (informativo vacío); cada ítem quedará
        # con amount=0 / tier_index=None (ver más abajo). Seam explícito para la liquidación.
        if org.billing_mode == _ANNUAL_MODE:
            amount = _ZERO_AMOUNT
            tiers_applied: list = []
            breakdown: List[TierBreakdown] = []
        else:
            resolved_plan = billing_service.resolve_plan(db, org, org.billing_mode)
            amount, breakdown = billing_service.compute_amount_monthly(
                total_billable, resolved_plan.tiers
            )
            tiers_applied = [b.to_dict() for b in breakdown]

        closure = BillingClosure(
            organization_id=org.id,
            period_year=year,
            period_month=month,
            cutoff_at=cuts.cutoff,
            mode=org.billing_mode,
            timezone=org.timezone,
            total_billable=total_billable,
            total_recycled=total_recycled,
            total_archived=total_archived,
            amount=amount,
            tiers_applied=tiers_applied,
            is_retroactive=is_retroactive,
            created_by_id=actor_id,
        )
        db.add(closure)
        # Flush para materializar closure.id y disparar el UniqueConstraint de idempotencia
        # (fail-closed ante una carrera con otro cierre del mismo periodo).
        db.flush()

        # ── 8.b Asignación de tramo/aporte por IP facturable (Req 8.3) ───────
        # Solo las ws billable aportan monto. Se ordenan de forma determinista (created_at_ws,
        # luego ip_private) y se les asigna una posición ordinal 1..total_billable; cada IP
        # recibe el tramo que contiene su posición y como aporte la tarifa marginal de ese
        # tramo. La suma de aportes = total sin redondear de compute_amount_monthly (la
        # cabecera redondea half-up a 2 decimales; ver nota de reconciliación en el helper).
        # En modalidad anual `breakdown` está vacío → item_allocations queda vacío y todas las
        # IPs facturables reciben amount=0 / tier_index=None.
        billable_ws = [ws for ws in recalc_scope if resulting_state[ws] == BILLABLE]
        item_allocations = self._assign_item_amounts(billable_ws, breakdown)

        # Ítems: todas las ws creadas antes del corte (recalc + archived), con last_seen
        # capado a cutoff (Req 5.7, 6.2). El billing_status del ítem es el estado histórico
        # de ESE cierre (resultante para recalc; ARCHIVED para las archivadas). El aporte
        # (tier_index, amount) solo aplica a las billable; el resto va en 0 / None.
        for ws in recalc_scope:
            tier_index, item_amount = item_allocations.get(
                ws.id, (None, Decimal("0"))
            )
            db.add(
                self._build_item(
                    closure.id,
                    ws,
                    resulting_state[ws],
                    cuts.cutoff,
                    tier_index=tier_index,
                    amount=item_amount,
                )
            )
        for ws in archived_in_scope:
            # Las archivadas no se facturan (no están en billable): amount=0, tier_index=None.
            db.add(self._build_item(closure.id, ws, ARCHIVED, cuts.cutoff))

        # ── 9. Actualización de la columna viva (Req 6.5) ────────────────────
        # Solo si este cierre es el más reciente de la organización. Un cierre retroactivo
        # anterior al último ejecutado registra histórico en el snapshot pero NO revierte la
        # columna viva.
        if is_most_recent:
            for ws, nuevo_estado in resulting_state.items():
                if ws.billing_status != nuevo_estado:
                    ws.billing_status = nuevo_estado

        # ── 10. Transacción única ────────────────────────────────────────────
        db.commit()
        db.refresh(closure)

        logger.info(
            "billing.cierre_completado",
            organization_id=str(org.id),
            period=f"{year}-{month:02d}",
            is_retroactive=is_retroactive,
            aplica_estado_vivo=is_most_recent,
            total_billable=total_billable,
            total_recycled=total_recycled,
            total_archived=total_archived,
        )

        # ── 11. Auditoría de la ejecución del cierre (Req 11.4) ──────────────
        # Se distingue el origen (source): 'auto' cuando lo dispara el scheduler (actor_id
        # None), 'retroactive' cuando es un cierre retroactivo con actor, y 'manual' en
        # cualquier otro cierre con actor. La escritura es fail-safe: el cierre ya está
        # commiteado; si la auditoría fallara no debe revertir ni ocultar el cierre.
        self._audit_closure(
            db=db,
            org=org,
            closure=closure,
            actor_id=actor_id,
            is_retroactive=is_retroactive,
            total_billable=total_billable,
            total_recycled=total_recycled,
            total_archived=total_archived,
        )

        return closure

    def _audit_closure(
        self,
        db: Session,
        org: Organization,
        closure: BillingClosure,
        actor_id: Optional[str],
        is_retroactive: bool,
        total_billable: int,
        total_recycled: int,
        total_archived: int,
    ) -> None:
        """
        Registra en auditoría la ejecución de un cierre mensual (Req 11.4).

        Determina el `source` de forma explícita:
        - 'auto'        → sin actor (scheduler de medianoche, task 26).
        - 'retroactive' → con actor y `is_retroactive=True` (endpoint superadmin, task 27).
        - 'manual'      → con actor y no retroactivo (cualquier otro disparo con actor).

        Tenant isolation: `organization_id = org.id`. Import diferido de `AuditService` para
        no introducir acoplamientos de import a nivel de módulo en el motor de cierre.
        """
        if actor_id is None:
            source = "auto"
        elif is_retroactive:
            source = "retroactive"
        else:
            source = "manual"

        try:
            from app.services.audit import AuditService

            AuditService().log_action(
                db=db,
                action_type=ActionType.BILLING_CLOSURE,
                entity_type="BillingClosure",
                entity_id=str(closure.id),
                user_id=str(actor_id) if actor_id else None,
                organization_id=str(org.id),
                new_values={
                    "source": source,
                    "is_retroactive": is_retroactive,
                    "period_year": closure.period_year,
                    "period_month": closure.period_month,
                    "mode": closure.mode,
                    "amount": str(closure.amount),
                    "total_billable": total_billable,
                    "total_recycled": total_recycled,
                    "total_archived": total_archived,
                },
                ip_address=None,
            )
        except Exception as exc:  # noqa: BLE001 — la auditoría no debe tumbar el cierre
            # El cierre YA está commiteado; si el INSERT del log falla, hacemos rollback para
            # dejar la sesión utilizable (el caller refresca/serializa el `closure`) sin
            # revertir el cierre ya persistido.
            db.rollback()
            logger.error(
                "billing.cierre_auditoria_error",
                organization_id=str(org.id),
                closure_id=str(closure.id),
                error=str(exc),
            )

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _should_recycle(self, ws: Workstation, cuts: BillingCuts) -> bool:
        """
        Evalúa si una workstation `billable` debe reciclarse, con `last_seen` CRUDO (Req 5.6).

        - Caso 2 (abandono, Req 5.5): `last_seen < cut2` (independiente del tiempo de uso).
        - Caso 1 (poco uso, Req 5.4): `last_seen < cut1` AND `(last_seen − created_at) < 24h`.

        El Caso 2 se evalúa primero por ser el más amplio (`cut2 < cut1`): cualquier
        `last_seen < cut2` recicla sin importar el uso.
        """
        last_seen = ws.last_seen
        # Caso 2 — abandono.
        if last_seen < cuts.cut2:
            return True
        # Caso 1 — poco uso.
        if last_seen < cuts.cut1:
            uso = (last_seen - ws.created_at).total_seconds()
            if uso < _CASE1_MAX_USE_SECONDS:
                return True
        return False

    def _build_item(
        self,
        closure_id,
        ws: Workstation,
        billing_status: str,
        cutoff: datetime,
        tier_index: Optional[int] = None,
        amount: Decimal = Decimal("0"),
    ) -> BillingClosureItem:
        """
        Construye un `BillingClosureItem` con `last_seen` capado a `cutoff` (Req 5.7, 6.2).

        El capping evita registrar en el sustento actividad posterior al mes cerrado, algo
        especialmente relevante en cierres retroactivos (Req 7.5). No modifica la columna
        `last_seen` en BD (solo el valor del snapshot).

        `tier_index` y `amount` son el aporte de esta IP a la facturación mensual (Req 8.3):
        para las IPs facturables se pasan calculados; para recycled/archived se dejan en los
        valores por defecto (None / 0) porque no se facturan.
        """
        last_seen_capped = min(ws.last_seen, cutoff)
        return BillingClosureItem(
            closure_id=closure_id,
            workstation_id=ws.id,
            ip_private=ws.ip_private,
            created_at_ws=ws.created_at,
            last_seen_capped=last_seen_capped,
            billing_status=billing_status,
            tier_index=tier_index,
            amount=amount,
        )

    def _assign_item_amounts(
        self,
        billable_ws: List[Workstation],
        breakdown: List[TierBreakdown],
    ) -> Dict[object, "tuple[Optional[int], Decimal]"]:
        """
        Asigna a cada workstation facturable su tramo (`tier_index`) y su aporte de monto
        (`amount`), devolviendo un dict `{workstation_id: (tier_index, amount)}` (Req 8.3).

        Enfoque (documentado y determinista):
        - Se ordenan las IPs facturables por `(created_at, ip_private)` para obtener un orden
          estable e independiente del orden de la query.
        - Se les asigna una posición ordinal 1..N (N = len(billable_ws)).
        - El `breakdown` (calculado por `compute_amount_monthly`) describe, en orden, cuántas
          IPs caen en cada tramo (`ips_in_tier`) y su tarifa (`rate`). Se recorren las IPs en
          orden llenando cada tramo con `ips_in_tier` posiciones consecutivas: cada IP recibe
          el `tier_index` de ese tramo y como aporte su `rate` (la contribución marginal de la
          IP en el modelo incremental por tramos).

        Reconciliación con la cabecera: la suma de los aportes por IP es exactamente el total
        SIN redondear (Σ ips_in_tier × rate). La cabecera (`compute_amount_monthly`) redondea
        ese total half-up a 2 decimales, de modo que la suma de los aportes por IP puede
        diferir del `amount` de cabecera hasta en <0.01 por el redondeo. Los aportes por IP se
        guardan con 4 decimales (Numeric(12,4)) para preservar esa precisión; el monto
        facturable oficial es el de la cabecera (2 decimales).

        Si `breakdown` está vacío (p.ej. modalidad anual, count<=0 o sin tramos) se devuelve un
        dict vacío → todas las IPs facturables quedan con (None, 0).
        """
        if not breakdown:
            return {}

        ordered = sorted(billable_ws, key=lambda w: (w.created_at, w.ip_private))

        allocations: Dict[object, "tuple[Optional[int], Decimal]"] = {}
        pos = 0  # índice en la lista ordenada de IPs facturables
        for tier in breakdown:
            rate = tier.rate.quantize(_ITEM_QUANTUM)
            # Llenar `ips_in_tier` posiciones consecutivas con este tramo.
            for _ in range(tier.ips_in_tier):
                if pos >= len(ordered):
                    break
                ws = ordered[pos]
                allocations[ws.id] = (tier.tier_index, rate)
                pos += 1

        return allocations

    def current_period(self, org: Organization) -> tuple:
        """
        Devuelve el mes EN CURSO `(year, month)` en la timezone de la organización.

        El mes en curso NO es cerrable todavía (su corte `00:00 del día 1 de M+1` aún no
        ocurre). Se usa como límite superior EXCLUSIVO al buscar el mes pendiente más antiguo
        en los cierres retroactivos (Req 7.2): solo se cierran meses ya finalizados.
        """
        now_local = datetime.now(ZoneInfo(org.timezone))
        return (now_local.year, now_local.month)

    def next_pending_period(
        self, db: Session, org: Organization
    ) -> Optional[tuple]:
        """
        Devuelve el mes pendiente MÁS ANTIGUO por cerrar de la organización como
        `(year, month)`, o None si no hay meses pendientes (Req 7.2, 7.3).

        Un mes pendiente es un mes ya finalizado (anterior al mes en curso en la tz de la org)
        que aún NO tiene un `BillingClosure`. Se busca desde el primer mes cerrable de la
        organización (`_org_first_period`, definido por el `created_at` más antiguo de una IP)
        hacia adelante, hasta llegar al mes en curso (exclusivo).

        Devuelve el PRIMER mes de ese rango sin cierre, garantizando que la generación
        retroactiva avanza uno por uno y desde el más antiguo (Req 7.3). Como se empieza por el
        más antiguo, el mes devuelto nunca tendrá un hueco anterior sin cerrar, por lo que
        respeta la secuencialidad (Req 7.4) por construcción.

        Returns:
            `(year, month)` del mes pendiente más antiguo, o None si:
            - la org no tiene IPs (no hay primer periodo cerrable), o
            - todos los meses hasta el mes en curso ya están cerrados.
        """
        first_period = self._org_first_period(db, org)
        if first_period is None:
            return None

        first_index = first_period[0] * 12 + (first_period[1] - 1)
        current_year, current_month = self.current_period(org)
        # Límite superior EXCLUSIVO: el mes en curso no es cerrable todavía.
        current_index = current_year * 12 + (current_month - 1)

        if first_index >= current_index:
            # El primer mes cerrable es el mes en curso (o posterior): nada finalizado aún.
            return None

        # Cierres existentes de la org, indexados por índice absoluto de mes.
        existing_indices = {
            row.period_year * 12 + (row.period_month - 1)
            for row in db.query(
                BillingClosure.period_year, BillingClosure.period_month
            )
            .filter(BillingClosure.organization_id == org.id)
            .all()
        }

        # Buscar el primer mes sin cierre desde el más antiguo hasta el mes anterior al actual.
        for idx in range(first_index, current_index):
            if idx not in existing_indices:
                year, month_0 = divmod(idx, 12)
                return (year, month_0 + 1)

        return None

    def _org_first_period(
        self, db: Session, org: Organization
    ) -> Optional[tuple]:
        """
        Devuelve el primer mes cerrable de la organización como `(year, month)`, definido por
        el `created_at` más antiguo de una IP de la org (Req 7.3), o None si no hay IPs.
        """
        oldest = (
            db.query(Workstation.created_at)
            .filter(Workstation.organization_id == org.id)
            .order_by(Workstation.created_at.asc())
            .first()
        )
        if oldest is None or oldest[0] is None:
            return None
        first_created: datetime = oldest[0]
        return (first_created.year, first_created.month)

    def _assert_sequential(
        self, db: Session, org: Organization, year: int, month: int
    ) -> None:
        """
        Verifica la secuencialidad (Req 7.4): el mes inmediatamente anterior a (year, month),
        dentro del rango activo de la organización, debe estar cerrado.

        Regla:
        - Si la org no tiene IPs todavía, no hay rango activo → no se aplica restricción de
          secuencialidad (el cierre operará sobre un alcance vacío).
        - Si (year, month) es anterior o igual al primer mes cerrable, se considera el inicio
          del rango: no requiere un mes previo cerrado.
        - En otro caso, el mes previo (M−1) debe tener un cierre; si no, se rechaza
          (fail-closed) para evitar saltos.
        """
        first_period = self._org_first_period(db, org)
        if first_period is None:
            # Sin IPs: no hay histórico que respetar; se permite (alcance vacío).
            return

        target_index = year * 12 + (month - 1)
        first_index = first_period[0] * 12 + (first_period[1] - 1)

        # El primer mes del rango (o anterior) es el inicio: no exige mes previo.
        if target_index <= first_index:
            return

        # Mes inmediatamente anterior (M−1).
        prev_index = target_index - 1
        prev_year, prev_month_0 = divmod(prev_index, 12)
        prev_month = prev_month_0 + 1

        prev_closure = (
            db.query(BillingClosure)
            .filter(
                BillingClosure.organization_id == org.id,
                BillingClosure.period_year == prev_year,
                BillingClosure.period_month == prev_month,
            )
            .first()
        )
        if prev_closure is None:
            raise BillingSequenceError(
                f"No se puede cerrar {year}-{month:02d} para la organización {org.id}: "
                f"el mes anterior {prev_year}-{prev_month:02d} no está cerrado. Los cierres "
                f"deben ser secuenciales, desde el más antiguo, sin saltos (Req 7.4)."
            )

    def _is_most_recent_period(
        self, db: Session, org: Organization, year: int, month: int
    ) -> bool:
        """
        Indica si (year, month) es el periodo de MAYOR `(year, month)` para la organización,
        considerando los cierres ya existentes (Req 6.5).

        El estado vivo lo determina siempre el cierre de mayor periodo. Como la idempotencia
        ya garantiza que (year, month) aún no está cerrado, basta con verificar que NO exista
        ningún cierre con periodo estrictamente mayor.
        """
        later = (
            db.query(BillingClosure)
            .filter(
                BillingClosure.organization_id == org.id,
                and_(
                    # (period_year > year) OR (period_year == year AND period_month > month)
                    (BillingClosure.period_year * 12 + (BillingClosure.period_month - 1))
                    > (year * 12 + (month - 1))
                ),
            )
            .first()
        )
        return later is None


# Instancia compartida sin estado, reutilizable por el scheduler (task 26) y el endpoint
# retroactivo (task 27).
billing_close_service = BillingCloseService()
