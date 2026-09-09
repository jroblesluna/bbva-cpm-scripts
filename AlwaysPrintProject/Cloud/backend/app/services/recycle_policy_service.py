"""
Servicio de Política de Reciclaje del módulo Usage and Billing (recycle-policy-config).

`RecyclePolicyService` resuelve la política de reciclaje aplicable a una organización para
un periodo de cierre `M` (año-mes), replicando el patrón `BillingService.resolve_plan`
(Global_Default + Org_Override), pero con dos diferencias sustanciales de diseño:

1. **Versionado por periodo, no por fecha de ejecución.** La resolución compara
   `effective_key = year*12 + (month-1)` contra el periodo `M` del cierre. Un cierre de un
   mes viejo ejecutado hoy resuelve la política que estaba vigente ESE mes, no la de hoy
   (Req 3.4/10.1). La fecha de ejecución se ignora por completo.
2. **Fallback en cascada.** Org_Override vigente para `M` → Global_Default vigente para `M`
   → política legacy base (`+1/-2/-3` + 24h), que reproduce el comportamiento hardcodeado
   histórico (Req 3.5/6.1).

Todo el comportamiento es **fail-closed**: si dos políticas del mismo scope comparten la
mayor `effective_key` aplicable (empate en el tope), la resolución se rechaza con
`RecyclePolicyResolutionError` sin mutar estado (Req 3.3).

Nota de ordenamiento (tasks): este módulo agrega la resolución de política (task 3.1), la
validación fail-closed (`validate_policy`, task 3.5) y el chequeo de conflicto con cierres
más `parse_frozen_policy` (task 3.8). El persist con auditoría transaccional (task 7.1) se
añade a este mismo módulo en una tarea posterior.
"""

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.billing import BillingClosure, BillingRecyclePolicy
from app.models.organization import Organization

logger = get_logger(__name__)


@dataclass(frozen=True)
class ResolvedRecyclePolicy:
    """
    Política de reciclaje resuelta para un periodo `M`, lista para congelar en el cierre.

    Es un `dataclass` congelado (inmutable) con exactamente los offsets, el umbral efímero y
    los metadatos de origen. Sus atributos `cutoff`, `cut1`, `cut2` y `ephemeral_hours` son
    los que `recycle_decision.decide_recycle` consume por duck typing (deben mantenerse).

    Atributos:
        cutoff: offset de mes del corte superior del periodo facturado (legacy +1).
        cut1: offset de mes del Caso 1 (poco uso / efímero) (legacy -2).
        cut2: offset de mes del Caso 2 (abandono) (legacy -3).
        ephemeral_hours: umbral de uso efímero en horas (legacy 24).
        source: origen de la política: "org" | "default" | "seed_base".
        policy_id: id de la fila `BillingRecyclePolicy` de origen (str) o None si es legacy.
    """

    cutoff: int
    cut1: int
    cut2: int
    ephemeral_hours: int
    source: str
    policy_id: Optional[str] = None

    def freeze_dict(self) -> dict:
        """
        Payload inmutable a congelar en `billing_closures.recycle_policy_applied`.

        Contiene únicamente los cuatro parámetros de la política (sin metadatos de origen),
        que son los que el PDF, el prompt de IA y el recálculo leen para garantizar
        inmutabilidad histórica y determinismo (Req 4.1/4.4).
        """
        return {
            "cutoff": self.cutoff,
            "cut1": self.cut1,
            "cut2": self.cut2,
            "ephemeral_hours": self.ephemeral_hours,
        }


# Política legacy base (Req 3.5 / 6.1): reproduce byte-a-byte el comportamiento hardcodeado
# actual (`+1/-2/-3` + 24h). Se devuelve como fallback cuando no existe ninguna política con
# `effective_key <= M_key` para el periodo del cierre.
LEGACY_POLICY = ResolvedRecyclePolicy(
    cutoff=1,
    cut1=-2,
    cut2=-3,
    ephemeral_hours=24,
    source="seed_base",
)


class RecyclePolicyResolutionError(Exception):
    """
    Fail-closed: no se pudo resolver una política de forma inequívoca.

    Se lanza cuando dos o más filas del mismo scope (Global_Default u Org_Override) comparten
    la mayor `effective_key` aplicable para el periodo `M` (empate en el tope), lo que haría
    ambigua la selección. La resolución no modifica ningún estado antes de lanzar (Req 3.3).
    """


