"""
Servicio de generación del Reporte de Cierre Mensual (PDF), sustento formal de la factura.

Es un servicio sin estado (recibe `db`, `closure`, `org` en cada método), al estilo de
`BillingService` y `DebuggingAnalysisService`. Opera en modo SOLO LECTURA sobre el snapshot
inmutable del cierre (`BillingClosure` + `BillingClosureItem`): nunca modifica el motor de
cierre ni la resolución de tarifas.

Hasta ahora se implementan: la serie histórica de cierres (`build_history_series`), el render
server-side de gráficos (`render_tiers_chart` / `render_history_chart`), el análisis IA
cacheado con fail-safe (`build_ai_prompt` / `resolve_ai_analysis`), la validación de
reconciliación de montos (`validate_reconciliation`), la composición del PDF de las 9 secciones
(`compose_pdf`) y el storage/caché S3 del artefacto (`build_s3_key` / `s3_exists` /
`upload_to_s3` / `generate_presigned_url`). La orquestación `generate_or_get` se agrega en la
tarea siguiente.

Nota sobre matplotlib (headless):
    El backend corre en contenedores sin servidor gráfico, por lo que se fija el backend
    no interactivo "Agg" a nivel de módulo ANTES de importar `pyplot`. Hacerlo aquí garantiza
    que cualquier import posterior de `matplotlib.pyplot` (en las funciones de render) no
    intente abrir un display.
"""

import matplotlib

# Fijar backend headless "Agg" ANTES de cualquier import de pyplot (sin display en contenedor).
matplotlib.use("Agg")

import io
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import List, Optional

import boto3
import matplotlib.pyplot as plt  # import DESPUÉS de matplotlib.use("Agg")
from botocore.client import Config
from botocore.exceptions import ClientError
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models.billing import BillingClosure, BillingClosureItem, BillingClosureReport
from app.models.organization import Organization
from app.schemas.billing_closures import HistoryPoint

logger = get_logger(__name__)

# DPI fijo para todos los PNG de gráficos: reproducible y suficiente para incrustar en PDF
# (fpdf2 `pdf.image()`) sin inflar el tamaño del artefacto.
_CHART_DPI = 150

# Reintentos/backoff para la invocación del LLM del análisis IA (mismo patrón que
# debugging_analysis._invoke_llm): 3 intentos con espera fija entre reintentos.
_LLM_MAX_RETRIES = 3
_LLM_RETRY_DELAY_SECONDS = 5

# Prefijo determinista de la key S3 del artefacto PDF por cierre (ver build_s3_key).
_S3_KEY_PREFIX = "billing-reports"

# Expiración (segundos) de la presigned URL de descarga del reporte. 3600s = 1 hora,
# alineado con `debugging.py` y con `ClosureReportUrlResponse.expires_in_seconds`.
_PRESIGNED_URL_EXPIRES_SECONDS = 3600

# === MÉTRICAS DE CONTINGENCIA (resumen para el reporte de cierre) ===
# Umbrales para clasificar "entradas masivas" de contingencia dentro del ciclo.
_MASS_WINDOW_MINUTES = 10   # ventana de tiempo para agrupar activaciones cercanas
_MASS_MIN_PER_VLAN = 5      # >= N WS distintas de una VLAN en la ventana → masiva por agencia
_MASS_ORG_PCT = 0.30        # >= 30% de las WS de la org en la ventana → masiva por organización

# Cantidad máxima de eventos masivos por VLAN detallados en el resumen (top N para no inflar
# el prompt/PDF). El conteo total (`mass_vlan_events`) no está limitado por este tope.
_MASS_VLAN_DETAIL_TOP = 10


class ContingencySummary:
    """
    Resumen de métricas de contingencia del ciclo de cierre (fail-safe, informativo).

    Es un objeto de resultado simple (sin estado ni efectos secundarios) que agrega las
    métricas de contingencia reconstruidas desde la auditoría (`audit_logs`) y el estado
    vigente de contingencia forzada (org/VLAN). Nunca afecta la factura: si algo falla al
    calcularlo, se devuelve un resumen en ceros con `data_available=False`.

    Atributos:
        activations_in_cycle: número de activaciones (contingency_active=true) en el ciclo.
            SOLO cuenta el esquema A (toggle automático por-workstation). Las forzadas Org/VLAN
            (esquema B) NUNCA suman aquí.
        distinct_ws_activated: WS distintas que activaron al menos una vez en el ciclo (esquema A).
        active_at_cutoff: WS en contingencia al cutoff (reconstruido point-in-time desde auditoría,
            SOLO esquema A con workstation_id NOT NULL). Las forzadas Org/VLAN vigentes al cierre NO
            se reflejan aquí: se ven en `forced_org` / `forced_vlan_count` (estado actual) y en las
            métricas de eventos forzados del ciclo (`forced_org_activations`, `forced_vlan_activations`,
            `forced_affected_ws_total`).
        mass_vlan_events: número de entradas masivas a nivel VLAN/agencia (algoritmo de ventana
            por-equipo, esquema A únicamente).
        mass_vlan_detail: lista de dicts (top eventos) con
            {"vlan_id": str|None, "count": int, "window_start": iso, "window_end": iso}.
        mass_org_events: entradas masivas a nivel organización (esquema A únicamente).
        forced_vlan_count: VLANs con forced_contingency=True vigentes (contingencia forzada manual,
            estado actual).
        forced_org: org.forced_contingency vigente (estado actual).
        forced_org_activations: eventos ON del ciclo con forced_contingency=true y scope=organization
            (esquema B, contingencia forzada manual a nivel organización).
        forced_vlan_activations: eventos ON del ciclo con forced_contingency=true y scope=vlan
            (esquema B, contingencia forzada manual a nivel agencia/VLAN).
        forced_deactivations: eventos OFF del ciclo con forced_contingency=false (cualquier scope,
            esquema B).
        forced_affected_ws_total: suma de affected_workstations de los ON forzados del ciclo (esquema B).
        deactivations_in_cycle: SALIDAS totales del ciclo = desactivaciones automáticas por-equipo
            (esquema A, contingency_active=false) + desactivaciones forzadas (esquema B, forced OFF).
        data_available: True si se pudo consultar la auditoría (para el fail-safe).
    """

    def __init__(
        self,
        *,
        activations_in_cycle: int = 0,
        distinct_ws_activated: int = 0,
        active_at_cutoff: int = 0,
        mass_vlan_events: int = 0,
        mass_vlan_detail: Optional[list] = None,
        mass_org_events: int = 0,
        forced_vlan_count: int = 0,
        forced_org: bool = False,
        forced_org_activations: int = 0,
        forced_vlan_activations: int = 0,
        forced_deactivations: int = 0,
        forced_affected_ws_total: int = 0,
        deactivations_in_cycle: int = 0,
        data_available: bool = True,
    ) -> None:
        self.activations_in_cycle = activations_in_cycle
        self.distinct_ws_activated = distinct_ws_activated
        self.active_at_cutoff = active_at_cutoff
        self.mass_vlan_events = mass_vlan_events
        self.mass_vlan_detail = mass_vlan_detail if mass_vlan_detail is not None else []
        self.mass_org_events = mass_org_events
        self.forced_vlan_count = forced_vlan_count
        self.forced_org = forced_org
        self.forced_org_activations = forced_org_activations
        self.forced_vlan_activations = forced_vlan_activations
        self.forced_deactivations = forced_deactivations
        self.forced_affected_ws_total = forced_affected_ws_total
        self.deactivations_in_cycle = deactivations_in_cycle
        self.data_available = data_available

    def to_dict(self) -> dict:
        """Serializa el resumen a un dict plano (para construir schemas de respuesta)."""
        return {
            "activations_in_cycle": self.activations_in_cycle,
            "distinct_ws_activated": self.distinct_ws_activated,
            "active_at_cutoff": self.active_at_cutoff,
            "mass_vlan_events": self.mass_vlan_events,
            "mass_vlan_detail": self.mass_vlan_detail,
            "mass_org_events": self.mass_org_events,
            "forced_vlan_count": self.forced_vlan_count,
            "forced_org": self.forced_org,
            "forced_org_activations": self.forced_org_activations,
            "forced_vlan_activations": self.forced_vlan_activations,
            "forced_deactivations": self.forced_deactivations,
            "forced_affected_ws_total": self.forced_affected_ws_total,
            "deactivations_in_cycle": self.deactivations_in_cycle,
            "data_available": self.data_available,
        }


class ClosureReportError(Exception):
    """Error durante la generación del Reporte de Cierre Mensual."""

    pass


