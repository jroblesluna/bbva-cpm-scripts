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

Nota sobre matplotlib (headless + LAZY import):
    matplotlib NO se importa a nivel de módulo. Es una dependencia PESADA cuyo primer import
    reconstruye el font cache (fontManager) cuando el cachedir está frío, lo que penalizaba el
    ARRANQUE del backend (el router `billing_closures` importa este servicio en el startup). Por
    eso se difiere (lazy) al interior de las funciones de render mediante el helper `_get_pyplot()`,
    que fija el backend headless "Agg" en ese momento —ANTES de importar `pyplot`— para que no se
    intente abrir un display en el contenedor. Así el costo se paga sólo la primera vez que se
    RENDERIZA un gráfico (operación lenta y poco frecuente), no en cada arranque.
"""

import io
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import List, Optional

import boto3
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

# === ESTADÍSTICAS DE USO DE CONTINGENCIA (resumen para el reporte de cierre) ===
# El resumen se orienta a VALOR OPERATIVO: cuántas veces entró/salió la contingencia por nivel
# (organización, agencia/VLAN, workstation), cuánto tiempo estuvo "protegido" cada nivel y
# cuántas intervenciones manuales se ahorraron a la Mesa de Ayuda. Ya NO hay algoritmos de
# "ventana masiva" ni conteos con doble sumatoria: se reemplazan por pairing de intervalos
# ON→OFF (ver `_pair_protection_intervals` / `_count_paired_interventions`).


class ContingencySummary:
    """
    Estadísticas de uso de contingencia del ciclo de cierre (fail-safe, informativas).

    Objeto de resultado simple (sin estado ni efectos secundarios) que agrega el uso de
    contingencia reconstruido desde la auditoría (`audit_logs`) y el estado vigente de
    contingencia forzada (org/VLAN). Nunca afecta la factura: si algo falla al calcularlo, se
    devuelve un resumen en ceros con `data_available=False` (fail-safe).

    Distingue dos esquemas de `new_values` del mismo `ActionType.CONTINGENCY_TOGGLE`:
      A) Automático por-workstation: `{"contingency_active": bool}`, `workstation_id` poblado.
      B) Forzada manual: `{"forced_contingency": bool, "scope": "organization"|"vlan"|"workstation",
         "affected_workstations": int, ...}`, `workstation_id` NULL (id de la entidad en `entity_id`).

    Atributos:
        data_available: True si se pudo consultar la auditoría (fail-safe). False → todo en ceros.
        timezone: string IANA de la tz usada para formatear timestamps (org/closure, fallback "UTC").

        --- Nivel ORGANIZACIÓN (intervención masiva forzada, scope=organization) ---
        org_entries: eventos ON forzados scope=organization en el ciclo (entradas a contingencia).
        org_exits: eventos OFF forzados scope=organization en el ciclo (salidas).
        org_entry_datetimes: timestamps ISO de cada entrada ON org, YA convertidos a la tz de la org.
            (se mantiene por compatibilidad; el PDF ahora usa `org_intervals` para la cronología).
        org_intervals: cronología de TRAMOS de contingencia a nivel org (pairing ON→OFF con la
            MISMA semántica de `_pair_protection_intervals`, ver `_pair_org_intervals`). Cada
            elemento es un dict con:
              - start_iso: ISO tz-local del ON (entrada). None si el tramo venía abierto del mes
                anterior (OFF sin ON previo → arranca en cycle_start).
              - end_iso: ISO tz-local del OFF (salida). None si quedó abierto al cierre (ON sin OFF
                → se corta en cutoff).
              - duration_seconds: duración del tramo (int, >=0), con corte a cycle_start/cutoff.
              - open_at_start: True si el tramo venía en contingencia del mes anterior.
              - open_at_end: True si el tramo quedó vigente en contingencia al cierre.
            La suma de `duration_seconds` coincide por construcción con `org_protection_seconds`.
        org_protection_seconds: tiempo total (s) de estadía en contingencia a nivel org en el ciclo
            (pairing ON→OFF con corte a cycle_start/cutoff; ver `_pair_protection_intervals`).

        --- Nivel VLAN/AGENCIA (scope=vlan) ---
        vlan_entries: eventos ON forzados scope=vlan en el ciclo.
        vlan_exits: eventos OFF forzados scope=vlan en el ciclo.
        vlan_protection_seconds: suma de estadías (s) de TODAS las VLAN (pairing por entity_id).

        --- Nivel WORKSTATION (scope=workstation forzado, esquema B) + esquema A por-equipo ---
        ws_entries: ON scope=workstation forzados + activaciones esquema A (contingency_active=true).
        ws_exits: OFF scope=workstation forzados + desactivaciones esquema A (contingency_active=false).
        ws_auto_interventions: intervenciones EMPAREJADAS entrada→salida del esquema A
            (auto-proteccion local del cliente: la workstation entró/salió de contingencia
            AUTOMÁTICAMENTE). Estas SÍ AHORRAN un ticket/acción manual a la Mesa de Ayuda
            (el equipo se auto-protegió sin intervención). Un ON sin OFF NO cuenta
            (ver `_count_paired_interventions`).
        ws_remote_interventions: intervenciones EMPAREJADAS entrada→salida del esquema B
            scope=workstation (un operador FORZÓ contingencia REMOTA sobre el equipo desde el
            panel, source=manual_endpoint). NO ahorran una acción manual: SON la acción, pero
            ejecutada de forma remota, evitando el desplazamiento presencial (FACILITAN/agilizan
            la atención). Un ON sin OFF NO cuenta (ver `_count_paired_interventions`).

        --- Estado vigente + magnitud real ---
        forced_org_now: org.forced_contingency vigente (estado actual).
        forced_vlan_count_now: VLANs con forced_contingency=True vigentes (estado actual).
        max_affected_ws: MÁXIMO de affected_workstations entre los ON forzados del ciclo
            (magnitud real de la mayor intervención, NO la suma → evita el doble conteo previo).
    """

    def __init__(
        self,
        *,
        data_available: bool = True,
        timezone: str = "UTC",
        # Nivel organización.
        org_entries: int = 0,
        org_exits: int = 0,
        org_entry_datetimes: Optional[list] = None,
        org_intervals: Optional[list] = None,
        org_protection_seconds: int = 0,
        # Nivel VLAN/agencia.
        vlan_entries: int = 0,
        vlan_exits: int = 0,
        vlan_protection_seconds: int = 0,
        # Nivel workstation.
        ws_entries: int = 0,
        ws_exits: int = 0,
        ws_auto_interventions: int = 0,
        ws_remote_interventions: int = 0,
        # Estado vigente + magnitud real.
        forced_org_now: bool = False,
        forced_vlan_count_now: int = 0,
        max_affected_ws: int = 0,
    ) -> None:
        self.data_available = data_available
        self.timezone = timezone
        self.org_entries = org_entries
        self.org_exits = org_exits
        self.org_entry_datetimes = (
            org_entry_datetimes if org_entry_datetimes is not None else []
        )
        self.org_intervals = org_intervals if org_intervals is not None else []
        self.org_protection_seconds = org_protection_seconds
        self.vlan_entries = vlan_entries
        self.vlan_exits = vlan_exits
        self.vlan_protection_seconds = vlan_protection_seconds
        self.ws_entries = ws_entries
        self.ws_exits = ws_exits
        self.ws_auto_interventions = ws_auto_interventions
        self.ws_remote_interventions = ws_remote_interventions
        self.forced_org_now = forced_org_now
        self.forced_vlan_count_now = forced_vlan_count_now
        self.max_affected_ws = max_affected_ws

    def to_dict(self) -> dict:
        """Serializa el resumen a un dict plano (para construir schemas de respuesta)."""
        return {
            "data_available": self.data_available,
            "timezone": self.timezone,
            "org_entries": self.org_entries,
            "org_exits": self.org_exits,
            "org_entry_datetimes": self.org_entry_datetimes,
            "org_intervals": self.org_intervals,
            "org_protection_seconds": self.org_protection_seconds,
            "vlan_entries": self.vlan_entries,
            "vlan_exits": self.vlan_exits,
            "vlan_protection_seconds": self.vlan_protection_seconds,
            "ws_entries": self.ws_entries,
            "ws_exits": self.ws_exits,
            "ws_auto_interventions": self.ws_auto_interventions,
            "ws_remote_interventions": self.ws_remote_interventions,
            "forced_org_now": self.forced_org_now,
            "forced_vlan_count_now": self.forced_vlan_count_now,
            "max_affected_ws": self.max_affected_ws,
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
        Construye las estadísticas de uso de contingencia del ciclo del cierre (fail-safe).

        El ciclo es el intervalo `[cycle_start, cutoff)`, donde
        `cycle_start = datetime(period_year, period_month, 1)` (naive UTC, consistente con
        `AuditLog.created_at`) y `cutoff = closure.cutoff_at` (naive UTC).

        DOS ESQUEMAS de `new_values` del mismo `ActionType.CONTINGENCY_TOGGLE` (NO se toca el filtro):
          A) Automático por-workstation: `{"contingency_active": bool}`, `workstation_id` poblado.
          B) Forzada manual: `{"forced_contingency": bool, "scope": "organization"|"vlan"|"workstation",
             "affected_workstations": int, ...}`, `workstation_id` NULL; la entidad va en `entity_id`.

        Se calcula por NIVEL (organización / VLAN / workstation) orientado a valor operativo:
        - Ingresos/salidas (entries/exits) por nivel = conteo de eventos ON/OFF de ese scope.
        - Tiempo de PROTECCIÓN (protection_seconds) por nivel = pairing de intervalos ON→OFF
          (`_pair_protection_intervals`), con corte a `cycle_start` (OFF sin ON previo, venía del
          mes anterior) y a `cutoff` (ON sin OFF al cierre). VLAN se agrupa por `entity_id` y se
          suma. Nivel org agrupa todos los eventos B scope=organization.
        - Nivel workstation: `ws_entries`/`ws_exits` mezclan los ON/OFF scope=workstation forzados
          (esquema B, agrupados por `entity_id`/`workstation_id`) con las activaciones/
          desactivaciones esquema A (`contingency_active` true/false, agrupadas por `workstation_id`).
          Las intervenciones EMPAREJADAS entrada→salida (`_count_paired_interventions`) se separan
          por esquema en DOS acumuladores distintos: `ws_auto_events_by_id` (solo esquema A,
          auto-proteccion → `ws_auto_interventions`, AHORRAN un ticket) y `ws_remote_events_by_id`
          (solo esquema B scope=workstation, remotas manuales → `ws_remote_interventions`, SON la
          acción pero ejecutada remotamente, FACILITAN la atención sin visita presencial).
        - `max_affected_ws` = máximo `affected_workstations` entre los ON forzados del ciclo
          (magnitud real de la mayor intervención; NO la suma → evita el doble conteo previo).
        - `forced_org_now` / `forced_vlan_count_now`: estado vigente de contingencia forzada.
        - `timezone`: se resuelve `closure.timezone or org.timezone or "UTC"` (zoneinfo). Los
          timestamps de entrada org (`org_entry_datetimes`) se convierten naive-UTC → tz local.

        FAIL-SAFE: toda la lógica va en try/except; ante CUALQUIER excepción se registra un
        warning y se devuelve un `ContingencySummary(data_available=False)` (ceros). Nunca se
        propaga: el reporte no debe romperse por estas estadísticas.
        """
        from zoneinfo import ZoneInfo

        from app.models.audit import AuditLog, ActionType
        from app.models.vlan import VLAN

        try:
            cycle_start = datetime(closure.period_year, closure.period_month, 1)
            cutoff = closure.cutoff_at

            # --- Resolver la tz de formateo: closure.timezone -> org.timezone -> "UTC" ---
            tz_name = (
                getattr(closure, "timezone", None)
                or getattr(org, "timezone", None)
                or "UTC"
            )
            try:
                tz = ZoneInfo(tz_name)
            except Exception:
                # tz inválida → cae a UTC (fail-safe local, no rompe el resumen completo).
                tz_name = "UTC"
                tz = ZoneInfo("UTC")

            def _to_local_iso(dt_naive_utc: datetime) -> str:
                """Convierte un created_at naive-UTC a ISO en la tz resuelta."""
                return (
                    dt_naive_utc.replace(tzinfo=ZoneInfo("UTC"))
                    .astimezone(tz)
                    .isoformat()
                )

            # --- Toggles de la org en [cycle_start, cutoff) ordenados asc ---
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

            # Acumuladores por nivel.
            org_entries = 0
            org_exits = 0
            org_entry_datetimes: list = []
            org_events = []  # (created_at, is_on) del scope=organization (para pairing)

            vlan_entries = 0
            vlan_exits = 0
            vlan_events_by_id = {}  # entity_id -> list[(created_at, is_on)]

            ws_entries = 0
            ws_exits = 0
            # Separación por esquema para el pairing de intervenciones (entries/exits siguen sumando ambos).
            ws_auto_events_by_id = {}    # esquema A (key = workstation_id): auto-proteccion, AHORRAN ticket
            ws_remote_events_by_id = {}  # esquema B scope=workstation (key = workstation_id or entity_id): remotas

            max_affected_ws = 0

            for log in cycle_toggles:
                nv = log.new_values if isinstance(log.new_values, dict) else None
                if nv is None:
                    continue

                # --- Esquema B: contingencia forzada (source manual_endpoint) ---
                if ("forced_contingency" in nv) or (
                    nv.get("scope") in ("organization", "vlan", "workstation")
                ):
                    scope = nv.get("scope")
                    is_on = nv.get("forced_contingency") is True
                    is_off = nv.get("forced_contingency") is False
                    if is_on:
                        # Magnitud real de la mayor intervención (máximo, NO suma).
                        affected = int(nv.get("affected_workstations") or 0)
                        if affected > max_affected_ws:
                            max_affected_ws = affected

                    if scope == "organization":
                        if is_on:
                            org_entries += 1
                            org_entry_datetimes.append(_to_local_iso(log.created_at))
                            org_events.append((log.created_at, True))
                        elif is_off:
                            org_exits += 1
                            org_events.append((log.created_at, False))
                    elif scope == "vlan":
                        vlan_key = log.entity_id  # id de la VLAN (entity_id, ver vlans.py)
                        if is_on:
                            vlan_entries += 1
                            vlan_events_by_id.setdefault(vlan_key, []).append(
                                (log.created_at, True)
                            )
                        elif is_off:
                            vlan_exits += 1
                            vlan_events_by_id.setdefault(vlan_key, []).append(
                                (log.created_at, False)
                            )
                    elif scope == "workstation":
                        # Forzada REMOTA a nivel workstation (esquema B): agrupar por workstation_id
                        # si viene, si no por entity_id (id del equipo afectado). Estas SON acciones
                        # de la Mesa de Ayuda ejecutadas remotamente (NO ahorran un ticket).
                        ws_key = log.workstation_id or log.entity_id
                        if is_on:
                            ws_entries += 1
                            ws_remote_events_by_id.setdefault(ws_key, []).append(
                                (log.created_at, True)
                            )
                        elif is_off:
                            ws_exits += 1
                            ws_remote_events_by_id.setdefault(ws_key, []).append(
                                (log.created_at, False)
                            )
                    continue  # una fila del esquema B NUNCA cuenta como toggle por-equipo esquema A

                # --- Esquema A: toggle automático por-workstation (auto-proteccion, AHORRAN ticket) ---
                if "contingency_active" in nv:
                    ws_key = log.workstation_id
                    if nv.get("contingency_active") is True:
                        ws_entries += 1
                        ws_auto_events_by_id.setdefault(ws_key, []).append(
                            (log.created_at, True)
                        )
                    elif nv.get("contingency_active") is False:
                        ws_exits += 1
                        ws_auto_events_by_id.setdefault(ws_key, []).append(
                            (log.created_at, False)
                        )

            # --- Tiempo de protección a nivel organización (pairing ON→OFF) ---
            org_protection_seconds = self._pair_protection_intervals(
                org_events, cycle_start, cutoff
            )

            # --- Cronología de tramos org (misma semántica de pairing, tz-local) ---
            # `org_protection_seconds` sigue siendo la fuente de verdad del "Tiempo total";
            # por construcción sum(iv["duration_seconds"]) == org_protection_seconds.
            org_intervals = self._pair_org_intervals(
                org_events, cycle_start, cutoff, _to_local_iso
            )

            # --- Tiempo de protección a nivel VLAN: pairing por cada VLAN y suma ---
            vlan_protection_seconds = 0
            for _vlan_key, events in vlan_events_by_id.items():
                vlan_protection_seconds += self._pair_protection_intervals(
                    events, cycle_start, cutoff
                )

            # --- Intervenciones workstation EMPAREJADAS, separadas por esquema ---
            # Esquema A (auto-proteccion): AHORRAN un ticket a la Mesa de Ayuda.
            ws_auto_interventions = sum(
                self._count_paired_interventions(ev)
                for ev in ws_auto_events_by_id.values()
            )
            # Esquema B scope=workstation (remotas manuales): FACILITAN atencion sin visita presencial.
            ws_remote_interventions = sum(
                self._count_paired_interventions(ev)
                for ev in ws_remote_events_by_id.values()
            )

            # --- Contingencia forzada vigente (estado actual) ---
            forced_vlan_count_now = (
                db.query(VLAN)
                .filter(
                    VLAN.organization_id == org.id,
                    VLAN.forced_contingency.is_(True),
                )
                .count()
            )
            forced_org_now = bool(getattr(org, "forced_contingency", False))

            return ContingencySummary(
                data_available=True,
                timezone=tz_name,
                org_entries=org_entries,
                org_exits=org_exits,
                org_entry_datetimes=org_entry_datetimes,
                org_intervals=org_intervals,
                org_protection_seconds=org_protection_seconds,
                vlan_entries=vlan_entries,
                vlan_exits=vlan_exits,
                vlan_protection_seconds=vlan_protection_seconds,
                ws_entries=ws_entries,
                ws_exits=ws_exits,
                ws_auto_interventions=ws_auto_interventions,
                ws_remote_interventions=ws_remote_interventions,
                forced_org_now=forced_org_now,
                forced_vlan_count_now=forced_vlan_count_now,
                max_affected_ws=max_affected_ws,
            )
        except Exception as exc:
            # FAIL-SAFE: nunca propagar. Resumen en ceros con data_available=False.
            logger.warning(
                "[CLOSURE_REPORT] Estadisticas de contingencia no disponibles (fail-safe): %s",
                exc,
            )
            return ContingencySummary(data_available=False)

    @staticmethod
    def _pair_protection_intervals(events, cycle_start, cutoff) -> int:
        """
        Empareja eventos ON→OFF de UN scope/entidad y devuelve el total de segundos de protección.

        `events` es una lista de tuplas `(created_at, is_on: bool)` para UN scope/entidad. Se
        ordena asc y se recorre manteniendo un "abierto" (timestamp del ON sin cerrar). Reglas:
          * ON sin abierto → abre intervalo en ese ts.
          * ON con abierto → se ignora (re-activación redundante; NO reinicia el intervalo).
          * OFF con abierto → cierra [abierto, ts], suma (ts - abierto), limpia abierto.
          * OFF sin abierto → venía en contingencia del mes anterior → cierra [cycle_start, ts].
          * Al final, si queda un abierto (ON sin OFF en el ciclo) → cierra en [abierto, cutoff].

        Devuelve el total de segundos (int, >= 0). Los intervalos negativos (datos inconsistentes)
        se saturan a 0 para no restar tiempo de protección.
        """
        total_seconds = 0
        opened = None  # timestamp del ON abierto sin cerrar

        for created_at, is_on in sorted(events, key=lambda e: e[0]):
            if is_on:
                if opened is None:
                    opened = created_at
                # con abierto → re-activación redundante: ignorar (no reinicia).
            else:  # OFF
                if opened is not None:
                    delta = (created_at - opened).total_seconds()
                    if delta > 0:
                        total_seconds += int(delta)
                    opened = None
                else:
                    # OFF sin ON previo: contingencia heredada del mes anterior.
                    delta = (created_at - cycle_start).total_seconds()
                    if delta > 0:
                        total_seconds += int(delta)

        # ON sin OFF al cierre → se corta en cutoff.
        if opened is not None:
            delta = (cutoff - opened).total_seconds()
            if delta > 0:
                total_seconds += int(delta)

        return max(0, total_seconds)

    @staticmethod
    def _pair_org_intervals(events, cycle_start, cutoff, to_iso) -> list:
        """
        Empareja eventos ON→OFF a nivel organización y devuelve la CRONOLOGÍA de tramos.

        Comparte EXACTAMENTE la semántica de emparejado de `_pair_protection_intervals` (no la
        modifica), pero en lugar de devolver solo el total de segundos, devuelve la LISTA de
        tramos individuales para dibujar la tabla cronológica del PDF. Por construcción, la suma
        de `duration_seconds` de todos los tramos coincide con `_pair_protection_intervals`.

        `events` es una lista de tuplas `(created_at naive-UTC, is_on: bool)` del scope=organization.
        `to_iso` es un callable que convierte un `datetime` naive-UTC a ISO en la tz local (mismo
        patrón que `_to_local_iso` usado para `org_entry_datetimes`). Reglas de emparejado:
          * ON sin abierto → abre tramo (start = ese ts).
          * ON con abierto → se ignora (re-activación redundante; NO reinicia el tramo).
          * OFF con abierto → cierra [start, ts]; open_at_start=False, open_at_end=False.
          * OFF sin abierto → tramo heredado del mes anterior → start=cycle_start
            (open_at_start=True), end=ts, duración = ts - cycle_start.
          * Al final, si queda un abierto (ON sin OFF) → end=cutoff (open_at_end=True),
            duración = cutoff - start.

        Cada tramo es un dict:
          {start_iso, end_iso, duration_seconds (>=0), open_at_start, open_at_end}.
        Las duraciones negativas (datos inconsistentes) se saturan a 0.
        """
        intervals: list = []
        opened = None  # timestamp del ON abierto sin cerrar

        for created_at, is_on in sorted(events, key=lambda e: e[0]):
            if is_on:
                if opened is None:
                    opened = created_at
                # con abierto → re-activación redundante: ignorar (no reinicia).
            else:  # OFF
                if opened is not None:
                    delta = (created_at - opened).total_seconds()
                    intervals.append(
                        {
                            "start_iso": to_iso(opened),
                            "end_iso": to_iso(created_at),
                            "duration_seconds": max(0, int(delta)),
                            "open_at_start": False,
                            "open_at_end": False,
                        }
                    )
                    opened = None
                else:
                    # OFF sin ON previo: contingencia heredada del mes anterior (arranca en cycle_start).
                    delta = (created_at - cycle_start).total_seconds()
                    intervals.append(
                        {
                            "start_iso": None,
                            "end_iso": to_iso(created_at),
                            "duration_seconds": max(0, int(delta)),
                            "open_at_start": True,
                            "open_at_end": False,
                        }
                    )

        # ON sin OFF al cierre → tramo vigente, se corta en cutoff.
        if opened is not None:
            delta = (cutoff - opened).total_seconds()
            intervals.append(
                {
                    "start_iso": to_iso(opened),
                    "end_iso": None,
                    "duration_seconds": max(0, int(delta)),
                    "open_at_start": False,
                    "open_at_end": True,
                }
            )

        return intervals

    @staticmethod
    def _count_paired_interventions(events) -> int:
        """
        Cuenta intervenciones EMPAREJADAS entrada→salida (ON→OFF) de UN equipo.

        Variante de `_pair_protection_intervals` que, en lugar de sumar segundos, CUENTA cuántos
        ON obtienen su OFF (intervalos cerrados). Un ON abierto al final del ciclo NO cuenta como
        intervención completada. Un OFF sin ON previo tampoco suma (no hubo entrada dentro del
        ciclo que emparejar). Cada par cerrado equivale a una acción manual ahorrada a la Mesa
        de Ayuda.
        """
        interventions = 0
        opened = False

        for _created_at, is_on in sorted(events, key=lambda e: e[0]):
            if is_on:
                # ON con abierto → re-activación redundante: no abre un nuevo par.
                opened = True
            else:  # OFF
                if opened:
                    interventions += 1
                    opened = False
                # OFF sin abierto → no hay entrada que emparejar dentro del ciclo.

        return interventions

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

        Si `contingency` viene y tiene `data_available`, se agrega una sección con las ESTADÍSTICAS
        DE USO de contingencia del ciclo (ingresos/salidas y tiempo de protección por nivel org y
        agencia/VLAN, intervenciones workstation emparejadas, y magnitud de la mayor intervención)
        y se pide EXPLÍCITAMENTE que en las observaciones ESTIME las acciones y tickets ahorrados a
        la Mesa de Ayuda gracias a la entrada/salida de contingencia automatizada y masiva, además
        del valor del tiempo de protección a nivel organización. Si es `None` o no hay datos, la
        sección se omite (compatibilidad hacia atrás).
        """
        sections: List[str] = []

        # Contexto/rol del modelo y reglas de tono y moneda.
        sections.append(
            "Eres un analista de consumo y facturacion de servicios de impresion corporativa. "
            "Redacta en espanol, con tono profesional y objetivo, sin exagerar hallazgos. "
            "Todos los precios estan expresados en dolares americanos (USD) y NO incluyen impuestos. "
            "IMPORTANTE: la unidad de facturacion es la ESTACION IP (una IP privada / workstation "
            "contabilizada), NO impresiones, paginas ni copias. Los tramos de tarifa se aplican "
            "sobre la CANTIDAD DE ESTACIONES IP facturables del periodo. Nunca describas los tramos "
            "como impresiones o paginas."
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
            "## Desglose de tramos por estaciones IP del mes objetivo\n" + self._format_tiers(header.tiers_applied)
        )

        # Estadísticas de uso de contingencia del ciclo (opcional; solo si hay datos disponibles).
        if contingency is not None and contingency.data_available:
            org_protection_hours = round(contingency.org_protection_seconds / 3600.0, 1)
            vlan_protection_hours = round(contingency.vlan_protection_seconds / 3600.0, 1)
            sections.append(
                "## Estadisticas de uso de contingencia del ciclo\n"
                f"- Ingresos a contingencia a nivel organizacion (intervencion masiva): "
                f"{contingency.org_entries}\n"
                f"- Salidas de contingencia a nivel organizacion: {contingency.org_exits}\n"
                f"- Tiempo de proteccion a nivel organizacion: {org_protection_hours} horas\n"
                f"- Ingresos a contingencia a nivel agencia/VLAN: {contingency.vlan_entries}\n"
                f"- Salidas de contingencia a nivel agencia/VLAN: {contingency.vlan_exits}\n"
                f"- Tiempo de proteccion a nivel agencia/VLAN: {vlan_protection_hours} horas\n"
                f"- Intervenciones AUTOMATIZADAS a nivel workstation (auto-proteccion, evitan/ahorran "
                f"un ticket a la Mesa de Ayuda): {contingency.ws_auto_interventions}\n"
                f"- Intervenciones REMOTAS a nivel workstation (ejecutadas por la Mesa de Ayuda desde "
                f"el panel, sin desplazamiento presencial): {contingency.ws_remote_interventions}\n"
                f"- Equipos afectados en la mayor intervencion: {contingency.max_affected_ws}\n"
                f"- Contingencia forzada vigente: organizacion={contingency.forced_org_now}, "
                f"VLANs={contingency.forced_vlan_count_now}"
            )

        # Solicitud concreta de las tres secciones en español.
        observaciones_extra = ""
        if contingency is not None and contingency.data_available:
            observaciones_extra = (
                " En las observaciones DISTINGUE CLARAMENTE dos tipos de intervencion a nivel "
                "workstation, con semantica distinta: (a) las intervenciones AUTOMATIZADAS "
                "(esquema de auto-proteccion) AHORRAN un ticket/accion a la Mesa de Ayuda porque el "
                "equipo se auto-protegio SIN intervencion humana; ESTIMA e indica EXPLICITAMENTE los "
                "tickets/acciones ahorrados con estas. (b) Las intervenciones REMOTAS son acciones "
                "que la Mesa de Ayuda SI ejecuto, pero de forma REMOTA desde el panel, evitando el "
                "desplazamiento presencial; NO las cuentes como tickets ahorrados sino como atencion "
                "remota eficiente: describe el BENEFICIO OPERATIVO (resolucion sin visita presencial, "
                "menor tiempo de atencion). Comenta ademas el valor del tiempo de proteccion a nivel "
                "organizacion (cuanto tiempo estuvo el servicio de impresion resguardado por la "
                "contingencia)."
            )
            # Si hubo contingencia forzada a nivel organizacion en el ciclo, destaca su valor:
            # el ruteo pasa a ser directo (bypass del flujo CPM/Linux), sin generar nuevos tickets.
            if contingency.org_entries > 0:
                observaciones_extra += (
                    " Ademas, DESTACA que al activarse la contingencia a nivel ORGANIZACION la "
                    "impresion pasa a ser DIRECTA (bypass del flujo normal CPM/Linux), por lo que "
                    "durante ese periodo NO se generan nuevos tickets de impresion y el servicio "
                    "sigue operativo sin intervencion de la Mesa de Ayuda. RECOMIENDA, para que el "
                    "usuario identifique rapidamente ese enrutamiento directo, mantener "
                    "correctamente asignadas las impresoras disponibles como parte de la AGENCIA y "
                    "las impresoras FAVORITAS por usuario."
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
                f"- Tramo {rango} estaciones IP: tarifa=USD {rate}, "
                f"estaciones_ip={ips_in_tier}, subtotal=USD {subtotal}"
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


def _get_pyplot():
    """
    Importa matplotlib.pyplot de forma LAZY (perezosa), fijando el backend headless "Agg".

    matplotlib es una dependencia PESADA cuyo primer import reconstruye el font cache
    (fontManager) si el cachedir esta frio; hacerlo a nivel de modulo penalizaba el arranque
    del backend (el router billing_closures importa este servicio en el startup). Al diferirlo
    aca, el costo se paga solo la primera vez que se RENDERIZA un grafico (operacion lenta y
    poco frecuente), no en cada arranque. Se fija "Agg" ANTES de importar pyplot (sin display
    en contenedor).
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


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