class RecyclePolicyService:
    """
    Servicio de resolución de la política de reciclaje.

    Sin estado: cada método recibe la sesión y la organización sobre las que opera. La
    instancia compartida `recycle_policy_service` se reutiliza desde el motor de cierre
    (task 4.2) y los endpoints de gestión (task 8.2).
    """

    @staticmethod
    def period_key(year: int, month: int) -> int:
        """
        Clave cronológica entera de un periodo año-mes: `year*12 + (month-1)`.

        Es monótona creciente en el tiempo, por lo que comparar dos periodos se reduce a
        comparar sus claves. Se usa tanto para resolver (`effective_key <= M_key`) como para
        mantener consistente la columna persistida `effective_key`.
        """
        return year * 12 + (month - 1)

    def resolve_recycle_policy(
        self,
        db: Session,
        org: Organization,
        year: int,
        month: int,
    ) -> ResolvedRecyclePolicy:
        """
        Resuelve la política de reciclaje aplicable al cierre del periodo `M=(year, month)`.

        Prioridad (Req 2.3/2.4/2.5, 3.2/3.4/3.5/3.6):
            1. Org_Override de `org` con `effective_key <= M_key` (tenant isolation por
               `organization_id`), tomando la de mayor `effective_key` (`source="org"`).
            2. Global_Default (`organization_id IS NULL`) con `effective_key <= M_key`,
               tomando la de mayor `effective_key` (`source="default"`).
            3. `LEGACY_POLICY` si no existe ninguna con `effective_key <= M_key`
               (`source="seed_base"`).

        La resolución IGNORA por completo la fecha de ejecución (Req 3.4/10.1): solo depende
        de `(year, month)`, `org.id` y las filas de política persistidas. Esto la hace robusta
        ante cierres retroactivos.

        Fail-closed (Req 3.3): si dos filas del mismo scope comparten la mayor `effective_key`
        aplicable (empate en el tope), se lanza `RecyclePolicyResolutionError` sin mutar estado.

        Args:
            db: sesión SQLAlchemy activa.
            org: organización objetivo del cierre.
            year: año del periodo `M`.
            month: mes del periodo `M` (1..12).

        Returns:
            La `ResolvedRecyclePolicy` aplicable al periodo `M`.

        Raises:
            RecyclePolicyResolutionError: si hay periodos efectivos duplicados en el tope
                aplicable del scope resuelto (fail-closed).
        """
        m_key = self.period_key(year, month)

        # 1) Org_Override vigente para M (tenant isolation por organization_id). Se traen
        #    ordenadas por effective_key DESC para inspeccionar el tope y detectar empates.
        org_rows = (
            db.query(BillingRecyclePolicy)
            .filter(
                BillingRecyclePolicy.organization_id == org.id,
                BillingRecyclePolicy.effective_key <= m_key,
            )
            .order_by(BillingRecyclePolicy.effective_key.desc())
            .all()
        )
        resolved = self._pick_top_or_error(org_rows, source="org", scope="Org_Override")
        if resolved is not None:
            return resolved

        # 2) Global_Default vigente para M (organization_id IS NULL). Un Org_Override futuro
        #    (effective_key > M_key) no fue seleccionado arriba, por lo que la resolución cae
        #    limpiamente aquí (Req 3.6).
        global_rows = (
            db.query(BillingRecyclePolicy)
            .filter(
                BillingRecyclePolicy.organization_id.is_(None),
                BillingRecyclePolicy.effective_key <= m_key,
            )
            .order_by(BillingRecyclePolicy.effective_key.desc())
            .all()
        )
        resolved = self._pick_top_or_error(
            global_rows, source="default", scope="Global_Default"
        )
        if resolved is not None:
            return resolved

        # 3) Sin política alguna para M -> política legacy base sembrada (Req 3.5).
        return LEGACY_POLICY

    @staticmethod
    def _pick_top_or_error(
        rows: list,
        source: str,
        scope: str,
    ) -> Optional[ResolvedRecyclePolicy]:
        """
        Selecciona la política del tope (mayor `effective_key`) de un scope ya filtrado por
        `effective_key <= M_key` y ordenado DESC, detectando empates en el tope.

        Args:
            rows: filas del scope (ya filtradas y ordenadas por `effective_key DESC`).
            source: valor de `source` a asignar en la política resuelta ("org" | "default").
            scope: nombre humano del scope, para el mensaje de error.

        Returns:
            La `ResolvedRecyclePolicy` del tope, o None si `rows` está vacío (para que el
            caller haga fallback al siguiente scope).

        Raises:
            RecyclePolicyResolutionError: si dos o más filas comparten la mayor
                `effective_key` aplicable (empate en el tope). No muta estado (Req 3.3).
        """
        if not rows:
            return None

        top = rows[0]
        # Empate en el tope aplicable: dos filas del mismo scope con idéntica effective_key
        # máxima => resolución ambigua => fail-closed sin mutar estado (Req 3.3).
        if len(rows) > 1 and rows[1].effective_key == top.effective_key:
            raise RecyclePolicyResolutionError(
                f"Periodos efectivos duplicados en {scope}: dos o más políticas comparten "
                f"effective_key={top.effective_key} "
                f"({top.effective_from_year}-{top.effective_from_month:02d})."
            )

        return ResolvedRecyclePolicy(
            cutoff=top.cutoff_offset,
            cut1=top.cut1_offset,
            cut2=top.cut2_offset,
            ephemeral_hours=top.ephemeral_hours,
            source=source,
            policy_id=str(top.id),
        )

    def assert_no_closed_periods_affected(
        self,
        db: Session,
        org_id: Optional[str],
        effective_key: int,
    ) -> None:
        """
        Verifica (fail-closed) que un cambio de política no afecte periodos ya cerrados (Req 5.3).

        El nuevo `Effective_From_Period` (identificado por `effective_key`) afectaría a todos los
        periodos `M` con `period_key(M) >= effective_key` dentro del scope. Como los cierres son
        inmutables y no se reprocesan (Req 5.1/5.2), si alguno de esos periodos ya tiene un
        `BillingClosure`, aceptar el cambio crearía una incoherencia entre lo congelado y lo
        configurado; por eso se rechaza SIN persistir.

        El `period_key` de un cierre no es una columna: se calcula igual que en `period_key`,
        como `period_year*12 + (period_month - 1)`, directamente en SQL para no traer filas.

        Semántica por scope:
            - Org_Override (`org_id` no None): conflictúan los cierres de ESA organización con
              `period_key >= effective_key` (Req 5.3, caso override).
            - Global_Default (`org_id` None): conflictúan los cierres de organizaciones que NO
              tienen un Org_Override PROPIO vigente en ese periodo, es decir, cierres cuya
              política resuelta sería la global. Una org con override propio con
              `effective_key <= period_key` del cierre resuelve por su override y NO se ve
              afectada por el cambio global (ver `resolve_recycle_policy`).

        Args:
            db: sesión SQLAlchemy activa.
            org_id: id de la organización (str/UUID) para un Org_Override, o `None` para el
                Global_Default.
            effective_key: clave cronológica del periodo efectivo del cambio propuesto.

        Raises:
            ClosedPeriodConflictError: si existe al menos un cierre afectado. No muta estado.
        """
        # period_key del cierre calculado en SQL: period_year*12 + (period_month - 1).
        closure_period_key = (
            BillingClosure.period_year * 12 + (BillingClosure.period_month - 1)
        )

        if org_id is not None:
            # --- Scope Org_Override: cierres de ESA org con period_key >= effective_key. ---
            conflictos = (
                db.query(BillingClosure)
                .filter(
                    BillingClosure.organization_id == org_id,
                    closure_period_key >= effective_key,
                )
                .order_by(
                    BillingClosure.period_year.asc(),
                    BillingClosure.period_month.asc(),
                )
                .all()
            )

            if conflictos:
                periodos = ", ".join(
                    f"{c.period_year}-{c.period_month:02d}" for c in conflictos
                )
                raise ClosedPeriodConflictError(
                    f"El cambio de política (Org_Override, effective_key={effective_key}) "
                    f"afectaría a {len(conflictos)} periodo(s) ya cerrado(s) de la organización "
                    f"{org_id}: {periodos}. Los cierres son inmutables y no se reprocesan, por "
                    f"lo que el cambio se rechaza sin persistir."
                )
            return

        # --- Scope Global_Default: cierres con period_key >= effective_key cuya política ---
        # --- resuelta sería la global (la org NO tiene Org_Override propio vigente en M). ---
        candidatos = (
            db.query(BillingClosure)
            .filter(closure_period_key >= effective_key)
            .order_by(
                BillingClosure.organization_id.asc(),
                BillingClosure.period_year.asc(),
                BillingClosure.period_month.asc(),
            )
            .all()
        )

        conflictos = []
        for cierre in candidatos:
            m_key = self.period_key(cierre.period_year, cierre.period_month)
            # ¿La org del cierre tiene un Org_Override propio vigente para ese periodo M
            # (effective_key <= m_key)? Si lo tiene, ese cierre resuelve por el override y el
            # cambio global NO lo afecta. Solo conflictúan las orgs SIN override propio vigente.
            tiene_override_vigente = (
                db.query(BillingRecyclePolicy.id)
                .filter(
                    BillingRecyclePolicy.organization_id == cierre.organization_id,
                    BillingRecyclePolicy.effective_key <= m_key,
                )
                .first()
                is not None
            )
            if not tiene_override_vigente:
                conflictos.append(cierre)

        if conflictos:
            periodos = ", ".join(
                f"org={c.organization_id}:{c.period_year}-{c.period_month:02d}"
                for c in conflictos
            )
            raise ClosedPeriodConflictError(
                f"El cambio de política global (Global_Default, effective_key={effective_key}) "
                f"afectaría a {len(conflictos)} periodo(s) ya cerrado(s) de organizaciones sin "
                f"Org_Override propio vigente: {periodos}. Los cierres son inmutables y no se "
                f"reprocesan, por lo que el cambio se rechaza sin persistir."
            )

    def upsert_policy(
        self,
        db: Session,
        *,
        organization_id: Optional[str],
        rule_or_offsets,
        ephemeral_hours: int,
        eff_year: int,
        eff_month: int,
        actor_id: Optional[str],
    ) -> "BillingRecyclePolicy":
        """
        Persiste (crea o reemplaza) una política de reciclaje con auditoría transaccional (task 7.1).

        Es la ÚNICA vía de escritura de `billing_recycle_policies`. Encadena, en este orden y
        siempre ANTES de tocar la base de datos, las tres verificaciones fail-closed del módulo,
        y solo si todas pasan realiza el upsert + auditoría en la MISMA transacción:

            1. Parseo del formato (si `rule_or_offsets` es string, vía `parse_recycle_rule`).
            2. `validate_policy(...)` — agrega TODAS las violaciones de regla (Req 7.1-7.5/7.8/7.9).
            3. `assert_no_closed_periods_affected(...)` — rechaza si afectaría cierres ya
               existentes (Req 5.3).

        Semántica de "upsert" (Req 9.1/9.2): una política se identifica de forma única por
        `(scope, effective_key)`, donde `scope` es la organización (`organization_id`) o el
        Global_Default (`organization_id IS NULL`). Si ya existe una fila para ese
        `(scope, effective_key)`, se ACTUALIZA en sitio (misma `id`, preservando `created_at` y
        `created_by_id`); si no existe, se INSERTA una nueva. Así, reconfigurar el mismo periodo
        efectivo no genera un empate que la resolución rechazaría (`RecyclePolicyResolutionError`),
        y `old_values` captura la política previa de ese mismo `(scope, effective_key)` (o `None`
        si es un alta).

        Auditoría transaccional fail-closed (Req 9.1-9.5): el INSERT del `AuditLog` va en la
        MISMA transacción que el upsert. `AuditService.log_action` hace `db.add` + `db.commit`,
        por lo que el flush de la política (pendiente en la sesión) y el log se confirman de forma
        atómica en ese único commit. Si algo falla (validación previa, conflicto, el commit de la
        auditoría o cualquier excepción), se hace `db.rollback()` y NINGÚN cambio de política
        queda persistido: no hay cambio sin rastro de auditoría. Esto DIFIERE a propósito de
        `billing_close_service._audit_closure`, que es fail-safe porque el cierre ya está
        commiteado; aquí es fail-closed (Req 9.5).

        Args:
            db: sesión SQLAlchemy activa.
            organization_id: id de la organización para un Org_Override, o `None` para el
                Global_Default.
            rule_or_offsets: la Recycle_Rule como string `"+1/-2/-3"`, o una tripleta/iterable
                `(cutoff, cut1, cut2)` de enteros ya parseados.
            ephemeral_hours: umbral de uso efímero en horas.
            eff_year: año del Effective_From_Period.
            eff_month: mes del Effective_From_Period (1..12).
            actor_id: id del Superadmin que realiza el cambio (identidad para la auditoría,
                Req 9.4); `None` si el cambio es del sistema.

        Returns:
            La fila `BillingRecyclePolicy` insertada o actualizada, refrescada desde la BD.

        Raises:
            RecyclePolicyValidationException: si el formato o alguna regla de validación falla
                (fail-closed, no persiste — Req 7.9).
            ClosedPeriodConflictError: si el cambio afectaría periodos ya cerrados (Req 5.3).
            Exception: si la auditoría (o el commit) falla, tras hacer `db.rollback()` para no
                dejar el cambio sin rastro (fail-closed, Req 9.5).
        """
        # --- 1. Parseo del formato (si viene como string) ---------------------------------
        # Un string se valida contra RECYCLE_RULE_RE (signo explícito, tres componentes) y se
        # descompone en (cutoff, cut1, cut2); una tripleta ya parseada se usa tal cual.
        if isinstance(rule_or_offsets, str):
            cutoff, cut1, cut2 = parse_recycle_rule(rule_or_offsets)
        else:
            cutoff, cut1, cut2 = (int(v) for v in rule_or_offsets)

        # --- 2. Validación fail-closed (agrega TODAS las violaciones) ---------------------
        # Ocurre ANTES de cualquier escritura, por lo que un rechazo preserva por construcción
        # la política previamente persistida (Req 7.9).
        validate_policy(cutoff, cut1, cut2, ephemeral_hours, eff_year, eff_month)

        # --- 3. effective_key y chequeo de conflicto con cierres existentes ---------------
        effective_key = self.period_key(eff_year, eff_month)
        # Rechaza (fail-closed, Req 5.3) si el nuevo periodo efectivo afectaría cierres ya
        # persistidos (inmutables). No muta estado si lanza.
        self.assert_no_closed_periods_affected(db, organization_id, effective_key)

        # A partir de aquí se toca la sesión. Todo va envuelto en un try/except que hace
        # rollback ante cualquier fallo, garantizando que política + auditoría son atómicas
        # (fail-closed, Req 9.5).
        try:
            # --- 4. Upsert por (scope, effective_key) -------------------------------------
            # Se localiza la fila existente del mismo scope y periodo efectivo. El filtro por
            # organization_id usa `is_(None)` para el Global_Default (en SQL NULL != NULL).
            scope_filter = (
                BillingRecyclePolicy.organization_id.is_(None)
                if organization_id is None
                else BillingRecyclePolicy.organization_id == organization_id
            )
            existing = (
                db.query(BillingRecyclePolicy)
                .filter(
                    scope_filter,
                    BillingRecyclePolicy.effective_key == effective_key,
                )
                .first()
            )

            # `old_values` = política previa de ese mismo (scope, effective_key), o None si es
            # un alta (Req 9.2). Se captura ANTES de mutar la fila.
            if existing is not None:
                old_values = {
                    "rule": format_recycle_rule(
                        existing.cutoff_offset,
                        existing.cut1_offset,
                        existing.cut2_offset,
                    ),
                    "ephemeral_hours": existing.ephemeral_hours,
                    "effective_from": f"{existing.effective_from_year:04d}-"
                    f"{existing.effective_from_month:02d}",
                }
            else:
                old_values = None

            scope = "Global_Default" if organization_id is None else "Org_Override"

            if existing is not None:
                # UPDATE en sitio: preserva id/created_at/created_by_id; `updated_at` lo
                # refresca `onupdate` del modelo.
                existing.cutoff_offset = cutoff
                existing.cut1_offset = cut1
                existing.cut2_offset = cut2
                existing.ephemeral_hours = ephemeral_hours
                existing.effective_from_year = eff_year
                existing.effective_from_month = eff_month
                existing.effective_key = effective_key
                policy = existing
            else:
                policy = BillingRecyclePolicy(
                    organization_id=organization_id,
                    cutoff_offset=cutoff,
                    cut1_offset=cut1,
                    cut2_offset=cut2,
                    ephemeral_hours=ephemeral_hours,
                    effective_from_year=eff_year,
                    effective_from_month=eff_month,
                    effective_key=effective_key,
                    created_by_id=actor_id,
                )
                db.add(policy)

            # Flush para materializar la fila (y su id autogenerado) en la transacción actual,
            # sin commitear todavía: la confirmación la hará el commit atómico de la auditoría.
            db.flush()

            new_values = {
                "scope": scope,
                "rule": format_recycle_rule(cutoff, cut1, cut2),
                "ephemeral_hours": ephemeral_hours,
                "effective_from": f"{eff_year:04d}-{eff_month:02d}",
            }

            # --- 5. Auditoría en la MISMA transacción (fail-closed, Req 9.1-9.5) ----------
            # Import diferido de AuditService para no acoplar imports a nivel de módulo (mismo
            # criterio que billing_close_service). `log_action` hace db.add(audit) + db.commit,
            # confirmando la política pendiente y el log de forma atómica.
            from app.models.audit import ActionType
            from app.services.audit import AuditService

            AuditService().log_action(
                db=db,
                action_type=ActionType.BILLING_RECYCLE_POLICY_CHANGE,
                entity_type="BillingRecyclePolicy",
                entity_id=str(policy.id),
                user_id=str(actor_id) if actor_id else None,  # identidad (Req 9.4)
                # org afectada, o None = Global_Default (Req 9.3).
                organization_id=str(organization_id) if organization_id else None,
                old_values=old_values,  # política previa o None (Req 9.2)
                new_values=new_values,  # política nueva + scope (Req 9.1)
                ip_address=None,
            )
        except Exception as exc:  # noqa: BLE001
            # Fail-closed (Req 9.5): cualquier fallo en el upsert o en la auditoría revierte el
            # cambio de política. No se persiste ningún cambio sin su rastro de auditoría.
            db.rollback()
            logger.error(
                "recycle_policy.upsert_error",
                organization_id=str(organization_id) if organization_id else None,
                effective_key=effective_key,
                error=str(exc),
            )
            raise

        db.refresh(policy)
        logger.info(
            "recycle_policy.upsert_ok",
            policy_id=str(policy.id),
            scope=scope,
            organization_id=str(organization_id) if organization_id else None,
            effective_from=f"{eff_year:04d}-{eff_month:02d}",
            rule=format_recycle_rule(cutoff, cut1, cut2),
            ephemeral_hours=ephemeral_hours,
            actor_id=str(actor_id) if actor_id else None,
        )
        return policy