class ClosureReportService:
    """
    Orquesta la generación (y caché) del Reporte de Cierre Mensual.

    Sin estado: cada método recibe la sesión de BD, el cierre y/o la organización sobre los
    que opera. Expone la serie histórica, la persistencia del artefacto derivado y el análisis
    IA cacheado; el resto del pipeline (PDF, S3) se añade en tareas posteriores.
    """

    def build_history_series(
        self,
        db: Session,
        org: Organization,
        up_to: Optional[BillingClosure] = None,
    ) -> List[HistoryPoint]:
        """
        Deriva la serie histórica de cierres de la organización con su número de ciclo.

        Consulta los `BillingClosure` de la organización (tenant isolation por `organization_id`)
        ordenados cronológicamente por `(period_year, period_month)` de más antiguo a más reciente,
        y asigna `cycle` 1-based: el cierre más antiguo es el ciclo 1 (primer mes de servicio) y la
        numeración crece consecutivamente.

        Corte point-in-time (Req: reporte histórico): si se pasa `up_to` (el cierre objetivo del
        reporte), la serie SOLO incluye cierres cuyo periodo sea MENOR O IGUAL a
        `(up_to.period_year, up_to.period_month)`. Así un reporte histórico (p. ej. mayo) nunca
        refleja información de periodos posteriores (junio, julio, ...) que no se conocían al
        momento de ese cierre. Si `up_to` es `None`, no se aplica corte (serie completa).

        Devuelve un `HistoryPoint` por cierre con el ciclo, el periodo, los totales por estado
        (facturables/reciclados/archivados) y el monto del cierre, listos para graficar la
        evolución histórica.
        """
        query = db.query(BillingClosure).filter(
            BillingClosure.organization_id == org.id  # tenant isolation
        )

        # Corte point-in-time: no incluir periodos posteriores al cierre objetivo.
        # (year < ty) OR (year == ty AND month <= tm) — comparación cronológica portable.
        if up_to is not None:
            ty = up_to.period_year
            tm = up_to.period_month
            query = query.filter(
                sa.or_(
                    BillingClosure.period_year < ty,
                    sa.and_(
                        BillingClosure.period_year == ty,
                        BillingClosure.period_month <= tm,
                    ),
                )
            )

        closures = query.order_by(
            BillingClosure.period_year.asc(),
            BillingClosure.period_month.asc(),
        ).all()

        series: List[HistoryPoint] = []
        for index, closure in enumerate(closures):
            series.append(
                HistoryPoint(
                    cycle=index + 1,  # 1-based: el cierre más antiguo es el ciclo 1
                    period_year=closure.period_year,
                    period_month=closure.period_month,
                    total_billable=closure.total_billable,
                    total_recycled=closure.total_recycled,
                    total_archived=closure.total_archived,
                    amount=closure.amount,
                )
            )

        return series

    # === Métricas de contingencia del ciclo (resumen fail-safe) ===

    def build_contingency_summary(
        self,
        db: Session,
        org: Organization,
        closure: BillingClosure,
    ) -> ContingencySummary:
        """
        Construye el resumen de métricas de contingencia del ciclo del cierre (fail-safe).

        El ciclo es el intervalo `[cycle_start, cutoff)`, donde
        `cycle_start = datetime(period_year, period_month, 1)` (naive UTC, consistente con
        `AuditLog.created_at`, que se guarda como `datetime.utcnow()`) y `cutoff = closure.cutoff_at`.

        Métricas calculadas:
        DOS ESQUEMAS de `new_values` en los `CONTINGENCY_TOGGLE` (ambos matchean el mismo
        `ActionType.CONTINGENCY_TOGGLE`, NO se toca ese filtro):
          A) Automático por-workstation: `{"contingency_active": bool}`, `workstation_id` poblado.
          B) Forzada manual Org/VLAN: `{"forced_contingency": bool, "scope": "organization"|"vlan",
             "affected_workstations": int, ...}`, `workstation_id` NULL.
        Las métricas del esquema A y del esquema B se computan por SEPARADO y NO se mezclan: una
        fila del esquema B nunca cuenta como activación/desactivación por-equipo (y viceversa).

        - `activations_in_cycle` / `distinct_ws_activated` (SOLO esquema A): sobre los `AuditLog` de
          tipo `CONTINGENCY_TOGGLE` de la org dentro del ciclo, se cuentan las activaciones
          (`new_values["contingency_active"] is True`) y las WS distintas que activaron.
        - Métricas forzadas del ciclo (SOLO esquema B): `forced_org_activations` /
          `forced_vlan_activations` cuentan los ON (`forced_contingency=true`) por scope;
          `forced_deactivations` cuenta los OFF (`forced_contingency=false`, cualquier scope);
          `forced_affected_ws_total` suma los `affected_workstations` de los ON forzados.
        - `deactivations_in_cycle`: SALIDAS totales del ciclo = desactivaciones por-equipo del
          esquema A (`contingency_active=false`) + `forced_deactivations` (esquema B OFF).
        - `active_at_cutoff` (reconstrucción EXACTA point-in-time): para cada WS de la org se
          toma su ÚLTIMO `CONTINGENCY_TOGGLE` con `created_at < cutoff`; si su
          `contingency_active` es True, la WS estaba en contingencia al cierre. Se traen todos
          los toggles de la org (`created_at < cutoff`) ordenados por `(workstation_id, created_at)`
          y se conserva el último por WS en memoria (evita N queries).
          `active_at_cutoff` es SOLO sobre el esquema A con `workstation_id NOT NULL` (equipos
          concretos en contingencia por detección automática al cierre). Las forzadas Org/VLAN
          vigentes al cierre NO se cuentan aquí: se reflejan en `forced_org` / `forced_vlan_count`
          (estado actual) y en las métricas de eventos forzados del ciclo.
          LIMITACIÓN CONOCIDA: por la retención de 12 meses de `audit_logs`
          (`audit.cleanup_old_logs`), cierres muy antiguos pueden SUBCONTAR este valor si el
          toggle relevante ya fue purgado. Es una métrica informativa fail-safe: NO afecta la
          factura.
        - `mass_vlan_events` / `mass_vlan_detail` / `mass_org_events` (ventana deslizante):
          se ordenan cronológicamente las activaciones (activated=True) del ciclo. Por VLAN, por
          cada activación se cuentan las WS DISTINTAS de la MISMA VLAN activadas en la ventana
          `[t, t + _MASS_WINDOW_MINUTES)`; si el conteo `>= _MASS_MIN_PER_VLAN`, se cuenta 1
          evento masivo y el cursor de esa VLAN avanza más allá de la ventana (evita
          solapamientos/doble conteo). El detalle guarda el top `_MASS_VLAN_DETAIL_TOP` por
          `count`. A nivel org, mismo algoritmo global (todas las VLANs juntas) contra el umbral
          `ceil(total_ws * _MASS_ORG_PCT)`; si `total_ws == 0`, `mass_org_events = 0`.
        - `forced_vlan_count` / `forced_org`: VLANs con `forced_contingency=True` y
          `org.forced_contingency` vigentes al momento de la consulta (contingencia forzada manual).

        FAIL-SAFE: toda la lógica va en try/except; ante CUALQUIER excepción se registra un
        warning y se devuelve un `ContingencySummary` en ceros con `data_available=False`. Nunca
        se propaga: el reporte no debe romperse por las métricas de contingencia.
        """
        from datetime import timedelta

        from app.models.audit import AuditLog, ActionType
        from app.models.workstation import Workstation
        from app.models.vlan import VLAN

        try:
            cycle_start = datetime(closure.period_year, closure.period_month, 1)
            cutoff = closure.cutoff_at

            # --- Mapa workstation_id -> vlan_id de la org (para agrupar por agencia/VLAN) ---
            ws_rows = (
                db.query(Workstation.id, Workstation.vlan_id)
                .filter(Workstation.organization_id == org.id)
                .all()
            )
            ws_to_vlan = {row[0]: row[1] for row in ws_rows}
            total_ws = len(ws_rows)

            # --- Activaciones dentro del ciclo [cycle_start, cutoff) ---
            cycle_toggles = (
                db.query(AuditLog)
                .filter(
                    AuditLog.organization_id == org.id,
                    AuditLog.action_type == ActionType.CONTINGENCY_TOGGLE,
                    AuditLog.created_at >= cycle_start,
                    AuditLog.created_at < cutoff,
                )
                .order_by(AuditLog.created_at.asc())
                .all()
            )

            # Recorremos las MISMAS filas del ciclo distinguiendo los DOS esquemas de new_values:
            #  - Esquema A (automático por-workstation): {"contingency_active": bool}. Alimenta
            #    activations_in_cycle / distinct_ws_activated / mass_* (algoritmo de ventana).
            #  - Esquema B (forzada manual Org/VLAN): {"forced_contingency": bool, "scope": ...,
            #    "affected_workstations": int, ...}, con workstation_id NULL. Alimenta las métricas
            #    forzadas separadas. Una fila de un esquema NO debe contaminar las del otro.
            activations = []  # (created_at, workstation_id) de las activaciones true del ciclo (esquema A)
            auto_deactivations = 0  # salidas por-equipo del esquema A (contingency_active=false)
            forced_org_activations = 0
            forced_vlan_activations = 0
            forced_deactivations = 0
            forced_affected_ws_total = 0
            for log in cycle_toggles:
                nv = log.new_values if isinstance(log.new_values, dict) else None
                if nv is None:
                    continue

                # --- Esquema B: contingencia forzada Org/VLAN (source manual_endpoint) ---
                if ("forced_contingency" in nv) or (
                    nv.get("scope") in ("organization", "vlan")
                ):
                    if nv.get("forced_contingency") is True:
                        scope = nv.get("scope")
                        if scope == "organization":
                            forced_org_activations += 1
                        elif scope == "vlan":
                            forced_vlan_activations += 1
                        forced_affected_ws_total += int(nv.get("affected_workstations") or 0)
                    elif nv.get("forced_contingency") is False:
                        forced_deactivations += 1
                    continue  # una fila del esquema B NUNCA cuenta como toggle por-equipo

                # --- Esquema A: toggle automático por-workstation ---
                if "contingency_active" in nv:
                    if nv.get("contingency_active") is True:
                        activations.append((log.created_at, log.workstation_id))
                    elif nv.get("contingency_active") is False:
                        auto_deactivations += 1

            activations_in_cycle = len(activations)
            distinct_ws_activated = len(
                {ws_id for (_, ws_id) in activations if ws_id is not None}
            )

            # SALIDAS totales del ciclo: por-equipo (esquema A, false) + forzadas OFF (esquema B).
            deactivations_in_cycle = auto_deactivations + forced_deactivations

            # --- active_at_cutoff: último toggle por WS con created_at < cutoff ---
            all_toggles = (
                db.query(AuditLog)
                .filter(
                    AuditLog.organization_id == org.id,
                    AuditLog.action_type == ActionType.CONTINGENCY_TOGGLE,
                    AuditLog.created_at < cutoff,
                    AuditLog.workstation_id.isnot(None),
                )
                .order_by(
                    AuditLog.workstation_id.asc(),
                    AuditLog.created_at.asc(),
                )
                .all()
            )
            last_toggle_by_ws = {}  # workstation_id -> último AuditLog (por created_at asc)
            for log in all_toggles:
                last_toggle_by_ws[log.workstation_id] = log  # el asc deja el último al final
            active_at_cutoff = sum(
                1
                for log in last_toggle_by_ws.values()
                if self._toggle_is_activation(log)
            )

            # --- Detección de entradas masivas (ventana deslizante) ---
            window = timedelta(minutes=_MASS_WINDOW_MINUTES)

            # Agrupar activaciones por VLAN (con la WS distinta como criterio de conteo).
            activations_by_vlan = {}  # vlan_id -> list[(created_at, ws_id)]
            for (created_at, ws_id) in activations:
                vlan_id = ws_to_vlan.get(ws_id)
                activations_by_vlan.setdefault(vlan_id, []).append((created_at, ws_id))

            mass_vlan_events = 0
            mass_vlan_detail = []
            for vlan_id, events in activations_by_vlan.items():
                events.sort(key=lambda e: e[0])
                count, detail = self._count_mass_windows(
                    events, window, _MASS_MIN_PER_VLAN
                )
                mass_vlan_events += count
                for d in detail:
                    mass_vlan_detail.append(
                        {
                            "vlan_id": str(vlan_id) if vlan_id is not None else None,
                            "count": d["count"],
                            "window_start": d["window_start"],
                            "window_end": d["window_end"],
                        }
                    )

            # Top N por count (los eventos masivos más grandes primero).
            mass_vlan_detail.sort(key=lambda d: d["count"], reverse=True)
            mass_vlan_detail = mass_vlan_detail[:_MASS_VLAN_DETAIL_TOP]

            # Masiva a nivel organización: ventana global sobre TODAS las activaciones.
            if total_ws > 0:
                import math

                org_threshold = max(1, math.ceil(total_ws * _MASS_ORG_PCT))
                org_events = sorted(activations, key=lambda e: e[0])
                mass_org_events, _ = self._count_mass_windows(
                    org_events, window, org_threshold
                )
            else:
                mass_org_events = 0

            # --- Contingencia forzada vigente (org/VLAN) ---
            forced_vlan_count = (
                db.query(VLAN)
                .filter(
                    VLAN.organization_id == org.id,
                    VLAN.forced_contingency.is_(True),
                )
                .count()
            )
            forced_org = bool(getattr(org, "forced_contingency", False))

            return ContingencySummary(
                activations_in_cycle=activations_in_cycle,
                distinct_ws_activated=distinct_ws_activated,
                active_at_cutoff=active_at_cutoff,
                mass_vlan_events=mass_vlan_events,
                mass_vlan_detail=mass_vlan_detail,
                mass_org_events=mass_org_events,
                forced_vlan_count=forced_vlan_count,
                forced_org=forced_org,
                forced_org_activations=forced_org_activations,
                forced_vlan_activations=forced_vlan_activations,
                forced_deactivations=forced_deactivations,
                forced_affected_ws_total=forced_affected_ws_total,
                deactivations_in_cycle=deactivations_in_cycle,
                data_available=True,
            )
        except Exception as exc:
            # FAIL-SAFE: nunca propagar. Resumen en ceros con data_available=False.
            logger.warning(
                "[CLOSURE_REPORT] Resumen de contingencia no disponible (fail-safe): %s",
                exc,
            )
            return ContingencySummary(data_available=False)

    @staticmethod
    def _toggle_is_activation(log) -> bool:
        """
        Indica si un `AuditLog` de `CONTINGENCY_TOGGLE` representa una activación por-equipo (true).

        SOLO considera el esquema A (toggle automático por-workstation): lee
        `new_values["contingency_active"]` de forma defensiva (el JSON column suele venir ya
        deserializado como dict). Las filas del esquema B (forzada Org/VLAN, que traen
        `forced_contingency`/`scope` y NO `contingency_active`) devuelven False a propósito, para
        NO contaminar `active_at_cutoff` (que reconstruye el estado por-workstation al cierre).
        Cualquier otro tipo/ausencia se trata como NO activación.
        """
        new_values = getattr(log, "new_values", None)
        if isinstance(new_values, dict):
            return new_values.get("contingency_active") is True
        return False

    @staticmethod
    def _count_mass_windows(events, window, threshold):
        """
        Cuenta ventanas "masivas" sobre una lista de activaciones ordenada cronológicamente.

        `events` es una lista de tuplas `(created_at, workstation_id)` YA ordenada asc. Para cada
        activación no consumida se cuentan las WS DISTINTAS activadas en `[t, t + window)`; si el
        conteo `>= threshold`, se cuenta 1 evento masivo, se registra su detalle y el cursor
        avanza más allá de la ventana (todas las activaciones dentro de `[t, t + window)` se
        marcan como consumidas) para no contar solapamientos varias veces.

        Devuelve `(count, detail)` donde `detail` es una lista de dicts
        `{"count": int, "window_start": iso, "window_end": iso}`.
        """
        count = 0
        detail = []
        n = len(events)
        i = 0
        while i < n:
            t0 = events[i][0]
            window_end = t0 + window
            distinct_ws = set()
            j = i
            while j < n and events[j][0] < window_end:
                ws_id = events[j][1]
                if ws_id is not None:
                    distinct_ws.add(ws_id)
                j += 1
            if len(distinct_ws) >= threshold:
                count += 1
                detail.append(
                    {
                        "count": len(distinct_ws),
                        "window_start": t0.isoformat(),
                        "window_end": window_end.isoformat(),
                    }
                )
                # Avanzar más allá de la ventana (consumir todas las activaciones en [t0, end)).
                i = j
            else:
                i += 1
        return count, detail

    # === Persistencia del artefacto derivado (billing_closure_reports) ===

    def get_report_row(
        self, db: Session, closure: BillingClosure
    ) -> Optional[BillingClosureReport]:
        """
        Devuelve la fila `BillingClosureReport` asociada al cierre (relación 1:1) o `None`.

        Es una lectura sin efectos secundarios: no crea la fila si no existe. El filtro es por
        `closure_id`, que es UNIQUE, por lo que a lo sumo hay una fila por cierre.
        """
        return (
            db.query(BillingClosureReport)
            .filter(BillingClosureReport.closure_id == closure.id)
            .first()
        )

    def upsert_report_row(
        self,
        db: Session,
        closure: BillingClosure,
        *,
        ai_analysis: Optional[str] = None,
        ai_model: Optional[str] = None,
        ai_generated_at: Optional[datetime] = None,
    ) -> BillingClosureReport:
        """
        Crea o actualiza la fila `BillingClosureReport` del cierre con la metadata del análisis IA.

        Escribe SIEMPRE sobre la tabla auxiliar `billing_closure_reports`, NUNCA sobre el cierre
        (`BillingClosure` es sustento inmutable). Si la fila no existe se inserta (desnormalizando
        `organization_id` para tenant isolation); si existe, se sobre-escriben el texto, el modelo
        y la fecha de generación del análisis (caso `regenerate`). Deja el commit al llamador que
        orquesta la transacción del pipeline.
        """
        row = self.get_report_row(db, closure)
        if row is None:
            row = BillingClosureReport(
                closure_id=closure.id,
                organization_id=closure.organization_id,  # desnormalizado (tenant isolation)
            )
            db.add(row)

        row.ai_analysis = ai_analysis
        row.ai_model = ai_model
        row.ai_generated_at = ai_generated_at

        db.flush()  # asigna PK/defaults sin cerrar la transacción del pipeline
        return row

    # === Construcción del prompt del análisis IA ===

    def build_ai_prompt(
        self,
        header: BillingClosure,
        history: List[HistoryPoint],
        items: List[BillingClosureItem],
        contingency: Optional[ContingencySummary] = None,
    ) -> str:
        """
        Construye el prompt (en español) para el análisis IA del consumo del cierre.

        Incluye la modalidad (`header.mode`) y la moneda (USD sin impuestos), la serie histórica
        de cierres por ciclo de servicio (facturables/reciclados/archivados/monto), y el desglose
        de tramos del mes objetivo (`header.tiers_applied`). Solicita al modelo tres bloques en
        español: resumen ejecutivo, análisis de evolución/crecimiento por número de ciclo de
        servicio y observaciones. `items` se acepta por firma (contexto disponible) aunque el
        detalle por IP se resume vía los totales del cierre para no inflar el prompt.

        Si `contingency` viene y tiene `data_available`, se agrega una sección con los eventos de
        contingencia del ciclo (activaciones y salidas por-equipo, entradas masivas, contingencia
        FORZADA Org/VLAN del ciclo con equipos afectados, y contingencia forzada vigente) y se pide
        comentar en las observaciones si hubo contingencia masiva/forzada, sus entradas y SALIDAS y
        su posible impacto operativo. Si es `None` o no hay datos, la sección se omite
        (compatibilidad hacia atrás).
        """
        sections: List[str] = []

        # Contexto/rol del modelo y reglas de tono y moneda.
        sections.append(
            "Eres un analista de consumo y facturacion de servicios de impresion corporativa. "
            "Redacta en espanol, con tono profesional y objetivo, sin exagerar hallazgos. "
            "Todos los precios estan expresados en dolares americanos (USD) y NO incluyen impuestos."
        )

        # Modalidad y moneda del cierre objetivo.
        sections.append(
            f"## Modalidad y moneda\n"
            f"- Modalidad del cierre: {header.mode}\n"
            f"- Moneda: USD (sin impuestos)\n"
            f"- Periodo objetivo: {header.period_year}-{header.period_month:02d}"
        )

        # Resumen del cierre objetivo (totales por estado y monto).
        sections.append(
            "## Resumen del mes objetivo\n"
            f"- Estaciones facturables: {header.total_billable}\n"
            f"- Estaciones recicladas: {header.total_recycled}\n"
            f"- Estaciones archivadas: {header.total_archived}\n"
            f"- Monto del mes: USD {header.amount}\n"
            f"- Tipo de cierre: {'retroactivo' if header.is_retroactive else 'normal'}"
        )

        # Serie histórica por ciclo de servicio (para el análisis de evolución).
        history_lines = ["## Serie historica de cierres (por ciclo de servicio)"]
        if history:
            for point in history:
                history_lines.append(
                    f"- Ciclo {point.cycle} ({point.period_year}-{point.period_month:02d}): "
                    f"facturables={point.total_billable}, reciclados={point.total_recycled}, "
                    f"archivados={point.total_archived}, monto=USD {point.amount}"
                )
        else:
            history_lines.append("- (sin cierres historicos disponibles)")
        sections.append("\n".join(history_lines))

        # Desglose de tramos del mes objetivo (composición del monto).
        sections.append(
            "## Desglose de tramos del mes objetivo\n" + self._format_tiers(header.tiers_applied)
        )

        # Eventos de contingencia del ciclo (opcional; solo si hay datos disponibles).
        if contingency is not None and contingency.data_available:
            sections.append(
                "## Eventos de contingencia del ciclo\n"
                f"- Activaciones de contingencia en el mes: {contingency.activations_in_cycle} "
                f"(equipos distintos: {contingency.distinct_ws_activated})\n"
                f"- Entradas masivas a nivel de agencia (VLAN): {contingency.mass_vlan_events}\n"
                f"- Entradas masivas a nivel de organizacion: {contingency.mass_org_events}\n"
                f"- Equipos que permanecen en contingencia al cierre: {contingency.active_at_cutoff}\n"
                f"- Contingencia forzada activada a nivel organizacion (eventos ON): "
                f"{contingency.forced_org_activations}\n"
                f"- Contingencia forzada activada a nivel agencia/VLAN (eventos ON): "
                f"{contingency.forced_vlan_activations}\n"
                f"- Desactivaciones/salidas de contingencia en el mes: "
                f"{contingency.deactivations_in_cycle}\n"
                f"- Equipos afectados por activaciones forzadas (acumulado): "
                f"{contingency.forced_affected_ws_total}\n"
                f"- Contingencia forzada vigente: organizacion={contingency.forced_org}, "
                f"VLANs={contingency.forced_vlan_count}"
            )

        # Solicitud concreta de las tres secciones en español.
        observaciones_extra = ""
        if contingency is not None and contingency.data_available:
            observaciones_extra = (
                " Comenta explicitamente si hubo contingencia masiva (a nivel de agencia/VLAN o de "
                "organizacion) y su posible impacto operativo. Comenta tambien las entradas y las "
                "SALIDAS (desactivaciones) de contingencia del ciclo, y la contingencia forzada a "
                "nivel de organizacion o de agencia/VLAN si las hubo."
            )
        sections.append(
            "## Solicitud\n"
            "Redacta un analisis en espanol con exactamente estas tres secciones:\n"
            "1. Resumen ejecutivo (2-3 oraciones sobre el estado general del consumo y el monto).\n"
            "2. Analisis de evolucion/crecimiento comentando explicitamente el numero de ciclo "
            "de servicio (compara ciclos, identifica tendencias de crecimiento o reduccion de "
            "estaciones facturables y del monto).\n"
            "3. Observaciones (detalle relevante del desglose de tramos, reciclaje/archivado y "
            "cualquier nota util para sustentar la factura)." + observaciones_extra
        )

        return "\n\n".join(sections)

    def _format_tiers(self, tiers_applied) -> str:
        """
        Formatea el desglose de tramos (`tiers_applied`) como texto legible para el prompt.

        Cada tramo del JSON tiene la forma `{tier_index, from, to, rate, ips_in_tier, subtotal}`
        (ver `billing_service.TierBreakdown.to_dict`). Un `to = None` representa un tramo sin
        tope superior. Si no hay tramos con IPs, lo indica de forma explícita.
        """
        if not tiers_applied:
            return "- (sin tramos aplicados / sin IPs facturables)"

        lines: List[str] = []
        for tier in tiers_applied:
            # `tiers_applied` es JSON (dicts); se accede defensivamente por si faltara una clave.
            if not isinstance(tier, dict):
                continue
            tier_from = tier.get("from")
            tier_to = tier.get("to")
            rate = tier.get("rate")
            ips_in_tier = tier.get("ips_in_tier", 0)
            subtotal = tier.get("subtotal")
            rango = f"{tier_from}-{tier_to}" if tier_to is not None else f"{tier_from}+"
            lines.append(
                f"- Tramo {rango}: tarifa=USD {rate}, IPs={ips_in_tier}, subtotal=USD {subtotal}"
            )

        return "\n".join(lines) if lines else "- (sin tramos aplicados / sin IPs facturables)"

    # === Storage / caché S3 del artefacto PDF (task 7.1) ===
    #
    # El PDF del reporte se cachea en S3 con una key determinista por cierre. Como el cierre es
    # sustento inmutable, la key es estable: la misma entrada siempre resuelve al mismo objeto,
    # lo que permite servir desde caché (cache-hit) sin recomputar el pipeline. El bucket es el
    # mismo que usa `debugging_analysis._upload_to_s3` (`settings.S3_DOCS_BUCKET`).

    def build_s3_key(self, closure: BillingClosure) -> str:
        """
        Construye la key S3 determinista del artefacto PDF del cierre.

        Formato: `billing-reports/{organization_id}/{closure_id}/report.pdf`. Al depender solo
        de identificadores inmutables del cierre, es idempotente: la misma entrada devuelve
        siempre la misma key, base de la caché (cache-hit vía `s3_exists`) y de la sobre-escritura
        en `regenerate` (mismo objeto en `upload_to_s3`).
        """
        return f"{_S3_KEY_PREFIX}/{closure.organization_id}/{closure.id}/report.pdf"

    def _get_s3_client(self):
        """
        Crea el cliente S3 con SigV4 y endpoint regional explícito.

        Replica `restore.py::_get_s3_client`: se fuerza SigV4 (`Config(signature_version="s3v4")`)
        y el endpoint regional explícito (`https://s3.{AWS_REGION}.amazonaws.com`). Sin el endpoint
        regional, botocore firma `generate_presigned_url()` contra el host global
        `s3.amazonaws.com` (sin región) y, para un bucket fuera de us-east-1, S3 responde
        `SignatureDoesNotMatch`. Con SigV2 (deprecado) la presigned URL directamente es rechazada.
        """
        session = boto3.Session(
            region_name=settings.AWS_REGION,
            profile_name=settings.AWS_PROFILE or None,
        )
        return session.client(
            "s3",
            endpoint_url=f"https://s3.{settings.AWS_REGION}.amazonaws.com",
            config=Config(signature_version="s3v4"),
        )

    def s3_exists(self, s3_key: str) -> bool:
        """
        Indica si el artefacto existe en S3 (cache-hit) usando `head_object`.

        Devuelve `True` si `head_object` responde 200; `False` si el objeto no existe
        (`404`/`NoSuchKey`). Cualquier otro `ClientError` (permisos, red) se propaga para que el
        llamador lo trate como fallo de S3 (502/500) y no lo confunda con un cache-miss.
        """
        s3 = self._get_s3_client()
        try:
            s3.head_object(Bucket=settings.S3_DOCS_BUCKET, Key=s3_key)
            return True
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code in ("404", "NoSuchKey", "NotFound"):
                return False
            # Otros errores (403, red, etc.) NO son cache-miss: propagar como fallo de S3.
            raise

    def upload_to_s3(self, pdf_bytes: bytes, s3_key: str) -> None:
        """
        Sube el PDF a S3 sobre la key determinista, sobre-escribiendo si ya existe.

        Reutiliza el patrón de `debugging_analysis._upload_to_s3` (`put_object` con
        `ContentType="application/pdf"` y `ContentDisposition` de descarga). Como S3 sobre-escribe
        por defecto al reusar la misma key, esto reemplaza el artefacto en el caso `regenerate`.
        Ante cualquier fallo se levanta `ClosureReportError` (el llamador lo mapea a 502/500 y NO
        deja un artefacto parcial cacheado).
        """
        s3 = self._get_s3_client()
        try:
            s3.put_object(
                Bucket=settings.S3_DOCS_BUCKET,
                Key=s3_key,
                Body=pdf_bytes,
                ContentType="application/pdf",
                ContentDisposition='attachment; filename="closure_report.pdf"',
            )
            logger.info(
                "[CLOSURE_REPORT] PDF subido a S3: bucket=%s, key=%s, size=%d bytes",
                settings.S3_DOCS_BUCKET,
                s3_key,
                len(pdf_bytes),
            )
        except Exception as exc:
            raise ClosureReportError(f"Error subiendo PDF del reporte a S3: {exc}") from exc

    def generate_presigned_url(
        self, s3_key: str, download_filename: Optional[str] = None
    ) -> str:
        """
        Genera una presigned URL de descarga (GET) del artefacto con expiración de 3600s.

        Usa el cliente SigV4 regional (`_get_s3_client`). Fija `ResponseContentDisposition`
        (`attachment; filename="..."`) para que el navegador descargue el PDF con un nombre
        sugerido en lugar de mostrarlo inline; si `download_filename` es `None`, usa
        `closure_report.pdf` por defecto. La URL caduca en `_PRESIGNED_URL_EXPIRES_SECONDS`
        (3600s), como en `debugging.py`. Ante fallo levanta `ClosureReportError` (502/500).
        """
        filename = download_filename or "closure_report.pdf"
        s3 = self._get_s3_client()
        try:
            return s3.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": settings.S3_DOCS_BUCKET,
                    "Key": s3_key,
                    "ResponseContentDisposition": f'attachment; filename="{filename}"',
                },
                ExpiresIn=_PRESIGNED_URL_EXPIRES_SECONDS,
            )
        except Exception as exc:
            raise ClosureReportError(
                f"Error generando presigned URL del reporte de cierre: {exc}"
            ) from exc

    def build_download_filename(self, header: "BillingClosure", org: "Organization") -> str:
        """
        Construye el nombre de descarga del PDF con la organización y el periodo del cierre.

        Formato: `Reporte_Cierre_<Org>_<YYYY-MM>.pdf`. El nombre de la organización se sanea a
        ASCII (se quitan acentos/caracteres no alfanuméricos y los espacios pasan a `_`) para que
        sea un nombre de archivo válido y estable en cualquier navegador/SO.
        """
        import re
        import unicodedata

        org_name = getattr(org, "name", None) or "Organizacion"
        # Normalizar a ASCII: quitar acentos y dejar solo alfanumérico + espacios/guiones.
        ascii_name = (
            unicodedata.normalize("NFKD", str(org_name))
            .encode("ascii", "ignore")
            .decode("ascii")
        )
        ascii_name = re.sub(r"[^A-Za-z0-9]+", "_", ascii_name).strip("_")
        if not ascii_name:
            ascii_name = "Organizacion"

        period = f"{int(header.period_year):04d}-{int(header.period_month):02d}"
        return f"Reporte_Cierre_{ascii_name}_{period}.pdf"

    # === Análisis IA cacheado con fail-safe ===

    async def resolve_ai_analysis(
        self,
        db: Session,
        closure: BillingClosure,
        org: Organization,
        header: BillingClosure,
        items: List[BillingClosureItem],
        history: List[HistoryPoint],
        regenerate: bool = False,
        contingency: Optional[ContingencySummary] = None,
    ) -> Optional[str]:
        """
        Resuelve el análisis IA del cierre: caché si existe, si no invoca el LLM (fail-safe).

        Comportamiento:
        - Si `regenerate=False` y ya existe una fila con `ai_analysis` no nulo → devuelve el texto
          cacheado SIN invocar el LLM (el cierre es inmutable, el análisis también lo es).
        - En caso contrario, construye el prompt e invoca el LLM reutilizando el patrón
          multi-proveedor de `debugging_analysis._invoke_llm` (Bedrock por defecto; OpenAI si
          `org.openai_api_key`; respeta `org.llm_model_id` y aplica retry/backoff). En éxito,
          persiste texto + modelo + `ai_generated_at` con `upsert_report_row`.
        - FAIL-SAFE: si el LLM falla tras los reintentos, se registra un warning, se devuelve
          `None` y NO se propaga la excepción. Un fallo de IA nunca bloquea la factura ni el PDF.
        """
        # 1. Cache-hit: análisis ya persistido y no se pide regenerar.
        if not regenerate:
            cached = self.get_report_row(db, closure)
            if cached is not None and cached.ai_analysis is not None:
                logger.info(
                    "[CLOSURE_REPORT] Analisis IA servido desde cache para cierre %s",
                    closure.id,
                )
                return cached.ai_analysis

        # 2. Construir prompt e invocar el LLM (fail-safe ante cualquier fallo).
        prompt = self.build_ai_prompt(header, history, items, contingency=contingency)
        try:
            analysis_text, model_id = await self._invoke_llm(prompt, org)
        except Exception as exc:
            # FAIL-SAFE: no propagar. El PDF se genera con la nota de "IA no disponible".
            logger.warning(
                "[CLOSURE_REPORT] Analisis IA no disponible para cierre %s (fail-safe): %s",
                closure.id,
                exc,
            )
            return None

        # 3. Persistir el análisis (texto + modelo + fecha) en la tabla auxiliar.
        self.upsert_report_row(
            db,
            closure,
            ai_analysis=analysis_text,
            ai_model=model_id,
            ai_generated_at=datetime.utcnow(),
        )
        logger.info(
            "[CLOSURE_REPORT] Analisis IA generado y persistido para cierre %s (modelo=%s)",
            closure.id,
            model_id,
        )
        return analysis_text

    async def _invoke_llm(self, prompt: str, org: Organization) -> tuple[str, str]:
        """
        Invoca el LLM respetando la configuración de la organización, con retry/backoff.

        Reutiliza el patrón de `debugging_analysis._invoke_llm`: usa OpenAI cuando
        `org.openai_api_key` está presente (y respeta `org.llm_model_id` si es un modelo OpenAI),
        y en caso contrario usa el `LLMService` por defecto (Bedrock) pasando `org.llm_model_id`
        como override. Reintenta ante `LLMServiceError` hasta `_LLM_MAX_RETRIES`.

        Devuelve la tupla `(texto_respuesta, model_id)` para poder persistir el modelo usado.
        Propaga `ClosureReportError` si se agotan los reintentos (el llamador aplica el fail-safe).
        """
        import asyncio

        from app.services.llm_service import (
            LLMService,
            LLMServiceError,
            OpenAIProvider,
        )

        last_error: Optional[Exception] = None

        for attempt in range(_LLM_MAX_RETRIES):
            try:
                if org.openai_api_key:
                    provider = OpenAIProvider()
                    provider.api_key = org.openai_api_key
                    if org.llm_model_id and any(
                        org.llm_model_id.startswith(p)
                        for p in ("gpt-", "o1-", "o3-", "chatgpt-")
                    ):
                        provider.model = org.llm_model_id
                    response_text, input_tokens, output_tokens = await provider.invoke(
                        prompt, settings.LOG_ANALYZER_LLM_MAX_TOKENS
                    )
                    model_id = provider.get_provider_name()
                else:
                    llm_service = LLMService()
                    response_text, input_tokens, output_tokens = await llm_service.invoke(
                        prompt, model_id=org.llm_model_id
                    )
                    model_id = llm_service.provider.get_provider_name()

                logger.info(
                    "[CLOSURE_REPORT] LLM completado: tokens_in=%d, tokens_out=%d, intento=%d",
                    input_tokens,
                    output_tokens,
                    attempt + 1,
                )
                return response_text, model_id

            except LLMServiceError as exc:
                last_error = exc
                if attempt < _LLM_MAX_RETRIES - 1:
                    logger.warning(
                        "[CLOSURE_REPORT] LLM error (intento %d/%d): %s. Reintentando en %ds...",
                        attempt + 1,
                        _LLM_MAX_RETRIES,
                        exc,
                        _LLM_RETRY_DELAY_SECONDS,
                    )
                    await asyncio.sleep(_LLM_RETRY_DELAY_SECONDS)
                else:
                    raise ClosureReportError(
                        f"Error del LLM tras {_LLM_MAX_RETRIES} intentos: {exc}"
                    ) from exc

        # Salvaguarda: no debería alcanzarse (el último intento lanza dentro del loop).
        raise ClosureReportError(
            f"Error inesperado en invocacion LLM del reporte de cierre: {last_error}"
        )

    # === Orquestación: generación o servido desde caché (task 7.2) ===

    async def generate_or_get(
        self,
        db: Session,
        closure: BillingClosure,
        org: Organization,
        regenerate: bool = False,
    ) -> tuple[str, bool, bool]:
        """
        Punto de entrada del pipeline: sirve el PDF desde caché S3 o lo genera de cero.

        Devuelve la tupla `(s3_key, ai_available, cached)`:
        - `s3_key`: key determinista del artefacto en S3 (`build_s3_key`).
        - `ai_available`: `True` si el reporte tiene análisis IA disponible (no nulo).
        - `cached`: `True` si se sirvió desde caché sin recomputar; `False` si se (re)generó.

        Comportamiento:
        - Cache-hit: si `regenerate=False` y el artefacto ya existe en S3 (`s3_exists`), NO se
          recomputa nada; se devuelve `(s3_key, <existe fila con ai_analysis>, True)`. El flag de
          IA se deriva de la fila persistida (`billing_closure_reports`), no del pipeline.
        - Cache-miss o `regenerate=True`: se ejecuta el pipeline completo — cargar items del
          cierre, serie histórica, análisis IA (fail-safe), render de ambos gráficos, composición
          del PDF y subida a S3 (sobre-escribe en `regenerate`); se devuelve
          `(s3_key, analysis IS NOT NULL, False)`.

        El `BillingClosure` (y sus items) se tratan como SOLO LECTURA (Req 11.3): esta orquestación
        nunca los modifica. La única escritura es sobre la tabla auxiliar `billing_closure_reports`
        (metadata del análisis IA vía `resolve_ai_analysis`, y `pdf_s3_key`/`pdf_generated_at` del
        artefacto generado).
        """
        s3_key = self.build_s3_key(closure)

        # 1. Cache-hit: artefacto ya en S3 y no se pide regenerar → servir sin recomputar.
        if not regenerate and self.s3_exists(s3_key):
            row = self.get_report_row(db, closure)
            ai_available = row is not None and row.ai_analysis is not None
            logger.info(
                "[CLOSURE_REPORT] Reporte servido desde cache S3 para cierre %s (key=%s)",
                closure.id,
                s3_key,
            )
            return (s3_key, ai_available, True)

        # 2. Cache-miss o regenerate: ejecutar el pipeline completo.
        #    El cierre y sus items son SOLO LECTURA (Req 11.3).
        header = closure  # BillingClosure (sustento inmutable)

        items = (
            db.query(BillingClosureItem)
            .filter(BillingClosureItem.closure_id == closure.id)
            .all()
        )

        history = self.build_history_series(db, org, up_to=closure)

        # Resumen de contingencia del ciclo (fail-safe): se calcula ANTES del análisis IA para
        # alimentar el prompt y, en paralelo, la nueva sección del PDF.
        contingency = self.build_contingency_summary(db, org, closure)

        analysis = await self.resolve_ai_analysis(
            db,
            closure,
            org,
            header,
            items,
            history,
            regenerate=regenerate,
            contingency=contingency,
        )

        # Render de gráficos server-side (PNG en memoria; degradan de forma elegante sin datos).
        tiers_png = render_tiers_chart(header.tiers_applied)
        history_png = render_history_chart(history)

        # Composición del PDF con las 9 secciones (valida reconciliación internamente).
        pdf_bytes = compose_pdf(
            header,
            items,
            history,
            tiers_png,
            history_png,
            analysis,
            org,
            contingency=contingency,
        )

        # Subida a S3 sobre la key determinista (sobre-escribe en regenerate).
        self.upload_to_s3(pdf_bytes, s3_key)

        # Registrar la key/fecha del artefacto en la tabla auxiliar (NUNCA en BillingClosure).
        self._record_pdf_artifact(db, closure, s3_key)

        logger.info(
            "[CLOSURE_REPORT] Reporte %s para cierre %s (key=%s, ai=%s)",
            "regenerado" if regenerate else "generado",
            closure.id,
            s3_key,
            analysis is not None,
        )
        return (s3_key, analysis is not None, False)

    def _record_pdf_artifact(
        self, db: Session, closure: BillingClosure, s3_key: str
    ) -> BillingClosureReport:
        """
        Anota `pdf_s3_key`/`pdf_generated_at` del artefacto en la fila auxiliar del reporte.

        Escribe SIEMPRE sobre `billing_closure_reports`, NUNCA sobre el cierre (`BillingClosure`
        es sustento inmutable, Req 11.3). A diferencia de `upsert_report_row`, preserva la metadata
        del análisis IA (texto/modelo/fecha) que `resolve_ai_analysis` pudo haber persistido en la
        misma transacción: solo toca los campos del PDF. Crea la fila si no existe (desnormalizando
        `organization_id` para tenant isolation) y deja el commit al llamador.
        """
        row = self.get_report_row(db, closure)
        if row is None:
            row = BillingClosureReport(
                closure_id=closure.id,
                organization_id=closure.organization_id,  # desnormalizado (tenant isolation)
            )
            db.add(row)

        row.pdf_s3_key = s3_key
        row.pdf_generated_at = datetime.utcnow()

        db.flush()  # asigna PK/defaults sin cerrar la transacción del pipeline
        return row


