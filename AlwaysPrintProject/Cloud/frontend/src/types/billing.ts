/**
 * Tipos TypeScript para el módulo Usage and Billing (facturación por IP privada).
 *
 * Corresponden a los schemas Pydantic del backend en:
 * - app/schemas/billing_rates.py     (planes/tarifas y modalidad)
 * - app/schemas/billing_closures.py  (cierres mensuales y detalle por IP)
 * - app/schemas/billing_annual.py    (suscripción y liquidación anual)
 * - app/api/v1/endpoints/workstations.py (BulkDeleteReport del borrado masivo)
 *
 * Convenciones (alineadas con el resto de src/types/*.ts):
 * - Campos en snake_case, iguales a los del backend.
 * - Fechas/UUID como `string` (el backend las serializa en ISO-8601 / UUID textual).
 * - Enteros de conteo como `number`.
 *
 * Nota sobre dinero (Decimal):
 * El backend define los campos monetarios como `Numeric`/`Decimal` de Pydantic. FastAPI puede
 * serializar Decimal como número o como string según la configuración; para no perder precisión
 * ni asumir un formato, los campos de dinero (montos, tarifas, crédito, cargo, aporte por IP) se
 * tipan como `number | string`. En la UI conviene normalizarlos con `Number(...)` antes de
 * formatear. Los tramos (`RateTier.rate`) también admiten `number | string` por el mismo motivo.
 */

// ── Enums de dominio ─────────────────────────────────────────────────────────

/** Modalidad de facturación de una organización o plan. */
export type BillingMode = 'monthly' | 'annual'

/** Estado del ciclo de vida de facturación de una workstation (columna `billing_status`). */
export type BillingStatus = 'new' | 'billable' | 'recycled' | 'archived'

// ── Tarifas y planes (billing_rates.py) ──────────────────────────────────────

/**
 * Tramo tarifario. `from`/`to` delimitan el rango de IPs (inclusive); `to = null` en el último
 * tramo (sin tope superior). `rate` es la tarifa unitaria (dinero → `number | string`).
 * `free_growth_to` solo aplica a la modalidad anual (margen de crecimiento libre del tramo).
 */
export interface RateTier {
  from: number
  to: number | null
  rate: number | string
  free_growth_to?: number
}

/** Plan tarifario por defecto del sistema (`billing_rate_plans`, editable por superadmin). */
export interface RatePlan {
  id: string
  mode: BillingMode
  is_default: boolean
  name: string
  tiers: RateTier[]
  currency: string
  effective_from: string | null
  created_at: string
  updated_at: string
}

/** Payload para editar/programar un plan por defecto (PUT /billing/rate-plans/{id}). */
export interface RatePlanUpdate {
  name?: string
  tiers?: RateTier[]
  currency?: string
  effective_from?: string | null
}

/** Plan tarifario individual de una organización por modalidad (`billing_org_plans`). */
export interface OrgPlan {
  id: string
  organization_id: string
  mode: BillingMode
  tiers: RateTier[]
  currency: string
  effective_from: string | null
  created_at: string
  updated_at: string
}

/** Payload para crear/actualizar el plan individual de una org (PUT .../plan). */
export interface OrgPlanUpsert {
  mode: BillingMode
  tiers: RateTier[]
  currency?: string
  effective_from?: string | null
}

/** Modalidad de facturación vigente de una organización (respuesta de PUT .../mode). */
export interface OrgModeResponse {
  organization_id: string
  billing_mode: BillingMode
}

// ── Cierres mensuales (billing_closures.py) ──────────────────────────────────

/**
 * Cabecera de un cierre mensual (una por organización/año/mes). `amount` y `tiers_applied`
 * describen el monto calculado y su desglose por tramo. `amount` es dinero (`number | string`).
 */
export interface ClosureHeader {
  id: string
  organization_id: string
  period_year: number
  period_month: number
  cutoff_at: string
  mode: BillingMode
  timezone: string
  total_billable: number
  total_recycled: number
  total_archived: number
  amount: number | string
  tiers_applied: unknown[]
  is_retroactive: boolean
  created_by_id: string | null
  created_at: string
}

/**
 * Detalle por IP de un cierre (una fila por workstation en el corte, inmutable).
 * `last_seen_capped` es el `last_seen` capado a `cutoff`; `billing_status` es el estado
 * histórico de esa IP en ese cierre. `amount` es el aporte de dinero de la IP.
 */
export interface ClosureItem {
  id: string
  closure_id: string
  workstation_id: string | null
  ip_private: string
  created_at_ws: string
  last_seen_capped: string
  billing_status: BillingStatus
  tier_index: number | null
  amount: number | string
}