# Instancia compartida sin estado, reutilizable por el motor de cierre y los endpoints.
recycle_policy_service = RecyclePolicyService()


# =============================================================================
# Validación fail-closed de la Recycle_Policy (task 3.5)
# =============================================================================
#
# Segunda capa de validación (Req 7.6): la API valida primero contra el schema
# Pydantic y ESTE servicio re-valida antes de persistir, independientemente del
# resultado del schema. Toda la validación es fail-closed y ocurre ANTES de
# cualquier escritura, por lo que un rechazo preserva por construcción la política
# previamente persistida (Req 7.9).
#
# La característica distintiva (Req 7.7) es que `validate_policy` NO corta en el
# primer error: agrega TODAS las violaciones (una por regla) y las reporta juntas
# vía `RecyclePolicyValidationException`, para que la API pueda mostrar un mensaje
# explícito por cada regla incumplida (Req 17.5).

import re

# Regex de la Recycle_Rule en formato string `"+1/-2/-3"`: exactamente tres enteros
# con SIGNO EXPLÍCITO (`+`/`-`) separados por `/` (Req 1.3/7.1). Rechaza `"1/-2/-3"`
# (falta signo), `"+1/-2"` (2 componentes) y `"+1/-2/-3/-4"` (4 componentes).
RECYCLE_RULE_RE = re.compile(r"^[+-]\d+/[+-]\d+/[+-]\d+$")

