/**
 * Cliente API del módulo Usage and Billing (facturación por IP privada).
 *
 * Funciones tipadas (sin `any`) para los endpoints del backend, todos bajo el prefijo
 * `/api/v1` que ya incluye `apiClient` (por eso las rutas aquí empiezan en `/billing/...`
 * y `/workstations/...`):
 *
 * Tarifas/planes/modalidad (billing_rates.py, solo superadmin):
 * - GET /billing/rate-plans
 * - PUT /billing/rate-plans/{id}
 * - PUT /billing/organizations/{org_id}/plan
 * - PUT /billing/organizations/{org_id}/mode
 *
 * Cierres mensuales (billing_closures.py):
 * - GET  /billing/organizations/{org_id}/closures
 * - GET  /billing/closures/{closure_id}/items
 * - POST /billing/organizations/{org_id}/closures/retroactive (superadmin)
 *
 * Suscripción/liquidación anual (billing_annual.py, solo superadmin):
 * - POST /billing/organizations/{org_id}/annual-subscription
 * - GET  /billing/organizations/{org_id}/annual-settlement
 * - POST /billing/organizations/{org_id}/annual-settlement/confirm
 *
 * Borrado masivo de workstations (workstations.py):
 * - POST /workstations/bulk-delete
 */

import { apiClient } from '@/lib/api'
import type {
  AnnualSettlement,
  AnnualSubscription,
  AnnualSubscriptionCreate,
  BillingMode,
  BulkDeleteReport,
  ClosureHeader,
  ClosureItemsPage,
  ClosureReportData,
  ClosureReportUrlResponse,
  OrgModeResponse,
  OrgPlan,
  OrgPlanUpsert,
  RatePlan,
  RatePlanUpdate,
  RetroactiveCloseResponse,
} from '@/types/billing'

// ── Tarifas y planes (superadmin) ────────────────────────────────────────────

/**
 * Lista los planes tarifarios por defecto del sistema (ambas modalidades).
 * GET /billing/rate-plans (solo superadmin).
 */
export async function getRatePlans(): Promise<RatePlan[]> {
  const response = await apiClient.get<RatePlan[]>('/billing/rate-plans')
  return response.data
}

/**
 * Edita o programa un plan por defecto del sistema (solo los campos enviados).
 * PUT /billing/rate-plans/{id} (solo superadmin).
 *
 * @param id - ID del plan por defecto a editar.
 * @param payload - Campos a actualizar (name, tiers, currency, effective_from).
 */
export async function updateRatePlan(
  id: string,
  payload: RatePlanUpdate
): Promise<RatePlan> {
  const response = await apiClient.put<RatePlan>(`/billing/rate-plans/${id}`, payload)
  return response.data
}

/**
 * Crea o actualiza el plan tarifario individual de una organización para una modalidad.
 * PUT /billing/organizations/{org_id}/plan (solo superadmin).
 *
 * @param orgId - ID de la organización.
 * @param payload - Plan individual (modalidad, tramos, moneda, vigencia).
 */
export async function upsertOrgPlan(
  orgId: string,
  payload: OrgPlanUpsert
): Promise<OrgPlan> {
  const response = await apiClient.put<OrgPlan>(
    `/billing/organizations/${orgId}/plan`,
    payload
  )
  return response.data
}

/**
 * Fija la modalidad de facturación de una organización ('monthly' | 'annual').
 * PUT /billing/organizations/{org_id}/mode (solo superadmin).
 *
 * @param orgId - ID de la organización.
 * @param mode - Modalidad de facturación a fijar.
 */
export async function setOrgMode(
  orgId: string,
  mode: BillingMode
): Promise<OrgModeResponse> {
  const response = await apiClient.put<OrgModeResponse>(
    `/billing/organizations/${orgId}/mode`,
    { mode }
  )
  return response.data
}

// ── Cierres mensuales ─────────────────────────────────────────────────────────

/**
 * Lista las cabeceras de cierre de una organización (del más reciente al más antiguo).
 * GET /billing/organizations/{org_id}/closures (admin/operador de su org).
 *
 * @param orgId - ID de la organización.
 */
export async function getClosures(orgId: string): Promise<ClosureHeader[]> {
  const response = await apiClient.get<ClosureHeader[]>(
    `/billing/organizations/${orgId}/closures`
  )
  return response.data
}

/**
 * Devuelve el detalle por IP de un cierre, paginado.
 * GET /billing/closures/{closure_id}/items (admin/operador de su org).
 *
 * @param closureId - ID del cierre.
 * @param page - Número de página (1-based). Por defecto lo asigna el backend (1).
 * @param pageSize - Ítems por página (1..500). Por defecto lo asigna el backend (50).
 */
export async function getClosureItems(
  closureId: string,
  page?: number,
  pageSize?: number
): Promise<ClosureItemsPage> {
  const params: Record<string, number> = {}
  if (page !== undefined) params.page = page
  if (pageSize !== undefined) params.page_size = pageSize

  const response = await apiClient.get<ClosureItemsPage>(
    `/billing/closures/${closureId}/items`,
    { params }
  )
  return response.data
}

