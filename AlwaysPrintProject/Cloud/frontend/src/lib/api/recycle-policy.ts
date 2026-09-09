/**
 * Cliente API de la Política de Reciclaje (recycle-policy-config, task 9.3) — solo Superadmin.
 *
 * Funciones tipadas (sin `any`) para los endpoints del backend, todos bajo el prefijo
 * `/api/v1` que ya incluye `apiClient` (por eso las rutas aquí empiezan en
 * `/billing/recycle-policy/...`):
 *
 * - GET  /billing/recycle-policy/global                → lista los Global_Default.
 * - PUT  /billing/recycle-policy/global                → crea/reemplaza un Global_Default.
 * - GET  /billing/recycle-policy/org/{organization_id} → lista los Org_Override de una org.
 * - PUT  /billing/recycle-policy/org/{organization_id} → crea/reemplaza un Org_Override.
 *
 * La entrada usa `RecyclePolicyIn` (regla string `"+1/-2/-3"`, `ephemeral_hours`, año/mes del
 * Effective_From_Period). La salida `RecyclePolicyOut` expone la regla formateada `"+1/-2/-3"` y
 * el `effective_from` ya como `"AAAA-MM"`.
 *
 * Errores fail-closed (Req 17.5/5.3): el backend responde 422 con
 * `detail = { errors: [{ rule, message }, ...] }` ante violaciones de validación (una por regla)
 * y 409 con `detail` string ante conflicto con periodos ya cerrados. El interceptor de
 * `apiClient` normaliza el error a `{ detail, status }`, por lo que el consumidor lee
 * `error.status` y `error.detail`.
 */

import { apiClient } from '@/lib/api'
import type {
  RecyclePolicyIn,
  RecyclePolicyOut,
} from '@/types/recycle-policy'

/**
 * Lista las políticas de reciclaje Global_Default (`organization_id IS NULL`).
 * GET /billing/recycle-policy/global (solo Superadmin).
 *
 * El backend las ordena por Effective_From_Period descendente (la más reciente primero).
 */
export async function getGlobalRecyclePolicies(): Promise<RecyclePolicyOut[]> {
  const response = await apiClient.get<RecyclePolicyOut[]>(
    '/billing/recycle-policy/global'
  )
  return response.data
}

/**
 * Crea o reemplaza un Global_Default para un Effective_From_Period.
 * PUT /billing/recycle-policy/global (solo Superadmin).
 *
 * @param payload - Regla `"+1/-2/-3"`, `ephemeral_hours` y año/mes del periodo efectivo.
 */
export async function putGlobalRecyclePolicy(
  payload: RecyclePolicyIn
): Promise<RecyclePolicyOut> {
  const response = await apiClient.put<RecyclePolicyOut>(
    '/billing/recycle-policy/global',
    payload
  )
  return response.data
}

/**
 * Lista los Org_Override de reciclaje de una organización (tenant isolation en el backend).
 * GET /billing/recycle-policy/org/{organization_id} (solo Superadmin).
 *
 * @param organizationId - ID de la organización.
 */
export async function getOrgRecyclePolicies(
  organizationId: string
): Promise<RecyclePolicyOut[]> {
  const response = await apiClient.get<RecyclePolicyOut[]>(
    `/billing/recycle-policy/org/${organizationId}`
  )
  return response.data
}

/**
 * Crea o reemplaza un Org_Override de reciclaje para una organización.
 * PUT /billing/recycle-policy/org/{organization_id} (solo Superadmin).
 *
 * @param organizationId - ID de la organización.
 * @param payload - Regla `"+1/-2/-3"`, `ephemeral_hours` y año/mes del periodo efectivo.
 */
export async function putOrgRecyclePolicy(
  organizationId: string,
  payload: RecyclePolicyIn
): Promise<RecyclePolicyOut> {
  const response = await apiClient.put<RecyclePolicyOut>(
    `/billing/recycle-policy/org/${organizationId}`,
    payload
  )
  return response.data
}
