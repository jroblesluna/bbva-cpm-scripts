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


# === REPORTE DE CIERRE MENSUAL (task 2.1) ===
#
# Schemas de salida del Reporte de Cierre Mensual (PDF), sustento formal de la factura.
# El reporte es de solo lectura sobre el snapshot inmutable del cierre; estos schemas
# describen la presigned URL del PDF cacheado, la metadata de generacion y los datos
# estructurados que alimentan tanto el PDF como la vista previa del frontend.


class ClosureReportUrlResponse(BaseModel):
    """
    Respuesta de `GET .../report` y `POST .../report/regenerate` (Req 1.1, 1.3).

    `report_url` es la presigned URL SigV4 regional del PDF en S3; `cached` es True cuando el
    artefacto se sirvio desde S3 sin recomputar (Cache_Hit) y False tras generar/regenerar;
    `ai_analysis_available` es False cuando el LLM fallo (fail-safe, Req 5.4) y el PDF se
    genero con la nota de analisis IA no disponible.
    """

    report_url: str
    expires_in_seconds: int = 3600
    cached: bool
    ai_analysis_available: bool


class ClosureReportMeta(BaseModel):
    """
    Metadata de generacion del reporte, de la fila `BillingClosureReport` (Req 6.1).

    Expone el modelo LLM usado y las fechas de generacion (IA y PDF). Los campos son nullable
    porque el reporte puede no haberse generado aun o el analisis IA puede no estar disponible
    (fail-safe). `ai_analysis_available` deriva de si el `ai_analysis` persistido es no nulo.
    """

    closure_id: UUID
    ai_model: Optional[str] = None
    ai_generated_at: Optional[datetime] = None
    pdf_generated_at: Optional[datetime] = None
    ai_analysis_available: bool

    model_config = {"from_attributes": True}


class HistoryPoint(BaseModel):
    """
    Punto de la serie historica de cierres de la organizacion (Req 7.4).

    `cycle` es el numero de ciclo/mes de servicio (1-based; el cierre mas antiguo es 1),
    derivado ordenando los cierres por `(period_year, period_month)`. Incluye los totales por
    estado y el monto del cierre de ese ciclo para graficar la evolucion historica.
    """

    cycle: int
    period_year: int
    period_month: int
    total_billable: int
    total_recycled: int
    total_archived: int
    amount: Decimal


class ContingencySummaryResponse(BaseModel):
    """
    Estadisticas de uso de contingencia del ciclo (fail-safe, informativas).

    Refleja EXACTAMENTE los campos de `ContingencySummary.to_dict()` del servicio, orientados a
    valor operativo por nivel:
    - Nivel organizacion: ingresos/salidas (`org_entries`/`org_exits`), timestamps de entrada en
      la tz de la org (`org_entry_datetimes`) y tiempo de proteccion en segundos
      (`org_protection_seconds`).
    - Nivel agencia/VLAN: ingresos/salidas (`vlan_entries`/`vlan_exits`) y tiempo de proteccion
      agregado (`vlan_protection_seconds`).
    - Nivel workstation: ingresos/salidas (`ws_entries`/`ws_exits`) e intervenciones emparejadas
      entrada->salida (`ws_interventions` = acciones/tickets ahorrados a la Mesa de Ayuda).
    - Estado vigente y magnitud: contingencia forzada actual (`forced_org_now` /
      `forced_vlan_count_now`) y equipos afectados en la mayor intervencion del ciclo
      (`max_affected_ws`, maximo real, no suma).

    `timezone` es la tz IANA usada para formatear los timestamps. `data_available` es False cuando
    el calculo fallo (fail-safe): en ese caso todo va en 0/False y la generacion del reporte no se
    bloquea. Todos los campos llevan default salvo `data_available` (para no romper el fail-safe).
    """

    data_available: bool
    timezone: str = "UTC"
    # Nivel organización.
    org_entries: int = 0
    org_exits: int = 0
    org_entry_datetimes: list = []
    org_protection_seconds: int = 0
    # Nivel agencia/VLAN.
    vlan_entries: int = 0
    vlan_exits: int = 0
    vlan_protection_seconds: int = 0
    # Nivel workstation.
    ws_entries: int = 0
    ws_exits: int = 0
    ws_interventions: int = 0
    # Estado vigente + magnitud real.
    forced_org_now: bool = False
    forced_vlan_count_now: int = 0
    max_affected_ws: int = 0


class ClosureReportDataResponse(BaseModel):
    """
    Datos estructurados del reporte para la vista previa del frontend (Req 8.7).

    Reutiliza `ClosureHeaderResponse` como `header` (cabecera inmutable del cierre) y agrega el
    desglose de tramos del mes (`tiers_applied`), la serie historica (`history`) y el texto IA
    si existe (`ai_analysis`, None si el LLM fallo). `currency`/`taxes_included` reflejan la
    declaracion obligatoria de precios en USD sin impuestos (Req 11.5). `contingency` agrega el
    resumen de contingencia del ciclo (None por compatibilidad si no se calculo).
    """

    header: ClosureHeaderResponse
    tiers_applied: list
    history: List[HistoryPoint]
    ai_analysis: Optional[str] = None
    currency: str = "USD"
    taxes_included: bool = False
    contingency: Optional[ContingencySummaryResponse] = None