# Rango permitido de cada offset de mes (Req 7.4): -24 <= offset <= +1.
OFFSET_MIN = -24
OFFSET_MAX = 1

# Valor mínimo del cutoff (Req 7.3): cutoff >= +1.
CUTOFF_MIN = 1

# Rango permitido del umbral de uso efímero en horas (Req 7.5): 1 <= horas <= 168.
EPHEMERAL_HOURS_MIN = 1
EPHEMERAL_HOURS_MAX = 168

# Rango permitido del año del Effective_From_Period (Req 3.1/7.8): 2000..2999.
EFF_YEAR_MIN = 2000
EFF_YEAR_MAX = 2999

# Rango permitido del mes del Effective_From_Period (Req 3.1/7.8): 1..12.
EFF_MONTH_MIN = 1
EFF_MONTH_MAX = 12


@dataclass
class PolicyValidationError:
    """
    Una violación de una regla de validación de la política (Req 7.7).

    Cada regla incumplida produce exactamente una instancia. El campo `rule` identifica
    la regla de forma estable (para que la API/UI pueda mapearla), y `message` es el texto
    explícito en español que se muestra al Superadmin.

    Atributos:
        rule: identificador estable de la regla violada. Uno de:
            "format" | "order" | "cutoff_min" | "offset_range" | "ephemeral_range" | "period".
        message: mensaje en español, explícito, describiendo la violación.
    """

    rule: str
    message: str