# === HELPERS DE ESTILO DE GRÁFICOS (funciones puras, sin estado, headless-safe) ===
#
# Estos helpers dan un look corporativo "elegante" a los charts (relieve 3D sutil + gradiente
# de fondo suave) sin tocar NADA de la lógica de datos. Son robustos bajo el backend "Agg"
# (headless) y no interfieren con el guardado a PNG: el gradiente de fondo se dibuja con
# `imshow` en `zorder=0` y las barras se pintan por encima (`zorder>=2`).

# Paleta corporativa (hex) reutilizada por los helpers y los render_*.
_CHART_BLUE = "#2563eb"        # azul primario AlwaysPrint
_CHART_BLUE_DARK = "#1e3a8a"   # azul oscuro (base del gradiente / anotaciones)
_CHART_GREEN = "#16a34a"       # verde monto
_CHART_SHADOW = "#cbd5e1"      # gris de la barra sombra (relieve)
_CHART_GRID = "#e2e8f0"        # gris grilla horizontal
_CHART_SPINE = "#cbd5e1"       # gris spines izq/inf
_CHART_TEXT = "#1e293b"        # gris texto de títulos/labels
_CHART_BG_SOFT = "#f1f5f9"     # gris fondo suave (parte baja del gradiente)


def _hex_to_rgb01(hex_color: str) -> tuple:
    """Convierte '#rrggbb' a una tupla (r, g, b) en el rango 0..1 (para arrays de gradiente)."""
    h = hex_color.lstrip("#")
    return tuple(int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))