# === RENDER DE GRÁFICOS SERVER-SIDE (task 4.1) ===
#
# Funciones puras (sin estado, sin efectos secundarios salvo el render en memoria) que
# devuelven `bytes` PNG. Cada una:
#   - Crea una figura, dibuja, exporta a un buffer `io.BytesIO` con `dpi` fijo (_CHART_DPI).
#   - Llama SIEMPRE a `plt.close(fig)` tras exportar (incluso en errores) para no filtrar
#     figuras (evita fugas de memoria en el backend headless "Agg").
#   - Degrada de forma elegante (sin excepción) cuando no hay datos suficientes:
#       * render_tiers_chart  → placeholder "sin IPs facturables" si no hay tramos con IPs.
#       * render_history_chart → render mínimo con marcador único + nota "primer ciclo de
#         servicio" cuando solo hay un punto.


def _tier_ips(tier: object) -> int:
    """
    Extrae `ips_in_tier` (entero >= 0) de un tramo de `tiers_applied` de forma defensiva.

    `tiers_applied` es JSON plano en la cabecera del cierre (lista de dicts serializados por
    `TierBreakdown.to_dict`), por lo que se accede con `.get` y se tolera ausencia o tipos
    inesperados devolviendo 0 (no facturable) en vez de lanzar excepción.
    """
    if not isinstance(tier, dict):
        return 0
    try:
        value = int(tier.get("ips_in_tier", 0) or 0)
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0