class RecyclePolicyValidationException(Exception):
    """
    Fail-closed: la política enviada viola una o más reglas de validación (Req 7.1-7.5, 7.8).

    Agrupa TODAS las violaciones detectadas (Req 7.7) en `errors`, una por regla, en lugar de
    abortar en la primera. El servicio la lanza antes de cualquier INSERT/UPDATE, por lo que la
    política previamente persistida queda intacta (Req 7.9).
    """

    def __init__(self, errors: "list[PolicyValidationError]"):
        self.errors = errors
        detalle = "; ".join(f"[{e.rule}] {e.message}" for e in errors)
        super().__init__(
            f"La política de reciclaje es inválida ({len(errors)} regla(s) violada(s)): {detalle}"
        )


def parse_recycle_rule(rule: str) -> "tuple[int, int, int]":
    """
    Parsea la Recycle_Rule string `"+1/-2/-3"` a la tripleta `(cutoff, cut1, cut2)` de enteros.

    Exige signo explícito y exactamente tres componentes (Req 1.3/7.1) mediante `RECYCLE_RULE_RE`.
    Esta función SOLO valida el FORMATO; las reglas semánticas (orden, rangos) las evalúa
    `validate_policy`.

    Args:
        rule: string de la regla, p. ej. `"+1/-2/-3"`.

    Returns:
        La tripleta `(cutoff, cut1, cut2)` como enteros con signo.

    Raises:
        RecyclePolicyValidationException: con un único error `rule="format"` si el string no
            cumple el formato de tres enteros con signo explícito separados por `/`.
    """
    if not isinstance(rule, str) or RECYCLE_RULE_RE.match(rule) is None:
        raise RecyclePolicyValidationException(
            [
                PolicyValidationError(
                    rule="format",
                    message=(
                        f"La Recycle_Rule '{rule}' no tiene el formato válido: se esperan "
                        f"exactamente tres enteros con signo explícito separados por '/', "
                        f"por ejemplo '+1/-2/-3'."
                    ),
                )
            ]
        )
    cutoff_str, cut1_str, cut2_str = rule.split("/")
    return int(cutoff_str), int(cut1_str), int(cut2_str)