/** Página del detalle por IP de un cierre (paginación por `page`/`page_size`). */
export interface ClosureItemsPage {
  total: number
  page: number
  page_size: number
  items: ClosureItem[]
}

/**
 * Respuesta del cierre retroactivo. `closed = true` con `closure` poblado si se cerró el mes
 * pendiente más antiguo; `closed = false` con `closure = null` si no había meses pendientes.
 */
export interface RetroactiveCloseResponse {
  closed: boolean
  detail: string
  closure: ClosureHeader | null
}

// ── Suscripción y liquidación anual (billing_annual.py) ──────────────────────

/** Suscripción anual creada (tarifa/tramo/tope congelados). `tier_rate` es dinero. */
export interface AnnualSubscription {
  id: string
  organization_id: string
  start_date: string
  end_date: string
  declared_volume: number
  tier_rate: number | string
  tier_from: number
  tier_to: number | null
  tier_cap: number | null
  status: string
  settlement: Record<string, unknown> | null
  created_at: string
}

/** Payload para crear una suscripción anual (POST .../annual-subscription). */
export interface AnnualSubscriptionCreate {
  declared_volume: number
  tier_from: number
  tier_rate: number | string
  tier_to?: number | null
  tier_cap?: number | null
}

/** Indicador informativo de "crecimiento libre" / reclasificación del tramo contratado. */
export interface AnnualFreeGrowth {
  within_free_growth: boolean
  free_growth_to: number | null
  requires_reclassification: boolean
}

/**
 * Liquidación anual (informativa) en el aniversario. `credit`/`charge`/`tier_rate` son dinero
 * (`number | string`); `declared`/`real`/`billable_count`/`diff` son conteos.
 */
export interface AnnualSettlement {
  declared: number
  real: number
  billable_count: number
  tier_cap: number | null
  diff: number
  credit: number | string
  charge: number | string
  tier_rate: number | string
  free_growth: AnnualFreeGrowth
}

// ── Borrado masivo de workstations (BulkDeleteReport) ────────────────────────

/** Motivo del rechazo de una IP en el borrado masivo (p. ej. 'online'). */
export interface BulkDeleteRejected {
  ip: string
  reason: string
}

/**
 * Reporte de desglose del borrado masivo (POST /workstations/bulk-delete):
 * - deleted:   IPs eliminadas físicamente (billing_status == 'new').
 * - archived:  IPs archivadas (no-'new' offline).
 * - rejected:  IPs no procesadas (no-'new' online) con su motivo.
 * - not_found: IDs inexistentes o fuera del alcance del operador (tenant isolation).
 */
export interface BulkDeleteReport {
  deleted: string[]
  archived: string[]
  rejected: BulkDeleteRejected[]
  not_found: string[]
}

// ── Reporte de Cierre Mensual (billing_closures.py → schemas de reporte) ─────

/**
 * Respuesta del endpoint de reporte (GET /billing/closures/{closure_id}/report y
 * POST .../report/regenerate). Corresponde al schema `ClosureReportUrlResponse`.
 * - `report_url`: presigned URL SigV4 regional al PDF en S3.
 * - `expires_in_seconds`: expiración de la presigned URL (por defecto 3600).
 * - `cached`: `true` si se sirvió desde S3 sin regenerar.
 * - `ai_analysis_available`: `false` si el LLM falló (fail-safe); el PDF se genera igual.
 */
export interface ClosureReportUrlResponse {
  report_url: string
  expires_in_seconds: number
  cached: boolean
  ai_analysis_available: boolean
}

/**
 * Punto de la serie histórica de cierres de una organización (uno por ciclo/mes de servicio).
 * Corresponde al schema `HistoryPoint`. `cycle` es 1-based (el cierre más antiguo = 1).
 * `amount` es dinero (`number | string`), ver "Nota sobre dinero (Decimal)" arriba.
 */
export interface HistoryPoint {
  cycle: number
  period_year: number
  period_month: number
  total_billable: number
  total_recycled: number
  total_archived: number
  amount: number | string
}

/**
 * Datos estructurados del reporte para la vista previa (GET .../report-data).
 * Corresponde al schema `ClosureReportDataResponse`. Alimenta los gráficos de composición de
 * tramos y evolución histórica en pantalla (recharts). `ai_analysis` es `null` bajo fail-safe.
 */
export interface ClosureReportData {
  header: ClosureHeader
  tiers_applied: unknown[]
  history: HistoryPoint[]
  ai_analysis: string | null
  currency: string
  taxes_included: boolean
}