def _tier_label(tier: object, index: int) -> str:
    """
    Construye la etiqueta legible de un tramo para el eje X (p. ej. "1-100", "101+").

    Usa `from`/`to` del dict serializado; si `to` es None (último tramo sin tope) muestra
    "{from}+". Ante datos ausentes cae en un rótulo genérico "Tramo {index+1}".
    """
    if not isinstance(tier, dict):
        return f"Tramo {index + 1}"
    tier_from = tier.get("from")
    tier_to = tier.get("to")
    if tier_from is None:
        return f"Tramo {index + 1}"
    if tier_to is None:
        return f"{tier_from}+"
    return f"{tier_from}-{tier_to}"


def _placeholder_png(message: str) -> bytes:
    """
    Genera un PNG mínimo con un texto centrado (sin ejes) usado como degradación elegante.

    Se emplea cuando no hay datos que graficar (p. ej. "sin IPs facturables"): produce un
    artefacto válido y no vacío para que la composición del PDF nunca falle por falta de datos.
    """
    fig = plt.figure(figsize=(6, 3.5))
    try:
        ax = fig.add_subplot(111)
        ax.axis("off")
        ax.text(
            0.5,
            0.5,
            message,
            ha="center",
            va="center",
            fontsize=13,
            color="#666666",
            wrap=True,
        )
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=_CHART_DPI, bbox_inches="tight")
    finally:
        # Cerrar SIEMPRE la figura para no filtrarla (aunque savefig fallara).
        plt.close(fig)
    return buf.getvalue()