def _style_axes(ax, fig) -> None:
    """
    Aplica el look elegante a un `Axes`: gradiente de fondo muy suave, spines sobrios y grilla fina.

    - Fondo del área de plot: gradiente vertical claro (#ffffff arriba -> #f1f5f9 abajo) dibujado
      con `imshow` en `zorder=0` y `aspect="auto"`, clip-eado a los límites del `Axes`. Si algo
      falla al construirlo, cae a un `set_facecolor("#f8fafc")` (fail-safe: nunca rompe el render).
    - Spines: se ocultan top/right; left/bottom quedan en gris #cbd5e1.
    - Grilla horizontal fina (#e2e8f0) por debajo de las barras (`zorder=0`).
    - Tipografía de títulos/labels en #1e293b (los títulos en bold los fija cada render_*).
    - Fondo de la figura en blanco.

    Es puramente estético: no toca datos ni límites de datos (el gradiente se re-encaja a los
    límites vigentes al momento de llamarlo, por eso conviene invocarlo tras dibujar las series).
    """
    fig.patch.set_facecolor("white")

    # Gradiente de fondo suave detrás de todo (zorder=0). Fail-safe a facecolor plano.
    try:
        import numpy as np

        top_rgb = _hex_to_rgb01("#ffffff")
        bot_rgb = _hex_to_rgb01(_CHART_BG_SOFT)
        # Rampa vertical (256 filas): fila 0 arriba (blanco), última abajo (gris suave).
        ramp = np.linspace(0.0, 1.0, 256).reshape(-1, 1)
        grad = np.empty((256, 1, 3), dtype=float)
        for ch in range(3):
            grad[:, 0, ch] = top_rgb[ch] + (bot_rgb[ch] - top_rgb[ch]) * ramp[:, 0]

        x0, x1 = ax.get_xlim()
        y0, y1 = ax.get_ylim()
        ax.imshow(
            grad,
            extent=(x0, x1, y0, y1),
            aspect="auto",
            origin="upper",
            zorder=0,
            interpolation="bilinear",
        )
        # imshow reajusta los límites; restaurarlos para no alterar el encuadre de las series.
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
    except Exception:
        ax.set_facecolor("#f8fafc")

    # Spines sobrios: sin top/right; left/bottom en gris.
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_visible(True)
        ax.spines[side].set_color(_CHART_SPINE)

    # Grilla horizontal fina por debajo de las series.
    ax.grid(axis="y", color=_CHART_GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)

    # Tipografía de ticks/labels en gris oscuro corporativo.
    ax.tick_params(colors=_CHART_TEXT, labelsize=8)
    ax.xaxis.label.set_color(_CHART_TEXT)
    ax.yaxis.label.set_color(_CHART_TEXT)


