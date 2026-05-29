/**
 * Cliente API para monitoreo de estado del sistema.
 *
 * Funciones para comunicarse con los 5 endpoints del backend:
 * - GET /system-status/current
 * - GET /system-status/history
 * - GET /system-status/services
 * - POST /system-status/collect
 * - GET /system-status/alerts
 *
 * Todos los endpoints requieren autenticación JWT con rol admin.
 */

import { apiClient } from '@/lib/api'
import type {
  StatusSnapshot,
  HistoryResponse,
  ServiceUptime,
  Alert,
} from '@/types/system-status'

/**
 * Respuesta del endpoint /current cuando no hay datos disponibles.
 */
interface EmptyStatusResponse {
  data: null
  message: string
}

/**
 * Obtener el estado actual del sistema (último snapshot).
 *
 * Retorna null si no hay snapshots disponibles en la base de datos.
 */
export async function getSystemStatusCurrent(): Promise<StatusSnapshot | null> {
  const response = await apiClient.get<StatusSnapshot | EmptyStatusResponse>(
    '/system-status/current'
  )

  // El backend retorna { data: null, message: "..." } cuando no hay snapshots
  if (response.data && 'data' in response.data && response.data.data === null) {
    return null
  }

  return response.data as StatusSnapshot
}

/**
 * Obtener historial de métricas con estadísticas agregadas.
 *
 * @param days - Período en días (7, 14 o 30). Por defecto 30.
 * @param metric - Métrica específica: cpu, memory, disk, swap. Por defecto cpu.
 */
export async function getSystemStatusHistory(
  days?: number,
  metric?: string
): Promise<HistoryResponse> {
  const params: Record<string, string | number> = {}
  if (days !== undefined) params.days = days
  if (metric !== undefined) params.metric = metric

  const response = await apiClient.get<HistoryResponse>(
    '/system-status/history',
    { params }
  )
  return response.data
}

/**
 * Obtener historial de disponibilidad (uptime %) por servicio.
 *
 * @param days - Período en días (7, 14 o 30). Por defecto 30.
 */
export async function getServicesUptime(
  days?: number
): Promise<ServiceUptime[]> {
  const params: Record<string, number> = {}
  if (days !== undefined) params.days = days

  const response = await apiClient.get<ServiceUptime[]>(
    '/system-status/services',
    { params }
  )
  return response.data
}

/**
 * Disparar una recolección manual de métricas.
 *
 * Retorna el snapshot generado por la recolección.
 * Lanza error HTTP 409 si ya hay una recolección en curso.
 */
export async function triggerCollection(): Promise<StatusSnapshot> {
  const response = await apiClient.post<StatusSnapshot>(
    '/system-status/collect'
  )
  return response.data
}

/**
 * Obtener las alertas activas basadas en el último snapshot.
 *
 * Retorna lista vacía si no hay snapshots o no hay umbrales excedidos.
 */
export async function getActiveAlerts(): Promise<Alert[]> {
  const response = await apiClient.get<Alert[]>(
    '/system-status/alerts'
  )
  return response.data
}