def _to_decimal(value: object) -> Decimal:
    """
    Convierte a `Decimal` de forma tolerante (los montos viajan como str/Decimal/num en JSON).

    Ante valores no convertibles devuelve Decimal("0") para no romper el render del gráfico.
    """
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def render_tiers_chart(tiers_applied: list) -> bytes:
    """
    Gráfico de composición de tramos del mes: IPs facturables (`ips_in_tier`) por tramo.

    Entrada: `tiers_applied` (JSON plano de la cabecera del cierre), lista de dicts con al
    menos `from`, `to`, `ips_in_tier`. Dibuja un gráfico de barras (una barra por tramo con
    `ips_in_tier > 0`) y anota el valor sobre cada barra.

    Degradación elegante (Req 4.5/4.6): si `tiers_applied` está vacío o ningún tramo tiene
    `ips_in_tier > 0` (p. ej. modalidad anual o sin IPs facturables), devuelve un PNG
    placeholder "sin IPs facturables" en vez de lanzar excepción.

    Devuelve los `bytes` del PNG (dpi fijo `_CHART_DPI`); cierra la figura tras exportar.
    """
    tiers = tiers_applied or []

    # Conservar solo los tramos con IPs facturables (>0); si ninguno → placeholder.
    populated = [(t, _tier_ips(t)) for t in tiers]
    populated = [(t, ips) for (t, ips) in populated if ips > 0]

    if not populated:
        return _placeholder_png("Sin IPs facturables")

    labels = [_tier_label(t, i) for i, (t, _) in enumerate(populated)]
    values = [ips for (_, ips) in populated]

    fig = plt.figure(figsize=(7, 4))
    try:
        ax = fig.add_subplot(111)
        bars = ax.bar(labels, values, color="#2563eb")
        ax.set_title("Composición de IPs facturables por tramo")
        ax.set_xlabel("Tramo (rango de IPs)")
        ax.set_ylabel("IPs facturables")
        ax.margins(y=0.15)  # espacio para las anotaciones sobre las barras

        # Anotar el valor sobre cada barra.
        for bar, value in zip(bars, values):
            ax.annotate(
                str(value),
                xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=9,
            )

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=_CHART_DPI, bbox_inches="tight")
    finally:
        plt.close(fig)
    return buf.getvalue()