/**
 * Genera el cierre retroactivo del mes pendiente más antiguo (uno por llamada).
 * POST /billing/organizations/{org_id}/closures/retroactive (solo superadmin).
 *
 * Respuesta idempotente: `closed = false` con `closure = null` si no hay meses pendientes.
 *
 * @param orgId - ID de la organización.
 */
export async function closeRetroactive(
  orgId: string
): Promise<RetroactiveCloseResponse> {
  const response = await apiClient.post<RetroactiveCloseResponse>(
    `/billing/organizations/${orgId}/closures/retroactive`
  )
  return response.data
}

// ── Reporte de Cierre Mensual (PDF) ──────────────────────────────────────────

/**
 * Obtiene (o genera si no existe) el reporte PDF de un cierre y devuelve su presigned URL.
 * GET /billing/closures/{closure_id}/report (admin/operador de su org).
 *
 * Sirve desde caché S3 si el artefacto ya existe (`cached=true`). El fallo del análisis IA
 * no es error (fail-safe): el PDF se genera igual con `ai_analysis_available=false`.
 *
 * @param closureId - ID del cierre.
 */
export async function getClosureReport(
  closureId: string
): Promise<ClosureReportUrlResponse> {
  const response = await apiClient.get<ClosureReportUrlResponse>(
    `/billing/closures/${closureId}/report`
  )
  return response.data
}

/**
 * Regenera el análisis IA y el PDF del cierre, sobre-escribiendo el artefacto cacheado.
 * POST /billing/closures/{closure_id}/report/regenerate (solo superadmin o admin de la org).
 *
 * Siempre recomputa: la respuesta trae `cached=false`.
 *
 * @param closureId - ID del cierre.
 */
export async function regenerateClosureReport(
  closureId: string
): Promise<ClosureReportUrlResponse> {
  const response = await apiClient.post<ClosureReportUrlResponse>(
    `/billing/closures/${closureId}/report/regenerate`
  )
  return response.data
}

/**
 * Devuelve los datos estructurados del reporte para la vista previa en pantalla (recharts).
 * GET /billing/closures/{closure_id}/report-data (admin/operador de su org).
 *
 * Incluye cabecera, desglose de tramos, serie histórica y el texto de IA si existe
 * (`ai_analysis = null` bajo fail-safe).
 *
 * @param closureId - ID del cierre.
 */
export async function getClosureReportData(
  closureId: string
): Promise<ClosureReportData> {
  const response = await apiClient.get<ClosureReportData>(
    `/billing/closures/${closureId}/report-data`
  )
  return response.data
}

// ── Suscripción y liquidación anual (superadmin) ─────────────────────────────

/**
 * Crea una suscripción anual para la organización (congela tarifa/tramo/tope).
 * POST /billing/organizations/{org_id}/annual-subscription (solo superadmin).
 *
 * @param orgId - ID de la organización.
 * @param payload - Volumen declarado y parámetros del tramo contratado.
 */
export async function createAnnualSubscription(
  orgId: string,
  payload: AnnualSubscriptionCreate
): Promise<AnnualSubscription> {
  const response = await apiClient.post<AnnualSubscription>(
    `/billing/organizations/${orgId}/annual-subscription`,
    payload
  )
  return response.data
}

/**
 * Obtiene la liquidación anual de forma INFORMATIVA (no persiste nada).
 * GET /billing/organizations/{org_id}/annual-settlement (solo superadmin).
 *
 * @param orgId - ID de la organización.
 */
export async function getAnnualSettlement(
  orgId: string
): Promise<AnnualSettlement> {
  const response = await apiClient.get<AnnualSettlement>(
    `/billing/organizations/${orgId}/annual-settlement`
  )
  return response.data
}

/**
 * Aplica manualmente la liquidación anual (status='settled').
 * POST /billing/organizations/{org_id}/annual-settlement/confirm (solo superadmin).
 *
 * @param orgId - ID de la organización.
 */
export async function confirmAnnualSettlement(
  orgId: string
): Promise<AnnualSubscription> {
  const response = await apiClient.post<AnnualSubscription>(
    `/billing/organizations/${orgId}/annual-settlement/confirm`
  )
  return response.data
}

// ── Borrado masivo de workstations ───────────────────────────────────────────

/**
 * Elimina/archiva múltiples workstations en una sola operación, con reporte de desglose.
 * POST /workstations/bulk-delete (admin; operador solo sobre su organización).
 *
 * Cada workstation se procesa según su `billing_status`: 'new' → borrado físico; no-'new'
 * offline → archivado; no-'new' online → rechazo. Los IDs fuera de alcance caen en `not_found`.
 *
 * @param workstationIds - IDs de las workstations a procesar.
 */
export async function bulkDeleteWorkstations(
  workstationIds: string[]
): Promise<BulkDeleteReport> {
  const response = await apiClient.post<BulkDeleteReport>('/workstations/bulk-delete', {
    workstation_ids: workstationIds,
  })
  return response.data
}