def _gradient_bars(ax, x_positions, heights, width, base_color, dark_color):
    """
    Dibuja barras con gradiente vertical (oscuro abajo -> claro arriba) + sombra para relieve 3D.

    Enfoque robusto y headless-safe:
      1. Una barra "sombra" gris (#cbd5e1) ligeramente desplazada a la derecha/abajo (zorder=2,
         alpha 0.5) para dar sensación de profundidad.
      2. La barra real dibujada con `imshow` de un gradiente vertical clip-eado al rectángulo de
         cada barra (zorder=3), `aspect="auto"`. Si numpy/imshow fallan, cae a una barra plana
         `ax.bar(color=base_color, zorder=3)` (fail-safe: nunca rompe el guardado a PNG).
      3. Un borde superior más oscuro (dark_color) sobre cada barra para acentuar el relieve.

    `x_positions` son los centros de barra (0..N-1), `heights` las alturas (valores), `width` el
    ancho de barra. Devuelve la lista de centros x (para que el llamador anote los valores).
    Función pura: no fija título/labels ni cierra la figura.
    """
    x_positions = list(x_positions)
    heights = [float(h) for h in heights]

    # Sombra de relieve: barra gris desplazada ligeramente (relleno plano, semi-transparente).
    x0, x1 = ax.get_xlim() if ax.has_data() else (0, 1)
    span = (x1 - x0) or 1.0
    dx = width * 0.10  # desplazamiento horizontal de la sombra
    ax.bar(
        [x + dx for x in x_positions],
        heights,
        width=width,
        color=_CHART_SHADOW,
        alpha=0.5,
        zorder=2,
        edgecolor="none",
    )

    used_gradient = False
    try:
        import numpy as np

        base_rgb = _hex_to_rgb01(base_color)
        dark_rgb = _hex_to_rgb01(dark_color)
        # Rampa vertical: arriba (fila 0) = base_color claro; abajo (última fila) = dark_color.
        ramp = np.linspace(0.0, 1.0, 256).reshape(-1, 1)
        grad = np.empty((256, 1, 3), dtype=float)
        for ch in range(3):
            grad[:, 0, ch] = base_rgb[ch] + (dark_rgb[ch] - base_rgb[ch]) * ramp[:, 0]

        for x, h in zip(x_positions, heights):
            if h <= 0:
                continue
            left = x - width / 2.0
            im = ax.imshow(
                grad,
                extent=(left, left + width, 0, h),
                aspect="auto",
                origin="upper",
                zorder=3,
                interpolation="bilinear",
            )
            # Clip al rectángulo de la barra (por si imshow desborda por interpolación).
            im.set_clip_on(True)
        used_gradient = True
    except Exception:
        used_gradient = False

    if not used_gradient:
        # Fail-safe: barras planas de color base por encima de la sombra.
        ax.bar(
            x_positions,
            heights,
            width=width,
            color=base_color,
            zorder=3,
            edgecolor="none",
        )

    # Borde superior más oscuro para acentuar el relieve 3D.
    for x, h in zip(x_positions, heights):
        if h <= 0:
            continue
        ax.plot(
            [x - width / 2.0, x + width / 2.0],
            [h, h],
            color=dark_color,
            linewidth=1.5,
            zorder=4,
            solid_capstyle="round",
        )

    return x_positions