def format_recycle_rule(cutoff: int, cut1: int, cut2: int) -> str:
    """
    Formatea la tripleta `(cutoff, cut1, cut2)` a la Recycle_Rule string `"+1/-2/-3"` (Req 1.4).

    Usa signo explícito en los tres offsets (formato `{:+d}`), de modo que
    `format_recycle_rule(*parse_recycle_rule(s)) == s` para todo string válido (round-trip,
    Property 1).

    Args:
        cutoff: offset del corte superior del periodo facturado.
        cut1: offset del Caso 1 (poco uso / efímero).
        cut2: offset del Caso 2 (abandono).

    Returns:
        El string `"+c/+c1/+c2"` con signo explícito en cada componente.
    """
    return f"{cutoff:+d}/{cut1:+d}/{cut2:+d}"


def validate_policy(
    cutoff: int,
    cut1: int,
    cut2: int,
    ephemeral_hours: int,
    eff_year: int,
    eff_month: int,
) -> None:
    """
    Valida una política de reciclaje contra TODAS las reglas fail-closed, agregando violaciones.

    A diferencia de una validación que corta en el primer fallo, esta recorre todas las reglas
    y acumula una `PolicyValidationError` por cada una incumplida (Req 7.7). Si al final hay al
    menos una violación, lanza `RecyclePolicyValidationException` con la lista completa; en caso
    contrario retorna `None`. No realiza ninguna escritura: es puramente una comprobación previa
    a la persistencia (Req 7.9).

    Nota sobre el formato: esta función recibe los offsets YA parseados a enteros. La regla de
    formato (Req 7.1) se valida en `parse_recycle_rule`, que se invoca aguas arriba (schema /
    endpoint) antes de llegar aquí con enteros; por eso `validate_policy` no re-evalúa el formato.

    Reglas evaluadas:
        - order (Req 7.2): debe cumplirse `cutoff > cut1 >= cut2`.
        - cutoff_min (Req 7.3): `cutoff >= +1`.
        - offset_range (Req 7.4): cada offset en `[-24, +1]`.
        - ephemeral_range (Req 7.5): `ephemeral_hours` en `[1, 168]`.
        - period (Req 7.8/3.1): mes en `[1, 12]` y año en `[2000, 2999]`.

    Args:
        cutoff: offset del corte superior (legacy +1).
        cut1: offset del Caso 1 (legacy -2).
        cut2: offset del Caso 2 (legacy -3).
        ephemeral_hours: umbral de uso efímero en horas (legacy 24).
        eff_year: año del Effective_From_Period.
        eff_month: mes del Effective_From_Period (1..12).

    Raises:
        RecyclePolicyValidationException: si se viola al menos una regla; contiene un error por
            cada regla violada (Req 7.7).
    """
    errors: list = []

    # Orden (Req 7.2): cutoff estrictamente mayor que cut1, y cut1 mayor o igual que cut2.
    if not (cutoff > cut1 >= cut2):
        errors.append(
            PolicyValidationError(
                rule="order",
                message=(
                    f"Los offsets no cumplen el orden requerido 'cutoff > cut1 >= cut2': "
                    f"cutoff={cutoff}, cut1={cut1}, cut2={cut2}."
                ),
            )
        )

    # Cutoff mínimo (Req 7.3): el corte superior no puede ser menor que +1.
    if cutoff < CUTOFF_MIN:
        errors.append(
            PolicyValidationError(
                rule="cutoff_min",
                message=(
                    f"El cutoff debe ser mayor o igual que +{CUTOFF_MIN}; se recibió {cutoff}."
                ),
            )
        )

    # Rango de offsets (Req 7.4): cada uno de los tres offsets dentro de [-24, +1]. Se reporta
    # un solo error de esta regla listando todos los offsets fuera de rango.
    fuera_de_rango = [
        (nombre, valor)
        for nombre, valor in (("cutoff", cutoff), ("cut1", cut1), ("cut2", cut2))
        if not (OFFSET_MIN <= valor <= OFFSET_MAX)
    ]
    if fuera_de_rango:
        detalle_offsets = ", ".join(f"{n}={v}" for n, v in fuera_de_rango)
        errors.append(
            PolicyValidationError(
                rule="offset_range",
                message=(
                    f"Cada offset debe estar en el rango [{OFFSET_MIN}, +{OFFSET_MAX}]; "
                    f"fuera de rango: {detalle_offsets}."
                ),
            )
        )

    # Umbral de uso efímero (Req 7.5): horas dentro de [1, 168].
    if not (EPHEMERAL_HOURS_MIN <= ephemeral_hours <= EPHEMERAL_HOURS_MAX):
        errors.append(
            PolicyValidationError(
                rule="ephemeral_range",
                message=(
                    f"El Ephemeral_Use_Threshold debe estar en el rango "
                    f"[{EPHEMERAL_HOURS_MIN}, {EPHEMERAL_HOURS_MAX}] horas; se recibió "
                    f"{ephemeral_hours}."
                ),
            )
        )

    # Periodo efectivo (Req 7.8/3.1): mes en [1, 12] y año en [2000, 2999]. Un solo error de
    # esta regla, describiendo el/los componente(s) inválido(s).
    periodo_invalido = []
    if not (EFF_MONTH_MIN <= eff_month <= EFF_MONTH_MAX):
        periodo_invalido.append(
            f"mes={eff_month} (rango [{EFF_MONTH_MIN}, {EFF_MONTH_MAX}])"
        )
    if not (EFF_YEAR_MIN <= eff_year <= EFF_YEAR_MAX):
        periodo_invalido.append(
            f"año={eff_year} (rango [{EFF_YEAR_MIN}, {EFF_YEAR_MAX}])"
        )
    if periodo_invalido:
        errors.append(
            PolicyValidationError(
                rule="period",
                message=(
                    "El Effective_From_Period no es un año-mes válido: "
                    + "; ".join(periodo_invalido)
                    + "."
                ),
            )
        )

    if errors:
        raise RecyclePolicyValidationException(errors)