def render_history_chart(history: list) -> bytes:
    """
    Gráfico de evolución histórica: `total_billable` (barras) y `amount` (línea, eje derecho).

    Entrada: `history` (lista de `HistoryPoint`), ya ordenada por ciclo. El eje X usa el
    periodo "YYYY-MM" de cada ciclo. Se dibujan dos series sobre ejes gemelos: barras para las
    estaciones facturables y una línea (eje secundario) para el monto en USD.

    Degradación elegante (Req 4.4): si `history` está vacío devuelve un placeholder; si tiene
    un solo punto, render mínimo con un marcador único y la nota "primer ciclo de servicio"
    (sin excepción).

    Devuelve los `bytes` del PNG (dpi fijo `_CHART_DPI`); cierra la figura tras exportar.
    """
    points = history or []

    if not points:
        return _placeholder_png("Sin cierres para graficar")

    # Etiqueta de eje X "YYYY-MM" por ciclo (defensiva ante atributos ausentes).
    def _period_label(p: object) -> str:
        year = getattr(p, "period_year", None)
        month = getattr(p, "period_month", None)
        if year is None or month is None:
            cycle = getattr(p, "cycle", "?")
            return f"Ciclo {cycle}"
        return f"{int(year):04d}-{int(month):02d}"

    labels = [_period_label(p) for p in points]
    billable = [int(getattr(p, "total_billable", 0) or 0) for p in points]
    amounts = [float(_to_decimal(getattr(p, "amount", 0))) for p in points]

    fig = plt.figure(figsize=(7, 4))
    try:
        ax_bill = fig.add_subplot(111)

        if len(points) == 1:
            # Render mínimo: un solo ciclo. Marcador único para facturables + monto y nota.
            ax_bill.plot(
                labels,
                billable,
                marker="o",
                markersize=9,
                color="#2563eb",
                linestyle="None",
                label="Estaciones facturables",
            )
            ax_bill.set_ylabel("Estaciones facturables", color="#2563eb")
            ax_bill.margins(x=0.5, y=0.3)

            ax_amount = ax_bill.twinx()
            ax_amount.plot(
                labels,
                amounts,
                marker="s",
                markersize=8,
                color="#16a34a",
                linestyle="None",
                label="Monto (USD)",
            )
            ax_amount.set_ylabel("Monto (USD)", color="#16a34a")

            ax_bill.set_title("Evolución histórica")
            ax_bill.set_xlabel("Periodo (YYYY-MM)")
            # Nota explícita de degradación elegante para el primer ciclo.
            ax_bill.text(
                0.5,
                -0.28,
                "Primer ciclo de servicio",
                transform=ax_bill.transAxes,
                ha="center",
                va="top",
                fontsize=9,
                color="#666666",
            )
        else:
            # Serie completa: barras (facturables) + línea (monto) en eje secundario.
            ax_bill.bar(labels, billable, color="#2563eb", label="Estaciones facturables")
            ax_bill.set_ylabel("Estaciones facturables", color="#2563eb")
            ax_bill.set_xlabel("Periodo (YYYY-MM)")
            ax_bill.margins(y=0.15)

            ax_amount = ax_bill.twinx()
            ax_amount.plot(
                labels,
                amounts,
                marker="o",
                color="#16a34a",
                linewidth=2,
                label="Monto (USD)",
            )
            ax_amount.set_ylabel("Monto (USD)", color="#16a34a")

            ax_bill.set_title("Evolución histórica de estaciones facturables y monto")

        # Rotar etiquetas del eje X si hay varios ciclos (evita solape).
        for label in ax_bill.get_xticklabels():
            label.set_rotation(45)
            label.set_horizontalalignment("right")

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=_CHART_DPI, bbox_inches="tight")
    finally:
        plt.close(fig)
    return buf.getvalue()


# === RECONCILIACIÓN DE MONTOS (task 6.2) ===
#
# Antes de componer el PDF se valida que el total del desglose por tramo y la suma de los
# `items.amount` reconcilien con `header.amount` (la fuente de verdad de la factura) dentro de
# una tolerancia `< 0.01`. Se aplica redondeo half-up con la cabecera a 2 decimales y los items
# a 4 decimales (Req 10.1). Si la diferencia excede la tolerancia se registra un warning y se
# devuelve la información de la discrepancia para anotarla en el PDF (Req 10.2), pero NUNCA se
# altera `header.amount` (Req 10.3): la cabecera se preserva como fuente de verdad.

# Tolerancia de reconciliación: diferencias por debajo de este umbral se consideran ruido de
# redondeo y NO se reportan como discrepancia.
_RECONCILIATION_TOLERANCE = Decimal("0.01")

# Cuantización half-up para cabecera (2 decimales) e items/subtotales (4 decimales).
_HEADER_QUANTIZE = Decimal("0.01")
_ITEMS_QUANTIZE = Decimal("0.0001")


def _quantize_half_up(value: Decimal, exp: Decimal) -> Decimal:
    """
    Redondea `value` a la precisión `exp` usando half-up (ROUND_HALF_UP).

    Se usa para normalizar la cabecera a 2 decimales y los items/subtotales a 4 decimales antes
    de compararlos, replicando el redondeo del motor de facturación (`compute_amount_monthly`).
    """
    from decimal import ROUND_HALF_UP

    return value.quantize(exp, rounding=ROUND_HALF_UP)


class ReconciliationResult:
    """
    Resultado de la validación de reconciliación de montos.

    Atributos:
        header_amount: monto de cabecera (fuente de verdad), cuantizado a 2 decimales.
        tiers_total: suma de los subtotales del desglose por tramo (4 decimales).
        items_total: suma de `items.amount` (4 decimales).
        tiers_diff: |header_amount - tiers_total| (para diagnóstico).
        items_diff: |header_amount - items_total| (para diagnóstico).
        reconciled: True si AMBAS diferencias están dentro de la tolerancia `< 0.01`.
        note: texto en español para anotar en el PDF cuando NO reconcilia (None si reconcilia).
    """

    def __init__(
        self,
        header_amount: Decimal,
        tiers_total: Decimal,
        items_total: Decimal,
        tiers_diff: Decimal,
        items_diff: Decimal,
        reconciled: bool,
        note: Optional[str],
    ) -> None:
        self.header_amount = header_amount
        self.tiers_total = tiers_total
        self.items_total = items_total
        self.tiers_diff = tiers_diff
        self.items_diff = items_diff
        self.reconciled = reconciled
        self.note = note


def validate_reconciliation(
    header: BillingClosure,
    items: List[BillingClosureItem],
) -> ReconciliationResult:
    """
    Valida que el desglose de tramos y `items.amount` reconcilien con `header.amount`.

    Suma los `subtotal` de `header.tiers_applied` y, por separado, los `items.amount`, y compara
    ambos totales contra `header.amount`. La cabecera se cuantiza a 2 decimales y los totales
    derivados a 4 decimales (half-up), tal como los produce el motor de facturación. Si alguna de
    las dos diferencias excede la tolerancia `< 0.01` (Req 10.1), se registra un warning (Req 10.2)
    y se arma una nota de discrepancia para el PDF; en ningún caso se modifica `header.amount`
    (Req 10.3): siempre es la fuente de verdad.

    Devuelve un `ReconciliationResult` con los totales, las diferencias y la nota (si aplica).
    """
    header_amount = _quantize_half_up(_to_decimal(header.amount), _HEADER_QUANTIZE)

    # Total del desglose por tramo (suma de subtotales de tiers_applied).
    tiers_total = Decimal("0")
    for tier in header.tiers_applied or []:
        if isinstance(tier, dict):
            tiers_total += _to_decimal(tier.get("subtotal", 0))
    tiers_total = _quantize_half_up(tiers_total, _ITEMS_QUANTIZE)

    # Total de los aportes por IP (suma de items.amount).
    items_total = Decimal("0")
    for item in items or []:
        items_total += _to_decimal(getattr(item, "amount", 0))
    items_total = _quantize_half_up(items_total, _ITEMS_QUANTIZE)

    tiers_diff = abs(header_amount - tiers_total)
    items_diff = abs(header_amount - items_total)

    reconciled = (
        tiers_diff < _RECONCILIATION_TOLERANCE and items_diff < _RECONCILIATION_TOLERANCE
    )

    note: Optional[str] = None
    if not reconciled:
        # Req 10.2: log warning + anotar en el PDF. Req 10.3: NO se altera header.amount.
        logger.warning(
            "[CLOSURE_REPORT] Discrepancia de reconciliacion en cierre %s: "
            "header_amount=%s, tiers_total=%s (dif=%s), items_total=%s (dif=%s), "
            "tolerancia=%s. Se preserva header.amount como fuente de verdad.",
            getattr(header, "id", "?"),
            header_amount,
            tiers_total,
            tiers_diff,
            items_total,
            items_diff,
            _RECONCILIATION_TOLERANCE,
        )
        note = (
            "Aviso de reconciliacion: el total del desglose (USD "
            f"{tiers_total}) y/o la suma de items (USD {items_total}) difieren del monto de "
            f"cabecera (USD {header_amount}) por encima de la tolerancia de "
            f"{_RECONCILIATION_TOLERANCE}. El monto de cabecera se conserva como fuente de "
            "verdad de la factura y no ha sido alterado."
        )

    return ReconciliationResult(
        header_amount=header_amount,
        tiers_total=tiers_total,
        items_total=items_total,
        tiers_diff=tiers_diff,
        items_diff=items_diff,
        reconciled=reconciled,
        note=note,
    )