def _placeholder_png(message: str) -> bytes:
    """
    Genera un PNG mínimo con un texto centrado (sin ejes) usado como degradación elegante.

    Se emplea cuando no hay datos que graficar (p. ej. "sin IPs facturables"): produce un
    artefacto válido y no vacío para que la composición del PDF nunca falle por falta de datos.
    """
    plt = _get_pyplot()  # import LAZY de matplotlib.pyplot (no penaliza el arranque del backend)
    fig = plt.figure(figsize=(6, 3.5))
    try:
        ax = fig.add_subplot(111)
        ax.set_facecolor("#f8fafc")  # combina con el fondo suave de los charts elegantes
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

    plt = _get_pyplot()  # import LAZY de matplotlib.pyplot (no penaliza el arranque del backend)
    fig = plt.figure(figsize=(7, 4))
    try:
        ax = fig.add_subplot(111)

        # Posiciones numéricas de barra (0..N-1) para el gradiente/relieve; etiquetas categóricas.
        x_positions = list(range(len(values)))
        bar_width = 0.6

        # Fijar límites ANTES del gradiente de fondo para que _style_axes encuadre bien.
        ax.set_xlim(-0.5, len(values) - 0.5)
        ax.set_ylim(0, max(values) * 1.15 if values else 1)

        # Barras con gradiente vertical + relieve 3D (azul primario -> azul oscuro).
        _gradient_bars(
            ax, x_positions, values, bar_width, _CHART_BLUE, _CHART_BLUE_DARK
        )

        ax.set_xticks(x_positions)
        ax.set_xticklabels(labels)
        ax.set_title(
            "Composición de estaciones IP facturables por tramo",
            fontweight="bold",
            color=_CHART_TEXT,
        )
        ax.set_xlabel("Tramo (rango de estaciones IP)")
        ax.set_ylabel("Estaciones IP facturables")

        # Anotar el valor sobre cada barra (bold, azul oscuro).
        for x, value in zip(x_positions, values):
            ax.annotate(
                str(value),
                xy=(x, value),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=9,
                fontweight="bold",
                color=_CHART_BLUE_DARK,
                zorder=5,
            )

        # Look elegante (gradiente de fondo, spines sobrios, grilla fina) tras dibujar las series.
        _style_axes(ax, fig)

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

    plt = _get_pyplot()  # import LAZY de matplotlib.pyplot (no penaliza el arranque del backend)
    fig = plt.figure(figsize=(7, 4))
    try:
        ax_bill = fig.add_subplot(111)

        if len(points) == 1:
            # Render mínimo: un solo ciclo. Marcador único (borde blanco) para facturables + monto.
            ax_bill.plot(
                labels,
                billable,
                marker="o",
                markersize=10,
                color=_CHART_BLUE,
                markeredgecolor="white",
                markeredgewidth=1.2,
                linestyle="None",
                label="Estaciones facturables",
                zorder=4,
            )
            ax_bill.set_ylabel("Estaciones facturables", color=_CHART_BLUE)
            ax_bill.margins(x=0.5, y=0.3)

            # Look elegante para el eje principal (fondo/spines/grilla).
            _style_axes(ax_bill, fig)

            ax_amount = ax_bill.twinx()
            ax_amount.plot(
                labels,
                amounts,
                marker="s",
                markersize=9,
                color=_CHART_GREEN,
                markeredgecolor="white",
                markeredgewidth=1.2,
                linestyle="None",
                label="Monto (USD)",
                zorder=4,
            )
            ax_amount.set_ylabel("Monto (USD)", color=_CHART_GREEN)
            # No duplicar grilla en el eje secundario.
            ax_amount.grid(False)

            ax_bill.set_title(
                "Evolución histórica", fontweight="bold", color=_CHART_TEXT
            )
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
                color=_CHART_TEXT,
            )
        else:
            # Serie completa: barras (facturables, gradiente/relieve) + línea (monto) en eje 2rio.
            x_positions = list(range(len(billable)))
            bar_width = 0.6

            ax_bill.set_xlim(-0.5, len(billable) - 0.5)
            ax_bill.set_ylim(0, max(billable) * 1.15 if billable else 1)

            _gradient_bars(
                ax_bill, x_positions, billable, bar_width, _CHART_BLUE, _CHART_BLUE_DARK
            )
            ax_bill.set_xticks(x_positions)
            ax_bill.set_xticklabels(labels)
            ax_bill.set_ylabel("Estaciones facturables", color=_CHART_BLUE)
            ax_bill.set_xlabel("Periodo (YYYY-MM)")

            # Look elegante para el eje principal ANTES de la línea de monto.
            _style_axes(ax_bill, fig)

            ax_amount = ax_bill.twinx()
            ax_amount.plot(
                x_positions,
                amounts,
                marker="o",
                markersize=6,
                color=_CHART_GREEN,
                linewidth=2.5,
                markeredgecolor="white",
                markeredgewidth=1.2,
                label="Monto (USD)",
                zorder=5,
            )
            ax_amount.set_ylabel("Monto (USD)", color=_CHART_GREEN)
            # No duplicar grilla en el eje secundario (monto).
            ax_amount.grid(False)

            ax_bill.set_title(
                "Evolución histórica de estaciones facturables y monto",
                fontweight="bold",
                color=_CHART_TEXT,
            )

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


def _fmt_money(value: object) -> str:
    """
    Formatea un importe SIEMPRE con exactamente 2 decimales (presentación).

    Reutiliza `_to_decimal` para parsear de forma tolerante y `_quantize_half_up` con
    `_HEADER_QUANTIZE` (half-up a 2 decimales), replicando el redondeo de la cabecera. Ante
    cualquier valor no parseable devuelve "0.00" (fail-safe). NO altera valores usados en la
    reconciliación: es solo formateo de presentación (ej. 0.5 -> "0.50", 228.8 -> "228.80").
    """
    try:
        return str(_quantize_half_up(_to_decimal(value), _HEADER_QUANTIZE))
    except Exception:
        return "0.00"


def _fmt_closure_date(header, org) -> str:
    """
    Devuelve la "Fecha de cierre" como el primer instante del mes SIGUIENTE al periodo.

    El cierre corresponde al periodo `header.period_year`/`header.period_month`; la fecha de
    cierre es el día 1 del mes siguiente a las 00:00 hora LOCAL de la organizacion (no se
    convierte desde UTC: los 00:00 ya son hora local). La tz se resuelve igual que en
    `_summarize_contingency`: `header.timezone -> org.timezone -> "UTC"` (aqui el `header` ES
    el closure). Formato de salida: `YYYY-MM-DD HH:MM (<tz_name>)`, p.ej.
    `2026-06-01 00:00 (America/Lima)`.

    Fail-safe: ante cualquier excepción devuelve el periodo siguiente en UTC sin romper.
    """
    try:
        year = int(getattr(header, "period_year"))
        month = int(getattr(header, "period_month"))
        if month == 12:
            next_year, next_month = year + 1, 1
        else:
            next_year, next_month = year, month + 1

        tz_name = (
            getattr(header, "timezone", None)
            or getattr(org, "timezone", None)
            or "UTC"
        )
        # Validar que la tz exista (fail-safe → "UTC" si es inválida o ausente).
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(tz_name)
        except Exception:
            tz_name = "UTC"

        # Instante naive en hora local de la org (00:00 del mes siguiente). NO se convierte
        # desde UTC: los 00:00 ya representan hora local de la organizacion.
        closure_dt = datetime(next_year, next_month, 1, 0, 0, 0)
        return f"{closure_dt.strftime('%Y-%m-%d %H:%M')} ({tz_name})"
    except Exception:
        # Fallback duro: intenta al menos el periodo siguiente en UTC.
        try:
            year = int(getattr(header, "period_year"))
            month = int(getattr(header, "period_month"))
            if month == 12:
                next_year, next_month = year + 1, 1
            else:
                next_year, next_month = year, month + 1
            return f"{next_year:04d}-{next_month:02d}-01 00:00 (UTC)"
        except Exception:
            return "-"


def _split_bold_segments(text: str) -> list:
    """
    Segmenta `text` en pares (fragmento, es_negrita) alternando por marcadores `**`.

    Enfoque mínimo sin dependencias: divide por `**` y marca en negrita los segmentos en
    posición impar (los que quedan ENTRE pares de `**`). Garantiza que ningún fragmento de
    salida contiene `**`. Ejemplos:
      - "1. **Resumen ejecutivo:**" -> [("1. ", False), ("Resumen ejecutivo:", True)]
      - "sin negrita"               -> [("sin negrita", False)]
      - "a **b** c **d**"           -> [("a ", False), ("b", True), (" c ", False), ("d", True)]

    Los segmentos vacíos se descartan. Si hay un número impar de `**` (marcador sin cerrar),
    el resto se trata como texto normal para no perder contenido.
    """
    if not text:
        return []
    parts = text.split("**")
    segments = []
    for index, part in enumerate(parts):
        if part == "":
            continue
        is_bold = index % 2 == 1
        segments.append((part, is_bold))
    return segments


def _render_inline_md(pdf, text, width, height, base_size=11) -> None:
    """
    Renderiza una línea con negrita inline `**...**` usando `pdf.write` (fpdf2).

    Segmenta con `_split_bold_segments` y pinta cada fragmento cambiando la fuente a "B" para
    los segmentos en negrita y "" para el resto, todo en la misma línea; termina con un salto
    de línea (`ln`). Así ningún `**` queda como texto literal en el PDF. Restaura la fuente
    normal al final.
    """
    for fragment, is_bold in _split_bold_segments(text):
        pdf.set_font("Helvetica", "B" if is_bold else "", base_size)
        pdf.write(height, fragment)
    pdf.set_font("Helvetica", "", base_size)
    pdf.ln(height)


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


def _fmt_hm(total_seconds: int) -> str:
    """
    Formatea una duración en segundos a "Xh Ym" (p. ej. 3661 -> "1h 1m"; 0 -> "0h 0m").

    Los segundos residuales se truncan (solo horas y minutos completos), suficiente para el
    reporte. Valores negativos o no numéricos se saturan a "0h 0m" (defensivo).
    """
    try:
        secs = int(total_seconds)
    except (TypeError, ValueError):
        secs = 0
    if secs < 0:
        secs = 0
    hours = secs // 3600
    minutes = (secs % 3600) // 60
    return f"{hours}h {minutes}m"