# =============================================================================
# Conflicto con cierres existentes y parseo del freeze (task 3.8)
# =============================================================================
#
# Estos dos comportamientos comparten la naturaleza fail-closed del módulo:
#
#   - `assert_no_closed_periods_affected` (Req 5.3): antes de persistir un cambio
#     de política, verifica que el nuevo `Effective_From_Period` no afecte a ningún
#     periodo `M` que YA tenga un `BillingClosure`. Como los cierres son inmutables y
#     no se reprocesan (Req 5.1/5.2), aceptar un cambio que "debería" haber aplicado
#     a un mes cerrado crearía una incoherencia entre lo congelado y lo configurado;
#     por eso se rechaza en origen SIN persistir.
#
#   - `parse_frozen_policy` (Req 11.4/12.3): valida el freeze inmutable persistido en
#     `billing_closures.recycle_policy_applied` y lo reconstruye como
#     `ResolvedRecyclePolicy(source="frozen")`. Un freeze ausente, vacío (`{}`), con
#     claves faltantes o con tipos inválidos se considera corrupto y lanza
#     `FrozenPolicyCorruptError`. Es la función compartida que el PDF (aborta) y el
#     prompt de IA (degrada solo el análisis) usan para leer SIEMPRE lo congelado,
#     nunca la política vigente.