# === COMPOSICIÓN DEL PDF (task 6.1) ===
#
# `compose_pdf` reutiliza el patrón de `debugging_analysis._generate_pdf`: subclase de FPDF con
# `footer()` de copyright en cada página (sección 9), incrustación de logos con `pdf.image()` y el
# helper `sanitize` para compatibilidad Latin-1 de la fuente Helvetica (Req 11.5). Compone las 9
# secciones del modelo de contenido del diseño en orden. Antes de componer valida la reconciliación
# de montos (task 6.2) y, si no reconcilia, anota la discrepancia sin alterar `header.amount`.

# Texto obligatorio de la declaración USD sin impuestos (sección 8, Req 3.7 / 11.5).
_USD_DISCLAIMER = (
    "Todos los precios estan expresados en dolares americanos (USD) y no incluyen impuestos."
)

# Nota fail-safe cuando el análisis IA no está disponible (sección 7, Req 5.4).
_AI_FAILSAFE_NOTE = (
    "Analisis IA no disponible en este momento. La generacion del reporte no se bloquea por la "
    "ausencia del analisis (fail-safe); el sustento de la factura permanece completo."
)


def _sanitize_latin1(text: str) -> str:
    """
    Reemplaza caracteres Unicode incompatibles con Latin-1 (fuente Helvetica de fpdf2).

    Replica el helper `sanitize` de `debugging_analysis._generate_pdf`: convierte comillas
    tipográficas, guiones largos, viñetas y elipsis a equivalentes ASCII y, como red de
    seguridad, codifica a Latin-1 con `errors="replace"` para no romper el render del PDF.
    """
    replacements = {
        "\u2022": "-",   # bullet
        "\u2013": "-",   # en-dash
        "\u2014": "--",  # em-dash
        "\u2018": "'",   # left single quote
        "\u2019": "'",   # right single quote
        "\u201c": '"',   # left double quote
        "\u201d": '"',   # right double quote
        "\u2026": "...",  # ellipsis
        "\u00b7": "-",   # middle dot
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _fmt_period(header: BillingClosure) -> str:
    """Formatea el periodo del cierre como `YYYY-MM` (p. ej. 2026-03)."""
    return f"{int(header.period_year):04d}-{int(header.period_month):02d}"


def compose_pdf(
    header: BillingClosure,
    items: List[BillingClosureItem],
    history: List[HistoryPoint],
    tiers_png: bytes,
    history_png: bytes,
    analysis: Optional[str],
    org: Organization,
    contingency: Optional["ContingencySummary"] = None,
) -> bytes:
    """
    Compone el PDF del Reporte de Cierre Mensual (sustento de factura) con las 9 secciones.

    Reutiliza el patrón de `debugging_analysis._generate_pdf` (FPDF + footer de copyright,
    incrustación de logos, sanitización Latin-1). Secciones, en orden (modelo de contenido del
    diseño):
      1. Portada: logos AlwaysPrint + Robles.AI, titulo, organizacion, periodo YYYY-MM,
         modalidad y fecha de generacion.
      2. Resumen del cierre: facturables/reciclados/archivados, monto USD y tipo de cierre.
      3. Conceptos, tarifas, modalidad y tabla de tramos.
      4. Grafico de composicion de tramos (`tiers_png`).
      5. Grafico de evolucion historica (`history_png`).
      6. Tabla resumen del desglose por tramo (from, to, rate, ips_in_tier, subtotal).
      6b. Contingencia del ciclo: activaciones, entradas masivas (VLAN/org), equipos en
          contingencia al cierre y contingencia forzada vigente (o nota fail-safe si
          `contingency is None` o no hay datos). Va JUSTO DESPUES de conceptos/tarifas + tabla de
          tramos y ANTES del analisis IA.
      7. Analisis IA, o nota fail-safe si `analysis is None` (Req 5.4).
      8. Nota explicita USD sin impuestos (Req 3.7).
      9. Footer de copyright de Inversiones On Line S.A.C. en cada pagina (Req 3.8).

    Antes de componer valida la reconciliacion de montos (`validate_reconciliation`, task 6.2): si
    no reconcilia, anota la discrepancia en la seccion de resumen SIN alterar `header.amount`.

    Devuelve los `bytes` del PDF (empiezan con `%PDF`).
    """
    from fpdf import FPDF

    # Validación de reconciliación ANTES de componer (task 6.2). No altera header.amount.
    reconciliation = validate_reconciliation(header, items)

    # Rutas a los logos (relativas al módulo del servicio → app/static/*.png).
    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
    alwaysprint_logo = os.path.join(static_dir, "alwaysprint_logo.png")
    robles_logo = os.path.join(static_dir, "robles_ai_logo.png")

    class ClosureReportPDF(FPDF):
        """PDF con footer de copyright de Inversiones On Line S.A.C. en cada página (sección 9)."""

        def footer(self) -> None:
            self.set_y(-15)
            self.set_font("Helvetica", "I", 7)
            self.set_text_color(150, 150, 150)
            year = datetime.utcnow().year
            self.cell(
                0,
                10,
                f"(c) {year} Inversiones On Line S.A.C. - Todos los derechos reservados",
                align="C",
            )

    pdf = ClosureReportPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    effective_width = pdf.w - pdf.l_margin - pdf.r_margin

    # ==================================================================================
    # Sección 1 — Portada / header (logos, título, organización, periodo, modalidad, fecha)
    # ==================================================================================
    if os.path.exists(alwaysprint_logo):
        pdf.image(alwaysprint_logo, x=10, y=8, w=20)

    if os.path.exists(robles_logo):
        # Logo Robles.AI a la derecha + subtítulo "División de Automatización".
        pdf.image(robles_logo, x=155, y=8, w=35)
        pdf.set_font("Helvetica", "I", 6.5)
        pdf.set_text_color(100, 100, 100)
        pdf.set_xy(145, 19)
        pdf.cell(55, 3, _sanitize_latin1("Division de Automatizacion"), align="R")
    else:
        # Fallback textual si no está el asset.
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(100, 100, 100)
        pdf.set_xy(130, 10)
        pdf.cell(70, 4, "Robles.AI", align="R")

    # Título centrado.
    pdf.set_xy(10, 30)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, _sanitize_latin1("Reporte de Cierre Mensual - Sustento de Factura"), ln=True, align="C")
    pdf.ln(3)

    # Separador.
    pdf.set_draw_color(200, 200, 200)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(5)

    # ==================================================================================
    # Secciones 1(datos) y 2 — Dos columnas: "Datos del cierre" (izq) y "Resumen del cierre" (der)
    # ==================================================================================
    # Los metadatos del cierre (izquierda) y el resumen de totales/monto (derecha) se disponen
    # en dos columnas a la MISMA altura. Cada bloque tiene su propio título. La nota de
    # reconciliación (si el desglose no reconcilia) se dibuja debajo de ambas columnas, a todo
    # el ancho, como aviso.
    org_name = getattr(org, "name", None) or getattr(org, "id", "N/A")
    tipo_cierre = "Retroactivo" if header.is_retroactive else "Normal"

    _META_GUTTER = 6.0  # separación horizontal entre columnas (mm)
    meta_col_width = (effective_width - _META_GUTTER) / 2.0
    meta_left_x = pdf.l_margin
    meta_right_x = pdf.l_margin + meta_col_width + _META_GUTTER
    blocks_top_y = pdf.get_y()

    # --- Columna izquierda: "Datos del cierre" ---
    pdf.set_xy(meta_left_x, blocks_top_y)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(meta_col_width, 7, _sanitize_latin1("Datos del cierre"), ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(60, 60, 60)
    datos_lines = [
        f"Organizacion: {org_name}",
        f"Periodo: {_fmt_period(header)}",
        f"Modalidad: {header.mode}",
        f"Tipo de cierre: {tipo_cierre}",
        f"Generacion: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
    ]
    for line in datos_lines:
        pdf.set_x(meta_left_x)
        pdf.multi_cell(meta_col_width, 5, _sanitize_latin1(f"- {line}"))
    left_bottom_y = pdf.get_y()

    # --- Columna derecha: "Resumen del cierre" ---
    pdf.set_xy(meta_right_x, blocks_top_y)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(meta_col_width, 7, _sanitize_latin1("Resumen del cierre"), ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(60, 60, 60)
    resumen_lines = [
        f"Estaciones facturables: {header.total_billable}",
        f"Estaciones recicladas: {header.total_recycled}",
        f"Estaciones archivadas: {header.total_archived}",
        f"Monto total: USD {reconciliation.header_amount}",
        f"Tipo de cierre: {tipo_cierre}",
    ]
    for line in resumen_lines:
        pdf.set_x(meta_right_x)
        pdf.multi_cell(meta_col_width, 5, _sanitize_latin1(f"- {line}"))
    right_bottom_y = pdf.get_y()

    # Continuar debajo de la columna más alta.
    pdf.set_y(max(left_bottom_y, right_bottom_y))

    # Anotación de discrepancia de reconciliación (solo si NO reconcilia, task 6.2), a todo el ancho.
    if reconciliation.note:
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(180, 50, 50)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(effective_width, 5, _sanitize_latin1(reconciliation.note))
        pdf.set_text_color(60, 60, 60)

    pdf.ln(4)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(5)

    # ==================================================================================
    # Gráficos en dos columnas (Composición izquierda, Evolución derecha) — van ANTES de
    # conceptos/tarifas para dar contexto visual del consumo y su evolución.
    # ==================================================================================
    # Layout de dos columnas a la misma altura: cada gráfico ocupa ~48% del ancho efectivo,
    # con un gutter central. Los títulos se dibujan sobre cada columna a la misma `y`, y las
    # imágenes se colocan con `x` explícito y la MISMA `y` de tope. fpdf2 calcula la altura de
    # cada imagen por su aspect ratio (ambos PNG comparten figsize 7x4 → misma altura), de modo
    # que quedan alineados. Al final, el cursor avanza por debajo del gráfico más alto.
    from PIL import Image as _PILImage  # backend de imagen ya presente (matplotlib/fpdf2)

    _GUTTER = 6.0  # separación horizontal entre columnas (mm)
    col_width = (effective_width - _GUTTER) / 2.0
    left_x = pdf.l_margin
    right_x = pdf.l_margin + col_width + _GUTTER

    def _png_height_for_width(png_bytes: bytes, width_mm: float) -> float:
        """Altura (mm) que tendrá el PNG al escalarlo a `width_mm`, según su aspect ratio."""
        try:
            with _PILImage.open(io.BytesIO(png_bytes)) as im:
                w_px, h_px = im.size
            if w_px:
                return width_mm * (h_px / w_px)
        except Exception:
            pass
        # Fallback al aspect ratio de figsize (7x4) si no se pudo leer el PNG.
        return width_mm * (4.0 / 7.0)

    # Títulos de ambas columnas a la misma altura.
    titles_y = pdf.get_y()
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_xy(left_x, titles_y)
    pdf.cell(col_width, 7, _sanitize_latin1("Composicion de tramos"), align="C")
    pdf.set_xy(right_x, titles_y)
    pdf.cell(col_width, 7, _sanitize_latin1("Evolucion historica"), align="C")

    images_y = titles_y + 9  # debajo de los títulos
    left_h = 0.0
    right_h = 0.0
    if tiers_png:
        tiers_buf = io.BytesIO(tiers_png)
        tiers_buf.name = "tiers.png"
        left_h = _png_height_for_width(tiers_png, col_width)
        pdf.image(tiers_buf, x=left_x, y=images_y, w=col_width)
    if history_png:
        history_buf = io.BytesIO(history_png)
        history_buf.name = "history.png"
        right_h = _png_height_for_width(history_png, col_width)
        pdf.image(history_buf, x=right_x, y=images_y, w=col_width)

    # Avanzar el cursor por debajo del gráfico más alto y dibujar el separador.
    pdf.set_y(images_y + max(left_h, right_h) + 4)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(5)

    # ==================================================================================
    # Conceptos/tarifas/modalidad (izquierda, stacked) + Tabla de tramos (derecha, como tabla)
    # ==================================================================================
    # Dos columnas a la misma altura: a la izquierda las definiciones de conceptos, la modalidad
    # y la moneda; a la derecha la tabla del desglose por tramo (Desde/Hasta/Tarifa/IPs/Subtotal)
    # con su fila de total, que reconcilia con `header.amount` (fuente de verdad).
    tiers_applied = header.tiers_applied or []

    _INFO_GUTTER = 6.0
    info_col_width = (effective_width - _INFO_GUTTER) / 2.0
    info_left_x = pdf.l_margin
    info_right_x = pdf.l_margin + info_col_width + _INFO_GUTTER
    info_top_y = pdf.get_y()

    # --- Columna izquierda: Conceptos, tarifas y modalidad (stacked) ---
    pdf.set_xy(info_left_x, info_top_y)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(info_col_width, 7, _sanitize_latin1("Conceptos, tarifas y modalidad"), ln=True)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(60, 60, 60)
    conceptos = [
        "Facturable: estacion (IP privada) contabilizada para el cobro del periodo.",
        "Reciclado: estacion reutilizada dentro del ciclo; no genera cargo adicional.",
        "Archivado: estacion retirada/archivada; se conserva como sustento historico.",
        f"Modalidad aplicada: {header.mode}. Moneda: USD (sin impuestos).",
    ]
    for line in conceptos:
        pdf.set_x(info_left_x)
        pdf.multi_cell(info_col_width, 5, _sanitize_latin1(f"- {line}"))
    left_info_bottom_y = pdf.get_y()

    # --- Columna derecha: Tabla del desglose por tramo ---
    pdf.set_xy(info_right_x, info_top_y)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(info_col_width, 7, _sanitize_latin1("Desglose por tramo"), ln=True)

    # Anchos de columna de la tabla, proporcionales al ancho de la columna derecha.
    tbl_col_widths = [
        info_col_width * 0.16,  # Desde
        info_col_width * 0.16,  # Hasta
        info_col_width * 0.24,  # Tarifa
        info_col_width * 0.16,  # IPs
        info_col_width * 0.28,  # Subtotal
    ]
    tbl_headers = ["Desde", "Hasta", "Tarifa", "IPs", "Subtotal"]

    # Cabecera de la tabla.
    pdf.set_xy(info_right_x, info_top_y + 8)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(230, 230, 230)
    pdf.set_text_color(0, 0, 0)
    for width, title in zip(tbl_col_widths, tbl_headers):
        pdf.cell(width, 6, _sanitize_latin1(title), border=1, align="C", fill=True)
    pdf.ln(6)

    # Filas de tramos.
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(60, 60, 60)
    if tiers_applied:
        for tier in tiers_applied:
            if not isinstance(tier, dict):
                continue
            tier_from = tier.get("from")
            tier_to = tier.get("to")
            rate = tier.get("rate")
            ips_in_tier = tier.get("ips_in_tier", 0)
            subtotal = tier.get("subtotal")
            row = [
                str(tier_from if tier_from is not None else "-"),
                str(tier_to if tier_to is not None else "+"),
                str(rate),
                str(ips_in_tier),
                str(subtotal),
            ]
            pdf.set_x(info_right_x)
            for width, cell in zip(tbl_col_widths, row):
                pdf.cell(width, 6, _sanitize_latin1(cell), border=1, align="C")
            pdf.ln(6)
    else:
        pdf.set_x(info_right_x)
        pdf.cell(
            sum(tbl_col_widths),
            6,
            _sanitize_latin1("(sin tramos aplicados / monto 0.00)"),
            border=1,
            align="C",
        )
        pdf.ln(6)

    # Fila de total (reconcilia con header.amount, la fuente de verdad).
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(0, 0, 0)
    pdf.set_x(info_right_x)
    pdf.cell(sum(tbl_col_widths[:4]), 6, _sanitize_latin1("Total"), border=1, align="R")
    pdf.cell(tbl_col_widths[4], 6, _sanitize_latin1(f"USD {reconciliation.header_amount}"), border=1, align="C")
    pdf.ln(6)
    right_info_bottom_y = pdf.get_y()

    # Continuar debajo de la columna más alta y dibujar el separador.
    pdf.set_y(max(left_info_bottom_y, right_info_bottom_y))
    pdf.ln(2)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(5)

    # ==================================================================================
    # Sección 6b — Contingencia del ciclo (JUSTO DESPUÉS de conceptos/tramos, ANTES del IA)
    # ==================================================================================
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, _sanitize_latin1("Contingencia del ciclo"), ln=True)
    pdf.ln(2)

    if contingency is None or not contingency.data_available:
        # Fail-safe: métricas no disponibles → nota en cursiva gris, no bloquea el reporte.
        pdf.set_font("Helvetica", "I", 10)
        pdf.set_text_color(120, 120, 120)
        pdf.set_x(pdf.l_margin + 2)
        pdf.multi_cell(
            effective_width - 2,
            5,
            _sanitize_latin1("Metricas de contingencia no disponibles para este cierre."),
        )
    else:
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(60, 60, 60)
        forced_org_txt = "si" if contingency.forced_org else "no"
        contingency_lines = [
            f"Activaciones de contingencia en el mes: {contingency.activations_in_cycle} "
            f"(equipos distintos: {contingency.distinct_ws_activated})",
            f"Entradas masivas a nivel de agencia (VLAN): {contingency.mass_vlan_events}",
            f"Entradas masivas a nivel de organizacion: {contingency.mass_org_events}",
            f"Equipos en contingencia al cierre: {contingency.active_at_cutoff}",
            f"Contingencia forzada a nivel organizacion (activaciones): "
            f"{contingency.forced_org_activations}",
            f"Contingencia forzada a nivel agencia/VLAN (activaciones): "
            f"{contingency.forced_vlan_activations}",
            f"Salidas de contingencia en el mes (desactivaciones): "
            f"{contingency.deactivations_in_cycle}",
            f"Equipos afectados por activaciones forzadas (acumulado): "
            f"{contingency.forced_affected_ws_total}",
            f"Contingencia forzada vigente: organizacion={forced_org_txt}, "
            f"VLANs={contingency.forced_vlan_count}",
        ]
        for line in contingency_lines:
            pdf.set_x(pdf.l_margin + 2)
            pdf.multi_cell(effective_width - 2, 5, _sanitize_latin1(f"- {line}"))

    pdf.ln(2)
    pdf.set_text_color(60, 60, 60)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(5)

    # ==================================================================================
    # Sección 7 — Análisis IA (o nota fail-safe si no está disponible)
    # ==================================================================================
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, _sanitize_latin1("Analisis IA del consumo"), ln=True)
    pdf.ln(2)

    if analysis is None:
        # Fail-safe (Req 5.4): nota explícita, el reporte no se bloquea por ausencia de IA.
        pdf.set_font("Helvetica", "I", 10)
        pdf.set_text_color(120, 120, 120)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(effective_width, 5, _sanitize_latin1(_AI_FAILSAFE_NOTE))
    else:
        # Render del texto IA con soporte básico de markdown (encabezados / viñetas / negritas),
        # replicando el estilo de `debugging_analysis._generate_pdf`.
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(0, 0, 0)
        for raw_line in analysis.split("\n"):
            line = _sanitize_latin1(raw_line)
            pdf.set_x(pdf.l_margin)
            if line.startswith("## "):
                pdf.ln(3)
                pdf.set_font("Helvetica", "B", 13)
                pdf.multi_cell(effective_width, 6, line[3:])
                pdf.set_font("Helvetica", "", 11)
            elif line.startswith("### "):
                pdf.ln(2)
                pdf.set_font("Helvetica", "B", 11)
                pdf.multi_cell(effective_width, 6, line[4:])
                pdf.set_font("Helvetica", "", 11)
            elif line.startswith("**") and line.endswith("**") and len(line) > 4:
                pdf.set_font("Helvetica", "B", 11)
                pdf.multi_cell(effective_width, 6, line.strip("*"))
                pdf.set_font("Helvetica", "", 11)
            elif line.startswith("- ") or line.startswith("* "):
                pdf.set_x(pdf.l_margin + 4)
                pdf.multi_cell(effective_width - 4, 5, f"- {line[2:]}")
            elif line.strip() == "":
                pdf.ln(3)
            else:
                pdf.multi_cell(effective_width, 5, line)

    pdf.ln(4)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(5)

    # ==================================================================================
    # Sección 8 — Nota explícita USD sin impuestos (contenido obligatorio, Req 3.7)
    # ==================================================================================
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(0, 0, 0)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(effective_width, 5, _sanitize_latin1(_USD_DISCLAIMER))

    # Sección 9 (footer de copyright) se dibuja automáticamente en cada página vía footer().
    return bytes(pdf.output())