def _fmt_entry_datetime(iso_dt: str) -> str:
    """
    Formatea una fecha ISO de entrada a contingencia para lectura humana.

    Entrada típica: "2026-08-27T08:48:49.372716-05:00" → salida "2026-08-27 08:48:49 (UTC-05:00)".
    Parseo defensivo con `datetime.fromisoformat`; si falla, recorta los microsegundos y sustituye
    la "T" por un espacio sobre el string tal cual (no propaga la excepción).
    """
    raw = str(iso_dt)
    try:
        dt = datetime.fromisoformat(raw)
        base = dt.strftime("%Y-%m-%d %H:%M:%S")
        offset = dt.utcoffset()
        if offset is None:
            return base
        # Offset a "(UTC±HH:MM)".
        total_min = int(offset.total_seconds() // 60)
        sign = "+" if total_min >= 0 else "-"
        total_min = abs(total_min)
        return f"{base} (UTC{sign}{total_min // 60:02d}:{total_min % 60:02d})"
    except Exception:
        # Fallback: recortar microsegundos (".######") y cambiar la "T" por espacio.
        trimmed = raw
        if "." in trimmed:
            head, _, tail = trimmed.partition(".")
            # Conservar el offset de zona que va tras los microsegundos (ej. "-05:00").
            offset_part = ""
            for marker in ("+", "-"):
                idx = tail.find(marker)
                if idx != -1:
                    offset_part = tail[idx:]
                    break
            trimmed = f"{head}{(' ' + offset_part) if offset_part else ''}"
        return trimmed.replace("T", " ")


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
      6b. Contingencia del ciclo: TABLA de estadisticas de uso (ingresos/salidas y tiempo de
          proteccion por nivel org y agencia/VLAN, intervenciones workstation emparejadas, mayor
          intervencion y contingencia forzada vigente), mas la CRONOLOGIA de tramos de contingencia
          a nivel org en la tz de la org (tabla con cada ENTRADA en ambar y cada SALIDA en verde,
          la duracion por tramo y una fila de TIEMPO TOTAL == org_protection_seconds; o nota
          fail-safe si `contingency is None` o no hay datos). Va JUSTO DESPUES de
          conceptos/tarifas + tabla de tramos y ANTES del analisis IA.
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
        """
        PDF con cabecera de marca en TODAS las páginas (banda azul corporativa) y footer de
        copyright de Inversiones On Line S.A.C. en cada página (sección 9).

        `header()`/`footer()` los invoca fpdf2 automáticamente dentro de `add_page()`, por lo
        que los atributos de instancia que consume `header()` (`report_org_name`,
        `report_period`, `report_logo_path`) deben setearse ANTES del primer `add_page()`. El
        header los lee de forma defensiva con `getattr`: si faltan, dibuja solo la banda.
        """

        def header(self) -> None:
            # Banda de marca: UNA SOLA banda de color plano azul #2563eb de 0 a 16mm.
            # (Antes eran dos rects apilados de 9mm y el título caía en el filo, cortándose.)
            self.set_fill_color(37, 99, 235)  # #2563eb
            self.rect(0, 0, self.w, 16, "F")

            # Logo mini de AlwaysPrint a la izquierda (si existe el asset).
            logo_path = getattr(self, "report_logo_path", None)
            text_left_x = 8.0
            if logo_path and os.path.exists(logo_path):
                try:
                    self.image(logo_path, x=8, y=2, h=12)
                    text_left_x = 24.0  # dejar espacio al logo
                except Exception:
                    text_left_x = 8.0

            # Título corto (blanco, bold) tras el logo, centrado VERTICALMENTE en la banda de 16mm
            # (set_xy a y=4 + cell alto 8 → ocupa 4..12, dentro de la banda, no en un borde).
            self.set_text_color(255, 255, 255)
            self.set_font("Helvetica", "B", 11)
            self.set_xy(text_left_x, 4)
            # Título corto que describe el ROL del documento (el subtítulo largo va en la portada).
            self.cell(90, 8, _sanitize_latin1("Detalle de Servicios Prestados"), align="L")

            # A la derecha: "{org} - {periodo}" (blanco, normal), también dentro de la banda.
            org_name = getattr(self, "report_org_name", None)
            period = getattr(self, "report_period", None)
            if org_name or period:
                right_txt = " - ".join(str(v) for v in (org_name, period) if v)
                self.set_font("Helvetica", "", 8)
                self.set_xy(self.w - 100 - 8, 5)
                self.cell(100, 6, _sanitize_latin1(right_txt), align="R")

            # Restaurar color de texto para el contenido del cuerpo.
            self.set_text_color(0, 0, 0)

            # ANCLA ANTI-SOLAPAMIENTO: dejar el cursor SIEMPRE en el top margin al terminar el
            # header. fpdf2 invoca header() al inicio de CADA página, incluidas las que crea el
            # AUTO PAGE BREAK cuando un multi_cell desborda (3ra, 4ta, N-ésima). En esas páginas
            # el flujo puede reanudarse en una `y` que cae DENTRO de la banda (16mm), solapando el
            # texto con la banda azul. Anclar aquí (top margin 24mm >= banda 16mm, 8mm de holgura)
            # garantiza que TODA página, manual o automática, reanude el cuerpo debajo de la banda.
            self.set_y(self.t_margin)
            self.set_x(self.l_margin)

        def footer(self) -> None:
            self.set_y(-15)
            self.set_font("Helvetica", "I", 7)
            self.set_text_color(100, 116, 139)  # #64748b
            year = datetime.utcnow().year
            self.cell(
                0,
                10,
                f"(c) {year} Inversiones On Line S.A.C. - Todos los derechos reservados",
                align="C",
            )

    pdf = ClosureReportPDF()
    # Márgenes: la banda del header mide 16mm; top margin 24mm deja 8mm de aire para que el
    # contenido de páginas 2+ (y el acento azul bajo el título) NO se solapen con la banda.
    # Footer con auto-break a 20mm.
    pdf.set_margins(left=15, top=24, right=15)
    pdf.set_auto_page_break(auto=True, margin=20)

    # Atributos que consume header() (setear ANTES del primer add_page para que la banda de la
    # portada ya muestre org/periodo/logo).
    _org_name_hdr = getattr(org, "name", None) or getattr(org, "id", "N/A")
    pdf.report_org_name = _org_name_hdr
    pdf.report_period = _fmt_period(header)
    pdf.report_logo_path = alwaysprint_logo if os.path.exists(alwaysprint_logo) else None

    pdf.add_page()
    effective_width = pdf.w - pdf.l_margin - pdf.r_margin

    # --- Helpers locales de estilo de sección (color corporativo + acento azul) ---
    def _section_title(text: str) -> None:
        """
        Dibuja un título de sección a todo el ancho: azul oscuro #1e3a8a (Helvetica B 12) con una
        línea de acento azul #2563eb (~30mm) debajo. AVANZA a nueva línea (uso en secciones
        stacked, NO en columnas alineadas). Restaura color de texto de cuerpo al terminar.
        """
        # Guard anti-solapamiento: si la `y` heredada quedó por encima del top margin (p. ej. por
        # un set_y negativo previo al abrir una página nueva), forzarla al top margin para que el
        # título NUNCA caiga dentro de la banda del header.
        if pdf.get_y() < pdf.t_margin:
            pdf.set_y(pdf.t_margin)
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(30, 58, 138)  # #1e3a8a
        pdf.set_x(pdf.l_margin)
        pdf.cell(0, 7, _sanitize_latin1(text), ln=True)
        # Línea de acento azul corta debajo del título.
        accent_y = pdf.get_y() + 0.5
        pdf.set_draw_color(37, 99, 235)  # #2563eb
        pdf.set_line_width(0.8)
        pdf.line(pdf.l_margin, accent_y, pdf.l_margin + 30, accent_y)
        pdf.set_line_width(0.2)  # restaurar grosor por defecto
        pdf.ln(2)
        pdf.set_text_color(0, 0, 0)

    def _section_title_at(text: str, x: float, width: float, y: float) -> None:
        """
        Variante para títulos de columnas alineadas: pinta el texto en azul oscuro y su acento
        azul en una `(x, y)` dada SIN avanzar el flujo vertical (no rompe el layout de columnas).
        No cambia la `y` del cursor de forma persistente; el llamador controla el flujo.
        """
        pdf.set_xy(x, y)
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(30, 58, 138)  # #1e3a8a
        pdf.cell(width, 7, _sanitize_latin1(text), ln=True)
        accent_y = y + 7.5
        accent_w = min(30.0, width)
        pdf.set_draw_color(37, 99, 235)  # #2563eb
        pdf.set_line_width(0.8)
        pdf.line(x, accent_y, x + accent_w, accent_y)
        pdf.set_line_width(0.2)
        pdf.set_text_color(0, 0, 0)

    # Helper de altura de PNG (usado tanto por la portada como por la sección de gráficos).
    from PIL import Image as _PILImage  # backend de imagen ya presente (matplotlib/fpdf2)

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

    # ==================================================================================
    # Sección 1 — Portada / header (logo Robles.AI, título, organización, periodo, modalidad, fecha)
    # La banda de marca (header()) ocupa 0-16mm en TODAS las páginas; el contenido de portada
    # empieza debajo (logo en y=24, título en y=44) para no solaparse con la banda. El logo mini
    # de AlwaysPrint ya va en la banda del header → NO se repite grande en la portada.
    # ==================================================================================
    if os.path.exists(robles_logo):
        # Logo Robles.AI a la derecha (x=155..190, w=35) + subtítulo "Division de Automatizacion"
        # JUSTO DEBAJO del logo, alineado a la izquierda del mismo (a la altura de la "R").
        _robles_logo_y = 24.0
        _robles_logo_w = 35.0
        pdf.image(robles_logo, x=155, y=_robles_logo_y, w=_robles_logo_w)
        # Altura real del logo Robles.AI para pegar el subtítulo justo debajo (aspect ratio del PNG).
        try:
            with open(robles_logo, "rb") as _f:
                _robles_h = _png_height_for_width(_f.read(), _robles_logo_w)
        except Exception:
            _robles_h = _robles_logo_w * (1.0 / 3.0)  # fallback aproximado
        pdf.set_font("Helvetica", "I", 6.5)
        pdf.set_text_color(100, 100, 100)
        pdf.set_xy(155, _robles_logo_y + _robles_h + 1)
        pdf.cell(40, 3, _sanitize_latin1("Division de Automatizacion"), align="L")
    else:
        # Fallback textual si no está el asset.
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(100, 100, 100)
        pdf.set_xy(130, 26)
        pdf.cell(70, 4, "Robles.AI", align="R")

    # Título centrado (debajo de los logos de portada).
    pdf.set_xy(10, 44)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, _sanitize_latin1("Reporte de Cierre Mensual - Detalle de Servicios Prestados"), ln=True, align="C")
    pdf.ln(3)

    # Separador (hairline gris #cbd5e1, entre márgenes).
    pdf.set_draw_color(203, 213, 225)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
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
    _section_title_at("Datos del cierre", meta_left_x, meta_col_width, blocks_top_y)
    pdf.set_xy(meta_left_x, blocks_top_y + 9)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 116, 139)  # #64748b texto secundario
    datos_lines = [
        f"Organizacion: {org_name}",
        f"Periodo: {_fmt_period(header)}",
        f"Modalidad: {header.mode}",
        f"Tipo de cierre: {tipo_cierre}",
        f"Fecha de cierre: {_fmt_closure_date(header, org)}",
    ]
    for line in datos_lines:
        pdf.set_x(meta_left_x)
        pdf.multi_cell(meta_col_width, 5, _sanitize_latin1(f"- {line}"))
    left_bottom_y = pdf.get_y()

    # --- Columna derecha: "Resumen del cierre" ---
    _section_title_at("Resumen del cierre", meta_right_x, meta_col_width, blocks_top_y)
    pdf.set_xy(meta_right_x, blocks_top_y + 9)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 116, 139)  # #64748b texto secundario
    resumen_lines = [
        f"Estaciones facturables: {header.total_billable}",
        f"Estaciones recicladas: {header.total_recycled}",
        f"Estaciones archivadas: {header.total_archived}",
        f"Monto total: USD {_fmt_money(reconciliation.header_amount)}",
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
        pdf.set_text_color(100, 116, 139)

    pdf.ln(4)
    pdf.set_draw_color(203, 213, 225)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
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
    # (El helper `_png_height_for_width` ya está definido arriba, antes de la portada.)
    _GUTTER = 6.0  # separación horizontal entre columnas (mm)
    col_width = (effective_width - _GUTTER) / 2.0
    left_x = pdf.l_margin
    right_x = pdf.l_margin + col_width + _GUTTER

    # Títulos de ambas columnas a la misma altura (azul oscuro + acento azul centrado).
    titles_y = pdf.get_y()
    pdf.set_text_color(30, 58, 138)  # #1e3a8a
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_xy(left_x, titles_y)
    pdf.cell(col_width, 7, _sanitize_latin1("Composicion de tramos"), align="C")
    pdf.set_xy(right_x, titles_y)
    pdf.cell(col_width, 7, _sanitize_latin1("Evolucion historica"), align="C")
    # Acento azul centrado bajo cada título de columna (~30mm).
    accent_y = titles_y + 7.5
    accent_w = min(30.0, col_width)
    pdf.set_draw_color(37, 99, 235)  # #2563eb
    pdf.set_line_width(0.8)
    pdf.line(left_x + (col_width - accent_w) / 2, accent_y, left_x + (col_width + accent_w) / 2, accent_y)
    pdf.line(right_x + (col_width - accent_w) / 2, accent_y, right_x + (col_width + accent_w) / 2, accent_y)
    pdf.set_line_width(0.2)
    pdf.set_text_color(0, 0, 0)

    images_y = titles_y + 10  # debajo de los títulos + acento
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
    pdf.set_draw_color(203, 213, 225)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
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
    _section_title_at("Conceptos, tarifas y modalidad", info_left_x, info_col_width, info_top_y)
    pdf.set_xy(info_left_x, info_top_y + 9)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(100, 116, 139)  # #64748b
    conceptos = [
        "Facturable: estacion (IP privada) contabilizada para el cobro del periodo "
        "(la unidad de cobro es la estacion IP, no impresiones).",
        "Reciclado: estacion reutilizada dentro del ciclo; no genera cargo adicional.",
        "Archivado: estacion retirada/archivada; se conserva como sustento historico.",
        f"Modalidad aplicada: {header.mode}. Moneda: USD (sin impuestos).",
    ]
    for line in conceptos:
        pdf.set_x(info_left_x)
        pdf.multi_cell(info_col_width, 5, _sanitize_latin1(f"- {line}"))
    left_info_bottom_y = pdf.get_y()

    # --- Columna derecha: Tabla del desglose por tramo ---
    _section_title_at("Desglose por tramo", info_right_x, info_col_width, info_top_y)

    # Anchos de columna de la tabla, proporcionales al ancho de la columna derecha.
    tbl_col_widths = [
        info_col_width * 0.16,  # Desde
        info_col_width * 0.16,  # Hasta
        info_col_width * 0.24,  # Tarifa
        info_col_width * 0.16,  # Estaciones IP
        info_col_width * 0.28,  # Subtotal
    ]
    tbl_headers = ["Desde", "Hasta", "Tarifa", "Estaciones", "Subtotal"]

    # Cabecera de la tabla (azul #2563eb con texto blanco).
    pdf.set_xy(info_right_x, info_top_y + 9)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(37, 99, 235)  # #2563eb
    pdf.set_text_color(255, 255, 255)
    for width, title in zip(tbl_col_widths, tbl_headers):
        pdf.cell(width, 6, _sanitize_latin1(title), border=1, align="C", fill=True)
    pdf.ln(6)

    # Filas de tramos (zebra striping: impares #f1f5f9, pares blanco).
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(51, 65, 85)  # #334155
    if tiers_applied:
        row_index = 0
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
                _fmt_money(rate),
                str(ips_in_tier),
                _fmt_money(subtotal),
            ]
            # Zebra striping suave: filas impares con fill gris #f1f5f9.
            if row_index % 2 == 1:
                pdf.set_fill_color(241, 245, 249)  # #f1f5f9
            else:
                pdf.set_fill_color(255, 255, 255)
            pdf.set_x(info_right_x)
            for width, cell in zip(tbl_col_widths, row):
                pdf.cell(width, 6, _sanitize_latin1(cell), border=1, align="C", fill=True)
            pdf.ln(6)
            row_index += 1
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

    # Fila de total (reconcilia con header.amount, la fuente de verdad). Fill azul suave.
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(30, 58, 138)  # #1e3a8a
    pdf.set_fill_color(226, 232, 240)  # #e2e8f0 (azul/gris suave para destacar el total)
    pdf.set_x(info_right_x)
    pdf.cell(sum(tbl_col_widths[:4]), 6, _sanitize_latin1("Total"), border=1, align="R", fill=True)
    pdf.cell(tbl_col_widths[4], 6, _sanitize_latin1(f"USD {_fmt_money(reconciliation.header_amount)}"), border=1, align="C", fill=True)
    pdf.ln(6)
    right_info_bottom_y = pdf.get_y()

    # Continuar debajo de la columna más alta.
    pdf.set_y(max(left_info_bottom_y, right_info_bottom_y))

    # ==================================================================================
    # Sección 8 (movida) — Nota explícita USD sin impuestos al PIE de la PÁGINA 1 (Req 3.7).
    # Va tras el "Desglose por tramo" y ANTES del add_page() que abre la página 2, para que quede
    # claramente en la página del resumen. Se ancla cerca del pie (por encima del footer en -15).
    # ==================================================================================
    pdf.set_y(-30)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(0, 0, 0)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(effective_width, 5, _sanitize_latin1(_USD_DISCLAIMER))

    # ==================================================================================
    # Salto de página: la página 1 contiene SOLO el resumen (portada + Datos/Resumen + gráficos
    # + Conceptos/tramos + disclaimer USD al pie). Contingencia y Análisis IA empiezan en pág 2.
    # ==================================================================================
    pdf.add_page()
    # Fuerza el cursor al top margin tras abrir la página 2: el disclaimer USD previo usó
    # set_y(-30) (zona de footer), y tras add_page() la `y` residual podía caer DENTRO de la
    # banda del header (16mm), solapando el título con el título de la banda. Anclar aquí al
    # top margin garantiza que "Contingencia del ciclo" arranque debajo de la banda.
    pdf.set_y(pdf.t_margin)
    pdf.set_x(pdf.l_margin)

    # ==================================================================================
    # Sección 6b — Contingencia del ciclo (página 2, ANTES del análisis IA)
    # ==================================================================================
    _section_title("Contingencia del ciclo")

    if contingency is None or not contingency.data_available:
        # Fail-safe: estadísticas no disponibles → nota en cursiva gris, no bloquea el reporte.
        pdf.set_font("Helvetica", "I", 10)
        pdf.set_text_color(120, 120, 120)
        pdf.set_x(pdf.l_margin + 2)
        pdf.multi_cell(
            effective_width - 2,
            5,
            _sanitize_latin1("Metricas de contingencia no disponibles para este cierre."),
        )
    else:
        # Subtítulo de la tabla de estadísticas de uso.
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(0, 0, 0)
        pdf.set_x(pdf.l_margin)
        pdf.cell(0, 6, _sanitize_latin1("Estadisticas de uso de contingencia"), ln=True)
        pdf.ln(1)

        forced_org_txt = "si" if contingency.forced_org_now else "no"
        # Filas de la tabla (Métrica | Valor); los valores se sanitizan al dibujar.
        rows = [
            (
                "Ingresos a contingencia - Organizacion (intervencion masiva)",
                str(contingency.org_entries),
            ),
            ("Salidas de contingencia - Organizacion", str(contingency.org_exits)),
            (
                "Tiempo de proteccion a nivel Organizacion",
                _fmt_hm(contingency.org_protection_seconds),
            ),
            ("Ingresos a contingencia - Agencia/VLAN", str(contingency.vlan_entries)),
            ("Salidas de contingencia - Agencia/VLAN", str(contingency.vlan_exits)),
            (
                "Tiempo de proteccion a nivel Agencia/VLAN",
                _fmt_hm(contingency.vlan_protection_seconds),
            ),
            (
                "Intervenciones automatizadas a nivel Workstation (auto-proteccion, ahorran ticket)",
                str(contingency.ws_auto_interventions),
            ),
            (
                "Intervenciones remotas a nivel Workstation (ejecutadas por Mesa de Ayuda, sin visita presencial)",
                str(contingency.ws_remote_interventions),
            ),
            (
                "Equipos afectados en la mayor intervencion",
                str(contingency.max_affected_ws),
            ),
            (
                "Contingencia forzada vigente",
                f"organizacion={forced_org_txt}, VLANs={contingency.forced_vlan_count_now}",
            ),
        ]

        # Anchos de columna de la tabla (Métrica ancha, Valor angosto).
        metric_w = effective_width * 0.68
        value_w = effective_width - metric_w
        line_h = 6

        # Cabecera de la tabla (azul #2563eb con texto blanco).
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(37, 99, 235)  # #2563eb
        pdf.set_text_color(255, 255, 255)
        pdf.set_x(pdf.l_margin)
        pdf.cell(metric_w, line_h, _sanitize_latin1("Metrica"), border=1, align="L", fill=True)
        pdf.cell(value_w, line_h, _sanitize_latin1("Valor"), border=1, align="C", fill=True)
        pdf.ln(line_h)

        # Filas de datos (zebra striping: impares #f1f5f9, pares blanco).
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(51, 65, 85)  # #334155
        for row_index, (metric, value) in enumerate(rows):
            if row_index % 2 == 1:
                pdf.set_fill_color(241, 245, 249)  # #f1f5f9
            else:
                pdf.set_fill_color(255, 255, 255)
            pdf.set_x(pdf.l_margin)
            pdf.cell(metric_w, line_h, _sanitize_latin1(metric), border=1, align="L", fill=True)
            pdf.cell(value_w, line_h, _sanitize_latin1(value), border=1, align="C", fill=True)
            pdf.ln(line_h)

        # Cronología de contingencia a nivel organización (si hubo tramos): TABLA cronológica
        # con CADA entrada y CADA salida, la DURACIÓN de cada tramo y una fila de TIEMPO TOTAL.
        # Cada tramo genera DOS filas: ENTRADA (ámbar) y SALIDA (verde, con la duración del tramo).
        # Máximo 12 tramos (24 filas); si hay más, una fila "y N tramos mas". El total siempre es
        # `org_protection_seconds` (fuente de verdad).
        org_intervals = contingency.org_intervals or []
        if org_intervals:
            tz_label = contingency.timezone or "UTC"
            max_intervals = 12
            shown_intervals = org_intervals[:max_intervals]
            extra_intervals = len(org_intervals) - len(shown_intervals)

            pdf.ln(2)
            # Encabezado de la cronología.
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(0, 0, 0)
            pdf.set_x(pdf.l_margin)
            pdf.cell(
                0,
                6,
                _sanitize_latin1(
                    f"Cronologia de contingencia - Organizacion ({tz_label})"
                ),
                ln=True,
            )
            pdf.ln(1)

            # Anchos de columna: Evento ~40%, Fecha ~38%, Duracion ~22%.
            event_w = effective_width * 0.40
            date_w = effective_width * 0.38
            dur_w = effective_width - event_w - date_w
            line_h = 6

            # Cabecera de la tabla (azul #2563eb con texto blanco), como las otras tablas.
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_fill_color(37, 99, 235)  # #2563eb
            pdf.set_text_color(255, 255, 255)
            pdf.set_x(pdf.l_margin)
            pdf.cell(event_w, line_h, _sanitize_latin1("Evento"), border=1, align="L", fill=True)
            pdf.cell(
                date_w,
                line_h,
                _sanitize_latin1(f"Fecha y hora ({tz_label})"),
                border=1,
                align="L",
                fill=True,
            )
            pdf.cell(
                dur_w, line_h, _sanitize_latin1("Duracion del tramo"), border=1, align="C", fill=True
            )
            pdf.ln(line_h)

            pdf.set_font("Helvetica", "", 9)
            for iv in shown_intervals:
                start_iso = iv.get("start_iso")
                end_iso = iv.get("end_iso")
                open_at_start = bool(iv.get("open_at_start"))
                open_at_end = bool(iv.get("open_at_end"))
                duration_seconds = iv.get("duration_seconds") or 0

                # Fila ENTRADA: ámbar suave #fef3c7, texto ámbar oscuro #92400e. Duración vacía ("-").
                if open_at_start:
                    entry_date = "(inicio del ciclo)"
                else:
                    entry_date = _fmt_entry_datetime(start_iso) if start_iso else "-"
                pdf.set_fill_color(254, 243, 199)  # #fef3c7 (entrada a contingencia)
                pdf.set_text_color(146, 64, 14)  # #92400e
                pdf.set_x(pdf.l_margin)
                pdf.cell(
                    event_w,
                    line_h,
                    _sanitize_latin1("Entrada a contingencia"),
                    border=1,
                    align="L",
                    fill=True,
                )
                pdf.cell(
                    date_w, line_h, _sanitize_latin1(entry_date), border=1, align="L", fill=True
                )
                pdf.cell(dur_w, line_h, _sanitize_latin1("-"), border=1, align="C", fill=True)
                pdf.ln(line_h)

                # Fila SALIDA: verde suave #dcfce7, texto verde oscuro #166534. Lleva la duración.
                if open_at_end:
                    exit_date = "(vigente al cierre)"
                else:
                    exit_date = _fmt_entry_datetime(end_iso) if end_iso else "-"
                pdf.set_fill_color(220, 252, 231)  # #dcfce7 (salida de contingencia)
                pdf.set_text_color(22, 101, 52)  # #166534
                pdf.set_x(pdf.l_margin)
                pdf.cell(
                    event_w,
                    line_h,
                    _sanitize_latin1("Salida de contingencia"),
                    border=1,
                    align="L",
                    fill=True,
                )
                pdf.cell(
                    date_w, line_h, _sanitize_latin1(exit_date), border=1, align="L", fill=True
                )
                pdf.cell(
                    dur_w,
                    line_h,
                    _sanitize_latin1(_fmt_hm(duration_seconds)),
                    border=1,
                    align="C",
                    fill=True,
                )
                pdf.ln(line_h)

            # Fila de tramos omitidos (si se superó el máximo mostrado).
            if extra_intervals > 0:
                pdf.set_fill_color(241, 245, 249)  # #f1f5f9
                pdf.set_text_color(100, 116, 139)  # #64748b
                pdf.set_x(pdf.l_margin)
                pdf.cell(
                    event_w + date_w,
                    line_h,
                    _sanitize_latin1(f"y {extra_intervals} tramos mas"),
                    border=1,
                    align="L",
                    fill=True,
                )
                pdf.cell(dur_w, line_h, _sanitize_latin1("-"), border=1, align="C", fill=True)
                pdf.ln(line_h)

            # Fila TOTAL: "Tiempo total de proteccion (Organizacion)" ocupa Evento+Fecha; la
            # duración es _fmt_hm(org_protection_seconds) (fuente de verdad). Fondo #e2e8f0,
            # texto azul oscuro #1e3a8a, bold.
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_fill_color(226, 232, 240)  # #e2e8f0
            pdf.set_text_color(30, 58, 138)  # #1e3a8a
            pdf.set_x(pdf.l_margin)
            pdf.cell(
                event_w + date_w,
                line_h,
                _sanitize_latin1("Tiempo total de proteccion (Organizacion)"),
                border=1,
                align="L",
                fill=True,
            )
            pdf.cell(
                dur_w,
                line_h,
                _sanitize_latin1(_fmt_hm(contingency.org_protection_seconds)),
                border=1,
                align="C",
                fill=True,
            )
            pdf.ln(line_h)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(51, 65, 85)

    pdf.ln(2)
    pdf.set_text_color(100, 116, 139)
    pdf.set_draw_color(203, 213, 225)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(5)

    # ==================================================================================
    # Sección 7 — Análisis IA (o nota fail-safe si no está disponible)
    # ==================================================================================
    _section_title("Analisis IA del consumo")

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
        import re as _re

        # Detecta líneas numeradas tipo "1. ..." para tratarlas como subtítulo (pequeño ln antes).
        _numbered_re = _re.compile(r"^\d+\.\s+")
        for raw_line in analysis.split("\n"):
            line = _sanitize_latin1(raw_line)
            pdf.set_x(pdf.l_margin)
            if line.startswith("### "):
                # H3 (se evalúa antes que "## " / "# " por ser prefijo más largo).
                pdf.ln(2)
                pdf.set_font("Helvetica", "B", 11)
                pdf.multi_cell(effective_width, 6, line[4:])
                pdf.set_font("Helvetica", "", 11)
            elif line.startswith("## "):
                pdf.ln(3)
                pdf.set_font("Helvetica", "B", 13)
                pdf.multi_cell(effective_width, 6, line[3:])
                pdf.set_font("Helvetica", "", 11)
            elif line.startswith("# "):
                # H1 (tamaño B 14). Va tras "### "/"## " para no capturarlas por error.
                pdf.ln(3)
                pdf.set_font("Helvetica", "B", 14)
                pdf.multi_cell(effective_width, 6, line[2:])
                pdf.set_font("Helvetica", "", 11)
            elif line.startswith("**") and line.endswith("**") and len(line) > 4:
                # Encabezado completo en negrita (comportamiento previo, sin asteriscos literales).
                pdf.set_font("Helvetica", "B", 11)
                pdf.multi_cell(effective_width, 6, line.strip("*"))
                pdf.set_font("Helvetica", "", 11)
            elif line.startswith("- ") or line.startswith("* "):
                # Viñeta: renderiza el contenido con soporte de negrita inline `**...**`.
                pdf.set_x(pdf.l_margin + 4)
                _render_inline_md(pdf, f"- {line[2:]}", effective_width - 4, 5, base_size=11)
            elif line.strip() == "":
                pdf.ln(3)
            else:
                # Línea numerada ("N. ...") → pequeño ln antes para tratarla como subtítulo.
                if _numbered_re.match(line):
                    pdf.ln(1)
                # CUALQUIER línea restante (incluida numerada) se renderiza con negrita inline
                # para que ningún `**...**` quede como texto literal en el PDF.
                pdf.set_x(pdf.l_margin)
                _render_inline_md(pdf, line, effective_width, 5, base_size=11)

    # (La nota USD sin impuestos —sección 8, Req 3.7— se dibuja al pie de la PÁGINA 1, no aquí.)
    # Sección 9 (footer de copyright) se dibuja automáticamente en cada página vía footer().
    return bytes(pdf.output())