class ClosedPeriodConflictError(Exception):
    """
    Fail-closed: un cambio de política afectaría a uno o más periodos YA cerrados (Req 5.3).

    Se lanza ANTES de cualquier escritura, por lo que la política previamente persistida queda
    intacta por construcción (Req 7.9). El mensaje identifica el conflicto (scope y periodos ya
    cerrados que quedarían afectados) para que la API/UI pueda mostrarlo al Superadmin.
    """


class FrozenPolicyCorruptError(Exception):
    """
    Fail-closed: el freeze de política de un cierre falta o está corrupto (Req 11.4/12.3).

    `billing_closures.recycle_policy_applied` debe contener las cuatro claves
    (`cutoff`, `cut1`, `cut2`, `ephemeral_hours`) con valores enteros. Un freeze `None`,
    vacío (`{}`), con claves faltantes o con tipos no enteros se considera corrupto: el PDF
    aborta (no genera un PDF sin política) y el prompt de IA falla solo el AI_Analysis.
    """


# Claves obligatorias del freeze persistido en `billing_closures.recycle_policy_applied`.
_FROZEN_POLICY_KEYS = ("cutoff", "cut1", "cut2", "ephemeral_hours")


def parse_frozen_policy(raw: dict) -> ResolvedRecyclePolicy:
    """
    Valida el freeze de política de un cierre y lo reconstruye como `ResolvedRecyclePolicy`.

    Lee el payload inmutable guardado en `billing_closures.recycle_policy_applied` (el mismo
    que produce `ResolvedRecyclePolicy.freeze_dict()`) y lo devuelve como una política resuelta
    con `source="frozen"`. NO consulta la política vigente: el PDF, el prompt de IA y cualquier
    recálculo deben leer SIEMPRE lo congelado para garantizar inmutabilidad histórica.

    Fail-closed (Req 11.4/12.3): un freeze ausente, vacío (`{}`), con alguna de las cuatro
    claves faltante o con algún valor que no sea `int` se considera corrupto y lanza
    `FrozenPolicyCorruptError`. Nota: `bool` es subtipo de `int` en Python, por lo que se
    rechaza explícitamente para no aceptar `True`/`False` como offsets válidos.

    Args:
        raw: el dict persistido en `recycle_policy_applied` (o `None` si la columna venía vacía).

    Returns:
        `ResolvedRecyclePolicy(source="frozen", policy_id=None)` con los cuatro parámetros
        congelados.

    Raises:
        FrozenPolicyCorruptError: si el freeze falta, está vacío, le faltan claves o tiene
            tipos inválidos.
    """
    # Freeze ausente o vacío ({} = corrupto por diseño, es solo red de seguridad del backfill).
    if not raw or not isinstance(raw, dict):
        raise FrozenPolicyCorruptError(
            "El freeze de política del cierre está ausente o vacío "
            f"(recycle_policy_applied={raw!r}); se esperaban las claves "
            f"{', '.join(_FROZEN_POLICY_KEYS)}."
        )

    # Claves faltantes.
    faltantes = [k for k in _FROZEN_POLICY_KEYS if k not in raw]
    if faltantes:
        raise FrozenPolicyCorruptError(
            "El freeze de política del cierre está incompleto; faltan las claves: "
            f"{', '.join(faltantes)} (recibido: {raw!r})."
        )

    # Tipos: cada valor debe ser int (y no bool, que es subtipo de int en Python).
    invalidos = [
        f"{k}={raw[k]!r}"
        for k in _FROZEN_POLICY_KEYS
        if isinstance(raw[k], bool) or not isinstance(raw[k], int)
    ]
    if invalidos:
        raise FrozenPolicyCorruptError(
            "El freeze de política del cierre tiene tipos inválidos (se esperaban enteros): "
            f"{', '.join(invalidos)}."
        )

    return ResolvedRecyclePolicy(
        cutoff=raw["cutoff"],
        cut1=raw["cut1"],
        cut2=raw["cut2"],
        ephemeral_hours=raw["ephemeral_hours"],
        source="frozen",
        policy_id=None,
    )
